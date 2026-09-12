# 分级错误码与处理策略（references/error-codes.md）

> 把计划书第五章的分级错误处理固化为错误码表，脚本统一返回结构化错误，便于上层降级与报告。

| 错误码 | 含义 | 处理策略 | 用户提示 |
|--------|------|----------|----------|
| `ERR_PLATFORM_UNRECOGNIZED` | 链接无效 / 无法识别平台 | 中止当前任务，跳过继续处理下一条 | "无法识别该链接的平台来源，请检查链接格式" |
| `ERR_DOWNLOAD_FAILED` | 视频下载失败 | 尝试备用下载方案；仍失败则中止该条 | "视频下载失败，已尝试 N 种方案。原因：[具体原因]" |
| `ERR_ASR_FAILED` | ASR 转写失败 | 降级至备用 ASR 引擎（Whisper → 云端 ASR） | "本地转写失败，已自动切换至云端引擎" |
| `ERR_COMMENTS_FAILED` | 评论采集失败 | 跳过评论模块，其余正常生成 | "该平台评论数据暂不可获取，已跳过" |
| `ERR_SUMMARY_FAILED` | LLM 总结失败 | 使用简化模板（仅保留文字稿） | "AI 总结服务暂不可用，已生成基础版笔记" |
| `ERR_SYNC_IMA` | ima 知识库同步失败 | 保留本地文件，重试 3 次 | "知识库同步失败，文件已保存至本地" |
| `ERR_SYNC_OBSIDIAN` | Obsidian 写入失败 | 保留本地文件，提示检查 Vault 路径 | "Obsidian 写入失败，文件已保存至本地" |
| `ERR_DEPS_MISSING` | 依赖缺失 | 中止并给出安装指引 | "缺少依赖：[依赖名]，请先安装" |
| `ERR_NETWORK` | 网络超时 / 重试耗尽 | 指数退避后重试；仍失败降级 | "网络请求失败，已重试 N 次" |
| `ERR_SECURITY` | 域名 / 类型校验不通过 | 拒绝该下载，跳过 | "链接域名不在白名单或文件类型异常，已拒绝" |
| `ERR_NOTE_IS_VIDEO` | 图文笔记路径收到含视频轨的笔记 | 转走视频管道（`run.py`） | "该笔记含视频，已切换至视频管道处理" |
| `ERR_NOTE_NO_IMAGES` | 图文笔记未解析到配图 | 中止该条并保留已取元数据 | "未找到该笔记的配图，请检查链接是否有效" |
| `ERR_NOTE_FETCH_FAILED` | 图文笔记页面抓取/解析失败 | 提示可能被风控拦截或笔记已删除 | "笔记页面解析失败（可能需登录或被风控），请稍后重试" |
| `ERR_WECHAT_NO_VIDEO` | 微信视频号：Web 侧不提供视频流（预览页仅二维码，无 `<video>`，yt-dlp `Unsupported URL`） | **不中止**：改走 `fetch_wechat_meta.py` 出元数据笔记，视频/音频/文字稿标"待补全" | "已抓取文案与元数据；视频流需 wx_channels_download / Apify / 人工录制补齐" |
| `ERR_WECHAT_NO_BROWSER` | 本机无 Edge/Chrome/Brave/Chromium，无法渲染 SPA | 提示装浏览器，或转外部解析服务 | "未找到可无头渲染的浏览器，无法取视频号元数据" |
| `ERR_WECHAT_META_FAILED` | 视频号预览页渲染/解析失败（DOM 过小、风控、无正文） | 提示稍后重试或换外部服务 | "视频号元数据解析失败，请稍后重试" |

## Cookie 相关失败（`ERR_DOWNLOAD_FAILED` 子类）

| 原始报错 | 原因 | 处置 |
|---|---|---|
| `Could not copy Chrome cookie database` | 浏览器正在运行，Cookie 库被独占锁定 | 完全退出该浏览器后重试；或改用 `download.cookie_file` |
| `Failed to decrypt with DPAPI`（issue #10927） | Chrome/Edge 127+ 启用 App-Bound Encryption（`v20`），yt-dlp 无法解密 | **必须**改用 cookies.txt：浏览器装 *Get cookies.txt LOCALLY* 类扩展导出，路径写入 `download.cookie_file` |
| `No video formats found` | 该内容需登录态 | 配置 `download.cookie_file` 或 `download.cookie_browser` 后重试 |

> `download.cookie_browser: auto` 会自动探测本机已安装浏览器（Edge / Chrome / Brave / Firefox …）。
> **优先级**：`cookie_file`（cookies.txt）> `cookie_browser`。前者是绕过 App-Bound 加密的唯一可靠方式。

## 告警码（不中止流程，仅记入报告）

| 告警码 | 含义 | 处置 |
|---|---|---|
| `WARN_TRANSCRIPT_NOT_SAVED` | 转写产物落盘失败（`transcript.json/txt`） | 检查 `output/.../_work/` 写权限；已付费算力可能丢失，建议重跑 |
| `VALIDATION: …` | `validate_output.py` 校验不通过（缺字段 / 层级跳跃 / 表格列数不一致 / 代码块未闭合 / 残留模板占位符） | 按提示修笔记；状态记为 `ok_with_warnings` |

## 报告状态

| 状态 | 含义 |
|---|---|
| `ok` | 全流程通过，无校验问题 |
| `ok_with_warnings` | 笔记已产出但有校验告警（不影响使用） |
| `ok_partial` | **降级产出**：如微信视频号只拿到元数据与文案，音视频/文字稿标"待补全" |
| `failed` | 该条彻底失败，错误见报告 |
| `skipped` | 未识别平台等，直接跳过 |

## 通用原则

- 所有网络请求：超时默认 30s，重试最多 3 次，指数退避。
- 单条失败不影响批量其余任务；结束时生成验证报告（成功 / 失败 / 跳过数量，各文件路径）。
- 安全类错误（`ERR_SECURITY`）一律拒绝，不降级执行。
