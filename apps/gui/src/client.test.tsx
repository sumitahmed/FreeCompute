import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { APIClient, APIError, mergeEvents, SSEParser } from './api'
import { ApprovalCard, conversation, Conversation, WorkerInfo } from './components'
import type { Approval, CoreEvent, Task, Worker } from './types'

afterEach(() => cleanup())
const event = (sequence: number, kind: string, payload: CoreEvent['payload'] = {}): CoreEvent => ({
  id: 'event-' + sequence, session_id: 'session', task_id: 'task', sequence, kind, payload,
  entity_id: 'entity', revision: 0, actor: 'core', created_at: '2026-10-03T12:00:00Z',
})
const approval: Approval = { id: 'approval', action_id: 'action', task_id: 'task', session_id: 'session', tool: 'edit_file',
  state: 'pending', profile_id: 'profile', action_revision: 2, task_revision: 3, context_epoch: 0,
  arguments_hash: 'args-witness', target_hash: 'file-witness', preview: { path: 'calculator.py', old_str: '//', new_str: '/' }, diff: '--- a/calculator.py\n+++ b/calculator.py\n-//\n+/' }

describe('event transport', () => {
  it('parses fragmented CRLF frames, multiline data, and heartbeat frames', () => {
    const frames: string[][] = []
    const parser = new SSEParser((kind, data) => frames.push([kind, data]))
    for (const chunk of ['id: 1\r\nevent: co', 're\r\ndata: first\r\ndata: second\r', '\n\r', '\nevent: heartbeat\ndata: {}\n\n']) parser.feed(chunk)
    expect(frames).toEqual([['core', 'first\nsecond'], ['heartbeat', '{}']])
  })
  it('deduplicates replay and preserves Core sequence ordering', () => {
    expect(mergeEvents([event(2, 'task.started'), event(1, 'task.created')], [event(2, 'task.started'), event(3, 'task.completed')]).map(e => e.sequence)).toEqual([1, 2, 3])
  })
  it('rejects public, credentialed, and query-bearing API URLs', () => {
    for (const url of ['https://example.com', 'http://user:password@127.0.0.1:8741', 'http://127.0.0.1:8741?token=unsafe', 'http://127.0.0.1:8741/path']) expect(() => new APIClient(url)).toThrow()
  })
  it('uses ambient HttpOnly sessions plus CSRF, without token URLs', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    const api = new APIClient('http://127.0.0.1:8741')
    api.csrf = 'test-csrf-value'
    await api.request('sessions', {})
    expect(fetch.mock.calls[0][0]).toBe('http://127.0.0.1:8741/api/v1/sessions')
    expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: 'include', headers: { 'X-FreeCompute-CSRF': 'test-csrf-value' } })
    vi.unstubAllGlobals()
  })
  it('preserves actionable auth/conflict errors from the Core API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'state_conflict', message: 'File binding changed' } }), { status: 409 })))
    const api = new APIClient('http://127.0.0.1:8741')
    await expect(api.request('sessions')).rejects.toEqual(new APIError(409, 'state_conflict', 'File binding changed'))
    vi.unstubAllGlobals()
  })
})

describe('Core presentation', () => {
  it('does not decide an approval until an explicit button action', () => {
    const decision = vi.fn()
    render(<ApprovalCard approval={approval} deciding={false} onDecision={decision} />)
    expect(decision).not.toHaveBeenCalled()
    expect(screen.getByText('calculator.py')).toBeTruthy()
    expect(screen.getByText('file-witness')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Deny' }))
    expect(decision).toHaveBeenCalledWith(false)
  })
  it('disables duplicate approval delivery and labels delivery separately from approval', () => {
    render(<ApprovalCard approval={approval} deciding onDecision={() => { throw new Error('No second delivery') }} />)
    expect((screen.getByRole('button', { name: 'Approve change' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('status').textContent).toContain('waiting for Core')
  })
  it('builds several model/tool cycles from actual events and preserves receipts', () => {
    const items = conversation([event(1, 'model.requested'), event(2, 'stream.text', { text: 'Read ' }),
      event(3, 'model.received'), event(4, 'tool.proposed', { action_id: 'a', tool: 'read_file', arguments: { path: 'file.py' } }),
      event(5, 'tool.completed', { action_id: 'a', result: { raw_content: 'hello' } }), event(6, 'model.requested'), event(7, 'stream.text', { text: 'Done' })])
    expect(items).toHaveLength(3)
    expect(items[1]).toMatchObject({ kind: 'tool', result: { raw_content: 'hello' }, state: 'completed' })
    expect(items[2]).toMatchObject({ content: 'Done', finished: false })
  })
  it('renders reasoning only when a reasoning event is emitted', () => {
    const task: Task = { id: 'task', session_id: 'session', state: 'completed', prompt: '<script>unsafe</script>', profile_id: 'profile',
      final_answer: 'Recorded final answer', revision: 0, context_epoch: 0, created_at: '2026-10-03T12:00:00Z', updated_at: '2026-10-03T12:00:01Z',
      cancellation: { requested: false, local_stop_confirmed: false, remote_cancel_confirmed: false, remote_outcome: 'not_requested' } }
    const props = { tasks: [task], approvals: [], busyApproval: new Set<string>(), onDecision: vi.fn() }
    const view = render(<Conversation {...props} events={[event(1, 'model.requested'), event(2, 'stream.text', { text: 'Visible output' })]} />)
    expect(screen.queryByText('Reasoning emitted by the engine')).toBeNull()
    expect(document.querySelector('script')).toBeNull()
    view.rerender(<Conversation {...props} events={[event(1, 'model.requested'), event(2, 'stream.reasoning', { text: 'Explicit displayable engine output' }), event(3, 'model.received', { error: 'No text returned' })]} />)
    expect(screen.getByText('Reasoning emitted by the engine')).toBeTruthy()
    expect(screen.getByText('No model text returned')).toBeTruthy()
    expect(screen.getByText('Recorded final answer')).toBeTruthy()
  })
  it('shows stale observations without turning free VRAM into schedulable capacity', () => {
    const worker: Worker = { worker_id: 'fixture', location: 'local simulation', engine: 'fixture', capabilities: ['text'], health: 'stale', attached: true,
      profiles: ['profile'], last_seen: null, observed_at: null, observed_resources: { gpus: [{ name: 'SIMULATED GPU', vramUsedMiB: 100, vramTotalMiB: 1000 }] }, active_or_quarantined: 1, concurrency_limit: 1 }
    render(<WorkerInfo worker={worker} />)
    expect(screen.getByText('stale')).toBeTruthy()
    expect(screen.getByText('1 / 1 declared')).toBeTruthy()
    expect(screen.getByText(/VRAM observations do not grant a slot/)).toBeTruthy()
  })
})
