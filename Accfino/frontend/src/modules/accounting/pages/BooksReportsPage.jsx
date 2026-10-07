import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { FileBarChart, Download } from 'lucide-react'
import * as api__0 from '../../../core/lib/platformHttp.js'
import * as api__1 from '../lib/booksApi.js'
import { fmtAUD, fmtDate, todayISO } from '../../../core/components/ui/Common.jsx'

const fyStart = () => { const d = new Date(); const y = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-07-01` }

const REPORTS = [
  { key: 'aged-receivables', label: 'Aged Receivables' },
  { key: 'aged-payables', label: 'Aged Payables' },
  { key: 'gst-summary', label: 'GST / BAS Summary' },
  { key: 'cash-flow', label: 'Cash Flow' },
  { key: 'by-customer', label: 'Sales by Customer' },
  { key: 'by-supplier', label: 'Purchases by Supplier' },
  { key: 'control', label: 'Sub-ledger Control Check' },
]

export default function BooksReportsPage() {
  const [key, setKey] = useState('aged-receivables')
  return (
    <div className="fade-in">
      <div style={{ marginBottom: 18 }}>
        <div className="flex items-center gap-1"><FileBarChart size={22} /><h2 style={{ margin: 0 }}>Financial Reports</h2></div>
        <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>
          Derived only from the ledger and its sales/purchase allocations. Trial Balance, Profit &amp; Loss and Balance Sheet are under Financial Statements.
        </p>
      </div>
      <div className="tabs-bar" style={{ marginBottom: 0, flexWrap: 'wrap' }}>
        {REPORTS.map(r => <button key={r.key} className={`tab-btn${key === r.key ? ' active' : ''}`} onClick={() => setKey(r.key)}>{r.label}</button>)}
      </div>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderTop: 'none', borderRadius: '0 0 var(--r-lg) var(--r-lg)', minHeight: 320, padding: 16, boxShadow: 'var(--sh-sm)' }}>
        {key === 'aged-receivables' && <AgedReport side="sales" />}
        {key === 'aged-payables' && <AgedReport side="purchases" />}
        {key === 'gst-summary' && <GstReport />}
        {key === 'cash-flow' && <CashFlowReport />}
        {key === 'by-customer' && <ByContactReport side="sales" />}
        {key === 'by-supplier' && <ByContactReport side="purchases" />}
        {key === 'control' && <ControlReport />}
      </div>
    </div>
  )
}

function downloadCSV(text, filename) {
  const blob = new Blob([text], { type: 'text/csv' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = filename; a.click()
}

function AgedReport({ side }) {
  const [asAt, setAsAt] = useState(todayISO())
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const report = side === 'sales' ? api__1.salesReport : api__1.purchasesReport
  const endpoint = side === 'sales' ? 'aged-receivables' : 'aged-payables'

  const run = () => { setLoading(true); report(endpoint, { as_at: asAt }).then(r => setData(r.data)).catch(e => toast.error(api__0.errMsg(e))).finally(() => setLoading(false)) }
  useEffect(() => { run() }, [])

  const exportCSV = async () => {
    try { const r = await report(endpoint, { as_at: asAt, format: 'csv' }); downloadCSV(r.data, `${endpoint}-${asAt}.csv`) } catch (e) { toast.error(api__0.errMsg(e)) }
  }

  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <label className="text-sm">As at <input type="date" className="input input-sm" value={asAt} onChange={e => setAsAt(e.target.value)} /></label>
        <button className="btn btn-primary btn-sm" onClick={run} disabled={loading}>Run</button>
        <button className="btn btn-outline btn-sm" onClick={exportCSV}><Download size={13} /> CSV</button>
        {data && <span className={`badge ${data.control.reconciled ? 'badge-success' : 'badge-warning'}`}>{data.control.reconciled ? 'Reconciles to the ledger' : `Off by ${fmtAUD(data.control.difference)}`}</span>}
      </div>
      {data && (
        <>
          <table className="data-table">
            <thead><tr><th>{side === 'sales' ? 'Customer' : 'Supplier'}</th><th>Current</th><th>1–30</th><th>31–60</th><th>61–90</th><th>90+</th><th>Total</th></tr></thead>
            <tbody>
              {data.contacts.map(c => (
                <tr key={c.contact_id}><td>{c.contact}</td><td className="mono">{fmtAUD(c.current)}</td><td className="mono">{fmtAUD(c['1-30'])}</td>
                  <td className="mono">{fmtAUD(c['31-60'])}</td><td className="mono">{fmtAUD(c['61-90'])}</td><td className="mono">{fmtAUD(c['90+'])}</td>
                  <td className="mono fw-700">{fmtAUD(c.total)}</td></tr>
              ))}
            </tbody>
            <tfoot><tr className="fw-700"><td>Total</td><td className="mono">{fmtAUD(data.buckets.current)}</td><td className="mono">{fmtAUD(data.buckets['1-30'])}</td>
              <td className="mono">{fmtAUD(data.buckets['31-60'])}</td><td className="mono">{fmtAUD(data.buckets['61-90'])}</td><td className="mono">{fmtAUD(data.buckets['90+'])}</td>
              <td className="mono">{fmtAUD(data.total)}</td></tr></tfoot>
          </table>
        </>
      )}
    </div>
  )
}

function GstReport() {
  const [from, setFrom] = useState(fyStart())
  const [to, setTo] = useState(todayISO())
  const [basis, setBasis] = useState('accrual')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = () => { setLoading(true); api__1.ledgerReport('gst-summary', { from, to, basis }).then(r => setData(r.data)).catch(e => toast.error(api__0.errMsg(e))).finally(() => setLoading(false)) }
  useEffect(() => { run() }, [])

  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <label className="text-sm">From <input type="date" className="input input-sm" value={from} onChange={e => setFrom(e.target.value)} /></label>
        <label className="text-sm">To <input type="date" className="input input-sm" value={to} onChange={e => setTo(e.target.value)} /></label>
        <select className="select-compact" value={basis} onChange={e => setBasis(e.target.value)}><option value="accrual">Accrual</option><option value="cash">Cash</option></select>
        <button className="btn btn-primary btn-sm" onClick={run} disabled={loading}>Run</button>
      </div>
      {data && (
        <>
          <div className="stats-grid" style={{ marginBottom: 16 }}>
            <div className="stat-card"><div className="stat-label">1A – GST on sales</div><div className="stat-value">{fmtAUD(data.gst_on_sales_1A)}</div></div>
            <div className="stat-card"><div className="stat-label">1B – GST on purchases</div><div className="stat-value">{fmtAUD(data.gst_on_purchases_1B)}</div></div>
            <div className="stat-card"><div className="stat-label">Net GST payable</div><div className="stat-value">{fmtAUD(data.net_gst_payable)}</div></div>
            <div className="stat-card"><div className="stat-label">Ledger check</div>
              <div className="stat-value">{data.ledger_check.reconciled === true ? <span className="badge badge-success">Reconciled</span> : data.ledger_check.reconciled === false ? <span className="badge badge-warning">Off by {fmtAUD(data.ledger_check.difference)}</span> : '—'}</div>
            </div>
          </div>
          <table className="summary-table">
            <thead><tr><th>BAS label</th><th style={{ textAlign: 'right' }}>Amount</th></tr></thead>
            <tbody>{Object.entries(data.fields).map(([k, v]) => <tr key={k}><td>{k}</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(v)}</td></tr>)}</tbody>
          </table>
        </>
      )}
    </div>
  )
}

function CashFlowReport() {
  const [from, setFrom] = useState(fyStart())
  const [to, setTo] = useState(todayISO())
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const run = () => { setLoading(true); api__1.ledgerReport('cash-flow', { from, to }).then(r => setData(r.data)).catch(e => toast.error(api__0.errMsg(e))).finally(() => setLoading(false)) }
  useEffect(() => { run() }, [])

  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <label className="text-sm">From <input type="date" className="input input-sm" value={from} onChange={e => setFrom(e.target.value)} /></label>
        <label className="text-sm">To <input type="date" className="input input-sm" value={to} onChange={e => setTo(e.target.value)} /></label>
        <button className="btn btn-primary btn-sm" onClick={run} disabled={loading}>Run</button>
        {data && <span className={`badge ${data.reconciled ? 'badge-success' : 'badge-warning'}`}>{data.reconciled ? 'Reconciles to bank movement' : `Off by ${fmtAUD(data.difference)}`}</span>}
      </div>
      {data && (
        <table className="summary-table">
          <tbody>
            <tr className="fw-700"><td colSpan={2}>Operating activities</td></tr>
            <tr><td>Net profit</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(data.operating.net_profit)}</td></tr>
            {data.operating.adjustments.map((a, i) => <tr key={i}><td>{a.label}</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(a.amount)}</td></tr>)}
            <tr className="fw-700"><td>Net cash from operating</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(data.operating.total)}</td></tr>
            <tr className="fw-700"><td colSpan={2} style={{ paddingTop: 10 }}>Investing activities</td></tr>
            {data.investing.items.map((a, i) => <tr key={i}><td>{a.label}</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(a.amount)}</td></tr>)}
            <tr className="fw-700"><td>Net cash from investing</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(data.investing.total)}</td></tr>
            <tr className="fw-700"><td colSpan={2} style={{ paddingTop: 10 }}>Financing activities</td></tr>
            {data.financing.items.map((a, i) => <tr key={i}><td>{a.label}</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(a.amount)}</td></tr>)}
            <tr className="fw-700"><td>Net cash from financing</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(data.financing.total)}</td></tr>
            <tr className="fw-700" style={{ borderTop: '2px solid var(--border-dark)' }}><td style={{ paddingTop: 10 }}>Net change in cash</td><td style={{ textAlign: 'right', paddingTop: 10 }} className="mono">{fmtAUD(data.net_change_in_cash)}</td></tr>
            <tr><td>Opening cash</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(data.opening_cash)}</td></tr>
            <tr className="fw-700"><td>Closing cash</td><td style={{ textAlign: 'right' }} className="mono">{fmtAUD(data.closing_cash)}</td></tr>
          </tbody>
        </table>
      )}
    </div>
  )
}

function ByContactReport({ side }) {
  const [from, setFrom] = useState(fyStart())
  const [to, setTo] = useState(todayISO())
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const report = side === 'sales' ? api__1.salesReport : api__1.purchasesReport
  const endpoint = side === 'sales' ? 'by-customer' : 'by-supplier'
  const run = () => { setLoading(true); report(endpoint, { from, to }).then(r => setData(r.data)).catch(e => toast.error(api__0.errMsg(e))).finally(() => setLoading(false)) }
  useEffect(() => { run() }, [])

  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <label className="text-sm">From <input type="date" className="input input-sm" value={from} onChange={e => setFrom(e.target.value)} /></label>
        <label className="text-sm">To <input type="date" className="input input-sm" value={to} onChange={e => setTo(e.target.value)} /></label>
        <button className="btn btn-primary btn-sm" onClick={run} disabled={loading}>Run</button>
      </div>
      {data && (
        <table className="data-table">
          <thead><tr><th>{side === 'sales' ? 'Customer' : 'Supplier'}</th><th style={{ textAlign: 'right' }}>Net</th><th style={{ textAlign: 'right' }}>GST</th><th style={{ textAlign: 'right' }}>Gross</th><th style={{ textAlign: 'right' }}>Docs</th></tr></thead>
          <tbody>
            {data.rows.map(r => <tr key={r.contact_id}><td>{r.contact}</td><td className="mono" style={{ textAlign: 'right' }}>{fmtAUD(r.net)}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{fmtAUD(r.gst)}</td><td className="mono fw-700" style={{ textAlign: 'right' }}>{fmtAUD(r.gross)}</td>
              <td style={{ textAlign: 'right' }}>{r.documents}</td></tr>)}
          </tbody>
          <tfoot><tr className="fw-700"><td>Total</td><td className="mono" style={{ textAlign: 'right' }}>{fmtAUD(data.totals.net)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{fmtAUD(data.totals.gst)}</td><td className="mono" style={{ textAlign: 'right' }}>{fmtAUD(data.totals.gross)}</td><td /></tr></tfoot>
        </table>
      )}
    </div>
  )
}

function ControlReport() {
  const [asAt, setAsAt] = useState(todayISO())
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const run = () => { setLoading(true); api__1.ledgerReport('subledger-control', { as_at: asAt }).then(r => setData(r.data)).catch(e => toast.error(api__0.errMsg(e))).finally(() => setLoading(false)) }
  useEffect(() => { run() }, [])
  return (
    <div>
      <div className="flex items-center gap-4" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
        <label className="text-sm">As at <input type="date" className="input input-sm" value={asAt} onChange={e => setAsAt(e.target.value)} /></label>
        <button className="btn btn-primary btn-sm" onClick={run} disabled={loading}>Run</button>
      </div>
      {data && (
        <div className="grid-2" style={{ gap: 16 }}>
          {['receivables', 'payables'].map(k => (
            <div key={k} className="card">
              <div className="section-header">{k === 'receivables' ? 'Accounts Receivable' : 'Accounts Payable'}</div>
              <div className="text-sm">Ledger balance: <strong>{fmtAUD(data[k].ledger_balance)}</strong></div>
              <div className="text-sm">Sub-ledger total: <strong>{fmtAUD(data[k].subledger_total)}</strong></div>
              <div className="text-sm">Difference: <strong>{fmtAUD(data[k].difference)}</strong></div>
              <div style={{ marginTop: 6 }}><span className={`badge ${data[k].reconciled ? 'badge-success' : 'badge-warning'}`}>{data[k].reconciled ? 'Reconciled' : 'Not reconciled'}</span></div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
