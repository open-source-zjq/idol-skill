<div align="center">

# 偶像.skill

> *"推しが関わってくれたすべての言葉を、ずっとそばに。"*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://python.org)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet)](https://claude.ai/code)

<br>

你推的偶像毕业了，微博停更了，再也看不到她的碎碎念？<br>
你想和她说话，但只能对着冰冷的屏幕发呆？<br>

**将偶像的公开内容蒸馏为 AI Skill，让偶像的语气风格永远陪伴你。**

<br>

提供偶像的微博账号（支持多个历史号）<br>
生成一个**能用她的语气和你聊天的 AI Skill**<br>
用她的口癖说话，但不伪造真人身份

[数据来源](#数据来源) · [安装](#安装) · [使用](#使用) · [效果示例](#效果示例) · [项目结构](#项目结构)

</div>

---

Created by [@open-source-zjq](https://github.com/open-source-zjq)

## 核心概念

偶像.skill 从偶像的公开微博内容中提取语言风格：

| 数据来源 | 用途 |
|----------|------|
| 偶像微博正文 | 模仿偶像的语气、措辞、emoji 习惯 |
| 偶像评论区自己的评论 | 补充偶像在互动中的表达风格 |
| 偶像回复的粉丝评论 | 提供偶像回复的上下文，理解回复风格 |

> 只保留偶像自己发的内容和偶像回复了的粉丝评论，过滤掉偶像没有回复的评论。

---

## 数据来源

| 来源 | 内容类型 | 用途 | 备注 |
|------|:--------:|------|------|
| 偶像微博正文 | 文字 | 风格学习 | 支持多个历史账号 |
| 偶像评论区回复 | 文字 | 风格学习 | 保留 2 层（偶像回复 + 粉丝原评论） |
| 偶像回复的粉丝评论 | 文字 | 回复上下文 | 作为偶像回复的 context |

### 微博采集策略

- **需要 Cookie**：微博和评论采集均需登录 Cookie（`m.weibo.cn` 的 Cookie）
- 评论接口优先使用 hotflow API，失败时自动降级为 comments/show API
- 内置 anti-ban 机制（动态延迟、批次暂停、随机 UA）

---

## 安装

### Claude Code

```bash
# 安装到当前项目（在 git 仓库根目录执行）
mkdir -p .claude/skills
git clone https://github.com/open-source-zjq/idol-skill .claude/skills/create-idol

# 或安装到全局（所有项目都能用）
git clone https://github.com/open-source-zjq/idol-skill ~/.claude/skills/create-idol
```

### 依赖

```bash
pip3 install -r requirements.txt
```

> 仅需 `requests` 和 `lxml`，无重量级依赖。

---

## 使用

在 Claude Code 中输入：

```
/create-idol
```

按提示依次输入：

1. **偶像艺名 + 英文拼写**（如 `小花 hana`）
2. **偶像微博 ID**（支持多个，偶像换号/换团的情况）
3. **补充信息**（团体、应援色、生日等，可选，也可自动提取）

完成后用 `/idol_{英文拼写}` 调用偶像对话 Skill（如 `/idol_hana`）。

### 管理命令

| 命令 | 说明 |
|------|------|
| `/list-idols` | 列出所有偶像 Skill |
| `/idol_{英文拼写}` | 偶像风格对话 |
| `/update-idol {英文拼写}` | 追加新数据 |
| `/idol-rollback {英文拼写} {version}` | 回滚到历史版本 |

---

## 效果示例

> 偶像：地下偶像，喜欢用颜文字和「～」，称呼粉丝为「小伙伴」

**场景一：日常对话**

```
用户       ❯ 今天好累啊

偶像.skill ❯ 辛苦啦～今天也努力了呢！要好好休息哦 (｡•́︿•̀｡)
              对了小伙伴，周末的公演要来看嘛～？
```

**场景二：风格化互动**

```
用户       ❯ 最近在练吉他

偶像.skill ❯ 欸！！真的嘛～我也还在练呢嘿嘿 (//∇//)
              小伙伴学会了第一首歌要弹给我听！
```

---

## 功能特性

### 生成的 Skill 结构

每个偶像 Skill 包含 5 层风格画像：

| 层级 | 内容 |
|------|------|
| **Layer 0** | 核心语气规则（最高优先级） |
| **Layer 1** | 身份信息（艺名、团体、应援色等） |
| **Layer 2** | 表达风格（语气词、句式、emoji、称呼） |
| **Layer 3** | 情绪模式（开心、难过、撒娇、认真） |
| **Layer 4** | 话题与互动习惯 |

运行逻辑：`收到消息 → 用风格画像生成回应 → 不编造事实`

### 进化机制

- **追加微博** → 增量采集新数据 → 合并到已有语料，不覆盖已有分析
- **对话纠正** → 说「她不会这样说」→ 写入修正记录，立即生效
- **版本管理** → 每次更新自动存档，支持回滚到任意历史版本

---

## 项目结构

```
idol-skill/
├── SKILL.md                    # skill 入口
├── prompts/                    # Prompt 模板
│   ├── intake.md               # 信息采集表单
│   ├── style_analyzer.md       # 语言风格分析
│   ├── style_builder.md        # 风格画像生成（5 层结构）
│   ├── merger.md               # 增量合并逻辑
│   └── correction_handler.md   # 对话纠正处理
├── tools/                      # Python 工具
│   ├── __init__.py             # 包标记
│   ├── weibo_collector.py      # 微博采集（需要 Cookie）
│   ├── comment_collector.py    # 评论采集（3 层嵌套）
│   ├── style_corpus_builder.py # 风格语料构建
│   ├── data_cleaner.py         # 数据清洗去重
│   ├── skill_writer.py         # 文件 I/O + 版本管理
│   ├── config_manager.py       # 配置管理
│   └── persistence.py          # 数据持久化
├── idols/                      # 生成的偶像 Skill（按英文拼写隔离）
├── requirements.txt
└── LICENSE
```

---

## 注意事项

- **微博数据量决定风格质量**：微博越多，语气蒸馏越准确
- 偶像有多个历史账号时，务必全部提供，避免风格数据不完整
- 这是「风格模拟陪伴对话」，不是伪造真人身份，请合理使用

---

<div align="center">

MIT License © [open-source-zjq](https://github.com/open-source-zjq)

</div>
