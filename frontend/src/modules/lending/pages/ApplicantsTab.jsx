import React, { useRef, useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import * as L from '../lib/lendApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Grid, Input, Modal, Money, Notice, Pct, Section, Select, Stat, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import { fmtAUD, fmtDate, label, todayISO } from '../lib/format.js'

const blank = o => Object.fromEntries(Object.entries(o || {}).map(([k, v]) => [k, v ?? '']))

// Applicant first: who is this, what do their statements show, and can they afford the loan?
export default function ApplicantsTab({ me }) {
  const caps = me.capabilities
  const [sel, setSel] = useState(null)
  const [q, setQ] = useState('')
  const [bump, setBump] = useState(0)
  const [adding, setAdding] = useState(false)
  const list = useLoad(() => L.applicants.list(q), [q, bump])
  const again = () => setBump(n => n + 1)
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/lending/bulk" areas={["Applicants"]} onDone={() => window.location.reload()} /></div>
      <Disclaimer />
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px,300px) 1fr', gap: 16, alignItems: 'start' }}>
        <div>
          <div className="flex gap-1" style={{ marginBottom: 8 }}><input className="input input-sm" aria-label="Search applicants" placeholder="Search applicants…" value={q} onChange={e => setQ(e.target.value)} style={{ flex: 1 }} />
            {caps.includes('edit') && <button className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>+ Applicant</button>}</div>
          <Async q={list}>{rows => rows.length === 0 ? <div className="text-sm text-muted" style={{ padding: 12 }}>No applicants yet. Add the first one to start.</div> : (
            <div role="list" aria-label="Applicants">{rows.map(r => (
              <div key={r.id} role="listitem"><button className={`btn btn-outline btn-sm${sel === r.id ? ' active' : ''}`} style={{ width: '100%', textAlign: 'left', marginBottom: 4, fontWeight: sel === r.id ? 700 : 400 }} onClick={() => setSel(r.id)}>
                {r.name}{r.open_applications > 0 && <span className="badge badge-info" style={{ marginLeft: 6 }}>{r.open_applications} open</span>}</button></div>))}</div>)}</Async>
        </div>
        <div>{sel ? <Workspace key={sel} id={sel} caps={caps} /> : <div className="text-muted" style={{ padding: 24 }}>Choose an applicant, or add one. Then upload their bank statements (or use the bank accounts already in Accfino) to see income, expenses, commitments, surplus and serviceability on one page.</div>}</div>
      </div>
      {adding && <NewApplicant onClose={() => setAdding(false)} onSaved={c => { setAdding(false); again(); setSel(c.id) }} />}
    </div>)
}

function NewApplicant({ onClose, onSaved }) {
  const [f, set] = useForm({ name: '', email: '', phone: '' })
  return (
    <Modal title="New applicant" onClose={onClose} width={480}>
      <div className="text-xs text-muted" style={{ marginBottom: 8 }}>The applicant is saved as a contact, so nothing is entered twice. Never enter a Tax File Number.</div>
      <Input label="Full name or business name" value={f.name} onChange={set('name')} /><Grid cols={2}><Input label="Email" value={f.email} onChange={set('email')} /><Input label="Phone" value={f.phone} onChange={set('phone')} /></Grid>
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!f.name.trim()} onClick={async () => { const r = await act(() => L.applicants.create(f), 'Applicant saved'); if (r && r !== true) onSaved(r) }}>Save</button></div>
    </Modal>)
}

function Workspace({ id, caps }) {
  const [bump, setBump] = useState(0)
  const [openA, setOpenA] = useState(null)
  const [profile, setProfile] = useState(false)
  const [commit, setCommit] = useState(null)
  const [analyse, setAnalyse] = useState(false)
  const ap = useLoad(() => L.applicants.get(id), [id, bump])
  const an = useLoad(() => L.analyses.list(id), [id, bump])
  const again = () => setBump(n => n + 1)
  return (
    <Async q={ap}>{d => (
      <div>
        <h3 style={{ margin: '0 0 8px' }}>{d.contact.name}</h3>
        <div className="text-sm text-muted" style={{ marginBottom: 10 }}>{[d.contact.email, d.contact.phone].filter(Boolean).join(' · ') || 'No contact details'}</div>
        <Section title="Profile" actions={caps.includes('edit') && <button className="btn btn-outline btn-sm" onClick={() => setProfile(true)}>{d.profile ? 'Edit' : 'Add profile'}</button>}>
          {d.profile ? <div className="text-sm">{label(d.profile.household_type)} · {d.profile.dependants} dependant(s) · {d.profile.employment_type ? label(d.profile.employment_type) : 'employment not entered'}{d.profile.employment_months != null ? ` · ${d.profile.employment_months} months in the job` : ''}</div>
            : <div className="text-sm text-muted">No profile yet: the household type sets the living-cost (HEM) benchmark, so add it before assessing.</div>}
        </Section>
        <Section title="Existing debts" hint="Declared by the applicant or found in their statements. Debts the statements do not show are added to the assessment, never counted twice." actions={caps.includes('edit') && <button className="btn btn-outline btn-sm" onClick={() => setCommit({})}>+ Debt</button>}>
          <DataGrid rows={d.commitments} empty="None recorded" columns={[{ key: 'kind', label: 'Kind', render: r => label(r.kind) }, { key: 'lender', label: 'Lender' }, { key: 'monthly_repayment', label: 'A month', money: true }, { key: 'balance', label: 'Balance', money: true }, { key: 'source', label: 'Source', render: r => <StatusBadge status={r.source === 'detected' ? 'in_progress' : 'draft'} text={label(r.source)} /> },
            { key: 'x', label: '', render: r => caps.includes('edit') && <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={() => setCommit(r)}>Edit</button><button className="btn btn-ghost btn-xs" onClick={async () => { if (window.confirm('Remove this debt?') && await act(() => L.applicants.removeCommitment(id, r.id), 'Removed')) again() }}>Remove</button></span> }]} />
          <div className="text-sm" style={{ marginTop: 6 }}>Total repayments: <Money v={d.commitments_monthly} strong /> a month</div>
        </Section>
        <Section title="Statement analyses" actions={caps.includes('assess') && <button className="btn btn-primary btn-sm" onClick={() => setAnalyse(true)}>Analyse statements</button>}>
          <Async q={an}>{rows => <DataGrid rows={rows} empty="No analysis yet" hint="Upload the applicant's bank statements, or use the bank accounts already in Accfino." onRowClick={r => setOpenA(r.id)} columns={[{ key: 'created_at', label: 'Run', date: true }, { key: 'label', label: 'Label', render: r => r.label || (r.source === 'books' ? 'Accfino bank accounts' : 'Uploaded statements') },
            { key: 'period_from', label: 'Period', render: r => `${fmtDate(r.period_from)} to ${fmtDate(r.period_to)}` }, { key: 'months', label: 'Months', align: 'right' }, { key: 'income_monthly', label: 'Income a month', money: true }, { key: 'surplus_monthly', label: 'Surplus a month', money: true },
            { key: 'superseded', label: '', render: r => (r.superseded ? <span className="badge badge-neutral">Replaced</span> : <span className="badge badge-success">Current</span>) }]} />}</Async>
        </Section>
        {openA && <Modal title="Applicant Financial Summary" onClose={() => { setOpenA(null); again() }} width={1100}><AnalysisView id={openA} caps={caps} applicantId={id} onChanged={again} onClose={() => { setOpenA(null); again() }} /></Modal>}
        {profile && <ProfileForm id={id} item={d.profile} onClose={() => setProfile(false)} onSaved={() => { setProfile(false); again() }} />}
        {commit && <CommitForm id={id} item={commit.id ? commit : null} onClose={() => setCommit(null)} onSaved={() => { setCommit(null); again() }} />}
        {analyse && <AnalyseForm id={id} onClose={() => setAnalyse(false)} onDone={a => { setAnalyse(false); again(); setOpenA(a.id) }} />}
      </div>)}</Async>)
}

function useRef_() { return useLoad(() => L.reference(), []) }

function ProfileForm({ id, item, onClose, onSaved }) {
  const ref = useRef_()
  const [f, set] = useForm({ household_type: 'single_no_children', dependants: 0, employment_type: '', employer: '', employment_months: '', residency: '', notes: '', ...blank(item) })
  return (
    <Modal title="Applicant profile" onClose={onClose} width={560}><Async q={ref}>{r => (
      <>
        <Select label="Household (sets the living-cost benchmark)" value={f.household_type} onChange={set('household_type')} options={r.households} /><Grid cols={2}><Input label="Dependants" type="number" value={f.dependants} onChange={set('dependants')} />
          <Select label="Employment type" value={f.employment_type} blank="Not entered" onChange={set('employment_type')} options={r.employment} /><Input label="Employer" value={f.employer} onChange={set('employer')} /><Input label="Months in current employment" type="number" value={f.employment_months} onChange={set('employment_months')} /></Grid>
        <Input label="Notes" value={f.notes} onChange={set('notes')} />
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={async () => { const b = { ...f }; for (const k of Object.keys(b)) if (b[k] === '') b[k] = null; if (await act(() => L.applicants.saveProfile(id, b), 'Saved')) onSaved() }}>Save</button></div></>)}</Async></Modal>)
}

function CommitForm({ id, item, onClose, onSaved }) {
  const ref = useRef_()
  const [f, set] = useForm({ kind: 'car_loan', lender: '', monthly_repayment: '', balance: '', limit_amount: '', rate_pct: item?.interest_rate ? (Number(item.interest_rate) * 100).toFixed(2) : '', source: 'declared', ...blank(item) })
  const bad = [!(Number(f.monthly_repayment) >= 0 && f.monthly_repayment !== '') && 'Enter the monthly repayment', f.rate_pct !== '' && Number(f.rate_pct) > 50 && 'The rate is a percentage a year, for example 6.5'].filter(Boolean)
  return (
    <Modal title={item ? 'Edit debt' : 'New debt'} onClose={onClose} width={520}><Async q={ref}>{r => (
      <>
        <Grid cols={2}><Select label="Kind" value={f.kind} onChange={set('kind')} options={r.commitment_kinds} /><Input label="Lender" value={f.lender} onChange={set('lender')} /><Input label="Repayment a month" type="number" step="any" value={f.monthly_repayment} onChange={set('monthly_repayment')} />
          <Input label="Balance" type="number" step="any" value={f.balance} onChange={set('balance')} /><Input label="Limit (cards, lines)" type="number" step="any" value={f.limit_amount} onChange={set('limit_amount')} /><Input label="Interest rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} /></Grid>
        {bad.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{bad.join(' · ')}</div>}
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={bad.length > 0} onClick={async () => { const b = { ...f, interest_rate: f.rate_pct === '' ? null : Number(f.rate_pct) / 100 }; delete b.id; delete b.rate_pct; for (const k of Object.keys(b)) if (b[k] === '') b[k] = null; if (await act(() => (item ? L.applicants.updateCommitment(id, item.id, b) : L.applicants.addCommitment(id, b)), 'Saved')) onSaved() }}>Save</button></div></>)}</Async></Modal>)
}

function AnalyseForm({ id, onClose, onDone }) {
  const ref = useRef_()
  const banks = useLoad(() => L.bankAccounts(), [])
  const [mode, setMode] = useState('upload')
  const [files, setFiles] = useState([])
  const [ids, setIds] = useState({})
  const [f, set] = useForm({ household_type: '', proposed_loan: '', rate_pct: '6.5', loan_term_years: '30', date_from: '', date_to: todayISO(), label: '' })
  const [busy, setBusy] = useState(false)
  const input = useRef(null)
  const go = async () => {
    setBusy(true)
    const chosen = Object.keys(ids).filter(k => ids[k]).map(Number)
    const fields = { household_type: f.household_type, proposed_loan: f.proposed_loan || 0, interest_rate: Number(f.rate_pct || 6.5) / 100, loan_term_years: f.loan_term_years, label: f.label }
    const r = await act(() => (mode === 'upload' ? L.analyses.upload(id, files, fields) : L.analyses.fromBooks(id, { account_ids: chosen, date_from: f.date_from, date_to: f.date_to, ...fields, proposed_loan: Number(f.proposed_loan || 0), interest_rate: Number(f.rate_pct || 6.5) / 100, loan_term_years: Number(f.loan_term_years) })), 'Analysis saved')
    setBusy(false)
    if (r && r !== true) onDone(r)
  }
  const ready = mode === 'upload' ? files.length > 0 : Object.values(ids).some(Boolean) && f.date_from && f.date_to
  return (
    <Modal title="Analyse statements" onClose={onClose} width={720}><Async q={ref}>{r => (
      <>
        <div role="radiogroup" aria-label="Where are the statements" className="flex gap-1" style={{ marginBottom: 10 }}>
          <label className="text-sm"><input type="radio" name="src" checked={mode === 'upload'} onChange={() => setMode('upload')} /> Upload statements (PDF, CSV or a photo)</label>
          <label className="text-sm"><input type="radio" name="src" checked={mode === 'books'} onChange={() => setMode('books')} /> Use bank accounts already in Accfino</label></div>
        {mode === 'upload' ? (
          <div style={{ marginBottom: 10 }}><label className="btn btn-outline btn-sm" style={{ cursor: 'pointer', marginBottom: 0 }}>Choose statement files…<input ref={input} type="file" multiple hidden aria-label="Statement files" accept=".pdf,.csv,.png,.jpg,.jpeg,.webp" onChange={e => setFiles(Array.from(e.target.files || []))} /></label>
            <span className="text-xs text-muted" style={{ marginLeft: 8 }}>{files.length ? files.map(x => x.name).join(', ') : 'Up to 12 files, 10 MB each. Three months or more is best.'}</span></div>
        ) : (
          <div style={{ marginBottom: 10 }}><Async q={banks}>{bs => bs.length === 0 ? <div className="text-sm text-muted">No bank accounts in the books yet.</div> : bs.map(b => <Check key={b.id} label={`${b.code} ${b.name}`} checked={!!ids[b.id]} onChange={e => setIds(s => ({ ...s, [b.id]: e.target.checked }))} />)}</Async>
            <Grid cols={2}><Input label="From" type="date" value={f.date_from} onChange={set('date_from')} /><Input label="To" type="date" value={f.date_to} onChange={set('date_to')} /></Grid></div>)}
        <Grid cols={3}><Select label="Household" value={f.household_type} blank="From the profile" onChange={set('household_type')} options={r.households} /><Input label="Loan being considered (AUD)" type="number" value={f.proposed_loan} onChange={set('proposed_loan')} /><Input label="Rate (% a year)" type="number" step="any" value={f.rate_pct} onChange={set('rate_pct')} />
          <Input label="Term (years)" type="number" value={f.loan_term_years} onChange={set('loan_term_years')} /><Input label="Label" value={f.label} onChange={set('label')} /></Grid>
        <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!ready || busy} onClick={go}>{busy ? 'Analysing…' : 'Analyse'}</button></div></>)}</Async></Modal>)
}

// ---- the Applicant Financial Summary -----------------------------------------------------------------------------------------------------------------
export function AnalysisView({ id, caps, applicantId, onChanged, onClose }) {
  const [bump, setBump] = useState(0)
  const [dialog, ask] = usePrompt()
  const [allLines, setAllLines] = useState(false)
  const q = useLoad(() => L.analyses.get(id), [id, bump])
  const ref = useRef_()
  const lines = useLoad(() => L.analyses.lines(id, !allLines), [id, bump, allLines])
  const sug = useLoad(() => L.analyses.suggestions(id), [id, bump])
  const again = () => { setBump(n => n + 1); onChanged && onChanged() }
  const [rf, setRf] = useState(null)
  const override = async line => {
    const cats = ref.data?.categories || []
    const r = await ask({ title: 'Correct the category', message: `${line.description} (${fmtAUD(line.credit > 0 ? line.credit : line.debit)})`, confirmLabel: 'Save', fields: [{ key: 'category', label: `Category (one of: ${cats.slice(0, 6).join(', ')}…)`, value: line.category || '' }, { key: 'reason', label: 'Reason (kept with the analysis)', value: '' }] })
    if (r.ok && await act(() => L.analyses.override(id, line.id, r.values), 'Corrected and re-calculated')) again()
  }
  const reanalyse = async () => { if (await act(() => L.analyses.reanalyse(id, { proposed_loan: Number(rf.proposed_loan || 0), interest_rate: Number(rf.rate_pct) / 100, loan_term_years: Number(rf.loan_term_years), household_type: rf.household_type || undefined }), 'Re-calculated')) { setRf(null); again() } }
  return (
    <div>{dialog}<Async q={q}>{a => {
      const m = a.metrics, s = a.summary, h = s.headline || {}
      const form = rf || { proposed_loan: a.inputs.proposed_loan, rate_pct: (Number(a.inputs.interest_rate) * 100).toFixed(2), loan_term_years: a.inputs.loan_term_years, household_type: a.inputs.household_type }
      return (
        <div>
          <Notice items={(a.reviewed || []).length ? [`${a.reviewed.length} credit(s) look like transfers from the applicant's own accounts and were NOT counted as income. Check them below.`] : []} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10, marginBottom: 12 }} aria-label="Income, expenses, commitments, surplus">
            <Stat label="Income a month" value={<Money v={h.income_monthly} strong />} sub={h.income_verified_pct != null ? `${h.income_verified_pct}% shown to recur` : ''} /><Stat label="Living expenses" value={<Money v={h.expenses_monthly} />} sub={`HEM benchmark ${fmtAUD(m.hem_benchmark_monthly)}`} />
            <Stat label="Existing commitments" value={<Money v={h.existing_commitments_monthly} />} /><Stat label="Surplus (UMI)" value={<Money v={h.surplus_monthly} strong />} tone={Number(h.surplus_monthly) < 0 ? 'danger' : undefined} sub={`${a.months} month(s), ${a.tx_count} transactions`} /></div>
          <Section title="Serviceability" hint="With the loan being considered, at the loan rate plus the buffer.">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
              <Stat label="Repayment a month" value={<Money v={m.proposed_repayment_monthly} />} sub={`at ${(m.assessment_rate * 100).toFixed(2)}%`} /><Stat label="Surplus after the loan" value={<Money v={m.serviced_umi} strong />} tone={Number(m.serviced_umi) < 0 ? 'danger' : undefined} />
              <Stat label="Maximum loan supported" value={<Money v={m.max_borrowing_capacity} strong />} /><Stat label="Debt service ratio" value={`${Number(m.dsr).toFixed(1)}%`} /><Stat label="Loan to income" value={Number(m.lti).toFixed(2)} /><Stat label="Statement risk score" value={`${m.risk_score} (${m.risk_category})`} /></div>
            {caps.includes('assess') && <div className="flex gap-1 items-end" style={{ marginTop: 10, flexWrap: 'wrap' }}>
              <Input label="Loan being considered" type="number" value={form.proposed_loan} onChange={e => setRf({ ...form, proposed_loan: e.target.value })} /><Input label="Rate (% a year)" type="number" step="any" value={form.rate_pct} onChange={e => setRf({ ...form, rate_pct: e.target.value })} />
              <Input label="Term (years)" type="number" value={form.loan_term_years} onChange={e => setRf({ ...form, loan_term_years: e.target.value })} /><Select label="Household" value={form.household_type} onChange={e => setRf({ ...form, household_type: e.target.value })} options={ref.data?.households || []} />
              <div style={{ marginBottom: 14 }}><button className="btn btn-outline btn-sm" disabled={!rf} onClick={reanalyse}>Re-calculate</button></div></div>}
            {(m.flags || []).length > 0 && <div style={{ marginTop: 8 }}>{m.flags.map((f, i) => <div key={i} className="text-sm">{f}</div>)}</div>}
          </Section>
          <Section title="Month by month" hint={s.trend?.note}>
            <div className="text-sm" style={{ marginBottom: 6 }}>Income: <strong>{s.trend?.income}</strong> · Spending: <strong>{s.trend?.spending}</strong></div>
            <DataGrid rows={(s.months || []).map(x => ({ ...x, id: x.month }))} empty="No months" pageSize={12} columns={[{ key: 'month', label: 'Month' }, { key: 'income', label: 'Income', money: true }, { key: 'spending', label: 'Spending', money: true }, { key: 'net', label: 'Net', money: true }, { key: 'transactions', label: 'Transactions', align: 'right' }]} />
          </Section>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(380px,1fr))', gap: 12 }}>
            <Section title="Recurring income"><DataGrid rows={(s.recurring_income || []).map((x, i) => ({ ...x, id: i }))} empty="No recurring income found" columns={[{ key: 'label', label: 'Source' }, { key: 'frequency', label: 'How often', render: r => label(r.frequency) }, { key: 'amount', label: 'Each', money: true }, { key: 'monthly_equivalent', label: 'A month', money: true }]} /></Section>
            <Section title="Recurring commitments" hint="Loan, card and interest payments found in the statements."><DataGrid rows={(s.recurring_commitments || []).map((x, i) => ({ ...x, id: i }))} empty="None found" columns={[{ key: 'label', label: 'Payee' }, { key: 'amount', label: 'Each', money: true }, { key: 'monthly_equivalent', label: 'A month', money: true }]} />
              {caps.includes('edit') && (sug.data || []).length > 0 && <div style={{ marginTop: 6 }}>{sug.data.map((x, i) => <div key={i} className="flex items-center gap-1 text-sm"><span>{x.lender}: {fmtAUD(x.monthly_repayment)} a month ({label(x.kind)})</span><button className="btn btn-outline btn-xs" onClick={async () => { if (await act(() => L.applicants.addCommitment(applicantId || a.contact_id, { kind: x.kind, lender: x.lender, monthly_repayment: x.monthly_repayment, source: 'detected' }), 'Added to the applicant\'s debts')) again() }}>Add as a debt</button></div>)}</div>}</Section>
          </div>
          <Section title="Unusual transactions" hint="Things worth asking about: large one-off payments and deposits, cash, gambling and dishonour fees."><DataGrid rows={(s.unusual || []).map((x, i) => ({ ...x, id: i }))} empty="Nothing unusual found" columns={[{ key: 'date', label: 'Date', date: true }, { key: 'description', label: 'Description' }, { key: 'amount', label: 'Amount', money: true }, { key: 'kind', label: 'Kind', render: r => label(r.kind) }, { key: 'reason', label: 'Why' }]} /></Section>
          <Section title="Account conduct"><div className="text-sm">{s.conduct?.dishonours || 0} dishonour or late-payment fee(s) · {s.conduct?.overdrawn_days || 0} overdrawn day(s)</div></Section>
          {(a.gap_report?.flags || []).length > 0 && <Notice items={a.gap_report.flags} />}
          <Section title={allLines ? 'All transactions' : 'Transactions to check'} actions={<label className="text-sm"><input type="checkbox" checked={allLines} onChange={e => setAllLines(e.target.checked)} /> Show every transaction</label>} hint="Credits treated as transfers, and lines you have corrected. Correct a category and everything is re-calculated; your reason is kept.">
            <Async q={lines}>{rows => <DataGrid rows={rows} empty="Nothing to check" pageSize={15} searchKeys={['description', 'category']} columns={[{ key: 'date', label: 'Date', date: true }, { key: 'description', label: 'Description' }, { key: 'debit', label: 'Out', money: true }, { key: 'credit', label: 'In', money: true }, { key: 'category', label: 'Category', render: r => <span>{r.category}{r.overridden && <span className="badge badge-info" style={{ marginLeft: 4 }} title={r.override_reason}>corrected</span>}{r.reclassified && !r.overridden && <span className="badge badge-warning" style={{ marginLeft: 4 }} title={r.reclassified}>transfer, not income</span>}</span> },
              { key: 'x', label: '', render: r => caps.includes('assess') && <button className="btn btn-ghost btn-xs" onClick={() => override(r)}>Correct</button> }]} />}</Async>
          </Section>
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="btn btn-outline" onClick={onClose}>Close</button></div>
        </div>)
    }}</Async></div>)
}
