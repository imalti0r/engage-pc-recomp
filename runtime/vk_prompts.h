// Keyboard-and-mouse prompt icons (TOTK_PROMPTS=pc, live): the drawn atlases and their bookkeeping live in
// vk_prompts.c; the texture uploader and the input sampler call in here.
#pragma once
#include <stddef.h>
#include <stdint.h>

// The game's own button-prompt atlas was just decoded for upload at storage addr (256x256 RGBA8): recognise it.
void vk_prompt_icons_note_upload(uint64_t addr, const uint8_t *rgba, uint32_t w, uint32_t h);
// The picture to upload instead of the storage's, when this address is a known atlas and the source wants ours.
int vk_prompt_icons_override(uint64_t addr, uint32_t w, uint32_t h, const uint8_t **rgba);
void vk_prompt_icons_flip(uint64_t addr, uint8_t *rgba, uint32_t w, uint32_t h);
// The player pressed a gamepad button or stick (pad 1) or a key or mouse button (pad 0).
void vk_prompt_icons_note_source(int pad);
// 1 once after the source changed and an atlas is known: the caller re-uploads those textures.
int vk_prompt_icons_take_switch(void);
// The addresses of the known atlases (at most max).
size_t vk_prompt_icons_addresses(uint64_t *out, size_t max);
// Whether the atlas at addr currently holds our icons.
void vk_prompt_icons_showing(uint64_t addr, int *pc);
