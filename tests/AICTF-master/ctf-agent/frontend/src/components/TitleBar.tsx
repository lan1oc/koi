import { Minus, Square, X } from 'lucide-react'

export default function TitleBar() {
  // Only show title bar in desktop mode
  const isDesktop = typeof (window as any).dragWindow === 'function'
  if (!isDesktop) return null

  return (
    <div
      className="h-8 bg-surface-100 flex items-center justify-between select-none border-b border-gray-200/50 z-50"
      onMouseDown={(e) => {
        const target = e.target as HTMLElement | null
        if (target?.closest('button')) return
        ;(window as any).dragWindow?.()
      }}
    >
      <div className="flex items-center px-3 gap-2">
        <div className="w-4 h-4 text-primary-500">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="w-full h-full">
            <path d="M19 8 L22 5 L22 11 Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" fill="none"/>
            <ellipse cx="11" cy="12" rx="8" ry="5.5" stroke="currentColor" strokeWidth="1.4"/>
            <circle cx="6" cy="11" r="1" fill="currentColor"/>
            <path d="M10 6.5 Q12 4 14 6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
            <path d="M3.5 12.5 Q3 11.5 3.5 10.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
          </svg>
        </div>
        <span className="text-xs font-medium text-gray-600">LovelyIrisAgent</span>
      </div>
      <div className="flex h-full">
        <button
          className="h-full px-3 hover:bg-gray-200/80 text-gray-500 transition-colors"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); (window as any).minimizeWindow?.() }}
        >
          <Minus className="w-4 h-4" />
        </button>
        <button
          className="h-full px-3 hover:bg-gray-200/80 text-gray-500 transition-colors"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); (window as any).maximizeWindow?.() }}
        >
          <Square className="w-3.5 h-3.5" />
        </button>
        <button
          className="h-full px-3 hover:bg-red-500 hover:text-white text-gray-500 transition-colors"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); (window as any).closeWindow?.() }}
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
