# 平台下载接口协议参考（references/platform-apis.md）

> 稳定的"知识"层：沉淀各平台下载接口、字段、协议与坑点。脚本实现以本文件为准，避免把几十个字段塞进 SKILL.md 或脚本正文。

## 1. 链接识别规则（Layer 1）

| 平台 | URL 特征 | 适配器 |
|------|----------|--------|
| 微信视频号 | `weixin.qq.com/sph/...`、`channels.weixin.qq.com/...` | `downloader/wechat.py` |
| 小红书 | `xiaohongshu.com/explore/...`、`xhslink.com/...` | `downloader/xiaohongshu.py` |
| B站 | `bilibili.com/video/BV...`、`b23.tv/...` | `downloader/bilibili.py` |
| 抖音 | `douyin.com/video/...`、`v.douyin.com/...` | `downloader/generic.py` |
| YouTube | `youtube.com/watch?v=...`、`youtu.be/...` | `downloader/generic.py` |
| 快手 / 微博 / TikTok | 预留扩展位 | `downloader/generic.py`（自动探测） |

识别失败时返回 `ERR_PLATFORM_UNRECOGNIZED`，跳过该条并提示用户检查链接格式。

## 2. 微信视频号（wechat）

> ⚠️ **实测结论优先**：Web 侧**拿不到视频流**。以下 2.1/2.2 属于"需要额外服务"的路线，
> 默认不可得；2.3 是本机实测可行的降级路径，`run.py` 已自动走它。

### 2.1 首选（需本地服务）：wx_channels_download

开源项目的 `/api/channels/parse_sph` 接口，传分享链接换视频直链；需在 `download.wechat_server`
（默认 `http://127.0.0.1:8080`）起本地服务。**服务没起时**脚本抛 `ERR_DOWNLOAD_FAILED`
并自动降级到 2.3，不会整条失败。

### 2.2 备选（需 APIFY_TOKEN，当前为占位实现）

Apify `agentflow~wechat-channels-video-downloader`：POST `https://api.apify.com/v2/acts/<actor>/runs`
提交任务（token 走 Authorization），再轮询 dataset。`downloader/wechat.py::_apify_fallback`
尚未实现轮询，会抛 `ERR_DOWNLOAD_FAILED` 提示手工补齐。

### 2.3 降级路径（实测可行）：无头渲染取元数据

- `weixin.qq.com/sph/<id>` → 302 → `channels.weixin.qq.com/finder-preview/pages/sph?id=<id>`。
- 该页是**纯前端 SPA**：静态 HTML 约 2.4 KB 无内容，JS 执行后 DOM 约 26 KB，**含全量元数据**
  （正文 / 话题 / 发布时间 / 作者 / 头像 / 封面 / 点赞·转发·收藏·评论数）。
- 视频流不在 Web 侧：DOM 无 `<video>`，页面只有「扫码去微信观看」二维码，yt-dlp 报 `Unsupported URL`。
- 取数方式：本机 Edge/Chrome `--headless=new --dump-dom --virtual-time-budget=12000`
  （**不装 playwright、不需要登录**），脚本 `scripts/fetch_wechat_meta.py`。
  渲染产物 < 5 KB 视为失败（`ERR_WECHAT_META_FAILED`）。
- ⚠️ **话题标签没有闭合的 `#`**：`#([^#\s]+)#` 匹配不到。正确做法是取正文末尾
  连续的一段 `#xxx`（正则 `((?:#[^\s#]+\s*)+)$`）再逐个抽取。
- 产物：文案完整、元数据齐全，音视频与文字稿标注「待补全」；错误码 `ERR_WECHAT_NO_VIDEO`。
- 视频本体若要补齐：起本地 `wx_channels_download` 服务 / Apify / 人工录屏，三选一。

## 3. 小红书（xiaohongshu）

- **首选**：`yt-dlp` 原生 `XiaoHongShu` 提取器，配合浏览器登录态 Cookie（`download.cookie_browser`，默认 `auto` 自动探测本机浏览器；也可用 `download.cookie_file` 指向 cookies.txt）直接下载，**无需任何外部服务**。短链 `xhslink.com` 由 yt-dlp 自动跟随跳转，`xsec_token` 参数原样保留即可。
  - ⚠️ **Cookie 现实约束**：Chrome/Edge **127+** 启用 App-Bound Encryption（Cookie 前缀 `v20`），yt-dlp 无法解密（issue #10927），且浏览器运行时其 Cookie 库被独占锁定。**可靠做法**是在浏览器内用 *Get cookies.txt LOCALLY* 类扩展导出该站点 cookies.txt，路径写入 `download.cookie_file`（优先级高于 `cookie_browser`）。
- **图文笔记（重要分支）**：小红书大量笔记是**图集而非视频**（`type == "normal"`，无 `video.media.stream`）。此时 yt-dlp 报 `No video formats found`，四层视频管道不适用，**改走 `scripts/fetch_image_note.py`**：解析笔记页 SSR 内嵌 `window.__INITIAL_STATE__`（**无需 Cookie**）→ 取标题/正文/标签/互动数/配图直链 → 下载配图 → 渲染 Markdown。该脚本会自判类型，遇视频笔记抛 `ERR_NOTE_IS_VIDEO`。
- **备选（可选）**：`social-media-copilot`（社媒助手）等解析接口，**仅当配置了 `download.xiaohongshu_endpoint` 且 yt-dlp 失败时**才会尝试。⚠️ 注意其**开源版（main 分支）是纯浏览器扩展、不提供 HTTP API**；提供 HTTP 的是 **server 分支**（端口 3000，仅 `/cookies` 与 `/request` 两个接口，且需配合浏览器插件端运行），与本文件早期写死的 `/api/video` 一档契约并不一致，接入需自备适配层。
- **兜底**：Apify `RedNote Video Downloader`（需 `APIFY_TOKEN`，按 dataset 轮询）。
- **视频笔记的元数据补充（实测）**：yt-dlp 拿到的 `info.json` **不含作者、发布时间、赞藏评转、IP 属地**。
  这些字段同样可以从笔记页 SSR 的 `window.__INITIAL_STATE__` 里解析出来（**无需 Cookie**），
  与 `fetch_image_note.py` 的解析逻辑同源。视频笔记走完下载后，用同一套 SSR 解析补元数据。
- **评论**：`fetch_comments.py` 走 MediaCrawler（未随包分发）；接口需登录签名（`x-s` / `x-t`），
  不可用时按 `ERR_COMMENTS_FAILED` 跳过评论段，笔记里标注「评论待采集」而非静默省略。

## 4. B站（bilibili）

- **下载**：`yt-dlp` 直接下载，支持 DASH / FLV。
- **元数据增强**：B站 API 获取播放量、弹幕数、点赞等 richer 字段。
- **字段**：`bvid`、`aid`、`title`、`desc`、`owner.name`、`stat.view`、`stat.like`、`stat.danmaku`、`pubdate`、`tags`。

## 5. 抖音 / YouTube（generic）

- 统一使用 `yt-dlp`（`uvx yt-dlp@latest` 保证提取器为最新）。
- **抖音**：部分需要浏览器登录态（Cookie），通过配置 `download.cookie_browser` 借用 Chrome 登录态或注入 Cookie 文件。
- **YouTube**：`yt-dlp` 原生支持；字幕/元数据随视频一并获取。

## 6. 通用约束

- 所有网络请求设置超时（默认 30s）与重试（最多 3 次，指数退避）。
- 需登录态平台支持 Cookie 配置或浏览器登录态借用；建议集成代理池（环境变量 `HTTP_PROXY` / `HTTPS_PROXY`）。
- 下载前对 URL 做白名单域名校验（见 SKILL.md 安全约定），拒绝非白名单域名，防 SSRF / 钓鱼。
- 下载后校验文件真实 MIME（视频 / 音频），丢弃非预期类型。
