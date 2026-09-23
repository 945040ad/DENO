'use client';

import { useEffect, useState } from 'react';
import { api, type Billing, type Me } from '@/lib/api';

const KIND_LABEL: Record<string, string> = { validation_run: 'Validation runs', content_plan: 'Content plans' };

export function AccountPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [billing, setBilling] = useState<Billing | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirm, setConfirm] = useState('');

  useEffect(() => {
    Promise.all([api.me(), api.billing()])
      .then(([m, b]) => {
        setMe(m);
        setBilling(b);
      })
      .catch((err) => setMessage(err instanceof Error ? err.message : String(err)));
  }, []);

  async function go(action: () => Promise<{ url: string }>) {
    try {
      window.location.href = (await action()).url;
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }

  async function exportData() {
    const data = await api.exportData();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'deno-export.json';
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function deleteAccount() {
    if (confirm !== 'DELETE') return;
    try {
      await api.deleteAccount();
      // Sign-out is POST-only (a GET could be triggered by any link).
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = '/auth/signout';
      document.body.appendChild(form);
      form.submit();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <div className="section-title">
        <h2>Account</h2>
        <p>{me?.email ?? 'Signed in'} · {billing ? (billing.plan === 'pro' ? 'Pro plan' : 'Free plan') : '…'}</p>
      </div>
      {message && <p style={{ color: 'var(--red-ink)' }}>{message}</p>}

      <div className="two-col-grid">
        <div className="card">
          <h3>Plan &amp; Usage This Month</h3>
          <div className="stats-grid">
            {billing?.usage.map((u) => (
              <div className="stat-item" key={u.kind}>
                <span className="stat-num">{u.used}{u.limit !== null ? ` / ${u.limit}` : ''}</span>
                <span className="stat-lbl">{KIND_LABEL[u.kind] ?? u.kind}</span>
              </div>
            ))}
          </div>
          <p className="card-desc" style={{ marginTop: '1rem' }}>
            {billing?.status === 'past_due' ? 'Your last payment failed. Update your card to keep Pro.' : ''}
            {billing?.current_period_end ? ` Renews ${new Date(billing.current_period_end).toLocaleDateString()}.` : ''}
          </p>
          <div className="button-group" style={{ marginTop: '1rem' }}>
            {billing?.plan !== 'pro' && (
              <button className="btn-primary" disabled={!billing?.billing_enabled} onClick={() => go(api.checkout)}>
                {billing?.billing_enabled ? 'Upgrade to Pro' : 'Upgrades open soon'}
              </button>
            )}
            {billing?.plan === 'pro' && (
              <button className="btn-secondary" onClick={() => go(api.portal)}>Manage Billing</button>
            )}
          </div>
        </div>

        <div className="card">
          <h3>Your Data</h3>
          <p className="card-desc">Download everything Deno stores about you, or delete it all. Deletion is permanent and also removes your login.</p>
          <div className="button-group" style={{ marginTop: '1rem' }}>
            <button className="btn-secondary" onClick={exportData}>Download My Data</button>
          </div>
          <div className="input-group" style={{ marginTop: '1.5rem' }}>
            <label htmlFor="delete-confirm">Type DELETE to remove your account</label>
            <input id="delete-confirm" type="text" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            <button className="btn-secondary" style={{ marginTop: '0.5rem', color: 'var(--red-ink)' }} disabled={confirm !== 'DELETE'} onClick={deleteAccount}>
              Delete Account
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
