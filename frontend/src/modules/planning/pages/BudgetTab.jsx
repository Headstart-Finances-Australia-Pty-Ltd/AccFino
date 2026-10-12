import React, { useRef, useState } from 'react'
import * as api from '../lib/planningApi.js'
import { fmtAUD, fmtDate, label, fyStartISO, todayISO, saveBlob } from '../lib/format.js'
import { useLoad, Async, Stat, Section, Provenance, Flags, Disclaimer, Money, StatusBadge, Table, Select, Input, Grid, Modal, act, Basis, useForm, useConfirm } from '../components/kit.jsx'

const monthLabel = m => { const [y, mo] = m.split('-'); return new Date(Number(y), Number(mo) - 1, 1).toLocaleDateString('en-AU', { month: 'short', year: '2-digit' }) }

function Grid_({ b, canEdit, onSaved }) {
  const [edits, setEdits] = useState({})
  const [newAcc, setNewAcc] = useState('')
  const [extra, setExtra] = useState([])
  const rows = [...b.accounts, ...extra]
  const key = (code, mo) => `${code}|${mo}`
  const val = (r, mo) => (edits[key(r.code, mo)] ?? r.months[mo] ?? '0.00')
  const dirty = Object.keys(edits).length > 0
  const save = async () => {
    const lines = Object.entries(edits).map(([k, v]) => { const [account, month] = k.split('|'); return { account, month, amount: v === '' ? 0 : v } })
    if (await act(() => api.budgets.saveLines(b.id, lines), 'Budget saved')) { setEdits({}); setExtra([]); onSaved() }
  }
  const addAcc = () => { const c = newAcc.trim(); if (c && !rows.some(r => r.code === c)) setExtra(x => [...x, { code: c, name: '(new line)', months: {}, annual: '0.00' }]); setNewAcc('') }
  return (
    <>
      <div style={{ overflowX: 'auto' }}>
        <table className="data-table"><caption className="sr-only">Budget lines by account and month</caption>
          <thead><tr><th scope="col">Account</th>{b.months.map(m => <th scope="col" key={m} className="text-right">{monthLabel(m)}</th>)}<th scope="col" className="text-right">Year</th></tr></thead>
          <tbody>{rows.map(r => {
            const tot = b.months.reduce((s, m) => s + (Number(val(r, m)) || 0), 0)
            return (<tr key={r.code}><td style={{ whiteSpace: 'nowrap' }}>{r.code} {r.name}</td>
              {b.months.map(m => <td key={m} className="text-right">{canEdit
                ? <input className="input input-sm mono" style={{ width: 84, textAlign: 'right' }} aria-label={`${r.code} ${m}`} inputMode="decimal" value={val(r, m)} onChange={e => setEdits(s => ({ ...s, [key(r.code, m)]: e.target.value }))} />
                : <Money v={val(r, m)} />}</td>)}
              <td className="text-right"><Money v={tot} strong /></td></tr>)
          })}</tbody></table>
      </div>
      {canEdit && (
        <div className="flex items-center gap-1" style={{ marginTop: 10, flexWrap: 'wrap' }}>
          <Input label="Add account code" value={newAcc} onChange={e => setNewAcc(e.target.value)} placeholder="e.g. 469" />
          <button className="btn btn-outline btn-sm" onClick={addAcc}>Add line</button>
          <button className="btn btn-primary btn-sm" disabled={!dirty} onClick={save}>Save changes</button>
          {dirty && <span className="text-xs text-muted">{Object.keys(edits).length} unsaved change(s)</span>}
        </div>)}
      {!canEdit && <Disclaimer>Only a draft budget can be edited. Copy it to start a new version.</Disclaimer>}
    </>)
}

function ImportBox({ b, onDone }) {
  const [csv, setCsv] = useState('account_code,month,amount\n')
  const [res, setRes] = useState(null)
  const file = useRef()
  const run = async apply => { const r = await act(() => api.budgets.importCsv(b.id, csv, apply, true)); if (r) { setRes(r); if (apply && r.applied) onDone() } }
  const load = e => { const f = e.target.files?.[0]; if (!f) return; const rd = new FileReader(); rd.onload = () => setCsv(String(rd.result)); rd.readAsText(f) }
  return (
    <>
      <p className="text-sm text-muted" style={{ marginTop: 0 }}>Columns: <code>account_code, month (YYYY-MM), amount</code>. Check first: nothing is changed until you choose Apply. A strict import is all-or-nothing.</p>
      <input ref={file} type="file" accept=".csv,text/csv" aria-label="Choose CSV file" onChange={load} />
      <textarea className="input mono" aria-label="Budget CSV" rows={6} style={{ width: '100%', marginTop: 8 }} value={csv} onChange={e => setCsv(e.target.value)} />
      <div className="flex gap-1" style={{ marginTop: 8 }}><button className="btn btn-outline btn-sm" onClick={() => run(false)}>Check only</button><button className="btn btn-primary btn-sm" onClick={() => run(true)}>Apply</button></div>
      {res && (
        <div role="status" style={{ marginTop: 10 }}>
          <div className="text-sm">{res.dry_run ? 'Check complete' : res.applied ? 'Applied' : 'Not applied'}: {res.valid_rows} valid row(s), {res.rejected.length} rejected.</div>
          {res.rejected.length > 0 && <Table caption="Rejected rows" columns={[{ key: 'row', label: 'Row', align: 'right' }, { key: 'error', label: 'Problem' }]} rows={res.rejected} rowKey="row" />}
        </div>)}
    </>)
}

function VsActual({ b }) {
  const [p, setP] = useState({ from: b.fy_start, to: todayISO() })
  const [drill, setDrill] = useState(null)
  const q = useLoad(() => api.budgets.vsActual(b.id, p.from, p.to), [b.id, p.from, p.to])
  const open = async r => { const d = await act(() => api.drilldown(r.account_id, p.from, p.to)); if (d) setDrill({ row: r, d }) }
  return (
    <>
      <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginBottom: 10 }} role="group" aria-label="Budget period">
        <label className="text-sm">From <input className="input input-sm" type="date" aria-label="From date" value={p.from} onChange={e => setP({ ...p, from: e.target.value })} /></label>
        <label className="text-sm">To <input className="input input-sm" type="date" aria-label="To date" value={p.to} onChange={e => setP({ ...p, to: e.target.value })} /></label>
      </div>
      <Async q={q}>{v => (
        <>
          <Provenance d={v} />
          {v.approval_note && <Flags items={[v.approval_note]} />}
          <Grid cols={3}>
            {['revenue', 'expenses', 'profit'].map(k => (
              <Stat key={k} label={label(k)} basis="BUDGET" value={fmtAUD(v.totals[k].actual)} tone={Number(v.totals[k].variance) < 0 ? 'danger' : undefined}
                sub={`Budget ${fmtAUD(v.totals[k].budget)} · variance ${fmtAUD(v.totals[k].variance)}${v.totals[k].variance_pct != null ? ` (${v.totals[k].variance_pct}%)` : ' (n/a: zero budget)'}`} />))}
          </Grid>
          <Disclaimer>{v.convention} Actuals are from the ledger; budget lines are the plan you approved.</Disclaimer>
          <Table caption="Budget vs actual by account" onRowClick={open} rows={v.rows} rowKey="account_id" empty="No budget or actual amounts in this period" columns={[
            { key: 'code', label: 'Account', render: r => `${r.code} ${r.name}` }, { key: 'account_class', label: 'Type', render: r => label(r.account_class) },
            { key: 'budget', label: 'Budget', money: true }, { key: 'actual', label: 'Actual', money: true }, { key: 'variance', label: 'Variance', money: true },
            { key: 'variance_pct', label: '%', align: 'right', render: r => (r.variance_pct == null ? 'n/a' : `${r.variance_pct}%`) },
            { key: 'flags', label: 'Notes', render: r => (r.flags || []).map(f => label(typeof f === 'string' ? f : f.code)).join(', ') || (r.favourable ? <StatusBadge status="active" text="Favourable" /> : <StatusBadge status="medium" text="Adverse" />) }]} />
          <Disclaimer>Select a row to see the ledger lines behind the number.</Disclaimer>
          <Section title="Year-end projection" hint={v.year_end.note}>
            <Disclaimer>Closed months to {v.year_end.last_closed_month || 'n/a'}. {v.year_end.basis_note}</Disclaimer>
            <Table caption="Year-end projection" rows={v.year_end.rows} rowKey="account_id" empty="Nothing to project" columns={[
              { key: 'code', label: 'Account', render: r => `${r.code} ${r.name}` }, { key: 'annual_budget', label: 'Annual budget', money: true }, { key: 'actual_ytd', label: 'Actual to date', money: true },
              { key: 'remaining_budget', label: 'Budget remaining', money: true }, { key: 'projection_budget_basis', label: 'Projection (budget basis)', money: true },
              { key: 'projection_run_rate', label: 'Projection (run-rate)', money: true }, { key: 'projected_variance', label: 'Projected variance', money: true }]} />
          </Section>
          {drill && (
            <Modal title={`${drill.row.code} ${drill.row.name}: ledger lines`} onClose={() => setDrill(null)} width={900}>
              <Disclaimer>{drill.d.count} line(s), {fmtDate(drill.d.period_from)} to {fmtDate(drill.d.period_to)}. Source: {drill.d.source}.</Disclaimer>
              <Table caption="Ledger lines" rows={drill.d.lines} rowKey="journal_id" empty="No ledger lines" columns={[{ key: 'date', label: 'Date', date: true }, { key: 'journal_no', label: 'Journal' }, { key: 'narration', label: 'Narration' },
                { key: 'contact', label: 'Contact' }, { key: 'debit', label: 'Debit', money: true }, { key: 'credit', label: 'Credit', money: true }]} />
            </Modal>)}
        </>)}</Async>
    </>)
}

export default function BudgetTab() {
  const list = useLoad(() => api.budgets.list(true), [])
  const me = useLoad(() => api.me(), [])
  const [sel, setSel] = useState(null)
  const [view, setView] = useState('lines')
  const [creating, setCreating] = useState(false)
  const [f, set] = useForm({ name: '', fy_start: fyStartISO(), interval: 'monthly' })
  const detail = useLoad(() => (sel ? api.budgets.get(sel) : Promise.resolve(null)), [sel])
  const confirm = useConfirm()
  const caps = me.data?.capabilities || []
  const canEdit = caps.includes('edit'), canApprove = caps.includes('approve')
  const refresh = () => { list.reload(); detail.reload() }

  const create = async () => { const r = await act(() => api.budgets.create(f), 'Budget created'); if (r) { setCreating(false); list.reload(); setSel(r.id); setView('lines') } }
  const doit = (fn, ok, ask) => async () => { if (ask && !confirm(ask)) return; if (await act(fn, ok)) refresh() }
  const b = detail.data
  const bs = list.data?.find(x => x.id === sel)

  return (
    <div style={{ padding: 16 }}>
      <Async q={list}>{rows => (
        <>
          <Section title="Budgets" actions={canEdit && <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>New budget</button>}
            hint="Budgets are plans, kept apart from ledger actuals. Only an approved budget feeds reports and alerts.">
            <Table caption="Budgets" rows={rows} onRowClick={r => { setSel(r.id); setView('lines') }} empty="No budgets yet" hint="Create one, or import a CSV." columns={[
              { key: 'name', label: 'Name' }, { key: 'fy_start', label: 'Year starts', date: true }, { key: 'version', label: 'Version', align: 'right' }, { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
              { key: 'owner', label: 'Owner' }, { key: 'lines', label: 'Lines', align: 'right' }]} />
          </Section>
          {sel && bs && (
            <Section title={`${bs.name} · v${bs.version}`} hint={`${label(bs.status)} · owner ${bs.owner || 'n/a'}`} actions={
              <>
                {canEdit && bs.status === 'draft' && <button className="btn btn-primary btn-sm" onClick={doit(() => api.budgets.submit(sel), 'Submitted for approval')}>Submit for approval</button>}
                {canApprove && bs.status === 'submitted' && <button className="btn btn-primary btn-sm" onClick={doit(() => api.budgets.approve(sel), 'Budget approved')}>Approve</button>}
                {canApprove && bs.status === 'submitted' && <button className="btn btn-outline btn-sm" onClick={async () => { const n = window.prompt('Reason for rejecting this budget'); if (n && await act(() => api.budgets.reject(sel, n), 'Returned to draft')) refresh() }}>Reject</button>}
                {canEdit && <button className="btn btn-outline btn-sm" onClick={async () => { const n = window.prompt('Name for the copy (a new draft version)', `${bs.name} v${bs.version + 1}`); if (n && await act(() => api.budgets.copy(sel, n), 'Copied as a new draft')) refresh() }}>Copy</button>}
                <button className="btn btn-outline btn-sm" onClick={async () => { const d = await act(() => api.budgets.exportCsv(sel)); if (d) saveBlob(`budget_${bs.name}.csv`, d) }}>Export CSV</button>
                {canEdit && bs.status !== 'archived' && <button className="btn btn-outline btn-sm" onClick={doit(() => api.budgets.archive(sel), 'Archived', 'Archive this budget? It will stop feeding reports.')}>Archive</button>}
                {canEdit && bs.status === 'draft' && <button className="btn btn-outline btn-sm" onClick={doit(async () => { await api.budgets.remove(sel); setSel(null) }, 'Draft deleted', 'Delete this draft and its lines?')}>Delete draft</button>}
              </>}>
              <div className="tabs-bar" style={{ marginBottom: 10 }} role="tablist">
                {[['lines', 'Budget lines'], ['vs', 'Budget vs actual'], ['import', 'Import']].map(([k, l]) => <button key={k} role="tab" aria-selected={view === k} className={`tab-btn${view === k ? ' active' : ''}`} onClick={() => setView(k)}>{l}</button>)}
              </div>
              <Async q={detail}>{d => d && (
                <>
                  {view === 'lines' && <><Provenance d={d} /><Grid_ b={d} canEdit={canEdit && d.status === 'draft'} onSaved={refresh} /></>}
                  {view === 'vs' && <VsActual b={d} />}
                  {view === 'import' && (canEdit && d.status === 'draft' ? <ImportBox b={d} onDone={refresh} /> : <Disclaimer>Import is available for draft budgets only.</Disclaimer>)}
                </>)}</Async>
            </Section>)}
          {creating && (
            <Modal title="New budget" onClose={() => setCreating(false)}>
              <Input label="Name" value={f.name} onChange={set('name')} maxLength={40} />
              <Input label="Budget year starts" type="date" value={f.fy_start} onChange={set('fy_start')} hint="Must be the first day of a month" />
              <Select label="Entry interval" value={f.interval} onChange={set('interval')} options={['monthly', 'quarterly', 'annual']} />
              <div className="flex gap-1" style={{ justifyContent: 'flex-end' }}><button className="btn btn-outline" onClick={() => setCreating(false)}>Cancel</button><button className="btn btn-primary" onClick={create} disabled={!f.name.trim()}>Create</button></div>
            </Modal>)}
        </>)}</Async>
    </div>)
}
