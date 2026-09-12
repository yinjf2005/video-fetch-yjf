# Obsidian 落盘规范（references/obsidian-vault.md）

> 把笔记写进用户的 Obsidian Vault 前**必读**。本文件是 `sync_obsidian.py` 的行为依据。

## 1. 仓库定位

- 本机唯一 Vault：`D:\Obsidian`（由 `%APPDATA%\obsidian\obsidian.json` 注册，vault id `90c07b64dc15583f`）。
- 配置写在 `config/config.yaml` 的 `knowledge_base.obsidian.vault_path`；环境变量 `OBSIDIAN_VAULT_PATH` 优先级更高。
- 若换机器或 Vault 不止一个，先读 `obsidian.json` 确认真实路径，不要猜。

## 2. 落盘路径铁律（来自仓库根目录 `AGENTS.md`）

**唯一判据：这篇是谁写的。**

| 内容来源 | 投递位置 | 文件名 |
|---|---|---|
| **别人写的**（网页剪藏、视频转写稿、他人文章、PDF、录音稿） | `raw/<主题>/` | 必须带 `raw_` 前缀 |
| **自己写的**（一闪念、半成品、随手记、未成型草稿） | `_inbox/` | 无前缀要求 |
| 最终产出（脚本、成稿文案） | `产出/<子目录>/` | — |
| 来不及分类的碎片 | `_inbox/`（**必须清空，不许隔周留存**） | — |

**本技能产出的笔记一律算「别人写的」**——内容源自第三方平台作者，不是用户原创。
因此默认应落 `raw/<主题>/` 且文件名带 `raw_` 前缀。

### 8 个固定主题（不得新建「交叉」主题）

```
计算机AI、经济金融、地产行业、政治法律、社会议题、文史地哲、数学物理、数据反馈
```

跨主题的素材按「将来在什么场景下会用到它」选**一个**主主题落盘，跨主题联系交给 `[[ ]]` 双链和 tags。
**新增主题必须同时在 `raw/` 和 `wiki/` 下建同名目录并登记，禁止擅自新建。**

## 3. 命令用法

```bash
# 标准写法：显式指定子目录与目标文件名（推荐，符合 raw_ 前缀规范）
python scripts/sync_obsidian.py "output/XHS_6a97cd01_坠落2真实评价/笔记.md" \
    --sub "raw/文史地哲" --name "raw_坠落2影评_幻云的观影日记.md"

# 用配置文件里的 sub_folder（默认"视频笔记"），不改名
python scripts/sync_obsidian.py "output/xxx/笔记.md"
```

- `--sub` 覆盖 `knowledge_base.obsidian.sub_folder`；未传则读配置。
- `--name` 指定写入后的文件名；未传则用源文件名（`笔记.md`，**在 Vault 里是坏名字**，
  全局搜索会出一堆同名文件，除非用 `--sub` 隔离，否则务必传 `--name`）。
- 目录参数也支持：传目录则批量复制其中所有 `*.md`（此时不能传 `--name`）。
- 目录不存在会自动创建。

## 4. 执行前必须做的确认

按全局高危操作规则，**写入 Vault 属于写用户文件**，落盘前先向用户确认两件事：

1. **主题子目录**（8 选 1）。归类有争议、或两种以上都说得通时，
   **必须先列出候选让用户选，不得自行选一种落地**（`AGENTS.md` 明令）。
2. **文件名**（`raw_` 前缀 + 内容命名，不照搬原始标题；原始标题可记在正文备注里）。

## 5. 落盘后校验

写完必须回读目标文件确认内容与字节数一致，不能只看脚本打印的 `[OK]`。

```bash
# 校验示例
python -c "from pathlib import Path; a=Path(r'output/x/笔记.md').read_bytes(); b=Path(r'D:\Obsidian\raw\文史地哲\raw_x.md').read_bytes(); print('一致' if a==b else '不一致'); print(len(b))"
```
