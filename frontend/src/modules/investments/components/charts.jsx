import React from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmtAUD, fmtPct } from '../lib/format.js'

export const PALETTE = ['#2E5597', '#2F9E7B', '#E39A2D', '#B04A8B', '#4F8FCB', '#C65D4A', '#7A6FD0', '#6B7F3A', '#8C8C8C']
const short = v => (Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}m` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : `${v}`)

// A donut of [{name, value, weight}] with a legend table underneath (the table is the accessible version of the chart).
export function Donut({ data, title, height = 190 }) {
  const rows = (data || []).filter(d => Number(d.value) > 0)
  if (!rows.length) return <div className="text-sm text-muted" style={{ padding: 12 }}>Nothing to chart yet.</div>
  return (
    <div role="group" aria-label={title}>
      <ResponsiveContainer width="100%" height={height}>
        <PieChart><Pie data={rows.map(r => ({ ...r, v: Number(r.value) }))} dataKey="v" nameKey="name" innerRadius={48} outerRadius={78} paddingAngle={1}>{rows.map((r, i) => <Cell key={r.name} fill={PALETTE[i % PALETTE.length]} />)}</Pie>
          <Tooltip formatter={(v, n) => [fmtAUD(v), n]} /></PieChart>
      </ResponsiveContainer>
      <table className="data-table" style={{ fontSize: 12 }}><tbody>{rows.map((r, i) => <tr key={r.name}><td><span style={{ display: 'inline-block', width: 10, height: 10, background: PALETTE[i % PALETTE.length], marginRight: 6, borderRadius: 2 }} />{String(r.name).replace(/_/g, ' ')}</td>
        <td className="text-right mono">{fmtAUD(r.value)}</td><td className="text-right mono">{fmtPct(r.weight, 1)}</td></tr>)}</tbody></table>
    </div>)
}

export function HistoryChart({ points, series, height = 240, stacked }) {
  if (!points || points.length < 2) return <div className="text-sm text-muted" style={{ padding: 12 }}>History needs at least two month-ends with data.</div>
  const data = points.map(p => ({ ...p, ...Object.fromEntries(series.map(s => [s.key, Number(p[s.key])])) }))
  const Chart = stacked ? AreaChart : LineChart
  return (
    <>
    <ResponsiveContainer width="100%" height={height}>
      <Chart data={data} margin={{ left: 4, right: 12, top: 8 }}><CartesianGrid strokeDasharray="3 3" stroke="var(--border)" /><XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={d => String(d).slice(0, 7)} /><YAxis tick={{ fontSize: 11 }} tickFormatter={short} width={48} />
        <Tooltip formatter={v => fmtAUD(v)} /><Legend />
        {series.map((s, i) => (stacked ? <Area key={s.key} type="monotone" dataKey={s.key} name={s.name} stackId="1" stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.5} /> : <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={PALETTE[i % PALETTE.length]} dot={false} strokeWidth={2} />))}</Chart>
    </ResponsiveContainer>
      <details style={{ marginTop: 6 }}><summary className="text-xs text-muted" style={{ cursor: 'pointer' }}>Show the figures</summary>
        <div style={{ maxHeight: 220, overflow: 'auto' }}><table className="data-table" style={{ fontSize: 12 }}><thead><tr><th>Month end</th>{series.map(s => <th key={s.key} className="text-right">{s.name}</th>)}</tr></thead>
          <tbody>{data.map(p => <tr key={p.date}><td>{String(p.date).slice(0, 10)}</td>{series.map(s => <td key={s.key} className="text-right mono">{fmtAUD(p[s.key])}</td>)}</tr>)}</tbody></table></div></details>
    </>)
}

export function Bars({ data, nameKey = 'name', valueKey = 'value', height = 220, color = PALETTE[0] }) {
  if (!data || !data.length) return <div className="text-sm text-muted" style={{ padding: 12 }}>Nothing to chart yet.</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data.map(d => ({ ...d, [valueKey]: Number(d[valueKey]) }))} margin={{ left: 4, right: 12, top: 8 }}><CartesianGrid strokeDasharray="3 3" stroke="var(--border)" /><XAxis dataKey={nameKey} tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} tickFormatter={short} width={48} />
        <Tooltip formatter={v => fmtAUD(v)} /><Bar dataKey={valueKey} fill={color} /></BarChart>
    </ResponsiveContainer>)
}
