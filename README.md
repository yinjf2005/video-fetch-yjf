# video-fetch-yjf — 多平台视频/图文内容抓取与归档 Skill

> 版本 1.3.0。行为规范以 `SKILL.md` 为准，本文件是速览。

将多平台内容（微信视频号 / 小红书视频与图文 / B站 / 抖音 / YouTube）一键转化为结构化工整的 Markdown 知识笔记，并可选同步至 ima / Obsidian 知识库。

## 能力

- 多平台抓取（微信视频号、小红书、B站、抖音、YouTube，预留快手/微博/TikTok）
- 语音转文字：**faster-whisper 本地离线（推荐，零 API Key）** / OpenAI Whisper API / Whisper / SiliconFlow / DashScope，带降级与逐段语言检测
- 智能总结（LLM + PREP 法则结构化小结）
- 评论采集（Top5 热门）
- 结构化输出（规范命名的 `.md`，排版工整）
- 知识库对接（ima / Obsidian）

### 三条降级路径（实测固化）

| 场景 | 行为 |
|---|---|
| 小红书**图文**笔记（无音视频轨） | 走 `fetch_image_note.py`：SSR 解析（无需 Cookie）→ 落图 → 渲染 Markdown |
| 微信视频号**拿不到视频流** | 走 `fetch_wechat_meta.py`：无头浏览器渲染取元数据，产出「文案完整 + 音视频待补全」笔记 |
| **无 LLM 密钥** | 转写产物先落盘，总结降级为「文字稿首段 + PREP 待补全」，笔记照常产出 |

## 目录结构

```
video-fetch-yjf/
├── SKILL.md
├── references/        # 平台接口 / 运行环境 / Obsidian 规范 / ima OpenAPI / Prompt 模板 / 错误码
├── scripts/           # detect_platform / downloader / extract_audio / transcribe / summarize /
│                      # fetch_comments / fetch_danmaku / fetch_image_note / fetch_wechat_meta /
│                      # render_markdown / validate_output / sync_ima / sync_obsidian / run.py
├── templates/         # note_template.md / summary_prompt.txt
├── config/            # config.yaml（生效） / config.example.yaml（模板）
└── README.md
```

## 快速开始

```bash
# 1. 依赖自检
python scripts/deps_check.py

# 2. 配置：config/config.yaml 已存在且默认生效；密钥走环境变量，勿硬编码
export OPENAI_API_KEY=sk-xxx                     # 可选：仅总结环节需要
export IMA_CLIENT_ID=... IMA_API_KEY=...         # 可选
export OBSIDIAN_VAULT_PATH=D:\Obsidian           # 可选

# 3. 运行（--no-sync 表示只落本地，不自动写 ima / Obsidian）
python scripts/run.py "https://www.bilibili.com/video/BVxxxx" --no-sync
```

换机器部署先读 `references/runtime-env.md`（venv / ffmpeg / 本地 Whisper 模型 / 无头浏览器 / Cookie）。

## 配置说明

- 生效配置：`config/config.yaml`；`config.example.yaml` 只是模板。
- 不带 `--config` 时 `run.py` 读 `config/config.yaml`（存在则优先，否则回退 example）。
- 环境变量优先级高于配置文件同名字段。
- 所有密钥均通过 `${ENV}` 占位注入；下载域名受白名单约束（防 SSRF）。

## 安全与合规

- 仅用于个人学习与知识归档，遵守各平台服务条款与版权规定。
- 下载前校验域名白名单，下载后校验文件真实 MIME。
- Cookie / 登录态仅从本地浏览器安全导出或环境变量注入，不落日志、不随笔记导出。

## 测试与校验

- 端到端：五大平台各 1 条链接（见计划书第九章验收标准）。
- 排版：生成的 `.md` 经 `scripts/validate_output.py` 校验（字段、层级、表格列数、模板占位符）。
