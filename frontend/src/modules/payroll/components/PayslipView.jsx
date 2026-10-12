import React from 'react'
import { Modal, Money } from './kit.jsx'
import * as api from '../lib/payrollApi.js'
import { download, fmtDate, fmtHours, label } from '../lib/format.js'
import { act } from './kit.jsx'

const Row = ({ a, b, strong }) => <tr><td style={{ fontWeight: strong ? 700 : 400 }}>{a}</td><td className="text-right"><Money v={b} strong={strong} /></td></tr>

export function PayslipBody({ s }) {
  const t = s.totals
  const ytd = s.ytd
  return (
    <div id="payslip-print" style={{ maxWidth: 760 }}>
      <div className="flex justify-between" style={{ flexWrap: 'wrap' }}>
        <div><div style={{ fontSize: '1.25rem', fontWeight: 700 }}>Payslip</div><div className="text-sm text-muted">{s.employer.name}{s.employer.abn ? ` · ABN ${s.employer.abn}` : ''}</div></div>
        <div className="text-sm text-right">Payslip {s.payslip_no}<br />Pay date {fmtDate(s.pay_date)}</div>
      </div>
      <div className="text-sm" style={{ margin: '8px 0 12px' }}><b>{s.employee.name}</b> · {s.employee.number}{s.employee.position ? ` · ${s.employee.position}` : ''}<br />Pay period {fmtDate(s.period_start)} to {fmtDate(s.period_end)} ({label(s.frequency)}) · {label(s.employee.employment_type)}</div>
      <h5>Earnings</h5>
      <table className="summary-table"><tbody>
        {s.earnings.map((e, i) => <tr key={i}><td>{e.name}{e.hours ? <span className="text-muted"> · {fmtHours(e.hours)} h</span> : ''}</td><td className="text-right"><Money v={e.amount} /></td></tr>)}
        <Row a="Gross earnings" b={t.gross} strong /></tbody></table>
      <h5>Tax and deductions</h5>
      <table className="summary-table"><tbody>
        <Row a="PAYG withholding" b={t.payg} />{Number(t.study_loan) > 0 && <Row a="Study and training loan" b={t.study_loan} />}
        {s.deductions.map((d, i) => <Row key={i} a={d.name} b={d.amount} />)}</tbody></table>
      {s.reimbursements.length > 0 && <><h5>Reimbursements</h5><table className="summary-table"><tbody>{s.reimbursements.map((d, i) => <Row key={i} a={d.name} b={d.amount} />)}</tbody></table></>}
      <h5>Net pay</h5>
      <table className="summary-table"><tbody><Row a="Net pay" b={t.net} strong />
        {s.payment.map((p, i) => <tr key={i}><td className="text-sm text-muted">Paid to {p.account_name} · BSB {p.bsb} · {p.account}</td><td className="text-right"><Money v={p.amount} /></td></tr>)}</tbody></table>
      <h5>Superannuation (paid by your employer)</h5>
      <table className="summary-table"><tbody>{s.super.length === 0 ? <tr><td className="text-muted">None this pay</td><td /></tr> : s.super.map((x, i) => <tr key={i}><td>{x.fund} · {label(x.component)}{x.member_number ? ` · member ${x.member_number}` : ''}</td><td className="text-right"><Money v={x.amount} /></td></tr>)}</tbody></table>
      {ytd && <><h5>Year to date</h5><table className="summary-table"><tbody><Row a="Gross" b={ytd.gross} /><Row a="Tax withheld" b={ytd.tax} /><Row a="Superannuation" b={ytd.super_total} /></tbody></table></>}
      {s.leave.length > 0 && <><h5>Leave</h5><table className="summary-table"><thead><tr><th>Type</th><th className="text-right">Accrued</th><th className="text-right">Taken</th><th className="text-right">Balance (h)</th></tr></thead>
        <tbody>{s.leave.map((l, i) => <tr key={i}><td>{l.name}</td><td className="text-right">{fmtHours(l.accrued)}</td><td className="text-right">{fmtHours(l.taken)}</td><td className="text-right">{fmtHours(l.balance)}</td></tr>)}</tbody></table></>}
      {s.footer && <p className="text-xs text-muted" style={{ marginTop: 14 }}>{s.footer}</p>}
    </div>
  )
}

export default function PayslipView({ id, snapshot, onClose }) {
  const [s, setS] = React.useState(snapshot || null)
  const [err, setErr] = React.useState('')
  React.useEffect(() => { if (!snapshot) api.payslip(id).then(r => setS(r.snapshot)).catch(e => setErr(api.errMsg(e))) }, [id, snapshot])
  const html = async () => { const t = await act(() => api.payslipHtml(id)); return t }
  return (
    <Modal title="Payslip" onClose={onClose} width={820}>
      {err ? <div className="alert alert-error">{err}</div> : !s ? <div className="text-muted">Loading…</div> : (
        <>
          <div className="flex gap-1" style={{ marginBottom: 10 }}>
            <button className="btn btn-primary btn-sm" onClick={async () => { const t = await html(); if (!t) return; const w = window.open('', '_blank'); if (w) { w.document.write(t); w.document.close(); w.focus(); w.print() } }}>Print / save as PDF</button>
            <button className="btn btn-outline btn-sm" onClick={async () => { const t = await html(); if (t) download(`payslip-${s.payslip_no}.html`, t, 'text/html') }}>Download</button>
          </div>
          <PayslipBody s={s} />
        </>)}
    </Modal>
  )
}
