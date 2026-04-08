---
name: idol-skill
description: "将地下偶像的公开内容蒸馏为 AI Skill，支持创建、列出、更新、回滚偶像 Skill。"
argument-hint: "[create | list | update <slug> | rollback <slug> <version>]"
version: "1.1.0"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

# 偶像.skill

## 命令路由

根据用户输入匹配对应流程：

| 触发词 | 流程 |
|--------|------|
| `/idol-skill create`、"帮我创建一个偶像 skill"、"我想蒸馏一个偶像" | → [创建新偶像 Skill](#主流程创建新偶像-skill) |
| `/idol-skill list`、"列出所有偶像" | → [列出偶像](#流程列出偶像) |
| `/idol-skill update {slug}`、"更新偶像 {slug}" | → [更新偶像](#流程更新偶像) |
| `/idol-skill rollback {slug} {version}`、"回滚偶像 {slug}" | → [回滚偶像](#流程回滚偶像) |

---

## 工具使用规则

| 任务 | 使用工具 |
|------|---------|
| 微博采集 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/weibo_collector.py` |
| 评论采集 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/comment_collector.py` |
| 数据清洗 | `Bash` → `python3 ${CLAUDE_SKILL_DIR}/tools/data_cleaner.py` |
| 文件写入 | `Write` / `Edit` 工具 |
| 读取文件 | `Read` 工具 |
| 列出已有偶像 | `Bash` → `python3 -c "from tools.skill_writer import SkillWriter; ..."` |

**基础目录**：Skill 文件写入 `./idols/{slug}/`（相对于本项目目录）。

---

## 主流程：创建新偶像 Skill

### Step 1：基础信息录入

参考 `${CLAUDE_SKILL_DIR}/prompts/intake.md` 的问题序列，依次询问：

1. **偶像艺名 + 英文拼写**（必填，示例：`小花 hana`）
2. **偶像微博 ID**（必填，支持多个）
3. **补充信息**（可选：团体、应援色、生日等）

每次只问一个问题。收集完后汇总确认再进入下一步。

### Step 2：数据采集

#### 2pre. Cookie 检查

在开始采集前，先检查是否已设置微博 Cookie：

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
import os
cookie = os.environ.get('WEIBO_COOKIE', '')
if cookie:
    print('COOKIE_OK')
else:
    print('COOKIE_MISSING')
"
```

如果输出 `COOKIE_MISSING`，**必须先向用户索要 Cookie**，告知：
```
微博数据采集需要登录 Cookie。请按以下步骤获取：

1. 在浏览器中打开 m.weibo.cn 并登录
2. 按 F12 打开开发者工具 → Network 标签
3. 刷新页面，点击任意请求
4. 在 Request Headers 中复制 Cookie 字段的完整内容

请把 Cookie 贴给我，或者在终端中输入：
! export WEIBO_COOKIE='你的cookie内容'
```

**拿到用户提供的 Cookie 后**，通过以下方式设置到环境变量中再继续采集。不要在没有 Cookie 的情况下执行采集步骤。

#### 2a. 微博采集

使用 Python 工具采集微博数据：

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.weibo_collector import WeiboCollector
from tools.config_manager import IdolConfig

config = IdolConfig(
    idol_name='{idol_name}',
    slug='{slug}',
    idol_weibo_ids=[{idol_ids}],
    since_date='{since_date}',
)
config.ensure_dirs()

collector = WeiboCollector(config)  # 需要有效 Cookie（WEIBO_COOKIE 环境变量或 config.cookie）

# 采集偶像微博（增量保存，断点续爬）
idol_weibos = collector.collect_all_idol_weibos()

print(f'采集完成：{len(idol_weibos)} 条偶像微博')
"
```

#### 2b. 评论采集

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.comment_collector import CommentCollector
from tools.config_manager import IdolConfig
import json

config = IdolConfig(
    idol_name='{idol_name}',
    slug='{slug}',
    idol_weibo_ids=[{idol_ids}],
    comment_max_count=200,
)

collector = CommentCollector(config)

# 加载之前采集的微博
with open(config.knowledge_dir() + '/weibo/idol_weibos.json', 'r') as f:
    idol_weibos = json.load(f)

# 采集评论（增量保存，断点续爬）
idol_comments = collector.collect_comments_for_weibos(idol_weibos, filename='idol_comments.json')

print('评论采集完成')
"
```

### Step 3：数据清洗与分流

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.data_cleaner import DataCleaner
from tools.style_corpus_builder import StyleCorpusBuilder
from tools.config_manager import IdolConfig
import json, os

config = IdolConfig(
    idol_name='{idol_name}',
    slug='{slug}',
    idol_weibo_ids=[{idol_ids}],
)

cleaner = DataCleaner()

# 加载数据
def load_json(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return [] if 'weibo' in path else {}

idol_weibos = load_json(config.knowledge_dir() + '/weibo/idol_weibos.json')
idol_comments = load_json(config.knowledge_dir() + '/comments/idol_comments.json')

# 清洗
idol_weibos = cleaner.clean_weibos(idol_weibos)
idol_comments = cleaner.clean_comments(idol_comments)

# 构建风格语料
corpus_builder = StyleCorpusBuilder(config)
style_corpus = corpus_builder.build(idol_weibos, idol_comments)
corpus_builder.save(style_corpus)

# 保存清洗后的完整数据
with open(config.data_dir() + '/raw_weibo.json', 'w', encoding='utf-8') as f:
    json.dump(idol_weibos, f, ensure_ascii=False, indent=2)

print(f'风格语料：{len(style_corpus)} 条')
"
```

### Step 4：LLM 风格分析

用 `Read` 工具读取：
- `${CLAUDE_SKILL_DIR}/prompts/style_analyzer.md` — 分析 prompt
- `idols/{slug}/data/style_corpus.json` — 风格语料

将风格语料（或取样）提供给 LLM，按 `style_analyzer.md` 的维度进行分析。
分析结果暂存为文本，供下一步使用。

同时，如果用户未提供偶像补充信息，尝试从微博语料中自动提取自我介绍信息（团体名、应援色、生日等）。

### Step 5：生成 style.md

用 `Read` 工具读取：
- `${CLAUDE_SKILL_DIR}/prompts/style_builder.md` — style.md 生成模板

根据模板和分析结果生成 style.md（5 层结构）。

生成前向用户展示摘要确认：
```
风格画像摘要：
  - 核心语气：{xxx}
  - 表达特征：{xxx}
  - 常用 emoji：{xxx}

确认生成？还是需要调整？
```

### Step 6：写入文件

用户确认后，用 `Write` 工具写入：

1. `idols/{slug}/style.md`
2. `idols/{slug}/meta.json`
3. `idols/{slug}/SKILL.md`（组合 style + 运行规则）

告知用户：
```
✅ 偶像 Skill 已创建！

文件位置：idols/{slug}/
触发词：/idol_{slug}

如果觉得语气哪里不对，直接说"她不会这样说"，我来调整。
```

---

## 流程：列出偶像

### 触发条件

当用户说以下内容时启动：
- `/list-idols`
- "列出所有偶像"
- "有哪些偶像 skill"

### 执行

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.skill_writer import SkillWriter
import json

writer = SkillWriter()
idols = writer.list_idols()

if not idols:
    print('目前还没有创建任何偶像 Skill。')
    print('使用 /create-idol 开始创建第一个吧！')
else:
    print(f'共 {len(idols)} 个偶像 Skill：')
    print()
    for idol in idols:
        group_info = f' ({idol[\"group\"]})' if idol.get('group') else ''
        print(f'  {idol[\"stage_name\"]}{group_info}')
        print(f'    slug: {idol[\"slug\"]}  |  版本: {idol[\"version\"]}  |  更新: {idol[\"updated_at\"][:10] if idol[\"updated_at\"] else \"未知\"}')
        print(f'    对话: /idol_{idol[\"slug\"]}  |  更新: /update-idol {idol[\"slug\"]}')
        print()
"
```

将输出直接展示给用户即可，无需额外处理。

---

## 流程：更新偶像

### 触发条件

当用户说以下内容时启动：
- `/update-idol {slug}`
- "更新偶像 {slug}"
- "给 {slug} 追加新数据"

### Step 1：验证偶像存在

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.skill_writer import SkillWriter
import json

writer = SkillWriter()
meta = writer.read_meta('{slug}')
if meta:
    print('IDOL_EXISTS')
    print(json.dumps(meta, ensure_ascii=False, indent=2))
else:
    print('IDOL_NOT_FOUND')
"
```

如果输出 `IDOL_NOT_FOUND`，告知用户该偶像不存在，建议使用 `/list-idols` 查看已有偶像或 `/create-idol` 创建新偶像。**流程结束。**

### Step 2：确认更新方式

向用户询问：
```
偶像 {stage_name} 当前版本：{version}

请选择更新方式：
1. 追加新微博数据（提供新的微博 ID 或使用已有 ID 增量采集）
2. 仅重新分析现有数据（不采集新数据，重新生成风格画像）

请选择 1 或 2：
```

### Step 3（仅方式 1）：增量数据采集

#### 3a. Cookie 检查

复用创建流程中的 Cookie 检查逻辑（参考 Step 2pre）。

#### 3b. 微博增量采集

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.weibo_collector import WeiboCollector
from tools.config_manager import IdolConfig

config = IdolConfig(
    idol_name='{idol_name}',
    slug='{slug}',
    idol_weibo_ids=[{idol_ids}],
    since_date='{since_date}',
)

collector = WeiboCollector(config)
idol_weibos = collector.collect_all_idol_weibos()
print(f'采集完成：{len(idol_weibos)} 条偶像微博')
"
```

#### 3c. 评论增量采集

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.comment_collector import CommentCollector
from tools.config_manager import IdolConfig
import json

config = IdolConfig(
    idol_name='{idol_name}',
    slug='{slug}',
    idol_weibo_ids=[{idol_ids}],
    comment_max_count=200,
)

collector = CommentCollector(config)

with open(config.knowledge_dir() + '/weibo/idol_weibos.json', 'r') as f:
    idol_weibos = json.load(f)

idol_comments = collector.collect_comments_for_weibos(idol_weibos, filename='idol_comments.json')
print('评论采集完成')
"
```

### Step 4：数据清洗与合并

参考 `${CLAUDE_SKILL_DIR}/prompts/merger.md` 的合并规则。

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.data_cleaner import DataCleaner
from tools.style_corpus_builder import StyleCorpusBuilder
from tools.config_manager import IdolConfig
import json, os

config = IdolConfig(
    idol_name='{idol_name}',
    slug='{slug}',
    idol_weibo_ids=[{idol_ids}],
)

cleaner = DataCleaner()

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return [] if 'weibo' in path else {}

idol_weibos = load_json(config.knowledge_dir() + '/weibo/idol_weibos.json')
idol_comments = load_json(config.knowledge_dir() + '/comments/idol_comments.json')

idol_weibos = cleaner.clean_weibos(idol_weibos)
idol_comments = cleaner.clean_comments(idol_comments)

corpus_builder = StyleCorpusBuilder(config)
style_corpus = corpus_builder.build(idol_weibos, idol_comments)
corpus_builder.save(style_corpus)

with open(config.data_dir() + '/raw_weibo.json', 'w', encoding='utf-8') as f:
    json.dump(idol_weibos, f, ensure_ascii=False, indent=2)

print(f'风格语料：{len(style_corpus)} 条')
"
```

### Step 5：备份当前版本

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.skill_writer import SkillWriter

writer = SkillWriter()
version = writer.backup_version('{slug}')
print(f'已备份当前版本：{version}')
"
```

### Step 6：LLM 风格重分析

用 `Read` 工具读取：
- `${CLAUDE_SKILL_DIR}/prompts/style_analyzer.md` — 分析 prompt
- `${CLAUDE_SKILL_DIR}/prompts/merger.md` — 合并规则
- `idols/{slug}/data/style_corpus.json` — 新风格语料
- `idols/{slug}/style.md` — 现有风格画像

按 `merger.md` 的规则，将新分析结果与现有 style.md 合并：
- **补充型**：新发现的特征 → 追加到对应层级
- **确认型**：与现有描述一致 → 不变
- **矛盾型**：与现有描述冲突 → 标记给用户确认

### Step 7：生成新版本

用 `Read` 工具读取 `${CLAUDE_SKILL_DIR}/prompts/style_builder.md`，根据合并后的分析结果生成新 style.md。

生成前向用户展示变更摘要：
```
风格画像更新摘要：
  - 新增特征：{xxx}
  - 变化特征：{xxx}（需确认）
  - 保持不变：{xxx}

确认更新？
```

### Step 8：写入文件

用户确认后：

1. 用 `Write` 工具写入新 `idols/{slug}/style.md`
2. 用 `Write` 工具写入新 `idols/{slug}/SKILL.md`
3. 递增版本号：

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.skill_writer import SkillWriter

writer = SkillWriter()
new_version = writer.increment_version('{slug}')
print(f'版本已更新至：{new_version}')
"
```

告知用户：
```
✅ 偶像 {stage_name} 已更新至 {new_version}！

变更内容：{变更摘要}
回滚命令：/idol-rollback {slug} {old_version}
```

---

## 流程：回滚偶像

### 触发条件

当用户说以下内容时启动：
- `/idol-rollback {slug} {version}`
- "回滚偶像 {slug} 到 {version}"
- "把 {slug} 恢复到之前的版本"

### Step 1：验证偶像存在

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.skill_writer import SkillWriter
import json

writer = SkillWriter()
meta = writer.read_meta('{slug}')
if meta:
    print('IDOL_EXISTS')
    print(f'当前版本：{meta.get(\"version\", \"v0\")}')
else:
    print('IDOL_NOT_FOUND')
"
```

如果输出 `IDOL_NOT_FOUND`，告知用户该偶像不存在。**流程结束。**

### Step 2：列出可用版本

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
import os, json

versions_dir = 'idols/{slug}/versions'
if not os.path.exists(versions_dir):
    print('NO_VERSIONS')
else:
    versions = sorted(os.listdir(versions_dir))
    versions = [v for v in versions if os.path.isdir(os.path.join(versions_dir, v))]
    if not versions:
        print('NO_VERSIONS')
    else:
        print(f'可用版本：{len(versions)} 个')
        for v in versions:
            meta_path = os.path.join(versions_dir, v, 'meta.json')
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                updated = meta.get('updated_at', '未知')[:10]
                print(f'  {v}  (更新于 {updated})')
            else:
                print(f'  {v}')
"
```

如果输出 `NO_VERSIONS`，告知用户没有历史版本可回滚。**流程结束。**

如果用户未指定 version 参数，展示可用版本列表，让用户选择。

### Step 3：确认回滚

向用户确认：
```
即将回滚 {stage_name}：{current_version} → {target_version}

当前版本会自动备份，回滚后可再次恢复。
确认回滚？
```

### Step 4：执行回滚

```bash
cd ${CLAUDE_SKILL_DIR}
python3 -c "
from tools.skill_writer import SkillWriter

writer = SkillWriter()
success = writer.rollback('{slug}', '{version}')
if success:
    meta = writer.read_meta('{slug}')
    print(f'ROLLBACK_OK')
    print(f'已回滚至：{meta.get(\"version\", \"{version}\")}')
else:
    print('ROLLBACK_FAILED')
    print('版本 {version} 不存在')
"
```

告知用户：
```
✅ 已将 {stage_name} 回滚至 {version}！

如需恢复，使用：/idol-rollback {slug} {backup_version}
```

