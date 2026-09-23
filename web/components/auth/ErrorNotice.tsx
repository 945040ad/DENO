'use client';

import { useEffect, useRef } from 'react';

/** The ERR notice; replays the nudge animation every time a new error is shown. */
export function ErrorNotice({ message, nonce }: { message: string | null; nonce: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !message) return;
    el.style.animation = 'none';
    const frame = requestAnimationFrame(() => {
      el.style.animation = 'denoNudge .32s ease both';
    });
    return () => cancelAnimationFrame(frame);
  }, [message, nonce]);

  return (
    <div id="error-notice" className="notice" hidden={!message} style={{ marginBottom: 16 }} ref={ref}>
      <span className="notice__tag">ERR</span>
      <span id="error-text">{message}</span>
    </div>
  );
}
