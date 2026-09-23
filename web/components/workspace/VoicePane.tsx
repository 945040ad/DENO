'use client';

import { useEffect, useState } from 'react';
import { api, type Story, type StoryCategory, type VoiceProfile, type VoiceSample } from '@/lib/api';
import { paneClass } from './paneClass';

const CATEGORY_LABEL: Record<StoryCategory, string> = {
  scar: 'SCAR',
  metric: 'METRIC',
  turning_point: 'TURNING POINT',
  defended_opinion: 'DEFENDED OPINION',
  customer_quote: 'CUSTOMER QUOTE',
};

function wordsPerSentence(samples: VoiceSample[]): string {
  const text = samples.map((s) => s.text).join(' ');
  const sentences = text.split(/[.!?]+\s/).filter((s) => s.trim());
  const words = text.split(/\s+/).filter(Boolean).length;
  return sentences.length ? (words / sentences.length).toFixed(1) : '—';
}

export function VoicePane({ active, onToast }: { active: boolean; onToast: (m: string) => void }) {
  const [samples, setSamples] = useState<VoiceSample[]>([]);
  const [profile, setProfile] = useState<VoiceProfile | null>(null);
  const [stories, setStories] = useState<Story[]>([]);
  const [sample, setSample] = useState('');
  const [category, setCategory] = useState<StoryCategory>('scar');
  const [headline, setHeadline] = useState('');
  const [numbers, setNumbers] = useState('');
  const [details, setDetails] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    Promise.all([api.voiceSamples(), api.voiceProfile(), api.stories()])
      .then(([s, p, st]) => {
        if (cancelled) return;
        setSamples(s);
        setProfile(p);
        setStories(st);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [active]);

  async function addSample() {
    if (sample.trim().split(/\s+/).length < 20) {
      onToast('Paste one of your own posts: at least 20 words.');
      return;
    }
    setBusy(true);
    try {
      const added = await api.addVoiceSample(sample.trim());
      const next = [...samples, added];
      setSamples(next);
      setSample('');
      if (next.length >= 3) {
        setProfile(await api.buildVoiceProfile());
        onToast('Voice profile updated.');
      } else {
        onToast(`Saved. Add ${3 - next.length} more to build your voice profile.`);
      }
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function addStory() {
    const nums = numbers
      .split(',')
      .map((n) => n.trim())
      .filter(Boolean);
    try {
      const story = await api.addStory({ category, headline: headline.trim(), details: details.trim(), numbers: nums });
      setStories([story, ...stories]);
      setHeadline('');
      setNumbers('');
      setDetails('');
      onToast('Added to your Story Bank.');
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    }
  }

  async function removeStory(id: string) {
    await api.deleteStory(id).catch(() => undefined);
    setStories(stories.filter((s) => s.id !== id));
  }

  return (
    <section className={paneClass(active)} id="voice-tab">
      <div className="section-title">
        <h2>Founder Voice Profile &amp; Story Bank</h2>
        <p>Drafts are checked against your own writing (Burrows&apos; Delta), and may only use numbers and stories you put in the Story Bank.</p>
      </div>

      <div className="two-col-grid">
        <div className="card">
          <h3>Stylometric Fingerprint</h3>
          <p className="card-desc">Built from posts you actually wrote. {profile ? (profile.strong ? 'Strong enough to block drafts that don’t sound like you.' : 'Advisory until you add 5+ longer posts.') : 'Add 3 or more to start.'}</p>
          <div className="stats-grid" id="stylometry-stats">
            <div className="stat-item"><span className="stat-num" id="stat-mean-len">{samples.length}</span><span className="stat-lbl">Your Samples</span></div>
            <div className="stat-item"><span className="stat-num" id="stat-ttr">{wordsPerSentence(samples)}</span><span className="stat-lbl">Mean Words/Sentence</span></div>
            <div className="stat-item"><span className="stat-num" id="stat-yules">{profile ? `v${profile.version}` : '—'}</span><span className="stat-lbl">Profile Version</span></div>
            <div className="stat-item"><span className="stat-num" id="stat-variance">{profile ? profile.threshold.toFixed(2) : '—'}</span><span className="stat-lbl">Delta Threshold</span></div>
          </div>
          <div className="input-group" style={{ marginTop: '1.5rem' }}>
            <label>Add a Post You Wrote (20+ words)</label>
            <textarea id="voice-sample-input" rows={3} placeholder="Paste a LinkedIn post, Reddit comment or email you wrote yourself..." value={sample} onChange={(e) => setSample(e.target.value)}></textarea>
            <button className="btn-secondary btn-sm" id="update-voice-btn" style={{ marginTop: '0.5rem' }} disabled={busy} onClick={addSample}>Add Sample &amp; Recalculate</button>
          </div>
        </div>

        <div className="card">
          <h3>Founder Story Bank</h3>
          <p className="card-desc">The only source of anecdotes and numbers drafts may use. Numbers must appear in the story text.</p>
          <div className="story-bank-input">
            <select id="sb-category" value={category} onChange={(e) => setCategory(e.target.value as StoryCategory)}>
              <option value="scar">SCAR (Past Failure/Hard Lesson)</option>
              <option value="metric">METRIC (Verifiable Number)</option>
              <option value="turning_point">TURNING POINT (Aha Moment)</option>
              <option value="defended_opinion">DEFENDED OPINION (Contrarian Stance)</option>
              <option value="customer_quote">CUSTOMER QUOTE (Their Words)</option>
            </select>
            <input type="text" id="sb-headline" placeholder="Headline: e.g. Spent 4 months building a feature no one used" value={headline} onChange={(e) => setHeadline(e.target.value)} />
            <input type="text" id="sb-numbers" placeholder="Numbers from the story, comma separated: e.g. 4 months, $14,000" value={numbers} onChange={(e) => setNumbers(e.target.value)} />
            <textarea id="sb-details" rows={2} placeholder="What happened, in your words..." value={details} onChange={(e) => setDetails(e.target.value)}></textarea>
            <button className="btn-primary btn-sm" id="add-story-entry-btn" onClick={addStory}>Add to Story Bank</button>
          </div>
          <div className="story-bank-entries" id="story-bank-list">
            {stories.map((s) => (
              <div className="story-entry-card" key={s.id}>
                <div className="story-entry-cat">{CATEGORY_LABEL[s.category]}{s.numbers.length ? ` · ${s.numbers.join(', ')}` : ''}</div>
                <div className="story-entry-head">{s.headline}</div>
                <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--ink-3)' }}>{s.details}</p>
                <button className="btn-ghost" style={{ padding: 0, fontSize: '0.75rem' }} onClick={() => removeStory(s.id)}>Remove</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
