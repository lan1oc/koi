import { useEffect, useRef, useCallback } from 'react'
import { Flag, X, Trophy, AlertCircle, Info, CheckCircle } from 'lucide-react'
import { useNotificationStore, type Notification } from '../stores/notificationStore'

const AUTO_DISMISS_MS = 8000
const FLAG_DISMISS_MS = 5000

// ─── Flag toast ─────────────────────────────────────────────────────────────
function FlagToast({ notification, onClose }: { notification: Notification; onClose: () => void }) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    timerRef.current = setTimeout(onClose, FLAG_DISMISS_MS)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [onClose])

  return (
    <div
      data-flag-toast=""
      className="relative flex items-center gap-3 pl-4 pr-5 py-3.5 rounded-2xl shadow-2xl border border-yellow-200/70 overflow-hidden"
      style={{
        background: 'linear-gradient(135deg, #fffbeb 0%, #fef3c7 50%, #fef9ee 100%)',
        minWidth: 320,
        maxWidth: 440,
        animation: 'toastIn 0.35s cubic-bezier(0.34,1.56,0.64,1) both',
      }}
    >
      {/* Shimmer bar */}
      <div
        className="absolute bottom-0 left-0 h-[3px] rounded-full bg-gradient-to-r from-amber-400 via-yellow-300 to-amber-400"
        style={{ animation: `shrinkBar ${FLAG_DISMISS_MS}ms linear forwards` }}
      />

      {/* Trophy */}
      <div className="flex-shrink-0 flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-yellow-300 to-amber-400 shadow-md shadow-yellow-200">
        <Trophy className="w-5 h-5 text-white drop-shadow-sm" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="font-bold text-sm text-amber-900">🎉 Flag 已获取！</div>
        {notification.challengeTitle && (
          <div className="text-[11px] text-amber-700/80 mt-0.5 truncate">{notification.challengeTitle}</div>
        )}
        {notification.flag && (
          <div className="flex items-center gap-1.5 mt-1">
            <Flag className="w-3 h-3 text-green-600 flex-shrink-0" />
            <code className="text-[11px] bg-white/70 text-green-800 px-1.5 py-0.5 rounded font-mono truncate">
              {notification.flag}
            </code>
          </div>
        )}
      </div>

      {/* Close */}
      <button
        onClick={onClose}
        className="flex-shrink-0 -mr-1 text-amber-400 hover:text-amber-700 transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>

      <style>{`
        @keyframes toastIn {
          from { opacity: 0; transform: translateX(40px) scale(0.92); }
          to   { opacity: 1; transform: translateX(0)   scale(1); }
        }
        @keyframes shrinkBar {
          from { width: 100%; }
          to   { width: 0%; }
        }
      `}</style>
    </div>
  )
}

// ─── Regular toast card ─────────────────────────────────────────────────────
function NotificationCard({ notification }: { notification: Notification }) {
  const remove = useNotificationStore((s) => s.removeNotification)

  useEffect(() => {
    const timer = setTimeout(() => remove(notification.id), AUTO_DISMISS_MS)
    return () => clearTimeout(timer)
  }, [notification.id, remove])

  return (
    <div
      className={`relative flex items-start gap-3 px-4 py-3 rounded-xl shadow-lg border backdrop-blur-sm animate-slide-in ${
        notification.type === 'error'
          ? 'bg-red-50 border-red-300'
          : notification.type === 'success'
          ? 'bg-blue-50 border-blue-300'
          : 'bg-white border-gray-200'
      }`}
      style={{ minWidth: 320, maxWidth: 420 }}
    >
      <div className={`flex-shrink-0 mt-0.5 ${notification.type === 'error' ? 'text-red-500' : 'text-blue-500'}`}>
        {notification.type === 'error' ? <AlertCircle className="w-5 h-5" /> :
         notification.type === 'success' ? <CheckCircle className="w-5 h-5" /> :
         <Info className="w-5 h-5" />}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-sm text-gray-900">{notification.title}</div>
        {notification.message && <div className="text-xs text-gray-600 mt-0.5">{notification.message}</div>}
      </div>
      <button onClick={() => remove(notification.id)} className="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors">
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

// ─── Root ───────────────────────────────────────────────────────────────────
export default function GlobalNotification() {
  const notifications = useNotificationStore((s) => s.notifications)
  const remove = useNotificationStore((s) => s.removeNotification)

  const flagNotifs = notifications.filter((n) => n.type === 'flag')
  const toasts = notifications.filter((n) => n.type !== 'flag')

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-3 items-end">
      {flagNotifs.map((n) => (
        <FlagToastWrapper key={n.id} notification={n} remove={remove} />
      ))}
      {toasts.map((n) => <NotificationCard key={n.id} notification={n} />)}
    </div>
  )
}

function FlagToastWrapper({ notification, remove }: { notification: Notification; remove: (id: string) => void }) {
  const onClose = useCallback(() => remove(notification.id), [notification.id, remove])
  return <FlagToast notification={notification} onClose={onClose} />
}