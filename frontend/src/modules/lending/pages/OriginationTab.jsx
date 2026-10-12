import React, { useState } from 'react'
import * as L from '../lib/lendApi.js'
import AssessmentPanel from '../components/assessment.jsx'
import { act, Async, DataGrid, Disclaimer, Grade, Grid, Input, Modal, Money, Outcome, Section, Select, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import { fmtAUD, fmtDate, label, saveBlob, todayISO } from '../lib/format.js'

const pctToFraction = v => (v === '' || v == null ? null : Number(v) / 100)
const STATUS_ORDER = ['draft', 'submitted', 'assessing', 'more_information', 'approved', 'declined', 'settled', 'withdrawn']

// Applicant -> Loan request -> Financial analysis -> Credit assessment -> Documents -> Recommendation -> Approval -> Settlement, all on one page.
export default function OriginationTab({ me }) {
  const caps = me.capabilities
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [bump, setBump] = useState(0)
  const [open, setOpen] = useState(null)
  const [adding, setAdding] = useState(false)
  const list = useLoad(() => L.applications.list({ status, q }), [status, q, bump])
  const again = () => setBump(n => n + 1)
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <Async q={list}>{d => (
        <>
          <div className="flex gap-1" style={{ flexWrap: 'wrap', marginBottom: 10 }} role="group" aria-label="Pipeline">
            <button className={`btn btn-sm ${status === '' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setStatus('')}>All ({d.total})</button>
            {STATUS_ORDER.map(s => <button key={s} className={`btn btn-sm ${status === s ? 'btn-primary' : 'btn-outline'}`} onClick={() => setStatus(s)}>{label(s)} ({d.counts[s] || 0})</button>)}
          </div>
          <div className="flex gap-1" style={{ marginBottom: 8 }}><input className="input input-sm" aria-label="Search applications" placeholder="Search by number, applicant or purpose…" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 340 }} />
            {caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>+ New application</button>}</div>
          <DataGrid rows={d.rows} empty="No applications yet" hint="Start one from an applicant." onRowClick={r => setOpen(r.id)} columns={[
            { key: 'number', label: 'No.' }, { key: 'applicant', label: 'Applicant' }, { key: 'purpose', label: 'Purpose' }, { key: 'loan_type', label: 'Type', render: r => label(r.loan_type) }, { key: 'amount', label: 'Amount', money: true },
            { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> }, { key: 'grade', label: 'Grade', render: r => <Grade g={r.grade} score={r.score} /> }, { key: 'outcome', label: 'Recommendation', render: r => <Outcome o={r.outcome} /> }, { key: 'age_days', label: 'Age (days)', align: 'right' }]} />
        </>)}</Async>
      {adding && <NewApplication onClose={() => setAdding(false)} onSaved={r => { setAdding(false); again(); setOpen(r.application.id) }} />}
      {open && <Modal title="Loan application" onClose={() => { setOpen(null); again() }} width={1100}><ApplicationDetail id={open} caps={caps} onChanged={again} onClose={() => { setOpen(null); again() }} /></Modal>}
    </div>)
}

function NewApplication({ onClose, onSaved }) {
  const ref = useLoad(() => L.reference(), [])
  const people = useLoad(() => L.applicants.list(''), [])
  const [f, set] = useForm({ contact_id: '', purpose: '', loan_type: 'term_loan', amount: '', term_months: '', rate_pct: '', repayment_frequency: 'monthly', security_description: '', security_value: '' })
  const bad = [!f.contact_id && 'Choose the applicant', !(Number(f.amount) > 0) && 'Enter the loan amount', !(Number(f.term_months) >= 1) && 'Enter the term in months', f.rate_pct !== '' && Number(f.rate_pct) > 50 && 'The rate is a percentage a year, for example 6.5'].filter(Boolean)
  return (
    <Modal title="New loan application" onClose={onClose} width={640}><Async q={ref}>{r => (
      <>
        <div className="text-xs text-muted" style={{ marginBottom: 8 }}>Only the essentials now. Everything else is added as the application progresses.</div>
        <Async q={people}>{ps => <Select label="Applicant" value={f.contact_id} blank={ps.length ? 'Choose…' : 'No applicants: add one under Statement Analysis'} onChange={set('contact_id')} options={ps.map(p => ({ value: p.id, label: p.name }))} />}</Async>
        <Grid cols={2}><Input label="Purpose" value={f.purpose} onChange={set('purpose')} /><Select label="Loan type" value={f.loan_type} onChange={set('loan_type')} options={r.loan_types} /><Input label="Amount (AUD)" type="number" value={f.amount} onChange={set('amount')} />
          <Input label="Term (months)" type="number" value={f.term_months} onChange={set('term_months')} /><Input label="Interest rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} hint="Optional: 6.5% is assumed for the assessment if left blank" />
          <Select label="Repayments" value={f.repayment_frequency} onChange={set('repayment_frequency')} options={r.frequencies} /></Grid>
        <details><summary className="text-sm" style={{ cursor: 'pointer', marginBottom: 8 }}>More options: security</summary><Grid cols={2}><Input label="Security / collateral" value={f.security_description} onChange={set('security_description')} /><Input label="Security value (AUD)" type="number" value={f.security_value} onChange={set('security_value')} /></Grid></details>
        {bad.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{bad.join(' · ')}</div>}
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={bad.length > 0} onClick={async () => {
          const b = { ...f, contact_id: Number(f.contact_id), rate: pctToFraction(f.rate_pct) }; delete b.rate_pct; for (const k of Object.keys(b)) if (b[k] === '' || b[k] == null) delete b[k]
          const x = await act(() => L.applications.create(b), 'Application started'); if (x && x !== true) onSaved(x) }}>Start application</button></div></>)}</Async></Modal>)
}

export function ApplicationDetail({ id, caps, onChanged, onClose }) {
  const [bump, setBump] = useState(0)
  const [dialog, ask] = usePrompt()
  const [edit, setEdit] = useState(false)
  const [settle, setSettle] = useState(false)
  const q = useLoad(() => L.applications.get(id), [id, bump])
  const again = () => { setBump(n => n + 1); onChanged && onChanged() }
  const run = (fn, ok) => async () => { if (await act(fn, ok)) again() }
  const withReason = (title, message, fn, ok, min = 5) => async () => { const r = await ask({ title, message, confirmLabel: 'Confirm', fields: [{ key: 'reason', label: `Reason (at least ${min} characters, recorded with your name)`, value: '' }] }); if (r.ok && await act(() => fn(r.values.reason), ok)) again() }
  return (
    <div>{dialog}<Async q={q}>{d => {
      const x = d.application, asm = d.assessment, open = ['draft', 'submitted', 'assessing', 'more_information'].includes(x.status)
      return (
        <div>
          <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 6 }}><h3 style={{ margin: 0 }}>{x.number} · {d.applicant.contact.name} <StatusBadge status={x.status} /></h3><Grade g={asm?.grade} score={asm?.score} /></div>
          <div role="note" className="alert alert-info" style={{ marginBottom: 12 }}><strong>Next:</strong> {d.next_action}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(420px,1fr))', gap: 12 }}>
            <Section title="Loan request" actions={open && caps.includes('edit') && <button className="btn btn-outline btn-sm" onClick={() => setEdit(true)}>Edit</button>}>
              <div className="text-sm">{x.purpose || 'No purpose entered'} · {label(x.loan_type)}</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 8, marginTop: 8 }}>
                <div><div className="text-xs text-muted">Amount</div><Money v={x.amount} strong /></div><div><div className="text-xs text-muted">Term</div>{x.term_months} months</div><div><div className="text-xs text-muted">Rate</div>{x.rate != null ? `${(Number(x.rate) * 100).toFixed(2)}%` : <span className="text-muted">6.50% assumed</span>}</div>
                <div><div className="text-xs text-muted">Repayments</div>{label(x.repayment_frequency)}</div><div><div className="text-xs text-muted">Security</div>{x.security_description || '—'}{x.security_value != null && <div className="text-xs">{fmtAUD(x.security_value)}</div>}</div></div>
            </Section>
            <Section title="Applicant and statements"><div className="text-sm">{d.applicant.profile ? `${label(d.applicant.profile.household_type)} · ${d.applicant.profile.employment_type ? label(d.applicant.profile.employment_type) : 'employment not entered'}` : 'No profile yet'}</div>
              <div className="text-sm">Existing debts: <Money v={d.applicant.commitments_monthly} /> a month</div>
              {d.analysis ? <div className="text-sm" style={{ marginTop: 4 }}>Latest analysis: {d.analysis.months} month(s), income <Money v={d.analysis.headline?.income_monthly} />, surplus <Money v={d.analysis.headline?.surplus_monthly} /> a month</div> : <div className="text-sm text-muted" style={{ marginTop: 4 }}>No statements analysed yet (do this under Statement Analysis).</div>}</Section>
          </div>
          <Section title="Documents" hint="What the application still needs. Files are stored with the books' documents and checked when downloaded." actions={caps.includes('edit') && open && <button className="btn btn-outline btn-sm" onClick={async () => { const r = await ask({ title: 'Ask for another document', confirmLabel: 'Add', fields: [{ key: 'label', label: 'What is needed?', value: '' }] }); if (r.ok && r.values.label.trim() && await act(() => L.applications.requestDoc(id, { key: r.values.label, label: r.values.label }), 'Added to the checklist')) again() }}>+ Ask for a document</button>}>
            <table className="data-table" aria-label="Documents"><thead><tr><th>Document</th><th>Status</th><th /></tr></thead><tbody>{d.documents.map(doc => (
              <tr key={doc.key}><td>{doc.label}{!doc.required && <span className="text-xs text-muted"> (optional)</span>}</td><td>{doc.received ? <span className="badge badge-success">Received {fmtDate(doc.received_at)}</span> : <span className="badge badge-warning">Needed</span>}</td>
                <td><span className="flex gap-1">{caps.includes('upload') && open && <label className="btn btn-outline btn-xs" style={{ cursor: 'pointer', marginBottom: 0 }}>{doc.received ? 'Replace' : 'Upload'}<input type="file" hidden aria-label={`Upload ${doc.label}`} onChange={async e => { const f = e.target.files?.[0]; if (f && await act(() => L.applications.uploadDoc(id, doc.key, f), 'Uploaded')) again() }} /></label>}
                  {doc.received && <button className="btn btn-ghost btn-xs" onClick={async () => { const b = await act(() => L.applications.downloadDoc(id, doc.key)); if (b && b !== true) saveBlob(`${x.number}-${doc.key}`, b) }}>Download</button>}
                  {doc.received && caps.includes('edit') && open && <button className="btn btn-ghost btn-xs" onClick={async () => { if (window.confirm('Remove this file?') && await act(() => L.applications.removeDoc(id, doc.key), 'Removed')) again() }}>Remove</button>}</span></td></tr>))}</tbody></table>
          </Section>
          <Section title="Credit assessment" actions={caps.includes('assess') && open && <button className="btn btn-primary btn-sm" onClick={run(() => L.applications.assess(id), 'Assessment complete')}>{asm ? 'Run the assessment again' : 'Run the credit assessment'}</button>}>
            <AssessmentPanel a={asm} />
          </Section>
          <Section title="Actions">
            <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
              {['draft', 'more_information'].includes(x.status) && caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={run(() => L.applications.status(id, 'submitted'), 'Submitted')}>Submit the application</button>}
              {['submitted', 'assessing'].includes(x.status) && caps.includes('edit') && <button className="btn btn-outline btn-sm" onClick={withReason('Ask for more information', 'What is needed from the applicant?', r => L.applications.status(id, 'more_information', r), 'Marked: more information needed')}>Request more information</button>}
              {['submitted', 'assessing', 'more_information'].includes(x.status) && caps.includes('approve') && <><button className="btn btn-primary btn-sm" onClick={withReason('Approve', 'Your name, the date and this reason are recorded.', r => L.applications.decide(id, 'approved', r), 'Approved')}>Approve</button>
                <button className="btn btn-outline btn-sm" onClick={withReason('Decline', 'Your name, the date and this reason are recorded.', r => L.applications.decide(id, 'declined', r), 'Declined')}>Decline</button></>}
              {x.status === 'approved' && caps.includes('settle') && <button className="btn btn-primary btn-sm" onClick={() => setSettle(true)}>Settle: create the loan</button>}
              {open && caps.includes('edit') && <button className="btn btn-ghost btn-sm" onClick={withReason('Withdraw the application', 'Why is it being withdrawn?', r => L.applications.status(id, 'withdrawn', r), 'Withdrawn')}>Withdraw</button>}
              {x.loan_id && <span className="text-sm">Loan created: see Loans.</span>}</div>
            {!caps.includes('approve') && ['submitted', 'assessing', 'more_information'].includes(x.status) && <div className="text-xs text-muted" style={{ marginTop: 6 }}>Your role can prepare and assess but not approve or decline: ask an accountant, admin or owner.</div>}
            {x.decision_reason && <div className="text-sm" style={{ marginTop: 8 }}>Decision ({label(x.status)}): {x.decision_reason}</div>}
          </Section>
          <Section title="History" hint="Every status change, assessment, decision and override, with who and when. It cannot be edited."><table className="data-table" aria-label="History"><thead><tr><th>When</th><th>Who</th><th>What</th><th>Why</th></tr></thead><tbody>{d.events.map(e => (
            <tr key={e.id}><td className="text-sm">{fmtDate(e.at)}</td><td className="text-sm">{e.by}</td><td className="text-sm"><StatusBadge status={e.kind === 'override' ? 'escalated' : e.to_status || 'draft'} text={e.kind === 'status' ? `${label(e.from_status) || 'New'} → ${label(e.to_status)}` : label(e.kind)} /></td><td className="text-sm">{e.reason}</td></tr>))}</tbody></table></Section>
          {edit && <EditApplication d={d} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); again() }} />}
          {settle && <SettleForm d={d} onClose={() => setSettle(false)} onSaved={() => { setSettle(false); again() }} />}
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Close</button></div>
        </div>)
    }}</Async></div>)
}

function EditApplication({ d, onClose, onSaved }) {
  const x = d.application
  const ref = useLoad(() => L.reference(), [])
  const [f, set] = useForm({ purpose: x.purpose || '', loan_type: x.loan_type, amount: x.amount, term_months: x.term_months, rate_pct: x.rate != null ? (Number(x.rate) * 100).toFixed(2) : '', repayment_frequency: x.repayment_frequency, security_description: x.security_description || '', security_value: x.security_value ?? '' })
  return (
    <Modal title="Edit the loan request" onClose={onClose} width={620}><Async q={ref}>{r => (
      <>
        <div className="text-xs text-muted" style={{ marginBottom: 8 }}>Changing the amount, term, rate, type or security means the credit assessment must be run again before a decision.</div>
        <Grid cols={2}><Input label="Purpose" value={f.purpose} onChange={set('purpose')} /><Select label="Loan type" value={f.loan_type} onChange={set('loan_type')} options={r.loan_types} /><Input label="Amount (AUD)" type="number" value={f.amount} onChange={set('amount')} /><Input label="Term (months)" type="number" value={f.term_months} onChange={set('term_months')} />
          <Input label="Interest rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} /><Select label="Repayments" value={f.repayment_frequency} onChange={set('repayment_frequency')} options={r.frequencies} /><Input label="Security" value={f.security_description} onChange={set('security_description')} /><Input label="Security value" type="number" value={f.security_value} onChange={set('security_value')} /></Grid>
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={async () => {
          const b = { ...f, rate: pctToFraction(f.rate_pct) }; delete b.rate_pct; for (const k of Object.keys(b)) if (b[k] === '') b[k] = null; if (await act(() => L.applications.update(x.id, b), 'Saved')) onSaved() }}>Save</button></div></>)}</Async></Modal>)
}

function SettleForm({ d, onClose, onSaved }) {
  const x = d.application
  const [f, set] = useForm({ start_date: todayISO(), lender: x.lender || '', rate_pct: x.rate != null ? (Number(x.rate) * 100).toFixed(2) : '', balloon: '' })
  const bad = [!f.start_date && 'Enter the settlement date', f.rate_pct === '' && 'Enter the rate the loan settles at'].filter(Boolean)
  return (
    <Modal title="Settle: create the loan" onClose={onClose} width={520}>
      <div className="text-sm" style={{ marginBottom: 8 }}>{x.number}: {fmtAUD(x.amount)} over {x.term_months} months. This creates the loan in the register and closes the application.</div>
      <Grid cols={2}><Input label="Settlement date" type="date" value={f.start_date} onChange={set('start_date')} /><Input label="Lender" value={f.lender} onChange={set('lender')} /><Input label="Rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} /><Input label="Residual / balloon (leases)" type="number" value={f.balloon} onChange={set('balloon')} /></Grid>
      {bad.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{bad.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={bad.length > 0} onClick={async () => { const b = { start_date: f.start_date, lender: f.lender || undefined, rate: pctToFraction(f.rate_pct), balloon: f.balloon || undefined }; if (await act(() => L.applications.settle(x.id, b), 'Loan created')) onSaved() }}>Create the loan</button></div>
    </Modal>)
}
