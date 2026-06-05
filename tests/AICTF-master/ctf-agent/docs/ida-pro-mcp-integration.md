# IDA Pro MCP 无头模式适配改动

## 概述

为了让 CTF Agent 能够使用 IDA Pro 的无头模式（idalib）进行二进制分析，对后端 MCP 客户端、工具策略、Agent 提示词进行了全面适配。

---

## 一、MCP 传输层改动

### 文件：`backend/internal/mcp/client.go`

### 1.1 SSE 传输基础实现
- 实现完整的 **Legacy HTTP+SSE** 传输：`GET /sse` 建立长连接，接收 `endpoint` 事件后通过 `POST` 发送 JSON-RPC 请求
- `sseReadLoop` 处理多行 SSE 事件解析、JSON-RPC 响应分发

### 1.2 连接状态追踪
- `Client` 新增 `connecting` map，追踪正在连接中的服务器
- `GetStatus()` 返回三态：`connected` / `connecting` / `disconnected`
- `ServerStatus` 新增 `Connecting bool` 字段

### 1.3 SSE 断线自动重连
- `ServerConn` 新增 `done chan struct{}` 区分主动断开和意外断线
- `sseReadLoop` 检测流关闭后自动触发 `reconnectSSE()`，指数退避重试
- `Disconnect()` 和 `Close()` 关闭 `done` channel 阻止重连

### 1.4 Streamable HTTP 传输实现
- 新增 `connectStreamableHTTP()` — POST JSON-RPC 到 `/mcp` 端点，直接获取 JSON 响应
- 新增 `sendRequestStreamableHTTP()` — 无需持久连接，每次请求独立 POST
- 新增 `sendNotificationStreamableHTTP()` — POST 通知

### 1.5 协议自动检测
- `Connect()` 中 transport 为 `"sse"` 时：
  1. 先尝试 Streamable HTTP（`POST /mcp`）
  2. 失败（400/404/405）则降级到 Legacy SSE
- IDA Pro MCP 的 zeromcp 库同时支持 `/mcp` 和 `/sse`，优先走更稳定的 Streamable HTTP

### 1.6 多传输类型分发
- `sendRequest()` / `sendNotification()` / `Disconnect()` / `Close()` 全部改为 `switch` 分发
- 支持 `sse` / `streamable_http` / `stdio` 三种传输

---

## 二、API 层改动

### 文件：`backend/internal/api/server.go`

- `mcpServerResp()` 增加 `"connecting"` 状态返回
- `connectMCPServer()` 修复重复 `c.JSON` 调用，添加 WS 广播通知前端
- `loadPersistedMCPServers()` 改为异步连接，避免阻塞服务器启动
- WSEvent.Data 序列化修复（map → JSON string）

---

## 三、前端改动

### 文件：`frontend/src/pages/McpManager.tsx`

- `handleConnect` 收到 `"connecting"` 状态后启动轮询
- 每 2 秒查询服务器状态，直到 `connected` 或 `disconnected`

---

## 四、工具策略改动

### 文件：`backend/internal/tools/engine.go`

- `GetToolDefs()` 自动放行所有 `mcp_*` 前缀工具
- MCP 工具名是动态的（`mcp_<server>_<tool>`），无法在 `config.yaml` 的 `policy_overrides` 中硬编码
- 所有 agent 类型都能自动使用已连接的 MCP 工具

---

## 五、Agent 提示词改动

### 文件：`backend/internal/agent/prompt.go`

### pwn agent
- **Identity**：新增 IDA Pro MCP 工具提示，优先使用 IDA Pro
- **Safety Constraints**：
  - 禁止本地运行二进制（可能是恶意文件）
  - 只允许静态分析工具：IDA Pro (MCP), checksec, strings, radare2, ghidra_decompile
  - 只能通过 `pwntools remote()` 交互远程服务
- **Phase 1**：优先 `idalib_open` 加载二进制到 IDA Pro
- **Phase 2**：用 IDA Pro 反编译 + 分析完整调用链
- 移除 "Test locally first" 建议

### reverse agent
- **Identity**：新增 IDA Pro MCP 工具提示
- **Safety Constraints**：
  - 禁止运行二进制
  - 通过反编译提取逻辑后用 Python 实现逆向
- **Phase 2**：改为 "Static Analysis with IDA Pro"，优先 `idalib_open`
- 新增 IDA xref 数据流追踪分析
- Anti-debug 改为 "use static analysis only, do NOT run the binary"

---

## 六、配置方式

### API JSON 格式
```json
{
  "name": "ida-pro-headless",
  "transport": "sse",
  "url": "http://127.0.0.1:8745/sse"
}
```

### config.yaml 格式
```yaml
mcp:
  servers:
    - name: "ida-pro-headless"
      transport: "sse"
      url: "http://127.0.0.1:8745/sse"
```

### 启动 IDA Pro MCP 无头服务器
```bash
cd D:\AI\AICTF\Tools\IDA\ida-pro-mcp-main
uv run idalib-mcp --host 127.0.0.1 --port 8745
```

### 协议自动检测流程
```
配置 transport: "sse", url: "http://127.0.0.1:8745/sse"
    │
    ├─ 1. POST InitializeRequest → http://127.0.0.1:8745/mcp
    │     ├─ 200 OK → Streamable HTTP（简单可靠）
    │     └─ 400/404/405 → 降级
    │
    └─ 2. GET http://127.0.0.1:8745/sse → Legacy SSE
```
