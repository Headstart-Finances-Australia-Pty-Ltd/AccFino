import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Async, Check, DataGrid, Disclaimer, Grid, Input, Modal, Section, Select, StatusBadge, useForm, useLoad } from '../components/kit.jsx'
import { label } from '../lib/format.js'

// Bracket tables read as 'up to $18,200 – 0%' instead of raw JSON; other objects stay compact JSON.
const pct = r => `${(Number(r) * 100).toFixed(2).replace(/\.?0+$/, '')}%`
export const showValue = v => {
  if (Array.isArray(v) && v.length && v.every(r => Array.isArray(r) && r.length === 2)) return v.map(([up, rate]) => `${up === null ? 'above' : 'up to $' + Number(up).toLocaleString('en-AU')} – ${pct(rate)}`).join('\n')
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}
const VER = { ato_primary: ['Read on ATO page', 'completed'], secondary_consistent: ['Secondary sources agree', 'in_progress'], knowledge_unverified: ['Unverified — confirm', 'overdue'], not_loaded: ['Not loaded', 'overdue'] }

export default function SettingsTab({ me, fy }) {
  const [sub, setSub] = useState('profile')
  return (
    <div style={{ padding: 16 }}>
      <div className="tabs-bar" style={{ marginBottom: 12 }}>{[['profile', 'Tax profile'], ['rates', 'Statutory rates']].map(([k, l]) => <button key={k} className={`tab-btn${sub === k ? ' active' : ''}`} onClick={() => setSub(k)}>{l}</button>)}</div>
      {sub === 'profile' ? <Profile me={me} /> : <Rates me={me} fy={fy} />}
    </div>)
}

function Profile({ me }) {
  const q = useLoad(() => api.profile(), [])
  const ref = useLoad(() => api.reference(), [])
  return <Async q={q}>{p => <ProfileForm p={p} ref_={ref.data} me={me} onSaved={q.reload} />}</Async>
}

function ProfileForm({ p, ref_, me, onSaved }) {
  const [f, set] = useForm({ ...p, extra_holidays: (p.extra_holidays || []).join(', ') })
  const can = me.capabilities.includes('config')
  const save = async () => {
    const b = { ...f, extra_holidays: String(f.extra_holidays || '').split(',').map(s => s.trim()).filter(Boolean) }; delete b.updated_at; delete b.is_small_business_entity_hint
    ;['payg_instalment_amount', 'payg_instalment_rate', 'fbt_instalment_amount', 'aggregated_turnover', 'passive_income_ratio', 'pool_opening_balance', 'state'].forEach(k => { if (b[k] === '') b[k] = null })
    if (await act(() => api.saveProfile(b), 'Profile saved')) onSaved() }
  const dis = !can
  return (
    <div>
      <Disclaimer />
      {!can && <div className="text-sm text-muted" style={{ marginBottom: 8 }}>Only an Accountant or the Organisation Admin can change the tax profile.</div>}
      <Section title="Entity"><Grid cols={3}>
        <Select label="Entity type" value={f.entity_type} onChange={set('entity_type')} options={ref_?.entity_types || [f.entity_type]} disabled={dis} /><Select label="Tax residency" value={f.residency} onChange={set('residency')} options={['resident', 'foreign']} disabled={dis} />
        <Input label="ABN" value={f.abn} onChange={set('abn')} disabled={dis} /><Input label="Aggregated turnover" type="number" value={f.aggregated_turnover} onChange={set('aggregated_turnover')} disabled={dis} hint="Needed for small business concessions and the company rate" />
        <Input label="Passive income ratio (0–1, companies)" type="number" value={f.passive_income_ratio} onChange={set('passive_income_ratio')} disabled={dis} hint="Share of assessable income that is passive: interest, rent, royalties, most dividends, franking credits and net capital gains. Over 0.80 means the 30% company rate." /><Select label="State / territory" value={f.state} blank="—" onChange={set('state')} options={ref_?.states || []} disabled={dis} /></Grid></Section>
      <Section title="GST, BAS and PAYG"><Grid cols={3}>
        <Check label="Registered for GST" checked={f.gst_registered} onChange={set('gst_registered')} /><Select label="GST basis" value={f.gst_basis} onChange={set('gst_basis')} options={['accrual', 'cash']} disabled={dis} /><Select label="Reporting frequency" value={f.bas_frequency} onChange={set('bas_frequency')} options={ref_?.bas_frequencies || ['quarterly']} disabled={dis} />
        <Check label="Withholds PAYG from employees" checked={f.payg_withholding} onChange={set('payg_withholding')} /><Select label="PAYG instalments" value={f.payg_instalment_method} onChange={set('payg_instalment_method')} options={['none', 'amount', 'rate']} disabled={dis} />
        {f.payg_instalment_method === 'amount' && <Input label="Instalment amount notified by the ATO (T7)" type="number" value={f.payg_instalment_amount} onChange={set('payg_instalment_amount')} disabled={dis} />}
        {f.payg_instalment_method === 'rate' && <Input label="Instalment rate % notified by the ATO (T2)" type="number" value={f.payg_instalment_rate} onChange={set('payg_instalment_rate')} disabled={dis} />}</Grid></Section>
      <Section title="Other taxes and depreciation"><Grid cols={3}>
        <Check label="Registered for FBT" checked={f.fbt_registered} onChange={set('fbt_registered')} /><Input label="FBT instalment (from ATO)" type="number" value={f.fbt_instalment_amount} onChange={set('fbt_instalment_amount')} disabled={dis} /><Check label="Taxable payments annual report (TPAR) required" checked={f.tpar_required} onChange={set('tpar_required')} />
        <Check label="Uses simplified depreciation (small business pool)" checked={f.simplified_depreciation} onChange={set('simplified_depreciation')} /><Input label="Pool opening balance this year" type="number" value={f.pool_opening_balance} onChange={set('pool_opening_balance')} disabled={dis} /><Input label="ASIC review date (MM-DD)" value={f.asic_review_date} onChange={set('asic_review_date')} disabled={dis} /></Grid></Section>
      <Section title="Advisers, calendar and controls"><Grid cols={3}>
        <Check label="Uses a registered tax agent" checked={f.has_tax_agent} onChange={set('has_tax_agent')} /><Input label="Tax agent name" value={f.tax_agent_name} onChange={set('tax_agent_name')} disabled={dis} /><Input label="Tax agent number" value={f.tax_agent_number} onChange={set('tax_agent_number')} disabled={dis} />
        <Check label="Lodges through the agent lodgement program (later due dates)" checked={f.uses_agent_program} onChange={set('uses_agent_program')} /><Input label="Extra public holidays (YYYY-MM-DD, comma separated)" value={f.extra_holidays} onChange={set('extra_holidays')} disabled={dis} />
        <Select label="Lodgement policy" value={f.lodgement_policy} onChange={set('lodgement_policy')} disabled={dis} options={[{ value: 'self_declaration', label: 'The taxpayer or a registered agent may sign off' }, { value: 'agent_signoff_required', label: 'A registered tax / BAS agent must sign off' }]} hint="Applies before lodgement can be recorded or submitted. A registered agent signs off from the document screen (Accountant or Admin role)." />
        <Check label="Allow the same person to prepare and approve (one-person business; every use is audited)" checked={f.allow_self_approval} onChange={set('allow_self_approval')} /></Grid></Section>
      {can && <button className="btn btn-primary" onClick={save}>Save profile</button>}
    </div>)
}

function Rates({ me, fy }) {
  const q = useLoad(() => api.rules(fy), [fy])
  const [edit, setEdit] = useState(null)
  const can = me.capabilities.includes('config')
  return (
    <Async q={q}>{r => (
      <>
        <Disclaimer />
        {r.rule_set.provisional && <div role="alert" className="alert alert-error" style={{ marginBottom: 8 }}><strong>Provisional rule set.</strong> The {r.rule_set.id} figures were carried forward before the ATO published them (only the second tax bracket is legislated). Use for planning and early BAS preparation, and confirm every figure with your tax agent.</div>}
        <div className="text-sm" style={{ marginBottom: 8 }}>Rule set <strong>{r.rule_set.id}</strong>. Each group shows how well it was verified. Rates are data, not code: overriding a value needs a reason and is audited. Re-verify every 1 July and after each Budget.
          {' '}{Object.entries(r.verification_summary).map(([k, v]) => <span key={k} style={{ marginLeft: 6 }}><StatusBadge status={VER[k]?.[1] || 'upcoming'} text={`${v} ${VER[k]?.[0] || k}`} /></span>)}</div>
        <DataGrid rows={r.rows} rowKey="path" searchKeys={['path', 'source']} pageSize={30} columns={[{ key: 'path', label: 'Rule', render: x => <span className="mono text-sm">{x.path}</span> },
          { key: 'value', label: 'Value', render: x => (x.value === null ? <em className="text-muted">not loaded</em> : <span className="mono text-sm" style={{ whiteSpace: 'pre', display: 'inline-block' }}>{showValue(x.value)}</span>) },
          { key: 'verification', label: 'Verification', render: x => <StatusBadge status={VER[x.verification]?.[1] || 'upcoming'} text={VER[x.verification]?.[0] || x.verification} /> }, { key: 'overridden', label: '', render: x => (x.overridden ? <StatusBadge status="due_soon" text="Overridden" /> : '') },
          { key: 'source', label: 'Source', render: x => <details style={{ minWidth: 260 }}><summary className="text-xs" style={{ cursor: 'pointer' }}>{(x.source || '').slice(0, 70)}{(x.source || '').length > 70 ? '…' : ''}</summary><div className="text-xs text-muted" style={{ marginTop: 4 }}>{x.source}{x.checked_on ? ` (checked ${x.checked_on})` : ''}</div></details> }, { key: 'x', label: '', render: x => can && !Array.isArray(x.value) && <button className="btn btn-ghost btn-xs" onClick={() => setEdit(x)}>Override</button> }]} />
        {edit && <Override fy={fy} row={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); q.reload() }} />}
        {r.overrides.length > 0 && <Section title="Active overrides">{r.overrides.map(o => <div key={o.path} className="flex items-center justify-between text-sm"><span><span className="mono">{o.path}</span> = {JSON.stringify(o.value)} — {o.reason}</span>{can && <button className="btn btn-ghost btn-xs" onClick={async () => { if (await act(() => api.clearOverride(fy, o.path), 'Override removed')) q.reload() }}>Remove</button>}</div>)}</Section>}
      </>)}</Async>)
}

function Override({ fy, row, onClose, onSaved }) {
  const [f, set] = useForm({ value: row.value ?? '', reason: '' })
  return (
    <Modal title={`Override ${row.path}`} onClose={onClose} width={500}>
      <p className="text-sm">Current value: <span className="mono">{String(row.value)}</span>. Enter a rate as a decimal (0.0877 = 8.77%).</p>
      <Input label="New value" value={f.value} onChange={set('value')} /><Input label="Reason / source (ATO page or ruling)" value={f.reason} onChange={set('reason')} />
      <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={f.reason.trim().length < 5} onClick={async () => { if (await act(() => api.setOverride({ fy, path: row.path, value: f.value === '' ? null : f.value, reason: f.reason }), 'Override saved')) onSaved() }}>Save override</button></div>
    </Modal>)
}
