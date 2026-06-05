# 系统提示词标签化优化方案

> 创建日期: 2026-02-19
> 状态: 实施中

## 一、现状分析

| 段落 | 字符数 | 占比 | 说明 |
|------|--------|------|------|
| `<tips>` | 38,115 | **79.3%** | 305 条经验，4 个子分类全量注入 |
| `<solving_protocol>` | 4,023 | 8.4% | 解题协议（含硬编码 CF/BrowserMCP 指令） |
| `<current_challenge>` | 1,562 | 3.2% | 题目信息 |
| `<available_skills>` | 1,096 | 2.3% | 技能列表 |
| `<relevant_knowledge>` | 1,068 | 2.2% | RAG 知识 |
| 其余 | ~2,220 | 4.6% | identity / safety / code_style / runtime / memory |

**根因**：`tips` 表用 `(category TEXT PK, content TEXT)` 存储——整个分类是一坨文本，无法按条目过滤。`GetTipsForContext()` 永远加载 `general + tool_usage + 题目分类 + 平台`，305 条全部爆进 prompt。

---

## 二、核心方案：标签化按需注入

### Phase 1：Tips 原子化 + 标签系统（P0，预期减少 ~85% tokens）

#### 1.1 新数据模型

```sql
CREATE TABLE tip_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT NOT NULL,                -- "general" / "tool" / "web" / "misc" / "platform" ...
    content    TEXT NOT NULL,                -- 单条 tip 文本
    tags       TEXT NOT NULL DEFAULT '[]',   -- JSON 数组: ["PNG","隐写","LSB"]
    source     TEXT DEFAULT '',              -- 来源: session_id / "manual" / "migration"
    hit_count  INTEGER DEFAULT 0,            -- 命中计数，用于后续权重排序
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_tip_items_category ON tip_items(category);
CREATE INDEX idx_tip_items_tags ON tip_items(tags);
```

#### 1.2 标签设计规范

每个 tag **≤4 个字符**（中/英均可），按维度分类：

| 维度 | 示例标签 |
|------|----------|
| **题目类型** | `web`, `pwn`, `rev`, `crypto`, `misc`, `取证` |
| **具体技术** | `RCE`, `SQL`, `XSS`, `SSRF`, `SSTI`, `LFI`, `JWT`, `反序列`, `堆`, `栈`, `格串`, `ROP`, `RSA`, `AES`, `LSB`, `隐写` |
| **文件/协议** | `PNG`, `ZIP`, `PDF`, `PCAP`, `ELF`, `APK`, `流量`, `USB`, `DNS` |
| **工具** | `pwn`, `GDB`, `IDA`, `Ghid`, `binw`, `sqlm`, `nmap`, `burp`, `sage`, `z3`, `CyC` |
| **平台** | `BUU`, `ctfs`, `GZCTF`, `攻防` |
| **通用** | `编码`, `爆破`, `搜索`, `脚本`, `沙箱`, `Docker`, `Git` |

#### 1.3 标签生成方式

- **辅助模型（utility_model）打标**：使用 `getUtilityProvider()` 获取轻量模型batch 打标
- **自动打标 prompt**：批量 30-50 条/次，LLM 输出 `[{"idx":N,"tags":["t1","t2"]}]`
- **迁移**：旧 tips blob → 按 `- ` 分割为逐条 → 调用 LLM 打标 → 写入 `tip_items`

#### 1.4 查询接口（Tag-Based）

```go
func (s *TipItemStore) QueryByTags(tags []string, limit int) ([]TipItem, error)
```

- 从 `tip_items` 加载匹配 category 或 tags 的条目
- 按标签交集大小排序
- 返回 top-N

### Phase 2：Challenge → Tags 自动推导

```go
func DeriveTags(ch *ChallengeInfo) []string
```

- 题目类型 → 标签
- 平台 → 标签
- 标题/描述关键词 → 标签映射表
- 附件扩展名 → 标签

### Phase 3：工具 Tips 按需加载

新增 `get_tool_tips` 工具，Agent 可在需要时主动获取特定工具的使用经验。
系统提示词中不再全量注入 `tool_usage` 分类。

### Phase 4：Writeup 生成同步打标

- 修改 `GenerateWriteup()` → 让 LLM 在生成 writeup 时同时输出 tags
- 或在 writeup 保存后，调用辅助模型单独打标
- tags 写入 writeup markdown 的 YAML frontmatter

### Phase 5：Memory 标签化

`agent_memories` 表加 `tags TEXT DEFAULT '[]'` 列，reflection 时同步生成 tags。

### Phase 6：Solving Protocol 条件化瘦身

按平台/题型条件注入，移除无关指令块。

---

## 三、效果预估

| 段落 | 优化前 | 优化后 | 减幅 |
|------|--------|--------|------|
| **Tips** | 38,115 chars (~23K tok) | ~3,500 chars (~2K tok) | **-91%** |
| **Solving Protocol** | 4,023 chars | ~2,500 chars | -38% |
| **Tool Usage Tips** | 含在 Tips 中 | 0（按需调用） | -100% |
| **其余** | ~5,946 chars | ~5,946 chars | 不变 |
| **总计** | **~48K chars (~29K tok)** | **~12K chars (~7K tok)** | **~75%** |

---

## 四、实施顺序

| 阶段 | 工作内容 | 状态 |
|------|----------|------|
| **P0** | `tip_items` 新表 + TipItemStore + 迁移 | 🔄 |
| **P0** | 辅助模型打标接口 | 🔄 |
| **P0** | `DeriveTags()` + 改写 `GetTipsForContext()` | 🔄 |
| **P1** | `get_tool_tips` 新工具 | ⬜ |
| **P1** | Writeup 生成 + 自动打标 | 🔄 |
| **P2** | Memory 加 tags 列 + 检索改造 | ⬜ |
| **P2** | Knowledge frontmatter tags + search 权重 | ⬜ |
| **P3** | Solving protocol 条件化拆分 | ⬜ |
| **P3** | 前端 tag 管理 UI（可选） | ⬜ |
