'use client';

import { useState } from 'react';

const ITEMS: { q: string; a: string }[] = [
  { q: 'Will this get my Reddit account banned?', a: "That's the entire point of the product. Deno never automates a single action, checks each community's posted rules and promo limits before drafting, and refuses to ship a post that hard-violates one. The Ban Risk Score is the number you check before you send." },
  { q: 'Is it just ChatGPT with a prompt?', a: "No. The scoring engines are deterministic code, not prompts: a 20-pattern structural detector, a vocabulary density scorer, and Burrows' Delta stylometry measuring the distance between a draft and your own writing. The model drafts; the maths decides whether it ships." },
  { q: 'What if the verdict is Kill?', a: 'Then you saved a year. You get the critic\'s argument with its sources, every claim that was dropped and why, and you can re-run a reframed idea. A tool that never says Kill is a tool that tells you nothing.' },
  { q: 'Do I need an existing audience?', a: 'No — zero followers is the assumed starting state. The calendar is built around other people\'s communities, which is where the first hundred users actually come from when nobody knows your name yet.' },
];

export function Faq() {
  // Single-open accordion; clicking the open item closes it.
  const [open, setOpen] = useState<number | null>(0);

  return (
    <div className="faq__list" id="faq-list">
      {ITEMS.map((item, i) => {
        const isOpen = open === i;
        return (
          <FaqPair key={item.q} index={i} item={item} isOpen={isOpen} onToggle={() => setOpen(isOpen ? null : i)} />
        );
      })}
    </div>
  );
}

function FaqPair({ index, item, isOpen, onToggle }: { index: number; item: { q: string; a: string }; isOpen: boolean; onToggle: () => void }) {
  return (
    <>
      <button className="faq__item" data-index={index} aria-expanded={isOpen} onClick={onToggle}>
        <span className="display">{item.q}</span>
        <span className="mono faq__sign">{isOpen ? '−' : '+'}</span>
      </button>
      <div className="faq__panel" data-panel={index} hidden={!isOpen}>{item.a}</div>
    </>
  );
}
