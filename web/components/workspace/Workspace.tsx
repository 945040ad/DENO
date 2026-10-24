'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  api,
  ApiError,
  blockingFindings,
  safeHref,
  signal,
  followEvents,
  TERMINAL,
  warningFindings,
  type Audit,
  type Brief,
  type Claim,
  type Community,
  type GateLayer,
  type GatePlatform,
  type Plan,
  type Project,
  type Run,
  type Report,
  type StreamEvent,
  type StudioEdit,
} from '@/lib/api';

type Screen = 0 | 1 | 2 | 3;
const PAST_LIMIT = 6;
// Wall clock for event handlers (kept out of render so the React compiler's purity check holds).
const clockNow = () => Date.now();

function ago(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

const PAST_VERDICT: Record<string, { word: string; cls: string }> = {
  build: { word: 'BUILD', cls: 'build' },
  pivot: { word: 'PIVOT', cls: 'pivot' },
  kill: { word: 'KILL', cls: 'kill' },
  insufficient_evidence: { word: 'NO CALL', cls: 'none' },
};

/** Badge, status line and action for one past idea, from its newest run. */
function pastState(p: Project, now: number): { badge: string; sub?: string; cls: string; meta: string; go: string; live: boolean } {
  const run = p.latest_run;
  if (!run) return { badge: 'NOT RUN', cls: 'idle', meta: `Added ${ago(p.created_at, now)}`, go: 'RUN →', live: false };
  const when = ago(run.finished_at ?? run.created_at, now);
  if (run.verdict) {
    const v = PAST_VERDICT[run.verdict] ?? PAST_VERDICT.insufficient_evidence;
    const conf = run.confidence != null ? ` · ${Math.round(run.confidence * 100)}% confidence` : '';
    const state = run.status === 'awaiting_review' ? 'Verdict ready · review pending' : 'Validated';
    return { badge: v.word, sub: 'VERDICT', cls: v.cls, meta: `${state}${conf} · ${when}`, go: 'OPEN →', live: false };
  }
  if (run.status === 'queued' || run.status === 'running') {
    return { badge: 'LIVE', sub: run.status === 'queued' ? 'STARTING' : 'RESEARCHING', cls: 'live', meta: `Researching now · started ${ago(run.created_at, now)}`, go: 'WATCH →', live: true };
  }
  if (run.status === 'failed') return { badge: 'FAILED', cls: 'failed', meta: `Run failed · ${when} · nothing was lost, retry anytime`, go: 'RETRY →', live: false };
  if (run.status === 'cancelled') return { badge: 'STOPPED', cls: 'idle', meta: `Cancelled · ${when}`, go: 'RUN →', live: false };
  return { badge: 'DONE', cls: 'none', meta: `Finished · ${when}`, go: 'OPEN →', live: false };
}
const TABS = ['01 INTAKE', '02 VERDICT', '03 CALENDAR', '04 BAN RISK'];

/** Transparent 0–100 score from real gate findings: −15 per blocking issue, −5 per warning. */
function gateScore(layers: GateLayer[]): number {
  return Math.max(0, 100 - 15 * blockingFindings(layers).length - 5 * warningFindings(layers).length);
}
function scoreTone(score: number): { bg: string; border: string; fg: string } {
  if (score >= 85) return { bg: 'var(--green-soft)', border: 'var(--green)', fg: 'var(--green)' };
  if (score >= 60) return { bg: 'var(--amber-soft)', border: 'var(--amber)', fg: 'var(--amber)' };
  return { bg: 'var(--red-soft)', border: 'var(--red-ink)', fg: 'var(--red-ink)' };
}

export function Workspace() {
  const [screen, setScreen] = useState<Screen>(0);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);

  const openProject = useCallback(async (id: string) => {
    setProjectId(id);
    setRunId(null);
    setReport(null);
    setPlan(null);
    const runs = await api.listRuns(id); // newest first
    const done = runs.find((r) => r.status === 'succeeded' || r.status === 'awaiting_review');
    if (done) {
      setRunId(done.id);
      setReport(await api.report(done.id));
    }
    const plans = await api.listPlans(id);
    const ready = plans.find((p) => p.status === 'succeeded');
    if (ready) setPlan(await api.plan(ready.id));
    return { done: Boolean(done), latest: runs[0] ?? null };
  }, []);


  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await api.listProjects();
        if (cancelled) return;
        setConnected(true);
        setProjects(page.items);
        if (page.items[0]) await openProject(page.items[0].id);
      } catch (err) {
        setConnected(!(err instanceof TypeError) && !(err instanceof ApiError && err.status >= 500));
      }
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(toastTimer.current);
    };
  }, [openProject]);

  const refreshProjects = useCallback(() => {
    api.listProjects().then((page) => setProjects(page.items)).catch(() => undefined);
  }, []);
  const anyLive = projects.some((p) => p.latest_run?.status === 'queued' || p.latest_run?.status === 'running');
  useEffect(() => {
    if (!anyLive) return;
    const id = setInterval(refreshProjects, 10_000);
    return () => clearInterval(id);
  }, [anyLive, refreshProjects]);

  const enabled = [true, Boolean(report), Boolean(plan), true];

  return (
    <div className="dv-shell">
      <div className="dv-frame">
        <div className="dv-top">
          <a href="/" className="dv-brand">
            <span className="dv-brand-word">deno</span>
            <span className="dv-brand-chip">GTM</span>
          </a>
          <div className="dv-tabs" style={{ flex: 1, justifyContent: 'center', minWidth: 0 }}>
            {TABS.map((label, i) => (
              <button key={label} className={`dv-tab${screen === i ? ' on' : ''}`} disabled={!enabled[i]} onClick={() => setScreen(i as Screen)}>
                {label}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 'none' }}>
            <div className={`dv-status${connected === false ? ' off' : ''}`}>
              <span className="dv-dot" />
              {connected === null ? 'CONNECTING' : connected ? 'CONNECTED' : 'API UNREACHABLE'}
            </div>
            <a href="/app/account" className="dv-tab" style={{ textDecoration: 'none' }}>ACCOUNT</a>
          </div>
        </div>

        {screen === 0 && (
          <IntakeScreen
            projects={projects}
            currentProjectId={projectId}
            onOpenProject={async (id) => {
              const opened = await openProject(id).catch(() => null);
              if (!opened) {
                showToast('Could not load that idea. Check your connection and try again.');
                return { open: false } as const;
              }
              if (opened.done) {
                setScreen(1);
                return { open: false } as const;
              }
              // No finished run: the intake screen shows live progress, or the failure with a retry.
              return { open: true, run: opened.latest } as const;
            }}
            onChanged={refreshProjects}
            onValidated={(pid, rid, r) => {
              refreshProjects();
              setProjectId(pid);
              setRunId(rid);
              setReport(r);
              setPlan(null);
              if (r) setScreen(1);
            }}
          />
        )}
        {screen === 1 && report && (
          <VerdictScreen
            report={report}
            projectId={projectId}
            runId={runId}
            onReport={setReport}
            onPlan={(p) => {
              setPlan(p);
              setScreen(2);
              showToast('Content plan ready. Every draft went through the gates.');
            }}
            onToast={showToast}
          />
        )}
        {screen === 2 && plan && <CalendarScreen plan={plan} onPlan={setPlan} onToast={showToast} />}
        {screen === 3 && <StudioScreen />}
      </div>
      <div className={`toast${toast ? ' show' : ''}`} id="toast">{toast}</div>
    </div>
  );
}

// ---- 01 INTAKE ---------------------------------------------------------------------------------

const STAGES: { label: string; nodes: string[] }[] = [
  { label: 'Idea Intake', nodes: ['intake'] },
  { label: 'Research Planner', nodes: ['perspective_planner', 'query_planner'] },
  { label: 'Source Collectors', nodes: ['collect'] },
  { label: 'Evidence Index', nodes: ['ingest', 'coverage_check'] },
  { label: 'Seven Analysts', nodes: ['analyst'] },
  { label: 'Citation Judge', nodes: ['citation_validator'] },
  { label: 'Critic (adversarial)', nodes: ['signal_scorer', 'critic', 'refiner'] },
  { label: 'Verdict', nodes: ['verdict', 'insufficient', 'account', 'finalize'] },
];
const NODE_TEXT: Record<string, string> = {
  intake: 'reading the idea',
  perspective_planner: 'planning buyer, user, competitor and skeptic angles',
  query_planner: 'writing search queries per source',
  collect: 'collecting public posts',
  ingest: 'indexing the evidence',
  coverage_check: 'checking there is enough evidence to judge',
  analyst: 'analysts reading the evidence',
  citation_validator: 'checking every claim against the post it cites',
  signal_scorer: 'computing signals from the evidence',
  critic: 'skeptic contesting the claims',
  refiner: 'narrowing claims that went too far',
  verdict: 'deciding the verdict',
  insufficient: 'not enough evidence; writing up the gaps',
  finalize: 'saving the report',
};
const SAMPLE_IDEA = 'An automated code review bot that catches race conditions in Go microservices before the PR merges.';

function stageOf(node: string): number {
  const base = node.split(':')[0];
  return STAGES.findIndex((s) => s.nodes.includes(base));
}

function IntakeScreen({
  projects,
  currentProjectId,
  onOpenProject,
  onChanged,
  onValidated,
}: {
  projects: Project[];
  currentProjectId: string | null;
  onOpenProject: (id: string) => Promise<{ open: false } | { open: true; run: Run | null }>;
  /** A run started or ended without a verdict: reload the list so its status is current. */
  onChanged: () => void;
  onValidated: (projectId: string, runId: string, report: Report | null) => void;
}) {
  const [idea, setIdea] = useState('');
  const [handle, setHandle] = useState('');
  const [running, setRunning] = useState(false);
  const [pct, setPct] = useState(0);
  const [stageState, setStageState] = useState<{ status: 'queued' | 'running' | 'done' | 'failed'; started?: number; seconds?: number }[]>(
    () => STAGES.map(() => ({ status: 'queued' })),
  );
  const [log, setLog] = useState('waiting for an idea');
  const [failed, setFailed] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [quiet, setQuiet] = useState(false);
  const [showAll, setShowAll] = useState(false);
  // Set when a past idea without a finished run is opened: "Run validation" re-runs that project.
  const [retryProject, setRetryProject] = useState<{ id: string; idea: string } | null>(null);
  const abort = useRef<AbortController | null>(null);
  // Progress creeps toward this ceiling between events, so a slow stage never looks frozen.
  const cap = useRef(0);
  const lastEvent = useRef(0);

  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => {
      const t = Date.now();
      setNow(t);
      setQuiet(lastEvent.current > 0 && t - lastEvent.current > 45_000);
      setPct((p) => (p < cap.current ? Math.min(cap.current, p + 0.35) : p));
    }, 1000);
    return () => clearInterval(id);
  }, [running]);

  async function openPast(project: Project) {
    if (running) return;
    const opened = await onOpenProject(project.id);
    if (!opened.open) return;
    const { run } = opened;
    setIdea(project.idea);
    setHandle('');
    setRetryProject({ id: project.id, idea: project.idea });
    setStageState(STAGES.map(() => ({ status: 'queued' })));
    if (run && (run.status === 'queued' || run.status === 'running')) {
      setFailed(false);
      setRunning(true);
      setStartedAt(new Date(run.started_at ?? run.created_at).getTime());
      setNow(clockNow());
      setPct(1);
      cap.current = 9;
      lastEvent.current = clockNow();
      setLog('reconnecting to the running validation…');
      void follow(project.id, run.id).finally(() => setRunning(false));
      return;
    }
    setPct(0);
    setStartedAt(null);
    setFailed(Boolean(run && run.status === 'failed'));
    setLog(
      run && run.status === 'failed'
        ? `last run failed (${run.error_code ?? 'error'}) · press Run validation to retry this idea`
        : run && run.status === 'cancelled'
          ? 'last run was cancelled · press Run validation to run it again'
          : 'not validated yet · press Run validation',
    );
  }

  const elapsed = startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0;
  const clock = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;

  async function follow(projectId: string, runId: string): Promise<void> {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    let finished = false;

    // Terminal state, from the stream's status event or (if the connection dropped) from the API.
    const finish = async (status: string, errorCode?: string | null) => {
      if (finished) return;
      finished = true;
      controller.abort();
      if (status === 'failed' || status === 'cancelled') {
        setFailed(true);
        setStageState((s) => s.map((x) => (x.status === 'running' ? { status: 'failed' } : x)));
        setLog(status === 'failed' ? `run failed (${String(errorCode ?? 'error')}) · try again in a minute` : 'cancelled');
        onChanged();
        return;
      }
      setPct(100);
      setStageState((s) => s.map((x) => ({ ...x, status: 'done' })));
      const r = await api.report(runId).catch(() => null);
      onValidated(projectId, runId, r);
    };

    await followEvents(
      `/api/v1/runs/${encodeURIComponent(runId)}/events`,
      (raw) => {
        let ev: StreamEvent;
        try {
          ev = JSON.parse(raw) as StreamEvent;
        } catch {
          return;
        }
        lastEvent.current = clockNow();
        if (ev.type === 'node_started' && ev.node) {
          const k = stageOf(ev.node);
          if (k >= 0) {
            cap.current = Math.max(cap.current, Math.round(((k + 1) / STAGES.length) * 100) - 3);
            setPct((p) => Math.max(p, Math.round((k / STAGES.length) * 100) + 1));
            setStageState((s) => s.map((x, i) => (i === k && x.status === 'queued' ? { status: 'running', started: clockNow() } : x)));
          }
          const [base, detail] = ev.node.split(':');
          setLog(`${NODE_TEXT[base] ?? base}${detail ? ` · ${detail.replace('_', ' ')}` : ''}`);
        } else if (ev.type === 'node_finished' && ev.node) {
          const k = stageOf(ev.node);
          if (k >= 0) {
            setPct((p) => Math.max(p, Math.round(((k + 1) / STAGES.length) * 100) - 2));
            setStageState((s) =>
              s.map((x, i) => (i === k ? { status: 'done', seconds: x.started ? (clockNow() - x.started) / 1000 : Number(ev.seconds ?? 0) } : i < k && x.status !== 'done' ? { ...x, status: 'done' } : x)),
            );
          }
        } else if (ev.type === 'source') {
          setLog(`${ev.source}: ${ev.error === 'blocked_by_policy' ? 'skipped (site disallows bots)' : ev.error ? `partial · ${ev.error}` : `${ev.count} posts`}`);
        } else if (ev.type === 'log' && ev.message) {
          setLog(ev.message);
        } else if (ev.type === 'status' && ev.status && TERMINAL.includes(ev.status)) {
          void finish(ev.status, ev.error_code as string | null | undefined);
        }
      },
      controller.signal,
      async () => TERMINAL.includes((await api.getRun(runId)).status),
    );
    // The connection ended without a status event (dropped, then the run finished): read it from the API.
    if (!finished && abort.current === controller) {
      const run = await api.getRun(runId).catch(() => null);
      if (run && TERMINAL.includes(run.status)) await finish(run.status, run.error_code);
    }
  }

  async function start() {
    const text = idea.trim();
    if (text.length < 5) return;
    setRunning(true);
    setFailed(false);
    setStartedAt(clockNow());
    setNow(clockNow());
    setPct(1);
    cap.current = 4;
    lastEvent.current = 0;
    setStageState(STAGES.map(() => ({ status: 'queued' })));
    setLog('saving your idea…');
    try {
      const reuse = retryProject && retryProject.idea.trim() === text ? retryProject.id : null;
      const project = reuse ? { id: reuse } : await api.createProject(text, handle.trim() || null);
      setRetryProject(null);
      setLog('request received · starting a research worker (the first one can take ~30–60 s)…');
      setPct((p) => Math.max(p, 3));
      cap.current = 9;
      const run = await api.startRun(project.id);
      onChanged();
      lastEvent.current = clockNow();
      await follow(project.id, run.run_id);
    } catch (err) {
      setFailed(true);
      setLog(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="dv-split wide dv-fade">
      <div className="dv-pad lg dv-rr" style={{ padding: 'clamp(22px,3vw,44px)' }}>
        <span className="dv-kicker">STAGE 1 · EVIDENCE-GROUNDED VALIDATION</span>
        <h1 className="dv-h1" style={{ fontSize: 'clamp(32px,3.8vw,52px)', margin: '20px 0 14px' }}>One input. A verdict you can defend.</h1>
        <p className="dv-lede" style={{ marginBottom: 26, maxWidth: 440 }}>
          Describe the idea. Agents read what real people post on Reddit, Hacker News, X and Product Hunt, then every claim is checked against the post it cites. No invented numbers.
        </p>

        <div style={{ border: '1.5px solid var(--ink)', background: 'var(--paper)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '11px 14px', borderBottom: '1.5px solid var(--ink)', background: 'var(--paper-2)' }}>
            <label htmlFor="idea-input" className="dv-label" style={{ margin: 0 }}>YOUR IDEA</label>
            <button className="dv-link" style={{ fontWeight: 400, color: 'var(--muted)', borderColor: 'var(--muted)', fontSize: 10.5 }} onClick={() => setIdea(SAMPLE_IDEA)}>load sample</button>
          </div>
          <textarea
            id="idea-input"
            rows={5}
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            placeholder="Describe the problem, who has it, and what you'd build."
            style={{ width: '100%', border: 0, background: 'transparent', padding: '16px 14px', fontFamily: 'var(--sans)', fontSize: 15, lineHeight: 1.6, minHeight: 132, resize: 'vertical', color: 'var(--ink)', outline: 'none' }}
          />
          <div style={{ display: 'flex', alignItems: 'stretch', borderTop: '1.5px solid var(--ink)', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 200, padding: '12px 14px', borderRight: '1.5px solid var(--ink)', display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span className="dv-mono dv-muted" style={{ fontSize: 9.5, letterSpacing: '.08em' }}>OPTIONAL · YOUR PUBLIC HANDLE</span>
              <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="u/yourhandle" style={{ border: 0, background: 'transparent', fontSize: 14, color: 'var(--ink)', outline: 'none', padding: 0 }} />
            </div>
            <button
              onClick={start}
              disabled={running || idea.trim().length < 5}
              style={{ flex: 'none', background: 'var(--lime)', border: 0, fontFamily: 'var(--sans)', fontSize: 15, fontWeight: 700, padding: '14px 24px', cursor: running ? 'wait' : 'pointer', color: 'var(--ink)', opacity: idea.trim().length < 5 ? 0.55 : 1 }}
            >
              {running ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
                  <span className="dv-orb ink" aria-hidden />
                  Researching… <span className="dv-mono" style={{ fontSize: 12, fontWeight: 400 }}>{clock}</span>
                </span>
              ) : (
                'Run validation →'
              )}
            </button>
          </div>
        </div>

        <div style={{ marginTop: 16, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <span className="dv-note">~3–6 MIN RUNTIME</span>
          <span className="dv-note">SOURCES REQUIRED</span>
          <span className="dv-note">UNSOURCED CLAIMS DROPPED</span>
        </div>

        {projects.length > 0 && (
          <section style={{ marginTop: 32 }} aria-labelledby="past-heading">
            <div className="dv-past-head">
              <span id="past-heading" className="dv-label" style={{ margin: 0 }}>YOUR VALIDATIONS</span>
              <span className="dv-mono dv-muted" style={{ fontSize: 10.5 }}>
                {projects.length} {projects.length === 1 ? 'IDEA' : 'IDEAS'}
              </span>
            </div>
            <div className="dv-past">
              {(showAll ? projects : projects.slice(0, PAST_LIMIT)).map((p) => {
                const st = pastState(p, now);
                return (
                  <button
                    key={p.id}
                    className={`dv-past-item${p.id === currentProjectId ? ' on' : ''}`}
                    onClick={() => void openPast(p)}
                    disabled={running}
                    title={p.idea}
                  >
                    <span className={`dv-past-badge ${st.cls}`}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        {st.live && <span className="dv-orb" aria-hidden />}
                        {st.badge}
                      </span>
                      {st.sub && <small>{st.sub}</small>}
                    </span>
                    <span className="dv-past-body">
                      <span className="dv-past-title">{p.title}</span>
                      <span className="dv-past-meta">{st.meta}</span>
                    </span>
                    <span className="dv-past-go" aria-hidden>{st.go}</span>
                  </button>
                );
              })}
              {projects.length > PAST_LIMIT && (
                <button className="dv-past-more" onClick={() => setShowAll((v) => !v)}>
                  {showAll ? 'SHOW LESS ↑' : `SHOW ALL ${projects.length} ↓`}
                </button>
              )}
            </div>
          </section>
        )}
      </div>

      <div className="dv-dark" style={{ padding: 'clamp(22px,3vw,44px)' }}>
        <div className="dv-grid-bg" />
        <div className="dv-inner">
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, marginBottom: 6 }}>
            <span className="dv-dark-label" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              {running && <span className="dv-orb" aria-hidden />}
              RESEARCH GRAPH · {running ? `LIVE · ${clock}` : failed ? 'FAILED' : pct === 100 ? 'DONE' : 'IDLE'}
            </span>
            <span className="dv-serif" style={{ fontSize: 32, lineHeight: 1 }}>{Math.round(pct)}%</span>
          </div>
          <div style={{ height: 8, background: 'rgba(250,248,243,.14)', marginBottom: 10 }}>
            <div
              className={running ? 'dv-shimmer' : undefined}
              style={{ height: '100%', width: `${pct}%`, background: failed ? 'var(--red)' : 'var(--lime)', transition: 'width 1s linear' }}
            />
          </div>
          <p className="dv-mono dv-dim" role="status" aria-live="polite" style={{ margin: '0 0 22px', fontSize: 11.5 }}>
            {log}
            {running && quiet && ' · still working, the AI queue is slow right now'}
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {STAGES.map((stage, i) => {
              const st = stageState[i];
              const cls = st.status === 'done' ? 'done' : st.status === 'running' ? 'now' : st.status === 'failed' ? 'bad' : 'wait';
              const stageSecs = st.status === 'running' && st.started ? Math.max(0, Math.floor((now - st.started) / 1000)) : 0;
              return (
                <div key={stage.label} className={`dv-row ${cls}`}>
                  <span className="dv-mono" style={{ fontSize: 10.5, flex: 'none', color: st.status === 'done' ? 'var(--lime)' : undefined }}>
                    {String(i + 1).padStart(2, '0')}{' '}
                    {st.status === 'done' ? '✓' : st.status === 'running' ? <span className="dv-spin">⟳</span> : st.status === 'failed' ? '✕' : '·'}
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>{stage.label}</span>
                  <span className="dv-mono" style={{ fontSize: 10.5, color: st.status === 'running' ? undefined : '#9AA5A0' }}>
                    {st.status === 'done' ? (st.seconds ? `${st.seconds.toFixed(1)}s` : 'done') : st.status === 'running' ? `running · ${stageSecs}s` : st.status === 'failed' ? 'failed' : 'queued'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- 02 VERDICT --------------------------------------------------------------------------------

const VERDICT_WORD: Record<string, string> = { build: 'BUILD', pivot: 'PIVOT', kill: 'KILL', insufficient_evidence: 'NO CALL' };
const VERDICT_BG: Record<string, string> = { build: 'var(--lime)', pivot: 'var(--amber-soft)', kill: 'var(--red-soft)', insufficient_evidence: 'var(--paper-2)' };

function firstCite(c: Claim) {
  return c.citations.find((x) => x.verified) ?? c.citations[0];
}

function VerdictScreen({
  report,
  projectId,
  runId,
  onReport,
  onPlan,
  onToast,
}: {
  report: Report;
  projectId: string | null;
  runId: string | null;
  onReport: (r: Report) => void;
  onPlan: (p: Plan) => void;
  onToast: (m: string) => void;
}) {
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState('');
  const [flagged, setFlagged] = useState<Set<string>>(() => new Set());
  const [radar, setRadar] = useState<Community[] | null>(null);
  const v = report.verdict;
  const verified = report.claims.filter((c) => !c.dropped && c.citations.some((x) => x.verified));
  const dropped = report.claims.filter((c) => c.dropped);
  const supporting = verified.filter((c) => c.stance === 'supports');
  const objection = verified.find((c) => c.stance === 'refutes');
  const labels = useMemo(
    () => new Map(Object.entries((v?.coverage?.claim_refs as Record<string, string> | undefined) ?? {}).map(([k, id]) => [id, k])),
    [v],
  );
  const bySource = v?.coverage?.by_source ?? {};

  async function toggleRadar() {
    if (radar) return setRadar(null);
    if (!runId) return;
    setRadar(await api.runCommunities(runId).catch(() => []));
  }

  async function generate() {
    if (!projectId) return;
    setGenerating(true);
    setProgress('Planning posts…');
    try {
      if (runId && report.run.status === 'awaiting_review') {
        await api.resume(runId, [...flagged]);
        onReport(await api.report(runId));
      }
      const created = await api.createPlan(projectId, 14, runId);
      const controller = new AbortController();
      let drafted = 0;
      const finished = async () => ['succeeded', 'failed', 'cancelled'].includes((await api.plan(created.plan_id)).status);
      await followEvents(
        created.events_url,
        (raw) => {
          let ev: StreamEvent;
          try {
            ev = JSON.parse(raw) as StreamEvent;
          } catch {
            return;
          }
          if (ev.type === 'log' && ev.message) setProgress(ev.message);
          if (ev.type === 'node_finished' && ev.node === 'brief_planner') setProgress(`${String(ev.briefs)} posts planned · writing and gating drafts…`);
          if (ev.type === 'node_finished' && ev.node === 'draft') setProgress(`${++drafted} drafts written and gated…`);
          if (ev.type === 'status' && (ev.status === 'succeeded' || ev.status === 'failed' || ev.status === 'cancelled')) controller.abort();
        },
        controller.signal,
        finished,
      );
      // Open the calendar only once the plan has really finished (never a half-written plan).
      const plan = await api.plan(created.plan_id);
      if (plan.status !== 'succeeded') throw new Error('The content plan failed. Try again in a minute.');
      onPlan(plan);
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
      setProgress('');
    }
  }

  const box = (label: string, value: number | null, bg: string, fg: string) => (
    <div style={{ border: '1.5px solid var(--ink)', background: bg, padding: '14px 12px' }}>
      <div className="dv-mono" style={{ fontSize: 10, letterSpacing: '.1em', color: fg, marginBottom: 6 }}>{label}</div>
      <div className="dv-serif" style={{ fontSize: 'clamp(22px,2.4vw,30px)', lineHeight: 1 }}>{value === null ? '—' : Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2)}</div>
    </div>
  );

  return (
    <div className="dv-fade">
      <div className="dv-split dv-rb">
        <div className="dv-pad dv-rr" style={{ background: VERDICT_BG[v?.verdict ?? 'insufficient_evidence'] }}>
          <span className="dv-kicker ink">VERDICT · STAGE 1 COMPLETE</span>
          <div className="dv-serif" style={{ fontSize: 'clamp(56px,8vw,110px)', lineHeight: 0.9, letterSpacing: '-.03em', margin: '18px 0 10px' }}>{VERDICT_WORD[v?.verdict ?? 'insufficient_evidence']}</div>
          <p style={{ margin: 0, fontSize: 'clamp(15px,1.3vw,18px)', lineHeight: 1.45, fontWeight: 600, maxWidth: 520 }}>{v?.rationale ?? 'No verdict was recorded for this run.'}</p>
        </div>
        <div className="dv-pad" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 14 }}>
            <span className="dv-serif" style={{ fontSize: 'clamp(48px,6vw,76px)', lineHeight: 0.9, color: 'var(--green)' }}>{v ? `${Math.round(v.confidence * 100)}%` : '—'}</span>
            <span className="dv-mono dv-muted" style={{ fontSize: 10.5, letterSpacing: '.08em', paddingBottom: 8 }}>EVIDENCE<br />CONFIDENCE</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 10 }}>
            {box('POSTS', signal(report, 'mention_volume'), 'var(--green-soft)', 'var(--green)')}
            {box('PAY TALK', signal(report, 'wtp_phrase_count'), 'var(--blue-soft)', 'var(--blue)')}
            {box('RIVALS', signal(report, 'competitor_mentions'), 'var(--amber-soft)', 'var(--amber)')}
          </div>
          <p className="dv-mono dv-muted" style={{ margin: 0, fontSize: 11, lineHeight: 1.7 }}>
            COUNTED, NOT ESTIMATED · {Object.entries(bySource).map(([s, n]) => `${s} ${n}`).join(' · ') || 'no sources'}
          </p>
        </div>
      </div>

      <div className="dv-split">
        <div className="dv-pad dv-rr">
          <div className="dv-serif" style={{ fontSize: 26, marginBottom: 18 }}>Why this verdict</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {(v?.reasons ?? []).map((reason, i) => (
              <div key={reason} style={{ display: 'flex', gap: 14, borderBottom: '1px solid rgba(16,22,19,.14)', paddingBottom: 12 }}>
                <span className="dv-serif" style={{ fontSize: 26, lineHeight: 1, color: 'var(--green)', flex: 'none' }}>{String(i + 1).padStart(2, '0')}</span>
                <span style={{ fontSize: 14.5, lineHeight: 1.55, minWidth: 0 }}>{reason}</span>
              </div>
            ))}
            {supporting.slice(0, 3).map((c) => (
              <div key={c.id} style={{ display: 'flex', gap: 14, borderBottom: '1px solid rgba(16,22,19,.14)', paddingBottom: 12 }}>
                <span className="dv-mono" style={{ fontSize: 11, color: 'var(--green)', flex: 'none', paddingTop: 3 }}>{labels.get(c.id) ?? '•'}</span>
                <span style={{ fontSize: 14.5, lineHeight: 1.55, minWidth: 0 }}>{c.text}</span>
              </div>
            ))}
          </div>
          {objection && (
            <div style={{ marginTop: 22, border: '1.5px solid var(--red)', background: 'var(--red-soft)', padding: 16 }}>
              <div className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.1em', color: 'var(--red-ink)', marginBottom: 8 }}>
                CRITIC&apos;S STANDING OBJECTION {labels.get(objection.id) ? `· ${labels.get(objection.id)}` : ''}
              </div>
              <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55, color: '#3A2A22' }}>{objection.text}</p>
            </div>
          )}
          {v?.verdict === 'insufficient_evidence' && (v.coverage.gaps ?? []).length > 0 && (
            <div style={{ marginTop: 22, border: '1.5px solid var(--ink)', background: 'var(--paper-2)', padding: 16 }}>
              <div className="dv-label">WHAT&apos;S MISSING</div>
              {(v.coverage.gaps ?? []).map((g) => <p key={g} style={{ margin: '4px 0', fontSize: 14 }}>{g}</p>)}
            </div>
          )}
        </div>
        <div className="dv-pad dv-soft">
          <div className="dv-serif" style={{ fontSize: 26, marginBottom: 6 }}>Source ledger</div>
          <p className="dv-mono dv-muted" style={{ margin: '0 0 18px', fontSize: 10.5 }}>{verified.length} CLAIMS SOURCED · {dropped.length} DROPPED AS UNVERIFIABLE</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 560, overflowY: 'auto' }}>
            {verified.map((c) => {
              const cite = firstCite(c);
              return (
                <div key={c.id} style={{ border: '1px solid rgba(16,22,19,.2)', background: 'var(--paper)', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 5 }}>
                  <span style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.4 }}>{labels.get(c.id) ? `${labels.get(c.id)} · ` : ''}{c.text}</span>
                  <a href={safeHref(cite?.document.url)} target="_blank" rel="noopener noreferrer" className="dv-mono" style={{ fontSize: 10.5, color: 'var(--blue)', wordBreak: 'break-all', textDecoration: 'none' }}>
                    {cite?.document.community ?? cite?.document.source} · {cite?.document.published_at ? `posted ${new Date(cite.document.published_at).toLocaleDateString()}` : 'undated'} ↗
                  </a>
                  {report.run.status === 'awaiting_review' && (
                    <button
                      className="dv-link"
                      style={{ alignSelf: 'flex-start', fontWeight: 400, color: flagged.has(c.id) ? 'var(--red-ink)' : 'var(--muted)', borderColor: 'currentColor', fontSize: 10 }}
                      onClick={() => setFlagged((f) => { const n = new Set(f); if (n.has(c.id)) n.delete(c.id); else n.add(c.id); return n; })}
                    >
                      {flagged.has(c.id) ? '✓ flagged as wrong' : 'flag as wrong'}
                    </button>
                  )}
                </div>
              );
            })}
            {dropped.slice(0, 6).map((c) => (
              <div key={c.id} style={{ border: '1px dashed rgba(16,22,19,.35)', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 5 }}>
                <span style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.4, color: 'var(--muted)' }}>“{c.text}”</span>
                <span className="dv-mono" style={{ fontSize: 10.5, color: 'var(--red-ink)' }}>DROPPED · the cited post didn&apos;t support it</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 22, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            <button className="dv-btn ink" disabled={generating || !projectId} onClick={generate}>{generating ? progress || 'Writing drafts…' : 'Generate 14-day plan →'}</button>
            <button className="dv-btn ghost" onClick={toggleRadar}>{radar ? 'Hide community radar' : 'Community radar'}</button>
          </div>
        </div>
      </div>

      {radar && (
        <div className="dv-pad dv-rise" style={{ borderTop: '1.5px solid var(--ink)' }}>
          <div className="dv-serif" style={{ fontSize: 26, marginBottom: 14 }}>Community radar</div>
          {radar.length === 0 && <p className="dv-muted">No communities recorded for this run.</p>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 10 }}>
            {radar.map((c) => (
              <div key={c.id} className="dv-card" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <a href={safeHref(c.url ?? `https://www.reddit.com/${c.name}/`)} target="_blank" rel="noopener noreferrer" style={{ fontWeight: 700 }}>{c.name}</a>
                  <span className="dv-mono dv-muted" style={{ fontSize: 10.5 }}>{c.evidence_count ?? 0} POSTS</span>
                </div>
                <span style={{ fontSize: 13 }}><b>Self-promo:</b> {c.promo_policy ?? 'not on file, read the sidebar'}</span>
                <span style={{ fontSize: 13 }}><b>Cadence:</b> {c.cadence ?? 'not on file'}</span>
                <span style={{ fontSize: 13, color: 'var(--red-ink)' }}><b>AI rule:</b> {c.ai_policy ?? 'unknown; assume AI posts get removed'}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- 03 CALENDAR -------------------------------------------------------------------------------

const PLATFORM_LINKS: Record<string, string> = {
  reddit: 'https://www.reddit.com/submit',
  linkedin: 'https://www.linkedin.com/feed/',
  x: 'https://x.com/compose/post',
};

function CalendarScreen({ plan, onPlan, onToast }: { plan: Plan; onPlan: (p: Plan) => void; onToast: (m: string) => void }) {
  const briefs = plan.briefs.filter((b) => b.draft);
  const [selected, setSelected] = useState(0);
  const [content, setContent] = useState(briefs[0]?.draft?.text ?? '');
  const [layers, setLayers] = useState<GateLayer[]>(briefs[0]?.draft?.gates ?? []);
  const [dirty, setDirty] = useState(false);
  const debounce = useRef<number | undefined>(undefined);
  const brief: Brief | undefined = briefs[selected];

  function load(i: number) {
    setSelected(i);
    setDirty(false);
    setContent(briefs[i]?.draft?.text ?? '');
    setLayers(briefs[i]?.draft?.gates ?? []);
  }

  function onChange(text: string) {
    setContent(text);
    setDirty(true);
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => {
      api.audit(text, brief?.platform === 'reddit' ? 'reddit' : 'linkedin', brief?.community).then((a) => setLayers(a.layers)).catch(() => undefined);
    }, 400);
  }

  async function refresh() {
    onPlan(await api.plan(plan.id));
  }

  async function approve() {
    if (!brief?.draft) return;
    try {
      const id = dirty ? (await api.editDraft(brief.draft.id, content)).id : brief.draft.id;
      setDirty(false);
      await api.approveDraft(id);
      await refresh();
      onToast('Approved. Copy it and post it yourself when you are ready.');
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function save() {
    if (!brief?.draft) return;
    try {
      const d = await api.editDraft(brief.draft.id, content);
      setLayers(d.gates);
      setDirty(false);
      await refresh();
      onToast(d.status === 'gated' ? 'Saved. Passes every gate.' : 'Saved. Some gates still flag it.');
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    }
  }

  const blocking = blockingFindings(layers);
  const warnings = warningFindings(layers);
  const score = gateScore(layers);
  const tone = scoreTone(score);
  const promoDay = briefs.find((b) => b.is_promotional)?.day;

  return (
    <div className="dv-split dv-fade" style={{ gridTemplateColumns: 'minmax(280px,1fr) minmax(0,2fr)' }}>
      <div className="dv-rr" style={{ minWidth: 0 }}>
        <div style={{ padding: '18px clamp(14px,2vw,22px)', borderBottom: '1.5px solid var(--ink)', background: 'var(--paper-2)' }}>
          <div className="dv-serif" style={{ fontSize: 24, lineHeight: 1.1 }}>{plan.days}-day plan</div>
          <p className="dv-mono dv-muted" style={{ margin: '6px 0 0', fontSize: 10.5 }}>≤1 PROMO IN 10 · COMMUNITY CADENCE RESPECTED</p>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', maxHeight: 720, overflowY: 'auto' }}>
          {briefs.map((b, i) => {
            const s = gateScore(b.draft?.gates ?? []);
            const t = scoreTone(s);
            return (
              <div
                key={b.id}
                onClick={() => load(i)}
                style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '15px clamp(14px,2vw,22px)', borderBottom: '1px solid rgba(16,22,19,.14)', cursor: 'pointer', background: i === selected ? 'var(--lime)' : 'transparent' }}
              >
                <span className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, flex: 'none', paddingTop: 2 }}>D{String(b.day).padStart(2, '0')}</span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'block', fontSize: 14, fontWeight: 600, lineHeight: 1.35 }}>{b.angle}</span>
                  <span className="dv-mono dv-muted" style={{ display: 'block', fontSize: 10, marginTop: 4 }}>
                    {b.community ?? b.platform.toUpperCase()} · {b.draft?.status.toUpperCase()}{b.is_promotional ? ' · PROMO' : ''}
                  </span>
                </span>
                <span className="dv-mono" style={{ fontSize: 11, fontWeight: 700, background: t.bg, border: `1px solid ${t.border}`, color: t.fg, padding: '3px 6px', flex: 'none' }}>{s}</span>
              </div>
            );
          })}
          <div className="dv-mono dv-muted" style={{ padding: '18px clamp(14px,2vw,22px)', background: 'var(--paper-2)', fontSize: 10.5, lineHeight: 1.7 }}>
            {briefs.length} DRAFTS · {promoDay ? `PROMO POST: DAY ${promoDay}` : 'NO PROMO POSTS IN THIS PLAN'}
          </div>
        </div>
      </div>

      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', padding: '16px clamp(14px,2vw,22px)', borderBottom: '1.5px solid var(--ink)' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="dv-pill solid">{brief?.platform.toUpperCase()}</span>
            <span className="dv-pill">{brief?.community ?? 'Personal feed'}</span>
            <span className="dv-mono dv-muted" style={{ fontSize: 10.5 }}>HOOK {brief?.hook_formula ?? '—'} · DAY {brief?.day} · {brief?.draft?.status.toUpperCase()}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, border: '1.5px solid var(--ink)', padding: '6px 10px', background: tone.bg }}>
            <span className="dv-serif" style={{ fontSize: 28, lineHeight: 1 }}>{score}</span>
            <span className="dv-mono" style={{ fontSize: 9.5, letterSpacing: '.08em' }}>BAN RISK<br />SCORE</span>
          </div>
        </div>

        <div style={{ padding: 'clamp(18px,2.4vw,28px) clamp(14px,2vw,22px)', borderBottom: '1.5px solid var(--ink)' }}>
          <div className="dv-label" style={{ color: 'var(--muted)', marginBottom: 12 }}>POST COPY · EDITABLE</div>
          <textarea
            value={content}
            onChange={(e) => onChange(e.target.value)}
            rows={12}
            style={{ width: '100%', border: 0, background: 'transparent', fontFamily: 'var(--sans)', fontSize: 14.5, lineHeight: 1.65, color: 'var(--ink-2)', resize: 'vertical', outline: 'none', padding: 0 }}
          />
        </div>

        <div style={{ padding: 'clamp(18px,2.4vw,28px) clamp(14px,2vw,22px)', background: 'var(--paper-2)', borderBottom: '1.5px solid var(--ink)' }}>
          <div className="dv-label" style={{ marginBottom: 12 }}>LIVE DEDUCTION BREAKDOWN</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {blocking.length === 0 && warnings.length === 0 && (
              <div style={{ display: 'flex', gap: 10, background: 'var(--paper)', border: '1px solid rgba(16,22,19,.18)', padding: '11px 13px' }}>
                <span className="dv-mono" style={{ fontSize: 11, fontWeight: 700, color: 'var(--green)' }}>PASS</span>
                <span style={{ fontSize: 13 }}>No AI-writing patterns, unsourced numbers, invented stories or rule conflicts found.</span>
              </div>
            )}
            {[...blocking, ...warnings].map((f, i) => (
              <div key={`${f.rule_id}-${i}`} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', background: 'var(--paper)', border: '1px solid rgba(16,22,19,.18)', padding: '11px 13px' }}>
                <span className="dv-mono" style={{ fontSize: 11, fontWeight: 700, flex: 'none', color: f.severity === 'block' ? 'var(--red-ink)' : 'var(--amber)' }}>{f.severity === 'block' ? '−15' : '−5'}</span>
                <span style={{ fontSize: 13, lineHeight: 1.45, minWidth: 0 }}>
                  {f.message}{f.quote ? `: “${f.quote}”` : ''} <span className="dv-muted">→ {f.fix}</span>
                </span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 'auto', padding: '14px clamp(14px,2vw,22px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <span className="dv-mono dv-muted" style={{ fontSize: 10.5 }}>🔒 DENO NEVER POSTS. YOU PRESS SEND.</span>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {dirty && <button className="dv-btn ghost sm" onClick={save}>Save &amp; re-check</button>}
            {brief?.draft?.status !== 'approved' && brief?.draft?.status !== 'exported' && (
              <button className="dv-btn ghost sm" disabled={blocking.length > 0} onClick={approve}>✓ Approve</button>
            )}
            <button
              className="dv-btn ghost sm"
              onClick={() => {
                void navigator.clipboard.writeText(content);
                if (brief?.draft && brief.draft.status === 'approved') void api.exportDraft(brief.draft.id).then(refresh).catch(() => undefined);
                onToast('Post copied. You are ready to publish.');
              }}
            >
              Copy post
            </button>
            <a href={PLATFORM_LINKS[brief?.platform ?? 'reddit'] ?? PLATFORM_LINKS.reddit} target="_blank" rel="noopener noreferrer" className="dv-btn lime sm" style={{ boxShadow: 'none' }}>Open platform ↗</a>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- 04 BAN RISK -------------------------------------------------------------------------------

function StudioScreen() {
  const [platform, setPlatform] = useState<GatePlatform>('reddit');
  const [text, setText] = useState('');
  const [audit, setAudit] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [edit, setEdit] = useState<StudioEdit | null>(null);
  const [editing, setEditing] = useState(false);
  // A suggestion belongs to the exact text and platform it was made for: typing or switching platform
  // drops it (and any answer still on its way), so "Use this version" can't overwrite newer writing.
  const editSeq = useRef(0);
  const community = platform === 'reddit' ? 'r/SaaS' : null;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const sentences = text.split(/[.!?]+(\s|$)/).filter((s) => s && s.trim()).length;

  async function run(value = text) {
    if (!value.trim()) return;
    try {
      setAudit(await api.audit(value.trim(), platform, community));
      dropEdit();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function dropEdit() {
    editSeq.current += 1;
    setEdit(null);
    setEditing(false);
  }

  async function fixForMe() {
    const seq = ++editSeq.current;
    setEditing(true);
    try {
      const result = await api.studioEdit(text.trim(), platform, community);
      if (seq !== editSeq.current) return;
      setEdit(result);
      setError(null);
    } catch (err) {
      if (seq === editSeq.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (seq === editSeq.current) setEditing(false);
    }
  }

  function acceptEdit(e: StudioEdit) {
    setText(e.edited);
    // The edit was already re-checked by every gate: show that result without spending another audit.
    setAudit({ passed: e.passed, layers: e.layers, autofixed: e.edited });
    dropEdit();
  }

  const blocking = audit ? blockingFindings(audit.layers) : [];
  const warnings = audit ? warningFindings(audit.layers) : [];
  const score = audit ? gateScore(audit.layers) : null;
  const canFix = audit && audit.autofixed.trim() && audit.autofixed.trim() !== text.trim();

  return (
    <div className="dv-split wide dv-fade">
      <div className="dv-pad dv-rr">
        <span className="dv-kicker red">PLAYGROUND</span>
        <h1 className="dv-h1" style={{ margin: '18px 0 12px' }}>Ban Risk &amp; Anti-Slop Studio</h1>
        <p className="dv-lede" style={{ fontSize: 14.5, marginBottom: 24, maxWidth: 420 }}>
          Paste anything, a draft we wrote or one you did. Twenty structural patterns, vagueness and rhythm checks, your voice, and the target community&apos;s rules.
        </p>
        <div style={{ border: '1.5px solid var(--ink)', marginBottom: 14 }}>
          <div className="dv-label" style={{ margin: 0, padding: '11px 14px', borderBottom: '1.5px solid var(--ink)', background: 'var(--paper-2)' }}>TARGET PLATFORM</div>
          <div style={{ padding: '12px 14px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {(['reddit', 'linkedin', 'x'] as GatePlatform[]).map((p) => (
              <button
                key={p}
                className={`dv-tab${platform === p ? ' on' : ''}`}
                style={{ padding: '7px 11px' }}
                onClick={() => {
                  if (p !== platform) dropEdit();
                  setPlatform(p);
                }}
              >
                {p.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <div style={{ border: '1.5px solid var(--ink)' }}>
          <div className="dv-label" style={{ margin: 0, padding: '11px 14px', borderBottom: '1.5px solid var(--ink)', background: 'var(--paper-2)' }}>DRAFT TO AUDIT</div>
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (edit || editing) dropEdit();
            }}
            rows={9}
            placeholder="Paste a post to see exactly what gets flagged and how to fix it..."
            style={{ width: '100%', border: 0, background: 'transparent', padding: '16px 14px', fontFamily: 'var(--sans)', fontSize: 14.5, lineHeight: 1.65, minHeight: 200, color: 'var(--ink-2)', resize: 'vertical', outline: 'none' }}
          />
          <div style={{ borderTop: '1.5px solid var(--ink)', display: 'flex', flexWrap: 'wrap' }}>
            <div className="dv-mono dv-muted" style={{ flex: 1, minWidth: 160, padding: '12px 14px', borderRight: '1.5px solid var(--ink)', fontSize: 10.5 }}>{words} WORDS · {sentences} SENTENCES</div>
            <button onClick={() => run()} disabled={!text.trim()} style={{ flex: 'none', background: 'var(--ink)', color: 'var(--paper)', border: 0, fontFamily: 'var(--sans)', fontSize: 14.5, fontWeight: 700, padding: '13px 22px', cursor: 'pointer' }}>Run audit</button>
          </div>
        </div>
      </div>

      <div className="dv-dark">
        <div className="dv-grid-bg" />
        <div className="dv-inner" style={{ padding: 'clamp(22px,3vw,40px)' }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 16, paddingBottom: 20, borderBottom: '1px solid rgba(250,248,243,.2)', marginBottom: 20, flexWrap: 'wrap' }}>
            <span className="dv-serif" style={{ fontSize: 'clamp(64px,9vw,120px)', lineHeight: 0.85, color: score === null ? '#9AA5A0' : score >= 85 ? 'var(--lime)' : score >= 60 ? '#FBF1C7' : '#FF6B4A' }}>{score ?? '--'}</span>
            <div style={{ paddingBottom: 10 }}>
              <div className="dv-mono dv-dim" style={{ fontSize: 10.5, letterSpacing: '.1em', marginBottom: 6 }}>BAN RISK SCORE · 0–100 · HIGHER IS SAFER</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: score === null ? 'var(--paper)' : audit?.passed ? 'var(--lime)' : '#FF8A6E' }}>
                {error ?? (score === null ? 'Paste a draft and run the audit.' : audit?.passed ? 'Safe to send. Passes every gate.' : 'Do not send yet. Fix the flagged lines.')}
              </div>
            </div>
          </div>
          {audit && (
            <>
              <div className="dv-dark-label" style={{ marginBottom: 12 }}>{blocking.length + warnings.length} FINDINGS · EACH WITH A FIX</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {[...blocking, ...warnings].map((f, i) => (
                  <div key={`${f.rule_id}-${i}`} className={`dv-row ${f.severity === 'block' ? 'bad' : 'warn'}`} style={{ alignItems: 'flex-start' }}>
                    <span className="dv-mono" style={{ fontSize: 11.5, fontWeight: 700, color: f.severity === 'block' ? '#FF8A6E' : '#FBF1C7', flex: 'none' }}>{f.severity === 'block' ? '−15' : '−5'}</span>
                    <span style={{ lineHeight: 1.5, minWidth: 0 }}>
                      {f.message}{f.quote ? `: “${f.quote}”` : ''} <span className="dv-dim">→ {f.fix}</span>
                    </span>
                  </div>
                ))}
              </div>
              {canFix && (
                <button
                  className="dv-btn lime"
                  style={{ marginTop: 20, width: '100%', boxShadow: 'none', borderColor: 'var(--lime)' }}
                  onClick={() => {
                    setText(audit.autofixed);
                    void run(audit.autofixed);
                  }}
                >
                  Apply safe mechanical fixes → rescore
                </button>
              )}
              {(blocking.length > 0 || warnings.length > 0) && !edit && (
                <button
                  className="dv-btn ghost"
                  style={{ marginTop: 10, width: '100%', boxShadow: 'none', color: 'var(--paper)', borderColor: 'rgba(250,248,243,.5)' }}
                  disabled={editing}
                  onClick={() => void fixForMe()}
                >
                  {editing ? 'Editing in your voice…' : 'Fix it for me → keeps your voice, lists every change'}
                </button>
              )}
              {edit && (
                <section aria-label="Suggested edit" style={{ marginTop: 20, border: '1px solid rgba(250,248,243,.3)', padding: 16 }}>
                  <div className="dv-dark-label" style={{ marginBottom: 10 }}>
                    SUGGESTED EDIT · {edit.passed ? 'PASSES EVERY GATE' : `${blockingFindings(edit.layers).length} ISSUES LEFT`}
                  </div>
                  <p style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6, margin: '0 0 14px' }}>{edit.edited}</p>
                  <div className="dv-dark-label" style={{ marginBottom: 8 }}>WHAT CHANGED</div>
                  <ul style={{ margin: '0 0 14px', paddingLeft: 18, lineHeight: 1.55 }}>
                    {edit.changes.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                  {!edit.passed && (
                    <ul className="dv-dim" style={{ margin: '0 0 14px', paddingLeft: 18, lineHeight: 1.5 }}>
                      {blockingFindings(edit.layers).map((f, i) => (
                        <li key={`${f.rule_id}-${i}`}>
                          {f.message}{f.quote ? `: “${f.quote}”` : ''} → {f.fix}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <button className="dv-btn lime sm" style={{ boxShadow: 'none' }} onClick={() => acceptEdit(edit)}>Use this version</button>
                    <button className="dv-btn ghost sm" style={{ color: 'var(--paper)', borderColor: 'rgba(250,248,243,.5)' }} onClick={dropEdit}>Keep mine</button>
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
