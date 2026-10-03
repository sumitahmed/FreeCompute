import type { CoreEvent, EventPage, Json } from './types'

export class APIError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message) }
}

export class APIClient {
  csrf: string | null = null
  readonly base: string
  constructor(base = '') {
    const url = new URL(base || window.location.origin)
    if (!['127.0.0.1', 'localhost'].includes(url.hostname) || url.protocol !== 'http:' || url.username || url.password || url.search || url.hash || (url.pathname !== '/' && url.pathname !== '')) {
      throw new Error('Choose a loopback HTTP Core URL, for example http://127.0.0.1:8741')
    }
    this.base = url.origin
  }
  async request<T>(path: string, body?: Record<string, Json>, signal?: AbortSignal): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body) {
      headers['Content-Type'] = 'application/json'
      if (this.csrf) headers['X-FreeCompute-CSRF'] = this.csrf
    }
    const response = await fetch(this.base + '/api/v1/' + path, {
      method: body ? 'POST' : 'GET', headers, credentials: 'include', signal,
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new APIError(response.status, data.error?.code || 'http_error', data.error?.message || `Local API returned HTTP ${response.status}`)
    }
    return response.json() as Promise<T>
  }
  async authenticate(token?: string) {
    const session = await this.request<{ csrf: string }>('auth/session', token ? { token } : undefined)
    this.csrf = session.csrf
  }
  async history(sessionId: string, signal: AbortSignal) {
    let cursor = 0
    const events: CoreEvent[] = []
    for (;;) {
      const page = await this.request<EventPage>(`sessions/${sessionId}/events?after=${cursor}`, undefined, signal)
      events.push(...page.events)
      cursor = page.cursor
      if (!page.has_more) return { events, cursor }
    }
  }
  async stream(sessionId: string, cursor: number, signal: AbortSignal, onEvent: (event: CoreEvent) => void, onHeartbeat: () => void) {
    const response = await fetch(this.base + `/api/v1/sessions/${sessionId}/events?after=${cursor}`, {
      headers: { Accept: 'text/event-stream' }, credentials: 'include', signal,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new APIError(response.status, data.error?.code || 'stream_error', data.error?.message || 'Event connection was rejected')
    }
    if (!response.body) throw new Error('Browser did not provide an event stream')
    const reader = response.body.getReader()
    const parser = new SSEParser((kind, data) => {
      if (kind === 'core') onEvent(JSON.parse(data) as CoreEvent)
      if (kind === 'heartbeat') onHeartbeat()
    })
    const decoder = new TextDecoder()
    try {
      for (;;) {
        const result = await reader.read()
        if (result.done) throw new Error('Event connection closed; reconnecting from the saved sequence')
        parser.feed(decoder.decode(result.value, { stream: true }))
      }
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
  }
}

export class SSEParser {
  private pending = ''
  constructor(private receive: (event: string, data: string) => void) {}
  feed(chunk: string) {
    this.pending += chunk
    let match: RegExpExecArray | null
    while ((match = /\r?\n\r?\n/.exec(this.pending))) {
      const frame = this.pending.slice(0, match.index)
      this.pending = this.pending.slice(match.index + match[0].length)
      let event = 'message'
      const data: string[] = []
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trimStart()
        if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
      }
      if (data.length) this.receive(event, data.join('\n'))
    }
    if (this.pending.length > 8 * 1024 * 1024) throw new Error('Event frame exceeded the client allowance; reload the session')
  }
}

export function mergeEvents(current: CoreEvent[], incoming: CoreEvent[]) {
  const rows = new Map(current.map(event => [event.sequence, event]))
  for (const event of incoming) rows.set(event.sequence, event)
  return [...rows.values()].sort((a, b) => a.sequence - b.sequence)
}
