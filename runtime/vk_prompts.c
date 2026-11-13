// Keyboard-and-mouse prompt icons for Engage (TOTK_PROMPTS=pc, live).
//
// Engage draws every key prompt from one 256x256 sprite atlas (icon/button/button.bundle for the outline prompts, and
// icon/buttonoutline/button_filled.bundle for the solid ones). Each prompt is a sprite with a fixed rectangle in that
// atlas, so replacing the atlas's pixels replaces every prompt at once: no prefab, font or message is touched, and the
// game keeps its own sprite rectangles.
//
// Two things make the switch automatic:
//  - the atlases are recognised by content, not by path: an upload whose decoded pixels hash to the game's own
//    keyboard-prompt atlas is remembered as that atlas;
//  - the input source is tracked (last gamepad button or stick movement vs last key or mouse button), and when it
//    changes the remembered atlases are re-uploaded with the other picture. That happens in the next present, so the
//    prompts change while the game runs.
//
// The pictures come from tools/make_prompt_icons.py (runtime/prompt_icons.h): drawn here, at the game's own sprite
// rectangles, with letters from the project's font. No game art is in the repository.
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <zstd.h>

#include "cfg.h"
#include "gfx.h"
#include "host.h"
#include "prompt_icons.h"
#include "tex.h"
#include "vk.h"
#include "vk_prompts.h"

#define PROMPT_SIZE 256
#define PROMPT_BYTES (PROMPT_SIZE * PROMPT_SIZE * 4)

// The game's own atlases are recognised by their picture, not by a hash: the uploader deswizzles the storage's
// block-linear ASTC bytes before they are seen here, so no hash of the file's bytes could match. See find_atlas.

// One remembered atlas: where its pixels live and which picture it currently holds.
typedef struct {
    uint64_t addr;          // the texture's guest storage
    uint32_t width, height;
    int solid;              // which of the two drawn atlases belongs here
    int flip;               // 1: the game's picture is stored bottom-up, so ours is flipped to match
    int showing_pc;         // 1: our icons are in it, 0: the game's own
} Atlas;

static Atlas *atlases;
static size_t natlases, atlas_cap;

static uint8_t *pc_pictures[2];   // decoded RGBA8, index = solid
static int pc_ready;

static int using_pad = 1;         // the input source the prompts currently follow
static int switch_pending;        // the source changed: re-upload on the next present
static int traced;
// ---- pictures
static int decode_picture(const unsigned char *zstd, unsigned size, uint8_t **out) {
    uint8_t *rgba = malloc(PROMPT_BYTES);
    if (!rgba) return 0;
    size_t got = ZSTD_decompress(rgba, PROMPT_BYTES, zstd, size);
    if (ZSTD_isError(got) || got != PROMPT_BYTES) {
        free(rgba);
        return 0;
    }
    *out = rgba;
    return 1;
}

static void load_pictures(void) {
    if (pc_ready) return;
    pc_ready = 1;
    if (!decode_picture(prompt_pc_outline_zstd, prompt_pc_outline_zstd_size, &pc_pictures[0]) ||
        !decode_picture(prompt_pc_filled_zstd, prompt_pc_filled_zstd_size, &pc_pictures[1])) {
        free(pc_pictures[0]), free(pc_pictures[1]);
        pc_pictures[0] = pc_pictures[1] = NULL;
        rt_log("prompts: the keyboard-and-mouse icons could not be decoded; the game's own stay");
    }
}

// 0: the game's own prompts (prompts = switch); 1: follow the device in use (auto); 2: always the keyboard and mouse
// pictures (prompts = pc).
static int pc_mode_value(void) {
    if (!RT_ENGAGE) return 0;
    const char *v = cfg_value("TOTK_PROMPTS");
    if (!v || !*v || !strcmp(v, "auto")) return 1;
    if (!strcmp(v, "switch") || !strcmp(v, "gamepad")) return 0;
    return (!strcmp(v, "pc") || !strcmp(v, "keyboard")) ? 2 : 1;
}

static int pc_enabled(void) { return pc_mode_value() != 0; }

// The game's own atlases, recognised by a fingerprint of their picture. The uploader deswizzles the storage's
// block-linear ASTC bytes, so a hash of the file's bytes cannot match, and a loose test (ink coverage alone) also
// matched unrelated textures and replaced them. This test is:
//   - the alpha coverage falls in the narrow band measured on each set (outline 14.3 %, solid 48.3 % measured from
//     the decoded atlas; the atlas is white line art, so its alpha is the ink);
//   - every one of the 19 sprite cells carries ink, so it is a sheet of separate icons.
// A font page, a photo or a background fails the band or the cell test. (The corners are NOT empty: the atlas uses
// them, ZR sits at x=0.03, y=0.08, so a corner test would reject the real thing.)
static const struct { float x, y, w, h; } kCells[] = {
    {44.06f, 0.06f, 39.89f, 39.89f}, {0.06f, 44.06f, 39.89f, 39.89f}, {88.06f, 0.06f, 39.89f, 39.89f},
    {44.06f, 44.06f, 39.89f, 39.89f}, {44.08f, 132.08f, 39.85f, 35.90f}, {0.08f, 132.08f, 39.90f, 35.90f},
    {132.08f, 88.08f, 39.85f, 39.85f}, {0.03f, 0.08f, 39.95f, 39.90f}, {88.06f, 44.06f, 39.89f, 39.89f},
    {176.06f, 0.08f, 39.89f, 39.87f}, {176.08f, 88.08f, 37.85f, 37.85f}, {218.08f, 88.08f, 37.85f, 37.85f},
    {88.08f, 132.03f, 33.85f, 40.90f}, {44.06f, 88.06f, 39.89f, 39.89f}, {88.06f, 88.06f, 39.89f, 39.89f},
    {0.06f, 88.06f, 39.89f, 39.89f}, {132.06f, 0.06f, 39.89f, 39.89f}, {132.06f, 44.08f, 39.89f, 39.87f},
    {176.08f, 44.08f, 39.85f, 39.85f},
};

static double cell_ink(const uint8_t *rgba, int x0, int y0, int w, int h) {
    size_t ink = 0, n = 0;
    for (int y = y0; y < y0 + h; y++)
        for (int x = x0; x < x0 + w; x++) {
            if (x < 0 || y < 0 || x >= PROMPT_SIZE || y >= PROMPT_SIZE) continue;
            if (rgba[((size_t)y * PROMPT_SIZE + x) * 4 + 3] > 40) ink++;
            n++;
        }
    return n ? (double)ink / (double)n : 0.0;
}

static void find_atlas(uint64_t addr, const uint8_t *rgba, uint32_t w, uint32_t h) {
    if (w != PROMPT_SIZE || h != PROMPT_SIZE) return;
    size_t ink = 0;
    for (uint32_t i = 0; i < (size_t)w * h; i++)
        if (rgba[(size_t)i * 4 + 3] > 40) ink++;
    double cover = (double)ink / ((double)w * h);
    int solid;
    if (cover > 0.11 && cover < 0.19) solid = 0;          // the outline set: 14.3 % measured
    else if (cover > 0.42 && cover < 0.55) solid = 1;      // the solid set: 48.3 % measured
    else return;
    // every sprite cell must carry ink. The picture's row order is not assumed: the uploader's decode may hand the
    // image top-down or bottom-up, so the cells are tested in both orientations and the one that fits is kept.
    int flip = -1;
    for (int try_flip = 0; try_flip < 2 && flip < 0; try_flip++) {
        int ok = 1;
        for (size_t i = 0; i < sizeof kCells / sizeof *kCells && ok; i++) {
            const float *c = &kCells[i].x;
            int x0 = (int)c[0], cw = (int)c[2], ch = (int)c[3];
            int y0 = try_flip ? (int)c[1] : (int)(PROMPT_SIZE - c[1] - c[3]);
            if (cell_ink(rgba, x0, y0, cw, ch) < 0.04) ok = 0;
        }
        if (ok) flip = try_flip;
    }
    if (flip < 0) {
        static int traced_cells;
        if (traced_cells < 4) {
            traced_cells++;
            double a0 = cell_ink(rgba, 44, (int)(PROMPT_SIZE - 0.06 - 39.89), 39, 39);
            double b0 = cell_ink(rgba, 44, 0, 39, 39);
            rt_log("prompts: 256x256 at %#llx ink %.2f%% rejected: cell A is empty both ways (%.2f%%, %.2f%%)",
                   (unsigned long long)addr, cover * 100.0, a0 * 100.0, b0 * 100.0);
        }
        return;
    }
    for (size_t j = 0; j < natlases; j++)
        if (atlases[j].addr == addr) return;   // already known
    if (natlases == atlas_cap) {
        size_t cap = atlas_cap ? atlas_cap * 2 : 4;
        Atlas *grown = realloc(atlases, cap * sizeof *grown);
        if (!grown) return;
        atlases = grown, atlas_cap = cap;
    }
    atlases[natlases++] = (Atlas){addr, w, h, solid, flip, 0};
    rt_log("prompts: recognised the %s prompt atlas at %#llx (ink %.1f%%, %s, %zu known)",
           solid ? "solid" : "outline", (unsigned long long)addr, cover * 100.0,
           flip ? "stored bottom-up" : "stored top-down", natlases);
    switch_pending = 1;
}

// ---- the public surface (vk_texture.c, input.c, ui/menu.cpp)
void vk_prompt_icons_note_upload(uint64_t addr, const uint8_t *rgba, uint32_t w, uint32_t h) {
    if (!pc_enabled() || !rgba || w != PROMPT_SIZE || h != PROMPT_SIZE) return;
    static int probes;
    if (probes < 8) {
        probes++;
        size_t ink = 0;
        for (uint32_t i = 0; i < (size_t)w * h; i++)
            if (rgba[(size_t)i * 4 + 3] > 40) ink++;
        rt_log("prompts: 256x256 picture at %#llx, ink %.2f%% (bands 11-19 and 42-55)", (unsigned long long)addr,
               100.0 * (double)ink / ((double)w * h));
    }
    find_atlas(addr, rgba, w, h);
}

// Called by the texture uploader before it reads the storage: 1 when the picture to upload is ours, in *rgba.
int vk_prompt_icons_override(uint64_t addr, uint32_t w, uint32_t h, const uint8_t **rgba) {
    if (!pc_enabled() || w != PROMPT_SIZE || h != PROMPT_SIZE) return 0;
    for (size_t i = 0; i < natlases; i++) {
        if (atlases[i].addr != addr) continue;
        int mode = pc_mode_value();
        int want_pc = mode == 2 || (mode == 1 && !using_pad);
        if (!want_pc) {
            atlases[i].showing_pc = 0;
            return 0;                        // the game's own picture: let the storage through
        }
        load_pictures();
        if (!pc_pictures[atlases[i].solid]) return 0;
        atlases[i].showing_pc = 1;
        *rgba = pc_pictures[atlases[i].solid];
        static int hits;
        if (hits < 6) {
            hits++;
            rt_log("prompts: substituted our %s picture for the atlas at %#llx%s", atlases[i].solid ? "solid" : "outline",
                   (unsigned long long)addr, atlases[i].flip ? " (flipped)" : "");
        }
        return 1;
    }
    return 0;
}

// The uploader hands the picture over row by row, so a bottom-up atlas needs its rows reversed here.
void vk_prompt_icons_flip(uint64_t addr, uint8_t *rgba, uint32_t w, uint32_t h) {
    for (size_t i = 0; i < natlases; i++) {
        if (atlases[i].addr != addr || !atlases[i].flip) continue;
        size_t rb = (size_t)w * 4;
        uint8_t *row = malloc(rb);
        if (!row) return;
        for (uint32_t y = 0; y < h / 2; y++) {
            uint8_t *a = rgba + (size_t)y * rb, *b = rgba + (size_t)(h - 1 - y) * rb;
            memcpy(row, a, rb);
            memcpy(a, b, rb);
            memcpy(b, row, rb);
        }
        free(row);
        return;
    }
}

void vk_prompt_icons_note_source(int pad) {
    if (!pc_enabled()) return;
    int now = pad ? 1 : 0;
    if (now == using_pad) return;
    using_pad = now;
    switch_pending = 1;
}

// 1 in the frame the source changed and an atlas is on screen: the caller re-uploads those textures.
int vk_prompt_icons_take_switch(void) {
    if (!switch_pending || !natlases) return 0;
    switch_pending = 0;
    if (!traced) {
        traced = 1;
        rt_log("prompts: %zu atlases follow the input source", natlases);
    }
    return 1;
}

size_t vk_prompt_icons_addresses(uint64_t *out, size_t max) {
    size_t n = 0;
    for (size_t i = 0; i < natlases && n < max; i++) out[n++] = atlases[i].addr;
    return n;
}

void vk_prompt_icons_showing(uint64_t addr, int *pc) {
    for (size_t i = 0; i < natlases; i++)
        if (atlases[i].addr == addr) *pc = atlases[i].showing_pc;
}
