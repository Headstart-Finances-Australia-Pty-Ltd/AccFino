import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Disclaimer, Findings, Grid, Input, Money, Section, Stat, Steps, StatusBadge, usePrompt, useForm, useLoad, WorkflowBar } from '../components/kit.jsx'
import { fmtDate, label, METHOD } from '../lib/format.js'
import LodgementPanel, { useLodgement } from '../components/LodgementPanel.jsx'

const FIELDS = [['other_income', 'Other income (salary, interest, dividends, rent)'], ['labour_income', 'Labour income (for the standard deduction)'], ['work_expenses_itemised', 'Itemised work-related expenses claimed'],
  ['deductions_other', 'Other deductions not in the accounts'], ['franking_credits', 'Franking credits'], ['tax_withheld', 'PAYG tax withheld by payers'], ['help_repayment', 'HELP / study loan repayment (from ATO)'],
  ['medicare_surcharge', 'Medicare levy surcharge (if any)'], ['other_offsets', 'Other tax offsets'], ['losses_brought_forward', 'Tax losses brought forward'],
  ['net_capital_gain_override', 'Net capital gain entered by you (required for CGT events on or after 1 July 2027; replaces the calculated figure)']]

// Only the inputs that change the result for this entity type are shown (the engines ignore the rest): an individual's HELP debt means nothing to a company.
const KEYS = {
  individual: FIELDS.map(f => f[0]), sole_trader: FIELDS.map(f => f[0]),
  company: ['other_income', 'deductions_other', 'franking_credits', 'losses_brought_forward', 'net_capital_gain_override'], smsf: ['other_income', 'deductions_other', 'franking_credits', 'losses_brought_forward', 'net_capital_gain_override'],
  partnership: ['other_income', 'deductions_other', 'net_capital_gain_override'], trust: ['other_income', 'deductions_other', 'net_capital_gain_override'],
}
export const fieldsFor = entity => FIELDS.filter(([k]) => (KEYS[entity] || KEYS.individual).includes(k))

export default function ReturnsTab({ me, fy, legacy }) {
  const [open, setOpen] = useState(null)
  const q = useLoad(() => api.returns.list({ fy }), [fy])
  const can = me.capabilities.includes('prepare')
  if (open) return <Detail id={open} me={me} onBack={() => { setOpen(null); q.reload() }} />
  const create = async () => { const r = await act(() => api.returns.create({ fy }), 'Return created'); if (r) setOpen(r.id) }
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <div className="flex items-center justify-between" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8 }}><h3 style={{ margin: 0 }}>Income tax returns {fy}</h3>{can && <button className="btn btn-primary" onClick={create}>+ Start {fy} return</button>}</div>
      <Async q={q}>{rows => <DataGrid rows={rows} empty="No return started for this year" hint="Start a return: it begins from the ledger profit for the year." onRowClick={r => setOpen(r.id)}
        columns={[{ key: 'fy', label: 'Year' }, { key: 'entity_type', label: 'Entity', render: r => label(r.entity_type) }, { key: 'version', label: 'Version', render: r => `v${r.version}` }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
          { key: 'taxable_income', label: 'Taxable income', money: true }, { key: 'tax_payable', label: 'Payable / (refund)', money: true }, { key: 'due_date', label: 'Due', date: true }, { key: 'lodgement_reference', label: 'ATO reference' }]} />}</Async>
      {legacy && <details style={{ marginTop: 20 }}><summary className="text-sm" style={{ cursor: 'pointer' }}>Legacy individual return worksheet (not linked to the ledger; uses 2024-25 rates — do not rely on it for 2026-27)</summary><div style={{ marginTop: 10 }}>{legacy}</div></details>}
    </div>)
}

function Detail({ id, me, onBack }) {
  const q = useLoad(() => api.returns.get(id), [id])
  const [dialog, ask] = usePrompt()
  const [f, set, setF] = useForm({})
  const [loaded, setLoaded] = useState(null)
  const caps = me.capabilities
  const lg = useLodgement('tax_return', id, q.data?.status)
  const after = r => { q.reload(); lg.reload() }
  return (
    <div style={{ padding: 16 }}>
      {dialog}
      <button className="btn btn-ghost btn-sm" onClick={onBack}>← All returns</button>
      <Async q={q}>{r => {
        if (loaded !== r.version + ':' + r.id + ':' + JSON.stringify(r.inputs)) { setLoaded(r.version + ':' + r.id + ':' + JSON.stringify(r.inputs)); setF({ ...r.inputs }) }
        const editable = ['draft', 'prepared'].includes(r.status)
        const c = r.computation || {}
        const save = async () => { const body = {}; fieldsFor(r.entity_type).forEach(([k]) => { if (f[k] !== undefined) body[k] = f[k] === '' ? null : f[k] }); if (await act(() => api.returns.inputs(id, body), 'Inputs saved')) after() }
        const assess = async () => { const x = await ask({ title: 'Record notice of assessment', confirmLabel: 'Record', fields: [{ key: 'amount', label: 'Assessed amount payable (+) / refundable (−)', type: 'number' }, { key: 'assessed_on', label: 'Date', type: 'date', required: false }] }); if (x.ok && await act(() => api.returns.assessment(id, { ...x.values, assessed_on: x.values.assessed_on || undefined }), 'Assessment recorded')) after() }
        const amend = async () => { const x = await ask({ title: 'Amend this return', message: 'Opens a new draft version with the same inputs. The lodged version stays on record.', confirmLabel: 'Open amendment', fields: [{ key: 'reason', label: 'Reason for amendment' }] }); if (x.ok) { const n = await act(() => api.returns.amend(id, x.values), 'Amendment opened'); if (n) onBack() } }
        const wp = async () => act(() => api.workpapers.generate({ kind: 'tax_return', doc_id: id }), 'Workpaper created')
        return (
          <>
            <h3 style={{ margin: '6px 0' }}>Income tax return {r.fy} <span className="text-sm text-muted">v{r.version} · {label(r.entity_type)}</span></h3>
            <WorkflowBar doc={r} caps={caps} api={api.returns} noun="return" onChange={after} declarationOk={lg.data ? lg.data.declaration_ok : undefined}
              extra={<>{['lodged', 'paid'].includes(r.status) && caps.includes('lodge') && <button className="btn btn-outline btn-sm" onClick={assess}>Record assessment</button>}
                {['lodged', 'paid'].includes(r.status) && caps.includes('prepare') && <button className="btn btn-outline btn-sm" onClick={amend}>Amend</button>}
                {r.calculated && caps.includes('prepare') && <button className="btn btn-outline btn-sm" onClick={wp}>Create workpaper</button>}</>} />
            {r.lodgement_reference && <div className="text-sm">Lodged {fmtDate(r.lodged_on)} via {METHOD[r.lodgement_method] || r.lodgement_method} — reference <strong>{r.lodgement_reference}</strong>{r.assessed_amount != null && ` · assessed ${r.assessed_amount} on ${fmtDate(r.assessed_on)} (AccFino computed ${r.tax_payable})`}</div>}
            {r.calculated && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, margin: '10px 0' }}>
              <Stat label="Taxable income" value={<Money v={c.taxable_income} />} /><Stat label="Tax assessed" value={<Money v={c.tax_assessed} />} /><Stat label="Credits" value={<Money v={c.credits} />} /><Stat label="Payable / (refund)" value={<Money v={c.balance} strong />} tone={Number(c.balance) > 0 ? 'danger' : 'success'} /></div>}
            <LodgementPanel st={lg} caps={caps} docType="tax_return" docId={id} onChange={() => q.reload()} />
            <Section title="Your inputs" hint="Things the ledger cannot know. Source figures come from the ledger, adjustments and the CGT register.">
              <Grid cols={2}>{fieldsFor(r.entity_type).map(([k, l]) => <Input key={k} label={l} type="number" value={f[k] ?? ''} disabled={!editable} onChange={set(k)} />)}</Grid>
              {r.entity_type === 'trust' || r.entity_type === 'partnership' ? <p className="text-xs text-muted">Partner / beneficiary allocations are set through the API (allocations: [{`{name, percent}`}]); they must total 100%.</p> : null}
              {editable && caps.includes('prepare') && <button className="btn btn-primary btn-sm" onClick={save}>Save inputs</button>}
            </Section>
            {r.calculated ? <><Section title="Working"><Steps steps={c.steps} /></Section><Section title="Checks and findings"><Findings items={r.findings} /></Section></> : <p className="text-muted">Save your inputs, then calculate.</p>}
          </>)
      }}</Async>
    </div>)
}
