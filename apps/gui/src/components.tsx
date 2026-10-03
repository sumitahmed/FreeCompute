import { useEffect, useRef, useState } from 'react'
import type { Approval, CoreEvent, Json, Payload, Task, Worker } from './types'

export const text = (value: Json | undefined) => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2)
export const terminal = new Set(['completed', 'failed', 'cancelled', 'context_overflow', 'malformed', 'truncated', 'incomplete', 'max_turns'])
export const human = (value: string) => value.replaceAll('_', ' ')
export const short = (id: string) => id.slice(0, 8)
export function Badge({ state }: { state: string }) { return <span className={'badge state-' + state}>{human(state)}</span> }

export function ApprovalCard({ approval, deciding, onDecision }: { approval: Approval; deciding: boolean; onDecision: (decision: boolean) => void }) {
  return <section className="approval-card" aria-label={'Approval for ' + approval.tool}>
    <div className="approval-heading"><span className="approval-icon">!</span><div><strong>Approval required</strong><span>{approval.tool} · one local action</span></div></div>
    {approval.preview.path && <p className="target">{text(approval.preview.path)}</p>}
    {approval.preview.command && <pre className="command">$ {text(approval.preview.command)}</pre>}
    {typeof approval.preview.content === 'string' && <pre aria-label="Proposed file content">{approval.preview.content}</pre>}
    {approval.diff ? <Diff value={approval.diff} /> : <details><summary>Exact tool arguments</summary><pre>{JSON.stringify(approval.preview, null, 2)}</pre></details>}
    <p className="muted">{approval.tool === 'run_command' ? 'Runs on your local host in the workspace.' : 'Changes the local workspace after Core validates the target.'} This decision grants only this action.</p>
    <details className="binding"><summary>Revision &amp; file witness</summary><dl>
      <dt>Action revision</dt><dd>{approval.action_revision}</dd><dt>Task revision</dt><dd>{approval.task_revision}</dd>
      <dt>Context epoch</dt><dd>{approval.context_epoch}</dd><dt>Target SHA-256</dt><dd>{approval.target_hash || 'Not a file target'}</dd>
      <dt>Arguments hash</dt><dd>{approval.arguments_hash}</dd><dt>Approval ID</dt><dd>{approval.id}</dd>
    </dl></details>
    <div className="approval-buttons"><button className="primary" disabled={deciding} onClick={() => onDecision(true)}>Approve {approval.tool === 'run_command' ? 'command' : 'change'}</button>
      <button disabled={deciding} onClick={() => onDecision(false)}>Deny</button>{deciding && <span role="status">Decision sent; waiting for Core</span>}</div>
  </section>
}

export function Diff({ value }: { value: string }) {
  return <pre className="diff" aria-label="Change preview">{value.split('\n').map((line, i) => <span key={i} className={line.startsWith('+') ? 'addition' : line.startsWith('-') ? 'deletion' : line.startsWith('@@') ? 'hunk' : ''}>{line || '\u00a0'}</span>)}</pre>
}

interface ModelItem { kind: 'model'; key: string; content: string; reasoning: string; finished: boolean }
interface ToolItem { kind: 'tool'; key: string; name: string; arguments: Payload; result?: Payload; state: string }
type ConversationItem = ModelItem | ToolItem
export function conversation(events: CoreEvent[]): ConversationItem[] {
  const items: ConversationItem[] = []
  const tools = new Map<string, ToolItem>()
  let model: ModelItem | undefined
  for (const event of events) {
    if (event.kind === 'model.requested') {
      model = { kind: 'model', key: event.id, content: '', reasoning: '', finished: false }
      items.push(model)
    } else if (event.kind === 'stream.text' || event.kind === 'stream.reasoning') {
      if (!model) { model = { kind: 'model', key: event.id, content: '', reasoning: '', finished: false }; items.push(model) }
      if (event.kind === 'stream.text') model.content += text(event.payload.text)
      else model.reasoning += text(event.payload.text)
    } else if (event.kind === 'model.received' && model) model.finished = true
    else if (event.kind === 'tool.proposed') {
      const key = text(event.payload.action_id)
      const arguments_ = event.payload.arguments
      const item: ToolItem = { kind: 'tool', key, name: text(event.payload.tool), arguments: typeof arguments_ === 'object' && arguments_ && !Array.isArray(arguments_) ? arguments_ : {}, state: 'proposed' }
      tools.set(key, item); items.push(item)
    } else if (event.kind.startsWith('tool.')) {
      const tool = tools.get(text(event.payload.action_id))
      if (tool) {
        tool.state = event.kind.slice(5)
        const result = event.payload.result
        if (result && typeof result === 'object' && !Array.isArray(result)) tool.result = result
      }
    }
  }
  return items
}

function ToolResult({ result }: { result: Payload }) {
  return <div className="tool-result">
    {result.exit_code !== undefined && <div className="receipt-head"><Badge state={result.exit_code === 0 ? 'completed' : 'failed'} /><span>Exit {text(result.exit_code)} · local command receipt</span></div>}
    {result.diff && <Diff value={text(result.diff)} />}
    {(result.stdout || result.stderr) && <pre className="command-output">{text(result.stdout)}{text(result.stderr)}</pre>}
    <details><summary>Recorded result</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>
  </div>
}

export function Conversation({ tasks, events, approvals, busyApproval, onDecision }: {
  tasks: Task[]; events: CoreEvent[]; approvals: Approval[]; busyApproval: Set<string>; onDecision: (approval: Approval, decision: boolean) => void
}) {
  const scroll = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const [, tick] = useState(0)
  useEffect(() => { const timer = setInterval(() => tick(n => n + 1), 1000); return () => clearInterval(timer) }, [])
  useEffect(() => { if (scroll.current && following.current) scroll.current.scrollTop = scroll.current.scrollHeight }, [events, approvals, tasks])
  return <div className="conversation" ref={scroll} onScroll={() => { const node = scroll.current; if (node) following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 150 }}>
    {!tasks.length && <div className="empty"><span className="empty-symbol">⌘</span><h2>Ready for a local task</h2><p>Send a prompt to your selected worker. Review proposed changes and commands here.</p><p className="muted">Core owns your session, tools, and task history.</p></div>}
    {tasks.map(task => {
      const taskEvents = events.filter(e => e.task_id === task.id)
      const items = conversation(taskEvents)
      const last = taskEvents.at(-1)
      const seconds = Math.max(0, ((terminal.has(task.state) ? new Date(task.updated_at).getTime() : Date.now()) - new Date(task.created_at).getTime()) / 1000)
      return <article className="task-block" key={task.id}>
        <div className="user-message"><span className="message-label">YOU</span><p>{task.prompt}</p></div>
        <div className="task-meta"><Badge state={task.state} /><span>{short(task.id)} · {seconds.toFixed(0)}s elapsed</span></div>
        {items.map(item => item.kind === 'model' ? <div className="model-message" key={item.key}>
          <span className="message-label">ASSISTANT{!item.finished ? ' · STREAMING' : ''}</span>
          {item.content ? <p className="model-text">{item.content}</p> : <p className="muted">Awaiting model output</p>}
          {item.reasoning && <details><summary>Reasoning emitted by the engine</summary><pre>{item.reasoning}</pre></details>}
        </div> : <section className="tool-card" key={item.key} aria-label={'Tool ' + item.name}>
          <div className="tool-heading"><strong>{item.name}</strong><Badge state={item.state} /></div>
          <span className="muted">Local tool · Core controlled</span>
          <pre className="tool-arguments">{item.arguments.command ? '$ ' + text(item.arguments.command) : JSON.stringify(item.arguments, null, 2)}</pre>
          {item.result && <ToolResult result={item.result} />}
        </section>)}
        {approvals.filter(a => a.task_id === task.id).map(approval => <ApprovalCard key={approval.id} approval={approval} deciding={busyApproval.has(approval.id)} onDecision={decision => onDecision(approval, decision)} />)}
        {task.final_answer && <section className="final-answer"><span className="message-label">FINAL ANSWER · CORE RECEIPT</span><p>{task.final_answer}</p></section>}
        {last && terminal.has(task.state) && task.state !== 'completed' && <div className="task-notice" role="status">{text(last.payload.detail) || `Task ${human(task.state)}. Inspect the timeline and receipts before resuming.`}</div>}
        {task.cancellation.requested && <div className="task-notice"><strong>{task.cancellation.local_stop_confirmed ? 'Stopped locally' : 'Cancellation requested'}</strong><p>Remote cancellation: {task.cancellation.remote_cancel_confirmed ? 'acknowledged' : 'unconfirmed'}. Remote outcome: {human(task.cancellation.remote_outcome)}.</p></div>}
      </article>
    })}
  </div>
}

const labels: Record<string, string> = {
  'session.created': 'Session created', 'task.created': 'Prompt submitted', 'queue.enqueued': 'Queued', 'queue.waiting': 'Waiting for worker',
  'task.started': 'Core task started', 'queue.assigned': 'Worker assigned', 'model.requested': 'Model started', 'model.received': 'Model receipt',
  'tool.proposed': 'Tool proposed', 'approval.requested': 'Waiting for approval', 'approval.decided': 'Approval decision',
  'tool.execution_intent': 'Tool running', 'tool.completed': 'Tool completed', 'tool.denied': 'Tool denied', 'task.turn_completed': 'Turn complete',
  'task.completed': 'Completed', 'task.failed': 'Failed', 'task.cancelled': 'Cancelled locally', 'task.cancel_requested': 'Cancellation requested',
  'task.outcome_unknown': 'Outcome unknown', 'lease.quarantined': 'Lease quarantined', 'lease.reconciled': 'Lease reconciled', 'task.recovered': 'Recovered after restart',
}
export function Timeline({ events }: { events: CoreEvent[] }) {
  return <ol className="timeline" aria-label="Ordered Core timeline">{events.filter(e => !e.kind.startsWith('stream.') && e.kind !== 'context.budget').slice(-60).map(event => <li key={event.id}>
    <div><span className="sequence">{event.sequence}</span><strong>{labels[event.kind] || human(event.kind)}</strong><time>{new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time></div>
    <span className="muted">{text(event.payload.tool) || text(event.payload.worker_id) || text(event.payload.reason) || text(event.payload.decision) || text(event.payload.detail)}</span>
  </li>)}</ol>
}

export function WorkerInfo({ worker }: { worker: Worker | undefined }) {
  if (!worker) return <p className="muted">No worker selected. Core will choose an eligible registered worker.</p>
  const raw = worker.observed_resources.gpus || worker.observed_resources.gpu_observations
  const gpus = Array.isArray(raw) ? raw : []
  return <><div className="section-line"><strong>{worker.worker_id}</strong><Badge state={worker.health === 'unhealthy' || worker.health === 'unreachable' ? 'degraded' : worker.health === 'unverified' || worker.health === 'unconfigured' ? 'unknown' : worker.health} /></div>
    <dl><dt>Location</dt><dd>{worker.location}</dd><dt>Engine</dt><dd>{worker.engine}</dd><dt>Capabilities</dt><dd>{worker.capabilities.join(', ')}</dd>
      <dt>Held slots</dt><dd>{worker.active_or_quarantined} / {worker.concurrency_limit} declared</dd><dt>Observation</dt><dd>{worker.observed_at ? new Date(worker.observed_at).toLocaleString() : 'Unknown'}</dd><dt>Last healthy</dt><dd>{worker.last_seen ? new Date(worker.last_seen).toLocaleString() : 'Unknown'}</dd></dl>
    {gpus.map((gpu, i) => { const row = gpu as Payload; return <p className="gpu" key={i}>{text(row.name)} · {text(row.vram_used_mib ?? row.vramUsedMiB)} / {text(row.vram_total_mib ?? row.vramTotalMiB)} MiB observed</p> })}
    {!!worker.observed_resources.error && <p className="task-notice">{text(worker.observed_resources.error)}</p>}
    <p className="muted small">Capacity follows declared leases. VRAM observations do not grant a slot.</p>
  </>
}
