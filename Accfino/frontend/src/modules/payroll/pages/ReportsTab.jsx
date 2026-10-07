import React, { useEffect, useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { act, Async, Field, Grid, Input, Loading, Select, useLoad } from '../components/kit.jsx'
import ReportTable from '../components/ReportTable.jsx'
import { download, fyLabel, todayISO } from '../lib/format.js'

export default function ReportsTab() {
  const cat = useLoad(() => api.reportCatalogue(), [])
  const refs = useLoad(async () => { const [d, e, r] = await Promise.all([api.departments.list().catch(() => []), api.employees({ limit: 200 }).catch(() => ({ items: [] })), api.runs().catch(() => [])]); return { d, e: e.items, r } }, [])
  const [key, setKey] = useState('payroll_summary')
  const [f, setF] = useState({ date_from: `${fyLabel().slice(0, 4)}-07-01`, date_to: todayISO(), employee_id: '', department_id: '', run_id: '' })
  const [rep, setRep] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const params = () => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ''))
  const run = async () => {
    setBusy(true); setErr('')
    try { setRep(await api.report(key, params())) } catch (e) { setErr(api.errMsg(e)); setRep(null) }
    setBusy(false)
  }
  useEffect(() => { run() }, [key]) // eslint-disable-line
  const set = k => e => setF(s => ({ ...s, [k]: e.target.value }))
  const exportCsv = async () => { const t = await act(() => api.reportCsv(key, params())); if (t) download(`payroll-${key}.csv`, t, 'text/csv') }
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Payroll reports</h3>
      <Async q={cat}>{list => (
        <>
          <Grid cols={4}>
            <Select label="Report" value={key} onChange={e => setKey(e.target.value)} options={list.map(r => ({ value: r.key, label: r.title }))} />
            <Input label="From" type="date" value={f.date_from} onChange={set('date_from')} /><Input label="To" type="date" value={f.date_to} onChange={set('date_to')} />
            <Select label="Employee" value={f.employee_id} onChange={set('employee_id')} blank="All" options={(refs.data?.e || []).map(e => ({ value: e.id, label: `${e.employee_number} ${e.name}` }))} />
            <Select label="Department" value={f.department_id} onChange={set('department_id')} blank="All" options={(refs.data?.d || []).map(d => ({ value: d.id, label: d.name }))} />
            <Select label="Pay run" value={f.run_id} onChange={set('run_id')} blank="All" options={(refs.data?.r || []).map(r => ({ value: r.id, label: `${r.run_no} (${r.pay_date})` }))} />
            <Field label=""><div className="flex gap-1"><button className="btn btn-primary" onClick={run} disabled={busy}>{busy ? 'Running…' : 'Run report'}</button>
              <button className="btn btn-outline" onClick={exportCsv} disabled={!rep}>Export CSV</button><button className="btn btn-outline" onClick={() => window.print()} disabled={!rep}>Print</button></div></Field>
          </Grid>
          {err && <div role="alert" className="alert alert-error">{err}</div>}
          {busy && !rep ? <Loading /> : rep && <div><h4>{rep.title}</h4><ReportTable rep={rep} /></div>}
        </>)}</Async>
    </div>
  )
}
