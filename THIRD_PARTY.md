# 第三方来源

本仓库的 MIT 许可仅覆盖自行编写的代码与文档，不授予游戏、汉化文本、游戏截图内原作素材或第三方依赖的额外权利。

| 项目 | 固定版本 | 许可 | 用途 |
|---|---|---|---|
| [majiro-py](https://github.com/trigger-segfault/majiro-py) | `f7ec450d5b78f0ed6df603b8c0b0ed79748d9cee` | MIT | Majiro 指令定义、脚本编码与名称哈希 |
| [evbunpack](https://github.com/mos9527/evbunpack) | `ee7b647acf2a46617b0c448dfa83d63132ea917b` | Apache-2.0 | 从用户本地的汉化程序中提取虚拟文件 |
| [pefile](https://github.com/erocarrera/pefile) | `2024.8.26` | MIT | 识别 PE 文件位置 |
| [aplib](https://github.com/snemes/aplib) | `0.6` | MIT | evbunpack 的解压依赖 |
| PyInstaller | `6.22.3` | GPL-2.0-or-later，含原文 Bootloader Exception | 构建玩家可执行入口，发行包保留 COPYING |

`tools/bootstrap.py` 将 majiro-py 的源码及原始 LICENSE 下载到被 Git 忽略的 `.deps/`。其余依赖由 `requirements.txt` 安装。发布安装包若包含这些依赖，应一并保留各自要求的许可与声明。

玩家包的 `licenses/` 同时保留 Python、Tcl/Tk、libffi、OpenSSL、zlib 与其他实际随包依赖的原始声明；版本以各平台的 `build-info.json`、`licenses/runtime-sources.json` 和原生运行库清单为准。Linux 构建使用兼容 SteamOS 的系统 X11、字体和 RAR 库，不另外复制整套系统库。运行库声明收集器记录实际来源及缺口，不将通用许可证文本当作对应源码或其他义务已经满足的证明。

`tools/translation_adapter.py` 的 Enigma Virtual Box 数据树解析与 PE 恢复逻辑参考并改编自上述固定版本的 evbunpack；该部分遵循 Apache-2.0，原始版权及许可随依赖保留。它在内存中处理玩家提供的程序，不执行输入程序。

源码分发同时保留 [Apache-2.0 许可全文](LICENSE-APACHE-2.0.txt)，适用于这部分改编；仓库根目录的 MIT 许可不替代其原许可条件。玩家包另保留随包 evbunpack 的原始许可副本。

日文、英文原版的字体功能不需要汉化。汉化来源及转载条件已经与风铃汉化组 PC v1.1 原包说明核对，详见 [汉化来源与转载说明](docs/TRANSLATION.md)。源码仓库不包含完整游戏、汉化程序、DLL、翻译文件或原始脚本。中文发行包另附透明安装材料：保留原虚拟资源与汉化信息、恢复虚拟化引擎；字体适配在玩家电脑上生成。这是非官方重新包装，恢复程序改变了程序字节，不宣称获得汉化组专项批准或完整第三方权利授权。字体功能及平台适配与原汉化组的贡献分别署名。
