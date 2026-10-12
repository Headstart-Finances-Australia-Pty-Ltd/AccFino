import React, { useState } from 'react'
import * as L from '../lib/lendApi.js'
import { act, Async, DataGrid, Disclaimer, Grid, Input, Modal, Money, Section, Select, Stat, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import { fmtAUD, fmtDate, label, todayISO } from '../lib/format.js'

const TONE = { Current: 'var(--success)', '1-30': 'var(--warning)', '31-60': 'var(--warning)', '61-90': 'var(--danger)', '90+': 'var(--danger)' }

// Practical visibility of repayment problems: who is behind, by how much, what has been done, and what is agreed.
export default function CollectionsTab({ me }) {
  const caps = me.capabilities
  const [bucket, setBucket] = useState('')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [bump, setBump] = useState(0)
  const [open, setOpen] = useState(null)
  const reg = useLoad(() => L.collections.register({ bucket, status, q }), [bucket, status, q, bump])
  const again = () => setBump(n => n + 1)
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <Async q={reg}>{d => (
        <>
          <div role="group" aria-label="Arrears buckets" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginBottom: 12 }}>
            {d.buckets.map(b => (
              <button key={b.bucket} className={`stat-card${bucket === b.bucket ? ' active' : ''}`} style={{ textAlign: 'left', cursor: 'pointer', borderTop: `3px solid ${TONE[b.bucket]}` }} onClick={() => setBucket(bucket === b.bucket ? '' : b.bucket)} aria-pressed={bucket === b.bucket}>
                <div className="stat-label">{b.bucket === 'Current' ? 'Current' : `${b.bucket} days`}</div><div className="stat-value">{b.loans} <span className="text-sm text-muted">loan{b.loans === 1 ? '' : 's'}</span></div>
                <div className="text-xs text-muted">{b.bucket === 'Current' ? `balance ${fmtAUD(b.balance)}` : `arrears ${fmtAUD(b.arrears)}`}</div></button>))}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label="Total arrears" value={<Money v={d.summary.arrears_total} strong />} sub={`${d.summary.in_arrears} of ${d.summary.loans} loans`} tone={d.summary.in_arrears ? 'danger' : undefined} /><Stat label="Follow-ups due" value={d.summary.follow_ups_due} tone={d.summary.follow_ups_due ? 'danger' : undefined} />
            <Stat label="Payment arrangements" value={d.summary.arrangements} sub={d.summary.broken_arrangements ? `${d.summary.broken_arrangements} behind` : 'none behind'} /><Stat label="Hardship cases" value={d.summary.hardship} /><Stat label="Promises to pay" value={d.summary.promises} /></div>
          <div className="flex gap-1" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
            <select className="input input-sm" aria-label="Collection status" value={status} onChange={e => setStatus(e.target.value)} style={{ maxWidth: 220 }}><option value="">All collection statuses</option>{['in_arrears', 'contacted', 'promise_to_pay', 'escalated', 'arrangement', 'hardship'].map(s => <option key={s} value={s}>{label(s)}</option>)}</select>
            <input className="input input-sm" aria-label="Search arrears" placeholder="Search…" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 260 }} /></div>
          <div className="text-xs text-muted" style={{ marginBottom: 6 }}>{d.note}</div>
          <DataGrid rows={d.rows.map(r => ({ ...r, id: r.loan_id }))} empty="Nobody is behind" hint="Loans in arrears, on an arrangement or in hardship appear here." onRowClick={r => setOpen(r.loan_id)} columns={[
            { key: 'number', label: 'Loan' }, { key: 'applicant', label: 'Applicant' }, { key: 'oldest_due_date', label: 'Oldest unpaid due', date: true }, { key: 'amount_due', label: 'Amount due', money: true }, { key: 'amount_paid', label: 'Last payment', render: r => (r.last_payment_date ? <span><Money v={r.amount_paid} /> <span className="text-xs text-muted">{fmtDate(r.last_payment_date)}</span></span> : <span className="text-muted">none</span>) },
            { key: 'days_overdue', label: 'Days overdue', align: 'right' }, { key: 'arrears_amount', label: 'Arrears', money: true }, { key: 'missed_payments', label: 'Missed', align: 'right' }, { key: 'bucket', label: 'Bucket' },
            { key: 'status', label: 'Collection status', render: r => <span><StatusBadge status={r.status} text={r.label} />{r.follow_up_due && <span className="badge badge-danger" style={{ marginLeft: 4 }}>follow up</span>}</span> }]} /></>)}</Async>
      {open && <Modal title="Collection case" onClose={() => { setOpen(null); again() }} width={1000}><Case id={open} caps={caps} onChanged={again} onClose={() => { setOpen(null); again() }} /></Modal>}
    </div>)
}

function Case({ id, caps, onChanged, onClose }) {
  const [bump, setBump] = useState(0)
  const [dialog, ask] = usePrompt()
  const [act_, setAct] = useState(false)
  const [arr, setArr] = useState(false)
  const [hs, setHs] = useState(false)
  const q = useLoad(() => L.collections.caseFor(id), [id, bump])
  const again = () => { setBump(n => n + 1); onChanged && onChanged() }
  return (
    <div>{dialog}<Async q={q}>{d => {
      const s = d.summary, arrOpen = d.arrangements.find(a => a.status === 'active'), hOpen = d.hardship.find(h => ['requested', 'assessing', 'approved', 'active'].includes(h.status))
      return (
        <div>
          <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 8 }}><h3 style={{ margin: 0 }}>{s.number} · {s.applicant}</h3><StatusBadge status={s.status} text={s.label} /></div>
          <div className="text-sm text-muted" style={{ marginBottom: 8 }}>{[s.phone, s.email].filter(Boolean).join(' · ') || 'No contact details on file'}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginBottom: 10 }}>
            <Stat label="Arrears" value={<Money v={s.arrears_amount} strong />} sub={`${s.missed_payments} missed`} tone={s.arrears_amount > 0 ? 'danger' : undefined} /><Stat label="Days overdue" value={s.days_overdue} sub={s.bucket === 'Current' ? 'current' : `${s.bucket} days`} /><Stat label="Balance" value={<Money v={s.balance} />} />
            <Stat label="Last activity" value={s.last_activity ? label(s.last_activity.kind) : 'None'} sub={s.last_activity ? `${fmtDate(s.last_activity.date)}${s.next_action_date ? ` · next ${fmtDate(s.next_action_date)}` : ''}` : ''} /></div>
          <div className="flex gap-1" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
            {caps.includes('collect') && <button className="btn btn-primary btn-sm" onClick={() => setAct(true)}>+ Log contact or note</button>}
            {caps.includes('collect') && !arrOpen && s.arrears_amount > 0 && <button className="btn btn-outline btn-sm" onClick={() => setArr(true)}>Agree a payment arrangement</button>}
            {caps.includes('collect') && !hOpen && <button className="btn btn-outline btn-sm" onClick={() => setHs(true)}>Hardship request</button>}</div>
          {s.arrangement && (
            <div className={`alert ${s.arrangement.compliance === 'behind' ? 'alert-error' : 'alert-info'}`} style={{ marginBottom: 10 }} aria-label="Payment arrangement">
              <strong>Payment arrangement:</strong> {fmtAUD(s.arrangement.amount_per_period)} {s.arrangement.frequency}. Expected so far {fmtAUD(s.arrangement.expected)}, received {fmtAUD(s.arrangement.paid)}: <strong>{s.arrangement.compliance === 'behind' ? `behind by ${fmtAUD(s.arrangement.behind)}` : 'on track'}</strong>.
              {s.arrangement.can_complete && <div className="text-sm">The arrears are cleared: the arrangement can now be completed.</div>}
              {caps.includes('collect') && <div className="flex gap-1" style={{ marginTop: 6 }}>{[['completed', 'Mark completed'], ['broken', 'Mark broken'], ['cancelled', 'Cancel']].map(([st, t]) => <button key={st} className="btn btn-outline btn-xs" onClick={async () => { const r = await ask({ title: t, confirmLabel: 'Confirm', fields: [{ key: 'notes', label: 'Note (optional)', value: '' }] }); if (r.ok && await act(() => L.collections.closeArrangement(id, s.arrangement.id, st, r.values.notes), 'Arrangement updated')) again() }}>{t}</button>)}</div>}
            </div>)}
          <Section title="Hardship" hint="Approving or declining needs approval authority and an outcome that is recorded with your name.">
            <DataGrid rows={d.hardship} empty="No hardship cases" columns={[{ key: 'requested_date', label: 'Requested', date: true }, { key: 'reason', label: 'Reason' }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status === 'active' ? 'hardship' : r.status} text={label(r.status)} /> }, { key: 'relief', label: 'Relief' }, { key: 'review_date', label: 'Review', date: true },
              { key: 'x', label: '', render: r => <span className="flex gap-1">{r.allowed_next.map(a => ((['approved', 'declined'].includes(a) ? caps.includes('approve') : caps.includes('collect')) && <button key={a} className="btn btn-outline btn-xs" onClick={async () => {
                const f = ['approved', 'declined'].includes(a) ? [{ key: 'outcome', label: 'Outcome and reason (recorded)', value: '' }, ...(a === 'approved' ? [{ key: 'relief', label: 'Relief given (e.g. reduced repayments, pause, longer term)', value: '' }] : [])] : [{ key: 'outcome', label: 'Note (optional)', value: '' }]
                const x = await ask({ title: `Hardship: ${a}`, confirmLabel: 'Confirm', fields: f }); if (x.ok && await act(() => L.collections.hardshipAction(id, r.id, { action: a, ...x.values }), 'Hardship case updated')) again() }}>{label(a)}</button>))}</span> }]} /></Section>
          <Section title="Contact and activity log"><DataGrid rows={d.activities} empty="Nothing recorded yet" columns={[{ key: 'date', label: 'Date', date: true }, { key: 'kind', label: 'What', render: r => label(r.kind) }, { key: 'outcome', label: 'Outcome' }, { key: 'notes', label: 'Notes' }, { key: 'next_action_date', label: 'Next action', date: true }]} /></Section>
          {act_ && <ActivityForm id={id} onClose={() => setAct(false)} onSaved={() => { setAct(false); again() }} />}
          {arr && <ArrangeForm id={id} arrears={s.arrears_amount} onClose={() => setArr(false)} onSaved={() => { setArr(false); again() }} />}
          {hs && <HardshipForm id={id} onClose={() => setHs(false)} onSaved={() => { setHs(false); again() }} />}
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Close</button></div>
        </div>)
    }}</Async></div>)
}

function ActivityForm({ id, onClose, onSaved }) {
  const ref = useLoad(() => L.reference(), [])
  const [f, set] = useForm({ kind: 'call', activity_date: todayISO(), outcome: '', notes: '', next_action_date: '' })
  const bad = [f.kind === 'promise_to_pay' && !f.next_action_date && 'A promise to pay needs the date it was promised for'].filter(Boolean)
  return (
    <Modal title="Log contact or note" onClose={onClose} width={520}><Async q={ref}>{r => (
      <><Grid cols={2}><Select label="What happened" value={f.kind} onChange={set('kind')} options={r.collection_kinds} /><Input label="Date" type="date" value={f.activity_date} onChange={set('activity_date')} /><Input label="Outcome" value={f.outcome} onChange={set('outcome')} /><Input label="Next action / promised date" type="date" value={f.next_action_date} onChange={set('next_action_date')} /></Grid>
        <Input label="Notes" value={f.notes} onChange={set('notes')} />{bad.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{bad.join(' · ')}</div>}
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={bad.length > 0} onClick={async () => { const b = { ...f }; for (const k of Object.keys(b)) if (b[k] === '') delete b[k]; if (await act(() => L.collections.activity(id, b), 'Recorded')) onSaved() }}>Save</button></div></>)}</Async></Modal>)
}

function ArrangeForm({ id, arrears, onClose, onSaved }) {
  const ref = useLoad(() => L.reference(), [])
  const [f, set] = useForm({ amount_per_period: '', frequency: 'fortnightly', start_date: todayISO(), end_date: '', notes: '' })
  return (
    <Modal title="Agree a payment arrangement" onClose={onClose} width={520}><Async q={ref}>{r => (
      <><div className="text-sm" style={{ marginBottom: 8 }}>Arrears to clear: <Money v={arrears} strong /></div>
        <Grid cols={2}><Input label="Amount each time (AUD)" type="number" value={f.amount_per_period} onChange={set('amount_per_period')} /><Select label="How often" value={f.frequency} onChange={set('frequency')} options={r.frequencies} /><Input label="Starting" type="date" value={f.start_date} onChange={set('start_date')} /><Input label="Ending (optional)" type="date" value={f.end_date} onChange={set('end_date')} /></Grid>
        <Input label="Notes" value={f.notes} onChange={set('notes')} />
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!(Number(f.amount_per_period) > 0)} onClick={async () => { const b = { ...f }; for (const k of Object.keys(b)) if (b[k] === '') delete b[k]; if (await act(() => L.collections.arrange(id, b), 'Arrangement agreed')) onSaved() }}>Agree</button></div></>)}</Async></Modal>)
}

function HardshipForm({ id, onClose, onSaved }) {
  const [f, set] = useForm({ reason: '', requested_date: todayISO() })
  return (
    <Modal title="Hardship request" onClose={onClose} width={500}>
      <div className="text-xs text-muted" style={{ marginBottom: 8 }}>Record what the borrower says. A decision is made separately by someone with approval authority.</div>
      <Input label="Reason" value={f.reason} onChange={set('reason')} /><Input label="Date requested" type="date" value={f.requested_date} onChange={set('requested_date')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={f.reason.trim().length < 5} onClick={async () => { if (await act(() => L.collections.hardship(id, f), 'Hardship request recorded')) onSaved() }}>Record</button></div>
    </Modal>)
}
