import { useEffect, useRef } from 'react'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import php from 'highlight.js/lib/languages/php'
import xml from 'highlight.js/lib/languages/xml'
import sql from 'highlight.js/lib/languages/sql'
import yaml from 'highlight.js/lib/languages/yaml'

// Register languages
hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('c', c)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('php', php)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('yaml', yaml)

/** Map tool name → highlight.js language */
const toolLangMap: Record<string, string> = {
  python_exec: 'python',
  pwntools_script: 'python',
  sage_math: 'python',
  exec: 'bash',
  web_fetch: 'json',
}

/** Guess language from file extension */
function langFromPath(path: string): string | undefined {
  const ext = path.split('.').pop()?.toLowerCase()
  const map: Record<string, string> = {
    py: 'python',
    js: 'javascript',
    ts: 'javascript',
    jsx: 'javascript',
    tsx: 'javascript',
    c: 'c',
    h: 'c',
    cpp: 'cpp',
    cc: 'cpp',
    cxx: 'cpp',
    php: 'php',
    html: 'html',
    htm: 'html',
    xml: 'xml',
    svg: 'xml',
    json: 'json',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    sql: 'sql',
    yml: 'yaml',
    yaml: 'yaml',
  }
  return ext ? map[ext] : undefined
}

/** Resolve language for a given tool + optional file path */
export function resolveLanguage(toolName: string, filePath?: string): string | undefined {
  if (filePath) {
    const fromPath = langFromPath(filePath)
    if (fromPath) return fromPath
  }
  return toolLangMap[toolName]
}

interface CodeBlockProps {
  code: string
  language?: string
  maxHeight?: string
  fileName?: string
  showLineNumbers?: boolean
}

export default function CodeBlock({
  code,
  language,
  maxHeight = '13rem',
  fileName,
  showLineNumbers = true,
}: CodeBlockProps) {
  const codeRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (codeRef.current) {
      // Reset previous highlighting
      codeRef.current.removeAttribute('data-highlighted')
      if (language && hljs.getLanguage(language)) {
        try {
          const result = hljs.highlight(code, { language })
          codeRef.current.innerHTML = result.value
        } catch {
          codeRef.current.textContent = code
        }
      } else {
        // Auto-detect
        try {
          const result = hljs.highlightAuto(code)
          codeRef.current.innerHTML = result.value
        } catch {
          codeRef.current.textContent = code
        }
      }
    }
  }, [code, language])

  const lines = code.split('\n')

  return (
    <div className="code-block rounded-lg overflow-hidden border border-surface-200/60 text-xs">
      {/* Header bar */}
      {(fileName || language) && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-[#1e1e2e] border-b border-[#313244]">
          {/* Dot decorations */}
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-[#f38ba8]/60" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#f9e2af]/60" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#a6e3a1]/60" />
          </div>
          <span className="text-[11px] text-[#a6adc8] font-mono truncate">
            {fileName || language}
          </span>
        </div>
      )}

      {/* Code area */}
      <div
        className="overflow-auto bg-[#1e1e2e]"
        style={{ maxHeight }}
      >
        <div className="flex">
          {/* Line numbers */}
          {showLineNumbers && lines.length > 1 && (
            <div className="flex-shrink-0 select-none text-right pr-3 pl-3 py-2.5 text-[#585b70] font-mono leading-relaxed border-r border-[#313244]">
              {lines.map((_, i) => (
                <div key={i}>{i + 1}</div>
              ))}
            </div>
          )}

          {/* Highlighted code */}
          <pre className="flex-1 p-2.5 m-0 overflow-x-auto">
            <code
              ref={codeRef}
              className={`hljs${language ? ` language-${language}` : ''} !bg-transparent !p-0 font-mono leading-relaxed text-[#cdd6f4]`}
            >
              {code}
            </code>
          </pre>
        </div>
      </div>
    </div>
  )
}
