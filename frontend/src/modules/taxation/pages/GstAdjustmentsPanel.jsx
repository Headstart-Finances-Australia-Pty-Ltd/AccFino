import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, DataGrid, Disclaimer, Input, Modal, Money, Section, Select, Stat, StatusBadge, useForm, useLoad } from '../components/kit.jsx'
import HistoryButton from '../components/HistoryButton.jsx'
import ImportPanel from '../components/ImportPanel.jsx'
import { fmtDate, label } from '../lib/format.js'

const REASONS = ['bad_debt', 'change_of_extent', 'private_use', 'goods_returned', 'price_change', 'cancelled_supply', 'annual_apportionment', 'other']
const startOfFy = fy => `${fy.slice(0, 4)}-07-01`
const endOfFy = fy => `${Number(fy.slice(0, 4)) + 1}-06-30`
const TONE = { draft: 'upcoming', confirmed: 'completed', void: 'void' }

export default function GstAdjustmentsPanel({ me, fy }) {
  const [f, set] = useForm({ date_from: startOfFy(fy), date_to: endOfFy(fy), adj_type: '', status: '', reason: '', q: '' })
  const [applied, setApplied] = useState(f)
  const [edit, setEdit] = useState(null)
  const list = useLoad(() => api.gst.list(Object.fromEntries(Object.entries(applied).filter(([, v]) => v !== ''))), [JSON.stringify(applied)])
  const sum = useLoad(() => api.gst.summary(applied.date_from, applied.date_to), [applied.date_from, applied.date_to, list.data?.length])
  const caps = me.capabilities
  const reload = () => { list.reload(); sum.reload() }
  const status = async (a, s) => { if (await act(() => api.gst.status(a.id, s), `Marked ${s}`)) reload() }
  const remove = async a => { if (window.confirm(`Delete this GST adjustment (${a.description})?`) && await act(() => api.gst.remove(a.id), 'Deleted')) reload() }
  const badRange = f.date_from && f.date_to && f.date_to < f.date_from
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <div className="text-sm text-muted" style={{ marginBottom: 10 }}>Adjustments that are not normal invoice lines. <strong>Confirmed</strong> adjustments inside a BAS period are added to that statement (increasing → 1A, decreasing → 1B); drafts and voided ones never are. Periods whose statement is approved or lodged are locked.</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 8, alignItems: 'end' }}>
        <Input label="From" type="date" value={f.date_from} onChange={set('date_from')} /><Input label="To" type="date" value={f.date_to} onChange={set('date_to')} />
        <Select label="Type" value={f.adj_type} blank="All" onChange={set('adj_type')} options={['increasing', 'decreasing']} /><Select label="Status" value={f.status} blank="All" onChange={set('status')} options={['draft', 'confirmed', 'void']} />
        <Select label="Reason" value={f.reason} blank="All" onChange={set('reason')} options={REASONS.map(r => ({ value: r, label: label(r) }))} /><Input label="Search description / reference" value={f.q} onChange={set('q')} />
        <div style={{ marginBottom: 14 }}><button className="btn btn-primary btn-sm" disabled={badRange} onClick={() => setApplied(f)}>Apply filters</button></div></div>
      {badRange && <div className="text-xs" style={{ color: 'var(--danger)' }}>The end date is before the start date.</div>}
      <Async q={sum}>{s => (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, margin: '8px 0 12px' }}>
          <Stat label="Adjustments in range" value={s.count} sub={Object.entries(s.by_status).map(([k, v]) => `${v} ${k}`).join(' · ') || 'none'} />
          <Stat label="Increasing (confirmed) → 1A" value={<Money v={s.increasing_confirmed} />} /><Stat label="Decreasing (confirmed) → 1B" value={<Money v={s.decreasing_confirmed} />} />
          <Stat label="Net effect on label 9" value={<Money v={s.net_effect_on_label_9} strong />} sub="increasing less decreasing" /></div>)}</Async>
      <Section title="GST adjustments register" actions={<>{caps.includes('prepare') && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>+ Adjustment</button>}<ImportPanel datasets={[{ key: 'gst_adjustments', label: 'GST adjustments' }]} caps={caps} onDone={reload} /></>}>
        <Async q={list}>{rows => <DataGrid rows={rows} empty="No GST adjustments match" hint="Add one, import a CSV, or widen the filters." columns={[
          { key: 'adj_date', label: 'Date', date: true }, { key: 'adj_type', label: 'Type', render: a => (a.adj_type === 'increasing' ? '▲ Increasing' : '▼ Decreasing') },
          { key: 'description', label: 'Description', render: a => <>{a.description}<div className="text-xs text-muted">{a.reason_label}{a.source === 'import' ? ' · imported' : ''}</div></> },
          { key: 'amount_ex_gst', label: 'Ex GST', money: true }, { key: 'gst_amount', label: 'GST', money: true }, { key: 'reference', label: 'Reference' },
          { key: 'status', label: 'Status', render: a => <StatusBadge status={TONE[a.status]} text={label(a.status)} /> },
          { key: 'x', label: '', render: a => caps.includes('prepare') && <span className="flex gap-1" style={{ flexWrap: 'wrap' }}>
            <button className="btn btn-ghost btn-xs" onClick={() => setEdit(a)}>Edit</button>
            {a.status !== 'confirmed' && <button className="btn btn-ghost btn-xs" onClick={() => status(a, 'confirmed')}>Confirm</button>}
            {a.status !== 'void' && <button className="btn btn-ghost btn-xs" onClick={() => status(a, 'void')}>Void</button>}
            {a.status !== 'draft' && <button className="btn btn-ghost btn-xs" onClick={() => status(a, 'draft')}>Draft</button>}
            <button className="btn btn-ghost btn-xs" onClick={() => remove(a)}>Delete</button><HistoryButton type="tax_gst_adjustment" id={a.id} caps={caps} /></span> }]} searchKeys={['description', 'reference']} />}</Async>
      </Section>
      {edit && <Editor item={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </div>)
}

function Editor({ item, onClose, onSaved }) {
  const [f, set] = useForm({ adj_date: '', adj_type: 'decreasing', reason: 'other', description: '', amount_ex_gst: '', gst_amount: '', reference: '', status: 'confirmed', ...Object.fromEntries(Object.entries(item).map(([k, v]) => [k, v ?? ''])) })
  const gst = Number(f.gst_amount), ex = Number(f.amount_ex_gst)
  const problems = [!f.adj_date && 'Date is required', !f.description.trim() && 'Description is required', !(gst > 0) && 'GST must be greater than zero', ex > 0 && gst > Math.round(ex * 10) / 100 + 0.05 && 'GST cannot be more than 10% of the amount'].filter(Boolean)
  const hints = [ex > 0 && gst > 0 && gst < Math.round(ex * 10) / 100 - 0.05 && 'GST is less than 10% of the amount: confirm it is a partial claim or has a GST-free part', f.reason === 'other' && 'Reason “other”: explain the adjustment in the description'].filter(Boolean)
  const go = async () => { const b = { ...f }; ['id', 'reason_label', 'source', 'created_at'].forEach(k => delete b[k]); if (await act(() => api.gst.save(b, item.id), 'Saved')) onSaved() }
  return (
    <Modal title={item.id ? 'Edit GST adjustment' : 'New GST adjustment'} onClose={onClose} width={560}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}><Input label="Adjustment date" type="date" value={f.adj_date} onChange={set('adj_date')} />
        <Select label="Type" value={f.adj_type} onChange={set('adj_type')} options={[{ value: 'increasing', label: 'Increasing (adds to 1A)' }, { value: 'decreasing', label: 'Decreasing (adds to 1B)' }]} /></div>
      <Select label="Reason" value={f.reason} onChange={set('reason')} options={REASONS.map(r => ({ value: r, label: label(r) }))} /><Input label="Description" value={f.description} onChange={set('description')} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}><Input label="Amount excl. GST" type="number" value={f.amount_ex_gst} onChange={set('amount_ex_gst')} /><Input label="GST amount" type="number" value={f.gst_amount} onChange={set('gst_amount')} />
        <Select label="Status" value={f.status} onChange={set('status')} options={['draft', 'confirmed', 'void']} /></div>
      <Input label="Reference" value={f.reference} onChange={set('reference')} />
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      {hints.length > 0 && <div className="text-xs" style={{ color: 'var(--warning)' }}>▲ {hints.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={problems.length > 0} onClick={go}>Save</button></div>
    </Modal>)
}
