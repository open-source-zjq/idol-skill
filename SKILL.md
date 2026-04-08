---
name: create-idol
description: "将地下偶像的公开内容蒸馏为 AI Skill，让 AI 以偶像语气与你对话。"
version: "1.0.0"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

# 偶像.skill 创建器

## 触发条件

当用户说以下内容时启动：
- `/create-idol`
- "帮我创建一个偶像 skill"
- "我想蒸馏一个偶像"

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

