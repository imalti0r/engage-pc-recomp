## alpha.12 — sharper 4K: DLSS output sharpening, anisotropic filtering, texture detail

Three separate causes made a 4K picture look soft, and each is addressed here.

**1. DLSS output had no sharpening.** The FSR path ends with RCAS; the DLSS path ended with a plain
encode. DLSS now sharpens its own output with a contrast-adaptive unsharp mask, applied in
**display space** (in linear light a dark scene spans almost no local range, so a mask there does
nothing). The amount is the existing **Sharpness** setting, which now applies to both upscalers:
- in game: **F1 → Screen → Picture → Sharpness** (0–100 %);
- in the launcher: the **Sharpness** row.

**2. The game's samplers ask for little or no anisotropic filtering.** Engage was authored for a
720p-class handheld, so ground planes and floors seen at a shallow angle smear at 4K. A new
`aniso` setting puts a **floor** under every sampler's own value:

```ini
[display]
aniso = 16
```

`0` keeps the game's own values; `1`–`16` force at least that much. **16 is now the default** —
measured on the title screen's grass and stone, it raises high-frequency scene detail by **+10.8 %**
over the game's own settings with no visible artefacts.

**3. Textures are sampled at mips authored for a lower resolution.** `tex_lod_bias` (a float, default
`0`) is added to every sampler's LOD bias; a negative value samples a sharper mip level. Try
`-0.5` for a little more texture crispness, `-1` for more (with some aliasing). This one is a taste
setting, so it is **off by default**.

### What is not the problem
The F1 menu and the launcher are drawn by the host at the window's own resolution, *after* the
upscaler runs — measured identical at DLSS DLAA and DLSS Quality (edge energy 6.84 in both). The
game's own UI (dialogue, menus) is drawn into the game's output buffer, so it is as sharp as that
buffer: at DLSS Quality the game renders 2560×1440 and DLSS brings it to 3840×2160.

### Verified
- DLSS DLAA and all four super-resolution modes at 4K: no `evaluate` failures, `Created DLSSContext`
  present, sharpness reported in the log (`vk: DLSS sharpening 80%`).
- 6 resolutions × 5 DLSS modes, 30/30 (scene size and applied mode both match).
- 4K × 5 DLSS modes with `render_scale = 150` in the file: 20/20, DLSS still draws at its own ratio.
- Render scale 25–200 % on cold start: 11/11.
- 75 automated tests pass.

### Requirements
Same as before: Engage 2.0.0 base + update + DLC. DLSS needs an RTX card and the Streamline DLLs
(`sl.interposer.dll`, `sl.common.dll`, `sl.dlss.dll`, `nvngx_dlss.dll`, `NvLowLatencyVk.dll`) in
`upscalers\streamline\`.
