// Windowed entry point for the bundled launcher; forward arguments without a shell.
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t folder[32768], python[32768], command[32768];
    DWORD n = GetModuleFileNameW(NULL, folder, 32768);
    if (!n || n >= 32768) goto fail;
    while (n && folder[n - 1] != L'\\') n--;
    if (!n) goto fail;
    folder[n - 1] = 0;
    int written = swprintf(python, 32768, L"%ls\\python\\pythonw.exe", folder);
    if (written < 0 || written >= 32768 || GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) goto fail;
    written = swprintf(command, 32768, L"\"%ls\" -I -m engage_setup.gui %ls", python, arguments);
    if (written < 0 || written >= 32768) goto fail;
    STARTUPINFOW si = {.cb = sizeof si};
    PROCESS_INFORMATION pi;
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, 0, NULL, folder, &si, &pi)) goto fail;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
fail:
    MessageBoxW(NULL, L"Extract the entire setup ZIP, keeping its files together, then run Engage-Launcher.exe again.",
                L"Engage PC Recomp", MB_OK | MB_ICONERROR);
    return 1;
}
