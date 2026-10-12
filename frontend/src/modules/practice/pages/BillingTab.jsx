import React, { useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import { Async, Section, Stat, Table, StatusBadge, useLoad, act, Input, Select, useForm, Money, Modal } from '../components/kit.jsx'
import * as api from '../lib/practiceApi.js'
import { label, todayISO } from '../lib/format.js'

const TBADGE = { draft: 'draft', submitted: 'submitted', approved: 'approved', rejected: 'high', billed: 'approved', written_off: 'archived' }

function InvoiceView({ id, can, onClose, onChanged }) {
  const q = useLoad(() => api.billing.invoice(id), [id])
  const go = async (fn, msg) => { if (await act(fn, msg)) { q.reload(); onChanged() } }
  return (
    <Modal title="Invoice" onClose={onClose} wide>
      <Async q={q}>{i => (
        <>
          <h4 style={{ margin: 0 }}>{i.accounting_number || `Draft #${i.id}`} <StatusBadge status={i.status === 'issued' ? 'approved' : i.status === 'voided' ? 'archived' : 'draft'} text={label(i.status)} /></h4>
          <div className="text-sm text-muted">Client {i.client_id}{i.issue_date ? ` · issued ${i.issue_date}, due ${i.due_date}` : ''}{i.payment ? ` · ${i.payment.status}, owing $${i.payment.due}` : ''}</div>
          <Table caption="Invoice lines" rows={i.lines} columns={[{ key: 'description', label: 'Description' }, { key: 'kind', label: 'Type', render: r => label(r.kind) }, { key: 'amount', label: 'Amount (ex tax)', money: true }, { key: 'reason', label: 'Reason' }]} />
          <div className="text-right" style={{ marginTop: 6 }}>Net <Money v={i.net} /> · Tax <Money v={i.tax} /> · <b>Total <Money v={i.total} strong /></b></div>
          {can('billing_admin') && <div className="flex gap-1" style={{ marginTop: 8, flexWrap: 'wrap' }}>
            {i.status === 'draft' && <><button className="btn btn-primary btn-sm" onClick={() => go(() => api.billing.issue(id), 'Issued to the receivables ledger')}>Issue invoice</button>
              <button className="btn btn-outline btn-sm" onClick={() => { const a = window.prompt('Adjustment amount (negative for a discount)', ''); const r = a && window.prompt('Reason', ''); if (r) go(() => api.billing.adjust(id, { description: 'Adjustment', amount: a, reason: r }), 'Adjusted') }}>Add adjustment</button></>}
            {i.status === 'issued' && <><button className="btn btn-outline btn-sm" onClick={() => go(() => api.billing.share(id, !i.visible_to_client), 'Updated')}>{i.visible_to_client ? 'Hide from client' : 'Show to client'}</button>
              <button className="btn btn-outline btn-sm" onClick={() => { const a = window.prompt('Credit amount (ex tax)', ''); const r = a && window.prompt('Reason', ''); if (r) go(() => api.billing.creditNote(id, a, r), 'Credit note issued') }}>Credit note</button></>}
            {['draft', 'issued'].includes(i.status) && <button className="btn btn-outline btn-sm" onClick={() => { const r = window.prompt('Reason for voiding', ''); if (r) go(() => api.billing.void(id, r), 'Voided') }}>Void</button>}</div>}
        </>)}
      </Async>
    </Modal>)
}

export default function BillingTab({ can }) {
  const dash = useLoad(() => api.billing.dashboard(), [])
  const [status, setStatus] = useState('')
  const [mine, setMine] = useState(true)
  const time = useLoad(() => api.billing.time({ mine, status: status || undefined, size: 50 }), [mine, status])
  const invs = useLoad(() => api.billing.invoices({ size: 25 }), [])
  const rates = useLoad(() => api.billing.rates(), [])
  const [open, setOpen] = useState(null)
  const [t, setT] = useForm({ client_id: '', work_date: todayISO(), hours: '1', description: '', billable: true })
  const [sel, setSel] = useState([])
  const [g, setG] = useForm({ client_id: '' })
  const [r, setR] = useForm({ hourly_rate: '', staff_id: '', client_id: '', effective_from: todayISO() })
  const refresh = () => { time.reload(); dash.reload(); invs.reload() }
  const toggle = id => setSel(s => (s.includes(id) ? s.filter(x => x !== id) : [...s, id]))
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/practice/bulk" areas={["Billing"]} onDone={() => window.location.reload()} /></div>
      {can('billing') && <Async q={dash}>{d => (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10, marginBottom: 12 }}>
          <Stat label="Unbilled WIP" value={<Money v={d.wip} />} sub="Approved, billable, not invoiced" /><Stat label="On draft invoices" value={<Money v={d.drafted_unissued} />} />
          <Stat label="Awaiting approval" value={d.submitted_awaiting_approval.count} sub={`${(d.submitted_awaiting_approval.minutes / 60).toFixed(1)} h`} /><Stat label="Invoiced this month (ex tax)" value={<Money v={d.invoiced_net} />} />
          <Stat label="Written off" value={<Money v={d.written_off} />} /><Stat label="Realisation" value={d.realisation_pct == null ? 'n/a' : `${d.realisation_pct}%`} sub="billed ÷ (billed + written off)" />
          <Stat label="Receivables" value={<Money v={d.receivables} />} sub={<>Overdue <Money v={d.receivables_overdue} /></>} /></div>)}</Async>}
      <Section title="Time" actions={<><label className="text-sm"><input type="checkbox" checked={mine} onChange={e => setMine(e.target.checked)} /> Mine only</label>
        <Select label="Status" value={status} onChange={e => setStatus(e.target.value)} options={['draft', 'submitted', 'approved', 'rejected', 'billed', 'written_off']} blank="All" /></>}>
        <Async q={time}>{d => <Table caption="Time entries" rows={d.items} empty="No time recorded" columns={[
          { key: 'sel', label: '', render: r => <input type="checkbox" aria-label={`Select entry ${r.id}`} checked={sel.includes(r.id)} onChange={() => toggle(r.id)} /> }, { key: 'work_date', label: 'Date', date: true }, { key: 'client_id', label: 'Client' },
          { key: 'description', label: 'Work' }, { key: 'hours', label: 'Hours', align: 'right' }, { key: 'rate_applied', label: 'Rate', money: true }, { key: 'amount', label: 'Value', money: true },
          { key: 'status', label: 'Status', render: r => <StatusBadge status={TBADGE[r.status]} text={label(r.status) + (r.billable ? '' : ' (non-billable)')} /> }]} />}</Async>
        <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginTop: 8 }}>
          <button className="btn btn-outline btn-sm" disabled={!sel.length} onClick={async () => { const x = await act(() => api.billing.submitTime(sel)); if (x) { if (x.skipped.length) window.alert(x.skipped.map(s => `#${s.id}: ${s.reason}`).join('\n')); setSel([]); refresh() } }}>Submit selected</button>
          {can('time_approve') && <><button className="btn btn-primary btn-sm" disabled={!sel.length} onClick={async () => { const x = await act(() => api.billing.approveTime(sel)); if (x) { if (x.skipped.length) window.alert(x.skipped.map(s => `#${s.id}: ${s.reason}`).join('\n')); setSel([]); refresh() } }}>Approve selected</button>
            <button className="btn btn-outline btn-sm" disabled={!sel.length} onClick={async () => { const why = window.prompt('Reason for rejecting', ''); if (why && await act(() => api.billing.rejectTime(sel, why))) { setSel([]); refresh() } }}>Reject selected</button></>}
          {can('writeoff') && <button className="btn btn-outline btn-sm" disabled={sel.length !== 1} onClick={async () => { const why = window.prompt('Reason for write-off', ''); if (why && await act(() => api.billing.writeOff(sel[0], why), 'Written off')) { setSel([]); refresh() } }}>Write off</button>}
        </div>
        {can('time') && <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginTop: 8 }}><Input label="Client id" type="number" value={t.client_id} onChange={setT('client_id')} /><Input label="Date" type="date" value={t.work_date} onChange={setT('work_date')} />
          <Input label="Hours" type="number" step="0.25" value={t.hours} onChange={setT('hours')} /><Input label="Description" value={t.description} onChange={setT('description')} />
          <label className="text-sm"><input type="checkbox" checked={t.billable} onChange={setT('billable')} /> Billable</label>
          <button className="btn btn-primary btn-sm" disabled={!t.client_id || !t.description} onClick={async () => { if (await act(() => api.billing.logTime({ client_id: Number(t.client_id), work_date: t.work_date, minutes: Math.round(Number(t.hours) * 60), description: t.description, billable: t.billable }), 'Time saved as draft')) { setT('description')(''); refresh() } }}>Log time</button></div>}
      </Section>
      {can('billing') && <Section title="Invoices">
        <Async q={invs}>{d => <Table caption="Invoices" rows={d.items} empty="No invoices" onRowClick={x => setOpen(x.id)} columns={[{ key: 'accounting_number', label: 'Number', render: x => x.accounting_number || `Draft #${x.id}` }, { key: 'client_id', label: 'Client' },
          { key: 'status', label: 'Status', render: x => label(x.status) }, { key: 'net', label: 'Net', money: true }, { key: 'total', label: 'Total', money: true }, { key: 'payment', label: 'Payment', render: x => (x.payment ? `${x.payment.status} · owing $${x.payment.due}` : '—') }]} />}</Async>
        {can('billing_admin') && <div className="flex items-center gap-1" style={{ marginTop: 8 }}><Input label="Client id" type="number" value={g.client_id} onChange={setG('client_id')} />
          <button className="btn btn-primary btn-sm" disabled={!g.client_id} onClick={async () => { const k = `ui-${g.client_id}-${Date.now()}`; const inv = await act(() => api.billing.generate({ client_id: Number(g.client_id), idempotency_key: k }), 'Draft invoice created from approved time'); if (inv) { invs.reload(); dash.reload(); setOpen(inv.id) } }}>Create draft from approved time</button></div>}
      </Section>}
      {can('billing') && <Section title="Rates" hint="The most specific rate wins: client + staff, client, staff + service, staff, service.">
        <Async q={rates}>{rows => <Table caption="Rates" rows={rows} empty="No rates set" columns={[{ key: 'hourly_rate', label: 'Hourly rate', money: true }, { key: 'staff_id', label: 'Staff' }, { key: 'client_id', label: 'Client' }, { key: 'service_type', label: 'Service' }, { key: 'effective_from', label: 'From', date: true }]} />}</Async>
        {can('billing_admin') && <div className="flex items-center gap-1" style={{ flexWrap: 'wrap' }}><Input label="Hourly rate" value={r.hourly_rate} onChange={setR('hourly_rate')} /><Input label="Staff login id" type="number" value={r.staff_id} onChange={setR('staff_id')} />
          <Input label="Client id (optional)" type="number" value={r.client_id} onChange={setR('client_id')} /><Input label="Effective from" type="date" value={r.effective_from} onChange={setR('effective_from')} />
          <button className="btn btn-outline btn-sm" disabled={!r.hourly_rate} onClick={async () => { if (await act(() => api.billing.setRate({ hourly_rate: r.hourly_rate, staff_id: r.staff_id ? Number(r.staff_id) : undefined, client_id: r.client_id ? Number(r.client_id) : undefined, effective_from: r.effective_from }), 'Rate saved')) rates.reload() }}>Save rate</button></div>}
      </Section>}
      {open && <InvoiceView id={open} can={can} onClose={() => setOpen(null)} onChanged={refresh} />}
    </div>)
}
