# 开发与构建

当前提供的是维护者构建流程。**只生成中间产物，不安装游戏；不要直接把 `staged/` 全部覆盖进游戏。**

## 目录

```text
tools/                  资源包、脚本与 1＋2 汉化适配逻辑
tests/                  不依赖游戏文件的检查
docs/                   兼容性、研究记录与后续计划
.deps/                  本地工具依赖（不提交）
work/                   本地源文件、构建结果（不提交）
```

Python 3.12 为当前开发与自动检查目标。

```sh
python tools/bootstrap.py
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

`bootstrap.py` 获取固定提交的 majiro-py 源码及许可文件。构建阶段需要 pefile，1＋2 虚拟文件提取另需 evbunpack。

## 本地路径

Linux / Steam Deck：

```sh
export NARCIBLOOM_GAME_DIR="/path/to/Narcissu 10th Anniversary Anthology Project"
export NARCIBLOOM_WORK_DIR="$PWD/work"
```

Windows PowerShell：

```powershell
$env:NARCIBLOOM_GAME_DIR = 'D:\Games\Narcissu 10th Anniversary Anthology Project'
$env:NARCIBLOOM_WORK_DIR = Join-Path (Get-Location) 'work'
```

仅指向自有游戏的受支持原始版本。当前流程不负责识别已安装其他修改的版本，也不应使用自己的已修改游戏反复覆盖生成新的基线。

## 原版与汉化的构建选择

字号、持久设置和文本区修正共用实现，新增菜单文字按目标加载器编码：

- 日文原版：加 `--menu-language ja`，使用 CP932 日文菜单，不需要汉化 DLL 或虚拟文件提取。
- 希望在日文原版中使用英文的新增菜单：加 `--menu-language en`，使用 CP932 的 ASCII 子集。此选项不翻译剧情，也不代表 Steam 英文发行文件已适配。
- 现有汉化：默认 `--menu-language zh-CN`，保持原有 GBK 菜单生成；1＋2 还必须执行下文的汉化虚拟文件步骤。

中文 Windows 上的 Iris 曾在原版默认字体下同时出现正文和动态菜单乱码，停用字体补丁后仍可复现。在游戏设置的字体选择框中选用电脑已有的日文字体 `UD Digi Kyokasho N` 后，原版正文恢复。先确认原版使用的字体能正常显示日文，再检查新增菜单；`en` 可让新增菜单避免非 ASCII 字形问题，但不解决正文乱码。无需修改系统区域；其他模块的字体环境仍待分别实测。

需要指定已安装的默认字体时，可额外使用 `--font-family`。它只改构建配置中的正文和角色名字体，不安装字体，也不改变系统设置；省略时保留源文件的字体。不要为汉化版盲目选用只适合日文的字体。例如：

```sh
python tools/build_font_settings.py --game narci_iris --menu-language ja --font-family "UD Digi Kyokasho N"
```

例如日文原版 1＋2：

```sh
python tools/build_font_settings.py --game narci_onetwo --menu-language ja
```

输出仍仅在工作目录。原版 1＋2 的构建结果包含完整的七项覆盖资源，不运行 `repair_onetwo_virtual_files.py`；后者专用于已测试的汉化。开发者可在独立游戏副本中放入对应 `update12.arc` 做运行检查。不要混用不同语言的构建输出，游戏运行时不要替换文件。

工具尚未自动识别版本或处理安装顺序：安装、更换汉化后必须重新从对应输入构建，不能假定先装字体补丁后覆盖汉化仍然有效。文件标识和当前已确认输入见 [VERSIONS.md](VERSIONS.md)。

## 四个后日谈/附加篇章

例如构建 Iris：

```sh
python tools/build_font_settings.py --game narci_iris
```

也可用 `--game narci_himeko`、`--game narci_zero`、`--game narci_sumire`，或重复传入多个 `--game`。输出位于工作目录的 `staged/<模块>/`，包括 `update12.arc` 与本地构建信息。游戏源文件仅被读取。

## 1＋2：必须完成虚拟文件适配

原汉化使用 Enigma Virtual Box，外部资源包可能被其虚拟脚本覆盖，因此不能只构建一个外部 `update12.arc` 后就视为有效。

1. 用受支持汉化的原始游戏文件准备基础构建：

   ```sh
   python tools/build_font_settings.py --game narci_onetwo
   ```

2. 将同一版本的原始汉化程序解包到工作目录的 `unpacked-onetwo/`。下面以默认工作目录为例：

   ```sh
   python -m evbunpack -pe 9_70 "/path/to/original/narci_onetwo.exe" "work/unpacked-onetwo"
   ```

3. 检查输出中确实有原始程序、`#mjo/`、`#txt/`、`FontPatch.dll`、`Narcissu_cn.dll`，再运行：

   ```sh
   python tools/repair_onetwo_virtual_files.py
   ```

4. 修正后的本地产物位于工作目录的 `repair-onetwo/`，**不是第一步的 `staged/narci_onetwo/`**。报告为 `repair-onetwo-report.json`。这一目录包含从自有游戏提取的内容，不能提交到源码仓库。

上述构建配方保留实际使用的汉化脚本，新增的菜单文字通过对应翻译表接入，并修正字幕区域及 DLL 窗口标题替换。结构不符时的断言失败表示需要重新适配，不能使用 `python -O` 绕过检查。

## 当前检查与后续安装器

测试会解释执行生成的辅助函数，检查各字号、菜单选项及控件范围；文本区测试使用人工构造的最小脚本，不附带游戏脚本。实际游戏验证另行记录在兼容性文档中。

尚待完成的安装器应支持：发现 Steam 游戏目录、识别游戏/汉化版本、检查游戏已退出、按安装记录更新或恢复。现阶段没有自动安装或远程部署命令。
