'use client';

import { useEffect, useRef, useState } from 'react';
import { api, streamEvents, TERMINAL, type Project, type Report, type StreamEvent } from '@/lib/api';
import { paneClass } from './paneClass';

// The real graph, in the order its nodes run.
const STAGES: { id: string; label: string; nodes: string[] }[] = [
  { id: 'chip-intake', label: '1. Idea Intake', nodes: ['intake'] },
  { id: 'chip-market', label: '2. Research Planner', nodes: ['perspective_planner', 'query_planner'] },
  { id: 'chip-sizing', label: '3. Source Collectors', nodes: ['collect'] },
  { id: 'chip-risk', label: '4. Evidence Index', nodes: ['ingest', 'coverage_check'] },
  { id: 'chip-critic', label: '5. Seven Analysts', nodes: ['analyst'] },
  { id: 'chip-refiner', label: '6. Citation Judge', nodes: ['citation_validator'] },
  { id: 'chip-decision', label: '7. Critic & Signals', nodes: ['signal_scorer', 'critic', 'refiner'] },
  { id: 'chip-community', label: '8. Verdict', nodes: ['verdict', 'insufficient', 'account', 'finalize'] },
];

const NODE_TEXT: Record<string, string> = {
  intake: 'Reading your idea…',
  perspective_planner: 'Planning research from buyer, user, competitor and skeptic angles…',
  query_planner: 'Writing search queries for each source…',
  collect: 'Collecting public posts',
  ingest: 'Indexing the evidence…',
  coverage_check: 'Checking there is enough evidence to judge…',
  analyst: 'Analysts reading the evidence',
  citation_validator: 'Checking every claim against the post it cites…',
  signal_scorer: 'Computing signals from the evidence…',
  critic: 'Skeptic reviewing the claims…',
  refiner: 'Narrowing claims that went too far…',
  verdict: 'Deciding the verdict…',
  insufficient: 'Not enough evidence; writing up the gaps…',
  finalize: 'Saving the report…',
};

const SAMPLE_IDEA =
  'An automated safety engine for founders that scans LinkedIn, Reddit, and X drafts to catch AI slop patterns and flag ban risk before publishing.';

function stageOf(node: string): number {
  const base = node.split(':')[0];
  return STAGES.findIndex((s) => s.nodes.includes(base));
}

interface Props {
  active: boolean;
  projects: Project[];
  currentProjectId: string | null;
  onOpenProject: (projectId: string) => void;
  onValidated: (projectId: string, runId: string, report: Report | null) => void;
}

export function IntakePane({ active, projects, currentProjectId, onOpenProject, onValidated }: Props) {
  const [idea, setIdea] = useState('');
  const [handle, setHandle] = useState('');
  const [running, setRunning] = useState(false);
  const [pipelineVisible, setPipelineVisible] = useState(false);
  const [pct, setPct] = useState(0);
  const [done, setDone] = useState<Set<number>>(() => new Set());
  const [log, setLog] = useState('Queued…');
  const streamAbort = useRef<AbortController | null>(null);

  useEffect(() => () => streamAbort.current?.abort(), []);

  function follow(projectId: string, runId: string): Promise<void> {
    streamAbort.current?.abort();
    const controller = new AbortController();
    streamAbort.current = controller;
    return new Promise((resolve) => {
      const finish = async () => {
        controller.abort();
        try {
          const report = await api.report(runId);
          onValidated(projectId, runId, report);
        } catch {
          onValidated(projectId, runId, null);
        }
        resolve();
      };
      streamEvents(
        `/api/v1/runs/${encodeURIComponent(runId)}/events`,
        (raw) => {
          let ev: StreamEvent;
          try {
            ev = JSON.parse(raw) as StreamEvent;
          } catch {
            return;
          }
          if (ev.type === 'node_started' && ev.node) {
            const k = stageOf(ev.node);
            if (k >= 0) setPct((p) => Math.max(p, Math.round(((k + 0.5) / STAGES.length) * 100)));
            const base = ev.node.split(':')[0];
            const detail = ev.node.includes(':') ? ` (${ev.node.split(':')[1].replace('_', ' ')})` : '';
            setLog(`${NODE_TEXT[base] ?? base}${detail}`);
          } else if (ev.type === 'node_finished' && ev.node) {
            const k = stageOf(ev.node);
            if (k >= 0) {
              setDone((d) => new Set(d).add(k));
              setPct((p) => Math.max(p, Math.round(((k + 1) / STAGES.length) * 100) - 2));
            }
          } else if (ev.type === 'source') {
            const what = ev.error === 'blocked_by_policy' ? 'skipped (site disallows bots)' : ev.error ? `partial: ${ev.error}` : `${ev.count} posts`;
            setLog(`${ev.source}: ${what}`);
          } else if (ev.type === 'log' && ev.message) {
            setLog(ev.message);
          } else if (ev.type === 'status' && ev.status && TERMINAL.includes(ev.status)) {
            if (ev.status === 'failed' || ev.status === 'cancelled') {
              setLog(ev.status === 'failed' ? `The run failed (${String(ev.error_code ?? 'error')}). Try again in a minute.` : 'Cancelled.');
              controller.abort();
              resolve();
              return;
            }
            setPct(100);
            setDone(new Set(STAGES.map((_, i) => i)));
            void finish();
          }
        },
        controller.signal,
      ).catch(() => resolve());
    });
  }

  async function startValidation() {
    const rawIdea = idea.trim();
    if (rawIdea.length < 5) {
      alert('Please describe your idea in a sentence or two.');
      return;
    }
    setRunning(true);
    setPipelineVisible(true);
    setPct(2);
    setDone(new Set());
    setLog('Queued…');
    try {
      const project = await api.createProject(rawIdea, handle.trim() || null);
      const run = await api.startRun(project.id);
      await follow(project.id, run.run_id);
    } catch (err) {
      console.error(err);
      alert('Could not start the validation: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className={paneClass(active)} id="intake-tab">
      <div className="hero-header">
        <span className="tag tag--lime">Stage 1 · Evidence-Grounded Validation</span>
        <h1 className="display">Validate your startup idea with evidence.<br /><span className="gradient-text">Then launch safely without getting banned.</span></h1>
        <p className="prose hero-subtext">Agents read what real people post on Reddit, Hacker News, X and Product Hunt, then every claim is checked against the post it cites. No invented numbers.</p>
      </div>

      <div className="card intake-card">
        <div className="input-group">
          <div className="input-header">
            <label htmlFor="idea-input">Your Startup Concept</label>
            <button className="btn-ghost" id="sample-idea-btn" onClick={() => { setIdea(SAMPLE_IDEA); setHandle(''); }}>✨ Load Sample SaaS Idea</button>
          </div>
          <textarea id="idea-input" rows={4} placeholder="Describe the problem, who has it, and what you'd build. e.g. An automated code review bot that catches race conditions in Go microservices before PR merge." value={idea} onChange={(e) => setIdea(e.target.value)}></textarea>
        </div>

        <div className="input-row">
          <div className="input-field">
            <label htmlFor="handle-input">Optional: Your Public Handle</label>
            <input type="text" id="handle-input" placeholder="@yourhandle or u/username" value={handle} onChange={(e) => setHandle(e.target.value)} />
          </div>
          <button className="btn-primary" id="start-validation-btn" disabled={running} onClick={startValidation}>
            {running ? <><span className="btn-icon">⏳</span> Researching…</> : <><span className="btn-icon">⚡</span> Run Validation</>}
          </button>
        </div>
      </div>

      <div className="card pipeline-card" id="pipeline-status-card" style={{ display: pipelineVisible ? 'block' : 'none' }}>
        <div className="pipeline-header">
          <h3>Research Progress</h3>
          <span className="pipeline-pct" id="pipeline-pct">{pct}%</span>
        </div>
        <div className="progress-bar-bg">
          <div className="progress-bar-fill" id="pipeline-progress-bar" style={{ width: `${pct}%` }}></div>
        </div>
        <p className="pipeline-log" id="pipeline-log">{log}</p>

        <div className="agent-grid">
          {STAGES.map((stage, i) => (
            <div key={stage.id} className={`agent-chip${done.has(i) ? ' completed' : ''}`} id={stage.id}><span>{stage.label}</span></div>
          ))}
        </div>
      </div>

      {projects.length > 0 && (
        <div className="card" style={{ marginTop: '1.5rem' }}>
          <h3>Past Validations</h3>
          <div className="source-list">
            {projects.map((p) => (
              <div className="source-item" key={p.id}>
                <a href="#" onClick={(e) => { e.preventDefault(); onOpenProject(p.id); }}>
                  {p.id === currentProjectId ? '▸ ' : ''}{p.title}
                </a>
                <div className="source-date">{new Date(p.created_at).toLocaleDateString()} · {p.status}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
