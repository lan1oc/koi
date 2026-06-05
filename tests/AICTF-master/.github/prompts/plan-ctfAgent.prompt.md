## Plan: CTF 解题 Agent 平台（基于 OpenClaw 架构）

借鉴 openclaw 的核心架构模式（Agent 循环、工具策略链、惰性技能加载、子代理协作、流式事件处理、上下文压缩），重新用 **Go 后端 + React 前端** 实现一个专注于 CTF 全方向解题的 AI Agent 平台。支持多模型切换/回退、MCP 工具协议、多 Agent 协作、实时终端、知识库积累和自动化评测。

---

### 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    React 前端 (Vite + React)                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐│
│  │ 聊天面板  │ │ 题目管理  │ │ 知识库    │ │ 实时终端(xterm) ││
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘│
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ Agent监控 │ │ Flag提交  │ │ Writeup  │                    │
│  └──────────┘ └──────────┘ └──────────┘                    │
└──────────────────────┬──────────────────────────────────────┘
                       │ WebSocket + REST API
┌──────────────────────▼──────────────────────────────────────┐
│                      Go 后端                                 │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                  API Gateway (Gin/Fiber)                 ││
│  │           WebSocket Hub  │  REST Endpoints              ││
│  └────────────────┬────────┴───────────────────────────────┘│
│  ┌────────────────▼────────────────────────────────────────┐│
│  │              Agent Orchestrator                          ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ ││
│  │  │Agent Loop │ │Session   │ │Context   │ │SubAgent    │ ││
│  │  │ Manager  │ │ Manager  │ │Compactor │ │ Spawner    │ ││
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────┘ ││
│  └────────────────┬────────────────────────────────────────┘│
│  ┌────────────────▼────────────────────────────────────────┐│
│  │              Tool Engine                                 ││
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐           ││
│  │  │内置工具 │ │CTF工具  │ │MCP Client│ │ Skill │           ││
│  │  │exec/rw │ │专用工具  │ │ Bridge  │ │Loader │           ││
│  │  └────────┘ └────────┘ └────────┘ └────────┘           ││
│  └────────────────┬────────────────────────────────────────┘│
│  ┌────────────────▼────────────────────────────────────────┐│
│  │           LLM Provider Layer                             ││
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐           ││
│  │  │OpenAI  │ │Anthropic│ │Ollama  │ │ Any    │           ││
│  │  │GPT-4o  │ │Claude  │ │ Local  │ │OpenAI  │           ││
│  │  │ o3     │ │Opus/Son│ │LLaMA   │ │compat  │           ││
│  │  └────────┘ └────────┘ └────────┘ └────────┘           ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Storage: SQLite/PostgreSQL + 文件系统(会话JSONL/知识库)  ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

### Steps

#### 第一阶段：项目脚手架与基础设施

**1. 项目目录结构**

```
ctf-agent/
├── frontend/              # React 前端
│   ├── src/
│   │   ├── components/    # UI 组件
│   │   ├── pages/         # 页面
│   │   ├── hooks/         # 自定义 hooks
│   │   ├── stores/        # 状态管理 (zustand)
│   │   ├── services/      # API/WebSocket 客户端
│   │   └── types/         # TypeScript 类型
│   └── package.json
├── backend/               # Go 后端
│   ├── cmd/server/        # 入口
│   ├── internal/
│   │   ├── api/           # HTTP/WS handler
│   │   ├── agent/         # Agent 核心循环
│   │   ├── llm/           # LLM Provider 抽象
│   │   ├── tools/         # 工具引擎
│   │   ├── mcp/           # MCP 客户端
│   │   ├── session/       # 会话管理
│   │   ├── skill/         # 技能系统
│   │   ├── challenge/     # 题目管理
│   │   ├── knowledge/     # 知识库
│   │   ├── terminal/      # 终端管理 (PTY)
│   │   └── config/        # 配置
│   ├── skills/            # CTF 技能文件 (Markdown)
│   ├── go.mod
│   └── go.sum
├── docker-compose.yml     # 开发环境编排
└── README.md
```

**2. 后端初始化**
- 使用 Go 1.22+，依赖 `github.com/gin-gonic/gin` 或 `github.com/gofiber/fiber` 作为 HTTP 框架
- `github.com/gorilla/websocket` 处理 WebSocket
- `github.com/creack/pty` 管理本地 PTY 终端
- SQLite（`modernc.org/sqlite`）或 PostgreSQL 作为元数据存储
- 配置管理用 Viper，环境变量 + YAML 配置文件

**3. 前端初始化**
- Vite + React 18 + TypeScript
- UI 库: Ant Design 或 shadcn/ui
- 状态管理: Zustand
- 终端: xterm.js + xterm-addon-fit
- Markdown 渲染: react-markdown + rehype-highlight (展示 writeup)
- WebSocket 客户端封装

---

#### 第二阶段：Agent 核心循环（借鉴 openclaw `pi-embedded-runner`）

**4. Agent Loop Manager** — 参考 openclaw 的 `src/agents/pi-embedded-runner/run.ts`

核心循环实现为 Go 的 goroutine 状态机：

```
用户输入 → 构建 Prompt → 调用 LLM(stream) → 解析响应
    ↓                                            ↓
如果纯文本 → 返回给用户              如果 tool_call → 执行工具
                                         ↓
                                    工具结果注入消息历史
                                         ↓
                                    回到「调用 LLM」步骤
                                    （直到 LLM 返回纯文本 或 达到最大轮次）
```

关键组件：
- `AgentRunner` 结构体：管理单次 agent 运行的完整生命周期
- `RunQueue`（参考 openclaw 的 lane 队列）：每个会话一个 goroutine 队列，防止并发冲突
- 最大工具调用轮次限制（如 50 轮），防止无限循环
- 流式事件通过 WebSocket 推送到前端：`agent_start`, `message_delta`, `tool_call_start`, `tool_call_result`, `agent_end`

**5. Session Manager** — 参考 openclaw 的 JSONL 会话存储

- 每次解题创建一个 Session，底层用 JSONL 文件存储完整对话历史
- 支持会话分支（branch）：从历史某个节点分叉尝试不同解题路径
- 会话元数据（关联的题目 ID、状态、flag）存入数据库
- 文件锁保证并发安全

**6. Context Compactor** — 参考 openclaw 的 `src/agents/compaction.ts`

- 监控当前消息历史的 token 数量（使用 `tiktoken-go`）
- 接近上下文窗口上限时，调用 LLM 对旧消息生成摘要
- 用摘要替换旧消息，保留最近 N 轮完整对话
- 特别保留工具调用中的关键发现（如部分 flag、漏洞特征）

---

#### 第三阶段：LLM Provider 抽象层

**7. Provider 接口设计** — 参考 openclaw 的多 provider + failover 机制

```go
type LLMProvider interface {
    ChatStream(ctx context.Context, req ChatRequest) (<-chan StreamEvent, error)
    CountTokens(messages []Message) (int, error)
    Name() string
    MaxContextTokens() int
}
```

实现：
- `OpenAIProvider` — 支持 GPT-4o, o3, o4-mini 等，通过 OpenAI API
- `AnthropicProvider` — 支持 Claude Opus/Sonnet，通过 Anthropic API
- `OllamaProvider` — 本地模型，通过 Ollama REST API
- `OpenAICompatProvider` — 任何兼容 OpenAI 格式的 API（DeepSeek、Qwen、Groq 等）

**8. Auth Profile 轮转与模型 Failover** — 参考 openclaw 的 `src/agents/auth-profiles.ts` 和 `src/agents/model-fallback.ts`

- 同一 Provider 支持配置多个 API Key，限流时自动切换
- 配置 Failover 链：如 `Claude Opus → GPT-4o → DeepSeek`
- 记录每个 profile 的冷却时间和错误计数

---

#### 第四阶段：工具引擎

**9. 内置工具** — 参考 openclaw 的 `src/agents/pi-tools.ts`

| 工具名 | 功能 | 实现方式 |
|--------|------|----------|
| `exec` | 执行 shell 命令 | `os/exec` + PTY，输出实时流式推送到前端终端 |
| `read_file` | 读取文件内容 | 标准文件 I/O，支持行范围 |
| `write_file` | 写入文件 | 标准文件 I/O |
| `grep` | 搜索文件内容 | 调用 ripgrep 或内置实现 |
| `find` | 查找文件 | `filepath.WalkDir` + glob |
| `web_fetch` | 抓取网页内容 | `net/http` + HTML-to-text 提取 |
| `web_search` | 搜索引擎查询 | Brave/Serper/Google API |
| `python_exec` | 执行 Python 脚本 | 调用 `python3` 子进程 |

**10. CTF 专用工具** — 这是区别于通用 Agent 的核心

| 工具名 | 方向 | 功能 |
|--------|------|------|
| `nmap_scan` | Web/Misc | 端口扫描和服务探测 |
| `sqlmap` | Web | SQL 注入自动化检测 |
| `burp_request` | Web | 发送自定义 HTTP 请求（类 curl 增强版） |
| `gdb_debug` | Pwn | 启动 GDB 调试会话，支持交互式命令 |
| `pwntools_script` | Pwn | 生成并执行 pwntools exploit 脚本 |
| `checksec` | Pwn | 检查二进制安全特性（NX/PIE/Canary） |
| `ghidra_decompile` | Reverse | 调用 Ghidra headless 反编译 |
| `radare2` | Reverse | r2 命令行分析 |
| `strings_analyze` | Reverse/Misc | 提取二进制字符串 |
| `crypto_toolkit` | Crypto | 常见密码学操作（频率分析、RSA 工具、hash 破解） |
| `sage_math` | Crypto | 执行 SageMath 脚本 |
| `steg_detect` | Misc | 隐写术检测（binwalk, steghide, zsteg） |
| `forensics` | Misc | 取证工具（volatility, foremost, exiftool） |
| `flag_submit` | 通用 | 向 CTF 平台自动提交 flag |

**11. 工具策略系统** — 参考 openclaw 的 `src/agents/tool-policy.ts`

多层策略链过滤：
```
全局策略 → Agent 策略 → 题目类型策略 → 用户自定义
```
例如：Web 类型题目自动启用 `sqlmap`、`burp_request`，禁用 `gdb_debug`

**12. MCP 工具桥接**

- 实现 MCP (Model Context Protocol) 客户端，支持 `stdio` 和 `sse` 传输
- 用户可在配置中声明 MCP Server（如 IDA Pro MCP、Browser MCP）
- Agent 运行时动态发现 MCP Server 提供的工具，注册为可用工具
- 参考 MCP SDK 的 Go 实现（`github.com/mark3labs/mcp-go`）

---

#### 第五阶段：技能系统（CTF 解题策略）

**13. CTF Skill 定义** — 参考 openclaw 的 `skills/` 和 `src/agents/skills/types.ts`

每个 Skill 是一个 Markdown 文件，定义解题策略和步骤：

```
skills/
├── web/
│   ├── sql-injection/SKILL.md
│   ├── xss/SKILL.md
│   ├── ssrf/SKILL.md
│   ├── file-upload/SKILL.md
│   └── deserialization/SKILL.md
├── pwn/
│   ├── buffer-overflow/SKILL.md
│   ├── rop-chain/SKILL.md
│   ├── heap-exploitation/SKILL.md
│   ├── format-string/SKILL.md
│   └── shellcode/SKILL.md
├── reverse/
│   ├── static-analysis/SKILL.md
│   ├── dynamic-debug/SKILL.md
│   ├── deobfuscation/SKILL.md
│   └── android-re/SKILL.md
├── crypto/
│   ├── rsa-attacks/SKILL.md
│   ├── aes-cbc/SKILL.md
│   ├── classical-cipher/SKILL.md
│   └── hash-extension/SKILL.md
└── misc/
    ├── steganography/SKILL.md
    ├── forensics/SKILL.md
    ├── network-pcap/SKILL.md
    └── encoding/SKILL.md
```

**Skill 示例**（`skills/web/sql-injection/SKILL.md`）：
```markdown
---
name: sql-injection
description: SQL 注入漏洞检测与利用
category: web
tools_required: [exec, burp_request, sqlmap, python_exec]
---
# SQL 注入解题策略
1. 首先识别注入点：对所有 GET/POST 参数逐一测试
2. 判断注入类型：联合查询 / 布尔盲注 / 时间盲注 / 报错注入
3. 使用 sqlmap 自动化检测...
4. 手动构造 payload：...
5. 提取 flag：...
```

**14. 技能加载** — 惰性加载模式（同 openclaw）

- 系统提示中只列出所有技能的名称和描述
- Agent 根据题目特征自主决定读取哪个 SKILL.md
- 支持用户自定义技能目录，优先级高于内置技能

---

#### 第六阶段：多 Agent 协作

**15. 子 Agent 生成** — 参考 openclaw 的 `src/agents/tools/sessions-spawn-tool.ts`

- **主 Agent（Coordinator）**：分析题目，判断类型，分发给专业子 Agent
- **子 Agent**：按 CTF 方向特化，拥有不同的系统提示和工具子集
  - `WebAgent` — Web 安全专家
  - `PwnAgent` — 二进制利用专家
  - `ReverseAgent` — 逆向工程专家
  - `CryptoAgent` — 密码学专家
  - `MiscAgent` — 杂项/取证专家
- 子 Agent 的系统提示使用 `minimal` 模式（参考 openclaw 的 prompt mode），专注于自己的领域
- 主 Agent 通过 `spawn_agent` 工具创建子 Agent，通过 `send_to_agent` / `get_agent_history` 通信
- 子 Agent 完成后通知主 Agent 汇总结果

**16. 协作通信机制**

- 每个 Agent 运行在独立的 goroutine 中，有自己的会话和消息历史
- Agent 间通过内存 channel + 消息队列通信
- 前端通过 WebSocket 可同时监控所有 Agent 的实时输出

---

#### 第七阶段：题目管理与自动化评测

**17. 题目管理模块**

数据库 schema:
```sql
CREATE TABLE challenges (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,  -- web/pwn/reverse/crypto/misc
    platform    TEXT,           -- ctfhub/buuoj/hackthebox/自定义
    url         TEXT,           -- 题目链接或靶机地址
    description TEXT,
    attachments TEXT,           -- 附件文件路径列表 (JSON)
    flag        TEXT,           -- 已知 flag (验证用)
    status      TEXT DEFAULT 'pending', -- pending/solving/solved/failed
    created_at  TIMESTAMP,
    solved_at   TIMESTAMP
);
```

- REST API: CRUD 题目，批量导入，按分类/状态筛选
- 支持附件上传（二进制文件、pcap 包等），存储到本地文件系统
- 支持从 CTF 平台 API 自动拉取题目（如 CTFd API）

**18. Flag 自动提交与验证**

- `flag_submit` 工具：Agent 发现 flag 后自动调用
- 支持正则匹配 flag 格式（如 `flag{...}`, `ctf{...}`）
- 对接 CTF 平台 API 自动提交
- 提交结果反馈给 Agent 继续决策

---

#### 第八阶段：知识库

**19. Writeup 自动生成与存储**

- 每次成功解题后，Agent 自动总结解题过程生成 Writeup（Markdown）
- 存储结构：
  ```
  knowledge/
  ├── web/
  │   ├── sql-injection-buu-easy.md
  │   └── xss-reflected-htb.md
  ├── pwn/
  │   └── stack-overflow-basic.md
  └── ...
  ```
- 知识库作为 RAG 源：新题目开始前，搜索相似 writeup 注入上下文
- 使用文本 embedding（OpenAI Ada / 本地 BGE）+ 向量搜索（内存 HNSW 或 SQLite FTS5）

**20. 解题回放**

- 前端可查看完整的解题对话历史（从 JSONL 会话文件）
- 支持查看每一步的工具调用和输出
- 时间线视图展示解题过程

---

#### 第九阶段：前端实现

**21. 页面设计**

| 页面 | 功能 |
|------|------|
| **Dashboard** | 解题统计、近期活动、各分类进度 |
| **Challenges** | 题目列表、筛选、导入、状态标签 |
| **Solve** | 核心解题页面：聊天面板 + 终端 + 文件树 + Agent 状态 |
| **Knowledge** | Writeup 库浏览、搜索 |
| **Settings** | LLM 配置、工具配置、MCP Server 管理 |

**22. 核心解题页面布局**

```
┌──────────────────────────────────────────────────┐
│ 题目信息栏: [标题] [分类:Web] [状态:解题中] [Flag提交] │
├─────────────────────┬────────────────────────────┤
│                     │                            │
│   聊天面板           │   实时终端 (xterm.js)       │
│   (Agent 对话流)     │   (Agent exec 输出)        │
│   - 思考过程         │                            │
│   - 工具调用卡片     │                            │
│   - 代码高亮         │                            │
│                     ├────────────────────────────┤
│                     │   文件查看器                 │
│                     │   (Agent 读写的文件)         │
│                     │                            │
├─────────────────────┴────────────────────────────┤
│ Agent 状态栏: [主Agent:思考中] [WebAgent:执行sqlmap] │
└──────────────────────────────────────────────────┘
```

**23. WebSocket 事件协议**

前后端通过 WebSocket 通信，事件类型参考 openclaw 的流式事件：

```typescript
type WSEvent =
  | { type: "agent_start"; agentId: string; model: string }
  | { type: "message_delta"; content: string }
  | { type: "thinking_delta"; content: string }
  | { type: "tool_call_start"; toolName: string; args: object }
  | { type: "tool_call_output"; output: string; isStreaming: boolean }
  | { type: "tool_call_end"; toolName: string; success: boolean }
  | { type: "terminal_output"; sessionId: string; data: string }
  | { type: "agent_end"; flagFound?: string }
  | { type: "error"; message: string }
```

**24. 实时终端**

- 后端为每个解题会话维护一个 PTY 会话池
- Agent 的 `exec` 工具执行的命令输出同时推送到前端 xterm.js
- 用户也可直接在终端输入命令（手动介入模式）
- WebSocket 双向数据流：后端 PTY → 前端 xterm / 前端键盘输入 → 后端 PTY

---

#### 第十阶段：系统提示工程

**25. 系统提示构建** — 参考 openclaw 的 `src/agents/system-prompt.ts`

主 Agent 系统提示结构（分段动态组装）：

```
[身份] 你是一个 CTF 解题 AI Agent，擅长...
[安全] 不执行任何超出解题范围的操作
[工具] 当前可用工具列表及使用说明
[技能] <available_skills> 列出所有可用解题技能 </available_skills>
[知识] 相关 writeup 摘要（RAG 检索结果）
[题目] 当前题目信息、附件、URL
[解题规范]
  - 先分析题目类型，选择合适的 skill
  - 逐步推理，每步验证
  - 发现 flag 后立即调用 flag_submit
  - 遇到困难时尝试不同方法
  - 可以 spawn 子 Agent 处理特定子任务
[运行时] OS、已安装工具、工作目录
[上下文文件] 注入的 AGENTS.md 等配置
```

---

### Verification

1. **单元测试**
   - Go 后端：每个 package 编写 `_test.go`，覆盖 Agent Loop、工具执行、LLM 调用 Mock、Session 读写
   - React 前端：Vitest + React Testing Library 测试关键组件

2. **集成测试**
   - 准备 3-5 道不同类型的模拟 CTF 题目（简单难度）
   - 端到端测试：前端发起解题 → Agent 推理 → 工具调用 → Flag 提交
   - 验证多 Agent 协作流程

3. **手动验证**
   - 用真实 CTF 平台题目（如 BUUCTF 的入门题）测试解题效果
   - 验证 MCP 工具集成（如 IDA Pro MCP 用于逆向题）
   - 验证上下文压缩在长对话中的效果
   - 验证模型 failover 在 API 限流时的行为

4. **性能验证**
   - WebSocket 流式输出延迟 < 100ms
   - 终端输出实时性
   - 并发多题目解题稳定性

---

### Decisions

- **选择本地执行而非 Docker 沙盒**：按用户要求。CTF 解题通常需要直接访问工具链（GDB、Ghidra 等），本地执行更灵活。但保留未来添加 Docker 隔离的扩展点。
- **会话存储用 JSONL 文件而非纯数据库**：参考 openclaw 的做法，JSONL 适合追加写入的对话日志，数据库只存元数据。方便调试和回放。
- **技能惰性加载**：参考 openclaw，系统提示只列描述，Agent 按需读取完整 SKILL.md。节省 token，保持灵活。
- **Go + goroutine 替代 openclaw 的 TS 异步 + 队列**：Go 原生并发模型天然适合 Agent 并发管理，goroutine 替代 lane 队列，channel 替代事件总线。
- **MCP 客户端集成**：用户要求 MCP 支持，通过 `mcp-go` 库实现标准 MCP 客户端，运行时动态注册 MCP Server 暴露的工具。
- **前端用 xterm.js 实现实时终端**：通过 WebSocket 双向绑定后端 PTY，同时支持 Agent 自动执行和用户手动介入。
