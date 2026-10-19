# 开发与构建

Python 3.12 为当前开发与自动检查目标，SteamOS 本机构建另使用 Python 3.13。源码包含图形安装器、版本识别、安装／更新／卸载及原文件恢复；玩家包属于开发预览，尚未全篇验收。高级构建器只生成本地产物，GUI 中的「安装 / 更新」才会写入选定游戏。请在独立副本中做开发测试，保留个人进度。

## 环境与检查

建议使用独立 Python 环境，在仓库根目录执行：

```sh
python tools/bootstrap.py
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

`bootstrap.py` 下载固定提交的 majiro-py 源码和许可至 `.deps/majiro-py/`；其他运行依赖在 `requirements.txt` 固定。`tests/` 使用合成资源与模拟接口，不附带游戏脚本。游戏相关的构建、启动和场景检查分别记录在 [COMPATIBILITY.md](COMPATIBILITY.md)，单元测试通过不代表全篇游玩通过。

目录用途：`tools/` 为实现，`docs/` 为说明及来源元数据，`.deps/` 为本地依赖，`work/`、`build/`、`dist/` 为被忽略的本地输入和产物。游戏 EXE、DLL、完整 ARC、翻译表、存档及安装记录都不能提交。

## 从源码运行安装器

Python 环境须有 `tkinter` 及对应 Tcl/Tk。启动共享 GUI：

```sh
python tools/app.py
python tools/app.py --mode chinese --language zh
```

可用 `--game-dir ./work/my-anthology` 预填游戏根目录。界面支持 `ja`、`en`、`zh`；界面语言不改变剧情语言。字体模式保留识别到的日文／英文／受支持中文输入，中文模式读取玩家提供的风铃汉化组 PC v1.1 原始 RAR，再用同一字体核心在本地生成适配文件。源码 GUI 的中文模式通过「选择 RAR」指定原包；分发包可自动发现启动程序旁的同名原包。

Windows RAR 读取使用系统 `tar.exe`；Linux／SteamOS 使用系统 `libarchive`。Linux 图形会话还须能运行 Tk，并具备相容的图形和字体运行库。字体自动选择会查询 Windows 字体注册表或 `fc-list`，也可手动指定本机已有字体；安装器不安装字体、不更改系统区域。

Windows 和 SteamOS 使用各自的原生入口。SteamOS 安装器在桌面模式运行，安装完成后仍通过 Steam 原入口启动游戏；安装器不需要放进 Proton 前缀。实际安装、冲突与恢复操作见 [INSTALLATION.md](INSTALLATION.md)。

## 版本识别与安装接口

- `docs/source-profiles.json`：五模块日文／英文原版的 EXE 与相关脚本、配置指纹。
- `docs/translation-source.json`：PC v1.1 RAR、五个成员 EXE 与原说明的指纹、署名及出处。它用于匹配已记录输入，不提供发布者真实性或安全性保证。
- `installer_app_backend.scan_game(path)` 返回实际安装的模块及其支持状态；未知或相关资源已修改的输入会被拒绝。
- `run_install(game_dir, modules, chinese=False, font_family=None, translation_archive=None)` 与 `run_uninstall(game_dir)` 是 GUI 共用的安装接口。`modules` 是本次希望保留安装的完整故事集合；取消先前已安装故事会恢复它。

上述接口从 `tools/installer_app_backend.py` 导入，开发调用时将 `tools/` 加入 Python 模块路径。后台构建以 `.narcibloom` 中保留的原始输入为基础，避免重复修补当前产物；写入前检查游戏进程，安装管理器记录备份、文件指纹和事务。未知外部覆盖、后续 Steam／用户修改、未完成事务的恢复冲突均应停止并保留现场，不能通过删除记录或放宽识别绕过。

`.narcibloom` 含本地原文件及恢复资料，不能随反馈或发布包上传。卸载恢复原文件并处理自身新增文件，个人存档与受保护设置不在写入范围。

## 字体核心与中文适配

`build_font_settings.build_overrides(game, files, language, font_family)` 接收已经展开、按优先级合并的有效资源映射，返回覆盖文件和构建信息。新增菜单使用 `ja` 的 CP932、`en` 的 ASCII，或中文加载器对应的映射；选择英文新增菜单不翻译日文剧情。GUI 依据实际输入选择菜单语言，而不是要求玩家猜测编码。

`chinese_builder.build_chinese_payload(game, packed_exe_bytes, stock_files, font_family)` 返回 `ChineseBuild(payload, executable, report)`。它在内存中读取原汉化的虚拟文件并恢复 PE，合并原版资源、汉化 ARC 和优先的 `#mjo/` 脚本；修改后的脚本同时保持松散覆盖与新 ARC 一致。每张译文表单独识别编码，新增 UI 按该版本 DLL 的记录规则接入。不要把仅有 `update12.arc` 的原版产物当作完整中文适配。

该路径不执行输入 EXE／DLL，不修改剧情表；原包和汉化信息保留，变更后的汉化产物只在玩家电脑生成。旧 `repair_onetwo_virtual_files.py` 是特定历史输入的研究配方，不是通用 v1.1 安装流程。来源与分发边界见 [TRANSLATION.md](TRANSLATION.md)、[THIRD_PARTY.md](../THIRD_PARTY.md)。

原生字体／菜单／固定确认提示的部分字段使用简短 ASCII，避免与 ANSI 加载器编码冲突。中文菜单与已抽样正文不因此改成英文；部分主窗口标题仍可能乱码，不能靠更改系统区域或盲目覆盖标题钩子掩盖。

`layout_candidate.py` 按有效 console 边界插入等待，保留原打字事件；新增等待不创建原生存档点，并暂时保护设置／历史记录入口。插入页内保存会回到前一个原生停顿点，不能精确恢复该页。当前为预览实现，实机场景和合成长段结果见兼容性记录，不构成全篇与所有演出的保证。

## 高级：仅生成原版覆盖资源

维护者可直接使用 `build_font_settings.py`。此入口读取指定副本并生成 `work/staged/<模块>/update12.arc` 与构建报告，不执行安装器版本识别或恢复事务，也不改源游戏。它不能替代完整的中文构建和原生窗口修正。

Linux 示例：

```sh
export NARCIBLOOM_GAME_DIR="./work/my-anthology"
export NARCIBLOOM_WORK_DIR="./work"
python tools/build_font_settings.py --game narci_onetwo --menu-language en
```

PowerShell 7 示例：

```powershell
$env:NARCIBLOOM_GAME_DIR = (Resolve-Path './work/my-anthology').Path
$env:NARCIBLOOM_WORK_DIR = Join-Path (Get-Location) 'work'
python tools/build_font_settings.py --game narci_iris --menu-language ja --font-family 'UD Digi Kyokasho N'
```

`--font-family` 仅选择已经安装且适合文本语言的字体；高级构建器省略此项时保留源配置字体，而 GUI 留空时会自动选择。`--game` 可重复指定；模块 ID 为 `narci_onetwo`、`narci_himeko`、`narci_iris`、`narci_zero`、`narci_sumire`。只使用已确认的受支持输入，不混用语言和加载器产物，不使用 `python -O` 绕过结构检查。

## 构建原生预览包

在对应平台的 x64 构建主机上安装打包依赖：

```sh
python tools/bootstrap.py
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
python tools/build_release.py --output dist/my-preview
```

`requirements-build.txt` 包含运行依赖及固定版本的 PyInstaller 工具链。输出目录必须为空或尚不存在，已有输出会保留。Windows 主机构建 Windows 原生 `.exe` 包；Linux 主机构建 SteamOS／Linux 原生程序。两个平台都生成带平台名的 Fonts ZIP、`SHA256SUMS.txt` 与 `artifacts.json`；当前版本取自安装后台的 `VERSION`。

构建中文包时提供自己的原始 v1.1 RAR：

```sh
python tools/build_release.py --output dist/my-preview-cn --translation-archive './work/N10 ver1.1补丁.rar'
```

此命令生成 Fonts 和 Chinese 两种 ZIP。Chinese 包原样附带 RAR，将入口命名为 `NarciBloomChinese.exe` 或 `NarciBloomChinese`，仍在安装时本地转换。也可向已有 Fonts 包添加原 RAR，不重新构建其原生入口：

```sh
python tools/build_release.py --output dist/my-bundle --bundle-existing './dist/my-preview/NarciBloom-<version>-<platform>-Fonts.zip' --translation-archive './work/N10 ver1.1补丁.rar'
```

打包不读取游戏安装目录，也不应把游戏、存档、生成后的汉化程序或 `.narcibloom` 装进 ZIP。构建会收集第三方许可，并联网获取所用 CPython／Tcl／OpenSSL／zlib 的对应声明；缺失或无法解释的 Linux 原生依赖来源会让构建停止，需核对报告。`build-info.json` 记录源码提交、是否有未提交修改及构建工具版本；正式候选应从干净提交构建并保留这些标识。

Linux 包依赖主机提供一部分图形、字体及归档共享库，并非面向任意发行版的全静态程序。所需共享库及 GLIBC 下限应依据该次构建的实际产物、构建主机和目标机检查（例如 `ldd`、`readelf --version-info`）；不能仅凭 ZIP 名称承诺通用兼容。发布时保留 `licenses/` 及其运行时来源报告。

`.github/workflows/packages.yml` 提供手动触发的两平台 Fonts 包构建；工作流产物不等于已经发布或完成游戏验收。公开发布前仍需核对原生启动、安装／更新／卸载、依赖声明及相应平台的游戏场景结果。
