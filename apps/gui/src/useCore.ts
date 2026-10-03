import { useCallback, useEffect, useRef, useState } from 'react'
import { APIClient, APIError, mergeEvents } from './api'
import type { Action, CoreEvent, Profile, Queue, Session, Snapshot, Status, Worker } from './types'

const pause = (signal: AbortSignal, ms: number) => new Promise<void>(resolve => {
  const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve() }
  const timer = setTimeout(finish, ms)
  signal.addEventListener('abort', finish, { once: true })
  if (signal.aborted) finish()
})

export function useCore(client: APIClient, unauthorized: () => void) {
  const [status, setStatus] = useState<Status | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [workers, setWorkers] = useState<Worker[]>([])
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [queue, setQueue] = useState<Queue>({ jobs: [], leases: [], active_task_id: null })
  const [actions, setActions] = useState<Action[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [events, setEvents] = useState<CoreEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const current = useRef<string | null>(null)
  current.current = selected
  const initialized = useRef(false)
  const mounted = useRef(true)
  const handleError = useCallback((error: unknown) => {
    if (!mounted.current || (error instanceof DOMException && error.name === 'AbortError')) return
    if (error instanceof APIError && error.status === 401) unauthorized()
    setError(error instanceof Error ? error.message : 'Local API command was not confirmed')
  }, [unauthorized])
  const refresh = useCallback(async (signal?: AbortSignal) => {
    const sid = current.current
    try {
      const [status, sessions, workers, profiles, queue, actions, snapshot] = await Promise.all([
        client.request<Status>('status', undefined, signal), client.request<Session[]>('sessions', undefined, signal),
        client.request<Worker[]>('workers', undefined, signal), client.request<Profile[]>('profiles', undefined, signal),
        client.request<Queue>('queue', undefined, signal), client.request<Action[]>('actions', undefined, signal),
        sid ? client.request<Snapshot>('sessions/' + sid, undefined, signal) : Promise.resolve(null),
      ])
      if (!mounted.current || signal?.aborted) return
      setStatus(status); setSessions(sessions); setWorkers(workers); setProfiles(profiles); setQueue(queue); setActions(actions); setConnected(true)
      if (sid === current.current && snapshot) setSnapshot(snapshot)
      if (!initialized.current) {
        initialized.current = true
        const saved = localStorage.getItem('fc.session.' + client.base)
        setSelected(sessions.some(s => s.id === saved) ? saved : sessions[0]?.id || null)
      }
    } catch (error) {
      if (signal?.aborted) return
      setConnected(false)
      handleError(error)
    }
  }, [client, handleError])
  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    let pending = false
    const tick = async () => {
      if (pending) return
      pending = true
      await refresh(controller.signal)
      pending = false
    }
    void tick()
    const timer = setInterval(() => void tick(), 2000)
    return () => { mounted.current = false; clearInterval(timer); controller.abort() }
  }, [refresh])
  useEffect(() => {
    const controller = new AbortController()
    setEvents([]); setSnapshot(null); setStreaming(false)
    if (!selected) return () => controller.abort()
    localStorage.setItem('fc.session.' + client.base, selected)
    const run = async () => {
      let cursor = 0
      let delay = 500
      let loaded = false
      while (!controller.signal.aborted) {
        try {
          if (!loaded) {
            const [snapshot, history] = await Promise.all([
              client.request<Snapshot>('sessions/' + selected, undefined, controller.signal), client.history(selected, controller.signal),
            ])
            if (controller.signal.aborted) return
            setSnapshot(snapshot); setEvents(history.events); cursor = history.cursor; loaded = true
          }
          await client.stream(selected, cursor, controller.signal, event => {
            if (controller.signal.aborted || event.session_id !== selected || event.sequence <= cursor) return
            cursor = event.sequence
            setEvents(current => mergeEvents(current, [event]))
            if (event.kind.startsWith('approval.') || event.kind.startsWith('task.') || event.kind.startsWith('lease.')) void refresh(controller.signal)
          }, () => { setStreaming(true); setConnected(true); delay = 500 })
        } catch (error) {
          if (controller.signal.aborted) return
          setStreaming(false)
          if (error instanceof APIError && error.status === 401) { handleError(error); return }
          if (error instanceof APIError && error.status === 400) { handleError(error); return }
          await pause(controller.signal, delay)
          delay = Math.min(delay * 2, 5000)
        }
      }
    }
    void run()
    return () => controller.abort()
  }, [selected, client, handleError, refresh])
  return { status, sessions, workers, profiles, queue, actions, selected, setSelected, snapshot, events,
    connected, streaming, error, setError, handleError, refresh }
}
