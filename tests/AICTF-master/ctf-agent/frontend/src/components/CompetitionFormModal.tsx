import { useState, useEffect } from 'react'
import { Key, Cookie, User, Eye, EyeOff, Trash2 } from 'lucide-react'
import { useCompetitionStore } from '../stores/competitionStore'
import { competitionApi } from '../services/api'
import type { Competition, CompetitionStatus } from '../types'

type AuthType = 'cookie' | 'token' | 'account' | 'custom'

interface AuthOption { value: AuthType; label: string; icon: typeof Cookie; desc: string }

const defaultAuthOptions: AuthOption[] = [
  { value: 'cookie', label: 'Cookie', icon: Cookie, desc: '使用浏览器 Cookie 认证' },
  { value: 'token', label: 'Token', icon: Key, desc: 'API Token / Bearer Token' },
  { value: 'account', label: '账号密码', icon: User, desc: '用户名 + 密码登录' },
  { value: 'custom', label: '自定义', icon: Key, desc: '自定义 Header 键值对' },
]

const gzctfAuthOptions: AuthOption[] = [
  { value: 'cookie', label: 'Cookie', icon: Cookie, desc: 'GZCTF 登录后的浏览器 Cookie' },
  { value: 'token', label: 'Team Token', icon: Key, desc: 'GZCTF 队伍 Token (Bearer)' },
  { value: 'account', label: '账号密码', icon: User, desc: 'GZCTF 平台账号密码' },
  { value: 'custom', label: '自定义', icon: Key, desc: '自定义 Header 键值对' },
]

interface Props {
  competition?: Competition // if provided, edit mode
  onClose: () => void
  onSaved?: (comp: Competition) => void
}

/** Detect auth type from a credentials JSON object */
function detectAuthType(creds: Record<string, string>): AuthType {
  if (creds.cookie) return 'cookie'
  if (creds.token || creds.bearer) return 'token'
  if (creds.username || creds.password) return 'account'
  if (Object.keys(creds).length > 0) return 'custom'
  return 'cookie'
}

export default function CompetitionFormModal({ competition, onClose, onSaved }: Props) {
  const { createCompetition, updateCompetition } = useCompetitionStore()
  const isEdit = !!competition

  const [form, setForm] = useState({
    name: '',
    platform: '',
    url: '',
    description: '',
    status: 'active' as CompetitionStatus,
  })
  const [authType, setAuthType] = useState<AuthType>('cookie')
  const [cookieValue, setCookieValue] = useState('')
  const [tokenValue, setTokenValue] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [customCreds, setCustomCreds] = useState<{ key: string; value: string }[]>([])
  const [showSecret, setShowSecret] = useState(false)
  const [saving, setSaving] = useState(false)
  const [loadingRaw, setLoadingRaw] = useState(false)

  // Pre-populate form when editing
  useEffect(() => {
    if (!competition) return
    setForm({
      name: competition.name,
      platform: competition.platform,
      url: competition.url,
      description: competition.description,
      status: competition.status,
    })
    // Load raw credentials for editing
    setLoadingRaw(true)
    competitionApi.getRaw(competition.id).then((raw) => {
      try {
        const creds: Record<string, string> = JSON.parse(raw.credentials || '{}')
        const type = detectAuthType(creds)
        setAuthType(type)
        switch (type) {
          case 'cookie':
            setCookieValue(creds.cookie || '')
            break
          case 'token':
            setTokenValue(creds.token || creds.bearer || '')
            break
          case 'account':
            setUsername(creds.username || '')
            setPassword(creds.password || '')
            break
          case 'custom':
            setCustomCreds(Object.entries(creds).map(([key, value]) => ({ key, value })))
            break
        }
      } catch {
        // ignore parse errors
      }
      setLoadingRaw(false)
    }).catch(() => setLoadingRaw(false))
  }, [competition])

  const isGZCTF = form.platform.toLowerCase().includes('gzctf')
  const authTypeOptions = isGZCTF ? gzctfAuthOptions : defaultAuthOptions

  const buildCredentials = (): Record<string, string> => {
    switch (authType) {
      case 'cookie':
        return cookieValue.trim() ? { cookie: cookieValue.trim() } : {}
      case 'token':
        // GZCTF uses Bearer token, CTFd uses Token
        if (!tokenValue.trim()) return {}
        return isGZCTF ? { bearer: tokenValue.trim() } : { token: tokenValue.trim() }
      case 'account':
        return {
          ...(username.trim() ? { username: username.trim() } : {}),
          ...(password ? { password } : {}),
        }
      case 'custom': {
        const creds: Record<string, string> = {}
        customCreds.forEach((c) => {
          if (c.key.trim() && c.value) creds[c.key.trim()] = c.value
        })
        return creds
      }
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim()) return
    setSaving(true)
    try {
      const data = {
        name: form.name,
        platform: form.platform,
        url: form.url,
        description: form.description,
        status: form.status,
        credentials: JSON.stringify(buildCredentials()),
      }
      if (isEdit) {
        await updateCompetition(competition.id, data)
        onSaved?.({ ...competition, ...data })
      } else {
        const created = await createCompetition(data)
        onSaved?.(created)
      }
      onClose()
    } catch (err) {
      console.error(`Failed to ${isEdit ? 'update' : 'create'} competition:`, err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="panel w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="panel-header justify-between">
          <span>{isEdit ? '编辑比赛' : '添加比赛'}</span>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        {loadingRaw ? (
          <div className="p-8 text-center text-gray-400">加载中...</div>
        ) : (
          <form onSubmit={handleSubmit} className="p-4 space-y-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">比赛名称 *</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="input-field w-full"
                placeholder="例如：XCTF 2025"
                autoFocus
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">平台类型</label>
                <select
                  value={form.platform}
                  onChange={(e) => setForm({ ...form, platform: e.target.value })}
                  className="input-field w-full"
                >
                  <option value="">选择平台...</option>
                  <option value="CTFd">CTFd</option>
                  <option value="GZCTF">GZCTF</option>
                  <option value="其他">其他</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">平台地址</label>
                <input
                  type="url"
                  value={form.url}
                  onChange={(e) => setForm({ ...form, url: e.target.value })}
                  className="input-field w-full"
                  placeholder="https://ctf.example.com"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">描述</label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className="input-field w-full resize-none"
                rows={2}
                placeholder="比赛描述..."
              />
            </div>

            {isEdit && (
              <div>
                <label className="block text-xs text-gray-500 mb-1">状态</label>
                <select
                  value={form.status}
                  onChange={(e) => setForm({ ...form, status: e.target.value as CompetitionStatus })}
                  className="input-field w-full"
                >
                  <option value="active">进行中</option>
                  <option value="archived">已归档</option>
                </select>
              </div>
            )}

            {/* Auth Type Selector */}
            <div>
              <label className="block text-xs text-gray-500 mb-2">认证方式</label>
              <div className="grid grid-cols-4 gap-2">
                {authTypeOptions.map((opt) => {
                  const Icon = opt.icon
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setAuthType(opt.value)}
                      className={`flex flex-col items-center gap-1 p-2 rounded-lg border text-xs transition-colors ${
                        authType === opt.value
                          ? 'border-primary-500 bg-primary-50 text-primary-700'
                          : 'border-surface-border text-gray-500 hover:border-gray-300'
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                      {opt.label}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Auth Fields */}
            <div className="space-y-3">
              {authType === 'cookie' && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Cookie</label>
                  <div className="relative">
                    <textarea
                      value={cookieValue}
                      onChange={(e) => setCookieValue(e.target.value)}
                      className="input-field w-full resize-none pr-10 font-mono text-xs"
                      rows={3}
                      placeholder={isGZCTF
                        ? '从浏览器复制 Cookie 值，例如：\n.AspNetCore.Identity.Application=CfDJ8...'
                        : '从浏览器复制 Cookie 值，例如：\nsession=abc123; token=xyz456'}
                    />
                    <button
                      type="button"
                      onClick={() => setShowSecret(!showSecret)}
                      className="absolute right-2 top-2 text-gray-400 hover:text-gray-600"
                    >
                      {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  {!showSecret && cookieValue && (
                    <div className="mt-1 text-xs text-gray-400 font-mono truncate">
                      {cookieValue.slice(0, 20)}{'****'}
                    </div>
                  )}
                  <p className="text-xs text-gray-400 mt-1">
                    {isGZCTF
                      ? '打开浏览器 F12 → Application → Cookies → 复制 .AspNetCore.Identity.Application 的值（或整行 Cookie）'
                      : '打开浏览器 F12 → Network → 复制请求头中的 Cookie 值'}
                  </p>
                </div>
              )}

              {authType === 'token' && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    {isGZCTF ? 'Team Token (Bearer)' : 'Token'}
                  </label>
                  <div className="relative">
                    <input
                      type={showSecret ? 'text' : 'password'}
                      value={tokenValue}
                      onChange={(e) => setTokenValue(e.target.value)}
                      className="input-field w-full pr-10 font-mono"
                      placeholder={isGZCTF ? 'GZCTF 队伍 Token' : 'API Token 或 Bearer Token'}
                    />
                    <button
                      type="button"
                      onClick={() => setShowSecret(!showSecret)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <p className="text-xs text-gray-400 mt-1">
                    {isGZCTF
                      ? '在 GZCTF 比赛页面 → 你的队伍 → 复制 Team Token（将作为 Bearer Token 使用）'
                      : '通常在平台设置页面可以获取 API Token'}
                  </p>
                </div>
              )}

              {authType === 'account' && (
                <>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">用户名</label>
                    <input
                      type="text"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="input-field w-full"
                      placeholder="平台登录用户名"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">密码</label>
                    <div className="relative">
                      <input
                        type={showSecret ? 'text' : 'password'}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        className="input-field w-full pr-10"
                        placeholder="平台登录密码"
                      />
                      <button
                        type="button"
                        onClick={() => setShowSecret(!showSecret)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                      >
                        {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-gray-400">
                    {isGZCTF
                      ? 'AI 会自动通过 /api/account/login 登录 GZCTF 获取 Session'
                      : 'AI 会自动使用账号密码登录平台获取 Session'}
                  </p>
                </>
              )}

              {authType === 'custom' && (
                <div className="space-y-2">
                  {customCreds.map((cred, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <input
                        type="text"
                        value={cred.key}
                        onChange={(e) => {
                          const updated = [...customCreds]
                          updated[idx] = { ...updated[idx], key: e.target.value }
                          setCustomCreds(updated)
                        }}
                        className="input-field w-28 flex-shrink-0 font-mono text-sm"
                        placeholder="Header 名"
                      />
                      <input
                        type={showSecret ? 'text' : 'password'}
                        value={cred.value}
                        onChange={(e) => {
                          const updated = [...customCreds]
                          updated[idx] = { ...updated[idx], value: e.target.value }
                          setCustomCreds(updated)
                        }}
                        className="input-field flex-1 font-mono text-sm"
                        placeholder="值"
                      />
                      <button
                        type="button"
                        onClick={() => setCustomCreds(customCreds.filter((_, i) => i !== idx))}
                        className="text-red-400 hover:text-red-600"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setCustomCreds([...customCreds, { key: '', value: '' }])}
                      className="btn-secondary text-xs"
                    >
                      + 添加字段
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowSecret(!showSecret)}
                      className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
                    >
                      {showSecret ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                      {showSecret ? '隐藏' : '显示'}值
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={onClose} className="btn-secondary">取消</button>
              <button type="submit" disabled={saving || !form.name.trim()} className="btn-primary">
                {saving ? (isEdit ? '保存中...' : '创建中...') : (isEdit ? '保存' : '创建')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
