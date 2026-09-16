import { useCallback, useEffect, useState } from 'react'
import './App.css'

const API = 'http://localhost:8000'

function formatBytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export default function App() {
  const [token, setToken] = useState(null)
  const [username, setUsername] = useState('alice')
  const [password, setPassword] = useState('alice-password')
  const [files, setFiles] = useState([])
  const [links, setLinks] = useState({})
  const [audit, setAudit] = useState(null)
  const [ttl, setTtl] = useState(300)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const logout = useCallback((message) => {
    setToken(null)
    setFiles([])
    setLinks({})
    setAudit(null)
    if (message) setError(message)
  }, [])

  const request = useCallback(
    async (path, options = {}) => {
      const headers = { ...(options.headers || {}) }
      if (token) headers.Authorization = `Bearer ${token}`

      const resp = await fetch(`${API}${path}`, { ...options, headers })

      if (resp.status === 401) {
        logout('Session expired — please sign in again.')
        throw new Error('unauthorized')
      }
      if (!resp.ok) {
        let detail = `Request failed (${resp.status})`
        try {
          const body = await resp.json()
          if (body.detail) detail = body.detail
        } catch {
          /* non-JSON error body */
        }
        throw new Error(detail)
      }
      return resp.status === 204 ? null : resp.json()
    },
    [token, logout],
  )

  const loadFiles = useCallback(async () => {
    try {
      setFiles(await request('/files'))
    } catch (e) {
      if (e.message !== 'unauthorized') setError(e.message)
    }
  }, [request])

  useEffect(() => {
    if (token) loadFiles()
  }, [token, loadFiles])

  async function login(e) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const resp = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!resp.ok) throw new Error('Invalid username or password')
      const data = await resp.json()
      setToken(data.access_token)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function upload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setBusy(true)
    const body = new FormData()
    body.append('file', file)
    try {
      await request('/files', { method: 'POST', body })
      await loadFiles()
    } catch (err) {
      if (err.message !== 'unauthorized') setError(err.message)
    } finally {
      setBusy(false)
      e.target.value = ''
    }
  }

  async function sign(id) {
    setError(null)
    try {
      const data = await request(`/files/${id}/sign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ttl_seconds: Number(ttl) }),
      })
      setLinks((prev) => ({ ...prev, [id]: data }))
    } catch (e) {
      if (e.message !== 'unauthorized') setError(e.message)
    }
  }

  async function remove(id) {
    setError(null)
    try {
      await request(`/files/${id}`, { method: 'DELETE' })
      setLinks((prev) => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      if (audit?.id === id) setAudit(null)
      await loadFiles()
    } catch (e) {
      if (e.message !== 'unauthorized') setError(e.message)
    }
  }

  async function showAudit(id) {
    if (audit?.id === id) return setAudit(null)
    setError(null)
    try {
      const events = await request(`/files/${id}/audit`)
      setAudit({ id, events })
    } catch (e) {
      if (e.message !== 'unauthorized') setError(e.message)
    }
  }

  if (!token) {
    return (
      <div className="shell">
        <div className="card login">
          <h1>Secure File Sharing</h1>
          <p className="muted">Sign in to upload files and generate signed links.</p>
          <form onSubmit={login}>
            <label>
              Username
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
            </label>
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button type="submit" disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          {error && <div className="error">{error}</div>}
          <p className="hint">Demo users: alice / bob</p>
        </div>
      </div>
    )
  }

  return (
    <div className="shell">
      <header>
        <h1>Secure File Sharing</h1>
        <button className="ghost" onClick={() => logout(null)}>
          Sign out
        </button>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <h2>Upload</h2>
        <input type="file" onChange={upload} disabled={busy} />
        {busy && <span className="muted"> uploading…</span>}
      </div>

      <div className="card">
        <div className="row-between">
          <h2>Your files</h2>
          <label className="ttl">
            Link TTL (seconds)
            <input
              type="number"
              min="1"
              max="86400"
              value={ttl}
              onChange={(e) => setTtl(e.target.value)}
            />
          </label>
        </div>

        {files.length === 0 ? (
          <p className="muted">No files yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Size</th>
                <th>Uploaded</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.id}>
                  <td className="name">{f.original_filename}</td>
                  <td>{formatBytes(f.size_bytes)}</td>
                  <td className="muted">
                    {new Date(f.created_at).toLocaleString()}
                  </td>
                  <td className="actions">
                    <button onClick={() => sign(f.id)}>Sign link</button>
                    <button className="ghost" onClick={() => showAudit(f.id)}>
                      Audit
                    </button>
                    <button className="danger" onClick={() => remove(f.id)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {Object.entries(links).length > 0 && (
        <div className="card">
          <h2>Signed links</h2>
          {Object.entries(links).map(([id, link]) => (
            <div key={id} className="link">
              <div className="muted">
                File #{id} — expires {new Date(link.expires_at).toLocaleTimeString()}{' '}
                (TTL {link.ttl_seconds}s)
              </div>
              <code>{link.download_url}</code>
              <div className="actions">
                <a href={link.download_url} target="_blank" rel="noreferrer">
                  <button>Download</button>
                </a>
                <button
                  className="ghost"
                  onClick={() => navigator.clipboard?.writeText(link.download_url)}
                >
                  Copy
                </button>
              </div>
            </div>
          ))}
          <p className="hint">
            These links carry no credentials — the signature is the authorization.
            They work in any browser until they expire.
          </p>
        </div>
      )}

      {audit && (
        <div className="card">
          <h2>Audit trail — file #{audit.id}</h2>
          {audit.events.length === 0 ? (
            <p className="muted">No events.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Event</th>
                  <th>TTL</th>
                  <th>Expires</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {audit.events.map((ev) => (
                  <tr key={ev.id}>
                    <td>
                      <span className={`tag ${ev.event_type}`}>{ev.event_type}</span>
                    </td>
                    <td>{ev.ttl_seconds ?? '—'}</td>
                    <td className="muted">
                      {ev.expires_at
                        ? new Date(ev.expires_at).toLocaleTimeString()
                        : '—'}
                    </td>
                    <td className="muted">
                      {new Date(ev.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
