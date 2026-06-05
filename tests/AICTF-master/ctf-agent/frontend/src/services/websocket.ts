import type { WSEvent } from '../types'

type EventHandler = (event: WSEvent) => void

export class WebSocketService {
  private ws: WebSocket | null = null
  private url: string
  private handlers: Map<string, Set<EventHandler>> = new Map()
  private globalHandlers: Set<EventHandler> = new Set()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 20
  private sessionId: string | null = null
  private _connected = false
  private pingTimer: ReturnType<typeof setInterval> | null = null
  private lastMessageTime = 0
  private healthCheckTimer: ReturnType<typeof setInterval> | null = null
  private intentionalClose = false
  private reconnectRequested = false
  private visibilityHandler: (() => void) | null = null

  constructor(url?: string) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.url = url || `${protocol}//${window.location.host}/ws`
  }

  get connected(): boolean {
    return this._connected
  }

  connect(sessionId?: string): void {
    if (sessionId) {
      this.sessionId = sessionId
    }

    if (this.ws?.readyState === WebSocket.OPEN) {
      return
    }

    // Prevent connecting while a connection is already opening
    if (this.ws?.readyState === WebSocket.CONNECTING) {
      return
    }

    this.intentionalClose = false

    try {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        this._connected = true
        this.reconnectAttempts = 0
        this.lastMessageTime = Date.now()
        console.log('[WS] Connected')
        // Always subscribe to all sessions; filtering is done client-side
        // This avoids conflicts between agentStore and activityStore
        this.subscribe('*')
        this.startHealthCheck()
        this.setupVisibilityHandler()
      }

      this.ws.onmessage = (event) => {
        this.lastMessageTime = Date.now()
        try {
          const data: WSEvent = JSON.parse(event.data)
          this.dispatch(data)
        } catch (e) {
          console.error('[WS] Parse error:', e)
        }
      }

      this.ws.onclose = (event) => {
        this._connected = false
        this.clearPing()
        this.stopHealthCheck()
        console.log('[WS] Disconnected:', event.code, event.reason)
        // If forceReconnect requested, reconnect once after close completes.
        if (this.reconnectRequested) {
          this.reconnectRequested = false
          this.intentionalClose = false
          this.connect(this.sessionId || undefined)
          return
        }

        // User-initiated close (disconnect/force close) should not trigger auto-reconnect.
        if (this.intentionalClose) {
          this.intentionalClose = false
          return
        }

        this.attemptReconnect()
      }

      this.ws.onerror = (error) => {
        console.error('[WS] Error:', error)
      }
    } catch (e) {
      console.error('[WS] Connection failed:', e)
      this.attemptReconnect()
    }
  }

  disconnect(): void {
    this.intentionalClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.clearPing()
    this.stopHealthCheck()
    this.removeVisibilityHandler()
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect')
      this.ws = null
    }
    this._connected = false
    this.sessionId = null
  }

  subscribe(sessionId: string): void {
    this.sessionId = sessionId
    this.send({ type: 'subscribe', session_id: sessionId })
  }

  sendUserInput(sessionId: string, content: string): void {
    this.send({
      type: 'user_input',
      session_id: sessionId,
      content,
    })
  }

  on(eventType: string, handler: EventHandler): () => void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set())
    }
    this.handlers.get(eventType)!.add(handler)
    return () => this.handlers.get(eventType)?.delete(handler)
  }

  onAll(handler: EventHandler): () => void {
    this.globalHandlers.add(handler)
    return () => this.globalHandlers.delete(handler)
  }

  private send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  private dispatch(event: WSEvent): void {
    // Global handlers
    for (const handler of this.globalHandlers) {
      try { handler(event) } catch (e) { console.error('[WS] Handler error:', e) }
    }
    // Type-specific handlers
    const typeHandlers = this.handlers.get(event.type)
    if (typeHandlers) {
      for (const handler of typeHandlers) {
        try { handler(event) } catch (e) { console.error('[WS] Handler error:', e) }
      }
    }
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[WS] Max reconnect attempts reached')
      return
    }
    // Exponential backoff with jitter to prevent thundering herd
    const baseDelay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000)
    const jitter = Math.random() * baseDelay * 0.5
    const delay = baseDelay + jitter
    this.reconnectAttempts++
    console.log(`[WS] Reconnecting in ${Math.round(delay)}ms (attempt ${this.reconnectAttempts})`)
    this.reconnectTimer = setTimeout(() => {
      this.connect(this.sessionId || undefined)
    }, delay)
  }

  private clearPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }

  /** Periodic health check: if no message received within 45s, reconnect.
   *  The server sends WebSocket pings every 30s, so if the connection is alive
   *  we should see activity at least that often. */
  private startHealthCheck(): void {
    this.stopHealthCheck()
    this.healthCheckTimer = setInterval(() => {
      const elapsed = Date.now() - this.lastMessageTime
      if (elapsed > 45000 && this._connected) {
        console.warn(`[WS] No message for ${Math.round(elapsed / 1000)}s, reconnecting...`)
        this.forceReconnect()
      }
    }, 15000)
  }

  private stopHealthCheck(): void {
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer)
      this.healthCheckTimer = null
    }
  }

  /** Force close and reconnect */
  private forceReconnect(): void {
    this.stopHealthCheck()
    this.clearPing()
    if (this.ws) {
      this.reconnectRequested = true
      this.intentionalClose = true // prevent attemptReconnect from onclose
      try { this.ws.close() } catch { /* ignore */ }
      // Wait for onclose to actually reconnect; avoid races.
      return
    }
    this._connected = false
    this.reconnectAttempts = 0 // reset for fresh reconnect
    this.connect(this.sessionId || undefined)
  }

  /** Reconnect when page becomes visible again */
  private setupVisibilityHandler(): void {
    this.removeVisibilityHandler()
    this.visibilityHandler = () => {
      if (document.visibilityState === 'visible') {
        // Check if connection is still alive
        if (!this._connected || this.ws?.readyState !== WebSocket.OPEN) {
          console.log('[WS] Page visible, reconnecting...')
          this.forceReconnect()
        } else {
          // Connection seems open, but verify with health check
          const elapsed = Date.now() - this.lastMessageTime
          if (elapsed > 45000) {
            console.log('[WS] Page visible but stale connection, reconnecting...')
            this.forceReconnect()
          }
        }
      }
    }
    document.addEventListener('visibilitychange', this.visibilityHandler)
  }

  private removeVisibilityHandler(): void {
    if (this.visibilityHandler) {
      document.removeEventListener('visibilitychange', this.visibilityHandler)
      this.visibilityHandler = null
    }
  }
}

// Singleton instance
export const wsService = new WebSocketService()
