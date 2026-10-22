# 开发与构建

preview.7补充只读成词位置数据及有界单字段候选图。修改或检查数据用`python tools/build_native_oov.py --check`；可用`--source-dir`指定已固定的三份概率表离线重现。它不执行下载的Python代码，不增加玩家运行依赖，许可与再生边界见[第三方说明](../THIRD_PARTY.md)及[中文换行说明](LAYOUT.md)。

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

可用 `--game-dir ./work/my-anthology` 预填游戏根目录。界面支持 `ja`、`en`、`zh`；界面语言不改变剧情语言。字体模式保留识别到的日文／英文／受支持中文输入，中文模式读取受支持的 PC v1.1 透明安装材料 ZIP 或原始 RAR，再用同一字体核心在本地生成适配文件。分发包优先自动发现启动程序旁的 `NarciBloom-translation-PC-v1.1-prepared.zip`，其次识别原 RAR。

透明安装材料使用标准 ZIP 读取，不需要 RAR 工具。读取原 RAR 时，Windows 使用系统 `tar.exe`，Linux／SteamOS 使用系统 `libarchive`。Linux 图形会话还须能运行 Tk，并具备相容的图形和字体运行库。字体自动选择会查询 Windows 字体注册表或 `fc-list`，也可手动指定本机已有字体；安装器不安装字体、不更改系统区域。

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

该路径不执行输入 EXE／DLL，不修改剧情表。透明材料保留原虚拟资源和说明，恢复虚拟化 PE；字体、分页和窗口提示适配仍在玩家电脑生成。原 RAR 与透明材料经过同一个生成核心，格式转换不能代替逐模块输出比较。旧 `repair_onetwo_virtual_files.py` 是特定历史输入的研究配方，不是通用 v1.1 安装流程。来源与分发边界见 [TRANSLATION.md](TRANSLATION.md)、[THIRD_PARTY.md](../THIRD_PARTY.md)。

原生字体／菜单／固定确认提示的部分字段使用简短 ASCII，避免与 ANSI 加载器编码冲突。中文菜单与已抽样正文不因此改成英文。preview.2 起独立 `majiro.env:TITLEBAR` 字段采用完整英文作品名；preview.3 仅为三个旧日文引擎明确存读档界面字符集。这里处理的是已识别路径，不保证所有动态文字都已遍历，不更改系统区域。

`layout_candidate.py` 按有效 console 边界插入等待，保留原打字事件；新增等待不创建原生存档点，并暂时保护设置／历史记录入口。插入页内保存会回到前一个原生停顿点，不能精确恢复该页。当前为预览实现，实机场景和合成长段结果见兼容性记录，不构成全篇与所有演出的保证。

## 中文显示层

`native_layout.patch_chinese_native_layout(original_restored, baseline=localized_engine)` 仅识别五个固定PC v1.1恢复引擎；日英路径不调用它。原始引擎用于身份检查，已本地化的同结构PE用于追加自有RX代码段和已核实的相对调用／跳转。保留导入、重定位、入口及原取行调用次数；三个布局分别适配，不将1＋2的栈协议套到其他篇章。

显示规则仅作用于中文：preview.6使用固定通用词频的DAG路径，按完整开闭标点、可容纳词边界及短尾软目标选择断点，包含ASCII单词和数字串保护。行首额外U+0020显示advance为零，U+3000为原advance向上取整的一半。全角标点、英文句内空格与译文字节保留。词语过宽和未知控制保留退化路径，GBK禁则另包含全角波浪号“～”。具体根因、容量及探测状态保护见[LAYOUT.md](LAYOUT.md)。

preview.5核心源码CI通过，185项检查中181项通过、4项平台跳过，含新增6项原生检查。三个ABI族使用真实32位执行harness核对调用协议与不同加载地址，不替代GDI或游戏实测。五部真实中文构建核对315份有效剧情脚本（含110份松散脚本）和110份原译表字节保留；十组日英只读构建未调用此适配。SteamOS仅中文1＋2最终候选完成44档短尾、空白、历史返回与单字回答有限抽样。

自有C源码为 `native_layout_tail.c` 与 `native_layout_spacing.c`，`native_layout_generated.py` 保存无CRT／外部符号／数据重定位的32位代码及源指纹，`native_layout_x86.py` 生成位置无关的调用桥。安装器只需要原有Python依赖，不调用编译器。维护者可用Zig 0.16.0在不读取游戏的情况下核对生成物：

```sh
python tools/regenerate_native_layout.py --compiler /path/to/zig --build-dir work/native-layout-build --check
```

修改C源码时先审阅，再用同命令的 `--write` 重新生成，并运行相关检查。源指纹归一化CRLF/LF。缓冲区以原生1024字节数据容量为界，不借用尾部占用标志；退回的后缀保持原始字节，遇未知控制和不能证明安全的状态保留原断法。不要以普通汉字禁首表、译表批量替换或缓存中的硬换行替代这条显示路径。实际游戏检查和剩余范围见兼容性说明。

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

词表再生与真实x86无界面验证入口见 [LAYOUT.md](LAYOUT.md)。`tools/build_native_lexicon.py`只供维护者使用；玩家安装器使用已固定的数据，不下载或运行分词工具。

已发布的preview.7四包以干净提交`8c911f33ed3690a562e8244d0edd09aab706c970`为冻结程序构建基线。附件大小、摘要、包内原生代码、词频与成词位置数据已核对；两平台安装器两种视图的冻结GUI启动检查通过。源码、安装文件与游戏场景的验证分别记录，后续文档提交不代表重新生成附件。

在对应平台的 x64 构建主机上安装打包依赖：

```sh
python tools/bootstrap.py
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
python tools/build_release.py --output dist/my-preview
```

`requirements-build.txt` 包含运行依赖及固定版本的 PyInstaller 工具链。输出目录必须为空或尚不存在，已有输出会保留。Windows 主机构建 Windows 原生 `.exe` 包；Linux 主机构建 SteamOS／Linux 原生程序。两个平台都生成带平台名的 Fonts ZIP、`SHA256SUMS.txt` 与 `artifacts.json`；当前版本取自安装后台的 `VERSION`。

透明安装材料可用 `tools/prepare_translation.py --source <原RAR> --output <新ZIP>` 从已识别原包生成；不执行其中程序，不读取完整游戏。原资源及说明保持原字节，新增元数据记录静态提取／恢复处理。输出包含第三方汉化内容，只作本地输入或发行附件，不应提交源码。固定指纹匹配本次发行材料；不同压缩库版本或来源说明变动可能使重新生成的 ZIP 指纹不同，不能绕过识别直接发布。

构建中文发行包时提供已记录指纹的透明安装材料：

```sh
python tools/build_release.py --output dist/my-preview-cn --translation-input './work/NarciBloom-translation-PC-v1.1-prepared.zip'
```

此命令生成 Fonts 和 Chinese 两种 ZIP。Chinese 包附带透明安装材料，将入口命名为 `NarciBloomChinese.exe` 或 `NarciBloomChinese`，仍在安装时本地生成字体适配。打包入口拒绝原 RAR，避免发行物重新带入本机已确认会被拦截的嵌套原包；运行时继续接受原 RAR。也可向已有 Fonts 包添加材料，不重新构建其原生入口：

```sh
python tools/build_release.py --output dist/my-bundle --bundle-existing './dist/my-preview/NarciBloom-<version>-<platform>-Fonts.zip' --translation-input './work/NarciBloom-translation-PC-v1.1-prepared.zip'
```

打包不读取游戏安装目录，也不应把游戏、存档、生成后的汉化程序或 `.narcibloom` 装进 ZIP。构建会收集第三方许可，并联网获取所用 CPython／Tcl／OpenSSL／zlib 的对应声明；缺失或无法解释的 Linux 原生依赖来源会让构建停止，需核对报告。`build-info.json` 记录源码提交、是否有未提交修改及构建工具版本；正式候选应从干净提交构建并保留这些标识。

Linux 包依赖主机提供一部分图形、字体及归档共享库，并非面向任意发行版的全静态程序。所需共享库及 GLIBC 下限应依据该次构建的实际产物、构建主机和目标机检查（例如 `ldd`、`readelf --version-info`）；不能仅凭 ZIP 名称承诺通用兼容。发布时保留 `licenses/` 及其运行时来源报告。

`.github/workflows/packages.yml` 提供手动触发的两平台 Fonts 包构建；工作流产物不等于已经发布或完成游戏验收。`frozen-smoke.yml`可复用指定成功构建的Fonts产物，在CI核对源提交、摘要和安全解压后启动两种视图；Linux使用独立Xvfb，脚本拒绝在非CI环境启动。原生启动、安装／更新／卸载、依赖声明及相应平台的游戏场景结果分别记录，不合并为全篇验收。
