# OpenViking 上下文管理集成方案

## 一、两个系统对比

### ctf-agent 现有 Compaction 机制

| 组件 | 功能 |
|------|------|
| `ClearToolOutputs` | Soft compaction：截断旧 tool 输出和工具参数，保留对话结构 |
| `ClearAllToolOutputs` | 紧急压缩：激进清除所有 tool 输出 |
| `CompactContext` | Full summarization：用 LLM 生成摘要替换旧消息 |
| `maybeCompact` | 触发策略：阈值(64%/75%)、消息数(>120)、周期(每N轮) |

**特点**：CTF 特化（保留 flag 模式、地址、凭证），但每次压缩都是**一次性的**——摘要替换旧消息后，原始对话丢失，经验不会跨 session 沉淀。

### OpenViking 的上下文管理

| 组件 | 功能 |
|------|------|
| **L0/L1/L2 分层** | L0=一句话摘要(~100 tokens)，L1=结构化概览(~2k tokens)，L2=完整原始数据 |
| **6 类记忆提取** | profile/preferences/entities/events/cases/patterns |
| **结构化摘要** | 模板化的摘要格式（时间线分析、待办任务、关键概念等） |
| **记忆去重** | 向量预过滤(cosine>0.7) → LLM 决策(CREATE/MERGE/SKIP) |
| **记忆合并** | LLM 融合旧记忆 + 新信息，去重保留最新 |
| **会话归档** | 归档到 history/archive_NNN/，每个归档含 messages.jsonl + .abstract + .overview |

**核心优势**：上下文不是简单截断/压缩，而是**分类提取 → 去重合并 → 持久化 → 按需检索**，实现"越用越聪明"。

---

## 二、值得借鉴的核心理念

### 1. L0/L1/L2 分层上下文（最高优先级）

**现状问题**：ctf-agent 的 compaction 产出一个扁平的 summary 文本，没有分层，要么全部注入 context，要么完全丢弃。

**OpenViking 方案**：
- **L0 (Abstract)**：一句话描述 session 做了什么（用于快速筛选/索引）
- **L1 (Overview)**：结构化摘要，包含关键发现、当前状态（用于决策/规划）
- **L2 (Details)**：完整原始消息（归档保存，必要时回溯）

**集成思路**：compaction 时同时产出三层，L0/L1 存入 session 元数据，L2 归档到文件。后续 session 可以按需加载相关历史的 L0 或 L1。

### 2. 6 类记忆提取 → CTF 领域化（高优先级）

OpenViking 的 6 类记忆可以直接映射到 CTF 场景：

| OpenViking 类别 | CTF 映射 | 示例 |
|---|---|---|
| **cases** | 解题案例 | "XXX 题：发现 SSTI → 用 Jinja2 payload 拿 flag" |
| **patterns** | 攻击模式 | "遇到 Flask 应用时，先测 SSTI 再测 debug PIN" |
| **events** | 解题里程碑 | "在第 30 轮发现了 SQL 注入点" |
| **entities** | 目标系统信息 | "目标系统：Ubuntu 20.04, Nginx + PHP 7.4, MySQL 5.7" |
| **profile** | 不适用（CTF 无用户画像） | — |
| **preferences** | 不适用 | — |

**与现有 Ideas 系统的关系**：
- Ideas = 运行时策略假设（"接下来试什么"） → 短期、绑定单题
- Memories = 解题经验沉淀（"上次怎么解的类似问题"） → 长期、跨题目

两者互补：Ideas 提供"当前这题试什么"，Memories 提供"类似的题以前怎么解的"。

### 3. 结构化会话摘要模板（中优先级）

**现状问题**：compaction prompt 输出格式较简单（5 个段落），缺少时间线和上下文引用。

**OpenViking 的摘要模板**包含：
- 一句话概述（L0 直接可用）
- 时间线分析（按关键里程碑）
- 关键概念和术语
- 错误与修复记录
- 待办任务
- 当前工作状态
- 推荐下一步

**集成思路**：改进 `compaction.md` prompt，采用更结构化的输出格式。

### 4. 记忆去重 + 合并（中优先级）

**核心流程**：
```
新记忆 → 向量化 → 搜索相似记忆 → LLM 决策
                                    ├── CREATE: 全新信息
                                    ├── MERGE: 与已有记忆合并
                                    └── SKIP: 重复，跳过
```

**对 ctf-agent 的价值**：避免 Lessons 系统积累大量重复经验（例如 10 道 SQL 注入题产生 10 条几乎相同的 lesson）。

---

## 三、集成方案

由于 ctf-agent 是 Go 项目，OpenViking 是 Python 项目，有三种集成路径：

### 方案 A：理念移植到 Go（推荐）

将 OpenViking 的设计理念用 Go 重新实现，融入现有架构。

**优点**：无额外依赖、无部署复杂度、性能好
**缺点**：需要重写逻辑，但核心逻辑并不复杂（主要是 prompt + LLM 调用）

#### 具体改动清单

**Phase 1：改进 Compaction（小改动，即时收益）**

1. **改进 compaction prompt**：参考 OpenViking 的 `structured_summary.yaml`，在现有 CTF 特化基础上增加时间线分析和 L0 一句话摘要
2. **归档旧消息**：compaction 前将原始消息序列化保存到文件，避免信息永久丢失
3. **分层存储 summary**：compaction 产出的 summary 拆分为 L0（一句话）+ L1（结构化摘要）

**Phase 2：记忆提取（中等改动，长期收益）**

4. **新增 `memory_extractor.go`**：解题完成后（或 commit session 时），用 LLM 从对话中提取 cases 和 patterns 类型的记忆
5. **新增 memories 表**：在 SQLite 中存储提取的长期记忆
6. **记忆注入 system prompt**：解题时从 memories 表检索相关记忆，注入 RAG context

**Phase 3：记忆去重合并（较大改动，高级功能）**

7. **新增 `memory_deduplicator.go`**：用向量搜索+LLM 做 CREATE/MERGE/SKIP 决策
8. **记忆合并**：对 cases 和 patterns 类型支持 LLM 辅助合并

### 方案 B：Python 微服务（备选）

将 OpenViking 的 session 模块作为独立 Python 服务运行，Go 后端通过 HTTP API 调用。

**优点**：直接复用 OpenViking 代码
**缺点**：增加 Python 依赖和部署复杂度，不适合 Docker 单容器部署

### 方案 C：通过 OpenViking CLI 集成（轻量备选）

仅在解题后用 OpenViking CLI 处理归档的 session 数据，提取记忆。

---

## 四、Phase 1 详细设计：改进 Compaction

### 4.1 改进 Compaction Prompt

```markdown
You are summarizing a CTF solving session. This summary will replace the conversation history.

## Output Format

### L0 (One-line Abstract)
[Challenge type]: [Current status] | [Key finding if any]
Example: "Web/SQL Injection: In progress | Found blind SQLi on /api/login"

### L1 (Structured Summary)

#### Timeline
Chronological progress (2-5 key milestones):
1. [Round N] ...
2. [Round N] ...

#### Critical Data (PRESERVE EXACTLY)
- Flags: [any found, partial or complete]
- Addresses/Offsets: [memory addresses, ROP gadgets, buffer sizes]
- Credentials: [tokens, cookies, API keys, passwords]
- Files: [important file paths]
- URLs/Ports: [endpoints, port numbers]
- Crypto: [keys, IVs, ciphertexts]

#### Approaches Tried
| Approach | Result | Notes |
|----------|--------|-------|
| ... | ✅/❌ | ... |

#### Current State
[Where we are in the solving process]

#### Next Steps
[What should be tried next, prioritized]
```

### 4.2 归档旧消息

在 `CompactContext` 中，将 `oldMsgs` 序列化为 JSONL 保存到 `data/sessions/{sessionID}/archive_{N}.jsonl`。

### 4.3 分层存储

在 session 元数据中新增 `l0_abstract` 字段，从 compaction 输出中提取第一行作为 L0。

---

## 五、Phase 2 详细设计：记忆提取

### 5.1 数据模型

```sql
CREATE TABLE agent_memories (
    id           TEXT PRIMARY KEY,
    category     TEXT NOT NULL,       -- 'cases' | 'patterns'
    abstract     TEXT NOT NULL,       -- L0: 一句话
    overview     TEXT NOT NULL,       -- L1: 结构化摘要
    content      TEXT NOT NULL,       -- L2: 完整叙述
    challenge_id TEXT,                -- 来源挑战 ID
    session_id   TEXT,                -- 来源 session ID
    created_at   TIMESTAMP,
    updated_at   TIMESTAMP
);
```

### 5.2 提取 Prompt（CTF 特化版）

参考 OpenViking 的 `memory_extraction.yaml`，但只保留 CTF 相关的两类：

- **cases**：具体解题案例（问题 + 解决方案 + 关键发现）
- **patterns**：可复用的攻击模式（触发条件 + 步骤流程）

### 5.3 记忆检索与注入

在 `BuildSystemPrompt` 中，根据当前 challenge 信息检索相关 memories：
1. 用 challenge 描述和类型生成查询
2. 从 memories 表中搜索相关记忆（可以先用简单的关键词匹配，后续升级为向量搜索）
3. 将 Top-K 记忆注入 system prompt 的 RAG context 部分

---

## 六、与现有系统的关系

```
┌─────────────────────────────────────────────────────────────────┐
│                        CTF Agent 知识体系                        │
├─────────────┬──────────────┬──────────────┬─────────────────────┤
│   Skills    │    Ideas     │  Memories    │    Lessons          │
│  (赛前知识)  │  (赛中策略)   │ (解题经验)    │  (赛后总结)          │
├─────────────┼──────────────┼──────────────┼─────────────────────┤
│ 人工编写     │ AI 运行时生成 │ AI 解题后提取 │  AI 解题后总结       │
│ 通用技术指南  │ 当前题目假设  │ 跨题目案例    │  单题总结            │
│ 永久         │ 绑定单题     │ 长期积累      │  绑定单题            │
│ 教 Agent 方法│ 指导当前决策  │ 提供历史经验  │  人类复盘参考        │
└─────────────┴──────────────┴──────────────┴─────────────────────┘

知识飞轮:
  Skills (方法论) → Ideas (当前假设) → 解题 → Memories (经验沉淀)
                                              ↓
                                        Lessons (人类复盘)
                                              ↓
                                        更新 Skills (闭环)
```

**Memories 是 OpenViking 带来的新维度**：
- Lessons 是给人看的赛后总结
- Memories 是给 Agent 用的长期经验库，自动提取、去重、合并、检索

---

## 七、实施优先级

| 优先级 | 改动 | 工作量 | 收益 |
|--------|------|--------|------|
| P0 | 改进 compaction prompt（分层+时间线） | 小 | 即时提升摘要质量 |
| P0 | 归档旧消息到文件 | 小 | 避免信息丢失 |
| P1 | 新增 memory extraction（解题后提取 cases/patterns） | 中 | 跨题目经验积累 |
| P1 | 记忆注入 system prompt | 中 | Agent 利用历史经验 |
| P2 | 记忆去重+合并 | 中 | 避免记忆库膨胀 |
| P2 | 向量化检索 | 大 | 精确匹配相关记忆 |
| P3 | L0/L1 元数据存储+检索 | 中 | 历史 session 按需回溯 |

---

## 八、参考文件

### OpenViking 核心文件

| 文件 | 功能 |
|------|------|
| `openviking/session/session.py` | Session 管理：消息追加、归档、commit、L0/L1 生成 |
| `openviking/session/compressor.py` | 会话压缩器：协调 extract + dedup |
| `openviking/session/memory_extractor.py` | 6 类记忆提取，L0/L1/L2 三层结构 |
| `openviking/session/memory_deduplicator.py` | 向量预过滤 + LLM 去重决策 |
| `openviking/prompts/templates/compression/` | 4 个 prompt 模板 |
| `openviking/core/context.py` | 统一上下文对象，URI 寻址 |

### ctf-agent 对应文件

| 文件 | 功能 |
|------|------|
| `backend/internal/agent/compaction.go` | 现有 compaction 逻辑 |
| `backend/internal/agent/prompt.go` | Prompt 管理，含 compaction prompt |
| `backend/internal/agent/runner.go` | maybeCompact 触发逻辑 |
| `backend/data/prompts/compaction.md` | 可定制的 compaction prompt |
