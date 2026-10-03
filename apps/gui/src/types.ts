export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type Payload = Record<string, Json>
export interface CoreEvent {
  id: string; session_id: string; task_id: string | null; sequence: number; kind: string;
  entity_id: string; revision: number; actor: string; created_at: string; payload: Payload
}
export interface Session {
  id: string; title?: string; status: string; profile_id: string; current_task_id: string | null;
  context_epoch: number; revision: number; created_at: string; updated_at: string
}
export interface Task {
  id: string; session_id: string; state: string; prompt: string; profile_id: string; final_answer: string;
  revision: number; context_epoch: number; created_at: string; updated_at: string;
  cancellation: { requested: boolean; local_stop_confirmed: boolean; remote_cancel_confirmed: boolean; remote_outcome: string }
}
export interface Approval {
  id: string; action_id: string; tool: string; task_id: string; session_id: string; profile_id: string;
  state: string; action_revision: number; task_revision: number; context_epoch: number;
  arguments_hash: string; target_hash: string | null; preview: Payload; diff: string
}
export interface Snapshot { session: Session; tasks: Task[]; approvals: Approval[]; cursor: number }
export interface Worker {
  worker_id: string; location: string; engine: string; capabilities: string[]; health: string; attached: boolean;
  profiles: string[]; last_seen: string | null; observed_at: string | null; observed_resources: Payload; active_or_quarantined: number; concurrency_limit: number
}
export interface Profile {
  profile_id: string; model: string; engine: string; capabilities: string[]; workers: string[];
  context_capacity: number; reserved_completion: number; verification: string
}
export interface QueueJob {
  id: string; task_id: string; profile_id: string; requested_worker: string | null; assigned_worker: string | null;
  state: string; task_state: string; waiting_reason: string; sequence: number; created_at: string
}
export interface Lease { id: string; worker_id: string; profile_id: string; task_id: string; state: string; reason: string }
export interface Queue { jobs: QueueJob[]; leases: Lease[]; active_task_id: string | null }
export interface Action { id: string; task_id: string; name: string; state: string; revision: number; target: string | null; pre_hash: string | null; post_hash: string | null; arguments: Payload; result: Payload | null }
export interface Status {
  api_version: number; simulated: boolean; workspace: string; default_profile: string; default_worker: string | null;
  active_task_id: string | null; runtime_error: string | null
}
export interface EventPage { events: CoreEvent[]; cursor: number; has_more: boolean }
