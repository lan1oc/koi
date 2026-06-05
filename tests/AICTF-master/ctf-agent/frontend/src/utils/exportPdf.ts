/**
 * simpleMarkdownToHTML — lightweight Markdown→HTML converter for structured reports.
 * Handles headings, tables, bold, code blocks, blockquotes, hr, lists, and paragraphs.
 */
function simpleMarkdownToHTML(md: string): string {
  const lines = md.split('\n')
  const out: string[] = []
  let inCode = false
  let codeLang = ''
  let codeLines: string[] = []
  let inTable = false
  let tableRows: string[][] = []
  let isHeaderRow = true

  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inlineFmt = (s: string) =>
    s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
     .replace(/`([^`]+)`/g, '<code>$1</code>')

  const flushTable = () => {
    if (tableRows.length === 0) return
    let html = '<table><thead><tr>'
    const header = tableRows[0]
    header.forEach(c => { html += `<th>${inlineFmt(c.trim())}</th>` })
    html += '</tr></thead><tbody>'
    for (let i = 1; i < tableRows.length; i++) {
      html += '<tr>'
      tableRows[i].forEach(c => { html += `<td>${inlineFmt(c.trim())}</td>` })
      html += '</tr>'
    }
    html += '</tbody></table>'
    out.push(html)
    tableRows = []
    isHeaderRow = true
    inTable = false
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    // Code block fence
    if (line.trimStart().startsWith('```')) {
      if (!inCode) {
        if (inTable) flushTable()
        inCode = true
        codeLang = line.trimStart().slice(3).trim()
        codeLines = []
      } else {
        out.push(`<pre><code class="language-${esc(codeLang)}">${esc(codeLines.join('\n'))}</code></pre>`)
        inCode = false
      }
      continue
    }
    if (inCode) { codeLines.push(line); continue }

    // Table row
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const cells = line.trim().slice(1, -1).split('|')
      // Skip separator row (| --- | --- |)
      if (cells.every(c => /^\s*-+\s*$/.test(c))) {
        inTable = true
        isHeaderRow = false
        continue
      }
      if (!inTable && isHeaderRow) inTable = true
      tableRows.push(cells)
      continue
    }
    if (inTable) flushTable()

    // Horizontal rule
    if (/^---+$/.test(line.trim())) { out.push('<hr>'); continue }

    // Headings
    const hm = line.match(/^(#{1,6})\s+(.*)/)
    if (hm) { const lvl = hm[1].length; out.push(`<h${lvl}>${inlineFmt(esc(hm[2]))}</h${lvl}>`); continue }

    // Blockquote
    if (line.startsWith('>')) { out.push(`<blockquote>${inlineFmt(esc(line.slice(1).trim()))}</blockquote>`); continue }

    // Empty line
    if (line.trim() === '') { continue }

    // Default: paragraph
    out.push(`<p>${inlineFmt(esc(line))}</p>`)
  }
  if (inCode) out.push(`<pre><code>${esc(codeLines.join('\n'))}</code></pre>`)
  if (inTable) flushTable()

  return out.join('\n')
}

/** Shared CSS styles for PDF export windows */
const PDF_STYLES = `
    *, *::before, *::after { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; font-size: 14px; line-height: 1.7; color: #1f2937; padding: 40px 56px; max-width: 960px; margin: 0 auto; }
    .pdf-header { display: flex; align-items: center; gap: 12px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; margin-bottom: 28px; }
    .pdf-header-badge { background: #4f46e5; color: #fff; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 99px; letter-spacing: 0.05em; }
    .pdf-header-title { font-size: 1.25rem; font-weight: 700; color: #111827; flex: 1; }
    .pdf-header-date { font-size: 11px; color: #9ca3af; }
    h1 { font-size: 1.65rem; font-weight: 700; margin: 1.2rem 0 0.6rem; color: #111827; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
    h2 { font-size: 1.3rem; font-weight: 700; margin: 1.1rem 0 0.5rem; color: #1f2937; }
    h3 { font-size: 1.1rem; font-weight: 600; margin: 0.9rem 0 0.4rem; color: #374151; }
    h4 { font-size: 1rem; font-weight: 600; margin: 0.8rem 0 0.3rem; color: #4b5563; }
    p { margin: 0 0 0.75rem; }
    ul, ol { padding-left: 1.6rem; margin: 0 0 0.75rem; }
    li { margin-bottom: 0.25rem; }
    code { background: #f3f4f6; padding: 0.12em 0.4em; border-radius: 4px; font-family: 'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace; font-size: 0.83em; color: #4338ca; }
    pre { background: #1e1e2e; border-radius: 8px; padding: 1rem 1.2rem; margin: 0.75rem 0 1rem; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word; border: 1px solid #2d2d3f; }
    pre code { background: transparent; color: #cdd6f4; padding: 0; font-size: 0.8em; white-space: pre-wrap; word-wrap: break-word; }
    blockquote { border-left: 4px solid #6366f1; margin: 0.75rem 0; padding: 0.5rem 1rem; background: #f5f3ff; color: #4b5563; border-radius: 0 6px 6px 0; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; font-size: 0.9em; }
    th { background: #f9fafb; border: 1px solid #e5e7eb; padding: 0.5rem 0.8rem; text-align: left; font-weight: 600; color: #374151; }
    td { border: 1px solid #e5e7eb; padding: 0.5rem 0.8rem; }
    tr:nth-child(even) td { background: #f9fafb; }
    a { color: #4f46e5; text-decoration: underline; }
    img { max-width: 100%; border-radius: 6px; }
    hr { border: none; border-top: 1px solid #e5e7eb; margin: 1.5rem 0; }
    .hljs-keyword,.hljs-selector-tag,.hljs-tag { color: #ff79c6; }
    .hljs-string,.hljs-attr { color: #f1fa8c; }
    .hljs-comment,.hljs-quote { color: #6272a4; font-style: italic; }
    .hljs-number,.hljs-literal { color: #bd93f9; }
    .hljs-title,.hljs-name,.hljs-function { color: #50fa7b; }
    .hljs-built_in,.hljs-type { color: #8be9fd; }
    .hljs-variable,.hljs-params { color: #f8f8f2; }
    .hljs-operator,.hljs-punctuation { color: #ff79c6; }
    @media print {
      body { padding: 0; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      pre { white-space: pre-wrap; word-wrap: break-word; break-inside: avoid; }
      h1,h2,h3 { break-after: avoid; }
    }
`

/**
 * exportReportPDF — converts Markdown report text to styled HTML and triggers
 * the browser's native Print → Save as PDF dialog.
 * @param markdown  The raw markdown content of the report
 * @param title     User-customizable PDF title
 * @param badge     Badge label shown in PDF header (e.g. "渗透测试报告", "代码审计报告")
 */
export function exportReportPDF(markdown: string, title: string, badge: string): void {
  const html = simpleMarkdownToHTML(markdown)
  const safeTitle = title.replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const safeBadge = badge.replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const win = window.open('', '_blank', 'width=960,height=800')
  if (!win) { alert('请允许弹出窗口以导出 PDF'); return }
  win.document.write(`<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>${safeTitle}</title>
  <style>${PDF_STYLES}</style>
</head>
<body>
  <div class="pdf-header">
    <span class="pdf-header-badge">${safeBadge}</span>
    <span class="pdf-header-title">${safeTitle}</span>
    <span class="pdf-header-date">${new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}</span>
  </div>
  ${html}
  <script>window.onload = () => { window.focus(); window.print(); }<\/script>
</body>
</html>`)
  win.document.close()
}

/**
 * exportWriteupPDF — renders the given DOM element's innerHTML into a
 * styled print window (Dracula-themed code blocks, CTF header) and triggers
 * the browser's native Print → Save as PDF dialog.
 */
export function exportWriteupPDF(contentEl: HTMLElement, title: string): void {
  const html = contentEl.innerHTML
  const safeTitle = title.replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const win = window.open('', '_blank', 'width=960,height=800')
  if (!win) { alert('请允许弹出窗口以导出 PDF'); return }
  win.document.write(`<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>${safeTitle} — Writeup</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; font-size: 14px; line-height: 1.7; color: #1f2937; padding: 40px 56px; max-width: 960px; margin: 0 auto; }
    .pdf-header { display: flex; align-items: center; gap: 12px; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; margin-bottom: 28px; }
    .pdf-header-badge { background: #4f46e5; color: #fff; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 99px; letter-spacing: 0.05em; }
    .pdf-header-title { font-size: 1.25rem; font-weight: 700; color: #111827; flex: 1; }
    .pdf-header-date { font-size: 11px; color: #9ca3af; }
    h1 { font-size: 1.65rem; font-weight: 700; margin: 1.2rem 0 0.6rem; color: #111827; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
    h2 { font-size: 1.3rem; font-weight: 700; margin: 1.1rem 0 0.5rem; color: #1f2937; }
    h3 { font-size: 1.1rem; font-weight: 600; margin: 0.9rem 0 0.4rem; color: #374151; }
    h4 { font-size: 1rem; font-weight: 600; margin: 0.8rem 0 0.3rem; color: #4b5563; }
    p { margin: 0 0 0.75rem; }
    ul, ol { padding-left: 1.6rem; margin: 0 0 0.75rem; }
    li { margin-bottom: 0.25rem; }
    code { background: #f3f4f6; padding: 0.12em 0.4em; border-radius: 4px; font-family: 'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace; font-size: 0.83em; color: #4338ca; }
    pre { background: #1e1e2e; border-radius: 8px; padding: 1rem 1.2rem; margin: 0.75rem 0 1rem; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word; border: 1px solid #2d2d3f; }
    pre code { background: transparent; color: #cdd6f4; padding: 0; font-size: 0.8em; white-space: pre-wrap; word-wrap: break-word; }
    blockquote { border-left: 4px solid #6366f1; margin: 0.75rem 0; padding: 0.5rem 1rem; background: #f5f3ff; color: #4b5563; border-radius: 0 6px 6px 0; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; font-size: 0.9em; }
    th { background: #f9fafb; border: 1px solid #e5e7eb; padding: 0.5rem 0.8rem; text-align: left; font-weight: 600; color: #374151; }
    td { border: 1px solid #e5e7eb; padding: 0.5rem 0.8rem; }
    tr:nth-child(even) td { background: #f9fafb; }
    a { color: #4f46e5; text-decoration: underline; }
    img { max-width: 100%; border-radius: 6px; }
    hr { border: none; border-top: 1px solid #e5e7eb; margin: 1.5rem 0; }
    .hljs-keyword,.hljs-selector-tag,.hljs-tag { color: #ff79c6; }
    .hljs-string,.hljs-attr { color: #f1fa8c; }
    .hljs-comment,.hljs-quote { color: #6272a4; font-style: italic; }
    .hljs-number,.hljs-literal { color: #bd93f9; }
    .hljs-title,.hljs-name,.hljs-function { color: #50fa7b; }
    .hljs-built_in,.hljs-type { color: #8be9fd; }
    .hljs-variable,.hljs-params { color: #f8f8f2; }
    .hljs-operator,.hljs-punctuation { color: #ff79c6; }
    @media print {
      body { padding: 0; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      pre { white-space: pre-wrap; word-wrap: break-word; break-inside: avoid; }
      h1,h2,h3 { break-after: avoid; }
    }
  </style>
</head>
<body>
  <div class="pdf-header">
    <span class="pdf-header-badge">CTF WRITEUP</span>
    <span class="pdf-header-title">${safeTitle}</span>
    <span class="pdf-header-date">${new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}</span>
  </div>
  ${html}
  <script>window.onload = () => { window.focus(); window.print(); }<\/script>
</body>
</html>`)
  win.document.close()
}
