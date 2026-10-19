# 第三方来源

本仓库的 MIT 许可仅覆盖自行编写的代码与文档，不授予游戏、汉化文本、游戏截图内原作素材或第三方依赖的额外权利。

| 项目 | 固定版本 | 许可 | 用途 |
|---|---|---|---|
| [majiro-py](https://github.com/trigger-segfault/majiro-py) | `f7ec450d5b78f0ed6df603b8c0b0ed79748d9cee` | MIT | Majiro 指令定义、脚本编码与名称哈希 |
| [evbunpack](https://github.com/mos9527/evbunpack) | `ee7b647acf2a46617b0c448dfa83d63132ea917b` | Apache-2.0 | 从用户本地的汉化程序中提取虚拟文件 |
| [pefile](https://github.com/erocarrera/pefile) | `2024.8.26` | MIT | 识别 PE 文件位置 |
| [aplib](https://github.com/snemes/aplib) | `0.6` | MIT | evbunpack 的解压依赖 |

`tools/bootstrap.py` 将 majiro-py 的源码及原始 LICENSE 下载到被 Git 忽略的 `.deps/`。其余依赖由 `requirements.txt` 安装。发布安装包若包含这些依赖，应一并保留各自要求的许可与声明。

1＋2 适配依赖已有汉化：项目只提供修改逻辑及自行增加的界面文案，不分发提取出的完整汉化程序、DLL、翻译文件或原始脚本。游戏与汉化作者应在安装兼容性信息补齐后进一步列明；当前无法仅凭本地程序确认完整作者与版本来源。
