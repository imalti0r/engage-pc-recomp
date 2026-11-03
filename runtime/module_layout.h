#pragma once
#ifdef RT_GAME_LIBRARY
#include "game_library.h"
#define MOD_COUNT GAME_LIBRARY_MODULES
#define MOD_MAIN_BASE (rt_game_library()->layout[0].base)
#else
#include "layout.h"
#endif
