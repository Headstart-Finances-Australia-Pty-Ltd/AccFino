import React, { useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import { Async, Section, Table, StatusBadge, useLoad, act, Input, Select, useForm } from '../components/kit.jsx'
import * as api from '../lib/practiceApi.js'
import { label } from '../lib/format.js'

export default function PortalTab({ can }) {
  const [clientId, setClientId] = useState('')
  const cid = Number(clientId) || undefined
  const reqs = useLoad(() => api.portal.requests({ client_id: cid }), [cid])
  const invs = useLoad(() => (cid ? api.portal.invites(cid) : Promise.resolve([])), [cid])
  const msgs = useLoad(() => (cid ? api.portal.messages(cid) : Promise.resolve([])), [cid])
  const deliv = useLoad(() => (cid ? api.portal.deliveries(cid) : Promise.resolve([])), [cid])
  const acc = useLoad(() => (cid ? api.portal.access(cid) : Promise.resolve([])), [cid])
  const [inv, setInv] = useForm({ contact_id: '' })
  const [rq, setRq] = useForm({ title: '', item: '' })
  const [m, setM] = useForm({ body: '', visibility: 'client' })
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/practice/bulk" areas={["Client Portal"]} onDone={() => window.location.reload()} /></div>
      <Input label="Client id" type="number" value={clientId} onChange={e => setClientId(e.target.value)} hint="Choose a client to manage its portal" />
      <Section title="Client requests" hint="Information and documents you have asked the client for">
        <Async q={reqs}>{rows => (
          <>{rows.length === 0 ? <div className="text-muted">No requests</div> : rows.map(r => (
            <div key={r.id} style={{ marginBottom: 8 }}><b>{r.title}</b> <StatusBadge status={r.status === 'accepted' ? 'approved' : r.status === 'submitted' ? 'submitted' : 'draft'} text={label(r.status)} /> <span className="text-xs text-muted">client {r.client_id}</span>
              {r.items.map(i => <div key={i.id} className="text-sm" style={{ marginLeft: 12 }}>{i.description} — {label(i.status)}{i.response_text ? `: "${i.response_text}"` : ''}{i.review_note ? ` (note: ${i.review_note})` : ''}
                {i.status === 'submitted' && can('portal') && <> <button className="btn btn-outline btn-sm" onClick={async () => { if (await act(() => api.portal.reviewItem(i.id, 'accepted', ''), 'Accepted')) reqs.reload() }}>Accept</button>
                  <button className="btn btn-outline btn-sm" onClick={async () => { const n = window.prompt('Tell the client why', ''); if (n && await act(() => api.portal.reviewItem(i.id, 'rejected', n), 'Sent back')) reqs.reload() }}>Reject</button></>}</div>)}</div>))}</>)}
        </Async>
        {can('portal') && cid && <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}><Input label="Request title" value={rq.title} onChange={setRq('title')} /><Input label="First item" value={rq.item} onChange={setRq('item')} />
          <button className="btn btn-primary btn-sm" disabled={!rq.title || !rq.item} onClick={async () => { if (await act(() => api.portal.createRequest({ client_id: cid, title: rq.title, items: [{ description: rq.item, response_types: 'file,text' }] }), 'Request sent')) { setRq('title')(''); setRq('item')(''); reqs.reload() } }}>Send request</button></div>}
      </Section>
      {cid && <>
        <Section title="Invitations" hint="Single-use, expiring links. The link is emailed to the contact and is never shown here.">
          <Async q={invs}>{rows => <Table caption="Invitations" rows={rows} empty="No invitations" columns={[{ key: 'email', label: 'Email' }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status === 'accepted' ? 'approved' : 'draft'} text={label(r.status)} /> },
            { key: 'expires_at', label: 'Expires', date: true }, { key: 'send_count', label: 'Sent' }, { key: 'x', label: '', render: r => can('portal') && r.status !== 'accepted' && <span className="flex gap-1">
              <button className="btn btn-outline btn-sm" onClick={async () => { if (await act(() => api.portal.resend(r.id), 'Invitation resent')) invs.reload() }}>Resend</button>
              {r.status === 'pending' && <button className="btn btn-outline btn-sm" onClick={async () => { if (await act(() => api.portal.revokeInvite(r.id), 'Revoked')) invs.reload() }}>Revoke</button>}</span> }]} />}</Async>
          {can('portal') && <div className="flex items-center gap-1"><Input label="Contact id" type="number" value={inv.contact_id} onChange={setInv('contact_id')} />
            <button className="btn btn-outline btn-sm" disabled={!inv.contact_id} onClick={async () => { if (await act(() => api.portal.invite(cid, Number(inv.contact_id)), 'Invitation sent')) invs.reload() }}>Invite to portal</button></div>}
        </Section>
        <Section title="People with portal access">
          <Async q={acc}>{rows => <Table caption="Portal access" rows={rows} empty="Nobody has access" columns={[{ key: 'contact_id', label: 'Contact' }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status === 'active' ? 'active' : 'archived'} text={r.status} /> },
            { key: 'granted_at', label: 'Granted', date: true }, { key: 'x', label: '', render: r => can('portal') && r.status === 'active' && <button className="btn btn-outline btn-sm" onClick={async () => { if (await act(() => api.portal.revokeAccess(r.id), 'Access revoked')) acc.reload() }}>Revoke now</button> }]} />}</Async>
        </Section>
        <Section title="Messages" hint="Internal messages are never visible to the client">
          <Async q={msgs}>{rows => rows.map(x => <div key={x.id} className="text-sm"><span className={`badge ${x.visibility === 'internal' ? 'badge-warning' : 'badge-info'}`}>{x.visibility === 'internal' ? 'Internal only' : 'Visible to client'}</span> {x.author_kind}: {x.body}</div>)}</Async>
          <div className="flex items-center gap-1" style={{ marginTop: 8 }}><input className="input" aria-label="Message" value={m.body} onChange={setM('body')} /><Select label="Visibility" value={m.visibility} onChange={setM('visibility')} options={[{ value: 'client', label: 'Visible to client' }, { value: 'internal', label: 'Internal only' }]} />
            <button className="btn btn-outline btn-sm" disabled={!m.body} onClick={async () => { if (await act(() => api.portal.post(cid, m.body, m.visibility), 'Posted')) { setM('body')(''); msgs.reload(); deliv.reload() } }}>Post</button></div>
        </Section>
        <Section title="Notification delivery" actions={can('portal') && <button className="btn btn-outline btn-sm" onClick={async () => { const r = await act(() => api.portal.retryDeliveries()); if (r) deliv.reload() }}>Retry failed</button>}>
          <Async q={deliv}>{rows => <Table caption="Deliveries" rows={rows} empty="Nothing sent yet" columns={[{ key: 'subject', label: 'Subject' }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status === 'sent' ? 'approved' : r.status === 'failed' ? 'high' : 'draft'} text={r.status} /> }, { key: 'attempts', label: 'Attempts' }, { key: 'last_error', label: 'Last error' }]} />}</Async>
        </Section></>}
    </div>)
}
