import { useCallback, useEffect, useRef, useState } from 'react'
import { APIClient } from './api'
import { Badge, Conversation, human, short, text, Timeline, terminal, WorkerInfo } from './components'
import type { Action, Approval, Json, Lease, Snapshot } from './types'
import { useCore } from './useCore'

function initialClient() {
  const fallback = import.meta.env.DEV ? 'http://127.0.0.1:8741' : window.location.origin
  try { return new APIClient(localStorage.getItem('fc.api') || fallback) } catch { return new APIClient(fallback) }
}

function Connect({ initial, onConnect, initialError }: { initial: string; onConnect: (client: APIClient) => void; initialError: string }) {
  const [url, setUrl] = useState(initial)
  const [token, setToken] = useState('')
  const [error, setError] = useState(initialError)
  const [busy, setBusy] = useState(false)
  async function connect(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const client = new APIClient(url)
      await client.authenticate(token)
      localStorage.setItem('fc.api', client.base)
      onConnect(client)
    } catch (error) { setError(error instanceof Error ? error.message : 'Connection was not confirmed') }
    finally { setToken(''); setBusy(false) }
  }
  return <main className="connect-screen"><form className="connect-form" onSubmit={event => void connect(event)}>
    <div className="brand"><span className="brand-mark">fc</span><strong>FreeCompute</strong><span className="muted">LOCAL CORE</span></div>
    <h1>Connect your workspace</h1><p>Attach this client to the Core running on your machine.</p>
    <label>Core URL<input autoFocus value={url} onChange={e => setUrl(e.target.value)} placeholder="http://127.0.0.1:8741" required /></label>
    <label>Local API token<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} required /></label>
    <p className="muted small">Read the <code>local-api-token</code> file at the path printed by the service. This token is separate from remote worker credentials. It is cleared from this form after connecting.</p>
    {error && <div role="alert" className="error">{error}</div>}
    <button className="primary" disabled={busy}>{busy ? 'Connecting…' : 'Connect to Core'}</button>
    <details className="launch-help"><summary>Start without a GPU</summary><pre>npm --prefix apps/gui ci{'\n'}npm --prefix apps/gui run build{'\n'}python -m harness.api --demo --open</pre><p className="muted">Simulated inference. Any approved tools run in the external demo workspace.</p></details>
  </form></main>
}

function ReconcileLease({ lease, busy, onReconcile }: { lease: Lease; busy: boolean; onReconcile: () => void }) {
  const [confirmed, setConfirmed] = useState(false)
  return <section className="recovery-card"><strong>Inference outcome unknown</strong><p>{lease.worker_id} · lease {short(lease.id)}</p><p className="muted">{lease.reason}. The slot stays held until an operator observes that this worker is idle. Health and low GPU use are insufficient.</p>
    <label className="checkbox"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I independently confirmed this worker is idle.</label>
    <button disabled={!confirmed || busy} onClick={onReconcile}>Reconcile idle lease</button>
  </section>
}

function ReconcileAction({ action, busy, onReconcile }: { action: Action; busy: boolean; onReconcile: (body: Record<string, Json>) => void }) {
  const [outcome, setOutcome] = useState('completed')
  const [witness, setWitness] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  return <section className="recovery-card"><strong>Tool effect needs reconciliation</strong><p>{action.name} · {action.target || 'Host command'}</p>
    <label>Observed outcome<select value={outcome} onChange={e => setOutcome(e.target.value)}><option value="completed">Completed</option><option value="not_executed">Not executed</option></select></label>
    {action.target && <label>Current file SHA-256<input value={witness} onChange={e => setWitness(e.target.value)} placeholder="Independent file witness" /></label>}
    <label className="checkbox"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I checked this tool's actual local outcome.</label>
    <button disabled={!confirmed || busy || !!action.target && !witness} onClick={() => onReconcile({ action_id: action.id, outcome, expected_hash: action.target ? witness : null, confirmed: true })}>Record operator decision</button>
  </section>
}

function Workspace({ client, onUnauthorized, onDisconnect }: { client: APIClient; onUnauthorized: () => void; onDisconnect: () => void }) {
  const core = useCore(client, onUnauthorized)
  const [view, setView] = useState<'conversation' | 'settings'>('conversation')
  const [profileId, setProfileId] = useState('')
  const [workerId, setWorkerId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [deciding, setDeciding] = useState(new Set<string>())
  const [theme, setTheme] = useState(localStorage.getItem('fc.theme') || 'dark')
  const input = useRef<HTMLTextAreaElement>(null)
  const submission = useRef<{ signature: string; body: Record<string, Json> } | null>(null)
  const profile = core.profiles.find(p => p.profile_id === profileId)
  const worker = core.workers.find(w => w.worker_id === workerId)
  const task = core.snapshot?.tasks.at(-1)
  const unfinished = !!task && !terminal.has(task.state)
  const budget = [...core.events].reverse().find(e => e.kind === 'context.budget')?.payload
  const receipt = [...core.events].reverse().find(e => e.kind === 'model.received')?.payload
  useEffect(() => { if (core.status && !profileId) { setProfileId(core.status.default_profile); setWorkerId(core.status.default_worker || '') } }, [core.status, profileId])
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('fc.theme', theme) }, [theme])

  async function command(action: () => Promise<void>) {
    setBusy(true); core.setError('')
    try { await action(); await core.refresh() } catch (error) { core.handleError(error) } finally { setBusy(false) }
  }
  async function newSession() {
    await command(async () => {
      const result = await client.request<Snapshot>('sessions', { profile_id: profileId || core.status!.default_profile })
      core.setSelected(result.session.id); setView('conversation'); setPrompt(''); submission.current = null
    })
  }
  async function send() {
    if (!core.selected || !prompt.trim()) return
    await command(async () => {
      const body = { prompt, session_id: core.selected!, profile_id: profileId, worker_id: workerId || null }
      const signature = JSON.stringify(body)
      if (!submission.current || submission.current.signature !== signature) submission.current = { signature, body: { ...body, request_id: crypto.randomUUID() } }
      await client.request('tasks', submission.current.body)
      submission.current = null; setPrompt('')
    })
  }
  async function decide(approval: Approval, decision: boolean) {
    setDeciding(current => new Set([...current, approval.id]))
    core.setError('')
    try {
      await client.request(`approvals/${approval.id}/decision`, { decision, action_revision: approval.action_revision,
        task_revision: approval.task_revision, arguments_hash: approval.arguments_hash, target_hash: approval.target_hash })
      await core.refresh()
    } catch (error) { core.handleError(error); setDeciding(current => { const next = new Set(current); next.delete(approval.id); return next }) }
  }
  const chooseProfile = (id: string) => { setProfileId(id); if (workerId && !core.profiles.find(p => p.profile_id === id)?.workers.includes(workerId)) setWorkerId('') }
  const fixture = (text: string) => { setPrompt(text); setView('conversation'); input.current?.focus() }
  const workspaceName = core.status?.workspace.split(/[\\/]/).at(-1) || 'Local workspace'
  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">fc</span><strong>FreeCompute</strong><span className="version">V1</span></div>
      <div className="route-pickers"><label>Worker<select aria-label="Worker" value={workerId} onChange={e => setWorkerId(e.target.value)}><option value="">Automatic eligible worker</option>
        {core.workers.map(w => { const compatible = w.profiles.includes(profileId) && w.attached; return <option key={w.worker_id} disabled={!compatible} value={w.worker_id}>{w.worker_id}{!compatible ? ' · incompatible / detached' : ' · ' + human(w.health)}</option> })}</select></label>
        <label>Profile<select aria-label="Profile" value={profileId} onChange={e => chooseProfile(e.target.value)}>{core.profiles.map(p => <option value={p.profile_id} disabled={!p.capabilities.includes('text')} key={p.profile_id}>{p.model}{!p.capabilities.includes('text') ? ' · requires a different operation' : ''}</option>)}</select></label></div>
      <span className={'connection ' + (core.connected ? 'online' : 'offline')} role="status">{core.connected ? 'Core connected' : 'Core disconnected'}</span>
      <button className="icon-button" aria-label="Toggle light or dark appearance" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '☀' : '◐'}</button>
    </header>
    {core.status?.simulated && <div className="simulation-bar"><strong>SIMULATED INFERENCE</strong><span>No GPU or remote model. Approved tools run locally in a disposable workspace.</span></div>}
    <div className="workspace-grid">
      <aside className="sidebar"><div className="workspace-heading"><span className="folder-icon">▱</span><div><strong title={core.status?.workspace}>{workspaceName}</strong><span>Local workspace</span></div></div>
        <button className="new-session" onClick={() => void newSession()} disabled={busy || !core.status}><span>＋</span> New session <span className="shortcut">↵</span></button>
        <div className="sidebar-heading">SESSIONS <span>{core.sessions.length}</span></div>
        <nav className="session-list" aria-label="Sessions">{core.sessions.map(session => <button key={session.id} aria-current={session.id === core.selected && view === 'conversation' ? 'page' : undefined} onClick={() => { core.setSelected(session.id); setView('conversation') }}>
          <span className="session-title">{session.title || 'New session'}</span><span className="session-detail"><span>{human(session.status)}</span><time>{new Date(session.updated_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}</time></span>
        </button>)}{!core.sessions.length && <p className="muted small">No sessions yet. Create one to begin.</p>}</nav>
        <div className="sidebar-bottom"><button aria-current={view === 'settings' ? 'page' : undefined} onClick={() => setView('settings')}>⚙ Workers &amp; settings</button><div className="local-note">Tools and history stay on this machine.</div></div>
      </aside>
      <main className="main-pane">
        <div className="pane-heading"><div><h1>{view === 'settings' ? 'Workers & settings' : core.sessions.find(s => s.id === core.selected)?.title || 'Workspace'}</h1><span>{view === 'settings' ? 'Registered Core routes and client connection' : core.selected ? `Session ${short(core.selected)} · persisted by Core` : 'Create a session to submit a task'}</span></div>
          {view === 'conversation' && task && <div className="task-controls">{unfinished && !['outcome_unknown', 'paused'].includes(task.state) && <button disabled={busy} onClick={() => void command(async () => { await client.request(`tasks/${task.id}/cancel`, {}) })}>Cancel task</button>}
            {['paused', 'outcome_unknown'].includes(task.state) && <button disabled={busy} onClick={() => void command(async () => { await client.request(`tasks/${task.id}/resume`, {}) })}>Resume task</button>}</div>}
        </div>
        {core.error && <div className="error command-error" role="alert"><span>{core.error}</span><button aria-label="Dismiss error" onClick={() => core.setError('')}>×</button></div>}
        {!core.connected && <div className="disconnect-notice">The client is disconnected. Core work may continue; no cancellation is implied. Reconnecting automatically.</div>}
        {view === 'settings' ? <div className="settings-content"><section><h2>Connection</h2><dl><dt>Local API</dt><dd>{client.base}</dd><dt>Workspace</dt><dd>{core.status?.workspace}</dd><dt>Authentication</dt><dd>HttpOnly local session · remote secrets not returned</dd><dt>Core default</dt><dd>{core.status?.default_profile} / {core.status?.default_worker || 'automatic'}</dd></dl>
          <button disabled={busy || !profile} onClick={() => void command(async () => { await client.request('defaults', { profile_id: profileId, worker_id: workerId || null }) })}>Use current selection as Core default</button>
          <p className="muted small">Applies to new tasks in this service. Queued tasks keep their bound route. Restart defaults come from your Core configuration.</p>
          <button onClick={() => void command(async () => { await client.request('auth/logout', {}); onDisconnect() })}>Disconnect this client</button></section>
          <section><div className="section-line"><h2>Registered workers</h2><button disabled={busy} onClick={() => void command(async () => { await client.request('workers/refresh', {}) })}>Refresh health</button></div>{core.workers.map(w => <div className="worker-setting" key={w.worker_id}><WorkerInfo worker={w} /><p className="muted">Profiles: {w.profiles.join(', ')}</p></div>)}</section>
          <section><h2>Model profiles</h2>{core.profiles.map(p => <div className="profile-setting" key={p.profile_id}><strong>{p.model}</strong><code>{p.profile_id}</code><p>{p.capabilities.join(' · ')} · {p.context_capacity.toLocaleString()} declared context · {p.verification}</p><p className="muted">Registered workers: {p.workers.join(', ')}</p></div>)}</section>
        </div> : <>
          <Conversation tasks={core.snapshot?.tasks || []} events={core.events} approvals={core.snapshot?.approvals || []} busyApproval={deciding} onDecision={(a, d) => void decide(a, d)} />
          <div className="composer-area">{core.status?.simulated && <div className="fixture-controls"><span>Fixture prompts</span><button disabled={!profile?.capabilities.includes('code_tools')} onClick={() => fixture('[demo:edit] Inspect calculator.py, fix fractional division, and run the local tests.')}>Read → edit → test</button><button onClick={() => fixture('[demo:long] Stream a long simulated response for cancellation.')}>Long stream</button><button onClick={() => fixture('[demo:failure] Simulate an engine authentication failure.')}>Engine failure</button></div>}
            <form className="composer" onSubmit={e => { e.preventDefault(); void send() }}><label className="sr-only" htmlFor="prompt">Task prompt</label><textarea ref={input} id="prompt" value={prompt} onChange={e => setPrompt(e.target.value)} placeholder={core.selected ? 'Describe a task in your workspace…' : 'Create a session to begin'} disabled={!core.selected} onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); if (!busy && !unfinished && core.connected) void send() } }} />
              <div className="composer-footer"><span>{unfinished ? 'Finish, cancel, or reconcile this session’s current task first.' : 'Ctrl / ⌘ Enter to send · changes require approval'}</span><button className="primary" disabled={busy || !core.connected || !core.selected || !prompt.trim() || unfinished || !profile?.capabilities.includes('text')}>Send task <span>↑</span></button></div>
            </form></div>
        </>}
      </main>
      <aside className="details-pane" aria-label="Task details"><section><h2>Worker</h2><WorkerInfo worker={worker} />{core.status?.simulated && <div className="demo-connection"><button disabled={busy} onClick={() => void command(async () => { await client.request('demo/worker', { connected: !core.workers.some(w => w.health === 'healthy') }) })}>{core.workers.some(w => w.health === 'healthy') ? 'Simulate worker disconnect' : 'Reconnect simulated worker'}</button></div>}</section>
        <section><h2>Model &amp; context</h2><strong>{profile?.model || 'No profile selected'}</strong><p className="muted small">{profile?.verification} · {profile?.capabilities.join(', ')}</p><dl><dt>Declared capacity</dt><dd>{profile?.context_capacity.toLocaleString() || 'Unknown'}</dd><dt>Response reserve</dt><dd>{profile?.reserved_completion.toLocaleString() || 'Unknown'}</dd><dt>Input estimate</dt><dd>{budget ? text(budget.input_total) : 'Not yet emitted'}</dd><dt>Observed TTFT</dt><dd>{receipt?.ttft_ms != null ? text(receipt.ttft_ms) + ' ms' : 'Not reported'}</dd><dt>Token usage</dt><dd>{receipt?.usage && typeof receipt.usage === 'object' && 'prompt_tokens' in receipt.usage ? text(receipt.usage.prompt_tokens) + ' input' : 'Not reported'}</dd></dl>{budget && <p className="muted small">{text(budget.method)}</p>}</section>
        <section><div className="section-line"><h2>Queue &amp; resources</h2><span className="count">{core.queue.jobs.length}</span></div>{core.queue.active_task_id && <p className="queue-active">Local task active · {short(core.queue.active_task_id)}</p>}
          {!core.queue.jobs.length && !core.queue.leases.length && <p className="muted">No queued or held inference.</p>}
          {core.queue.jobs.map(job => <div className="queue-row" key={job.id}><div><code>{short(job.task_id)}</code><Badge state={job.state} /></div><span>{job.profile_id} · {job.requested_worker || 'eligible worker'}</span><p className="muted small">{job.waiting_reason || (core.queue.active_task_id !== job.task_id && core.queue.active_task_id ? 'Local task / approval loop is busy' : 'Waiting for Core dispatch')}</p></div>)}
          {core.queue.leases.map(lease => lease.state === 'quarantined' ? <ReconcileLease key={lease.id} lease={lease} busy={busy} onReconcile={() => void command(async () => { await client.request('reconcile/inference', { lease_id: lease.id, confirmed_idle: true }) })} /> : <p className="lease-active" key={lease.id}>Active lease · {lease.worker_id} · {short(lease.id)}</p>)}
          {core.actions.filter(a => a.state === 'outcome_unknown').map(action => <ReconcileAction key={action.id} action={action} busy={busy} onReconcile={body => void command(async () => { await client.request('reconcile/action', body) })} />)}
        </section>
        <section className="timeline-section"><div className="section-line"><h2>Task timeline</h2><span className="count">#{core.events.at(-1)?.sequence || 0}</span></div><p className="muted small">Latest 60 state events · Core sequence</p><Timeline events={core.events} /></section>
      </aside>
    </div>
    <footer className="statusbar"><span>LOCAL AUTHORITY · {core.status?.workspace || 'Connecting'}</span><span>{core.streaming ? 'Events connected' : core.selected ? 'Events reconnecting' : 'No session selected'} · HTTP / SSE</span></footer>
  </div>
}

export default function App() {
  const [client, setClient] = useState(initialClient)
  const [authenticated, setAuthenticated] = useState(false)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState('')
  const unauthorized = useCallback(() => { setAuthenticated(false); setChecking(false); setError('Your local API session expired or the service restarted. Reconnect; Core history is retained.') }, [])
  useEffect(() => {
    let alive = true
    void client.authenticate().then(() => { if (alive) setAuthenticated(true) }).catch(() => {}).finally(() => { if (alive) setChecking(false) })
    return () => { alive = false }
  }, [client])
  if (checking) return <main className="connect-screen"><p role="status">Connecting to local Core…</p></main>
  if (!authenticated) return <Connect initial={client.base} initialError={error} onConnect={next => { setClient(next); setAuthenticated(true); setError('') }} />
  return <Workspace key={client.base} client={client} onUnauthorized={unauthorized} onDisconnect={() => { setAuthenticated(false); setError('') }} />
}
