import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Findings, Input, Modal, Money, Section, Select, StatusBadge, useForm, useLoad, usePrompt } from '../components/kit.jsx'
import { label } from '../lib/format.js'
import ImportPanel from '../components/ImportPanel.jsx'
import HistoryButton from '../components/HistoryButton.jsx'

export default function IncomeTab({ me, fy }) {
  const adj = useLoad(() => api.adjustments.list(fy), [fy])
  const ref = useLoad(() => api.reference(fy), [fy])
  const assets = useLoad(() => api.assetsReview(fy), [fy])
  const [edit, setEdit] = useState(null)
  const [dialog, ask] = usePrompt()
  const caps = me.capabilities
  const remove = async a => { if (await act(() => api.adjustments.remove(fy, a.id), 'Deleted')) adj.reload() }
  const review = async a => { const r = await ask({ title: 'Review adjustment', message: a.description, confirmLabel: 'Mark reviewed', fields: [{ key: 'note', label: 'Review note', required: false }] }); if (r.ok && await act(() => api.adjustments.review(a.id, r.values), 'Reviewed')) adj.reload() }
  const gen = async () => { if (await act(() => api.adjustments.generateDepreciation(fy), 'Depreciation adjustments generated')) { adj.reload(); assets.reload() } }
  return (
    <div style={{ padding: 16 }}>
      {dialog}
      <Disclaimer />
      <Section title={`Book-to-tax adjustments ${fy}`} hint="Added to or deducted from the ledger profit when the return is calculated. Estimates and assumptions must be reviewed before approval."
        actions={<><ImportPanel datasets={[{ key: 'income_adjustments', label: 'Book-to-tax adjustments' }, { key: 'income_return_inputs', label: 'Income tax return inputs' }]} caps={caps} onDone={() => { adj.reload(); assets.reload() }} />{caps.includes('prepare') && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>+ Adjustment</button>}</>}>
        <Async q={adj}>{rows => <DataGrid rows={rows} empty="No adjustments" hint="Typical items: non-deductible entertainment, private use, depreciation differences." columns={[
          { key: 'description', label: 'Description', render: a => <>{a.description}<div className="text-xs text-muted">{a.code}{a.source !== 'manual' ? ` · generated (${a.source})` : ''}</div></> },
          { key: 'direction', label: 'Effect', render: a => (a.direction === 'add' ? 'Adds to income' : 'Deducts') }, { key: 'amount', label: 'Amount', money: true },
          { key: 'category', label: 'Basis', render: a => label(a.category) },
          { key: 'requires_review', label: 'Review', render: a => (a.requires_review ? (a.reviewed ? <StatusBadge status="approved" text="Reviewed" /> : <StatusBadge status="due_soon" text="Needs review" />) : '—') },
          { key: 'x', label: '', render: a => <span className="flex gap-1">{a.requires_review && !a.reviewed && caps.includes('approve') && <button className="btn btn-outline btn-xs" onClick={() => review(a)}>Review</button>}
            {caps.includes('prepare') && a.source === 'manual' && <button className="btn btn-ghost btn-xs" onClick={() => setEdit(a)}>Edit</button>}{caps.includes('prepare') && <button className="btn btn-ghost btn-xs" onClick={() => remove(a)}>Delete</button>}<HistoryButton type="tax_adjustment" id={a.id} caps={caps} /></span> }]} />}</Async>
      </Section>
      <Section title="Depreciation and instant asset write-off review" hint="From the Fixed Assets register. Computed only for small business entities with a known turnover."
        actions={caps.includes('prepare') && assets.data?.computed && <button className="btn btn-outline btn-sm" onClick={gen}>Generate adjustments</button>}>
        <Async q={assets}>{a => (
          <>
            {a.warnings.map((w, i) => <div key={i} className="text-sm" style={{ color: 'var(--warning)' }}>▲ {w}</div>)}
            {a.computed && <div className="text-sm" style={{ margin: '6px 0' }}>Instant write-off <Money v={a.iawo_total} /> · Pool deduction <Money v={a.pool?.deduction} /> · Tax depreciation <Money v={a.tax_depreciation} strong /> · Book depreciation <Money v={a.book_depreciation} /> · Difference <Money v={a.difference} /></div>}
            {a.pool && <div className="text-xs text-muted">Pool: opening {a.pool.opening}, additions {a.pool.additions}, disposals {a.pool.disposals} → closing {a.pool.closing}. {a.pool.method}</div>}
            <DataGrid rows={a.lines} empty="No fixed assets" columns={[{ key: 'number', label: 'No.' }, { key: 'name', label: 'Asset' }, { key: 'treatment', label: 'Treatment', render: l => label(l.treatment) }, { key: 'cost', label: 'Cost', money: true },
              { key: 'deduction', label: 'Tax deduction', money: true }, { key: 'book', label: 'Book depreciation', money: true }, { key: 'note', label: 'Note', render: l => <span className="text-xs text-muted">{l.note}</span> }]} rowKey="asset_id" />
          </>)}</Async>
      </Section>
      {edit && <Editor fy={fy} item={edit} codes={ref.data?.adjustments || []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); adj.reload() }} />}
    </div>)
}

function Editor({ fy, item, codes, onClose, onSaved }) {
  const [f, set, setF] = useForm({ code: 'OTHER', description: '', direction: 'add', amount: '', category: 'user_entered', requires_review: false, review_note: '', ...Object.fromEntries(Object.entries(item).map(([k, v]) => [k, v ?? ''])) })
  const pick = e => { const c = codes.find(x => x.code === e.target.value); setF(s => ({ ...s, code: e.target.value, direction: c?.direction || s.direction, description: s.description || c?.label || '' })) }
  const problems = [!f.description.trim() && 'Description is required', !(Number(f.amount) >= 0) || f.amount === '' ? 'Enter an amount (zero or more)' : null].filter(Boolean)
  const go = async () => { const body = { ...f, requires_review: !!f.requires_review || ['assumption', 'estimate'].includes(f.category) }; delete body.id; delete body.reviewed; delete body.fy; delete body.source; delete body.reviewed_by; delete body.workpaper_id; if (await act(() => api.adjustments.save(fy, body, item.id), 'Saved')) onSaved() }
  return (
    <Modal title={item.id ? 'Edit adjustment' : 'New adjustment'} onClose={onClose} width={520}>
      <Select label="Type" value={f.code} onChange={pick} options={codes.map(c => ({ value: c.code, label: c.label }))} />
      <Input label="Description" value={f.description} onChange={set('description')} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
        <Select label="Effect" value={f.direction} onChange={set('direction')} options={[{ value: 'add', label: 'Adds to income' }, { value: 'deduct', label: 'Deducts' }]} />
        <Input label="Amount" type="number" value={f.amount} onChange={set('amount')} />
        <Select label="Basis" value={f.category} onChange={set('category')} options={['user_entered', 'calculated', 'assumption', 'estimate']} /></div>
      <Check label="Requires review by an approver before the return can be approved" checked={f.requires_review || ['assumption', 'estimate'].includes(f.category)} onChange={set('requires_review')} />
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={problems.length > 0} onClick={go}>Save</button></div>
    </Modal>)
}
