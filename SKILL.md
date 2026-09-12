---
name: video-fetch-yjf
description: 多平台视频/图文内容抓取与归档工具。当用户说出"抓取 / 抓录 / 抓存 / 抓取视频 / 抓取音频 / 抓取图文"等指令，或提供微信视频号/小红书/B站/抖音/YouTube 等平台的分享链接，并希望"转成笔记/转文字/结构化总结/采集评论/归档到知识库"时，使用本技能一键下载、本地离线转写、总结并生成结构化工整的 Markdown 笔记，可同步至 ima / Obsidian。覆盖三类降级路径：小红书图文笔记（SSR 解析，无需 Cookie）、微信视频号拿不到视频流时改为元数据降级（无头浏览器渲染）、无 LLM 密钥时转写产物先落盘后降级。
description_zh: 多平台视频/图文内容抓取与归档工具，支持微信视频号、小红书（视频与图文）、B站、抖音、YouTube，自动下载、本地离线 ASR 转写、总结、采集评论并生成结构化工整的 Markdown 笔记，可同步至 ima/Obsidian 知识库；内置图文笔记、视频号元数据、无密钥三条降级路径。
description_en: Multi-platform video & image-note fetch/archive skill for WeChat Channels, Xiaohongshu, Bilibili, Douyin and YouTube — download, offline ASR transcription, summarization, top-comment collection, structured Markdown rendering, and sync to ima/Obsidian, with graceful degradation for image notes, Channels metadata-only pages and missing LLM keys.
version: 1.3.0
author: video_fetch_yjf-contributor
allowed-tools: Read, Write, Edit, Bash, PowerShell, Glob, Grep, WebFetch
agent_created: true
---

# video-fetch-yjf — 多平台视频 / 图文内容抓取与归档 Skill

## Overview

将多平台内容（微信视频号、小红书**视频与图文**、B站、抖音、YouTube）一键转化为结构化工整的 Markdown 知识笔记，并可选地同步至 ima / Obsidian 个人知识库。完整能力矩阵、架构、执行流程见随附计划书 `video_fetch_yjf_Skill 开发计划书.docx`；本文件聚焦"如何执行"。

核心产物：一个符合命名规范的 `.md` 笔记，内含内容基本信息、≤100 字内容总结、PREP 结构化小结、完整文字稿（按段落、不删减）、Top5 热门评论，以及可选的封面截图与时间戳。

**三条实测固化的降级路径**（任一环节不可得时降级而非整条失败）：

| 场景 | 走哪条路 | 产物 |
|---|---|---|
| 小红书**图文**笔记（无音视频轨） | `fetch_image_note.py`：SSR 解析（无需 Cookie） | 正文 + 配图 |
| 微信视频号**拿不到视频流** | `fetch_wechat_meta.py`：无头浏览器渲染取元数据 | 文案完整、音视频待补全 |
| **无 LLM 密钥** | 转写产物先落盘，总结降级 | 文字稿完整、PREP 待补全 |

## When to use

在以下场景触发本技能：

- 用户直接下指令："抓取 / 抓录 / 抓存 / 抓取视频 / 抓取音频 / 抓取图文" + 链接或平台名（这是最高优先级的显式触发词，见长期记忆中的路由规则）。
- 用户给出上述任一平台的视频分享链接，并要求"转成笔记 / 整理成 Markdown / 转文字 / 结构化总结 / 存到知识库 / 归档"。
- 用户粘贴视频链接并说"总结一下 / 转文字 / 存到 Obsidian / 同步到 ima"。
- 用户希望把多条视频批量归档为可读笔记。

> 安全约定：本技能会下载第三方平台内容、调用付费 API、写入用户文件系统，属中高风险操作。执行实际下载 / 写入 / 付费调用前，先向用户显式确认（来源链接、目标平台、预计费用、写入路径），不默认静默自动执行整条管道。

## Workflow（四层管道）

按 Layer 1→4 顺序执行；任一环节失败按"分级错误处理"降级而非中止整体（详见 `references/error-codes.md`）。

1. **Layer 1 输入解析**：运行 `scripts/detect_platform.py` 识别平台与校验链接；无法识别则跳过该条并提示。
2. **Layer 2 数据采集**：按平台分派 `scripts/downloader/` 下适配器下载视频、抓取元数据、采集评论（Top5）。
3. **Layer 3 内容处理**：`scripts/extract_audio.py`（FFmpeg 提取音频）→ `scripts/transcribe.py`（Whisper / 云端 ASR）→ `scripts/summarize.py`（LLM 总结 + PREP）。
4. **Layer 4 输出与归档**：`scripts/render_markdown.py`（按 `templates/note_template.md` 渲染）→ `scripts/validate_output.py`（排版校验）→ 写入本地 `output/`，并按配置同步 `scripts/sync_ima.py` / `scripts/sync_obsidian.py`。

> **分支判定（Layer 1 之后）**：小红书 / 抖音等平台的笔记分**视频**与**图文（图集）**两类。
> 图文笔记 `type=="normal"` 且无音视频轨，yt-dlp 会报 `No video formats found`，**四层视频管道不适用**。
> 此时改走 `scripts/fetch_image_note.py`：解析页面 SSR 状态（无需 Cookie）→ 下载配图 → 渲染 Markdown。
> 脚本可自动判定：遇视频笔记抛 `ERR_NOTE_IS_VIDEO`，提示转回 `run.py` 视频管道。

> **微信视频号的降级（视频流不可得时）**：`weixin.qq.com/sph/<id>` 会 302 到
> `channels.weixin.qq.com/finder-preview/pages/sph?id=<id>`，该页是纯前端 SPA——
> **静态 HTML 无内容，但 JS 执行后的 DOM 带完整元数据**（正文 / 话题 / 发布时间 /
> 作者 / 头像 / 封面 / 互动数），而**视频流不在 Web 侧**（页面只有"扫码去微信观看"
> 二维码，DOM 无 `<video>`，yt-dlp 也报 `Unsupported URL`）。
> 此时不要整条失败：改走 `scripts/fetch_wechat_meta.py`，用本机 Edge/Chrome 无头渲染
> `--dump-dom`（**不装 playwright、不需要登录**）拿到元数据并落封面/头像，产出
> 「文案完整、音视频待补全」的笔记；视频本体按笔记第四节的三条路径补齐。

> **无 LLM 密钥时（Layer 3 后半不可用时）**：`run.py` 不再整体失败——转写产物先落盘
> `transcript.json/txt`，总结降级为「文字稿首段截断 + PREP 待补全」，笔记照常生成，
> 错误记入验证报告。产物目录为 `output/<平台缩写>_<ID前8位>_<标题前12字>/笔记.md` + `_work/`。

> **无字幕 / 无 ASR 时的降级（Layer 3 不可用）**：若视频无字幕轨（可用
> `yt-dlp --list-subs` 确认）且 ASR 后端不可得（无 API Key、无本地 Whisper），
> **不要中止**，改走 `scripts/fetch_danmaku.py`：弹幕带视频内时间戳，可做密度时间轴、
> 高频词与段落样本分析，据此产出"内容结构 + 观众情绪"笔记。
> 此时交付物应包含：完整视频/音频（供后续补转写）、元数据、简介、弹幕推断的结构表、
> 热门评论；**文字稿段明确标注"待补全"**，且所有推断结论须标为「合理推论」。

建议的统一入口为 `scripts/run.py`（串联上述步骤、支持批量与降级）：

```bash
# 单条 / 多条链接；--no-sync 表示只落本地、不自动同步 ima / Obsidian
python scripts/run.py "https://www.bilibili.com/video/BVxxxx" --no-sync
python scripts/run.py "URL1" "URL2" --config config/config.yaml --output ./output

# 单独跑某一步（均在**技能根目录**执行；脚本会自动把 scripts/ 加入模块搜索路径）
python scripts/deps_check.py                    # 依赖自检（先跑它）
python scripts/fetch_image_note.py "小红书图文URL" --out output/XHS_xxx
python scripts/fetch_wechat_meta.py "https://weixin.qq.com/sph/xxx" output/WX_xxx
python scripts/sync_obsidian.py "output/xxx/笔记.md" --sub "raw/文史地哲" --name "raw_xxx.md"
```

> 本机执行环境（隔离 venv / ffmpeg / 本地 Whisper 模型目录 / 无头浏览器路径 / Cookie 导出方式等）
> 见 `references/runtime-env.md`；换机器部署前先对照该文件核对路径。

## 产物约定

- 根目录：默认 `./output`，**相对路径以技能包所在目录为基准**（不看 cwd），
  即落在包外的 `output/`——这样打包时不会把抓取产物混进 zip。要显式指定就传绝对路径。
- 子目录：`output/<平台缩写>_<内容ID前8位>_<标题前12字>/`，平台缩写见 `PLATFORM_ABBR`
  （XHS / BILI / DY / YT / WX / KS / WB）。
- 笔记文件名固定为 `笔记.md`；原始素材（视频 / 音频 / info.json / transcript / 封面）放在同级 `_work/`。
- 元数据表必须含「来源 / 视频发布日期 / 内容存档日期」三行，否则 `validate_output.py` 会报错。
- ⚠️ `output/` 在技能目录内，**打包发布前先清空或排除它**——否则历次抓取产物会被打进 zip。

## Scripts

| 脚本 | 职责 |
|------|------|
| `scripts/run.py` | 编排入口：串联四层管道，支持批量链接、分级降级、费用统计与验证报告 |
| `scripts/detect_platform.py` | 平台识别与链接校验 |
| `scripts/downloader/wechat.py` | 微信视频号下载适配器（wx_channels_download / Apify 备选） |
| `scripts/downloader/xiaohongshu.py` | 小红书下载适配器（yt-dlp 首选；social-media-copilot 接口 / Apify 为可选降级） |
| `scripts/downloader/bilibili.py` | B站下载适配器（yt-dlp + B站 API 元数据增强） |
| `scripts/downloader/generic.py` | yt-dlp 通用下载器（抖音 / YouTube / 快手等） |
| `scripts/extract_audio.py` | FFmpeg 音频提取 |
| `scripts/transcribe.py` | 语音转文字：**faster-whisper 本地离线（推荐，零 API Key）** / OpenAI Whisper API / Whisper / SiliconFlow / DashScope，含降级与逐段语言检测 |
| `scripts/summarize.py` | LLM 总结 + PREP 结构化分析 + 文字稿分段 |
| `scripts/fetch_comments.py` | 评论采集（MediaCrawler，Top5 热门） |
| `scripts/fetch_danmaku.py` | **无字幕降级路径**：下载弹幕并做时间轴密度分析、高频词与段落样本推断，供无字幕/无 ASR 密钥时生成"结构 + 情绪"笔记（结论须标注为推论） |
| `scripts/fetch_image_note.py` | **图文笔记路径**：小红书等图文（图集）笔记抓取与渲染——解析页面 SSR 状态（无需 Cookie），落图并生成 Markdown；遇视频笔记返回 `ERR_NOTE_IS_VIDEO` 转走视频管道 |
| `scripts/fetch_wechat_meta.py` | **微信视频号元数据降级**：无头浏览器渲染 finder-preview 页，解析正文/话题/发布时间/作者/头像/封面/互动数并生成笔记（无需登录与外部服务）。视频流仍不可得，按 `ERR_WECHAT_NO_VIDEO` 标注待补全 |
| `scripts/render_markdown.py` | 按模板渲染 Markdown 笔记 |
| `scripts/validate_output.py` | Markdown 排版与字段校验（含 Markdown Lint） |
| `scripts/sync_ima.py` | ima 知识库同步（OpenAPI）。**更省事的路径是用 ima MCP 连接器**（免 API Key），见 `references/ima-openapi.md` 第 5 节 |
| `scripts/sync_obsidian.py` | Obsidian Vault 文件写入（直接文件系统复制）。支持 `--sub <子目录>` 与 `--name <文件名>`，用于满足 Vault 的 `raw/<主题>/` + `raw_` 前缀规范 |
| `scripts/deps_check.py` | 依赖自检（ffmpeg / yt-dlp / whisper / Python 包） |
| `scripts/common.py` | 共享工具：配置加载、日志、HTTP 辅助 |

## References（按需加载）

- `references/platform-apis.md`：各平台下载接口、字段、协议、Cookie 要求。
- `references/runtime-env.md`：**本机运行环境与踩坑清单**——隔离 venv 路径、ffmpeg、本地 Whisper 模型目录、无头浏览器、Cookie 导出、常见报错速查。换机器或首次部署先读它。
- `references/obsidian-vault.md`：Obsidian 仓库约定（`AGENTS.md` 铁律）与本技能的落盘规范。写 Vault 前必读。
- `references/ima-openapi.md`：ima OpenAPI 字段、双自定义 HTTP 头鉴权，以及走 ima MCP 连接器免密钥上传的实测流程。
- `references/prompt-templates.md`：总结 / PREP / 分段 / 标签规范化等 LLM Prompt 细节。
- `references/error-codes.md`：分级错误码与处理策略速查。

## Configuration

生效配置是 `config/config.yaml`；`config/config.example.yaml` 只是模板。

- **加载优先级**（`common.DEFAULT_CONFIG`）：`config/config.yaml` 存在就读它，不存在才回退 example。
  不带 `--config` 跑 `run.py` 时走的正是这条路径——改配置后无需加参数即生效。
- **环境变量优先级更高**：`OBSIDIAN_VAULT_PATH`、`IMA_CLIENT_ID`、`IMA_API_KEY`、`OPENAI_API_KEY`
  等一旦在环境中设置，会覆盖配置文件里的同名字段。
- 配置文件中只写 `${VAR}` 占位，**禁止硬编码密钥**；未解析的占位符会被替换为空串（密钥缺失时对应通道自动跳过）。
- 换机器部署时，除密钥外还要改 `knowledge_base.obsidian.vault_path`（Vault 真实路径）与
  `knowledge_base.obsidian.sub_folder`（目标子目录，可用 `--sub` 临时覆盖）。

> ⚠️ `obsidian.enabled: true` 时，每次 `run.py` 都会自动写 Vault。若只想本地产出，加 `--no-sync`。
> 走进 Obsidian 仓库前先读 `references/obsidian-vault.md`——该仓库的 `AGENTS.md` 对
> 「他人内容必须放 `raw/<主题>/` 且文件名加 `raw_` 前缀」有强制要求。

## Safety & Compliance

- 仅用于个人学习与知识归档，遵守各平台服务条款与版权规定。
- 外部下载仅允许白名单域名，下载后校验文件真实 MIME，丢弃非预期类型（防 SSRF / 恶意文件）。
- Cookie / 登录态仅从用户本地浏览器安全导出或环境变量注入，不写入日志、不随笔记导出。
- 批量处理时按平台施加速率限制与指数退避，降低被封禁风险。
