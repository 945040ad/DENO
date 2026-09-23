'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type Plan, type Project, type Report } from '@/lib/api';
import { AuditorPane } from './AuditorPane';
import { CalendarPane } from './CalendarPane';
import { CommunitiesPane } from './CommunitiesPane';
import { IntakePane } from './IntakePane';
import { VerdictPane } from './VerdictPane';
import { VoicePane } from './VoicePane';

export type TabId = 'intake-tab' | 'verdict-tab' | 'communities-tab' | 'voice-tab' | 'calendar-tab' | 'auditor-tab';

const TABS: { id: TabId; label: string; navId?: string; gated?: boolean }[] = [
  { id: 'intake-tab', label: '01 Intake' },
  { id: 'verdict-tab', label: '02 Verdict', navId: 'nav-verdict-tab', gated: true },
  { id: 'communities-tab', label: '03 Communities' },
  { id: 'voice-tab', label: '04 Voice & Story Bank' },
  { id: 'calendar-tab', label: '05 Calendar', navId: 'nav-calendar-tab', gated: true },
  { id: 'auditor-tab', label: '06 Ban Risk Studio' },
];

export function Workspace() {
  const [activeTab, setActiveTab] = useState<TabId>('intake-tab');
  const [unlocked, setUnlocked] = useState<Set<TabId>>(() => new Set());
  const [statusLabel, setStatusLabel] = useState('Connecting…');
  const [projectId, setProjectId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [toast, setToast] = useState({ message: 'Post copied to clipboard!', show: false });
  const toastTimer = useRef<number | undefined>(undefined);

  const showToast = useCallback((message: string) => {
    setToast({ message, show: true });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast((t) => ({ ...t, show: false })), 3000);
  }, []);

  const switchTab = useCallback((tab: TabId) => {
    setUnlocked((prev) => new Set(prev).add(tab));
    setActiveTab(tab);
  }, []);

  /** Loads a project's latest finished run (report) and latest finished content plan. */
  const openProject = useCallback(async (id: string) => {
    setProjectId(id);
    setRunId(null);
    setReport(null);
    setPlan(null);
    const runs = await api.listRuns(id);
    const done = runs.find((r) => r.status === 'succeeded' || r.status === 'awaiting_review');
    if (done) {
      setRunId(done.id);
      setReport(await api.report(done.id));
      setUnlocked((prev) => new Set(prev).add('verdict-tab'));
    }
    const plans = await api.listPlans(id);
    const ready = plans.find((p) => p.status === 'succeeded');
    if (ready) {
      setPlan(await api.plan(ready.id));
      setUnlocked((prev) => new Set(prev).add('calendar-tab'));
    }
    return Boolean(done);
  }, []);

  // Restore the latest project on load.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await api.listProjects();
        if (cancelled) return;
        setStatusLabel('Connected');
        setProjects(page.items);
        if (page.items[0]) await openProject(page.items[0].id);
      } catch (err) {
        setStatusLabel(err instanceof ApiError && err.status === 401 ? 'Signed out' : 'API unreachable');
      }
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(toastTimer.current);
    };
  }, [openProject]);

  return (
    <>
      <div className="workspace-shell">
        <div className="workspace-frame">

          <header className="workspace-topbar">
            <a href="/" className="brand brand--sm">
              <span className="brand__word">deno</span>
              <span className="brand__chip">GTM</span>
            </a>

            <nav className="nav-tabs">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  className={`nav-tab${activeTab === tab.id ? ' active' : ''}`}
                  data-tab={tab.id}
                  id={tab.navId}
                  disabled={tab.gated && !unlocked.has(tab.id)}
                  onClick={() => setActiveTab(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </nav>

            <div className="system-status">
              <span className="pulse-dot"></span>
              <span className="mono" id="status-label">{statusLabel}</span>
              <a className="mono" href="/app/account" style={{ marginLeft: '0.75rem' }}>Account</a>
            </div>
          </header>

          <main className="main-content">
            <IntakePane
              active={activeTab === 'intake-tab'}
              projects={projects}
              currentProjectId={projectId}
              onOpenProject={async (id) => {
                const hasReport = await openProject(id).catch(() => false);
                if (hasReport) switchTab('verdict-tab');
                else showToast('That idea has no finished validation yet.');
              }}
              onValidated={(pid, rid, validated) => {
                api.listProjects().then((p) => setProjects(p.items)).catch(() => undefined);
                setProjectId(pid);
                setRunId(rid);
                setReport(validated);
                setPlan(null);
                switchTab('verdict-tab');
                showToast(validated?.verdict ? 'Validation complete. Verdict ready.' : 'Run finished.');
              }}
            />
            <VerdictPane
              active={activeTab === 'verdict-tab'}
              report={report}
              projectId={projectId}
              runId={runId}
              onReport={setReport}
              onOpenCommunities={() => switchTab('communities-tab')}
              onPlan={(p) => {
                setPlan(p);
                switchTab('calendar-tab');
                showToast('Content plan ready. Every draft was checked by the gates.');
              }}
              onToast={showToast}
            />
            <CommunitiesPane active={activeTab === 'communities-tab'} runId={runId} />
            <VoicePane active={activeTab === 'voice-tab'} onToast={showToast} />
            <CalendarPane active={activeTab === 'calendar-tab'} plan={plan} onPlan={setPlan} onToast={showToast} />
            <AuditorPane active={activeTab === 'auditor-tab'} />
          </main>
        </div>
      </div>

      <div className={`toast${toast.show ? ' show' : ''}`} id="toast">{toast.message}</div>
    </>
  );
}
