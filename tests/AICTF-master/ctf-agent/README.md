# LovelyIrisAgent

AI-powered Capture The Flag solving platform. Multi-agent, multi-provider, tool-augmented architecture inspired by [OpenClaw](https://github.com/nicepkg/openclaw).

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  React Frontend                  │
│  Dashboard │ Challenges │ Solve │ Knowledge      │
│  WebSocket streaming │ xterm.js terminal         │
├─────────────────────────────────────────────────┤
│                REST + WebSocket                  │
├─────────────────────────────────────────────────┤
│                   Go Backend                     │
│                                                  │
│  ┌─────────┐  ┌──────────┐  ┌──────────────┐   │
│  │  Agent   │  │   LLM    │  │    Tools      │   │
│  │  Runner  │  │ Provider │  │  8 builtin    │   │
│  │  Loop    │  │ Registry │  │  14 CTF       │   │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       │             │               │            │
│  ┌────┴─────┐  ┌────┴─────┐  ┌─────┴──────┐    │
│  │ Session  │  │ OpenAI   │  │ MCP Bridge │    │
│  │ Manager  │  │ Anthropic│  │            │    │
│  │ (JSONL)  │  │ Ollama   │  │ Skills     │    │
│  └──────────┘  │ DeepSeek │  │ Loader     │    │
│                └──────────┘  └────────────┘    │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │Challenge │  │Knowledge │  │  Terminal     │  │
│  │ Store    │  │  Store   │  │  Manager     │  │
│  │ (SQLite) │  │  (Files) │  │  (PTY)       │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
└─────────────────────────────────────────────────┘
```

## Features

- **Multi-Agent Collaboration**: Coordinator spawns specialized sub-agents (web, pwn, reverse, crypto, misc) 
- **Multi-Provider LLM**: OpenAI, Anthropic, Ollama, DeepSeek with key rotation & failover chains
- **22 Built-in Tools**: 8 general (exec, read/write file, grep, find, web_fetch, python) + 14 CTF-specific (nmap, sqlmap, gdb, pwntools, ghidra, radare2, crypto_toolkit, sage_math, steg_detect, forensics, etc.)
- **MCP Protocol Bridge**: Extend with any MCP-compatible tool server
- **Skill System**: Lazy-loaded Markdown skill files with YAML frontmatter, organized by CTF category
- **Context Compaction**: Automatic context summarization when approaching token limits
- **Session Branching**: Fork conversation at any point to explore alternative approaches
- **Knowledge Base**: Auto-generated writeups for solved challenges, searchable
- **Real-time Streaming**: WebSocket-based SSE forwarding of LLM + tool outputs
- **Integrated Terminal**: xterm.js-backed PTY sessions for live tool interaction
- **Dynamic System Prompts**: Category-aware prompts with tool/skill/knowledge injection

## Quick Start

### Prerequisites
- Go 1.22+
- Node.js 20+
- Docker (optional, for sandbox)
- At least one LLM API key (OpenAI/Anthropic/etc.)

### Development

```bash
# Clone
git clone <repo-url>
cd ctf-agent

# Backend
cd backend
cp config.yaml config.local.yaml
# Edit config.local.yaml with your API keys
go mod tidy
go run ./cmd/server

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### Docker Compose

```bash
# Set API keys
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# Start all services
docker compose up -d

# With CTF sandbox (Kali tools)
docker compose --profile sandbox up -d
```

## Configuration

Edit `backend/config.yaml`:

```yaml
llm:
  providers:
    - name: openai
      type: openai
      api_key: ${OPENAI_API_KEY}
      model: gpt-4o
      
    - name: anthropic
      type: anthropic
      api_key: ${ANTHROPIC_API_KEY}
      model: claude-sonnet-4-20250514

  failover_chain: [openai, anthropic]

agent:
  max_tool_rounds: 50
  compaction_threshold: 0.75

tools:
  policy_overrides:
    web: [exec, web_fetch, sqlmap, burp_request, nmap_scan]
    pwn: [exec, gdb_debug, pwntools_script, checksec, radare2]
    crypto: [exec, python_exec, crypto_toolkit, sage_math]
```

## Project Structure

```
ctf-agent/
├── backend/
│   ├── cmd/server/         # Entry point
│   ├── internal/
│   │   ├── config/         # Viper-based configuration
│   │   ├── types/          # Core data types
│   │   ├── llm/            # LLM provider abstraction
│   │   ├── session/        # JSONL session management
│   │   ├── agent/          # Agent loop, compaction, orchestration
│   │   ├── tools/          # Tool engine + built-in + CTF tools
│   │   ├── mcp/            # MCP protocol client bridge
│   │   ├── skill/          # Markdown skill loader
│   │   ├── challenge/      # Challenge CRUD (SQLite)
│   │   ├── knowledge/      # Writeup storage & search
│   │   ├── terminal/       # PTY session management
│   │   └── api/            # HTTP + WebSocket server
│   ├── skills/             # CTF skill markdown files
│   │   ├── web/
│   │   ├── pwn/
│   │   ├── reverse/
│   │   ├── crypto/
│   │   ├── misc/
│   │   └── forensics/
│   ├── config.yaml
│   ├── go.mod
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/     # UI components
│   │   ├── pages/          # Route pages
│   │   ├── stores/         # Zustand state
│   │   ├── services/       # API + WebSocket clients
│   │   └── types/          # TypeScript types
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── docker-compose.yml
├── Dockerfile.sandbox      # Kali-based CTF tool sandbox
└── README.md
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET/POST | `/api/challenges` | List/create challenges |
| GET/PUT/DELETE | `/api/challenges/:id` | CRUD operations |
| POST | `/api/challenges/:id/upload` | Upload attachments |
| POST | `/api/sessions` | Create session |
| GET | `/api/sessions/:id/messages` | Get session messages |
| POST | `/api/sessions/:id/branch` | Branch session |
| POST | `/api/agent/solve` | Start solving |
| POST | `/api/agent/stop` | Stop agent |
| GET | `/api/agent/status` | Agent status |
| GET | `/api/knowledge` | List writeups |
| GET | `/api/knowledge/search` | Search writeups |
| GET | `/api/skills` | List skills |
| GET | `/api/providers` | List LLM providers |
| WS | `/ws` | Agent event stream |
| WS | `/ws/terminal/:id` | Terminal PTY bridge |

## License

MIT
