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
