// NVIDIA DLSS (DLAA and Super Resolution) through NVIDIA Streamline, in place of FSR 1 on the
// present path (gfx_present.c present_image): TOTK_UPSCALER=dlss, TOTK_DLSS_MODE=dlaa|quality|
// performance|ultra. RTX only. Streamline is loaded at run time from sl.interposer.dll; its
// plugins (sl.common.dll, sl.dlss.dll) and nvngx_dlss.dll sit next to it. None of NVIDIA's files
// is part of this project: the player puts the four DLLs of NVIDIA's Streamline SDK (bin/x64) in
// upscalers\streamline next to the executable, or names their folder in TOTK_DLSS_DIR. Nothing is
// linked. Streamline has to see vkCreateInstance / vkCreateDevice and the rest of the Vulkan
// calls, so with DLSS selected at start-up the loader functions come from its vkGetInstanceProcAddr
// (vk_dlss_preinit, called by vk_device.c before the instance is created, then every vulkan-1
// import of the executable is re-resolved through it, see vk_dlss_iat_patch). Choosing DLSS later
// takes effect at the next start.
//
// The chain the game feeds the present is display-encoded (the swapchain is UNORM over an SRGB
// colorspace): DLSS wants linear light, so dlss_in decodes the crop into an RGBA16F image, SL's
// DLSS reads it (tagged scalingInputColor), and dlss_out encodes SL's RGBA16F result into an RGBA8
// image the 1:1 blit puts into the swapchain (blit maps the named channels red to red, whatever
// the swapchain's order is).
//
// The game exposes no motion vectors or depth: a zero MV image and a far-plane depth image are
// tagged instead, which DLSS documents as its worst case: temporal accumulation without
// reprojection, a static or slowly panning camera looks right, fast pans smear. This is Engage's
// shape (turn-based), and DLAA at the game's own resolution is the main use.
//
// MIT Streamline headers: runtime/third_party/streamline/include (NVIDIA's, copied from the
// fefw-recomp integration, which also documents the DLL layout and the signature check).
extern "C" {
#include "vk.h"
}

#include <windows.h>

#include <csetjmp>
#include <cstdio>
#include <cwchar>
#include <string>

#include <sl.h>
#include <sl_consts.h>
#include <sl_dlss.h>
#include <sl_helpers_vk.h>
#include <sl_security.h>

extern "C" {
#include "cfg.h"
#include "dlss_in_spv.h"
#include "dlss_out_spv.h"
#include "host.h"
#include "nvn_api.h"
#include "platform/platform.h"
}

#include <psapi.h>

#define SLOTS 8

namespace {

struct Sl {
    HMODULE mod = nullptr;
    bool started = false;
    PFun_slInit *init = nullptr;
    PFun_slIsFeatureSupported *supported = nullptr;
    PFun_slGetNewFrameToken *token = nullptr;
    PFun_slSetConstants *constants = nullptr;
    PFun_slSetTagForFrame *tag = nullptr;
    PFun_slEvaluateFeature *evaluate = nullptr;
    PFun_slGetFeatureFunction *feature_fn = nullptr;
    PFun_slShutdown *shutdown = nullptr;
    PFN_vkGetInstanceProcAddr gipa = nullptr;
    PFN_vkGetDeviceProcAddr gdpa = nullptr;
    PFun_slDLSSSetOptions *set_options = nullptr;
    PFun_slDLSSGetOptimalSettings *optimal = nullptr;
    // the present bookkeeping pair the interposer would call; resolved from sl.common.dll lazily
    int (*hook_present)(VkQueue, const VkPresentInfoKHR *, bool &) = nullptr;
    int (*hook_after_present)() = nullptr;
    int hooks_tried = 0;
};

Sl &sl_state() {
    static Sl s;
    return s;
}

constexpr const wchar_t *kRequired[] = {L"sl.interposer.dll", L"sl.common.dll", L"sl.dlss.dll", L"nvngx_dlss.dll"};

bool exists(const std::wstring &p) { return GetFileAttributesW(p.c_str()) != INVALID_FILE_ATTRIBUTES; }

std::string narrow(const std::wstring &w) {
    char buf[1024];
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, buf, sizeof buf, nullptr, nullptr);
    return buf;
}

// The folder holding sl.interposer.dll: TOTK_DLSS_DIR (a folder, or the path of sl.interposer.dll
// or any file in it); unset: upscalers\streamline next to the executable, else in the run folder
// (the working directory), else the executable's own folder.
std::wstring sl_dir() {
    std::wstring p;
    {
        char a[MAX_PATH];
        if (plat_getenv("TOTK_DLSS_DIR", a, sizeof a) && a[0]) {
            int n = MultiByteToWideChar(CP_UTF8, 0, a, -1, nullptr, 0);
            std::wstring w((size_t)n, L'\0');
            MultiByteToWideChar(CP_UTF8, 0, a, -1, w.data(), n);
            if (!w.empty() && w.back() == L'\0') w.pop_back();
            p = w;
        }
    }
    if (p.empty()) {
        wchar_t buf[MAX_PATH];
        const DWORD n = GetModuleFileNameW(nullptr, buf, MAX_PATH);
        std::wstring exe(buf, n);
        const size_t s = exe.find_last_of(L"\\/");
        const std::wstring dir = s == std::wstring::npos ? std::wstring() : exe.substr(0, s + 1);
        wchar_t cwd[MAX_PATH];
        const DWORD cn = GetCurrentDirectoryW(MAX_PATH, cwd);
        std::wstring run(cwd, cn);
        if (!run.empty() && run.back() != L'\\') run += L'\\';
        for (const std::wstring &base : {dir, run}) {
            if (base.empty()) continue;
            const std::wstring pkg = base + L"upscalers\\streamline\\";
            if (exists(pkg + L"sl.interposer.dll")) return pkg;
        }
        return dir;
    }
    const DWORD a = GetFileAttributesW(p.c_str());
    if (a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY))
        return p.back() == L'\\' || p.back() == L'/' ? p : p + L"\\";
    const size_t s = p.find_last_of(L"\\/");
    return s == std::wstring::npos ? std::wstring() : p.substr(0, s + 1);
}

void on_log(sl::LogType type, const char *msg) {
    std::string m = msg ? msg : "";
    while (!m.empty() && (m.back() == '\n' || m.back() == '\r')) m.pop_back();
    if (!m.empty()) rt_log("sl: %c %s", type == sl::LogType::eError ? 'E' : type == sl::LogType::eWarn ? 'W' : 'I', m.c_str());
}

sl::Resource resource(VkImage image, VkImageView view, uint32_t usage, VkFormat fmt, uint32_t w, uint32_t h) {
    sl::Resource r(sl::ResourceType::eTex2d, reinterpret_cast<void *>(image), nullptr, reinterpret_cast<void *>(view),
                   static_cast<uint32_t>(VK_IMAGE_LAYOUT_GENERAL));
    r.width = w;
    r.height = h;
    r.nativeFormat = static_cast<uint32_t>(fmt);
    r.mipLevels = 1;
    r.arrayLayers = 1;
    r.flags = 0;
    r.usage = usage;
    return r;
}

}  // namespace

// ---- the escape guard, kept from the direct-NGX version: a faulting first-chance exception
// inside sl.interposer/its plugins during init jumps back out instead of taking the game down.
static jmp_buf g_sl_escape;
static volatile int g_sl_guard;
static void *g_sl_lo, *g_sl_hi;

static long __stdcall sl_escape_handler(EXCEPTION_POINTERS *e) {
    void *rip = e->ExceptionRecord->ExceptionAddress;
    if (g_sl_guard && (e->ExceptionRecord->ExceptionCode == 0xC0000005 ||
                       e->ExceptionRecord->ExceptionCode == 0xC0000409) &&
        rip >= g_sl_lo && rip < g_sl_hi) {
        g_sl_guard = 0;
        longjmp(g_sl_escape, 1);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

static void sl_range(void) {
    g_sl_lo = g_sl_hi = NULL;
    HMODULE mods[6];
    DWORD need = 0;
    int n = 0;
    if (EnumProcessModules(GetCurrentProcess(), mods, sizeof mods, &need))
        for (unsigned i = 0; i < sizeof mods / sizeof mods[0] && i < need / sizeof mods[0]; i++) {
            wchar_t name[MAX_PATH];
            if (!mods[i] || !GetModuleFileNameW(mods[i], name, MAX_PATH)) continue;
            const wchar_t *base = wcsrchr(name, L'\\');
            base = base ? base + 1 : name;
            if (wcsncmp(base, L"sl.", 3) && wcsncmp(base, L"nvngx", 5)) continue;
            IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)mods[i];
            if (dos->e_magic != IMAGE_DOS_SIGNATURE) continue;
            IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)((char *)mods[i] + dos->e_lfanew);
            char *lo = (char *)mods[i], *hi = lo + nt->OptionalHeader.SizeOfImage;
            if (!g_sl_lo || lo < g_sl_lo) g_sl_lo = lo;
            if (!g_sl_hi || hi > g_sl_hi) g_sl_hi = hi;
            n++;
        }
    (void)n;
}

// Called by vk_device.c right after the device exists: loads Streamline (slInit), then hands the
// real handles over with slSetVulkanInfo — no loader routing, the interposer's proxies break this
// port's guest threads. Everything happens here so the NGX context sees the device when the DLSS
// plugin starts.
void vk_dlss_set_device(VkInstance inst, VkPhysicalDevice phys, VkDevice dev, unsigned gfx_family, unsigned gfx_index) {
    if (strcmp(cfg_value("TOTK_UPSCALER"), "dlss")) return;
    Sl &s = sl_state();
    const std::wstring dir = sl_dir();
    const std::wstring dll = dir + L"sl.interposer.dll";
    if (!exists(dll)) {
        rt_log("vk: DLSS selected but %s is missing: put the Streamline DLLs (sl.interposer.dll, sl.common.dll, "
               "sl.dlss.dll, nvngx_dlss.dll) in upscalers\\streamline next to the game, or name their folder in "
               "TOTK_DLSS_DIR; FSR keeps the present",
               narrow(dll).c_str());
        return;
    }
    std::string missing;
    for (const wchar_t *f : kRequired)
        if (!exists(dir + f)) missing += (missing.empty() ? "" : ", ") + narrow(f);
    if (!missing.empty()) {
        rt_log("vk: DLSS selected but %s lacks %s: copy all four Streamline files there; FSR keeps the present",
               narrow(dir).c_str(), missing.c_str());
        return;
    }
    if (!sl::security::verifyEmbeddedSignature(dll.c_str())) {
        rt_log("vk: %s has no valid NVIDIA signature: not loaded", narrow(dll).c_str());
        return;
    }
    s.mod = LoadLibraryW(dll.c_str());
    if (!s.mod) {
        rt_log("vk: LoadLibrary(%s) failed (error %lu)", narrow(dll).c_str(), GetLastError());
        return;
    }
    auto get = [&](const char *n) { return reinterpret_cast<void *>(GetProcAddress(s.mod, n)); };
    s.init = reinterpret_cast<PFun_slInit *>(get("slInit"));
    s.supported = reinterpret_cast<PFun_slIsFeatureSupported *>(get("slIsFeatureSupported"));
    s.token = reinterpret_cast<PFun_slGetNewFrameToken *>(get("slGetNewFrameToken"));
    s.constants = reinterpret_cast<PFun_slSetConstants *>(get("slSetConstants"));
    s.tag = reinterpret_cast<PFun_slSetTagForFrame *>(get("slSetTagForFrame"));
    s.evaluate = reinterpret_cast<PFun_slEvaluateFeature *>(get("slEvaluateFeature"));
    s.feature_fn = reinterpret_cast<PFun_slGetFeatureFunction *>(get("slGetFeatureFunction"));
    s.shutdown = reinterpret_cast<PFun_slShutdown *>(get("slShutdown"));
    if (!s.init || !s.supported || !s.token || !s.constants || !s.tag || !s.evaluate || !s.feature_fn) {
        rt_log("vk: sl.interposer.dll lacks the Streamline API");
        return;
    }
    static const wchar_t *paths[1];
    static std::wstring plugin_dir;
    plugin_dir = dir;
    paths[0] = plugin_dir.c_str();
    static const sl::Feature features[] = {sl::kFeatureDLSS};
    sl::Preferences pref;
    pref.showConsole = false;
    pref.logLevel = sl::LogLevel::eDefault;
    pref.pathsToPlugins = paths;
    pref.numPathsToPlugins = 1;
    pref.pathToLogsAndData = nullptr;
    pref.logMessageCallback = &on_log;
    // no over-the-air downloads; the host restores no command buffer state (the present rebinds everything after)
    pref.flags = sl::PreferenceFlags::eDisableCLStateTracking | sl::PreferenceFlags::eUseFrameBasedResourceTagging;
    pref.featuresToLoad = features;
    pref.numFeaturesToLoad = 1;
    pref.engine = sl::EngineType::eCustom;
    pref.engineVersion = "1.0";
    pref.projectId = "5a1f0c2e-8f3b-4e61-9d4c-7b2e6a90c3d5";
    pref.renderAPI = sl::RenderAPI::eVulkan;
    sl_range();
    void *veh = AddVectoredExceptionHandler(1, sl_escape_handler);
    g_sl_guard = 1;
    sl::Result r = sl::Result::eErrorDriverOutOfDate;
    int escaped = 0;
    if (setjmp(g_sl_escape) == 0)
        r = s.init(pref, sl::kSDKVersion);
    else
        escaped = 1;
    g_sl_guard = 0;
    if (veh) RemoveVectoredExceptionHandler(veh);
    if (r != sl::Result::eOk) {
        if (escaped)
            rt_log("vk: Streamline init crashed (guarded); DLSS stays off this session, FSR keeps the present");
        else
            rt_log("vk: slInit failed (%d): DLSS off", (int)r);
        return;
    }
    auto set_info = reinterpret_cast<PFun_slSetVulkanInfo *>(GetProcAddress(s.mod, "slSetVulkanInfo"));
    if (!set_info) {
        rt_log("vk: DLSS off: sl.interposer.dll has no slSetVulkanInfo");
        return;
    }
    sl::VulkanInfo info;
    info.device = dev;
    info.instance = inst;
    info.physicalDevice = phys;
    info.graphicsQueueFamily = gfx_family;
    info.graphicsQueueIndex = gfx_index;
    info.computeQueueFamily = gfx_family;
    info.computeQueueIndex = gfx_index;
    info.opticalFlowQueueFamily = gfx_family;
    info.opticalFlowQueueIndex = gfx_index;
    r = set_info(info);
    if (r != sl::Result::eOk) {
        rt_log("vk: slSetVulkanInfo failed (%d): DLSS off", (int)r);
        return;
    }
    s.started = true;
    rt_log("vk: Streamline %d.%d.%d started with the device (family %u, index %u), no interposer hooks",
           SL_VERSION_MAJOR, SL_VERSION_MINOR, SL_VERSION_PATCH, gfx_family, gfx_index);
}

// ---- (the interposer-hook mode was removed: its proxies break this port's guest threads)
void vk_dlss_iat_patch(void *inst, void *dev) { (void)inst, (void)dev; }

// ---- the rest is the present chain: our decode/encode passes, the images, the per-slot source views.
static struct {
    int tried, ok, pipelines;
    PFN_vkCmdPushDescriptorSetKHR push;   // VK_KHR_push_descriptor: no loader export, resolved per device
    VkDescriptorSetLayout dsl;
    VkPipelineLayout layout;
    VkPipeline decode, encode;
    VkSampler sampler;
    VkImage lin, out, mv, depth, swp;
    VmaAllocation lin_a, out_a, mv_a, depth_a, swp_a;
    VkImageView lin_v, out_v, mv_v, depth_v, swp_v;
    VkImageView src_view[SLOTS];
    uint32_t lw, lh, ow2, oh2;
    int logged;
    sl::DLSSMode mode;
    uint32_t mow, moh;
    int reset;
} D;

static void barrier(VkCommandBuffer cb, VkImage img, VkImageLayout from, VkImageLayout to, VkPipelineStageFlags2 ss,
                    VkAccessFlags2 sa, VkPipelineStageFlags2 ds, VkAccessFlags2 da) {
    VkImageMemoryBarrier2 b = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2, .srcStageMask = ss, .srcAccessMask = sa,
                               .dstStageMask = ds, .dstAccessMask = da, .oldLayout = from, .newLayout = to,
                               .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                               .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = img,
                               .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    VkDependencyInfo d = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .imageMemoryBarrierCount = 1,
                          .pImageMemoryBarriers = &b};
    vkCmdPipelineBarrier2(cb, &d);
}

static void free_images(VkCtx *c) {
    VkImageView *views[] = {&D.lin_v, &D.out_v, &D.mv_v, &D.depth_v, &D.swp_v};
    VkImage *imgs[] = {&D.lin, &D.out, &D.mv, &D.depth, &D.swp};
    VmaAllocation *allocs[] = {&D.lin_a, &D.out_a, &D.mv_a, &D.depth_a, &D.swp_a};
    for (size_t i = 0; i < 5; i++) {
        if (*views[i]) vkDestroyImageView(c->device, *views[i], NULL);
        if (*imgs[i]) vmaDestroyImage(c->vma, *imgs[i], *allocs[i]);
        *views[i] = VK_NULL_HANDLE;
        *imgs[i] = VK_NULL_HANDLE;
    }
    D.lw = D.lh = D.ow2 = D.oh2 = 0;
}

static int make_image(VkCtx *c, VkFormat fmt, uint32_t w, uint32_t h, VkImageUsageFlags usage, VkImage *img,
                      VmaAllocation *alloc, VkImageView *view) {
    VkImageCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = fmt,
                            .extent = {w, h, 1}, .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
                            .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = usage};
    VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (vmaCreateImage(c->vma, &ci, &ai, img, alloc, NULL) != VK_SUCCESS) return 0;
    VkImageViewCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = *img,
                                .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = fmt,
                                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    if (vkCreateImageView(c->device, &vi, NULL, view) != VK_SUCCESS) return 0;
    return 1;
}

static int ensure_images(VkCtx *c, uint32_t iw, uint32_t ih, uint32_t ow, uint32_t oh) {
    if (D.lin && D.lw == iw && D.lh == ih && D.ow2 == ow && D.oh2 == oh) return 1;
    vk_queue_lock();
    vkDeviceWaitIdle(c->device);
    vk_queue_unlock();
    free_images(c);
    if (!make_image(c, VK_FORMAT_R16G16B16A16_SFLOAT, iw, ih,
                    VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, &D.lin, &D.lin_a, &D.lin_v) ||
        !make_image(c, VK_FORMAT_R16G16B16A16_SFLOAT, ow, oh,
                    VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, &D.out, &D.out_a, &D.out_v) ||
        !make_image(c, VK_FORMAT_R16G16_SFLOAT, iw, ih,
                    VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, &D.mv, &D.mv_a, &D.mv_v) ||
        !make_image(c, VK_FORMAT_R32_SFLOAT, iw, ih,
                    VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, &D.depth, &D.depth_a, &D.depth_v) ||
        !make_image(c, VK_FORMAT_R8G8B8A8_UNORM, ow, oh,
                    VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, &D.swp, &D.swp_a, &D.swp_v)) {
        free_images(c);
        rt_log("vk: DLSS off: its %ux%u -> %ux%u images could not be created", iw, ih, ow, oh);
        return 0;
    }
    D.lw = iw, D.lh = ih, D.ow2 = ow, D.oh2 = oh;
    return 1;
}

static void bind_pass(VkCommandBuffer cb, VkPipeline p, VkImageView in, VkImageView out) {
    VkDescriptorImageInfo ii = {D.sampler, in, VK_IMAGE_LAYOUT_GENERAL}, oi = {VK_NULL_HANDLE, out, VK_IMAGE_LAYOUT_GENERAL};
    VkWriteDescriptorSet w[2] = {
        {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1,
         .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &ii},
        {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1,
         .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &oi}};
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, p);
    D.push(cb, VK_PIPELINE_BIND_POINT_COMPUTE, D.layout, 0, 2, w);
}

static VkPipeline make_pipeline(VkCtx *c, const uint32_t *code, size_t size) {
    VkShaderModuleCreateInfo mi = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = size, .pCode = code};
    VkShaderModule m = VK_NULL_HANDLE;
    if (vkCreateShaderModule(c->device, &mi, NULL, &m) != VK_SUCCESS) return VK_NULL_HANDLE;
    VkComputePipelineCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
                                      .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
                                                .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main"},
                                      .layout = D.layout};
    VkPipeline p = VK_NULL_HANDLE;
    if (vkCreateComputePipelines(c->device, VK_NULL_HANDLE, 1, &ci, NULL, &p) != VK_SUCCESS) p = VK_NULL_HANDLE;
    vkDestroyShaderModule(c->device, m, NULL);
    return p;
}

static int init_pipelines(VkCtx *c) {
    D.push = (PFN_vkCmdPushDescriptorSetKHR)vkGetDeviceProcAddr(c->device, "vkCmdPushDescriptorSetKHR");
    if (!D.push) {
        rt_log("vk: DLSS off: no VK_KHR_push_descriptor; FSR stays");
        return 0;
    }
    VkDescriptorSetLayoutBinding b[2] = {
        {.binding = 0, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .descriptorCount = 1,
         .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT},
        {.binding = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .descriptorCount = 1,
         .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT}};
    VkDescriptorSetLayoutCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
                                           .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR,
                                           .bindingCount = 2, .pBindings = b};
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 16};
    VkPipelineLayoutCreateInfo li = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1,
                                     .pSetLayouts = &D.dsl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr};
    VkSamplerCreateInfo si = {.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_NEAREST,
                              .minFilter = VK_FILTER_NEAREST, .mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST,
                              .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
                              .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
                              .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .maxLod = 0};
    if (vkCreateDescriptorSetLayout(c->device, &dci, NULL, &D.dsl) != VK_SUCCESS ||
        vkCreatePipelineLayout(c->device, &li, NULL, &D.layout) != VK_SUCCESS ||
        vkCreateSampler(c->device, &si, NULL, &D.sampler) != VK_SUCCESS ||
        !(D.decode = make_pipeline(c, dlss_in_spv, sizeof dlss_in_spv)) ||
        !(D.encode = make_pipeline(c, dlss_out_spv, sizeof dlss_out_spv))) {
        rt_log("vk: DLSS off: its pipelines could not be created; FSR stays");
        return 0;
    }
    return 1;
}

static sl::DLSSMode mode_of(const char *m) {
    if (!strcmp(m, "quality")) return sl::DLSSMode::eMaxQuality;
    if (!strcmp(m, "performance")) return sl::DLSSMode::eMaxPerformance;
    if (!strcmp(m, "ultra")) return sl::DLSSMode::eUltraPerformance;
    return sl::DLSSMode::eDLAA;
}

static bool fail(const char *what, int code = -1) {
    rt_log("vk: DLSS %s failed (%d): off this session, FSR keeps the present", what, code);
    return false;
}

int vk_dlss_record(VkCommandBuffer cb, unsigned slot, VkImage src, VkFormat fmt, int sw, int sh, const int crop[4],
                   VkImage dst, const int out[4], VkFormat dstfmt) {
    (void)sw, (void)sh, (void)dstfmt;
    Sl &s = sl_state();
    int cw = crop[2], ch = crop[3];
    uint32_t dw = (uint32_t)out[2], dh = (uint32_t)out[3];
    if (rt_game_id != 1 || strcmp(cfg_value("TOTK_UPSCALER"), "dlss") || !fmt) return 0;
    if (!s.started) return 0;
    VkCtx *c = vk_ctx();
    if (!D.tried) {
        D.tried = 1;
        sl::AdapterInfo ai;
        ai.vkPhysicalDevice = reinterpret_cast<void *>(c->phys);
        const sl::Result sup = s.supported(sl::kFeatureDLSS, ai);
        if (sup != sl::Result::eOk) {
            rt_log("vk: DLSS is not supported on this GPU / driver (slIsFeatureSupported %d)", (int)sup);
            return 0;
        }
        void *so = nullptr, *os = nullptr;
        if (s.feature_fn(sl::kFeatureDLSS, "slDLSSSetOptions", so) != sl::Result::eOk || !so ||
            s.feature_fn(sl::kFeatureDLSS, "slDLSSGetOptimalSettings", os) != sl::Result::eOk || !os) {
            rt_log("vk: the DLSS plugin functions are missing");
            return 0;
        }
        s.set_options = reinterpret_cast<PFun_slDLSSSetOptions *>(so);
        s.optimal = reinterpret_cast<PFun_slDLSSGetOptimalSettings *>(os);
        D.ok = 1;
        rt_log("vk: DLSS available (Streamline)");
    }
    if (!D.ok) return 0;
    if (!D.pipelines) {
        if (!init_pipelines(c)) {
            D.tried = -1;
            return 0;
        }
        D.pipelines = 1;
    }
    sl::DLSSMode m = mode_of(cfg_value("TOTK_DLSS_MODE"));
    uint32_t iw = (uint32_t)cw, ih = (uint32_t)ch;
    uint32_t ow = iw, oh = ih;
    if (dw > iw || dh > ih) {   // the window is larger than the picture: the mode's ratio, capped by the window
        double ratio = m == sl::DLSSMode::eMaxQuality ? 1.5 : m == sl::DLSSMode::eMaxPerformance ? 2.0
                                             : m == sl::DLSSMode::eUltraPerformance ? 3.0 : 1.0;
        ow = (uint32_t)(iw * ratio + 0.5);
        oh = (uint32_t)(ih * ratio + 0.5);
        ow = ow > dw ? dw : ow;
        oh = oh > dh ? dh : oh;
    }
    if (!ensure_images(c, iw, ih, ow, oh)) return 0;
    slot %= SLOTS;
    if (D.src_view[slot]) vkDestroyImageView(c->device, D.src_view[slot], NULL);
    VkImageViewCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = src,
                                .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = fmt,
                                .components = {VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY,
                                               VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_ONE},
                                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    if (vkCreateImageView(c->device, &vi, NULL, &D.src_view[slot]) != VK_SUCCESS) {
        D.src_view[slot] = VK_NULL_HANDLE;
        return 0;
    }
    // a fresh token every frame (slGetNewFrameToken with no frame index), then the mode's options
    // whenever the sizes or the mode change
    sl::FrameToken *frame = nullptr;
    if (s.token(reinterpret_cast<sl::FrameToken *&>(frame), nullptr) != sl::Result::eOk || !frame)
        return fail("slGetNewFrameToken");
    if (m != D.mode || ow != D.mow || oh != D.moh) {
        static int opt_once;
        if (!opt_once++) rt_log("vk: DLSS: applying options mode %d, %ux%u -> %ux%u", (int)m, iw, ih, ow, oh);
        sl::DLSSOptions o;
        o.mode = m;
        o.outputWidth = ow;
        o.outputHeight = oh;
        o.colorBuffersHDR = sl::Boolean::eTrue;     // our chain hands DLSS linear light
        o.useAutoExposure = sl::Boolean::eTrue;
        if (s.set_options(sl::ViewportHandle(0), o) != sl::Result::eOk) return fail("slDLSSSetOptions");
        sl::DLSSOptimalSettings os;
        if (s.optimal(o, os) == sl::Result::eOk && os.optimalRenderWidth)
            rt_log("vk: DLSS %ux%u -> %ux%u, mode %d (optimal render %ux%u, range %ux%u .. %ux%u)", iw, ih, ow, oh, (int)m,
                   os.optimalRenderWidth, os.optimalRenderHeight, os.renderWidthMin, os.renderHeightMin, os.renderWidthMax,
                   os.renderHeightMax);
        else
            rt_log("vk: DLSS %ux%u -> %ux%u, mode %d", iw, ih, ow, oh, (int)m);
        D.mode = m, D.mow = ow, D.moh = oh;
    }
    if (!D.logged) {
        D.logged = 1;
        rt_log("vk: DLSS upscales %dx%d to %ux%u (no motion vectors: zero MV, far-plane depth)", iw, ih, ow, oh);
    }
    const VkPipelineStageFlags2 CS = VK_PIPELINE_STAGE_2_COMPUTE_SHADER_BIT, XF = VK_PIPELINE_STAGE_2_TRANSFER_BIT;
    // the game's writes to the source become visible to the compute read; the earlier frame's reads of the
    // intermediates finish before this frame writes them
    barrier(cb, src, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT,
            VK_ACCESS_2_MEMORY_WRITE_BIT, CS, VK_ACCESS_2_SHADER_SAMPLED_READ_BIT);
    VkImage imgs_pre[4] = {D.lin, D.mv, D.depth, D.swp};
    for (int i = 0; i < 4; i++)
        barrier(cb, imgs_pre[i], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, CS | XF, 0, CS,
                VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT | VK_ACCESS_2_SHADER_SAMPLED_READ_BIT);
    // the zero MVs and the far-plane depth, cleared every frame (their contents are not kept)
    VkClearColorValue clear_zero = {.float32 = {0, 0, 0, 0}}, clear_far = {.float32 = {1, 0, 0, 0}};
    VkImageSubresourceRange all = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdClearColorImage(cb, D.mv, VK_IMAGE_LAYOUT_GENERAL, &clear_zero, 1, &all);
    vkCmdClearColorImage(cb, D.depth, VK_IMAGE_LAYOUT_GENERAL, &clear_far, 1, &all);
    barrier(cb, D.mv, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, XF, VK_ACCESS_2_TRANSFER_WRITE_BIT,
            VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, VK_ACCESS_2_MEMORY_READ_BIT);
    barrier(cb, D.depth, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, XF, VK_ACCESS_2_TRANSFER_WRITE_BIT,
            VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, VK_ACCESS_2_MEMORY_READ_BIT);

    // 1. decode: the crop, display-encoded, into linear light
    int32_t pc_in[4] = {crop[0], crop[1], cw, ch};
    bind_pass(cb, D.decode, D.src_view[slot], D.lin_v);
    vkCmdPushConstants(cb, D.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, 16, pc_in);
    vkCmdDispatch(cb, (iw + 7) / 8, (ih + 7) / 8, 1);
    barrier(cb, D.lin, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, CS, VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT,
            VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, VK_ACCESS_2_MEMORY_READ_BIT);

    // 2. DLSS through Streamline: default-constructed constants (the game exposes no camera data),
    // zero jitter, no motion vectors
    sl::Constants cst;
    for (int i = 0; i < 4; i++) {
        cst.cameraViewToClip.setRow(i, sl::float4(i == 0 ? 1.0f : 0.0f, i == 1 ? 1.0f : 0.0f, i == 2 ? 1.0f : 0.0f, i == 3 ? 1.0f : 0.0f));
        cst.clipToCameraView.setRow(i, sl::float4(i == 0 ? 1.0f : 0.0f, i == 1 ? 1.0f : 0.0f, i == 2 ? 1.0f : 0.0f, i == 3 ? 1.0f : 0.0f));
        cst.clipToLensClip.setRow(i, sl::float4(i == 0 ? 1.0f : 0.0f, i == 1 ? 1.0f : 0.0f, i == 2 ? 1.0f : 0.0f, i == 3 ? 1.0f : 0.0f));
        cst.clipToPrevClip.setRow(i, sl::float4(i == 0 ? 1.0f : 0.0f, i == 1 ? 1.0f : 0.0f, i == 2 ? 1.0f : 0.0f, i == 3 ? 1.0f : 0.0f));
        cst.prevClipToClip.setRow(i, sl::float4(i == 0 ? 1.0f : 0.0f, i == 1 ? 1.0f : 0.0f, i == 2 ? 1.0f : 0.0f, i == 3 ? 1.0f : 0.0f));
    }
    cst.jitterOffset = sl::float2(0.0f, 0.0f);
    cst.mvecScale = sl::float2(1.0f, 1.0f);
    cst.motionVectorsInvalidValue = -2.0f;   // SL validates it (our MVs are all-valid zeros)
    cst.cameraPinholeOffset = sl::float2(0.0f, 0.0f);
    cst.cameraPos = sl::float3(0.0f, 0.0f, 0.0f);
    cst.cameraUp = sl::float3(0.0f, 1.0f, 0.0f);
    cst.cameraRight = sl::float3(1.0f, 0.0f, 0.0f);
    cst.cameraFwd = sl::float3(0.0f, 0.0f, 1.0f);
    cst.cameraNear = 0.05f;
    cst.cameraFar = 1000.0f;
    cst.cameraFOV = 1.0f;
    cst.cameraAspectRatio = (float)iw / (float)ih;
    cst.depthInverted = sl::Boolean::eFalse;
    cst.cameraMotionIncluded = sl::Boolean::eFalse;
    cst.motionVectors3D = sl::Boolean::eFalse;
    cst.reset = D.reset ? sl::Boolean::eTrue : sl::Boolean::eFalse;
    cst.motionVectorsJittered = sl::Boolean::eFalse;
    D.reset = 0;
    if (s.constants(cst, *frame, sl::ViewportHandle(0)) != sl::Result::eOk) return fail("slSetConstants");
    uint32_t usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_STORAGE_BIT;
    sl::Resource col = resource(D.lin, D.lin_v, usage, VK_FORMAT_R16G16B16A16_SFLOAT, iw, ih),
                 dep = resource(D.depth, D.depth_v, VK_IMAGE_USAGE_SAMPLED_BIT, VK_FORMAT_R32_SFLOAT, iw, ih),
                 mv = resource(D.mv, D.mv_v, VK_IMAGE_USAGE_SAMPLED_BIT, VK_FORMAT_R16G16_SFLOAT, iw, ih),
                 out_res = resource(D.out, D.out_v, usage, VK_FORMAT_R16G16B16A16_SFLOAT, ow, oh);
    const sl::Extent in_ext{0, 0, iw, ih}, out_ext{0, 0, ow, oh};
    sl::ResourceTag tags[4] = {sl::ResourceTag(&col, sl::kBufferTypeScalingInputColor, sl::ResourceLifecycle::eValidUntilPresent, &in_ext),
                               sl::ResourceTag(&dep, sl::kBufferTypeDepth, sl::ResourceLifecycle::eValidUntilPresent, &in_ext),
                               sl::ResourceTag(&mv, sl::kBufferTypeMotionVectors, sl::ResourceLifecycle::eValidUntilPresent, &in_ext),
                               sl::ResourceTag(&out_res, sl::kBufferTypeScalingOutputColor, sl::ResourceLifecycle::eValidUntilPresent, &out_ext)};
    auto *slcb = reinterpret_cast<sl::CommandBuffer *>(cb);
    if (s.tag(*frame, sl::ViewportHandle(0), tags, 4, slcb) != sl::Result::eOk) return fail("slSetTagForFrame");
    const sl::ViewportHandle vp(0);
    const sl::BaseStructure *inputs[] = {&vp};
    const sl::Result er = s.evaluate(sl::kFeatureDLSS, *frame, inputs, 1, slcb);
    if (er != sl::Result::eOk) return fail("slEvaluateFeature", (int)er);
    barrier(cb, D.out, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT,
            VK_ACCESS_2_MEMORY_WRITE_BIT, CS, VK_ACCESS_2_SHADER_SAMPLED_READ_BIT);

    // 3. encode into RGBA8, then the 1:1 blit into the swapchain
    int32_t pc_out[4] = {(int32_t)ow, (int32_t)oh, 0, 0};
    bind_pass(cb, D.encode, D.out_v, D.swp_v);
    vkCmdPushConstants(cb, D.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, 16, pc_out);
    vkCmdDispatch(cb, (ow + 7) / 8, (oh + 7) / 8, 1);
    barrier(cb, D.swp, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, CS, VK_ACCESS_2_SHADER_STORAGE_WRITE_BIT,
            XF, VK_ACCESS_2_TRANSFER_READ_BIT);
    barrier(cb, src, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, CS, 0, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, 0);
    VkImageBlit region = {.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                          .srcOffsets = {{0, 0, 0}, {(int)ow, (int)oh, 1}},
                          .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                          .dstOffsets = {{out[0], out[1], 0}, {out[0] + (int)ow, out[1] + (int)oh, 1}}};
    vkCmdBlitImage(cb, D.swp, VK_IMAGE_LAYOUT_GENERAL, dst, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region,
                   VK_FILTER_NEAREST);
    return 1;
}

// The present bookkeeping: SL's common plugin counts evaluates between presents and needs its
// presentCommon() every frame (otherwise internal bookkeeping and garbage collection never run).
// These two are exactly what the interposer's vkQueuePresentKHR calls; the host without loader
// routing calls them itself, around the real present.
int vk_dlss_present_before(VkQueue queue, const VkPresentInfoKHR *pi) {
    Sl &s = sl_state();
    if (!s.started) return 0;
    if (!s.hooks_tried) {
        s.hooks_tried = 1;
        HMODULE common = GetModuleHandleW(L"sl.common.dll");
        auto gpf = reinterpret_cast<void *(*)(const char *)>(common ? GetProcAddress(common, "slGetPluginFunction") : nullptr);
        if (gpf) {
            s.hook_present = reinterpret_cast<int (*)(VkQueue, const VkPresentInfoKHR *, bool &)>(gpf("slHookVkPresent"));
            s.hook_after_present = reinterpret_cast<int (*)()>(gpf("slHookVkAfterPresent"));
        }
        if (!s.hook_present || !s.hook_after_present) {
            s.hook_present = nullptr;
            s.hook_after_present = nullptr;
            rt_log("vk: DLSS: sl.common.dll has no present hooks; its per-frame bookkeeping stays off");
        }
    }
    if (!s.hook_present) return 0;
    bool skip = false;
    if (s.hook_present(queue, pi, skip) != VK_SUCCESS) return 0;
    return skip ? 0 : 1;
}

void vk_dlss_present_after(void) {
    Sl &s = sl_state();
    if (s.started && s.hook_after_present) s.hook_after_present();
}

void vk_dlss_release(void) {
    VkCtx *c = vk_ctx();
    Sl &s = sl_state();
    if (c && D.tried > 0) {
        free_images(c);
        if (D.decode) vkDestroyPipeline(c->device, D.decode, NULL);
        if (D.encode) vkDestroyPipeline(c->device, D.encode, NULL);
        if (D.sampler) vkDestroySampler(c->device, D.sampler, NULL);
        if (D.layout) vkDestroyPipelineLayout(c->device, D.layout, NULL);
        if (D.dsl) vkDestroyDescriptorSetLayout(c->device, D.dsl, NULL);
        for (int i = 0; i < SLOTS; i++)
            if (D.src_view[i]) {
                vkDestroyImageView(c->device, D.src_view[i], NULL);
                D.src_view[i] = VK_NULL_HANDLE;
            }
    }
    memset(&D, 0, sizeof D);
    if (s.started) {
        if (s.shutdown) {
            const sl::Result r = s.shutdown();
            if (r != sl::Result::eOk) rt_log("vk: slShutdown failed (%d)", (int)r);
        }
        s.started = false;
        if (s.mod) {
            FreeLibrary(s.mod);
            s.mod = nullptr;
        }
    }
}
