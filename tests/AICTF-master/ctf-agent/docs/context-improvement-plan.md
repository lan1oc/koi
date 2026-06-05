# 上下文管理改善计划

> 基于 OpenViking 项目深度分析，结合 ctf-agent 现有架构，制定的全面改善方案。
> 
> 日期：2026-02-23

---

## 一、现状诊断

### 1.1 当前上下文生命周期

```
buildMessages() 构建消息:
  [system prompt]
  ↓
  [SOLVE STATE] ← pinned: TodoList + Ideas + Vulns + Blocked
  ↓
  [session history] ← LoadMessages() 从 JSONL 加载
```

**Compaction 触发链**:
```
maybeCompact(round)
  ├─ messages > 120      → CompactContext (强制全摘要)
  ├─ tokens > 75%        → CompactContext (LLM 摘要替换旧消息)
  ├─ tokens > 64%        → ClearToolOutputs (截断旧 tool output)
  └─ round % N == 0      → 周期性清理
```

### 1.2 已识别的 6 个核心问题

| # | 问题 | 影响 | 严重度 |
|---|------|------|--------|
| **P1** | L0 Abstract 存了但没用 | CompactContext 提取 L0 存入 Session.L0Abstract，但 buildMessages() **从不注入**到 pinned state，压缩后 Agent 丢失全局进度感知 | 🔴 高 |
| **P2** | ClearToolOutputs 截断太粗暴 | 旧 tool output 一律截断到 400+400 chars（head+tail），**error/traceback/segfault 等关键调试信息**可能被截掉 | 🔴 高 |
| **P3** | Approaches Tried 表不持久 | CompactContext 的摘要含 "Approaches Tried" 表，但多次压缩后该表被**再次压缩掉**，Agent 反复尝试已失败的方法 | 🟡 中 |
| **P4** | 压缩时不提取记忆 | ExtractMemories 仅在**挑战结束时**调用（server.go），长会话中间有价值的发现随压缩丢失 | 🟡 中 |
| **P5** | Memory 检索太粗 | GetForContext(category, 5) 只用 challenge category 做 LIKE 搜索，web 类题各种不同但检索结果可能完全无关 | 🟢 低 |
| **P6** | compaction prompt 缺少关键维度 | 没有 "Errors & Fixes"、"Context References"（文件路径、关键命令）、"Key User Messages"  | 🟢 低 |

### 1.3 与 OpenViking 的差距分析

| 维度 | OpenViking | ctf-agent 现状 | 差距 |
|------|-----------|---------------|------|
| **上下文分层** | L0/L1/L2 三层，按需加载 | L0 存了但没注入；L1 仅在压缩消息中 | L0 未利用 |
| **记忆提取** | session commit 时自动提取 6 类记忆 | 仅挑战结束时提取 cases/patterns | 中间无提取 |
| **记忆去重** | 向量预过滤 → LLM CREATE/MERGE/SKIP | LLM-based dedup 已实现 (memory_deduplicator.go) | ✅ 已有 |
| **结构化摘要** | 模板含 7+ 维度（时间线、错误、上下文引用等） | 5 维度（Timeline, Critical Data, Approaches, State, Next） | 缺 2 维度 |
| **检索匹配** | 向量 + hierarchical retriever + rerank | LIKE 关键词搜索 | 差距大 |
| **持久 state** | 归档含 abstract + overview | JSONL 归档 + L0Abstract 字段 | 未利用归档 |
| **打断保护** | truncation 智能保护关键信息 | 仅保护 flag 模式 | 缺错误保护 |

---

## 二、改善方案总图

```
┌──────────────────────────────────────────────────────────────┐
│                    改善方案分层路线图                           │
│                                                              │
│  Phase 0: 即时修复 (无新依赖，改逻辑即可)                       │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ ① Pin L0 Abstract → buildMessages pinned state     │     │
│  │ ② ClearToolOutputs 智能截断（保护 error/traceback）  │     │
│  │ ③ Approaches Tried 持久化到 Session 元数据           │     │
│  │ ④ Compaction prompt 补充 Errors & Fixes 维度        │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                              │
│  Phase 1: 中期增强 (需少量新代码)                              │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ ⑤ Compaction 后异步触发 Memory Extraction            │     │
│  │ ⑥ Memory 检索增强（多关键词组合搜索）                  │     │
│  │ ⑦ Session 元数据扩展（L0 + Approaches + ErrorFixes）│     │
│  └─────────────────────────────────────────────────────┘     │
│                                                              │
│  Phase 2: 远期升级 (需新基础设施)                              │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ ⑧ 向量化 Memory（嵌入模型 + 向量存储）               │     │
│  │ ⑨ Hierarchical Retriever（多轮递归检索 + rerank）    │     │
│  │ ⑩ Intent Analyzer（LLM 分析 session 生成查询计划）   │     │
│  │ ⑪ Cross-session 经验传播（session 之间知识共享）      │     │
│  └─────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、Phase 0: 即时修复（无新依赖）

### ① Pin L0 Abstract 到 buildMessages

**现状**: `CompactContext()` 提取 L0 → 存入 `Session.L0Abstract` → **从未读取**

**修改文件**: `runner.go` → `buildMessages()`

**方案**:
```go
// buildMessages() 的 pinnedParts 构建中，最前面加入 L0
if sess, err := r.sessionMgr.Get(r.SessionID); err == nil && sess.L0Abstract != "" {
    pinnedParts = append([]string{
        "## Progress Summary\n" + sess.L0Abstract,
    }, pinnedParts...)
}
```

**效果**: 压缩后 Agent 始终看到 "我目前在干什么" 的一行摘要，避免上下文断裂。

**预计改动**: ~10 行

---

### ② ClearToolOutputs 智能截断

**现状**: `truncatePreserveFlags()` 仅保护 `flag{`/`ctf{`/`key{` 模式，错误信息被截断。

**修改文件**: `compaction.go` → `truncatePreserveFlags()`

**方案**: 在截断中间部分时，额外保留包含关键诊断模式的行：

```go
// 新增保护模式列表
var diagnosticPatterns = []string{
    "error", "Error", "ERROR",
    "traceback", "Traceback",
    "segfault", "Segmentation fault",
    "permission denied", "Permission denied",
    "not found", "No such file",
    "syntax error", "SyntaxError",
    "connection refused", "timeout",
    "stack smashing", "buffer overflow",
    "SIGSEGV", "SIGABRT",
}
```

同时调大截断上限：`400+400` → `600+600`（tool output 通常 2-10KB，多保留 400 bytes 性价比高）。

**效果**: Soft compaction 不再丢失关键调试线索。Agent 在 64%-75% token 区间仍能看到报错信息。

**预计改动**: ~30 行

---

### ③ Approaches Tried 持久化

**现状**: CompactContext 的 LLM 摘要含 Approaches Tried 表，但存在 user 消息中，多次压缩后丢失。

**修改文件**: 
- `types.go` → Session 新增 `ApproachesTried string` 字段
- `compaction.go` → CompactContext 中提取表格并持久化
- `runner.go` → buildMessages 注入到 pinned state

**方案**:

1. **提取**: 在 CompactContext 完成后，正则提取 `## Approaches Tried` 到下一个 `##` 之间的内容：
```go
func extractApproachesTried(summary string) string {
    // 匹配 "## Approaches Tried" 或 "## Approaches" 段落
    // 返回 markdown 表格文本
}
```

2. **合并**: 如果 Session 已有旧的 approaches，**追加**而不是覆盖：
```go
sess.ApproachesTried = mergeApproaches(sess.ApproachesTried, newApproaches)
```

3. **注入**: buildMessages 的 pinned state 中：
```go
if sess.ApproachesTried != "" {
    pinnedParts = append(pinnedParts, "## Approaches History\n" + sess.ApproachesTried)
}
```

**效果**: 即使经历多次压缩，Agent 始终能看到完整的历史方法尝试表，避免重复。

**预计改动**: ~60 行

---

### ④ Compaction Prompt 补充维度

**修改文件**: `data/prompts/compaction.md`

**新增段落**:

```markdown
## Errors & Fixes
Key errors encountered and how they were resolved (or still unresolved):
- **Error**: [error message or symptom]
  **Status**: ✅ Fixed / ❌ Unresolved
  **Fix/Workaround**: [what was done]

## Context References
Important file paths, URLs, and commands used:
- **Files**: [paths to binaries, scripts, configs discovered]
- **Commands**: [key tool commands that produced useful output]
- **Environment**: [OS, architecture, library versions detected]
```

**效果**: 压缩摘要保留更多可操作信息，减少 Agent 在压缩后"重新发现"已知信息的浪费。

**预计改动**: ~20 行

---

## 四、Phase 1: 中期增强

### ⑤ Compaction 后异步触发 Memory Extraction

**背景**: OpenViking 在 `session.commit()` 时自动 `_extract_memories()`。我们的 ExtractMemories 只在挑战**结束后**由 server.go 调用。

**修改文件**: 
- `compaction.go` → CompactContext 返回归档消息
- `runner.go` → maybeCompact 调用 CompactContext 后异步触发 ExtractMemories

**方案**:
```go
// maybeCompact 中，CompactContext 成功后：
go func() {
    ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
    defer cancel()
    if err := r.ExtractMemories(ctx, r.challengeInfo, globalMemoryStore); err != nil {
        r.logger.Warn("mid-session memory extraction failed", zap.Error(err))
    }
}()
```

**关键决策**: ExtractMemories 使用 **归档的旧消息** 而不是当前消息（因为旧消息在压缩后已被替换）。需要修改 ExtractMemories 的接口，使其可以接受消息列表参数而不是从 session 加载。

**接口变更**:
```go
// 新增：支持传入消息列表（用于归档消息的中间提取）
func (r *Runner) ExtractMemoriesFromMessages(ctx context.Context, messages []types.Message, challengeInfo *ChallengeInfo, memStore *memory.Store) error
```

**效果**: 长会话中每次压缩都会沉淀经验，不用等挑战结束。

**预计改动**: ~40 行

---

### ⑥ Memory 检索增强

**现状**: `GetForContext(category, 5)` → `Search(category)` → `LIKE '%web%'`

**问题**: "web" 匹配所有 web 类记忆，但 SQL 注入题和 XSS 题的记忆完全不同。

**方案**: 多关键词组合搜索

```go
func (s *Store) GetForContext(challenge *ChallengeInfo, maxCount int) string {
    // 1. 用 category + title 关键词联合搜索
    keywords := extractKeywords(challenge.Title + " " + challenge.Description)
    
    // 2. 对每个关键词独立搜索，合并去重
    scored := map[string]float64{} // memory_id → relevance score
    for _, kw := range keywords {
        results, _ := s.Search(kw)
        for _, m := range results {
            scored[m.ID] += 1.0 // 每命中一个关键词加分
        }
    }
    
    // 3. 按 tag 精确匹配加权
    for _, tag := range challenge.Tags {
        results, _ := s.SearchByTag(tag)
        for _, m := range results {
            scored[m.ID] += 2.0 // tag 精确匹配权重更高
        }
    }
    
    // 4. 按分数排序返回 Top-K
    return formatTopK(scored, maxCount)
}
```

**额外**: 在 Memory 表增加 `tags` 索引，在 ExtractMemories 时让 LLM 生成 tags。

**预计改动**: ~80 行

---

### ⑦ Session 元数据扩展

**修改文件**: `types.go` → Session 结构体

```go
type Session struct {
    // ... existing fields ...
    L0Abstract       string `json:"l0_abstract,omitempty"`
    ApproachesTried  string `json:"approaches_tried,omitempty"`   // 新增：持久化方法尝试历史
    ErrorsFixes      string `json:"errors_fixes,omitempty"`       // 新增：错误与修复记录
    CompactionCount  int    `json:"compaction_count,omitempty"`   // 新增：压缩次数（用于调试）
}
```

**效果**: 每次压缩都沉淀结构化元数据到 Session，跨压缩持久保存。

**预计改动**: ~15 行

---

## 五、Phase 2: 远期升级（需新基础设施）

### ⑧ 向量化 Memory

**目标**: 用嵌入模型将 Memory 向量化，实现语义搜索取代 LIKE 关键词匹配。

**架构选型**:

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A. SQLite + Go 嵌入** | 用 Go 嵌入库 (如 `github.com/nicpottier/sqlite-vec`) 在 SQLite 中存储向量 | 零额外依赖，单文件部署 | 嵌入模型需要本地运行或API调用 |
| **B. Qdrant/Milvus** | 独立向量数据库 | 专业级性能 | 新增部署依赖，docker compose 需加服务 |
| **C. OpenAI Embeddings + SQLite** | 调 API 生成嵌入，存 SQLite，暴力 cosine 搜索 | 最简单 | 依赖 API，Memory 数量小时够用 |

**推荐**: 方案 C（初期 Memory 数量不会爆炸，SQLite 暴力搜索完全够用）

**实现路径**:

1. **嵌入接口** (`internal/memory/embedder.go`):
```go
type Embedder interface {
    Embed(ctx context.Context, text string) ([]float64, error)
}
```

2. **OpenAI 实现**:
```go
type OpenAIEmbedder struct {
    apiKey string
    model  string // "text-embedding-3-small"
}
```

3. **向量存储** (SQLite blob 列):
```sql
ALTER TABLE agent_memories ADD COLUMN embedding BLOB;
```

4. **搜索** (Go 中 cosine similarity):
```go
func (s *Store) SemanticSearch(ctx context.Context, query string, topK int) ([]*Memory, error) {
    queryVec, _ := s.embedder.Embed(ctx, query)
    all, _ := s.List("")
    // 计算 cosine similarity，排序返回 Top-K
}
```

**预计改动**: ~200 行新代码

---

### ⑨ Hierarchical Retriever

**OpenViking 方案**: `hierarchical_retriever.py` 递归搜索目录树，分数传播，多轮收敛。

**CTF-agent 适配**: 我们的知识体系扁平（skills + memories + knowledge），不需要目录树搜索。但可以借鉴**多源融合 + rerank** 的思路：

```
Query → 并行搜索:
  ├─ Memory.SemanticSearch(query)  → candidates A
  ├─ Knowledge.Search(query)       → candidates B  
  ├─ Skill.Match(category, tags)   → candidates C
  └─ 融合去重 → LLM Rerank(query, candidates) → Top-K
```

**实现路径**:

1. **统一 Retriever 接口**:
```go
type RetrievalResult struct {
    Source  string  // "memory", "knowledge", "skill"
    Title   string
    Content string
    Score   float64
}

type Retriever interface {
    Search(ctx context.Context, query string, topK int) ([]RetrievalResult, error)
}
```

2. **FusionRetriever**: 并行调用多个 Retriever，合并结果

3. **LLM Reranker**: 用 utility model 对 top-20 候选做相关性排序

**预计改动**: ~300 行新代码，需要 Phase ⑧ 的向量搜索作为前置

---

### ⑩ Intent Analyzer

**OpenViking 方案**: `intent_analyzer.py` 用 LLM 分析 session 上下文，生成 `QueryPlan`（包含多个 typed query）。

**CTF-agent 适配**: 在长会话开始前或每次压缩后，分析当前挑战状态，生成精准的检索查询：

```go
type QueryPlan struct {
    Queries []TypedQuery
}

type TypedQuery struct {
    Type     string // "memory_search", "skill_lookup", "knowledge_search"
    Query    string // 具体搜索词
    Priority int    // 优先级
}
```

**使用场景**:
- 挑战开始时: 分析题目描述 → 检索相关 memories + skills
- 压缩后: 分析当前进度 → 检索针对性的经验/技术

**预计改动**: ~150 行新代码

---

### ⑪ Cross-session 经验传播

**目标**: 同一竞赛的不同挑战之间共享发现（如同一服务器的信息收集结果复用）。

**实现思路**:
1. 在 Memory 增加 `competition_id` 字段
2. 新增 `entities` 记忆类别（目标系统信息）
3. 解题时自动检索同竞赛的 entity 记忆注入

**这在渗透测试模式下特别有价值**: 一个目标的多个 session 共享已发现的子域名、端口、凭证。

**预计改动**: ~100 行新代码

---

## 六、实施优先级与排期

| 优先级 | 编号 | 改动 | 修改文件 | 代码量 | 依赖 |
|--------|------|------|----------|--------|------|
| **P0** | ① | Pin L0 Abstract | runner.go | ~10 行 | 无 |
| **P0** | ② | 智能截断 ClearToolOutputs | compaction.go | ~30 行 | 无 |
| **P0** | ③ | Approaches Tried 持久化 | types.go, compaction.go, runner.go | ~60 行 | 无 |
| **P0** | ④ | Compaction prompt 补充 | compaction.md | ~20 行 | 无 |
| **P1** | ⑤ | 压缩后异步 Memory Extraction | runner.go, memory_extractor.go | ~40 行 | 无 |
| **P1** | ⑥ | Memory 检索增强 | memory/store.go, tips_store.go | ~80 行 | 无 |
| **P1** | ⑦ | Session 元数据扩展 | types.go | ~15 行 | ①③ |
| **P2** | ⑧ | 向量化 Memory | memory/embedder.go, store.go | ~200 行 | OpenAI Embedding API |
| **P2** | ⑨ | Hierarchical Retriever | agent/retriever.go | ~300 行 | ⑧ |
| **P2** | ⑩ | Intent Analyzer | agent/intent.go | ~150 行 | ⑨ |
| **P2** | ⑪ | Cross-session 传播 | memory/store.go, types.go | ~100 行 | ⑧ |

### 估计工时

| Phase | 总代码量 | 估计工时 |
|-------|---------|---------|
| Phase 0 (即时修复) | ~120 行 | 2-3 小时 |
| Phase 1 (中期增强) | ~135 行 | 3-5 小时 |
| Phase 2 (远期升级) | ~750 行 | 2-3 天 |

---

## 七、知识体系全景图（改善后）

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CTF Agent 知识体系 (改善后)                        │
│                                                                     │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐│
│  │ Skills  │  │  Ideas   │  │ Memories │  │ Lessons  │  │Knowledge││
│  │ 赛前知识 │  │ 赛中策略  │  │ 长期经验  │  │ 赛后总结  │  │ 经验库  ││
│  ├─────────┤  ├──────────┤  ├──────────┤  ├──────────┤  ├────────┤│
│  │人工编写  │  │AI运行时  │  │AI自动提取 │  │AI解题后  │  │人工整理 ││
│  │通用方法  │  │单题假设  │  │跨题沉淀  │  │单题总结  │  │Writeup ││
│  │永久不变  │  │绑定session│  │越用越多  │  │绑定题目  │  │全文搜索 ││
│  └────┬────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘│
│       │            │             │              │             │     │
│       └─────── 解题时注入 system prompt (RAG) ──────────────┘     │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Pinned State (每轮重建，不被压缩)                │   │
│  │  [L0 Progress] + [TodoList] + [Ideas] + [Vulns] + [Blocked] │   │
│  │  + [Approaches History]  ← NEW                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Compaction (上下文压缩循环)                      │   │
│  │  ClearToolOutputs → 智能截断(保护 error/flag) ← IMPROVED    │   │
│  │  CompactContext → L0 提取 → Approaches 提取 → Memory 提取   │   │
│  │                    ↓                ↓              ↓ NEW      │   │
│  │              Session.L0Abstract  Session.AP    memory DB     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────── Phase 2 ────────────────────────┐   │
│  │  Vector Embeddings → Semantic Search → Hierarchical Retrieval   │
│  │  Intent Analyzer → 精准注入上下文                              │   │
│  │  Cross-session → 竞赛内知识共享                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

知识飞轮:
  Skills (方法论)
    → Ideas (当前假设) → 解题 → Memories (经验沉淀) → 更好的 Ideas
    → Memory Extraction (压缩时自动提取) ← NEW
    → Cross-session 传播 (同竞赛共享) ← FUTURE
```

---

## 八、测试计划

### Phase 0 测试

| 测试 | 验证点 | 文件 |
|------|--------|------|
| TestBuildMessagesWithL0Abstract | 有 L0 时注入 pinned state；无 L0 时不注入 | compaction_test.go |
| TestSmartTruncation | error/traceback 行被保留；flag 行被保留；普通文本正常截断 | compaction_test.go |
| TestExtractApproachesTried | 从压缩摘要中正确提取 approaches 表 | compaction_test.go |
| TestMergeApproaches | 合并新旧 approaches 去重 | compaction_test.go |

### Phase 1 测试

| 测试 | 验证点 | 文件 |
|------|--------|------|
| TestMidSessionMemoryExtraction | 压缩后触发 memory extraction，验证异步执行 | runner_test.go |
| TestMultiKeywordSearch | 多关键词搜索结果按相关度排序 | memory/store_test.go |
| TestSessionMetaPersistence | 新字段正确 JSON 序列化/反序列化 | types_test.go |

---

## 九、参考资料

### OpenViking 核心源码

| 文件 | 核心逻辑 | 我们借鉴的点 |
|------|----------|-------------|
| `session/session.py` (585 行) | commit/archive 自动触发 memory extraction | Phase 1 ⑤ |
| `session/memory_extractor.py` (200 行) | 6 类记忆提取，L0/L1/L2 三层 | 已有实现 |
| `session/memory_deduplicator.py` (150 行) | 向量预过滤 + LLM CREATE/MERGE/SKIP | 已有实现 |
| `retrieval/hierarchical_retriever.py` (407 行) | 递归搜索 + score propagation + rerank | Phase 2 ⑨ |
| `retrieval/intent_analyzer.py` (200 行) | LLM 分析 query intent → typed queries | Phase 2 ⑩ |
| `prompts/structured_summary.yaml` | 7 维度结构化摘要模板 | Phase 0 ④ |
| `core/context.py` | URI-based L0/L1/L2 context hierarchy | 理念已融入 |

### ctf-agent 关键文件

| 文件 | 功能 | 改动 Phase |
|------|------|-----------|
| `internal/agent/runner.go` | buildMessages, maybeCompact | 0, 1 |
| `internal/agent/compaction.go` | ClearToolOutputs, CompactContext, extract* | 0 |
| `internal/agent/memory_extractor.go` | ExtractMemories | 1 |
| `internal/memory/store.go` | Memory CRUD, Search, GetForContext | 1, 2 |
| `internal/types/types.go` | Session 结构体 | 0, 1 |
| `data/prompts/compaction.md` | Compaction LLM prompt | 0 |

---

## 十、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Approaches 提取正则不准 | 中 | Approaches 表内容不完整 | 用宽松正则 + fallback 到整段保存 |
| 中间 Memory Extraction 浪费 token | 低 | 增加 API 费用 | 仅在 full compaction 时触发，限制每会话最多 3 次 |
| 向量嵌入 API 调用增加延迟 | 中 | Memory 创建变慢 | 异步 embedding，批量处理 |
| L0 注入增加 pinned state 大小 | 低 | 略增 token 用量 | L0 限制 ≤200 chars |
| Approaches History 膨胀 | 中 | 长会话 approaches 表太长 | 限制最多保留最近 20 条 |
