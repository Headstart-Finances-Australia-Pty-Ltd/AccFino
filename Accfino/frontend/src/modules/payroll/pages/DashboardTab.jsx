import React from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import * as api from '../lib/payrollApi.js'
import { Async, Money, Section, Stat, StatusBadge, useLoad, EmptyState } from '../components/kit.jsx'
import { fmtAUD, fmtDate, label, num } from '../lib/format.js'

const TONE = { danger: 'badge-danger', warning: 'badge-warning', info: 'badge-info' }

export default function DashboardTab({ onNav }) {
  const q = useLoad(() => api.dashboard(), [])
  return (
    <Async q={q}>{d => {
      const nx = d.next_pay_run
      const p = d.pending
      return (
        <div>
          <div className="stats-grid" style={{ marginBottom: 14 }}>
            <Stat label="Employees on payroll" value={d.employees.active} sub={Object.entries(d.employees.by_type).map(([k, v]) => `${v} ${label(k).toLowerCase()}`).join(' · ') || 'none yet'} onClick={() => onNav('employees')} />
            <Stat label={`Gross payroll (FY ${d.financial_year})`} value={fmtAUD(d.ytd.gross)} sub="Finalised pays this financial year" />
            <Stat label="PAYG withheld" value={fmtAUD(d.ytd.payg)} sub="Including study loan amounts" />
            <Stat label="Superannuation" value={fmtAUD(d.ytd.super)} sub={`Net pay ${fmtAUD(d.ytd.net)}`} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 14 }}>
            <Section title="Current payroll status" actions={<button className="btn btn-primary btn-sm" onClick={() => onNav('runs')}>Open pay runs</button>}>
              {nx ? (
                <div>
                  <div className="text-sm">Next pay run · {nx.calendar}</div>
                  <div style={{ fontSize: '1.15rem', fontWeight: 700 }}>{fmtDate(nx.period_start)} – {fmtDate(nx.period_end)}</div>
                  <div className="text-sm text-muted">Pay date {fmtDate(nx.pay_date)} · <StatusBadge status={nx.run_status} /></div>
                  {d.periods.filter(x => x.previous_period.overdue).map(x => (
                    <div key={x.calendar_id} className="alert alert-warning" style={{ marginTop: 8 }}>
                      Period ending {fmtDate(x.previous_period.period_end)} ({x.calendar}) has no finalised pay run.</div>))}
                </div>) : <EmptyState icon="🗓" title="No pay calendar yet" hint="Create one in Settings to start your first pay run" />}
              <div className="divider" />
              <div className="text-sm"><b>Last completed pay run</b></div>
              {d.last_run ? <div className="text-sm">{d.last_run.run_no} · pay date {fmtDate(d.last_run.pay_date)} · {d.last_run.employee_count} employees · gross <Money v={d.last_run.total_gross} /> · net <Money v={d.last_run.total_net} /></div>
                : <div className="text-sm text-muted">None yet</div>}
            </Section>

            <Section title="Pending payroll actions">
              {[['Timesheets to approve', p.timesheets_to_approve, 'timesheets'], ['Leave requests to approve', p.leave_to_approve, 'leave'], ['Pay runs in progress', p.runs_in_progress, 'runs'],
                ['Finalised runs awaiting payment', p.runs_awaiting_payment, 'payments'], ['Super contributions overdue', p.super_overdue, 'super'], ['Super contributions unpaid', p.super_unpaid, 'super']].map(([t, n, tab]) => (
                <div key={t} className="flex items-center justify-between" style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => onNav(tab)}>
                  <span className="text-sm">{t}</span><span className={`badge ${n ? (t.includes('overdue') ? 'badge-danger' : 'badge-warning') : 'badge-neutral'}`}>{n}</span></div>))}
            </Section>

            <Section title="Alerts and compliance reminders">
              {d.alerts.length === 0 && <div className="text-sm text-muted">No alerts</div>}
              {d.alerts.map((a, i) => <div key={i} className={`alert alert-${a.level === 'danger' ? 'error' : a.level === 'info' ? 'success' : 'warning'}`} style={{ marginBottom: 6 }}>{a.message}</div>)}
              <div className="divider" />
              {d.reminders.map((r, i) => <div key={i} className="text-sm" style={{ padding: '3px 0' }}>{r.date ? <b>{fmtDate(r.date)} ({r.days}d) </b> : null}{r.message}</div>)}
            </Section>

            <Section title={`Employees requiring attention (${d.employees.requiring_attention})`}>
              {d.employees.attention.length === 0 && <div className="text-sm text-muted">Everyone is set up</div>}
              {d.employees.attention.map(e => (
                <div key={e.employee_id} style={{ padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
                  <div className="text-sm"><b>{e.employee_number}</b> {e.name}</div>
                  {e.issues.map(i => <div key={i.code} className="text-xs" style={{ color: i.severity === 'error' ? 'var(--danger)' : 'var(--warning)' }}>{i.severity === 'error' ? '✖' : '▲'} {i.message}</div>)}
                </div>))}
            </Section>
          </div>

          <Section title="Payroll trend (last 12 pay runs)">
            {d.trend.length < 1 ? <div className="text-sm text-muted">Trends appear after your first finalised pay run.</div> : (
              <div style={{ width: '100%', height: 260 }}>
                <ResponsiveContainer>
                  <LineChart data={d.trend.map(t => ({ ...t, gross: num(t.gross), payg: num(t.payg), super: num(t.super), net: num(t.net) }))}>
                    <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="pay_date" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} tickFormatter={v => `$${Math.round(v / 1000)}k`} />
                    <Tooltip formatter={v => fmtAUD(v)} /><Legend />
                    <Line type="monotone" dataKey="gross" name="Gross" stroke="#0f766e" strokeWidth={2} /><Line type="monotone" dataKey="net" name="Net" stroke="#2563eb" strokeWidth={2} />
                    <Line type="monotone" dataKey="payg" name="PAYG" stroke="#d97706" /><Line type="monotone" dataKey="super" name="Super" stroke="#7c3aed" />
                  </LineChart>
                </ResponsiveContainer>
              </div>)}
          </Section>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 14 }}>
            <Section title="Upcoming pay dates">
              {d.upcoming_pay_dates.length === 0 && <div className="text-sm text-muted">None</div>}
              {d.upcoming_pay_dates.map((u, i) => <div key={i} className="flex justify-between text-sm" style={{ padding: '4px 0' }}><span>{fmtDate(u.pay_date)} · {u.calendar}</span><span className="text-muted">{u.days === 0 ? 'today' : `in ${u.days} days`}</span></div>)}
            </Section>
            <Section title="Recent pay runs">
              {d.recent_runs.length === 0 && <div className="text-sm text-muted">None yet</div>}
              {d.recent_runs.map(r => <div key={r.id} className="flex justify-between text-sm" style={{ padding: '4px 0' }}><span>{r.run_no} · {fmtDate(r.pay_date)}</span><span><StatusBadge status={r.status} /> <Money v={r.total_net} /></span></div>)}
            </Section>
          </div>
        </div>)
    }}</Async>
  )
}
