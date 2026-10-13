/**
 * Sign-in and roles (ROLE-BASED ACCESS, 2026-10-13) - see app/auth.py.
 *
 * <AuthGate> asks the server who is signed in. Nobody: the sign-in page.
 * Somebody: the dashboard, with {email, role} available through useAuth().
 * The session itself is two HttpOnly cookies set by the server, so this code
 * never holds a token; every fetch the dashboard makes carries them.
 *
 * A request that comes back 401 later (the session ended) fires
 * "eds:auth-required" (api/client.js), which brings the sign-in page back.
 *
 * <RevealContact> is the manager's "Show" for one record's phone and email.
 * It renders nothing for anyone else, and the server refuses them anyway.
 */

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { LogIn, Eye, Loader2 } from 'lucide-react';

const AuthContext = createContext({ user: null, signOut: () => {} });
export const useAuth = () => useContext(AuthContext);
export const isManager = user => user?.role === 'manager';

async function postJson(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
  return data;
}

export function AuthGate({ children }) {
  // undefined: still asking; null: nobody signed in; {email, role}: signed in.
  const [user, setUser] = useState(undefined);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/auth/me')
      .then(async res => {
        if (cancelled) return;
        if (res.ok) setUser(await res.json());
        else {
          if (res.status === 403) {
            const d = await res.json().catch(() => ({}));
            setNotice(d.detail || null);
          }
          setUser(null);
        }
      })
      .catch(() => { if (!cancelled) setUser(null); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const ended = () => {
      setNotice('Your session ended. Sign in again.');
      setUser(null);
    };
    window.addEventListener('eds:auth-required', ended);
    return () => window.removeEventListener('eds:auth-required', ended);
  }, []);

  const signOut = useCallback(async () => {
    await postJson('/api/auth/logout').catch(() => {});
    setNotice(null);
    setUser(null);
  }, []);

  if (user === undefined) {
    return <div style={{ minHeight: '100vh', background: 'var(--page)' }} />;
  }
  if (user === null) {
    return <SignIn notice={notice} onSignedIn={u => { setNotice(null); setUser(u); }} />;
  }
  return (
    <AuthContext.Provider value={{ user, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

function SignIn({ notice, onSignedIn }) {
  // The dashboard applies the saved light/dark choice when it mounts; this
  // page comes before it, so it applies the same choice itself (light unless
  // the user picked Night sheet) - otherwise it always opened dark.
  useEffect(() => {
    let theme = 'light';
    try { theme = localStorage.getItem('dsr.theme') || 'light'; } catch { /* private mode */ }
    if (theme === 'dark') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', 'light');
  }, []);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async e => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await postJson('/api/auth/login', { email: email.trim(), password }));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--page)', padding: 16,
    }}>
      <form onSubmit={submit} className="xp-panel" style={{
        width: '100%', maxWidth: 380, padding: 28, background: 'var(--surface)',
        border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-md)',
      }}>
        <div style={{ fontSize: 'var(--fs-head)', fontWeight: 600, color: 'var(--ink)' }}>
          Volkswagen Elite Motors
        </div>
        <div style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-muted)', margin: '4px 0 22px' }}>
          Sign in to the sales dashboard
        </div>

        {notice && !error && (
          <div role="status" style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-2)', marginBottom: 14 }}>
            {notice}
          </div>
        )}

        <label className="field">
          <span>Email</span>
          <input type="email" autoComplete="username" required autoFocus
                 value={email} onChange={e => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" autoComplete="current-password" required
                 value={password} onChange={e => setPassword(e.target.value)} />
        </label>

        {error && (
          <div role="alert" style={{ fontSize: 'var(--fs-small)', color: 'var(--critical)', marginBottom: 14 }}>
            {error}
          </div>
        )}

        <button type="submit" className="primary" disabled={busy}
                style={{ width: '100%', display: 'inline-flex', alignItems: 'center',
                         justifyContent: 'center', gap: 8 }}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <LogIn size={15} />}
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}

/**
 * A manager's "Show" for one record. `table` is lead, booking or registration;
 * `id` is that record's id. Revealing is logged on the server.
 */
export function RevealContact({ table, id }) {
  const { user } = useAuth();
  const [state, setState] = useState({ status: 'idle', data: null, error: null });
  if (!isManager(user) || id == null) return null;

  const show = async e => {
    e.stopPropagation();
    setState({ status: 'loading', data: null, error: null });
    try {
      setState({ status: 'shown', data: await postJson('/api/pii/reveal', { table, id }), error: null });
    } catch (err) {
      setState({ status: 'error', data: null, error: err.message });
    }
  };

  if (state.status === 'shown') {
    const d = state.data;
    if (!d.encrypted) {
      return <span title={d.note} style={{ color: 'var(--ink-muted)', fontSize: 'var(--fs-small)' }}>
        Not on record
      </span>;
    }
    return (
      <span style={{ display: 'inline-flex', flexDirection: 'column', fontSize: 'var(--fs-small)',
                     color: 'var(--ink)', userSelect: 'all' }}>
        {d.phone && <span>{d.phone}</span>}
        {d.email && <span>{d.email}</span>}
      </span>
    );
  }
  return (
    <button onClick={show} disabled={state.status === 'loading'}
            title={state.error || 'Show the full phone number and email (logged)'}
            style={{ padding: '2px 8px', fontSize: 'var(--fs-small)', display: 'inline-flex',
                     alignItems: 'center', gap: 5,
                     color: state.status === 'error' ? 'var(--critical)' : undefined }}>
      {state.status === 'loading' ? <Loader2 size={12} className="animate-spin" /> : <Eye size={12} />}
      {state.status === 'error' ? 'Retry' : 'Show'}
    </button>
  );
}

/* A records-table column with the reveal in it - managers only. Its value is
   empty, so search, sort and CSV export never carry a revealed contact. */
export function contactColumn(table, rowId) {
  return {
    key: '_contact', label: 'Contact',
    render: r => <RevealContact table={table} id={rowId(r)} />,
    value: () => '',
  };
}
