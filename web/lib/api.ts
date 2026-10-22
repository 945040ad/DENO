/**
 * Browser-side client for the FastAPI v1 API (proxied at /api/* by next.config.ts).
 * Attaches the Supabase access token when signed in. Types mirror /api/v1/openapi.json.
 */
import { createClient } from '@/lib/supabase/client';

// ---- types -------------------------------------------------------------------------

export type RunStatus = 'queued' | 'running' | 'awaiting_review' | 'succeeded' | 'failed' | 'cancelled';
export type VerdictKind = 'build' | 'pivot' | 'kill' | 'insufficient_evidence';
export type Stance = 'supports' | 'refutes' | 'neutral';
export type StoryCategory = 'scar' | 'metric' | 'turning_point' | 'defended_opinion' | 'customer_quote';
export type DraftStatus = 'draft' | 'gated' | 'approved' | 'rejected' | 'exported';
export type GatePlatform = 'linkedin' | 'reddit' | 'x' | 'hn';

export interface LatestRun {
  id: string;
  status: RunStatus;
  error_code: string | null;
  created_at: string;
  finished_at: string | null;
  verdict: VerdictKind | null;
  confidence: number | null;
}

export interface Project {
  id: string;
  title: string;
  idea: string;
  status: string;
  created_at: string;
  /** Newest validation run with its verdict; null when the idea was never run. */
  latest_run?: LatestRun | null;
}

export interface Run {
  id: string;
  project_id: string;
  status: RunStatus;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface Evidence {
  id: string;
  source: string;
  url: string;
  author_handle: string | null;
  community: string | null;
  published_at: string | null;
  engagement: Record<string, number>;
  excerpt: string | null;
}

export interface Citation {
  chunk_id: string;
  quote: string;
  verified: boolean;
  entailment_score: number | null;
  document: Evidence;
}

export interface Claim {
  id: string;
  analyst: string;
  text: string;
  stance: Stance;
  dropped: boolean;
  flagged_wrong: boolean;
  citations: Citation[];
}

export interface Signal {
  name: string;
  value: number;
  method: string;
  inputs: Record<string, unknown>;
}

export interface Verdict {
  verdict: VerdictKind;
  confidence: number;
  coverage: { documents?: number; by_source?: Record<string, number>; gaps?: string[] } & Record<string, unknown>;
  reasons: string[];
  rationale: string | null;
}

export interface Report {
  run: Run;
  verdict: Verdict | null;
  signals: Signal[];
  claims: Claim[];
}

export interface Community {
  id: string;
  platform: string;
  name: string;
  url: string | null;
  audience: string | null;
  relevance: number | null;
  evidence_count: number | null;
  karma_gate: string | null;
  promo_policy: string | null;
  ai_policy: string | null;
  cadence: string | null;
  rules_verified: boolean;
}

export interface VoiceSample {
  id: string;
  text: string;
  created_at: string;
}

export interface VoiceProfile {
  version: number;
  samples: number;
  strong: boolean;
  threshold: number;
  created_at: string;
  avg_draft_delta: number | null;
  drafts_scored: number;
}

export interface Story {
  id: string;
  category: StoryCategory;
  headline: string;
  details: string;
  numbers: string[];
  tags: string[];
}

export interface GateFinding {
  rule_id: string;
  message: string;
  quote: string;
  fix: string;
  severity: 'block' | 'warn';
}

export interface GateLayer {
  layer: string;
  passed: boolean;
  score: number | null;
  findings: GateFinding[];
}

export interface Draft {
  id: string;
  version: number;
  text: string;
  first_comment: string | null;
  status: DraftStatus;
  edited_by_user: boolean;
  gates: GateLayer[];
}

export interface Brief {
  id: string;
  day: number;
  platform: string;
  community: string | null;
  hook_formula: string | null;
  angle: string;
  is_promotional: boolean;
  draft: Draft | null;
}

export interface Plan {
  id: string;
  project_id: string;
  run_id: string | null;
  days: number;
  status: RunStatus;
  briefs: Brief[];
}

export interface Audit {
  passed: boolean;
  layers: GateLayer[];
  autofixed: string;
}

export interface StreamEvent {
  type: string;
  node?: string;
  status?: RunStatus;
  source?: string;
  count?: number;
  error?: string | null;
  message?: string;
  [key: string]: unknown;
}

// ---- transport ---------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const supabase = createClient();
  if (!supabase) return {};
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = { ...(await authHeaders()), ...(init.headers as Record<string, string> | undefined) };
  const res = await fetch(`/api/v1${path}`, { ...init, headers });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    let code: string | undefined;
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string } };
      if (body.error?.message) message = body.error.message;
      code = body.error?.code;
    } catch {
      /* not JSON */
    }
    if (code === 'mfa_required' && typeof window !== 'undefined') {
      // The session is password-only but this account has 2FA: finish the second step first.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- full reload outside React on purpose
      window.location.href = `/auth/mfa?next=${encodeURIComponent(window.location.pathname)}`;
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function send<T>(method: string, path: string, body?: unknown, extra: Record<string, string> = {}): Promise<T> {
  return request<T>(path, {
    method,
    headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...extra },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

const enc = encodeURIComponent;

export interface Billing {
  plan: 'free' | 'pro' | 'internal';
  status: string;
  current_period_end: string | null;
  billing_enabled: boolean;
  usage: { kind: string; used: number; limit: number | null }[];
}

export interface Handle {
  platform: 'reddit' | 'x' | 'linkedin' | 'hn';
  handle: string;
}

export interface Me {
  id: string;
  email: string | null;
  display_name: string | null;
  plan: string;
  role: string;
  product_name: string | null;
  product_url: string | null;
  timezone: string | null;
  founder_role: string | null;
  handles: Handle[];
  voice_preset: string | null;
  notification_prefs: Record<string, boolean>;
}

export const api = {
  me: () => request<Me>('/me'),
  updateMe: (body: Partial<Omit<Me, 'id' | 'email' | 'plan' | 'role'>>) => send<Me>('PATCH', '/me', body),
  billing: () => request<Billing>('/billing'),
  checkout: () => send<{ url: string }>('POST', '/billing/checkout'),
  portal: () => send<{ url: string }>('POST', '/billing/portal'),
  exportData: () => request<unknown>('/me/export'),
  deleteAccount: () => send<void>('DELETE', '/me'),
  takedown: (body: { url?: string | null; author_handle?: string | null; reason: string; contact?: string | null }) =>
    send<{ id: string; status: string }>('POST', '/takedowns', body),
  createProject: (idea: string, authorHandle: string | null) =>
    send<Project>('POST', '/projects', { idea, author_handle: authorHandle }),
  listProjects: () => request<{ items: Project[]; next_cursor: string | null }>('/projects?limit=20'),
  listRuns: (projectId: string) => request<Run[]>(`/projects/${enc(projectId)}/runs`),
  startRun: (projectId: string) =>
    send<{ run_id: string; status: RunStatus; events_url: string }>('POST', `/projects/${enc(projectId)}/runs`, undefined, {
      'Idempotency-Key': crypto.randomUUID(),
    }),
  getRun: (runId: string) => request<Run>(`/runs/${enc(runId)}`),
  report: (runId: string) => request<Report>(`/runs/${enc(runId)}/report`),
  resume: (runId: string, wrongClaimIds: string[]) =>
    send<Run>('POST', `/runs/${enc(runId)}/resume`, { approve: true, wrong_claim_ids: wrongClaimIds }),
  cancel: (runId: string) => send<Run>('POST', `/runs/${enc(runId)}/cancel`),
  runCommunities: (runId: string) => request<Community[]>(`/runs/${enc(runId)}/communities`),

  voiceSamples: () => request<VoiceSample[]>('/voice/samples'),
  addVoiceSample: (text: string) => send<VoiceSample>('POST', '/voice/samples', { text }),
  deleteVoiceSample: (id: string) => send<void>('DELETE', `/voice/samples/${enc(id)}`),
  buildVoiceProfile: () => send<VoiceProfile>('POST', '/voice/profile'),
  voiceProfile: () => request<VoiceProfile | null>('/voice/profile'),

  stories: () => request<Story[]>('/stories'),
  addStory: (story: Omit<Story, 'id' | 'tags'> & { tags?: string[] }) => send<Story>('POST', '/stories', story),
  deleteStory: (id: string) => send<void>('DELETE', `/stories/${enc(id)}`),

  createPlan: (projectId: string, days: 7 | 14 | 30, runId?: string | null) =>
    send<{ plan_id: string; status: RunStatus; events_url: string }>('POST', `/projects/${enc(projectId)}/content-plans`, {
      days,
      run_id: runId ?? null,
    }),
  listPlans: (projectId: string) => request<Plan[]>(`/projects/${enc(projectId)}/content-plans`),
  plan: (planId: string) => request<Plan>(`/content-plans/${enc(planId)}`),
  editDraft: (draftId: string, text: string) => send<Draft>('PATCH', `/drafts/${enc(draftId)}`, { text }),
  /** Gate an unsaved edit with the draft's own context. Saves nothing and isn't counted as an audit. */
  checkDraft: (draftId: string, text: string) => send<GateLayer[]>('POST', `/drafts/${enc(draftId)}/check`, { text }),
  approveDraft: (draftId: string) => send<Draft>('POST', `/drafts/${enc(draftId)}/approve`),
  exportDraft: (draftId: string) => send<Draft>('POST', `/drafts/${enc(draftId)}/export`),
  audit: (text: string, platform: GatePlatform, community?: string | null) =>
    send<Audit>('POST', '/gates/audit', { text, platform, community: community ?? null }),
};

/**
 * Reads a text/event-stream with fetch instead of EventSource, so the
 * Authorization header can be sent. Resolves when the stream ends or the
 * signal aborts.
 */
export async function streamEvents(
  path: string,
  onData: (data: string) => void,
  signal: AbortSignal,
  resume?: { lastEventId?: string; onId?: (id: string) => void },
): Promise<void> {
  const headers: Record<string, string> = { Accept: 'text/event-stream', ...(await authHeaders()) };
  if (resume?.lastEventId) headers['Last-Event-ID'] = resume.lastEventId;
  const res = await fetch(path, { headers, signal });
  if (!res.ok || !res.body) throw new ApiError(res.status, 'stream failed');
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let boundary: number;
    while ((boundary = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary).replace(/^\r?\n\r?\n/, '');
      const lines = block.split(/\r?\n/);
      const id = lines.find((line) => line.startsWith('id:'))?.slice(3).trim();
      const data = lines
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).replace(/^ /, ''))
        .join('\n');
      if (data) onData(data);
      if (id) resume?.onId?.(id);
    }
  }
}

/**
 * Follow a run/plan event stream until it has really finished. Long responses get cut by proxies
 * (Vercel's rewrite, mobile networks), so when the connection ends early this asks `isDone()` and,
 * if the work is still going, reconnects with `Last-Event-ID` (no events lost or repeated).
 */
export async function followEvents(
  path: string,
  onData: (data: string) => void,
  signal: AbortSignal,
  isDone: () => Promise<boolean>,
): Promise<void> {
  let lastEventId: string | undefined;
  let delay = 1000;
  for (;;) {
    try {
      await streamEvents(path, onData, signal, { lastEventId, onId: (id) => (lastEventId = id) });
    } catch {
      // dropped connection or a transient API error: fall through to the status check
    }
    if (signal.aborted) return;
    if (await isDone().catch(() => false)) return;
    await new Promise((resolve) => setTimeout(resolve, delay));
    if (signal.aborted) return;
    delay = Math.min(delay * 2, 8000);
  }
}

/** Only http(s) links from API data become hrefs (blocks javascript: URLs). */
export function safeHref(url: string | null | undefined): string {
  try {
    const parsed = new URL(url ?? '');
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : '#';
  } catch {
    return '#';
  }
}

export const TERMINAL: RunStatus[] = ['succeeded', 'failed', 'cancelled', 'awaiting_review'];

export function signal(report: Report | null, name: string): number | null {
  const s = report?.signals.find((x) => x.name === name);
  return s ? s.value : null;
}

/** Flattens gate layers into the itemised list the editor and studio show. */
export function blockingFindings(layers: GateLayer[]): (GateFinding & { layer: string })[] {
  return layers.flatMap((l) => l.findings.filter((f) => f.severity === 'block').map((f) => ({ ...f, layer: l.layer })));
}

export function warningFindings(layers: GateLayer[]): (GateFinding & { layer: string })[] {
  return layers.flatMap((l) => l.findings.filter((f) => f.severity === 'warn').map((f) => ({ ...f, layer: l.layer })));
}
