# 本机运行环境与踩坑清单（references/runtime-env.md）

> 实测环境（2026-09，Windows）。换机器部署前逐条核对；带 ⚠️ 的是踩过的坑。

## 1. Python 与依赖

| 项 | 值 |
|---|---|
| 隔离 venv | `C:\Users\yinjf\.workbuddy\binaries\python\envs\default` |
| 解释器 | `…\envs\default\Scripts\python.exe`（**不要用系统 Python**） |
| yt-dlp | 装在 venv 内，版本 `2026.08.19` |
| faster-whisper | `1.2.1`（CT2 int8，CPU） |
| ffmpeg | venv `Scripts\ffmpeg.exe`（`ffprobe.exe` **未安装**，当前脚本不依赖） |
| PyYAML | 建议装；缺失时 `common.py` 会退化为内置极简 YAML 解析器（够用但不支持复杂语法） |

`common.ensure_tools_on_path()` 会把 venv `Scripts` 目录、`~/.workbuddy/binaries/ffmpeg/bin`
插到 `PATH` 前面，因此**不手动配 PATH 也能找到 ffmpeg/yt-dlp**。
额外目录可用环境变量 `VIDEO_FETCH_TOOL_BIN` 追加（`os.pathsep` 分隔）。

## 2. 本地离线 ASR（零 API Key，推荐默认路线）

- 模型目录：`C:\Users\yinjf\.workbuddy\binaries\whisper\large-v3-turbo`
  （`mobiuslabsgmbh/faster-whisper-large-v3-turbo`，约 **1.55 GB**）。
- 留空 `asr.faster_whisper.model_dir` 时默认就是该路径；也可用 `WHISPER_MODEL_DIR` 覆盖。
- ⚠️ **HuggingFace 主站实测 502 不可达**，用镜像 `https://hf-mirror.com` 下载。
- ⚠️ **中英混说必须开 `segment_lang_detect: true`**。否则整段被强制判为一种语言，
  另一种语言会被「幻觉式硬译」成乱码（实测把英文片名翻成无意义中文）。
  开启后走 VAD 分段 + 逐段语言检测，各归其位。
- 转写产物**先落盘** `transcript.json` / `transcript.txt` 再进 LLM，
  避免 LLM 失败时已消耗的算力白费。

## 3. 浏览器与 Cookie

- 无头渲染（微信视频号降级用）优先用本机 Edge：
  `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`，其次 Chrome / Brave / Chromium。
  脚本按 `%PROGRAMFILES%` 等环境变量探测，**不建议装 playwright/selenium**。
- ⚠️ **Edge/Chrome 152 的 Cookie 是 App-Bound Encryption（v20）**，yt-dlp 走 DPAPI 解密必失败；
  且浏览器运行时 Cookie 库被独占锁定。可靠做法：浏览器内用 *Get cookies.txt LOCALLY*
  导出 `cookies.txt`，写进 `download.cookie_file`（优先级高于 `cookie_browser`）。
- 小红书评论接口需登录签名（`x-s` / `x-t`），无 Cookie 时不采集，按 `ERR_COMMENTS_FAILED` 跳过。

## 4. 微信视频号

- `weixin.qq.com/sph/<id>` → 302 → `channels.weixin.qq.com/finder-preview/pages/sph?id=<id>`。
- 该页是**纯前端 SPA**：静态 HTML 仅约 2.4 KB，JS 执行后 DOM 约 26 KB 且含全量元数据。
- ⚠️ **视频流不在 Web 侧**：DOM 里没有 `<video>`，页面只有「扫码去微信观看」二维码，
  yt-dlp 报 `Unsupported URL`。所以**不要指望 Web 管道拿到视频**。
- 渲染命令（无需登录、无需 playwright）：
  `msedge --headless=new --disable-gpu --no-sandbox --virtual-time-budget=12000 --dump-dom <URL>`
  渲染产物小于 5 KB 即判失败（抛 `ERR_WECHAT_META_FAILED`）。
- ⚠️ **视频号话题标签没有闭合的 `#`**，用 `#([^#\s]+)#` 匹配不到；
  正确做法是取正文末尾连续的一段 `#xxx` 再逐个抽取。
- 视频本体若要补齐：本地 `wx_channels_download` 服务 / Apify / 人工录屏三选一。

## 5. 微信/本地服务的异常类型

⚠️ 本地解析服务没起时抛的是 `ConnectionResetError` / `ConnectionRefusedError`，
它们属于 `OSError` 而**不是** `urllib.error.URLError`。只捕获 `URLError` 会让异常穿透，
`run.py` 的降级分支根本进不去。已统一改为 `except (OSError, RuntimeError, KeyError, ValueError)`。

## 6. ima 同步

- OpenAPI 直连需 `IMA_CLIENT_ID` / `IMA_API_KEY`（两个自定义头 `X-IMA-Client-Id` / `X-IMA-Api-Key`）。
- ⚠️ **手写 COS 签名必 403**（差异在 `q-header-list` 要签 `host`/`content-type`），
  必须 `pip install cos-python-sdk-v5` 用官方 SDK 上传。详见 `references/ima-openapi.md` 第 5 节。
- 更省事的路线是直接用 ima MCP 连接器，免 API Key。

## 7. 已知缺口（未解决，遇到就按降级走）

| 缺口 | 现状与对策 |
|---|---|
| 小红书评论区 | 需 cookies.txt 或 MediaCrawler；无则跳过评论段，笔记里标注「评论待采集」 |
| 视频号视频本体 | Web 侧拿不到；走元数据降级，笔记里标注「音视频待补全」 |
| `OPENAI_API_KEY` 缺失 | 转写照常完成，总结降级为「文字稿首段 + PREP 待补全」，需人工补全 |
| 视频号/小红书 ASR 校正 | 专有名词（人名、片名、地名）ASR 易错，笔记末尾附「校正/存疑清单」供人工核对 |
