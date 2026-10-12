import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Findings, Input, Modal, Money, Section, Select, Stat, StatusBadge, useForm, useLoad } from '../components/kit.jsx'
import { label } from '../lib/format.js'
import ImportPanel from '../components/ImportPanel.jsx'
import HistoryButton from '../components/HistoryButton.jsx'

const CLASSES = ['shares', 'etf', 'crypto', 'property', 'business_asset', 'other']

export default function CgtTab({ me, fy, legacy }) {
  const calc = useLoad(() => api.cgt.compute(fy), [fy])
  const ev = useLoad(() => api.cgt.events(fy), [fy])
  const losses = useLoad(() => api.cgt.losses(), [])
  const [edit, setEdit] = useState(null)
  const [imp, setImp] = useState(false)
  const [loss, setLoss] = useState(false)
  const can = me.capabilities.includes('prepare')
  const reload = () => { calc.reload(); ev.reload(); losses.reload() }
  const remove = async e => { if (await act(() => api.cgt.remove(e.id), 'Deleted')) reload() }
  const exclude = async e => { if (await act(() => api.cgt.exclude(e.id, !e.excluded), e.excluded ? 'Included' : 'Excluded')) reload() }
  const resultFor = id => calc.data?.events?.find(x => x.id === id)
  return (
    <div style={{ padding: 16 }}>
      <Disclaimer />
      <Async q={calc}>{c => (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginBottom: 12 }}>
            <Stat label="Gains before losses" value={<Money v={c.total_gains_before_losses} />} /><Stat label="Current-year losses" value={<Money v={c.current_year_losses} />} />
            <Stat label="Prior losses applied" value={<Money v={c.prior_losses_applied} />} /><Stat label="Discount applied" value={<Money v={c.discount_applied} />} />
            <Stat label="Net capital gain" value={<Money v={c.net_capital_gain} strong />} sub={`holder: ${label(c.holder)}`} /><Stat label="Losses carried forward" value={<Money v={c.losses_carried_forward} />} /></div>
          {c.review.length > 0 && <Section title="Needs review"><Findings items={c.review.map((m, i) => ({ key: 'r' + i, severity: 'review', message: m }))} /></Section>}
          <div className="text-xs text-muted" style={{ marginBottom: 8 }}>{c.assumption} {c.loss_register_note}</div>
        </>)}</Async>
      <Section title={`CGT events ${fy}`} actions={<>{can && <button className="btn btn-outline btn-sm" onClick={() => setImp(true)}>Import from Trading / CSV</button>}<ImportPanel datasets={[{ key: 'cgt_events', label: 'CGT events' }, { key: 'cgt_losses', label: 'Capital losses brought forward' }]} caps={me.capabilities} onDone={reload} />{can && <button className="btn btn-primary btn-sm" onClick={() => setEdit({})}>+ Event</button>}</>}>
        <Async q={ev}>{rows => <DataGrid rows={rows} searchKeys={['asset_name']} empty="No CGT events for this year" hint="Add property or other disposals, or import shares and crypto disposals from Trading." columns={[
          { key: 'asset_name', label: 'Asset', render: e => <>{e.asset_name}<div className="text-xs text-muted">{label(e.asset_class)} · {e.source === 'trading_import' ? 'imported' : e.source}</div></> },
          { key: 'acquire_date', label: 'Acquired', date: true }, { key: 'dispose_date', label: 'Disposed', date: true }, { key: 'proceeds', label: 'Proceeds', money: true },
          { key: 'gain', label: 'Gain / (loss)', render: e => { const r = resultFor(e.id); return r ? <Money v={Number(r.gain) - Number(r.loss)} /> : '—' } },
          { key: 'disc', label: 'Discount', render: e => { const r = resultFor(e.id); return r ? (r.status === 'exempt' ? <StatusBadge status="completed" text="Exempt" /> : r.discountable ? '50% eligible' : '—') : (e.excluded ? <StatusBadge status="void" text="Excluded" /> : '—') } },
          { key: 'x', label: '', render: e => can && <span className="flex gap-1"><button className="btn btn-ghost btn-xs" onClick={() => setEdit(e)}>Edit</button><button className="btn btn-ghost btn-xs" onClick={() => exclude(e)}>{e.excluded ? 'Include' : 'Exclude'}</button><button className="btn btn-ghost btn-xs" onClick={() => remove(e)}>Delete</button><HistoryButton type="tax_cgt_event" id={e.id} caps={me.capabilities} /></span> }]} />}</Async>
      </Section>
      <Section title="Capital losses brought forward" hint="Entered by you. After each return, update this register with the carried-forward amount shown above."
        actions={can && <button className="btn btn-outline btn-sm" onClick={() => setLoss(true)}>+ Loss</button>}>
        <Async q={losses}>{rows => <DataGrid rows={rows} empty="No capital losses recorded" columns={[{ key: 'fy_incurred', label: 'Year incurred' }, { key: 'amount', label: 'Amount', money: true }, { key: 'note', label: 'Note' },
          { key: 'x', label: '', render: l => can && <button className="btn btn-ghost btn-xs" onClick={async () => { if (await act(() => api.cgt.removeLoss(l.id), 'Deleted')) reload() }}>Delete</button> }]} />}</Async>
      </Section>
      {edit && <Editor item={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
      {imp && <Import onClose={() => setImp(false)} onDone={() => { setImp(false); reload() }} />}
      {loss && <Loss onClose={() => setLoss(false)} onDone={() => { setLoss(false); reload() }} />}
      {legacy && <details style={{ marginTop: 20 }}><summary className="text-sm" style={{ cursor: 'pointer' }}>Legacy property CGT calculator (stand-alone estimate, not linked to returns)</summary><div style={{ marginTop: 10 }}>{legacy}</div></details>}
    </div>)
}

function Editor({ item, onClose, onSaved }) {
  const [f, set] = useForm({ asset_name: '', asset_class: 'shares', acquire_date: '', dispose_date: '', proceeds: '', acquisition_cost: '', incidental_costs: '', ownership_costs: '', capital_improvements: '', disposal_costs: '', pre_cgt: false, main_residence_exempt: false, notes: '',
    ...Object.fromEntries(Object.entries(item).map(([k, v]) => [k, v ?? ''])) })
  const problems = [!f.asset_name.trim() && 'Asset name is required', (!f.acquire_date || !f.dispose_date) && 'Both dates are required', f.acquire_date && f.dispose_date && f.dispose_date < f.acquire_date && 'Disposal cannot be before acquisition', f.proceeds === '' && 'Proceeds are required'].filter(Boolean)
  const go = async () => { const b = { ...f }; ['id', 'fy', 'source', 'source_ref', 'excluded', 'quantity'].forEach(k => delete b[k]); if (await act(() => api.cgt.save(b, item.id), 'Saved')) onSaved() }
  return (
    <Modal title={item.id ? 'Edit CGT event' : 'New CGT event'} onClose={onClose} width={620}>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 10 }}><Input label="Asset" value={f.asset_name} onChange={set('asset_name')} /><Select label="Class" value={f.asset_class} onChange={set('asset_class')} options={CLASSES} /></div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}><Input label="Acquired" type="date" value={f.acquire_date} onChange={set('acquire_date')} /><Input label="Disposed" type="date" value={f.dispose_date} onChange={set('dispose_date')} /><Input label="Proceeds" type="number" value={f.proceeds} onChange={set('proceeds')} /></div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}><Input label="Cost" type="number" value={f.acquisition_cost} onChange={set('acquisition_cost')} /><Input label="Incidental" type="number" value={f.incidental_costs} onChange={set('incidental_costs')} />
        <Input label="Improvements" type="number" value={f.capital_improvements} onChange={set('capital_improvements')} /><Input label="Selling costs" type="number" value={f.disposal_costs} onChange={set('disposal_costs')} /></div>
      {f.dispose_date >= '2027-07-01' && <div role="alert" className="alert alert-error" style={{ margin: '8px 0' }}>Disposals on or after 1 July 2027 fall under the new CGT regime (Treasury Laws Amendment (Tax Reform No. 1) Act 2026: indexation and a 30% minimum tax on gains accruing from that date). AccFino cannot calculate that yet, so it will not prepare a return for that year. Take advice before relying on this event.</div>}
      <Check label="Pre-CGT asset (acquired before 20 September 1985)" checked={f.pre_cgt} onChange={set('pre_cgt')} />
      {f.asset_class === 'property' && <Check label="Main residence exemption claimed in full (partial exemptions are not assessed)" checked={f.main_residence_exempt} onChange={set('main_residence_exempt')} />}
      {problems.length > 0 && <div className="text-xs" style={{ color: 'var(--danger)' }}>{problems.join(' · ')}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={problems.length > 0} onClick={go}>Save</button></div>
    </Modal>)
}

function Import({ onClose, onDone }) {
  const [text, setText] = useState('')
  const [cls, setCls] = useState('shares')
  const [res, setRes] = useState(null)
  const run = async dry => { const r = await act(() => api.cgt.importRows({ text, asset_class: cls, dry_run: dry }), dry ? undefined : 'Imported'); if (r) { setRes(r); if (!dry) onDone() } }
  return (
    <Modal title="Import disposals" onClose={onClose} width={680}>
      <p className="text-sm">Paste the Disposals sheet exported from Investments (columns: Disposal Date, Asset Name, Qty Disposed, Total Proceeds ($), Total Cost Base ($), Acquisition Date, Reference) as CSV. Re-importing the same rows is safe: duplicates are skipped. <strong>Crypto:</strong> use a per-disposal export that includes each acquisition date. The Investments crypto report only gives per-asset totals, which are not enough to tell whether the 12-month discount applies.</p>
      <Select label="Asset class" value={cls} onChange={e => setCls(e.target.value)} options={CLASSES} />
      <textarea className="input" aria-label="CSV text" rows={8} value={text} onChange={e => setText(e.target.value)} style={{ width: '100%', fontFamily: 'monospace' }} />
      {res && <div className="text-sm" style={{ marginTop: 8 }}>{res.dry_run ? 'Preview: ' : ''}{res.added} to add · {res.skipped_duplicates} duplicates · {res.rejected} rejected{res.errors.slice(0, 5).map(e => <div key={e.row} style={{ color: 'var(--danger)' }}>Row {e.row}: {e.error}</div>)}</div>}
      <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 10 }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-outline" disabled={!text.trim()} onClick={() => run(true)}>Preview</button><button className="btn btn-primary" disabled={!text.trim()} onClick={() => run(false)}>Import</button></div>
    </Modal>)
}

function Loss({ onClose, onDone }) {
  const [f, set] = useForm({ fy_incurred: '', amount: '', note: '' })
  return (
    <Modal title="Capital loss brought forward" onClose={onClose} width={420}>
      <Input label="Year incurred (e.g. 2024-25)" value={f.fy_incurred} onChange={set('fy_incurred')} /><Input label="Amount" type="number" value={f.amount} onChange={set('amount')} /><Input label="Note" value={f.note} onChange={set('note')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.fy_incurred || !(Number(f.amount) > 0)} onClick={async () => { if (await act(() => api.cgt.addLoss(f), 'Saved')) onDone() }}>Save</button></div>
    </Modal>)
}
