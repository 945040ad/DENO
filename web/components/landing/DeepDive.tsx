'use client';

import { useState } from 'react';

interface PanelCopy {
  label: string;
  title: string;
  desc: string;
  rows: [string, string][];
}

const PREVIEWS: PanelCopy[] = [
  { label: 'Validation · DAG', title: 'Eight agents, one of them hostile', desc: 'Concurrent intake, market, sizing and risk agents. A Critic that attacks the thesis. A refiner loop bounded at three rounds so it terminates.', rows: [['Critic rounds', '3'], ['Sourced claims', '24'], ['Dropped / unsourced', '6']] },
  { label: 'Verdict · Report', title: 'Build, Pivot or Kill — with the receipts', desc: 'Bottom-up sizing you can audit, the top three arguments on each side, and a clickable source ledger with retrieval timestamps.', rows: [['Verdict', 'BUILD'], ['Confidence', '84%'], ['SOM (yr 1)', '$12M']] },
  { label: 'Ban Risk · Studio', title: 'The number you check before you send', desc: 'Eighteen structural patterns, 2026 density tells and live community rule conflicts, recomputed as you type.', rows: [['Score', '88 / 100'], ['Deductions', '3'], ['Hard violations', '0']] },
  { label: 'Story Bank', title: 'Receipts a model can’t fabricate', desc: 'Scars, metrics, turning points and defended opinions. Every draft pulls one real detail, which is what defeats the portability test.', rows: [['Entries', '14'], ['Metrics on file', '6'], ['Scars', '4']] },
  { label: 'Publishing · Manual', title: 'Copy, deep-link, send', desc: 'No automation anywhere in the loop. Deno prepares the post and the platform link; a human always presses the button.', rows: [['Automated actions', '0'], ['Deep links', 'READY'], ['ToS posture', 'COMPLIANT']] },
];

interface AccordionEntry {
  label: string;
  num: string;
  background: string;
  proseColor: string;
  body: string;
  href: string;
  cta: string;
}

const ENTRIES: AccordionEntry[] = [
  { label: 'Eight agents that argue with each other', num: '01', background: 'var(--green-soft)', proseColor: 'var(--ink-2)', body: 'Intake, Market, Sizing and Risk run concurrently. Then a Critic agent tries to kill the thesis, and a bounded refiner loop answers it — maximum three rounds, graceful on partial failure. You read the disagreement, not a summary.', href: '/app', cta: 'Explore validation →' },
  { label: 'A verdict that says Kill when it means Kill', num: '02', background: 'var(--peach)', proseColor: '#3A2A22', body: 'BUILD, PIVOT or KILL with calibrated confidence and the top three arguments on each side. Bottom-up TAM/SAM/SOM you can audit line by line. Claims without a retrievable source are dropped, never guessed.', href: '#receipts', cta: 'Read a sample verdict →' },
  { label: 'Ban Risk Score on every single draft', num: '03', background: 'var(--blue-soft)', proseColor: '#1E2A38', body: 'One number, 0–100, recomputed as you type. Below threshold you get itemised deductions: which slop pattern, which density tell, which community rule — and the rewrite that clears it.', href: '#risk', cta: 'Open the Studio →' },
  { label: 'A Story Bank no model could invent', num: '04', background: 'var(--amber-soft)', proseColor: '#33301E', body: 'Scars, metrics, turning points and defended opinions, stored once. Every post pulls a real receipt, which is what defeats the portability test — the reason generic AI posts read as generic.', href: '/app', cta: 'Build your bank →' },
  { label: 'It never posts for you', num: '05', background: 'var(--paper-2)', proseColor: 'var(--ink-2)', body: "No automation, no vote rings, no DMs. Copy, deep-link, send. It's the only publishing model that survives platform terms of service — and the only one that keeps your account.", href: '#trust', cta: 'Read the compliance stance →' },
];

export function DeepDive() {
  const [active, setActive] = useState(0);
  const preview = PREVIEWS[active] ?? PREVIEWS[0];

  return (
    <div className="deepdive__grid">
      <div>
        <h2 className="display deepdive__title">Why founders with no audience start here</h2>
        <p className="prose deepdive__sub">You don&apos;t need another writing assistant. You need to know the idea holds up, and then not get filtered out of the only channels you can afford.</p>

        <div className="accordion" id="deepdive-accordion" role="tablist" aria-label="Deno platform capabilities">
          {ENTRIES.map((entry, i) => (
            <AccordionPair key={entry.num} entry={entry} index={i} active={i === active} onSelect={setActive} />
          ))}
        </div>
      </div>

      <div className="deepdive__preview-shell">
        <div className="deepdive__preview panel">
          <div className="panel__head">
            <span className="mono" id="deepdive-label">{preview.label}</span>
            <span className="mono-plain">deno/workspace</span>
          </div>
          <div className="deepdive__preview-body">
            <div className="display deepdive__preview-title" id="deepdive-title">{preview.title}</div>
            <div className="deepdive__preview-desc" id="deepdive-desc">{preview.desc}</div>
            <div className="deepdive__preview-rows" id="deepdive-rows">
              {preview.rows.map(([k, v]) => (
                <div key={k}><span>{k}</span><span>{v}</span></div>
              ))}
            </div>
            <div className="deepdive__preview-shot">
              <img src="/assets/workspace-intake.png" alt="Deno workspace intake screen showing the idea input and live agent DAG" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AccordionPair({ entry, index, active, onSelect }: { entry: AccordionEntry; index: number; active: boolean; onSelect: (i: number) => void }) {
  return (
    <>
      <button className="accordion__item" data-index={index} aria-expanded={active} onClick={() => onSelect(index)}>
        <span className="display accordion__label">{entry.label}</span>
        <span className="mono-plain">{entry.num}</span>
      </button>
      <div className="accordion__panel" data-panel={index} hidden={!active} style={{ background: entry.background }}>
        <p className="prose" style={{ color: entry.proseColor, marginBottom: 14 }}>{entry.body}</p>
        <a href={entry.href} className="link-mono">{entry.cta}</a>
      </div>
    </>
  );
}
