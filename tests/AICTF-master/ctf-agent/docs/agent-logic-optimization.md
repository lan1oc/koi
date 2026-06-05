# CTF-Agent 逻辑审查与优化方案

> 审查日期: 2025-02-19
> 审查范围: 整个 Agent 逻辑体系（runner, orchestrator, subagent, strategy, compaction, tools, llm, prompt, memory, tips）

---

## 一、整体架构评估

### 1.1 架构优势
- **多 Agent 编排**：Coordinator + 专业 Sub-Agent 模式成熟，任务委派清晰
- **策略监控系统**：StrategyMonitor 重复检测 + 失败阻断 + 反思注入，形成完整的防死循环机制
- **上下文压缩**：分层压缩（soft/hard/emergency）设计合理，防止 token 溢出
- **多 Provider 容灾**：指数退避 + failover chain + key 轮转，鲁棒性好
- **知识沉淀体系**：tips + memory + ideas + writeup 多维知识管理

### 1.2 核心发现概要

| 优先级 | 类别 | 问题数 |
|--------|------|--------|
| 🔴 高 | Agent 主循环逻辑缺陷 | 5 |
| 🟡 中 | 性能与资源管理 | 6 |
| 🔵 低 | 代码质量与可维护性 | 5 |

---

## 二、高优先级问题（🔴 需尽快修复）

### 2.1 并行工具执行的竞态条件

**文件**: `backend/internal/agent/runner.go:620-698`

**问题**: 工具调用使用 `sync.WaitGroup` 并行执行，但多个工具可能同时写入同一个文件或操作同一个网络资源，导致不可预测的结果。特别是 `exec`、`write_file`、`python_exec` 等工具并行执行时，存在文件系统竞态。

**影响**: 工具结果不一致，极端情况下可能导致文件损坏。

**建议修复**:
```go
// 方案 A: 对文件操作类工具加互斥锁
// 方案 B: 识别有副作用的工具，对其串行执行，只并行化只读工具
// 方案 C (推荐): 引入工具分类标记

type Tool struct {
    Def       types.ToolDef
    Handler   ToolFunc
    SideEffect bool  // true = 有副作用，需串行执行
}

// runner.go 中修改为：
// 1. 先并行执行所有无副作用工具
// 2. 再串行执行有副作用工具
```

### 2.2 utilityReviewRound 的异步数据竞争

**文件**: `backend/internal/agent/runner.go:811`

**问题**: `utilityReviewRound` 通过 `go r.utilityReviewRound(...)` 异步执行，它内部调用 `r.toolEngine.Execute(ctx, "ideas", ...)` 修改 ideas 数据，但主循环同一时刻也可能在读取 ideas（通过 `getIdeasSummary`）。虽然 ideas 工具内部可能有锁，但 `r.cachedIdeasSummary` 缓存在 Runner 上，无锁保护。

**影响**: ideas 缓存可能读到脏数据，或在竞争条件下返回过期内容。

**建议修复**:
```go
// 对 cachedIdeasSummary 加锁保护
func (r *Runner) getIdeasSummary(ctx context.Context) string {
    r.mu.Lock()
    cached := r.cachedIdeasSummary
    r.mu.Unlock()
    if cached != "" {
        return cached
    }
    summary := r.fetchIdeasSummary(ctx)
    r.mu.Lock()
    r.cachedIdeasSummary = summary
    r.mu.Unlock()
    return summary
}
```

### 2.3 Sub-Agent 同步等待导致 Coordinator 阻塞

**文件**: `backend/internal/agent/subagent.go:324-482`

**问题**: `spawnAgent` 方法启动 sub-agent 后同步等待其完成（带 10 分钟超时）。这意味着 Coordinator 在整个 sub-agent 执行期间被阻塞在一个工具调用上，无法并行处理其他任务。如果 Coordinator 调用了多个 `spawn_agent`，它们在同一轮中并行执行（因为工具并行化），但这会导致多个 sub-agent 同时竞争资源。

**影响**: 
- 单次只能有效利用一个 sub-agent
- Coordinator 无法在 sub-agent 运行期间做出策略调整

**建议优化**:
```
方案: 引入异步 sub-agent 模式
1. spawn_agent 立即返回 agent_id + session_id
2. 新增 wait_agent(agent_id, timeout) 工具，让 Coordinator 自行控制何时回收
3. 新增 poll_agent(agent_id) 工具查询进度
4. 这样 Coordinator 可以并行启动多个 sub-agent，然后逐个 poll/wait
```

### 2.4 Compaction 与主循环的消息一致性

**文件**: `backend/internal/agent/runner.go:1291-1392`

**问题**: `maybeCompact` 在主循环开始时调用，它会 `LoadMessages` → 判断阈值 → `CompactContext/ClearToolOutputs` → `ReplaceMessages`。但在 compact 完成后到 `buildMessages` 之间，`utilityReviewRound`（异步）可能已经向 session 追加了新消息。这导致 `buildMessages` 读到的消息列表与 compact 后的状态不一致。

**影响**: 罕见情况下可能导致上下文不连贯。

**建议修复**:
```
方案: 将 compaction 与消息构建合并为一个原子操作
或者: 在 maybeCompact 中持有 session 级别锁，确保异步写入不会穿插
```

### 2.5 Flag 检测逻辑分散且不全面

**文件**: `backend/internal/agent/runner.go:722-749`

**问题**: Flag 检测仅通过特定工具名 (`flag_submit`, `ctfd_submit_flag`, `gzctf_submit_flag`) 判断，且依赖 `tr.success` 和特定输出字符串（"FLAG CORRECT"、"Accepted"）。如果 LLM 通过 `exec` 或 `python_exec` 直接打印出 flag，或者通过 `web_fetch` 获取到 flag 但未调用提交工具，flag 不会被自动捕获。虽然有 `reviewForFlag` 作为兜底，但它只在循环结束后执行。

**影响**: 中途发现 flag 但未通过专用工具提交时，agent 会继续浪费轮次。

**建议优化**:
```go
// 方案: 在每轮工具执行后，对所有工具输出做正则 flag 检测
flagPatterns := []string{`flag\{[^}]+\}`, `ctfshow\{[^}]+\}`, `FLAG\{[^}]+\}`, ...}
for _, tr := range results {
    for _, pattern := range flagPatterns {
        if matches := regexp.FindString(tr.output, pattern); matches != "" {
            // 记录候选 flag，提示 agent 验证
            candidateFlags = append(candidateFlags, matches)
        }
    }
}
if len(candidateFlags) > 0 {
    // 注入提示让 agent 验证并提交
    r.sessionMgr.AppendMessage(rc.SessionID, types.Message{
        Role:    "user",
        Content: fmt.Sprintf("[System] 检测到可能的 flag: %v，请验证并使用提交工具提交。", candidateFlags),
    })
}
```

---

## 三、中优先级问题（🟡 建议近期优化）

### 3.1 SSE 解码器逐字节读取效率低

**文件**: `backend/internal/llm/openai.go:319-349`

**问题**: `SSEDecoder.Next()` 使用 `reader.Read(tmp)` 每次仅读 1 字节，效率极低。对于长时间的 streaming 响应，这会产生大量系统调用。

**建议修复**:
```go
// 使用 bufio.Scanner 或 bufio.Reader 替代逐字节读取
type SSEDecoder struct {
    scanner *bufio.Scanner
}

func NewSSEDecoder(r io.Reader) *SSEDecoder {
    return &SSEDecoder{scanner: bufio.NewScanner(r)}
}

func (d *SSEDecoder) Next() (*SSEEvent, error) {
    for d.scanner.Scan() {
        line := strings.TrimSpace(d.scanner.Text())
        if line == "" { continue }
        if strings.HasPrefix(line, "data:") {
            data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
            if data == "[DONE]" { return nil, io.EOF }
            return &SSEEvent{Data: data}, nil
        }
    }
    return nil, d.scanner.Err()
}
```

### 3.2 Orchestrator 队列无限增长风险

**文件**: `backend/internal/agent/orchestrator.go:67-87`

**问题**: session 队列 (`chan func()`) 容量为 100，但 session worker goroutine 永不退出（除非 channel 被关闭）。长时间运行后，如果有大量不同 session 被创建，`queues` map 会无限增长，每个闲置 session 都保留一个 goroutine。

**建议修复**:
```go
// 方案: 添加空闲超时自动清理
func (o *Orchestrator) sessionWorker(sessionID string, q chan func()) {
    idleTimer := time.NewTimer(30 * time.Minute)
    for {
        select {
        case fn, ok := <-q:
            if !ok { return }
            idleTimer.Reset(30 * time.Minute)
            o.safeRun(sessionID, fn)
        case <-idleTimer.C:
            o.mu.Lock()
            close(q)
            delete(o.queues, sessionID)
            o.mu.Unlock()
            return
        }
    }
}
```

### 3.3 Token 计数仅使用估算，缺少精确计数

**文件**: `backend/internal/llm/provider.go:63-96`

**问题**: `CountTokens` 在 OpenAI 和 Anthropic provider 中都直接调用 `EstimateMessageTokens`（基于字符/词数估算），而非使用 tiktoken 等精确计数器。对于接近上下文窗口边界的长对话，估算误差可能导致过早或过晚触发 compaction。

**建议优化**:
```
方案 1: 集成 tiktoken-go 库用于 OpenAI 模型精确计数
方案 2: 在 compaction 阈值上增加安全余量（如从 75% 降到 70%）
方案 3: 利用 API 返回的实际 usage 数据动态校准估算系数
```

### 3.4 Prompt 构建缺少 Token 预算控制

**文件**: `backend/internal/agent/prompt.go:81-353`

**问题**: `BuildSystemPrompt` 将 identity + safety + skills + knowledge + challenge + tips + memories + protocol 全部拼接，没有对总长度做预算控制。当 skills 和 memories 很多时，system prompt 本身可能占用大量 context window，压缩留给对话的空间。

**建议优化**:
```go
// 在 BuildSystemPrompt 中添加 token 预算
const maxSystemPromptTokens = 8000

func BuildSystemPrompt(params PromptParams) string {
    // 1. 必选部分 (identity + safety + challenge): 先构建
    // 2. 可选部分 (skills, memories, tips, knowledge): 按优先级裁剪
    // 3. 如果超预算，依次砍掉: knowledge > memories > tips > skills 的详细内容
}
```

### 3.5 Anthropic 硬编码 max_tokens 为 32000

**文件**: `backend/internal/llm/anthropic.go:125`

**问题**: `body["max_tokens"] = 32000` 硬编码为 32000。虽然后面 `if req.MaxTokens > 0` 会覆盖，但对于未设置 MaxTokens 的请求（大部分 agent 主循环调用，MaxOutputTokens 默认 0），始终使用 32000。这可能导致浪费（实际输出远小于此）或对某些模型不适用。

**建议修复**:
```go
// 根据模型调整默认值
defaultMaxTokens := 8192
if strings.Contains(p.cfg.Model, "opus") || strings.Contains(p.cfg.Model, "sonnet") {
    defaultMaxTokens = 16000
}
body["max_tokens"] = defaultMaxTokens
if req.MaxTokens > 0 {
    body["max_tokens"] = req.MaxTokens
}
```

### 3.6 config.yaml 暴露敏感信息

**文件**: `backend/config.yaml:217-218`

**问题**: SageMath 服务器的 `api_key` 直接硬编码在 config.yaml 中（`16873e79571cd08723db4ca2dce6587e9426b23ddffda5db367d4deb708e7d22`），而非使用 `${SAGE_API_KEY}` 环境变量。该文件已被 git 跟踪。

**影响**: API Key 泄漏风险。

**建议修复**:
```yaml
sage:
  url: "http://110.42.47.91:8617/execute"
  api_key: "${SAGE_API_KEY}"
  timeout: 120
```

---

## 四、低优先级问题（🔵 持续改进）

### 4.1 全局单例过多，测试困难

**涉及文件**:
- `tips_store.go`: `globalTipsStore`, `globalMemoryStore`
- `auto_tagger.go`: `globalAutoTagger`
- `stats.go`: 全局 `Stats` 实例
- `tip_item_store.go`: 全局 `tipItemStore`
- `prompt_store.go`: 全局 `promptStore`

**问题**: 大量全局单例 (`var globalXxx`) 通过 `Set/Get` 函数访问，缺少依赖注入。这导致单元测试困难，组件间隐式耦合严重。

**建议**: 长期引入依赖注入容器或通过 `Runner` 结构体字段传递依赖。

### 4.2 MD5 哈希用于工具调用去重安全性不足

**文件**: `backend/internal/agent/strategy.go:375-379`

**问题**: `hashToolArgs` 使用 MD5 哈希来标识工具调用签名。虽然这里不涉及安全场景（仅用于去重），但 MD5 碰撞概率较高，可能导致不同工具调用被误判为相同。

**建议**: 替换为更安全且性能相当的 `xxhash` 或 `fnv` 哈希。

### 4.3 extractJSON 函数重复实现

**文件**: 
- `runner.go` 中的 `extractJSON` 方法（通过 goto 语句）
- `auto_tagger.go` 注释提到已移至 `util.go`
- `memory_deduplicator.go` 使用 `util.ExtractJSON`

**问题**: JSON 提取函数在多处有不同实现，部分使用 `goto` 语句（`runner.go:1119-1133`），代码风格不一致。

**建议**: 统一到 `internal/util` 包，删除重复实现。

### 4.4 Runner 结构体字段过多

**文件**: `backend/internal/agent/runner.go:24-51`

**问题**: `Runner` 结构体已有 20+ 字段，承担了太多职责（LLM 调用、工具执行、策略监控、TodoList 管理、ideas 缓存、compaction 等）。随着功能增长，这个结构体会越来越难以维护。

**建议**: 将 Runner 拆分为多个职责明确的子组件：
```
Runner
├── ContextManager    // 消息构建、compaction、token 管理
├── StrategyMonitor   // 已独立，保持不变
├── ToolExecutor      // 工具执行、并行控制、结果收集
├── FlagDetector      // flag 检测、验证、提交
└── PostSolveProcessor // writeup、lessons、reflection、memory 提取
```

### 4.5 缺少关键路径的单元测试

**问题**: 以下核心逻辑缺少测试：
- `processStream` 的各种边界情况（工具调用中断、thinking overflow）
- `sanitizeAnthropicMessages` 的复杂消息序列
- `CompactContext` 在 split 边界的正确性
- `StrategyMonitor` 的 ping-pong 检测

**建议**: 为上述函数编写表驱动测试（table-driven tests）。

---

## 五、功能增强建议

### 5.1 动态工具选择策略

**现状**: 工具按 category 静态配置（`policy_overrides`），同一类别始终暴露相同工具集。

**建议**: 根据解题进度动态调整可用工具：
- 前 5 轮仅暴露侦查类工具（read_file, grep, strings, checksec）
- 中期开放攻击类工具
- 后期开放提交类工具
- 这可以引导 agent 遵循「侦查→分析→攻击→提交」的方法论

### 5.2 工具执行超时控制

**现状**: 工具执行没有统一超时机制。`exec` 等工具可能执行很长时间的命令（如 `sqlmap --wizard`），占据整个轮次。

**建议**:
```go
// 在 Engine.Execute 中添加统一超时
func (e *Engine) Execute(ctx context.Context, name, args string, emit EventEmitter) (string, error) {
    timeout := e.getToolTimeout(name) // 不同工具不同超时
    ctx, cancel := context.WithTimeout(ctx, timeout)
    defer cancel()
    // ...
}
```

### 5.3 思维链（CoT）利用率提升

**现状**: `thinkingMsg` 被截断存储后基本弃用，未参与后续决策。

**建议**: 在 `utilityReviewRound` 中同时传入 thinking 内容，让 utility model 从 agent 的推理过程中提取更精准的 ideas 更新。

### 5.4 跨 Session 知识传递

**现状**: 每个 session 独立，同一题目的多次尝试之间仅通过 ideas（按 challenge_id）共享信息。

**建议**: 
- 在创建新 session 时，自动加载同一 challenge 的历史 session 摘要
- 将前次失败的 compaction summary 作为 RAG context 注入新 session

### 5.5 Coordinator 直接解题的优化

**现状**: 当 Coordinator 不 spawn sub-agent 而是直接解题时，它看到的工具集不受 category policy 限制（因为 `coordinator` 类型在 policy_overrides 中通常没有定义或定义过宽）。

**建议**: 为 coordinator 直接解题场景设计专门的策略——如果 Coordinator 决定不委派，自动根据题目 category 收窄工具集，避免暴露不相关的 30+ 工具干扰 LLM 选择。

---

## 六、实施优先级排序

### Phase 1（本周）
1. ✅ 修复 config.yaml 中的 API key 泄漏（§3.6）
2. ✅ 修复 `cachedIdeasSummary` 竞态（§2.2）
3. ✅ 增强 flag 检测覆盖率（§2.5）

### Phase 2（下周）
4. SSE 解码器性能优化（§3.1）
5. Orchestrator 空闲清理（§3.2）
6. 工具并行执行策略改进（§2.1）

### Phase 3（中期）
7. Prompt token 预算控制（§3.4）
8. Sub-Agent 异步模式（§2.3）
9. Token 精确计数（§3.3）
10. 工具执行超时控制（§5.2）

### Phase 4（长期）
11. Runner 结构体拆分（§4.4）
12. 依赖注入重构（§4.1）
13. 单元测试补全（§4.5）
14. 动态工具选择（§5.1）
15. 跨 Session 知识传递（§5.4）

---

## 七、总结

整体来看，项目的 Agent 逻辑架构设计合理且功能完善，已具备以下核心能力：

- ✅ 多层策略防御（planning → 重复检测 → 反思注入 → 方法阻断）
- ✅ 弹性上下文管理（3 级 compaction + emergency compact）
- ✅ 多 Provider 容灾（failover + 指数退避 + key 轮转）
- ✅ 知识沉淀闭环（tips ← extraction ← reflection → memory）

主要改进方向集中在：
1. **并发安全**：工具并行执行和异步 utility review 的竞态条件
2. **资源管理**：goroutine 泄漏、SSE 解码效率、token 预算
3. **智能增强**：动态工具选择、跨 session 知识、思维链利用

建议按照 Phase 1-4 的优先级逐步实施，每个 Phase 完成后进行回归测试。
