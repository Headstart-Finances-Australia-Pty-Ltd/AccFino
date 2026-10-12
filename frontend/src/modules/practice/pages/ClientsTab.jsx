import React, { useRef, useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import { Async, Section, Table, StatusBadge, useLoad, act, Input, Select, useForm, Modal, EmptyState } from '../components/kit.jsx'
import * as api from '../lib/practiceApi.js'
import { saveBlob } from '../lib/useMe.js'

const STATUSES = ['active', 'inactive', 'archived']
const SERVICES = ['bookkeeping', 'financial_statements', 'tax_return', 'bas', 'payroll', 'advisory', 'other']

function ClientDetail({ id, can, onClose, onChanged }) {
  const q = useLoad(() => api.clients.get(id), [id])
  const [n, setN] = useForm({ body: '' })
  const [c, setC] = useForm({ full_name: '', email: '', can_use_portal: false, can_receive_documents: false, is_authorised_rep: false })
  const [i, setI] = useForm({ kind: 'abn', value: '' })
  const [shown, setShown] = useState({})
  return (
    <Modal title="Client" onClose={onClose} wide>
      <Async q={q}>{d => (
        <>
          <h4 style={{ margin: 0 }}>{d.legal_name} <StatusBadge status={d.status} /></h4>
          <div className="text-sm text-muted">{d.ref} · {d.client_type} · {d.email || 'no email'} · {d.open_jobs} open job(s) · {d.outstanding_requests} outstanding request(s)</div>
          <Section title="Tax identifiers" hint="Stored sealed. Revealing is permission-gated and audited.">
            {d.identifiers.length === 0 ? <div className="text-muted text-sm">None recorded</div> : d.identifiers.map(x => (
              <div key={x.kind} className="flex items-center gap-1"><b>{x.kind.toUpperCase()}</b> <span className="mono">{shown[x.kind] || x.masked}</span> <span className="text-xs text-muted">{x.verified ? 'Verified' : 'Unverified (entered by staff)'}</span>
                {can('tax_ids') && <button className="btn btn-outline btn-sm" onClick={async () => { const r = await act(() => api.clients.reveal(id, x.kind)); if (r) setShown(s => ({ ...s, [x.kind]: r.value })) }}>Reveal</button>}</div>))}
            {can('clients_edit') && <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}><Select label="Type" value={i.kind} onChange={setI('kind')} options={['abn', 'acn', 'tfn']} /><Input label="Value" value={i.value} onChange={setI('value')} />
              <button className="btn btn-outline btn-sm" disabled={!i.value} onClick={async () => { if (await act(() => api.clients.setIdentifier(id, i), 'Saved')) { setI('value')(''); q.reload() } }}>Save identifier</button></div>}
          </Section>
          <Section title="Entities and structure">
            <Table caption="Entities" rows={d.entities} empty="No entities linked" columns={[{ key: 'name', label: 'Name' }, { key: 'entity_type', label: 'Type' }, { key: 'relationship', label: 'Relationship' },
              { key: 'verified_label', label: 'Verification' }]} />
          </Section>
          <Section title="Contacts and authority">
            <Table caption="Contacts" rows={d.contacts} empty="No contacts" columns={[{ key: 'full_name', label: 'Name' }, { key: 'email', label: 'Email' }, { key: 'is_primary', label: 'Primary', render: r => (r.is_primary ? 'Yes' : '') },
              { key: 'is_authorised_rep', label: 'Auth. rep', render: r => (r.is_authorised_rep ? 'Yes' : '') }, { key: 'can_use_portal', label: 'Portal', render: r => (r.can_use_portal ? 'Yes' : '') }]} />
            {can('clients_edit') && <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}><Input label="Name" value={c.full_name} onChange={setC('full_name')} /><Input label="Email" value={c.email} onChange={setC('email')} />
              <label className="text-sm"><input type="checkbox" checked={c.is_authorised_rep} onChange={setC('is_authorised_rep')} /> Authorised rep</label>
              <label className="text-sm"><input type="checkbox" checked={c.can_use_portal} onChange={setC('can_use_portal')} /> May use portal</label>
              <button className="btn btn-outline btn-sm" disabled={!c.full_name} onClick={async () => { if (await act(() => api.clients.addContact(id, c), 'Contact added')) q.reload() }}>Add contact</button></div>}
          </Section>
          <Section title="Contact history (internal)">
            {d.history.map((h, k) => <div key={k} className="text-sm"><span className="text-muted">{h.at?.slice(0, 10)}</span> {h.body}</div>)}
            <div className="flex gap-1"><input className="input" aria-label="File note" placeholder="Add an internal note" value={n.body} onChange={setN('body')} />
              <button className="btn btn-outline btn-sm" disabled={!n.body} onClick={async () => { if (await act(() => api.clients.addNote(id, n.body, 'note'), 'Note added')) { setN('body')(''); q.reload() } }}>Add</button></div>
          </Section>
          {can('clients_archive') && <div className="flex gap-1">{STATUSES.filter(s => s !== d.status).map(s => <button key={s} className="btn btn-outline btn-sm" onClick={async () => {
            const reason = window.prompt(`Reason for setting ${s}`, ''); if (reason !== null && await act(() => api.clients.setStatus(id, s, reason), `Client ${s}`)) { q.reload(); onChanged() } }}>Set {s}</button>)}</div>}
        </>)}
      </Async>
    </Modal>)
}

export default function ClientsTab({ can }) {
  const [f, set] = useForm({ q: '', status: 'active', service: '' })
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState('name')
  const q = useLoad(() => api.clients.search({ q: f.q || undefined, status: f.status || undefined, service: f.service || undefined, sort, page, size: 25 }), [f.q, f.status, f.service, sort, page])
  const dups = useLoad(() => (can('clients_edit') ? api.clients.duplicates('pending') : Promise.resolve([])), [])
  const [open, setOpen] = useState(null)
  const [adding, setAdding] = useState(false)
  const [nc, setNc] = useForm({ client_type: 'organisation', legal_name: '', email: '' })
  const [imp, setImp] = useState(null)
  const file = useRef(null)
  const create = async (allow = false) => {
    try { await api.clients.create(nc, allow); setAdding(false); q.reload() } catch (e) {
      if (e?.response?.status === 409 && !allow) { if (window.confirm(`${api.errMsg(e)}\n\nCreate anyway? (Duplicates are never merged automatically.)`)) create(true) } else await act(() => Promise.reject(e))
    } }
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/practice/bulk" areas={["Clients"]} onDone={() => window.location.reload()} /></div>
      <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginBottom: 10 }}>
        <input className="input" aria-label="Search clients" placeholder="Search name, reference, email" value={f.q} onChange={e => { set('q')(e); setPage(1) }} />
        <Select label="Status" value={f.status} onChange={e => { set('status')(e); setPage(1) }} options={STATUSES} blank="All" />
        <Select label="Service" value={f.service} onChange={e => { set('service')(e); setPage(1) }} options={SERVICES} blank="All" />
        <Select label="Sort" value={sort} onChange={e => setSort(e.target.value)} options={[{ value: 'name', label: 'Name' }, { value: 'ref', label: 'Reference' }, { value: 'updated', label: 'Last updated' }]} />
        {can('clients_edit') && <button className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>New client</button>}
        {can('import') && <><input ref={file} type="file" accept=".csv" aria-label="Import CSV" style={{ display: 'none' }} onChange={async e => { const fl = e.target.files[0]; if (fl) { const r = await act(() => api.clients.importCsv(fl, false)); if (r) setImp({ file: fl, r }) } }} />
          <button className="btn btn-outline btn-sm" onClick={() => file.current.click()}>Import CSV</button></>}
        <button className="btn btn-outline btn-sm" onClick={async () => { const b = await act(() => api.clients.exportCsv()); if (b) saveBlob('clients.csv', b) }}>Export CSV</button>
      </div>
      <Async q={q}>{d => (
        <>
          <Table caption="Clients" rows={d.items} empty="No clients match" hint="Clear the filters or add a client" onRowClick={r => setOpen(r.id)} columns={[
            { key: 'ref', label: 'Ref' }, { key: 'legal_name', label: 'Client' }, { key: 'client_type', label: 'Type' }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
            { key: 'service_lines', label: 'Services', render: r => (r.service_lines || []).join(', ') || '—' }, { key: 'manager_id', label: 'Manager' }]} />
          <div className="flex items-center gap-1" style={{ marginTop: 8 }}><button className="btn btn-outline btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="text-sm">Page {d.page} of {d.pages || 1} · {d.total} client(s)</span><button className="btn btn-outline btn-sm" disabled={page >= d.pages} onClick={() => setPage(page + 1)}>Next</button></div>
        </>)}
      </Async>
      {can('clients_edit') && dups.data && dups.data.length > 0 && <Section title="Possible duplicates awaiting review" hint="Nothing is merged automatically">
        {dups.data.map(x => <div key={x.id} className="flex items-center gap-1 text-sm"><span>{x.a.name} ↔ {x.b.name} (score {x.score})</span>
          {['not_duplicate', 'confirmed'].map(dc => <button key={dc} className="btn btn-outline btn-sm" onClick={async () => { if (await act(() => api.clients.reviewDuplicate(x.id, dc, ''), 'Recorded')) dups.reload() }}>{dc.replace('_', ' ')}</button>)}</div>)}</Section>}
      {open && <ClientDetail id={open} can={can} onClose={() => setOpen(null)} onChanged={q.reload} />}
      {adding && <Modal title="New client" onClose={() => setAdding(false)}>
        <Select label="Type" value={nc.client_type} onChange={setNc('client_type')} options={['organisation', 'individual']} /><Input label="Legal name" value={nc.legal_name} onChange={setNc('legal_name')} /><Input label="Email" value={nc.email} onChange={setNc('email')} />
        <button className="btn btn-primary" disabled={!nc.legal_name.trim()} onClick={() => create(false)}>Create client</button></Modal>}
      {imp && <Modal title="Import preview" onClose={() => setImp(null)}>
        <div>{imp.r.valid_rows} valid row(s), {imp.r.rejected.length} rejected.</div>
        {imp.r.rejected.map(x => <div key={x.row} className="text-sm" style={{ color: 'var(--danger)' }}>Row {x.row}: {x.error}</div>)}
        <button className="btn btn-primary" disabled={imp.r.valid_rows === 0 || imp.r.rejected.length > 0} onClick={async () => { const r = await act(() => api.clients.importCsv(imp.file, true), 'Imported'); if (r) { setImp(null); q.reload() } }}>Import {imp.r.valid_rows} client(s)</button>
        {imp.r.rejected.length > 0 && <div className="text-xs text-muted">Fix the rejected rows and re-upload; a file with errors is not imported.</div>}</Modal>}
    </div>)
}
