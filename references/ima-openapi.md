# ima OpenAPI 对接参考（references/ima-openapi.md）

> 专项说明 ima 知识库同步所需的字段、鉴权与上传流程。脚本实现见 `scripts/sync_ima.py`。

## 1. 凭证获取

1. 访问 `https://ima.qq.com/agent-interface` 生成 **Client ID** 与 **API Key**。
2. 通过环境变量注入（不要硬编码）：
   - `IMA_CLIENT_ID`
   - `IMA_API_KEY`

## 2. 鉴权要点（关键差异）

ima 的鉴权**不使用标准 `Authorization` 头**，而是使用两个自定义 HTTP 头：

| 头名 | 值 |
|------|----|
| `X-IMA-Client-Id` | `${IMA_CLIENT_ID}` |
| `X-IMA-Api-Key` | `${IMA_API_KEY}` |

调用前务必在请求头显式设置这两个头，否则返回 401。

## 3. 上传流程

1. 渲染生成 `.md` 笔记文件（见 `scripts/render_markdown.py`）。
2. 调用 ima OpenAPI 上传接口，将文件传至指定知识库（默认 `target_kb: "default"`）。
3. 可选「文本转笔记」模式：上传后让 ima 自动索引，便于后续语义检索。
4. 建议用 `scripts/sync_ima.py upload-dir` 批量上传整个输出目录。

## 4. 字段与错误处理

- 上传失败按 `references/error-codes.md` 的 `ERR_SYNC_IMA` 处理：保留本地文件，重试最多 3 次后退化为本地归档并提示用户。
- 凭据缺失（`IMA_CLIENT_ID` / `IMA_API_KEY` 未设置）时跳过同步，仅输出到本地 `./output/`。
- 同步前校验 Markdown 文件存在且非空；禁止上传临时缓存（视频 / 音频原始文件）。

## 5. 走 ima MCP 连接器时的上传流程（实测 · 免 API Key）

若会话里已连接 **ima-mcp**（`~/.workbuddy/connectors`），无需 Client ID / API Key，
三步即可把本地 `.md` 入库：

1. `create_media(knowledge_base_id, file_name, file_ext, file_size, content_type)`
   → 返回 `media_id` 与 `cos_credential`（STS 临时凭证：`secret_id/secret_key/token/
   bucket_name/region/cos_key`）。**`file_size` 必须与待传文件字节数完全一致**；
   `content_type` 按扩展名精确填（`md` → `text/markdown`），不接受 `octet-stream` 兜底。
2. **把文件内容 PUT 到 COS**。
3. `add_knowledge(knowledge_base_id, media_id, folder_id?)` → 入库。

### 踩坑（重要）

- **手写 COS 签名（`q-sign-algorithm=sha1`）实测 403 `SignatureDoesNotMatch`**，
  即使 `StringToSign` 逐字节比对一致（SDK 会把 `host`/`content-type` 等纳入
  `q-header-list`，与手写空表不一致）。
  → **直接用官方 SDK**：`pip install cos-python-sdk-v5`，
  `CosConfig(Region, SecretId, SecretKey, Token, Scheme='https')`
  + `CosS3Client.put_object(Bucket, Body=<bytes>, Key=<cos_key>, ContentType=...)`，一次成功。
- 凭证有效期约 12 小时（`start_time`→`expired_time`），失效需重新 `create_media`。
- **凭证含 `secret_key`/`token`，临时脚本与 JSON 用完必须删除**，不得留在工作区或入库。
- `folder_id` 用 `get_knowledge_list` 拿到的 `folder_info.folder_id`（形如
  `folder_7502619572446859`）；不给则落知识库根目录。

### 目录约定（用户主库）

`ima主库`（`7501593008155833`）下有 `01_进行中项目库` / `02_高频调用库` /
`03_已归档参考库` / `收件箱` 四个文件夹；新抓取的笔记默认入**收件箱**待用户自行归类。
