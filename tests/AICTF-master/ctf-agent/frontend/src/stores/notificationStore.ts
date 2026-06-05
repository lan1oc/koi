import { create } from 'zustand'

export interface Notification {
  id: string
  type: 'flag' | 'success' | 'error' | 'info'
  title: string
  message: string
  flag?: string
  challengeTitle?: string
  timestamp: number
}

interface NotificationState {
  notifications: Notification[]
  addNotification: (n: Omit<Notification, 'id' | 'timestamp'>) => void
  removeNotification: (id: string) => void
  clearAll: () => void
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  addNotification: (n) =>
    set((s) => ({
      notifications: [
        ...s.notifications,
        { ...n, id: `notif-${Date.now()}-${Math.random()}`, timestamp: Date.now() },
      ],
    })),
  removeNotification: (id) =>
    set((s) => ({
      notifications: s.notifications.filter((n) => n.id !== id),
    })),
  clearAll: () => set({ notifications: [] }),
}))
