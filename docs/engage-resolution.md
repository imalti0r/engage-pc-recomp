# Engage resolution controls

Engage 2.0.0 draws at the window's size: the window is the game resolution (there
is no separate game-resolution row). Two more controls say how that resolution is
produced, in F1 → Screen → Picture, and a change takes effect at once — no restart.

- 3D render scale: Game, 50%, 75%, 100% or 150%. Game preserves Engage's own
  scene-dependent scale. A percentage overrides the render-pipeline camera scale;
  150% supersamples the scene and costs more GPU time and memory.
- Upscaler (Scaling to the window): AMD FSR 1, Bilinear or NVIDIA DLSS. With
  DLSS, the mode (DLAA / Quality / Performance / Ultra performance) divides the
  resolution the game draws at: Quality draws 1.5× smaller, Performance 2×,
  Ultra performance 3×, and DLSS upscales the picture back to the window's size.
  DLAA draws at the window's size and only anti-aliases.

The same settings can be written in `engage.ini` next to `engage.exe`:

```ini
[display]
window_size = 1920x1080
render_scale = game
```

`TOTK_WINDOW_SIZE` and `TOTK_RENDER_SCALE` environment variables override the file.
A window size that is not one of the six 16:9 sizes Engage draws (1280×720 …
3840×2160) makes the game use the nearest smaller one. Invalid scales or
percentages outside 50–150 fall back to Game. Window scaling, FSR presentation
and color adjustment remain separate settings.

The guarded Engage patch table changes Unity's screen manager, NVN display-buffer
storage sizing, device extent and default depth-buffer dimensions together. Changing
only the screen manager leaves a 1080p buffer and clips the scene/UI at smaller
sizes. The scene patch supplies the final camera render scale in
`UniversalRenderPipeline.InitializeStackedCameraData`. It does not resize textures
in the host Vulkan renderer or apply TotK's resolution/HeapDef patches.

## Verification

On Windows with an RTX 4060, isolated runs of Engage 2.0.0 exercised the title,
opening sequence and prologue map/dialogue for about 70 game-clock seconds each.
Read-only instrumentation observed the buffers actually bound for rendering and
the image passed to presentation:

| Selected output | Scale | Measured output color/depth | Measured scene color/depth |
| --- | --- | --- | --- |
| 1280×720 | 50% | 1280×720 | 640×360 |
| 1600×900 | 75% | 1600×900 | 1200×675 |
| 1920×1080 | 100% | 1920×1080 | 1920×1080 |
| 2560×1440 | 150% | 2560×1440 | 3840×2160 |
| 1920×1080 | Game | 1920×1080 | 1920×1080 at title; 1728×972 in tested map scene |

Game is not a fixed 83%. The title/map measurements were the same before these
patches and with the candidate set to Game. Other scenes may choose other scales;
these observations do not establish a performance-driven dynamic-resolution policy.

Prologue screenshots at all four fixed combinations retain the full scene,
dialogue and portrait layout. All six F1 tabs were captured and the Screen tab
was inspected. Presentation remained RGBA8 sRGB, and the synthetic RGBA/BGRA sRGB
and color-adjustment readback probe passed. Validation layers were not enabled.
The menu's settings hook saved 1280×720/50% to the isolated candidate's INI; a new
process loaded those values and bound 1280×720 output and 640×360 scene buffers.
Other GPUs, handheld mode, combat effects, later chapters and long sessions remain
unverified. These runs are rendering checks, not performance benchmarks.
