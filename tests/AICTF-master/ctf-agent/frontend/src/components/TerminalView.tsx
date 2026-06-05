import { useEffect, useRef, useState } from 'react'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { sessionApi } from '../services/api'

interface TerminalViewProps {
  sessionId: string
  terminalId?: string | null
}

export default function TerminalView({ sessionId, terminalId: propTerminalId }: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<XTerm | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const [resolvedTerminalId, setResolvedTerminalId] = useState<string | null>(propTerminalId ?? null)
  const [error, setError] = useState<string | null>(null)

  // Resolve terminal ID: use prop or create on demand
  useEffect(() => {
    if (propTerminalId) {
      setResolvedTerminalId(propTerminalId)
      return
    }
    // Create terminal on demand
    sessionApi.createTerminal(sessionId)
      .then(r => setResolvedTerminalId(r.terminal_id))
      .catch(e => setError(`终端创建失败: ${(e as Error).message}`))
  }, [sessionId, propTerminalId])

  // Connect xterm once we have a terminal ID
  useEffect(() => {
    if (!containerRef.current || !resolvedTerminalId) return

    const term = new XTerm({
      theme: {
        background: '#010409',
        foreground: '#c9d1d9',
        cursor: '#00ff41',
        cursorAccent: '#010409',
        selectionBackground: '#264f78',
        black: '#0d1117',
        red: '#ff7b72',
        green: '#00ff41',
        yellow: '#d29922',
        blue: '#58a6ff',
        magenta: '#bc8cff',
        cyan: '#39d353',
        white: '#c9d1d9',
        brightBlack: '#484f58',
        brightRed: '#ffa198',
        brightGreen: '#56d364',
        brightYellow: '#e3b341',
        brightBlue: '#79c0ff',
        brightMagenta: '#d2a8ff',
        brightCyan: '#56d364',
        brightWhite: '#f0f6fc',
      },
      fontSize: 13,
      fontFamily: 'JetBrains Mono, Fira Code, Consolas, monospace',
      cursorBlink: true,
      cursorStyle: 'block',
      allowProposedApi: true,
    })

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(containerRef.current)
    fitAddon.fit()

    termRef.current = term
    fitAddonRef.current = fitAddon

    // WebSocket connection to terminal
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/terminal/${resolvedTerminalId}`)
    wsRef.current = ws

    ws.onopen = () => {
      term.writeln('\x1b[32m● Terminal connected\x1b[0m')
      ws.send(JSON.stringify({
        type: 'resize',
        cols: term.cols,
        rows: term.rows,
      }))
    }

    ws.onmessage = (event) => {
      term.write(event.data)
    }

    ws.onclose = () => {
      term.writeln('\x1b[31m● Terminal disconnected\x1b[0m')
    }

    // Send input to terminal
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      fitAddon.fit()
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'resize',
          cols: term.cols,
          rows: term.rows,
        }))
      }
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      ws.close()
      term.dispose()
    }
  }, [resolvedTerminalId])

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-500 text-sm">
        {error}
      </div>
    )
  }

  if (!resolvedTerminalId) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        正在创建终端...
      </div>
    )
  }

  return (
    <div className="h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
    </div>
  )
}
