import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../../core/hooks/useAuth.jsx'
import { Async, Section, Stat, Table, StatusBadge, Input, EmptyState, useLoad, useForm, act, Money } from '../components/kit.jsx'
import { clientPortal as api, errMsg } from '../lib/practiceApi.js'
import { saveBlob } from '../lib/useMe.js'

// Client-facing portal. Everything shown here is decided by the server for the signed-in client login; nothing is filtered in the browser.
const Shell = ({ children, title }) => (
  <div style={{ maxWidth: 980, margin: '0 auto', padding: 20 }}>
    <h2 style={{ marginTop: 0 }}>{title || 'Client portal'}</h2>
    {children}
  </div>)

// ---- /portal/accept : the token is in the URL fragment (never sent to a server in a URL) and is removed from the address bar after reading.
export function PortalAccept() {
  const { user } = useAuth()
  const [token] = useState(() => {
    const t = new URLSearchParams((window.location.hash || '').replace(/^#/, '')).get('token') || ''
    if (t) { try { window.history.replaceState(null, '', window.location.pathname) } catch { /* ignore */ } }
    return t
  })
  const [info, setInfo] = useState(null)
  const [err, setErr] = useState('')
  const [done, setDone] = useState(false)
  const [f, set] = useForm({ full_name: '', phone: '', password: '' })
  useEffect(() => { if (!token) { setErr('This invitation link is not valid.'); return } api.lookup(token).then(setInfo).catch(() => setErr('This invitation is invalid, expired or already used.')) }, [token])
  if (done) return <Shell title="Invitation accepted"><p>Your access has been set up. <Link to={user ? '/portal' : '/login'}>{user ? 'Open the portal' : 'Sign in'}</Link></p></Shell>
  if (err) return <Shell title="Invitation"><div role="alert" className="alert alert-error">{err}</div></Shell>
  if (!info) return <Shell title="Invitation"><p className="text-muted">Checking invitation…</p></Shell>
  return (
    <Shell title={`Join ${info.practice}`}>
      <p>You have been invited to the portal for <b>{info.client}</b> ({info.email}). The invitation expires {String(info.expires_at).slice(0, 10)}.</p>
      {info.account_exists
        ? <>
          <p>An account already exists for this email address. {user ? 'Accept the invitation with your current sign-in.' : <>Please <Link to="/login">sign in</Link>, then return to this link.</>}</p>
          {user && <button className="btn btn-primary" onClick={async () => { if (await act(() => api.claim(token), 'Invitation accepted')) setDone(true) }}>Accept invitation</button>}
        </>
        : <div style={{ maxWidth: 380 }}>
          <Input label="Full name" value={f.full_name} onChange={set('full_name')} />
          <Input label="Mobile phone" value={f.phone} onChange={set('phone')} />
          <Input label="Choose a password" type="password" value={f.password} onChange={set('password')} autoComplete="new-password" />
          <button className="btn btn-primary" disabled={!f.full_name || !f.password} onClick={async () => { if (await act(() => api.accept({ token, ...f }), 'Account created')) setDone(true) }}>Create account</button>
        </div>}
    </Shell>)
}

// ---- /portal
export default function PortalApp() {
  const { user } = useAuth()
  const clients = useLoad(() => (user ? api.clients() : Promise.resolve([])), [user?.token])
  const [cid, setCid] = useState(null)
  if (!user) return <Shell><p>Please <Link to="/login">sign in</Link> to open your portal.</p></Shell>
  return (
    <Shell>
      <Async q={clients}>{list => {
        if (!list.length) return <EmptyState icon="🔒" title="No portal access" hint="Your practice has not given this login access to any client, or access was withdrawn." />
        const id = cid || list[0].client_id
        return <>
          {list.length > 1 && <select className="input" aria-label="Client" value={id} onChange={e => setCid(Number(e.target.value))} style={{ maxWidth: 360, marginBottom: 12 }}>{list.map(c => <option key={c.client_id} value={c.client_id}>{c.name} ({c.practice})</option>)}</select>}
          <ClientView key={id} id={id} />
        </>
      }}</Async>
    </Shell>)
}

function ClientView({ id }) {
  const [tab, setTab] = useState('home')
  const tabs = [['home', 'Overview'], ['requests', 'Requests'], ['docs', 'Documents'], ['msgs', 'Messages'], ['inv', 'Invoices'], ['consent', 'Consent'], ['notes', 'Notifications']]
  return <>
    <div className="tabs-bar" style={{ flexWrap: 'wrap' }}>{tabs.map(([k, l]) => <button key={k} className={`tab-btn${tab === k ? ' active' : ''}`} onClick={() => setTab(k)}>{l}</button>)}</div>
    <div style={{ paddingTop: 12 }}>
      {tab === 'home' && <Home id={id} go={setTab} />}
      {tab === 'requests' && <Requests id={id} />}
      {tab === 'docs' && <Docs id={id} />}
      {tab === 'msgs' && <Messages id={id} />}
      {tab === 'inv' && <Invoices id={id} />}
      {tab === 'consent' && <Consent id={id} />}
      {tab === 'notes' && <Notes id={id} />}
    </div></>
}

function Home({ id, go }) {
  const q = useLoad(() => api.dashboard(id), [id])
  return <Async q={q}>{d => <>
    <p className="text-muted">{d.client.name} · {d.practice}</p>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10 }}>
      <Stat label="Open requests" value={d.open_requests} onClick={() => go('requests')} />
      <Stat label="Shared documents" value={d.shared_documents} onClick={() => go('docs')} />
      <Stat label="Messages from your practice" value={d.staff_messages} onClick={() => go('msgs')} />
      <Stat label="Invoices" value={d.invoices} onClick={() => go('inv')} />
      <Stat label="Unread notifications" value={d.unread_notifications} onClick={() => go('notes')} />
    </div></>}</Async>
}

function Item({ id, it, reload }) {
  const [text, setText] = useState('')
  const open = ['requested', 'rejected'].includes(it.status)
  return (
    <div style={{ borderTop: '1px solid var(--border)', padding: '8px 0' }}>
      <div className="flex items-center gap-1"><b>{it.description}</b> <StatusBadge status={it.status} /></div>
      {it.review_note && <div className="text-sm text-muted">Note from your practice: {it.review_note}</div>}
      {open && <div className="flex items-center gap-1" style={{ marginTop: 6, flexWrap: 'wrap' }}>
        {it.response_types.includes('file') && <input type="file" aria-label={`Upload for ${it.description}`} onChange={async e => { const f = e.target.files[0]; if (f && await act(() => api.uploadFile(id, it.id, f), 'File sent')) reload() }} />}
        {it.response_types.includes('text') && <>
          <input className="input" aria-label={`Answer for ${it.description}`} value={text} onChange={e => setText(e.target.value)} style={{ minWidth: 240 }} />
          <button className="btn btn-primary btn-sm" disabled={!text.trim()} onClick={async () => { if (await act(() => api.respondText(id, it.id, text), 'Answer sent')) reload() }}>Send answer</button></>}
      </div>}
    </div>)
}

function Requests({ id }) {
  const q = useLoad(() => api.requests(id), [id])
  return <Async q={q}>{rows => !rows.length ? <EmptyState icon="📭" title="No requests" hint="Your practice has not asked for anything right now." /> :
    rows.map(r => <Section key={r.id} title={`${r.title}${r.due_date ? ` · due ${r.due_date}` : ''}`}>
      {r.description && <p className="text-sm">{r.description}</p>}
      {(r.items || []).map(it => <Item key={it.id} id={id} it={it} reload={q.reload} />)}
    </Section>)}</Async>
}

function Docs({ id }) {
  const q = useLoad(() => api.documents(id), [id])
  return <Async q={q}>{d => <Table rows={d.items} empty="No documents have been shared with you" columns={[
    { key: 'title', label: 'Document' }, { key: 'category', label: 'Type' }, { key: 'file_name', label: 'File' },
    { key: 'uploaded_at', label: 'Added', render: r => String(r.uploaded_at || '').slice(0, 10) },
    { key: 'dl', label: '', render: r => <button className="btn btn-outline btn-sm" onClick={async () => { try { const x = await api.download(id, r.id); saveBlob(x.name || 'document', x.blob) } catch (e) { act(() => Promise.reject(e)) } }}>Download</button> }]} />}</Async>
}

function Messages({ id }) {
  const q = useLoad(() => api.messages(id), [id])
  const [body, setBody] = useState('')
  return <Async q={q}>{rows => <>
    {!rows.length && <EmptyState icon="💬" title="No messages yet" />}
    {rows.map(m => <div key={m.id} style={{ margin: '6px 0', textAlign: m.author_kind === 'client' ? 'right' : 'left' }}><span className="badge badge-neutral">{m.author_kind === 'client' ? 'You' : 'Practice'}</span> {m.body}</div>)}
    <div className="flex items-center gap-1" style={{ marginTop: 10 }}>
      <input className="input" aria-label="Message" value={body} onChange={e => setBody(e.target.value)} style={{ flex: 1 }} />
      <button className="btn btn-primary" disabled={!body.trim()} onClick={async () => { if (await act(() => api.postMessage(id, body), 'Message sent')) { setBody(''); q.reload() } }}>Send</button>
    </div></>}</Async>
}

function Invoices({ id }) {
  const q = useLoad(() => api.invoices(id), [id])
  return <Async q={q}>{rows => <Table rows={rows} empty="No invoices" columns={[
    { key: 'number', label: 'Number' }, { key: 'issue_date', label: 'Issued' }, { key: 'due_date', label: 'Due' },
    { key: 'total', label: 'Total', render: r => <Money v={r.total} /> }, { key: 'amount_due', label: 'Outstanding', render: r => r.amount_due === '' ? '' : <Money v={r.amount_due} /> }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> }]} />}</Async>
}

const CONSENTS = [['email_contact', 'Contact me by email'], ['share_with_accountant', 'Share my records with my accountant']]
function Consent({ id }) {
  const q = useLoad(() => api.consents(id), [id])
  return <Async q={q}>{rows => {
    const cur = {}; rows.forEach(r => { cur[r.key] = r.granted })
    return <>{CONSENTS.map(([k, l]) => <label key={k} style={{ display: 'block', margin: '8px 0' }}>
      <input type="checkbox" checked={!!cur[k]} onChange={async e => { if (await act(() => api.recordConsent(id, k, e.target.checked), 'Preference recorded')) q.reload() }} /> {l}</label>)}
      <p className="text-xs text-muted">Each change is recorded with the date and who made it.</p></>
  }}</Async>
}

function Notes({ id }) {
  const q = useLoad(() => api.notifications(id), [id])
  return <Async q={q}>{rows => <Table rows={rows} empty="No notifications" columns={[
    { key: 'subject', label: 'Subject', render: r => r.read ? r.subject : <b>{r.subject}</b> }, { key: 'created_at', label: 'Sent', render: r => String(r.created_at || '').slice(0, 10) },
    { key: 'r', label: '', render: r => !r.read && <button className="btn btn-outline btn-sm" onClick={async () => { if (await act(() => api.markRead(id, r.id))) q.reload() }}>Mark read</button> }]} />}</Async>
}
