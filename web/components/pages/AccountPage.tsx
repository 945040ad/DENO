'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  api,
  type Billing,
  type Handle,
  type Me,
  type Story,
  type StoryCategory,
  type VoiceProfile,
  type VoiceSample,
} from '@/lib/api';
import { createClient } from '@/lib/supabase/client';

type Tab = 'profile' | 'voice' | 'billing' | 'checkout' | 'notif' | 'security' | 'data';

const TIMEZONES = [
  'Asia/Kolkata',
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Berlin',
  'Asia/Singapore',
  'Australia/Sydney',
];
const ROLES: [string, string][] = [
  ['solo_founder', 'Solo founder'],
  ['co_founder', 'Co-founder'],
  ['indie_hacker', 'Indie hacker'],
  ['founding_marketer', 'Founding marketer'],
];
const PRESETS: [string, string][] = [
  ['terse_engineer', 'Terse engineer'],
  ['build_in_public', 'Build-in-public'],
  ['dry_humour', 'Dry humour'],
  ['data_first', 'Data-first'],
  ['storyteller', 'Storyteller'],
];
const NOTIFS: [string, string, string][] = [
  ['verdict_ready', 'Verdict ready', 'When a validation run finishes.'],
  ['draft_ready', 'Draft ready to send', 'Morning of each calendar slot, with the deep link to post.'],
  ['rule_changed', 'Community rule changed', 'A community you target updated its self-promo or AI policy.'],
  ['ban_risk', 'Draft flagged by the gates', 'A draft in your queue fails a check and needs your edit.'],
  ['weekly_digest', 'Weekly digest', "Mondays: what shipped, what's next, what got flagged."],
  ['product_updates', 'Product updates', 'New agents, communities and features. Rare.'],
];
const NOTIF_DEFAULTS: Record<string, boolean> = {
  verdict_ready: true,
  draft_ready: true,
  rule_changed: true,
  ban_risk: true,
  weekly_digest: false,
  product_updates: false,
};
const USAGE_LABEL: Record<string, string> = {
  validation_run: 'Validation runs',
  content_plan: 'Content plans',
  audit: 'Ban Risk audits',
};
const CATEGORY_LABEL: Record<StoryCategory, string> = {
  scar: 'SCAR',
  metric: 'METRIC',
  turning_point: 'TURNING POINT',
  defended_opinion: 'DEFENDED OPINION',
  customer_quote: 'CUSTOMER QUOTE',
};

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .map((w) => w[0])
      .slice(0, 2)
      .join('')
      .toUpperCase() || 'D'
  );
}

/** Style traits measured from the user's own samples (not estimates). */
function traits(samples: VoiceSample[]): { label: string; value: string; pct: number }[] {
  const text = samples.map((s) => s.text).join('\n');
  const sentences = text.split(/(?<=[.!?])\s+/).filter((s) => s.trim());
  const lengths = sentences.map((s) => s.split(/\s+/).filter(Boolean).length);
  const words = text.toLowerCase().match(/[a-z']+/g) ?? [];
  if (!words.length || !lengths.length) return [];
  const mean = lengths.reduce((a, b) => a + b, 0) / lengths.length;
  const sd = Math.sqrt(lengths.reduce((a, b) => a + (b - mean) ** 2, 0) / lengths.length);
  const firstPerson = words.filter((w) => ['i', "i'm", "i've", 'my', 'we', 'our', "we're"].includes(w)).length / words.length;
  const hedges = (text.match(/\b(maybe|perhaps|probably|kind of|sort of|i think|arguably)\b/gi) ?? []).length / sentences.length;
  const contractions = words.filter((w) => w.includes("'")).length / words.length;
  return [
    { label: 'Mean words per sentence', value: mean.toFixed(1), pct: Math.min(100, (mean / 30) * 100) },
    { label: 'Sentence length variation', value: (sd / Math.max(mean, 1)).toFixed(2), pct: Math.min(100, (sd / Math.max(mean, 1)) * 100) },
    { label: 'First-person rate', value: `${(firstPerson * 100).toFixed(1)}%`, pct: Math.min(100, firstPerson * 1000) },
    { label: 'Hedges per sentence', value: hedges.toFixed(2), pct: Math.min(100, hedges * 100) },
    { label: 'Contraction rate', value: `${(contractions * 100).toFixed(1)}%`, pct: Math.min(100, contractions * 1000) },
  ];
}

export function AccountPage() {
  const [tab, setTab] = useState<Tab>('profile');
  const [me, setMe] = useState<Me | null>(null);
  const [billing, setBilling] = useState<Billing | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get('tab') as Tab | null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deep links like /app/account?tab=billing
    if (initial) setTab(initial);
    Promise.all([api.me(), api.billing()])
      .then(([m, b]) => {
        setMe({ ...m, handles: m.handles ?? [], notification_prefs: m.notification_prefs ?? {} });
        setBilling(b);
      })
      .catch((err) => setMessage(err instanceof Error ? err.message : String(err)));
  }, []);

  const pro = billing?.plan === 'pro';
  const name = me?.display_name || me?.email?.split('@')[0] || 'Your account';
  const nav: [Tab, string, string, string][] = [
    ['profile', '01', 'Profile', ''],
    ['voice', '02', 'Voice & handles', me?.handles.length ? String(me.handles.length) : ''],
    ['billing', '03', 'Plan & usage', pro ? 'PRO' : 'FREE'],
    ['checkout', '04', 'Checkout', ''],
    ['notif', '05', 'Notifications', ''],
    ['security', '06', 'Security', ''],
    ['data', '07', 'Data & privacy', ''],
  ];

  async function signOut() {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/auth/signout';
    document.body.appendChild(form);
    form.submit();
  }

  return (
    <div className="dv-shell">
      <div className="dv-frame">
        <div className="dv-top">
          <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap' }}>
            <a href="/app" className="dv-brand">
              <span className="dv-brand-word">deno</span>
              <span className="dv-brand-chip">GTM</span>
            </a>
            <a href="/app" className="dv-back">← WORKSPACE</a>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 'none' }}>
            <span className="dv-pill" style={{ background: pro ? 'var(--lime)' : 'transparent', borderWidth: 1.5 }}>{pro ? 'PRO' : 'FREE PLAN'}</span>
            <span style={{ width: 36, height: 36, border: '1.5px solid var(--ink)', background: 'var(--lime)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--serif)', fontSize: 17 }}>
              {initials(name)}
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 220px', maxWidth: '100%', borderRight: '1.5px solid var(--ink)', background: 'var(--paper-2)', minWidth: 0 }}>
            <div style={{ padding: '22px clamp(14px,2vw,22px) 14px' }}>
              <div className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.12em', color: 'var(--muted)' }}>ACCOUNT</div>
              <div className="dv-serif" style={{ fontSize: 26, lineHeight: 1.05, marginTop: 6, overflowWrap: 'anywhere' }}>{name}</div>
              <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4, wordBreak: 'break-all' }}>{me?.email ?? ''}</div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', borderTop: '1.5px solid var(--ink)' }}>
              {nav.map(([k, num, label, meta]) => {
                const on = tab === k;
                return (
                  <button
                    key={k}
                    onClick={() => {
                      setTab(k);
                      setMessage(null);
                    }}
                    style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%', textAlign: 'left', border: 0, borderBottom: '1px solid rgba(16,22,19,.16)', padding: '13px clamp(14px,2vw,22px)', cursor: 'pointer', fontFamily: 'var(--sans)', fontSize: 14.5, fontWeight: 600, background: on ? 'var(--ink)' : 'transparent', color: on ? 'var(--paper)' : 'var(--ink)' }}
                  >
                    <span className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, color: on ? 'var(--lime)' : 'var(--muted)' }}>{num}</span>
                    <span style={{ flex: 1, minWidth: 0 }}>{label}</span>
                    <span className="dv-mono" style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: on ? 'var(--lime)' : 'var(--muted)' }}>{meta}</span>
                  </button>
                );
              })}
            </div>
            <div style={{ padding: '18px clamp(14px,2vw,22px)' }}>
              <button className="dv-link" onClick={signOut}>Sign out →</button>
            </div>
          </div>

          <div style={{ flex: '999 1 520px', minWidth: 0 }}>
            {message && (
              <div className="dv-err" style={{ margin: '16px clamp(22px,3vw,40px) 0' }}>
                <span className="dv-mono" style={{ fontWeight: 700, color: 'var(--red-ink)' }}>ERR</span>
                <span>{message}</span>
              </div>
            )}
            {tab === 'profile' && me && <ProfileTab me={me} onSaved={setMe} onError={setMessage} />}
            {tab === 'voice' && me && <VoiceTab me={me} onSaved={setMe} onError={setMessage} />}
            {tab === 'billing' && billing && <BillingTab billing={billing} onCheckout={() => setTab('checkout')} onError={setMessage} />}
            {tab === 'checkout' && billing && <CheckoutTab billing={billing} onError={setMessage} />}
            {tab === 'notif' && me && <NotifTab me={me} onSaved={setMe} onError={setMessage} />}
            {tab === 'security' && <SecurityTab onError={setMessage} />}
            {tab === 'data' && <DataTab onError={setMessage} />}
          </div>
        </div>
      </div>
    </div>
  );
}

function Head({ kicker, title, lede, lime }: { kicker: string; title: string; lede?: string; lime?: boolean }) {
  return (
    <div className="dv-pad dv-rb">
      <span className={`dv-kicker${lime ? ' lime' : ''}`}>{kicker}</span>
      <h1 className="dv-h1">{title}</h1>
      {lede && <p className="dv-lede">{lede}</p>}
    </div>
  );
}

type Saver = { me: Me; onSaved: (m: Me) => void; onError: (m: string) => void };

function ProfileTab({ me, onSaved, onError }: Saver) {
  const [form, setForm] = useState({
    display_name: me.display_name ?? '',
    product_name: me.product_name ?? '',
    product_url: me.product_url ?? '',
    timezone: me.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
    founder_role: me.founder_role ?? 'solo_founder',
  });
  const [saved, setSaved] = useState(false);
  const zones = TIMEZONES.includes(form.timezone) ? TIMEZONES : [form.timezone, ...TIMEZONES];

  async function save() {
    try {
      onSaved(await api.updateMe({ ...form }));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2200);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  const field = (key: keyof typeof form, label: string) => (
    <div>
      <label className="dv-label">{label}</label>
      <input className="dv-input" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
    </div>
  );

  return (
    <div className="dv-rise">
      <Head kicker="01 · PROFILE" title="Who the posts are from." lede="Your name and product show up in drafts and disclosures. Communities can see this, so keep it real." />
      <div className="dv-pad" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: '16px 20px', maxWidth: 880 }}>
        {field('display_name', 'DISPLAY NAME')}
        <div>
          <label className="dv-label">EMAIL · FROM YOUR LOGIN</label>
          <input className="dv-input" value={me.email ?? ''} readOnly style={{ color: 'var(--muted)' }} />
        </div>
        {field('product_name', 'PRODUCT NAME')}
        {field('product_url', 'PRODUCT URL')}
        <div>
          <label className="dv-label">TIMEZONE · FOR POSTING WINDOWS</label>
          <select className="dv-input" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })}>
            {zones.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
        </div>
        <div>
          <label className="dv-label">ROLE</label>
          <select className="dv-input" value={form.founder_role} onChange={(e) => setForm({ ...form, founder_role: e.target.value })}>
            {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
      </div>
      <div style={{ padding: '0 clamp(22px,3vw,40px) clamp(22px,3vw,40px)', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <button className="dv-btn lime" onClick={save}>Save changes</button>
        {saved && <span className="dv-mono dv-rise" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.08em', color: 'var(--green)' }}>✓ SAVED</span>}
      </div>
    </div>
  );
}

function VoiceTab({ me, onSaved, onError }: Saver) {
  const [samples, setSamples] = useState<VoiceSample[]>([]);
  const [profile, setProfile] = useState<VoiceProfile | null>(null);
  const [stories, setStories] = useState<Story[]>([]);
  const [sample, setSample] = useState('');
  const [newHandle, setNewHandle] = useState<Handle>({ platform: 'reddit', handle: '' });
  const [story, setStory] = useState({ category: 'scar' as StoryCategory, headline: '', details: '', numbers: '' });

  useEffect(() => {
    Promise.all([api.voiceSamples(), api.voiceProfile(), api.stories()])
      .then(([s, p, st]) => {
        setSamples(s);
        setProfile(p);
        setStories(st);
      })
      .catch(() => undefined);
  }, []);

  const measured = useMemo(() => traits(samples), [samples]);

  async function saveMe(body: Parameters<typeof api.updateMe>[0]) {
    try {
      onSaved(await api.updateMe(body));
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  async function addSample() {
    if (sample.trim().split(/\s+/).length < 20) return onError('Paste one of your own posts: at least 20 words.');
    try {
      const added = await api.addVoiceSample(sample.trim());
      const next = [...samples, added];
      setSamples(next);
      setSample('');
      if (next.length >= 3) setProfile(await api.buildVoiceProfile());
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  async function addStory() {
    try {
      const created = await api.addStory({
        category: story.category,
        headline: story.headline.trim(),
        details: story.details.trim(),
        numbers: story.numbers.split(',').map((n) => n.trim()).filter(Boolean),
      });
      setStories([created, ...stories]);
      setStory({ ...story, headline: '', details: '', numbers: '' });
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="dv-rise">
      <Head kicker="02 · VOICE & HANDLES" title="Sound like you. Not like a model." lede="Drafts are measured against posts you wrote yourself. Handles are read-only: Deno never posts, votes or DMs from them." />
      <div className="dv-split">
        <div className="dv-pad dv-rr dv-cell">
          <div className="dv-label" style={{ marginBottom: 0 }}>PUBLIC HANDLES</div>
          {me.handles.map((h, i) => (
            <div key={`${h.platform}-${h.handle}`} className="dv-card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span className="dv-pill solid" style={{ minWidth: 74, textAlign: 'center' }}>{h.platform.toUpperCase()}</span>
              <span style={{ flex: 1, minWidth: 0, fontSize: 14.5, fontWeight: 600, overflowWrap: 'anywhere' }}>{h.handle}</span>
              <button className="dv-link" style={{ color: 'var(--red-ink)', borderColor: 'var(--red-ink)' }} onClick={() => saveMe({ handles: me.handles.filter((_, j) => j !== i) })}>REMOVE</button>
            </div>
          ))}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <select className="dv-input" style={{ width: 130 }} value={newHandle.platform} onChange={(e) => setNewHandle({ ...newHandle, platform: e.target.value as Handle['platform'] })}>
              <option value="reddit">Reddit</option>
              <option value="x">X</option>
              <option value="linkedin">LinkedIn</option>
              <option value="hn">HN</option>
            </select>
            <input className="dv-input" style={{ flex: 1, minWidth: 160 }} placeholder="u/yourname or @yourname" value={newHandle.handle} onChange={(e) => setNewHandle({ ...newHandle, handle: e.target.value })} />
            <button
              className="dv-btn ghost"
              disabled={!newHandle.handle.trim()}
              onClick={() => {
                void saveMe({ handles: [...me.handles, { ...newHandle, handle: newHandle.handle.trim() }] });
                setNewHandle({ ...newHandle, handle: '' });
              }}
            >
              + Add handle
            </button>
          </div>
          <div className="dv-label" style={{ margin: '14px 0 0' }}>ADD A POST YOU WROTE · 20+ WORDS</div>
          <textarea className="dv-input" rows={3} value={sample} onChange={(e) => setSample(e.target.value)} placeholder="Paste a LinkedIn post, Reddit comment or email you wrote yourself..." />
          <button className="dv-btn ghost" style={{ alignSelf: 'flex-start' }} onClick={addSample}>Add sample &amp; recalculate</button>
          <div className="dv-label" style={{ margin: '14px 0 0' }}>NO PUBLIC HISTORY? TAP A STYLE</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {PRESETS.map(([v, l]) => (
              <button key={v} className="dv-tab" style={{ background: me.voice_preset === v ? 'var(--lime)' : 'transparent', color: 'var(--ink)' }} onClick={() => saveMe({ voice_preset: v })}>{l}</button>
            ))}
          </div>
        </div>
        <div className="dv-pad dv-dark" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <span className="dv-dark-label">VOICE FINGERPRINT</span>
            <span className="dv-mono dv-dim" style={{ fontSize: 10 }}>{samples.length} POSTS READ</span>
          </div>
          <div className="dv-serif" style={{ fontSize: 'clamp(40px,4.6vw,58px)', lineHeight: 0.9, color: 'var(--lime)' }}>
            {profile?.avg_draft_delta != null ? profile.avg_draft_delta.toFixed(2) : '—'}
          </div>
          <div className="dv-mono dv-dim" style={{ fontSize: 10.5, letterSpacing: '.08em', marginTop: -6 }}>
            {profile?.drafts_scored ? `AVG DELTA · ${profile.drafts_scored} DRAFTS VS YOU · LOWER IS CLOSER` : profile ? 'NO DRAFTS SCORED YET' : 'ADD 3+ POSTS TO BUILD YOUR FINGERPRINT'}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 6 }}>
            {measured.map((t) => (
              <div key={t.label}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, marginBottom: 5 }}>
                  <span>{t.label}</span>
                  <span className="dv-mono" style={{ fontSize: 11, color: 'var(--lime)' }}>{t.value}</span>
                </div>
                <div className="dv-thin"><div style={{ width: `${Math.max(2, t.pct)}%` }} /></div>
              </div>
            ))}
          </div>
          {profile && (
            <div className="dv-row done" style={{ marginTop: 'auto', justifyContent: 'space-between', flexWrap: 'wrap' }}>
              <span>{profile.strong ? 'Drafts are blocked above Delta' : 'Advisory until 5+ longer posts · flag above'}</span>
              <span className="dv-mono" style={{ fontSize: 12, fontWeight: 700, color: 'var(--lime)' }}>{profile.threshold.toFixed(2)}</span>
            </div>
          )}
        </div>
      </div>
      <div className="dv-split" style={{ borderTop: '1.5px solid var(--ink)' }}>
        <div className="dv-pad dv-rr dv-cell">
          <div className="dv-label" style={{ marginBottom: 0 }}>STORY BANK · THE ONLY SOURCE OF NUMBERS AND ANECDOTES IN DRAFTS</div>
          <select className="dv-input" value={story.category} onChange={(e) => setStory({ ...story, category: e.target.value as StoryCategory })}>
            {Object.entries(CATEGORY_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <input className="dv-input" placeholder="Headline: e.g. Spent 4 months on a feature nobody used" value={story.headline} onChange={(e) => setStory({ ...story, headline: e.target.value })} />
          <textarea className="dv-input" rows={3} placeholder="What happened, in your words" value={story.details} onChange={(e) => setStory({ ...story, details: e.target.value })} />
          <input className="dv-input" placeholder="Numbers that appear in the text, comma separated" value={story.numbers} onChange={(e) => setStory({ ...story, numbers: e.target.value })} />
          <button className="dv-btn lime" style={{ alignSelf: 'flex-start' }} onClick={addStory}>Add to Story Bank</button>
        </div>
        <div className="dv-pad dv-soft dv-cell">
          <div className="dv-label" style={{ marginBottom: 0 }}>{stories.length} ENTRIES</div>
          {stories.map((s) => (
            <div key={s.id} className="dv-card">
              <div className="dv-mono" style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', letterSpacing: '.06em' }}>
                {CATEGORY_LABEL[s.category]}
                {s.numbers.length ? ` · ${s.numbers.join(', ')}` : ''}
              </div>
              <div style={{ fontWeight: 600, margin: '4px 0' }}>{s.headline}</div>
              <div style={{ fontSize: 13.5, color: 'var(--ink-3)', lineHeight: 1.5 }}>{s.details}</div>
              <button
                className="dv-link"
                style={{ marginTop: 8, color: 'var(--red-ink)', borderColor: 'var(--red-ink)' }}
                onClick={() => api.deleteStory(s.id).then(() => setStories(stories.filter((x) => x.id !== s.id)))}
              >
                REMOVE
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function BillingTab({ billing, onCheckout, onError }: { billing: Billing; onCheckout: () => void; onError: (m: string) => void }) {
  const pro = billing.plan === 'pro';
  const nextReset = new Date();
  nextReset.setMonth(nextReset.getMonth() + 1, 1);

  async function portal() {
    try {
      window.location.href = (await api.portal()).url;
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="dv-rise">
      <Head
        kicker="03 · PLAN & USAGE"
        title={pro ? 'Pro. Distribution unlocked.' : 'Free. Validation, forever.'}
        lede={pro ? 'Content plans, the 30-day calendar and Story Bank are on. Usage resets on the first of each month.' : "You're on Stage 1. Upgrade when a verdict says BUILD and you want the plan to post it."}
      />
      <div className="dv-split dv-rb">
        <div className="dv-pad dv-rr">
          <div className="dv-label" style={{ marginBottom: 16 }}>
            THIS MONTH · RESETS {nextReset.toLocaleDateString(undefined, { month: 'short', day: '2-digit' }).toUpperCase()}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {billing.usage.map((u) => {
              const ratio = u.limit ? u.used / u.limit : 0;
              return (
                <div key={u.kind}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, marginBottom: 7 }}>
                    <span style={{ fontSize: 14.5, fontWeight: 600 }}>{USAGE_LABEL[u.kind] ?? u.kind}</span>
                    <span className="dv-mono" style={{ fontSize: 11.5, fontWeight: 700 }}>{u.used.toLocaleString()} / {u.limit?.toLocaleString() ?? '∞'}</span>
                  </div>
                  <div className="dv-bar">
                    <div style={{ width: `${Math.max(2, Math.min(100, Math.round(ratio * 100)))}%`, background: ratio >= 1 ? 'var(--red)' : ratio > 0.7 ? '#C8A21A' : 'var(--green)' }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div className="dv-pad" style={{ background: pro ? 'var(--green-soft)' : 'var(--lime)' }}>
          {!pro ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <span className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.12em' }}>STAGE 2 · PRO</span>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span className="dv-serif" style={{ fontSize: 56, lineHeight: 0.9 }}>$20</span>
                <span className="dv-mono" style={{ fontSize: 11, fontWeight: 700 }}>/ MONTH</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7, fontSize: 14, lineHeight: 1.45 }}>
                <span>→ 50 validation runs, 20 content plans</span>
                <span>→ 5,000 Ban Risk audits</span>
                <span>→ 30-day calendar + Story Bank</span>
              </div>
              <button className="dv-btn ink" style={{ alignSelf: 'flex-start', color: 'var(--lime)', boxShadow: '4px 4px 0 var(--paper)' }} onClick={onCheckout}>Upgrade to Pro →</button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <span className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.12em', color: 'var(--green)' }}>
                PRO · {billing.status.toUpperCase()}
              </span>
              <div className="dv-serif" style={{ fontSize: 28, lineHeight: 1.1 }}>
                {billing.current_period_end ? `Renews ${new Date(billing.current_period_end).toLocaleDateString()}` : 'Active'}
              </div>
              {billing.status === 'past_due' && <div className="dv-err">Your last payment failed. Update your card to keep Pro.</div>}
              <button className="dv-btn ghost" style={{ alignSelf: 'flex-start' }} onClick={portal}>Manage card, invoices &amp; cancellation</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CheckoutTab({ billing, onError }: { billing: Billing; onError: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  const pro = billing.plan === 'pro';

  async function checkout() {
    setBusy(true);
    try {
      window.location.href = (await api.checkout()).url;
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="dv-rise dv-split wide">
      <div className="dv-pad dv-rr">
        <span className="dv-kicker lime">04 · CHECKOUT</span>
        <h1 className="dv-h1" style={{ marginBottom: 14 }}>{pro ? "You're already Pro." : 'Unlock distribution.'}</h1>
        <p className="dv-lede" style={{ marginBottom: 22 }}>
          Payment happens on Stripe&apos;s secure checkout page. Deno never sees or stores your card.
        </p>
        {!pro && (
          <button className="dv-btn lime" style={{ width: '100%', fontSize: 16, padding: 16 }} disabled={!billing.billing_enabled || busy} onClick={checkout}>
            {!billing.billing_enabled ? 'Upgrades open soon' : busy ? 'Opening Stripe…' : 'Continue to secure checkout · $20.00'}
          </button>
        )}
        <p className="dv-mono" style={{ margin: '14px 0 0', fontSize: 10.5, letterSpacing: '.06em', color: 'var(--muted)', lineHeight: 1.6 }}>
          SECURED BY STRIPE · CANCEL ANYTIME FROM THE BILLING PORTAL
        </p>
      </div>
      <div className="dv-pad dv-dark" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <span className="dv-dark-label">ORDER SUMMARY</span>
        <div style={{ border: '1.5px solid var(--lime)', background: 'rgba(198,242,78,.1)', padding: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
            <span className="dv-serif" style={{ fontSize: 28 }}>Deno Pro</span>
            <span className="dv-mono" style={{ fontSize: 13, fontWeight: 700 }}>$20.00</span>
          </div>
          <div className="dv-mono dv-dim" style={{ fontSize: 10.5, marginTop: 4 }}>MONTHLY</div>
        </div>
        {['Content plans with every draft gated for AI tells', 'Up to 30-day calendar across your communities', 'Voice-matched drafts + Story Bank'].map((t, i) => (
          <div key={t} className="dv-row"><span className="dv-mono" style={{ fontSize: 11, color: 'var(--lime)' }}>0{i + 1}</span>{t}</div>
        ))}
        <div className="dv-mono" style={{ marginTop: 'auto', borderTop: '1px solid rgba(250,248,243,.22)', paddingTop: 14, display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span className="dv-dim">SUBTOTAL</span><span>$20.00</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span className="dv-dim">TAX</span><span>Calculated at payment</span></div>
        </div>
      </div>
    </div>
  );
}

function NotifTab({ me, onSaved, onError }: Saver) {
  const prefs = { ...NOTIF_DEFAULTS, ...me.notification_prefs };
  async function toggle(key: string) {
    try {
      onSaved(await api.updateMe({ notification_prefs: { [key]: !prefs[key] } }));
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }
  return (
    <div className="dv-rise">
      <Head kicker="05 · NOTIFICATIONS" title="Only when it's your move." lede="Email only, and not switched on yet during the beta. Your choices are saved and apply from the first email Deno sends — only when something needs a human." />
      <div style={{ padding: 'clamp(14px,2vw,24px) clamp(22px,3vw,40px) clamp(22px,3vw,40px)' }}>
        {NOTIFS.map(([key, label, desc]) => (
          <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '16px 0', borderBottom: '1px solid rgba(16,22,19,.16)' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{label}</div>
              <div style={{ fontSize: 13.5, color: 'var(--muted)', marginTop: 3, lineHeight: 1.45 }}>{desc}</div>
            </div>
            <button className={`dv-toggle${prefs[key] ? ' on' : ''}`} aria-label={label} aria-pressed={prefs[key]} onClick={() => toggle(key)}>
              <span />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function SecurityTab({ onError }: { onError: (m: string) => void }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const [mfa, setMfa] = useState<{ enrolled: boolean; qr?: string; factorId?: string; code: string }>({ enrolled: false, code: '' });

  useEffect(() => {
    createClient()
      ?.auth.mfa.listFactors()
      .then(({ data }) => setMfa((m) => ({ ...m, enrolled: Boolean(data?.totp.some((f) => f.status === 'verified')) })))
      .catch(() => undefined);
  }, []);

  async function changePassword() {
    const supabase = createClient();
    if (!supabase) return onError('Login is not configured.');
    if (next.length < 10) return onError('New passwords need at least 10 characters.');
    const { data } = await supabase.auth.getUser();
    const email = data.user?.email;
    if (!email) return onError('Signed in without a password (e.g. Google). Use “Forgot password” to set one.');
    const check = await supabase.auth.signInWithPassword({ email, password: current });
    if (check.error) return onError('Your current password is not right.');
    const { error } = await supabase.auth.updateUser({ password: next });
    if (error) return onError(error.message);
    setCurrent('');
    setNext('');
    setDone('Password updated.');
  }

  async function signOutOthers() {
    const { error } = (await createClient()?.auth.signOut({ scope: 'others' })) ?? { error: null };
    if (error) return onError(error.message);
    setDone('Signed out of every other device.');
  }

  async function startMfa() {
    const supabase = createClient();
    if (!supabase) return;
    const { data, error } = await supabase.auth.mfa.enroll({ factorType: 'totp' });
    if (error) return onError(error.message);
    setMfa({ enrolled: false, qr: data.totp.qr_code, factorId: data.id, code: '' });
  }

  async function verifyMfa() {
    const supabase = createClient();
    if (!supabase || !mfa.factorId) return;
    const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId: mfa.factorId, code: mfa.code.trim() });
    if (error) return onError('That code did not match. Try the next one from your app.');
    setMfa({ enrolled: true, code: '' });
    setDone('Two-factor authentication is on.');
  }

  return (
    <div className="dv-rise">
      <Head kicker="06 · SECURITY" title="Login and sessions." />
      <div className="dv-split">
        <div className="dv-pad dv-rr dv-cell">
          <div className="dv-label" style={{ marginBottom: 0 }}>CHANGE PASSWORD</div>
          <input className="dv-input" type="password" placeholder="Current password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          <input className="dv-input" type="password" placeholder="New password · 10+ characters" value={next} onChange={(e) => setNext(e.target.value)} />
          <button className="dv-btn ink" style={{ alignSelf: 'flex-start' }} onClick={changePassword}>Update password</button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, border: '1.5px solid var(--ink)', padding: 14, marginTop: 10, background: mfa.enrolled ? 'var(--green-soft)' : 'var(--paper)' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 600 }}>Two-factor authentication</div>
              <div className="dv-mono" style={{ fontSize: 10.5, letterSpacing: '.06em', marginTop: 4, color: mfa.enrolled ? 'var(--green)' : 'var(--red-ink)' }}>
                {mfa.enrolled ? 'ON · AUTHENTICATOR APP' : 'OFF · RECOMMENDED'}
              </div>
            </div>
            {!mfa.enrolled && !mfa.qr && <button className={`dv-toggle`} aria-label="Turn on two-factor" onClick={startMfa}><span /></button>}
            {mfa.enrolled && <span className="dv-toggle on" aria-hidden><span /></span>}
          </div>
          {mfa.qr && !mfa.enrolled && (
            <div className="dv-card dv-cell">
              <span style={{ fontSize: 13.5 }}>Scan with your authenticator app, then enter the 6-digit code.</span>
              <img src={mfa.qr} alt="Two-factor QR code" width={160} height={160} />
              <div style={{ display: 'flex', gap: 8 }}>
                <input className="dv-input" inputMode="numeric" placeholder="123456" value={mfa.code} onChange={(e) => setMfa({ ...mfa, code: e.target.value })} />
                <button className="dv-btn ink" onClick={verifyMfa}>Verify</button>
              </div>
            </div>
          )}
        </div>
        <div className="dv-pad dv-cell">
          <div className="dv-label" style={{ marginBottom: 0 }}>SESSIONS</div>
          <div className="dv-card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14.5, fontWeight: 600 }}>This browser</div>
              <div className="dv-mono" style={{ fontSize: 10.5, color: 'var(--muted)', marginTop: 3 }}>ACTIVE NOW</div>
            </div>
            <span className="dv-mono" style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', background: 'var(--green-soft)', padding: '4px 7px' }}>THIS DEVICE</span>
          </div>
          <button className="dv-btn ghost" style={{ alignSelf: 'flex-start', color: 'var(--red-ink)', borderColor: 'var(--red-ink)' }} onClick={signOutOthers}>
            Sign out of all other devices
          </button>
          {done && <span className="dv-mono dv-rise" style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--green)' }}>✓ {done.toUpperCase()}</span>}
        </div>
      </div>
    </div>
  );
}

function DataTab({ onError }: { onError: (m: string) => void }) {
  const [confirm, setConfirm] = useState('');
  const [exported, setExported] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function doExport() {
    try {
      const data = await api.exportData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'deno-export.json';
      link.click();
      URL.revokeObjectURL(link.href);
      setExported(true);
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  async function doDelete() {
    if (confirm !== 'DELETE') return;
    setDeleting(true);
    try {
      await api.deleteAccount();
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = '/auth/signout';
      document.body.appendChild(form);
      form.submit();
    } catch (err) {
      setDeleting(false);
      onError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="dv-rise">
      <Head kicker="07 · DATA & PRIVACY" title="Your data leaves when you do." lede="Download everything Deno stores about you, or delete it all. Deletion is permanent and also removes your login." />
      <div className="dv-split">
        <div className="dv-pad dv-rr dv-cell" style={{ alignItems: 'flex-start' }}>
          <div className="dv-serif" style={{ fontSize: 26, lineHeight: 1.1 }}>Export</div>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55, color: 'var(--ink-3)' }}>Projects, verdicts, source ledgers, drafts, Story Bank and voice fingerprint as one JSON file.</p>
          <button className="dv-btn ghost" onClick={doExport}>{exported ? '✓ deno-export.json downloaded' : 'Download my data'}</button>
          <a href="/takedown" className="dv-link" style={{ marginTop: 10 }}>Request a takedown for a third party →</a>
        </div>
        <div className="dv-pad dv-cell" style={{ background: 'var(--red-soft)' }}>
          <div className="dv-serif" style={{ fontSize: 26, lineHeight: 1.1, color: 'var(--red-ink)' }}>Delete account</div>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55, color: '#3A2A22' }}>Removes every project, report, draft and your login. This can&apos;t be undone.</p>
          <label className="dv-label" style={{ marginTop: 4, marginBottom: 0 }}>TYPE DELETE TO CONFIRM</label>
          <input className="dv-input" style={{ borderColor: 'var(--red-ink)', fontFamily: 'var(--mono)' }} placeholder="DELETE" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button className="dv-btn danger" style={{ alignSelf: 'flex-start' }} disabled={confirm !== 'DELETE' || deleting} onClick={doDelete}>
            {deleting ? 'Deleting…' : 'Delete account permanently'}
          </button>
        </div>
      </div>
    </div>
  );
}
