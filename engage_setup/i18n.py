"""The launcher's own interface language.

The wizard already reads `installer/text/<lang>.json`; the launcher window is separate code, so it keeps its own
small table here. A message is translated by its English source text, which keeps the call sites readable and makes a
missing entry fall back to English instead of showing an id.

Only the window's own wording is translated. File names, setting keys, folder names and the game's own text are not.
"""
import json
import os
from pathlib import Path

LANGUAGES = {'en': 'English', 'zh-Hans': '简体中文'}
DEFAULT = 'en'
_current = DEFAULT

# Launcher window wording. Keys are the English strings used in the code.
ZH = {
    # navigation and header
    'Play': '开始游戏',
    'Mods': '模组',
    'Saves': '存档',
    'Settings': '设置',
    'Setup / Update': '安装 / 更新',
    'Engage PC Recomp': '火焰纹章 Engage PC 移植版',
    # home
    'Ready to play': '可以开始游戏',
    'Game running': '游戏运行中',
    'Working…': '处理中…',
    'Setup needed': '需要安装',
    'Play Engage': '启动 Engage',
    'Set up Engage': '安装 Engage',
    'F1 for in-game settings': 'F1 打开游戏内设置',
    'Display': '画面',
    'Enabled mods': '已启用模组',
    'enabled': '已启用',
    'Open folder': '打开文件夹',
    'Back up': '备份',
    'Edit settings': '修改设置',
    'Manage mods': '管理模组',
    'No mods enabled': '未启用模组',
    'Ready for the next launch': '下次启动时生效',
    'Game 2.0.0': '游戏 2.0.0',
    # settings page
    'Changes apply on next launch. F1 offers more settings in-game.':
        '修改将在下次启动时生效。游戏内按 F1 可调整更多设置。',
    'Save settings': '保存设置',
    'Choose game folder': '选择游戏文件夹',
    'Refresh': '刷新',
    'Check for updates': '检查更新',
    'Game default, or ': '游戏自动，或 ',
    'No game folder selected': '未选择游戏文件夹',
    'Settings saved for the next launch.': '设置已保存，下次启动生效。',
    'Window size saved — it applies when the game next starts.': '窗口大小已保存，游戏下次启动时生效。',
    '3D render scale must be Game default or ': '3D 渲染比例必须是「游戏自动」或 ',
    ' must be Game default or ': ' 必须是「游戏自动」或 ',
    # mods page
    'Your mods': '你的模组',
    'RomFS mods are supported. Cobalt plugins and code patches are not available yet.':
        '支持 RomFS 模组。暂不支持 Cobalt 插件和代码补丁。',
    'Search': '搜索',
    'All mods': '全部模组',
    'Mod': '模组',
    'Status': '状态',
    'Files': '文件',
    'Overlaps': '覆盖',
    'Enabled': '已启用',
    'Disabled': '已停用',
    'Needs attention': '需要注意',
    'Unavailable': '不可用',
    'Select a mod': '选择一个模组',
    'Build your collection': '导入你的第一个模组',
    'Select a mod to see its files, conflicts and compatibility.': '选择模组可查看文件、覆盖情况和兼容性。',
    'Import a ZIP or an extracted mod folder to get started.': '导入 ZIP 或已解包的模组文件夹即可开始。',
    'No matching mods': '没有匹配的模组',
    'Try another search or choose All mods.': '换个关键词，或选择「全部模组」。',
    'Enable / Disable': '启用 / 停用',
    'Enable mod': '启用模组',
    'Disable mod': '停用模组',
    'Import ZIP': '导入 ZIP',
    'Import folder': '导入文件夹',
    'Open mods folder': '打开模组文件夹',
    'Importing mod…': '正在导入模组…',
    ' files · ': ' 个文件 · ',
    ' overridden by earlier mods.': ' 被更早的模组覆盖。',
    ' Contains executable patches: those patches will be ignored.': ' 含可执行补丁，这些补丁会被忽略。',
    '\nChanges apply on the next launch.': '\n修改将在下次启动时生效。',
    ' installed    ·    ': ' 个已安装    ·    ',
    ' enabled    ·    ': ' 个已启用    ·    ',
    ' need attention': ' 个需要注意',
    'Choose the extracted mod folder': '选择已解包的模组文件夹',
    'Choose a RomFS mod ZIP': '选择 RomFS 模组 ZIP',
    'ZIP archive': 'ZIP 压缩包',
    # saves page
    'Your saves': '你的存档',
    'Load a save from the title menu in-game. Create a backup here with the game closed; backups include committed saves and any pending save transaction.':
        '在游戏标题画面读取存档。备份请先关闭游戏；备份会包含已提交的存档和未完成的写入。',
    'Back up saves': '备份存档',
    'Open save folder': '打开存档文件夹',
    'Open backups': '打开备份文件夹',
    'Saves found in profile/save.': '已在 profile/save 找到存档。',
    'No saves found yet. Save once in-game to create them.': '还没有存档。在游戏内存档一次即可创建。',
    'Backing up saves…': '正在备份存档…',
    # setup choice page
    'Set up Engage': '安装 Engage',
    'Use a game you have already installed, or create an installation from your own game files.':
        '使用已经安装好的版本，或用你自己的游戏文件创建安装。',
    'Already have an installed build?': '已经装好了？',
    'Select the folder containing engage.exe and romfs-index.bin.': '选择包含 engage.exe 和 romfs-index.bin 的文件夹。',
    'Use existing install': '使用现有安装',
    'Starting with game files?': '从游戏文件开始？',
    'Choose your base game, update 2.0.0, keys and firmware. Setup builds the game on this PC.':
        '选择本体、2.0.0 更新、密钥和固件。安装器会在本机编译游戏。',
    'Set up from my game files': '用我的游戏文件安装',
    # status messages
    'All changes apply on next launch': '所有修改在下次启动时生效',
    'Choose your game folder, or open Setup / Update to install.': '选择游戏文件夹，或打开「安装 / 更新」开始安装。',
    'That folder does not contain engage.exe.': '该文件夹里没有 engage.exe。',
    'Game folder selected.': '已选择游戏文件夹。',
    'Folder selected; could not remember it: ': '已选择文件夹，但无法记住它：',
    'Could not remember game folder: ': '无法记住游戏文件夹：',
    'Game started. Settings, mods and save backups unlock after it exits.':
        '游戏已启动。退出后才能修改设置、模组和备份存档。',
    'Game closed.': '游戏已退出。',
    'Game exited with code ': '游戏退出，返回码 ',
    '. Check the game’s logs folder.': '。请查看游戏的 logs 文件夹。',
    'Choose an installed Engage game folder first.': '请先选择一个已安装的 Engage 游戏文件夹。',
    'Close the game before changing settings, mods or saves.': '请先关闭游戏，再修改设置、模组或存档。',
    'Close any running engage.exe before changing this installation.': '请先关闭正在运行的 engage.exe。',
    'Close Setup / Update before changing this installation.': '请先关闭「安装 / 更新」窗口。',
    'Close the game and Setup / Update before installing a launcher update.': '安装启动器更新前，请先关闭游戏和安装窗口。',
    'Close the Setup / Update window first.': '请先关闭「安装 / 更新」窗口。',
    'Wait for the current operation to finish, or cancel the update, before closing.': '请等待当前操作完成或取消更新后再关闭。',
    'Setup / Update is open in its own window. Refresh here when it finishes.':
        '「安装 / 更新」已在独立窗口中打开，完成后回到这里刷新。',
    'Finished: ': '完成：',
    'Could not finish: ': '未能完成：',
    'Checking for launcher updates…': '正在检查启动器更新…',
    'Checking the new launcher…': '正在检查新的启动器…',
    'Could not check updates. Try again later.': '检查更新失败，请稍后再试。',
    'No newer published setup is available.': '没有更新的版本。',
    'Launcher update v': '启动器更新 v',
    ' is available.': ' 可用。',
    'Later': '稍后',
    'Cancel': '取消',
    'Update now': '立即更新',
    'Update postponed. You can keep playing.': '已推迟更新，可以继续游戏。',
    'Update did not finish. Your current launcher is available.': '更新未完成，当前启动器仍可使用。',
    'Cancelling update…': '正在取消更新…',
    'Preparing launcher update…': '正在准备启动器更新…',
    'Update cancelled. Your current version is unchanged.': '已取消更新，当前版本未改动。',
    'Use the packaged launcher to install updates. Source checkouts are updated through Git.':
        '请使用打包好的启动器来安装更新。源码版本请通过 Git 更新。',
    'Download and install v': '现在下载并安装 v',
    ' now?\n\nThe launcher will restart, then update your selected game installation. Saves, mods and settings are kept. A game-code rebuild may be needed.':
        ' 吗？\n\n启动器会重启，然后更新你选定的游戏安装。存档、模组和设置都会保留，可能需要重新编译游戏代码。',
    'Update Engage PC Recomp': '更新 火焰纹章 Engage PC 移植版',
    'Launcher updated. Choose an existing game folder or set up Engage.': '启动器已更新。请选择游戏文件夹或安装 Engage。',
    'Launcher updated. Close the running game, then select Setup / Update.': '启动器已更新。请关闭游戏后选择「安装 / 更新」。',
    'Launcher updated. Select the files Setup needs to finish updating your game.':
        '启动器已更新。请选择安装器需要的文件以完成更新。',
    'Choose the folder containing engage.exe': '选择包含 engage.exe 的文件夹',
    'Language changed.': '界面语言已切换。',
    ' enabled': ' 个已启用',
    'disabled': '已停用',
    'Language': '界面语言',
    # launcher settings labels (launcher.py SETTINGS)
    'Window mode': '窗口模式',
    'Windowed': '窗口',
    'Fullscreen': '全屏',
    'Window size': '窗口大小',
    'Presentation': '呈现方式',
    'VSync': '垂直同步',
    'Mailbox': '低延迟（邮箱）',
    'Immediate': '立即呈现',
    'Performance overlay': '性能监视器',
    'Off': '关闭',
    'FPS only': '仅帧率',
    'Full': '完整',
    '3D render scale': '3D 渲染比例',
    'Game default': '游戏自动',
    'Scaling to the window': '超分到窗口',
    'AMD FSR 1': 'AMD FSR 1',
    'Bilinear': '双线性',
    'NVIDIA DLSS': 'NVIDIA DLSS',
    'DLSS mode': 'DLSS 档位',
    'DLAA': 'DLAA',
    'Quality': '质量',
    'Balanced': '平衡',
    'Performance': '性能',
    'Ultra performance': '超级性能',
    'Sharpness': '锐度',
    'Picture shape': '画面比例',
    'Black bars': '黑边',
    'Stretch': '拉伸',
    'Button prompts': '按键提示',
    'Follow the device in use': '跟随当前输入设备',
    'Switch buttons': 'Switch 按钮',
    'Keyboard and mouse': '键盘与鼠标',
    'Frame rate limit': '帧率上限',
    'Game language': '游戏语言',
    'English': '英语',
    'Japanese': '日语',
    'French': '法语',
    'German': '德语',
    'Italian': '意大利语',
    'Spanish': '西班牙语',
    'Korean': '韩语',
    'Chinese (simplified)': '简体中文',
    'Chinese (traditional)': '繁体中文',
    'Volume': '音量',
}

# Where the launcher remembers its own interface language (separate from the game's language setting).
def state_path():
    return Path(os.environ.get('APPDATA', Path.home())) / 'Engage PC Recomp/launcher.json'


def load_language():
    """The saved interface language, or the system's when there is none."""
    try:
        saved = json.loads(state_path().read_text(encoding='utf-8'))
        lang = saved.get('ui_language') if isinstance(saved, dict) else None
        if isinstance(lang, str) and lang in LANGUAGES:
            return lang
    except (OSError, ValueError):
        pass
    return system_language()


def system_language():
    """Chinese when Windows is Chinese, English otherwise: a player who reads neither is no worse off."""
    try:
        import locale
        name = locale.getdefaultlocale()[0] or ''
    except (ImportError, ValueError):
        name = ''
    if not name:
        try:
            name = os.environ.get('LANG', '') or ''
        except (AttributeError, TypeError):
            name = ''
    return 'zh-Hans' if name.lower().startswith('zh') else DEFAULT


def save_language(lang):
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {}
        try:
            loaded = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                record = loaded
        except (OSError, ValueError):
            record = {}
        record['ui_language'] = lang if lang in LANGUAGES else DEFAULT
        path.write_text(json.dumps(record), encoding='utf-8')
    except OSError:
        pass


def set_language(lang):
    global _current
    _current = lang if lang in LANGUAGES else DEFAULT
    return _current


def language():
    return _current


def tr(text):
    """The text in the current interface language; unknown text stays as it is."""
    if _current == 'zh-Hans':
        return ZH.get(text, text)
    return text
