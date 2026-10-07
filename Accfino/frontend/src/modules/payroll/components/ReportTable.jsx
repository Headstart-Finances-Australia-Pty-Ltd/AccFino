import React from 'react'
import { DataGrid, Money } from './kit.jsx'
import { fmtHours } from '../lib/format.js'

export default function ReportTable({ rep }) {
  const cols = rep.columns.map(c => ({ key: c.key, label: c.label, money: c.type === 'money', hours: c.type === 'hours', align: c.type === 'int' ? 'right' : undefined }))
  const cell = (c, v) => (c.type === 'money' ? <Money v={v} strong /> : c.type === 'hours' ? fmtHours(v) : v)
  return (
    <div>
      {rep.note && <p className="text-sm text-muted">{rep.note}</p>}
      <DataGrid rows={rep.rows.map((r, i) => ({ ...r, __i: i }))} rowKey="__i" columns={cols} pageSize={50} searchKeys={rep.columns.filter(c => c.type === 'text' || !c.type).map(c => c.key)} empty="No data for these filters"
        footer={Object.keys(rep.totals || {}).length ? <tr>{rep.columns.map((c, i) => <td key={c.key} className={c.type === 'money' || c.type === 'hours' ? 'text-right' : ''}><b>{i === 0 ? 'Total' : rep.totals[c.key] !== undefined ? cell(c, rep.totals[c.key]) : ''}</b></td>)}</tr> : null} />
      {(rep.control || []).length > 0 && (
        <div style={{ marginTop: 12 }}>
          {rep.control.map((c, i) => (
            <div key={i} className={`alert ${c.reconciled ? 'alert-success' : 'alert-error'}`} style={{ marginBottom: 6 }}>
              {c.reconciled ? '✓ Reconciled' : '✖ DOES NOT RECONCILE'}: {c.label} — report <Money v={c.report} /> vs {c.source_name} <Money v={c.source} />{!c.reconciled && <> (difference <Money v={c.difference} />)</>}</div>))}
        </div>)}
    </div>
  )
}
