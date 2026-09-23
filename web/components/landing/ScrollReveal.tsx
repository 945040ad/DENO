'use client';

import { useEffect } from 'react';

/**
 * Fades sections in as they scroll into view (every <section> after the
 * first three, same as the original landing.js). Renders nothing.
 */
export function ScrollReveal() {
  useEffect(() => {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const targets = Array.from(document.querySelectorAll('section')).slice(3);
    if (reduceMotion || !targets.length) return;

    targets.forEach((el) => el.classList.add('reveal'));
    const show = (el: Element) => el.classList.add('is-visible');

    if (!('IntersectionObserver' in window)) {
      targets.forEach(show);
      return;
    }

    let fired = false;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            fired = true;
            show(entry.target);
            io.unobserve(entry.target);
          }
        });
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.05 },
    );
    targets.forEach((el) => io.observe(el));

    // Safety net: if IO never fires (e.g. everything already in view), reveal anyway.
    const timer = window.setTimeout(() => {
      if (!fired) targets.forEach(show);
    }, 1200);

    return () => {
      io.disconnect();
      window.clearTimeout(timer);
    };
  }, []);

  return null;
}
