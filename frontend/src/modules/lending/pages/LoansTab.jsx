import React, { useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import * as L from '../lib/lendApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Grid, Input, Modal, Money, Section, Select, Stat, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import { fmtAUD, fmtDate, fmtPct, label, todayISO } from '../lib/format.js'

const pctToFraction = v => (v === '' || v == null ? null : Number(v) / 100)
const BUCKET_TONE = { Current: 'current', '1-30': 'contacted', '31-60': 'hardship', '61-90': 'in_arrears', '90+': 'escalated' }

// The loan register: every settled loan, with the balance, next repayment and arrears worked out from its terms and repayments.
export default function LoansTab({ me }) {
  const caps = me.capabilities
  const [status, setStatus] = useState('active')
  const [q, setQ] = useState('')
  const [bump, setBump] = useState(0)
  const [open, setOpen] = useState(null)
  const [adding, setAdding] = useState(false)
  const list = useLoad(() => L.loans.list({ status, q }), [status, q, bump])
  const again = () => setBump(n => n + 1)
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/lending/bulk" areas={["Loans"]} onDone={() => window.location.reload()} /></div>
      <Disclaimer />
      <Async q={list}>{d => (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 12 }}>
            <Stat label="Active loans" value={d.totals.active} /><Stat label="Outstanding balance" value={<Money v={d.totals.balance} strong />} sub={`of ${fmtAUD(d.totals.original)} lent`} /><Stat label="In arrears" value={d.totals.in_arrears} tone={d.totals.in_arrears ? 'danger' : undefined} sub={fmtAUD(d.totals.arrears)} /></div>
          <div className="flex gap-1" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
            <select className="input input-sm" aria-label="Status" value={status} onChange={e => setStatus(e.target.value)} style={{ maxWidth: 180 }}><option value="">All statuses</option>{['active', 'paid_out', 'refinanced', 'written_off', 'cancelled'].map(s => <option key={s} value={s}>{label(s)}</option>)}</select>
            <input className="input input-sm" aria-label="Search loans" placeholder="Search…" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 260 }} />
            {caps.includes('settle') && <button className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>+ Loan</button>}</div>
          <DataGrid rows={d.rows} empty="No loans in the register" hint="Settle an approved application, or add a loan arranged elsewhere, a lease or hire purchase." onRowClick={r => setOpen(r.id)} columns={[
            { key: 'number', label: 'No.' }, { key: 'applicant', label: 'Applicant' }, { key: 'lender', label: 'Lender' }, { key: 'loan_type', label: 'Type', render: r => label(r.loan_type) }, { key: 'original_amount', label: 'Original', money: true }, { key: 'balance', label: 'Balance', money: true },
            { key: 'rate', label: 'Rate', render: r => fmtPct(r.rate), align: 'right' }, { key: 'next_due', label: 'Next repayment', render: r => (r.next_due ? <span>{fmtDate(r.next_due)} · <Money v={r.next_amount} /></span> : '—') }, { key: 'maturity', label: 'Matures', date: true },
            { key: 'status', label: 'Status', render: r => (r.status === 'active' && r.arrears_amount > 0 ? <span><StatusBadge status="in_arrears" text={`${r.bucket} days`} /></span> : <StatusBadge status={r.status === 'active' ? 'current' : r.status} />) }]} /></>)}</Async>
      {adding && <NewLoan onClose={() => setAdding(false)} onSaved={g => { setAdding(false); again(); setOpen(g.loan.id) }} />}
      {open && <Modal title="Loan" onClose={() => { setOpen(null); again() }} width={1100}><LoanDetail id={open} caps={caps} onChanged={again} onClose={() => { setOpen(null); again() }} /></Modal>}
    </div>)
}

function NewLoan({ onClose, onSaved }) {
  const ref = useLoad(() => L.reference(), [])
  const people = useLoad(() => L.applicants.list(''), [])
  const accts = useLoad(() => L.ledgerAccounts(), [])
  const banks = useLoad(() => L.bankAccounts(), [])
  const [f, set] = useForm({ contact_id: '', lender: '', loan_type: 'term_loan', original_amount: '', rate_pct: '', term_months: '', frequency: 'monthly', start_date: todayISO(), first_due: '', interest_only_periods: '', balloon: '', security_description: '', ledger_loan_account_id: '', ledger_interest_account_id: '', ledger_bank_account_id: '' })
  const ledger = [f.ledger_loan_account_id, f.ledger_interest_account_id, f.ledger_bank_account_id]
  const bad = [!f.contact_id && 'Choose the applicant', !(Number(f.original_amount) > 0) && 'Enter the amount', f.rate_pct === '' && 'Enter the rate', !(Number(f.term_months) >= 1) && 'Enter the term in months', !f.start_date && 'Enter the start date',
    ledger.some(Boolean) && !ledger.every(Boolean) && 'Give all three ledger accounts, or none'].filter(Boolean)
  return (
    <Modal title="New loan" onClose={onClose} width={720}><Async q={ref}>{r => (
      <>
        <Async q={people}>{ps => <Select label="Applicant" value={f.contact_id} blank="Choose…" onChange={set('contact_id')} options={ps.map(p => ({ value: p.id, label: p.name }))} />}</Async>
        <Grid cols={3}><Input label="Lender" value={f.lender} onChange={set('lender')} /><Select label="Type" value={f.loan_type} onChange={set('loan_type')} options={r.loan_types} /><Input label="Amount (AUD)" type="number" value={f.original_amount} onChange={set('original_amount')} />
          <Input label="Rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} /><Input label="Term (months)" type="number" value={f.term_months} onChange={set('term_months')} /><Select label="Repayments" value={f.frequency} onChange={set('frequency')} options={r.frequencies} />
          <Input label="Start date" type="date" value={f.start_date} onChange={set('start_date')} /><Input label="First repayment" type="date" value={f.first_due} onChange={set('first_due')} hint="Blank: one period after the start" /></Grid>
        <details><summary className="text-sm" style={{ cursor: 'pointer', marginBottom: 8 }}>More options: interest-only, residual, security, ledger link</summary>
          <Grid cols={3}><Input label="Interest-only repayments" type="number" value={f.interest_only_periods} onChange={set('interest_only_periods')} /><Input label="Residual / balloon (leases)" type="number" value={f.balloon} onChange={set('balloon')} /><Input label="Security" value={f.security_description} onChange={set('security_description')} /></Grid>
          <div className="text-xs text-muted" style={{ margin: '6px 0' }}>Link the ledger ONLY for the organisation's own borrowing: repayments then post as principal to the loan account, interest to expense, and the cash out of the bank. A loan you only track for a client is left unlinked.</div>
          <Async q={accts}>{as => <Grid cols={3}><Select label="Loan (liability) account" value={f.ledger_loan_account_id} blank="Not linked" onChange={set('ledger_loan_account_id')} options={as.filter(a => /liab/i.test(a.type)).map(a => ({ value: a.id, label: `${a.code} ${a.name}` }))} />
            <Select label="Interest expense account" value={f.ledger_interest_account_id} blank="Not linked" onChange={set('ledger_interest_account_id')} options={as.filter(a => /expense/i.test(a.type)).map(a => ({ value: a.id, label: `${a.code} ${a.name}` }))} />
            <Async q={banks}>{bs => <Select label="Bank account" value={f.ledger_bank_account_id} blank="Not linked" onChange={set('ledger_bank_account_id')} options={bs.map(b => ({ value: b.id, label: `${b.code} ${b.name}` }))} />}</Async></Grid>}</Async></details>
        {bad.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{bad.join(' · ')}</div>}
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={bad.length > 0} onClick={async () => {
          const b = { ...f, contact_id: Number(f.contact_id), rate: pctToFraction(f.rate_pct) }; delete b.rate_pct; for (const k of Object.keys(b)) if (b[k] === '') delete b[k]; const g = await act(() => L.loans.create(b), 'Loan created'); if (g && g !== true) onSaved(g) }}>Create the loan</button></div></>)}</Async></Modal>)
}

export function LoanDetail({ id, caps, onChanged, onClose }) {
  const [bump, setBump] = useState(0)
  const [dialog, ask] = usePrompt()
  const [tab, setTab] = useState('schedule')
  const [pay, setPay] = useState(false)
  const [rate, setRate] = useState(false)
  const [refi, setRefi] = useState(false)
  const q = useLoad(() => L.loans.get(id), [id, bump])
  const sched = useLoad(() => L.loans.schedule(id), [id, bump])
  const again = () => { setBump(n => n + 1); onChanged && onChanged() }
  return (
    <div>{dialog}<Async q={q}>{d => {
      const l = d.loan, p = d.position, active = l.status === 'active'
      return (
        <div>
          <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 8 }}><h3 style={{ margin: 0 }}>{l.number} · {l.applicant} <StatusBadge status={active ? (p.arrears_amount > 0 ? 'in_arrears' : 'current') : l.status} text={active ? (p.arrears_amount > 0 ? `In arrears: ${p.bucket} days` : 'Current') : label(l.status)} /></h3>
            <span className="text-sm text-muted">{l.lender || 'Lender not recorded'} · {label(l.loan_type)}{l.refinanced_from_id ? ' · refinance' : ''}</span></div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label="Balance" value={<Money v={p.balance} strong />} sub={`of ${fmtAUD(l.original_amount)}`} /><Stat label="Rate" value={fmtPct(p.current_rate)} sub={`${label(l.frequency)} · ${l.term_periods} repayments`} />
            <Stat label="Next repayment" value={p.next ? <Money v={p.next.amount} strong /> : '—'} sub={p.next ? fmtDate(p.next.due) : ''} /><Stat label="Arrears" value={<Money v={p.arrears_amount} strong />} tone={p.arrears_amount > 0 ? 'danger' : undefined} sub={p.missed_count ? `${p.missed_count} missed · ${p.days_overdue} days` : 'paid up to date'} />
            <Stat label="Matures" value={fmtDate(p.maturity)} /><Stat label="Payout today" value={<Money v={p.payout_estimate} />} sub="includes interest to today" /></div>
          <div className="flex gap-1" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
            {active && caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setPay(true)}>+ Repayment</button>}
            {active && caps.includes('settle') && <><button className="btn btn-outline btn-sm" onClick={() => setRate(true)}>Change the rate</button><button className="btn btn-outline btn-sm" onClick={() => setRefi(true)}>Refinance</button></>}
            {active && caps.includes('approve') && <button className="btn btn-ghost btn-sm" onClick={async () => { const r = await ask({ title: 'Write the loan off', message: 'Needs approval authority. The balance and your reason are recorded.', confirmLabel: 'Write off', fields: [{ key: 'reason', label: 'Reason', value: '' }] }); if (r.ok && await act(() => L.loans.setStatus(id, 'written_off', r.values.reason), 'Written off')) again() }}>Write off</button>}
            {l.application_id && <span className="text-sm">Settled from an application.</span>}{l.ledger_posting && <span className="badge badge-info">Posts to the ledger</span>}</div>
          <div className="tabs-bar" role="tablist" style={{ marginBottom: 8 }}>{[['schedule', 'Schedule'], ['repayments', `Repayments (${d.repayments.filter(r => !r.voided).length})`], ['rates', 'Rate changes']].map(([k, t]) => <button key={k} role="tab" aria-selected={tab === k} className={`tab-btn${tab === k ? ' active' : ''}`} onClick={() => setTab(k)}>{t}</button>)}</div>
          {tab === 'schedule' && <Async q={sched}>{s => (
            <div><div className="text-sm text-muted" style={{ marginBottom: 6 }}>{s.note} Total interest over the life of the loan: <strong>{fmtAUD(s.totals.total_interest)}</strong>.</div>
              <DataGrid rows={s.contractual.map(r => ({ ...r, id: r.n }))} pageSize={24} empty="No schedule" columns={[{ key: 'n', label: '#' }, { key: 'due', label: 'Due', date: true }, { key: 'opening', label: 'Opening', money: true }, { key: 'interest', label: 'Interest', money: true }, { key: 'principal', label: 'Principal', money: true }, { key: 'payment', label: 'Repayment', money: true }, { key: 'closing', label: 'Closing', money: true },
                { key: 'status', label: 'Received', render: r => (r.status === 'future' ? <span className="text-muted">due later</span> : <StatusBadge status={r.status === 'paid' ? 'current' : r.status === 'part' ? 'contacted' : 'in_arrears'} text={label(r.status)} />) }]} /></div>)}</Async>}
          {tab === 'repayments' && <DataGrid rows={d.repayments} empty="No repayments yet" columns={[{ key: 'paid_date', label: 'Date', date: true }, { key: 'amount', label: 'Amount', money: true }, { key: 'method', label: 'Method' }, { key: 'reference', label: 'Reference' }, { key: 'journal_id', label: 'Ledger', render: r => (r.voided ? <StatusBadge status="cancelled" text="Void" /> : r.journal_id ? <span className="badge badge-success">Posted</span> : '—') },
            { key: 'x', label: '', render: r => !r.voided && <span className="flex gap-1">{l.ledger_posting && !r.journal_id && caps.includes('settle') && <button className="btn btn-outline btn-xs" onClick={async () => { if (await act(() => L.loans.postRepayment(id, r.id), 'Posted to the ledger')) again() }}>Post to ledger</button>}
              {!r.journal_id && caps.includes('edit') && <button className="btn btn-ghost btn-xs" onClick={async () => { const x = await ask({ title: 'Void the repayment', confirmLabel: 'Void', fields: [{ key: 'reason', label: 'Reason', value: '' }] }); if (x.ok && await act(() => L.loans.voidRepayment(id, r.id, x.values.reason), 'Voided')) again() }}>Void</button>}</span> }]} />}
          {tab === 'rates' && <div><div className="text-xs text-muted" style={{ marginBottom: 6 }}>A rate change applies from the first repayment period that starts on or after its date, and the repayment is re-worked over the remaining term.</div><DataGrid rows={d.rate_changes} empty="No rate changes: the loan stays at its starting rate" columns={[{ key: 'effective_date', label: 'From', date: true }, { key: 'rate', label: 'New rate', render: r => fmtPct(r.rate) }, { key: 'note', label: 'Note' }]} /></div>}
          {pay && <RepayForm id={id} loan={l} onClose={() => setPay(false)} onSaved={() => { setPay(false); again() }} />}
          {rate && <RateForm id={id} onClose={() => setRate(false)} onSaved={() => { setRate(false); again() }} />}
          {refi && <RefiForm id={id} p={p} onClose={() => setRefi(false)} onSaved={() => { setRefi(false); again() }} />}
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Close</button></div>
        </div>)
    }}</Async></div>)
}

function RepayForm({ id, loan, onClose, onSaved }) {
  const [f, set] = useForm({ paid_date: todayISO(), amount: '', reference: '', method: '', post: false })
  const bad = [!(Number(f.amount) > 0) && 'Enter the amount', !f.paid_date && 'Enter the date'].filter(Boolean)
  return (
    <Modal title="Record a repayment" onClose={onClose} width={480}>
      <Grid cols={2}><Input label="Date received" type="date" value={f.paid_date} onChange={set('paid_date')} /><Input label="Amount (AUD)" type="number" step="any" value={f.amount} onChange={set('amount')} /><Input label="Reference" value={f.reference} onChange={set('reference')} /><Input label="Method" value={f.method} onChange={set('method')} /></Grid>
      {loan.ledger_posting && <Check label="Post it to the ledger now (principal, interest and bank)" checked={f.post} onChange={e => set('post')({ target: { value: e.target.checked } })} />}
      {bad.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{bad.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={bad.length > 0} onClick={async () => { const b = { paid_date: f.paid_date, amount: f.amount, reference: f.reference || undefined, method: f.method || undefined }; if (await act(() => L.loans.repay(id, b, !!f.post), 'Repayment recorded')) onSaved() }}>Save</button></div>
    </Modal>)
}

function RateForm({ id, onClose, onSaved }) {
  const [f, set] = useForm({ effective_date: todayISO(), rate_pct: '', note: '' })
  return (
    <Modal title="Change the rate" onClose={onClose} width={440}>
      <Grid cols={2}><Input label="Effective from" type="date" value={f.effective_date} onChange={set('effective_date')} /><Input label="New rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} /></Grid><Input label="Note" value={f.note} onChange={set('note')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={f.rate_pct === '' || !f.effective_date} onClick={async () => { if (await act(() => L.loans.rateChange(id, { effective_date: f.effective_date, rate: pctToFraction(f.rate_pct), note: f.note }), 'Rate changed')) onSaved() }}>Save</button></div>
    </Modal>)
}

function RefiForm({ id, p, onClose, onSaved }) {
  const [f, set] = useForm({ refinance_date: todayISO(), lender: '', rate_pct: '', term_months: '', frequency: 'monthly', original_amount: '' })
  const bad = [f.rate_pct === '' && 'Enter the new rate', !(Number(f.term_months) >= 1) && 'Enter the new term in months'].filter(Boolean)
  return (
    <Modal title="Refinance" onClose={onClose} width={560}>
      <div className="text-sm" style={{ marginBottom: 8 }}>The old loan is paid out (what is owing to the date, about <Money v={p.payout_estimate} strong /> today) and a new loan starts, linked to it. Leave the amount blank to borrow exactly the payout, or enter a larger amount for a top-up.</div>
      <Grid cols={2}><Input label="Refinance date" type="date" value={f.refinance_date} onChange={set('refinance_date')} /><Input label="New lender" value={f.lender} onChange={set('lender')} /><Input label="New rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} /><Input label="New term (months)" type="number" value={f.term_months} onChange={set('term_months')} />
        <Input label="New amount (optional)" type="number" value={f.original_amount} onChange={set('original_amount')} /></Grid>
      {bad.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{bad.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={bad.length > 0} onClick={async () => { const b = { ...f, rate: pctToFraction(f.rate_pct) }; delete b.rate_pct; for (const k of Object.keys(b)) if (b[k] === '') delete b[k]; if (await act(() => L.loans.refinance(id, b), 'Refinanced')) onSaved() }}>Refinance</button></div>
    </Modal>)
}
