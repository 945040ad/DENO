import type { GateFinding } from '@/lib/api';

const LAYER_LABEL: Record<string, string> = {
  L1_scrub: 'Scrub',
  L2_patterns: 'AI pattern',
  L3_density: 'Vagueness',
  L4_structure: 'Structure',
  L5_judge: 'Editor check',
  voice: 'Voice',
  compliance: 'Community rules',
};

/** Itemised gate findings, shared by the calendar editor and the playground. */
export function DeductionItems({
  findings,
  fixLabel,
}: {
  findings: (GateFinding & { layer: string })[];
  fixLabel: string;
}) {
  return (
    <>
      {findings.map((f, i) => (
        <div className="deduction-item" key={`${f.rule_id}-${i}`}>
          <div className="deduction-header">
            <span>{f.severity === 'block' ? '⚠️' : 'ℹ️'} {f.message}</span>
            <span>{LAYER_LABEL[f.layer] ?? f.layer}</span>
          </div>
          {f.quote && <div className="deduction-quote">&quot;{f.quote}&quot;</div>}
          <div className="deduction-fix"><strong>{fixLabel}</strong> {f.fix}</div>
        </div>
      ))}
    </>
  );
}
