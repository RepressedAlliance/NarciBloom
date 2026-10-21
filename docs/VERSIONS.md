# 输入版本记录

更新于 2026-10-22，适用于已发布的 preview.5。安装器按 [source-profiles.json](source-profiles.json) 的十组日文／英文 EXE 与关键资源指纹，以及 [translation-source.json](translation-source.json) 的 PC v1.1 原包／透明材料标识识别输入。下面是便于阅读的版本说明；高级覆盖资源构建器不执行完整的安装器版本识别，不能仅凭 EXE 相同就认定全部资源一致。指纹匹配不代表来源身份、安全或权利认证。

## Steam 日文输入

所记录的 Steam 日文基线来自 AppID `426690`、BuildID `3467893`、语言 `japanese`，暂停菜单脚本文字为 CP932 日文。本节描述识别基线，不表示任意机器当前安装状态，也没有对完整 Steam 游戏逐文件认证。

| 模块 | EXE 字节数 | EXE SHA-256 |
|---|---:|---|
| 1＋2 | 1015296 | `c573a0901b007c1db2cc96f6277aafe15401352b7c52f4a2bb16b6bc69ce8693` |
| 姬子后日谈 | 1048576 | `45c8a1b5ea39a552629e637e4435b9fa9639978f40f3c164a24867c739d70075` |
| Iris | 831488 | `f687e510f14dcbb2fe467f31b740f10e8baa6ca981ca626d61d0b6b7ee7cc825` |
| Zero | 1105920 | `f85b6f836bf21360c50e997664df5635992a06c3eb8c3fa21ffd51811adfb137` |
| Sumire | 1176064 | `33ca175716962f6387523fac3d4c8edc4864b038c7ac3953e7e62b19091fff40` |

## Steam 英文输入

以下是已识别的独立Steam英文输入，分别生成英文菜单；实际运行抽样范围见兼容性说明。

| 模块 | EXE SHA-256 |
|---|---|
| 1＋2 | `f0255f28dd6ce77b71565363e75e5b59ea192da0136b50cfa6d62cfd8b0f40d3` |
| 姬子后日谈 | `dbbbd6ce447846311a2ff934f8c15d51b9f3ca384b55d1e639d339633e6ec8e2` |
| Iris | `f88df926e03f806cd354ecc21ae4fda6fe272cbe8b57f31ef95550f9046ff6e4` |
| Zero | `d2bd02daed3053b970f8d2006173ff9c40a24dbd5c6555925eddb0b214517df1` |
| Sumire | `a39ab5c816cf447bd6e0e54110abe617225b93da9bc05e5e7d49a935b2aeda56` |

## 风铃 PC v1.1 中文输入

已核对本地 `N10 ver1.1补丁.rar` 的五个汉化 EXE 和原说明，结合原发布页记录署名、版本 v1.1（2025-10-31）及转载声明。原包为81,014,080字节，SHA-256 `20c18c518f001249867fe8903344b3eff456ed342115ac0d6d1d8db3e7b9d735`；五模块成员路径、大小和指纹见 [translation-source.json](translation-source.json)。页面另列的移植版 v1.2 不在本次适配范围内。

Chinese 发行包附 `NarciBloom-translation-PC-v1.1-prepared.zip`，94,474,514字节，SHA-256 `7437994224d5c22b7323f60c5a37b4cbbc163e47de4db61c94639aa839cc9a8c`。它保留原虚拟资源和署名，恢复虚拟化引擎；字体及排版适配在玩家电脑生成。处理方式、转载依据与未确认权利边界见 [TRANSLATION.md](TRANSLATION.md)。

早期1＋2开发样本为10,677,248字节、SHA-256 `c87ae1cbcfd35d10fbc93113167cbb4feab0507189f646c454573b873b8b56ce`；它与v1.1原包成员 `daf4201820ecb89b1d09008b303a8e8e35a79ccb136abbd606438e11bd3052e6` 不同，不能将旧样本结果当作当前原包验证，也不宣称支持所有风铃汉化版本。

preview.5五部中文真实构建通过，315份有效剧情脚本、其中110份松散剧情脚本，以及110份原译表均逐字节保留；十组日英输入完成只读构建，未调用中文显示层。五故事×三语言共十五组有效输入已完成构建及翻译表适配检查；游戏运行只做限定场景抽样，具体版本与范围见 [COMPATIBILITY.md](COMPATIBILITY.md)。没有取得发布者公布的原包哈希或签名，也未比较独立重新下载的第二份原包，不能把本地匹配写作发布者认证。

本表只包含标识及来源说明，不附带汉化程序、脚本、翻译文本或玩家数据。
