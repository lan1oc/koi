import { useEffect, useMemo, useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Trophy,
  Brain,
  BookOpen,
  Settings,
  Plug,
  Activity,
  FileText,
  Flag,
  Search,
  Crosshair,
  FolderSearch,
  Target,
  FileCode,
  Swords,
  Lightbulb,
  History,
  Sun,
  Moon,
  Heart,
  Tag,
  ClipboardList,
  Monitor,
  Cpu,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { useSettingsStore } from '../stores/settingsStore'
import { useActivityStore } from '../stores/activityStore'
import { usePipelineStore } from '../stores/pipelineStore'
import { wsService } from '../services/websocket'
import { bootstrapApi } from '../services/api'
import GlobalNotification from './GlobalNotification'
import GlobalFlagModal from './GlobalFlagModal'
import GlobalAskUserModal from './GlobalAskUserModal'
import PipelineFloater from './PipelineFloater'
import type { AgentMode } from '../types'
import { getModeHomePath } from '../utils/modeRoutes'

type NavItem = { to: string; icon: React.ComponentType<{ className?: string }>; label: string }

const navByMode: Record<AgentMode, NavItem[]> = {
  ctf: [
    { to: '/dashboard',     icon: LayoutDashboard, label: '仪表盘' },
    { to: '/competitions',  icon: Trophy,           label: '比赛管理' },
    { to: '/agent-arena',   icon: Swords,           label: 'Agent 竞技场' },
    { to: '/activity',      icon: Activity,         label: 'AI 动态' },
    { to: '/solve-records', icon: ClipboardList,    label: '解题记录' },
    { to: '/ideas',         icon: Lightbulb,        label: '点子' },
    { to: '/prompts',       icon: FileText,         label: '提示词' },
    { to: '/skills',        icon: Brain,            label: '技能库' },
    { to: '/knowledge',     icon: BookOpen,         label: '知识库' },
    { to: '/memories',      icon: History,          label: '经验库' },
    { to: '/tags',          icon: Tag,              label: '标签管理' },
    { to: '/mcp',           icon: Plug,             label: 'MCP 服务' },
    { to: '/settings',      icon: Settings,         label: '设置' },
  ],
  reverse: [
    { to: '/reverse-lab',   icon: Cpu,              label: '工作台' },
    { to: '/activity',      icon: Activity,         label: 'AI 动态' },
    { to: '/skills',        icon: Brain,            label: '技能库' },
    { to: '/knowledge',     icon: BookOpen,         label: '知识库' },
    { to: '/memories',      icon: History,          label: '经验库' },
    { to: '/mcp',           icon: Plug,             label: 'MCP 服务' },
    { to: '/settings',      icon: Settings,         label: '设置' },
  ],
  audit: [
    { to: '/audit/dashboard', icon: LayoutDashboard, label: '仪表盘' },
    { to: '/audit/projects',  icon: FolderSearch,    label: '审计项目' },
    { to: '/activity',        icon: Activity,         label: 'AI 动态' },
    { to: '/ideas',           icon: Lightbulb,        label: '点子' },
    { to: '/prompts',         icon: FileText,         label: '提示词' },
    { to: '/skills',          icon: FileCode,         label: '技能库' },
    { to: '/knowledge',       icon: BookOpen,         label: '知识库' },
    { to: '/memories',        icon: History,          label: '经验库' },
    { to: '/tags',            icon: Tag,              label: '标签管理' },
    { to: '/mcp',             icon: Plug,             label: 'MCP 服务' },
    { to: '/settings',        icon: Settings,         label: '设置' },
  ],
  pentest: [
    { to: '/pentest/dashboard', icon: LayoutDashboard, label: '仪表盘' },
    { to: '/pentest/targets',   icon: Target,           label: '目标管理' },
    { to: '/activity',          icon: Activity,         label: 'AI 动态' },
    { to: '/ideas',             icon: Lightbulb,        label: '点子' },
    { to: '/prompts',           icon: FileText,         label: '提示词' },
    { to: '/skills',            icon: Swords,           label: '技能库' },
    { to: '/knowledge',         icon: BookOpen,         label: '知识库' },
    { to: '/memories',          icon: History,          label: '经验库' },
    { to: '/tags',              icon: Tag,              label: '标签管理' },
    { to: '/mcp',               icon: Plug,             label: 'MCP 服务' },
    { to: '/settings',          icon: Settings,         label: '设置' },
  ],
  inspection: [
    { to: '/inspection/dashboard', icon: LayoutDashboard, label: '仪表盘' },
    { to: '/inspection/hosts',     icon: Monitor,         label: '主机管理' },
    { to: '/settings',             icon: Settings,         label: '设置' },
  ],
}

const modeConfig: Record<AgentMode, {
  label: string
  icon: React.ComponentType<{ className?: string }>
  color: string       // active text color
  bg: string          // active bg
  border: string      // active border
  dot: string         // active dot
}> = {
  ctf:        { label: 'CTF',   icon: Flag,      color: 'text-blue-600',   bg: 'bg-blue-50',    border: 'border-blue-200',   dot: 'bg-blue-500'    },
  reverse:    { label: '逆向',  icon: Cpu,       color: 'text-purple-600', bg: 'bg-purple-50',  border: 'border-purple-200', dot: 'bg-purple-500'  },
  audit:      { label: '审计',  icon: Search,    color: 'text-amber-600',  bg: 'bg-amber-50',   border: 'border-amber-200',  dot: 'bg-amber-500'   },
  pentest:    { label: '黑盒',  icon: Crosshair, color: 'text-red-600',    bg: 'bg-red-50',     border: 'border-red-200',    dot: 'bg-red-500'     },
  inspection: { label: '巡检',  icon: Monitor,   color: 'text-teal-600',   bg: 'bg-teal-50',    border: 'border-teal-200',   dot: 'bg-teal-500'    },
}

// ─── Bottom bar Layout ─────────────────────────────────────────────────────
export default function Layout() {
  const { agentMode, setAgentMode, theme, setTheme } = useSettingsStore()
  const navigate = useNavigate()
  const activityConnect = useActivityStore((s) => s.connect)
  const activityDisconnect = useActivityStore((s) => s.disconnect)
  const pipelineInitWS = usePipelineStore((s) => s.initWS)

  const navItems = useMemo(() => navByMode[agentMode] || navByMode.ctf, [agentMode])
  const currentMode = modeConfig[agentMode] || modeConfig.ctf

  // For horizontal scrolling on nav items
  const [navScrollLeft, setNavScrollLeft] = useState(0)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)
  const navRef = useMemo(() => ({ current: null as HTMLDivElement | null }), [])

  const updateScrollState = () => {
    const el = navRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 2)
    setCanScrollRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 2)
    setNavScrollLeft(el.scrollLeft)
  }

  useEffect(() => {
    const el = navRef.current
    if (!el) return
    updateScrollState()
    el.addEventListener('scroll', updateScrollState)
    const ro = new ResizeObserver(updateScrollState)
    ro.observe(el)
    return () => { el.removeEventListener('scroll', updateScrollState); ro.disconnect() }
  }, [navItems])

  const scrollNav = (dir: 'left' | 'right') => {
    const el = navRef.current
    if (!el) return
    el.scrollBy({ left: dir === 'left' ? -200 : 200, behavior: 'smooth' })
  }

  // Active nav indicator theme
  const themeBar = {
    light: 'bg-violet-500',
    dark:  'bg-cyan-400',
    pink:  'bg-pink-400',
  }[theme] ?? 'bg-violet-500'

  // Apply theme class to <html>
  useEffect(() => {
    const html = document.documentElement
    html.classList.remove('theme-light', 'theme-dark', 'theme-pink')
    html.classList.add(`theme-${theme}`)
  }, [theme])

  const { fetchConfig } = useSettingsStore()

  useEffect(() => {
    ;(async () => {
      try {
        const bs = await bootstrapApi.get()
        if (bs && bs.completed === false) {
          navigate('/onboarding', { replace: true })
        }
      } catch { /* noop */ }
    })()

    fetchConfig()
    wsService.connect()
    activityConnect()
    const pipelineUnsub = pipelineInitWS()
    return () => {
      pipelineUnsub()
      activityDisconnect()
    }
  }, [activityConnect, activityDisconnect, pipelineInitWS, navigate, fetchConfig])

  return (
    <div className="flex flex-col h-full overflow-hidden bg-surface-50">

      {/* ── Main content ── */}
      <main className="flex-1 overflow-auto bg-surface-50 min-w-0">
        <Outlet />
      </main>

      {/* ── Bottom navigation bar ── */}
      <div className="flex-shrink-0 border-t border-gray-200 bg-white/80 backdrop-blur-xl shadow-[0_-4px_24px_rgba(0,0,0,0.06)]">
        <div className="flex items-stretch h-12">

          {/* Mode tabs (left) */}
          <div className="flex items-center gap-0.5 px-2 border-r border-gray-200">
            {(Object.keys(modeConfig) as AgentMode[]).map((mode) => {
              const cfg = modeConfig[mode]
              const ModeIcon = cfg.icon
              const isActive = agentMode === mode
              return (
                <button
                  key={mode}
                  onClick={() => {
                    if (mode === agentMode) return
                    setAgentMode(mode)
                    navigate(getModeHomePath(mode))
                  }}
                  title={`${cfg.label}模式`}
                  className={`relative group flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
                    isActive
                      ? `${cfg.color} ${cfg.bg} border ${cfg.border}`
                      : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  <ModeIcon className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">{cfg.label}</span>
                  {/* Active dot */}
                  {isActive && (
                    <span className={`absolute -top-0.5 right-0.5 w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                  )}
                </button>
              )
            })}
          </div>

          {/* Navigation items (center, scrollable) */}
          <div className="flex-1 flex items-center min-w-0 relative">
            {/* Left scroll arrow */}
            {canScrollLeft && (
              <button
                onClick={() => scrollNav('left')}
                className="absolute left-0 z-10 flex items-center justify-center w-7 h-full bg-gradient-to-r from-white via-white/90 to-transparent"
              >
                <ChevronLeft className="w-4 h-4 text-gray-400" />
              </button>
            )}

            <div
              ref={(el) => { navRef.current = el }}
              className="flex items-center gap-0.5 px-2 overflow-x-auto scrollbar-none scroll-smooth"
              style={{ scrollbarWidth: 'none' }}
            >
              {navItems.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    `group relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all duration-200 ${
                      isActive
                        ? 'text-gray-900 bg-gray-100'
                        : 'text-gray-400 hover:text-gray-700 hover:bg-gray-50'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon className={`w-3.5 h-3.5 flex-shrink-0 transition-transform duration-200 ${isActive ? '' : 'group-hover:scale-110'}`} />
                      <span>{label}</span>
                      {/* Active indicator — bottom bar */}
                      {isActive && (
                        <span className={`absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-[2px] rounded-full ${themeBar}`} />
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>

            {/* Right scroll arrow */}
            {canScrollRight && (
              <button
                onClick={() => scrollNav('right')}
                className="absolute right-0 z-10 flex items-center justify-center w-7 h-full bg-gradient-to-l from-white via-white/90 to-transparent"
              >
                <ChevronRight className="w-4 h-4 text-gray-400" />
              </button>
            )}
          </div>

          {/* Theme switcher (right) */}
          <div className="flex items-center gap-0.5 px-2 border-l border-gray-200">
            {([
              { key: 'light' as const, icon: Sun,   label: '浅色', active: 'bg-yellow-50 text-yellow-600 border border-yellow-200' },
              { key: 'dark' as const,  icon: Moon,  label: '深色', active: 'bg-slate-800 text-slate-100 border border-slate-600' },
              { key: 'pink' as const,  icon: Heart, label: '粉色', active: 'bg-pink-50 text-pink-500 border border-pink-200' },
            ]).map(({ key, icon: Icon, label, active }) => (
              <button
                key={key}
                onClick={() => setTheme(key)}
                title={`${label}主题`}
                className={`flex items-center justify-center w-7 h-7 rounded-lg transition-all duration-200 ${
                  theme === key
                    ? active
                    : 'text-gray-300 hover:text-gray-500 hover:bg-gray-100'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
              </button>
            ))}
          </div>

        </div>
      </div>

      <GlobalNotification />
      <GlobalFlagModal />
      <GlobalAskUserModal />
      <PipelineFloater />
    </div>
  )
}
