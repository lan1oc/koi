import { useState, useMemo, type ReactNode } from 'react'
import {
  ChevronRight,
  Terminal,
  FileText,
  FilePen,
  Search,
  FolderSearch,
  Globe,
  Code2,
  Radar,
  Syringe,
  Waves,
  Bug,
  Zap,
  ShieldCheck,
  Ghost,
  Microscope,
  Type,
  KeyRound,
  Calculator,
  Image,
  FileSearch,
  Flag,
  Bot,
  Send,
  ScrollText,
  Clock,
  Wrench,
  FileArchive,
  Download,
  FileCode,
} from 'lucide-react'
import type { ToolExecution } from '../types'
import CodeBlock, { resolveLanguage } from './CodeBlock'

const toolIconMap: Record<string, ReactNode> = {
  exec:              <Terminal className="w-3 h-3" />,
  read_file:         <FileText className="w-3 h-3" />,
  write_file:        <FilePen className="w-3 h-3" />,
  grep:              <Search className="w-3 h-3" />,
  find:              <FolderSearch className="w-3 h-3" />,
  web_fetch:         <Globe className="w-3 h-3" />,
  python_exec:       <Code2 className="w-3 h-3" />,
  nmap_scan:         <Radar className="w-3 h-3" />,
  sqlmap:            <Syringe className="w-3 h-3" />,
  burp_request:      <Waves className="w-3 h-3" />,
  gdb_debug:         <Bug className="w-3 h-3" />,
  pwntools_script:   <Zap className="w-3 h-3" />,
  checksec:          <ShieldCheck className="w-3 h-3" />,
  ghidra_decompile:  <Ghost className="w-3 h-3" />,
  radare2:           <Microscope className="w-3 h-3" />,
  strings_analyze:   <Type className="w-3 h-3" />,
  crypto_toolkit:    <KeyRound className="w-3 h-3" />,
  sage_math:         <Calculator className="w-3 h-3" />,
  steg_detect:       <Image className="w-3 h-3" />,
  forensics:         <FileSearch className="w-3 h-3" />,
  flag_submit:       <Flag className="w-3 h-3" />,
  spawn_agent:       <Bot className="w-3 h-3" />,
  send_to_agent:     <Send className="w-3 h-3" />,
  get_agent_history: <ScrollText className="w-3 h-3" />,
  extract_archive:   <FileArchive className="w-3 h-3" />,
  download_file:     <Download className="w-3 h-3" />,
}

/** Shared icon lookup for use by other components (e.g. ActivityPanel) */
export function getToolIcon(name: string): ReactNode {
  return toolIconMap[name] || <Wrench className="w-3 h-3" />
}

/** Status dot color classes */
function statusDot(status: ToolExecution['status']): string {
  switch (status) {
    case 'running':   return 'cc-status-dot cc-status-dot--active'
    case 'completed': return 'cc-status-dot cc-status-dot--success'
    case 'failed':    return 'cc-status-dot cc-status-dot--error'
  }
}

/** Left border color for status */
function statusBorder(status: ToolExecution['status']): string {
  switch (status) {
    case 'running':   return 'border-l-amber-400'
    case 'completed': return 'border-l-emerald-400'
    case 'failed':    return 'border-l-red-400'
  }
}

/**
 * Tries to extract a human-readable preview from the partial/complete JSON arg string.
 */
function extractArgPreview(toolName: string, raw: string): string {
  if (!raw) return ''
  const fieldMap: Record<string, string[]> = {
    write_file:      ['content'],
    python_exec:     ['code', 'script'],
    pwntools_script: ['code'],
    exec:            ['command', 'cmd'],
    web_fetch:       ['url', 'body'],
    read_file:       ['path'],
    grep:            ['pattern'],
  }
  const fields = fieldMap[toolName] ?? []
  for (const field of fields) {
    const re = new RegExp(`"${field}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`, 's')
    const m = raw.match(re)
    if (m?.[1]) {
      return m[1]
        .replace(/\\n/g, '\n')
        .replace(/\\t/g, '\t')
        .replace(/\\r/g, '')
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, '\\')
    }
  }
  return raw.length > 400 ? '...' + raw.slice(-400) : raw
}

/**
 * Renders tool arguments with tool-specific layouts.
 */
export function renderArguments(toolName: string, args: Record<string, unknown>): ReactNode {
  switch (toolName) {
    case 'write_file': {
      const path = (args.path as string) || ''
      const content = (args.content as string) || ''
      const lang = resolveLanguage(toolName, path)
      return (
        <>
          {path && (
            <div className="flex items-center gap-1.5 mb-2">
              <FileCode className="w-3 h-3 text-[var(--text-muted)] flex-shrink-0" />
              <code className="text-xs text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded font-mono break-all">{path}</code>
            </div>
          )}
          {content && <CodeBlock code={content} language={lang} fileName={path} />}
        </>
      )
    }
    case 'python_exec':
    case 'pwntools_script':
    case 'sage_math': {
      const code = ((args.code || args.script || '') as string)
      const lang = resolveLanguage(toolName)
      return code ? <CodeBlock code={code} language={lang} /> : null
    }
    case 'exec': {
      const cmd = ((args.command || args.cmd || '') as string)
      return cmd ? <CodeBlock code={cmd} language="bash" showLineNumbers={false} maxHeight="8rem" /> : null
    }
    default:
      return (
        <pre className="text-xs text-[var(--text-muted)] bg-[var(--bg-base)] rounded-md px-2.5 py-2 whitespace-pre-wrap overflow-x-auto max-h-40 overflow-y-auto font-mono leading-relaxed border border-[var(--border-color)]">
          {JSON.stringify(args, null, 2)}
        </pre>
      )
  }
}

export default function ToolCallCard({ execution }: { execution: ToolExecution }) {
  const [expanded, setExpanded] = useState(false)
  const duration = execution.endTime
    ? ((execution.endTime - execution.startTime) / 1000).toFixed(1)
    : null

  const streamingPreview = useMemo(
    () => execution.streamingArgs ? extractArgPreview(execution.name, execution.streamingArgs) : null,
    [execution.name, execution.streamingArgs],
  )

  const icon = getToolIcon(execution.name)
  const isGeneratingArgs = execution.status === 'running' && !!execution.streamingArgs && !execution.output

  return (
    <div className={`cc-tool-card border-l-2 ${statusBorder(execution.status)} ${expanded ? 'cc-tool-card--expanded' : ''}`}>
      {/* Header — single compact line */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="cc-tool-header group"
      >
        {/* Status dot */}
        <span className={statusDot(execution.status)} />

        {/* Tool icon + name */}
        <span className="cc-tool-icon">{icon}</span>
        <span className="cc-tool-name">{execution.name}</span>

        {/* Duration */}
        {duration && (
          <span className="cc-tool-duration">
            <Clock className="w-2.5 h-2.5" />
            {duration}s
          </span>
        )}

        <span className="flex-1" />

        {/* Chevron */}
        <ChevronRight
          className={`w-3 h-3 text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-all flex-shrink-0 ${
            expanded ? 'rotate-90' : ''
          }`}
        />
      </button>

      {/* Collapsed preview */}
      {!expanded && execution.output && (
        <div className="cc-tool-preview">
          <pre className="cc-tool-preview-text">
            {execution.output.split('\n')[0].slice(0, 120)}
          </pre>
        </div>
      )}

      {/* Collapsed: input content preview for content tools */}
      {!expanded && !isGeneratingArgs && (() => {
        const contentTools = ['write_file', 'python_exec', 'pwntools_script']
        if (!contentTools.includes(execution.name)) return null
        const args = execution.arguments
        const raw = (args?.content || args?.code || args?.script || '') as string
        if (!raw) return null
        const firstLine = raw.split('\n').find((l) => l.trim()) ?? ''
        if (!firstLine) return null
        return (
          <div className="cc-tool-preview">
            <pre className="cc-tool-preview-text text-indigo-500/70">
              {firstLine.slice(0, 120)}
            </pre>
          </div>
        )
      })()}

      {/* Collapsed: streaming args preview */}
      {!expanded && isGeneratingArgs && streamingPreview && (
        <div className="cc-tool-preview">
          <pre className="cc-tool-preview-text text-amber-500/60">
            {streamingPreview.split('\n').filter(Boolean).pop()?.slice(0, 120) ?? ''}
          </pre>
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <div className="cc-tool-details">
          {/* Arguments */}
          {execution.arguments && Object.keys(execution.arguments).length > 0 && (
            <div className="mb-2">
              <div className="cc-tool-section-label">参数</div>
              {renderArguments(execution.name, execution.arguments)}
            </div>
          )}

          {/* Output */}
          {execution.output && (
            <div className="mb-2">
              <div className="cc-tool-section-label">输出</div>
              <pre className="text-xs text-[var(--text-muted)] bg-[var(--bg-base)] rounded-md px-2.5 py-2 whitespace-pre-wrap overflow-x-auto max-h-60 overflow-y-auto font-mono leading-relaxed border border-[var(--border-color)]">
                {execution.output.length > 5000
                  ? execution.output.slice(0, 5000) + '\n… (已截断)'
                  : execution.output}
              </pre>
            </div>
          )}

          {/* Streaming args live preview */}
          {isGeneratingArgs && streamingPreview && (
            <div className="mb-2">
              <div className="cc-tool-section-label text-amber-500 flex items-center gap-1">
                <span className="cc-status-dot cc-status-dot--active" style={{ width: 5, height: 5 }} />
                生成中
              </div>
              <pre className="text-xs text-[var(--text-muted)] bg-amber-50/40 rounded-md px-2.5 py-2 whitespace-pre-wrap overflow-x-auto max-h-52 overflow-y-auto font-mono leading-relaxed border border-amber-200/40">
                {streamingPreview.length > 4000
                  ? '...' + streamingPreview.slice(-4000)
                  : streamingPreview}
              </pre>
            </div>
          )}

          {/* Running indicator */}
          {execution.status === 'running' && !execution.output && !isGeneratingArgs && (
            <div className="flex items-center gap-2 text-xs text-amber-600 py-1">
              <span className="cc-status-dot cc-status-dot--active" />
              执行中…
            </div>
          )}
        </div>
      )}
    </div>
  )
}
