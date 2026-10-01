/**
 * ExtraReports - the eleven reports that were "coming soon" in Financial Reports, now live:
 *   Budget Variance · Cash Summary · Management Report · Expense Claims · PAYG Summary · General Ledger Summary
 *   Bank Reconciliation · Account Summary · Cash Validation · Journal Report · Inventory Item Details
 *
 * Same conventions as FinancialReports: every screen loads through useReport (never throws into React), is wrapped by the
 * caller's error boundary, tolerates missing fields, and hands its rows to setExport for the CSV button.
 * Data comes from /ledger/reports/* and /banking/reconciliation (all derived from the posted ledger and sub-ledgers).
 */
import React, { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import * as books from '../../lib/booksApi.js'
import { num, fmtAUD, fmtDate, fyStart, todayISO, arr, Sec, R, Tot, GH, EmptyState, ReportLoading, Note, Badge, Filters, DateField, useReport, ErrorState } from './reportKit.jsx'

const mono = { fontFamily: 'var(--font-mono)' }
const right = { textAlign: 'right' }
const monthLabel = ym => { const [y, m] = String(ym).split('-'); return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString('en-AU', { month: 'short', year: '2-digit' }) }
const pctText = v => (v == null || v === '' ? '—' : `${num(v).toFixed(1)}%`)
const fmtNum = v => new Intl.NumberFormat('en-AU', { maximumFractionDigits: 2 }).format(num(v))
const sevColor = { high: ['#991b1b', '#fee2e2'], medium: ['#92400e', '#fef3c7'], low: ['#1e40af', '#dbeafe'] }
const useRange = () => { const [from, setFrom] = useState(fyStart()); const [to, setTo] = useState(todayISO()); return { from, to, setFrom, setTo } }
const RangeFilters = ({ r, run, busy, children }) => (
  <Filters onRun={run} busy={busy}><DateField label="From" value={r.from} onChange={r.setFrom} /><DateField label="To" value={r.to} onChange={r.setTo} />{children}</Filters>
)
const Body = ({ state, children, emptyWhen, empty }) => {
  const { data, loading, error, run } = state
  if (error) return <ErrorState error={error} run={run} />
  if (!data) return loading ? <ReportLoading /> : null
  if (emptyWhen && emptyWhen(data)) return empty
  return children(data)
}

// Small generic table: cols = [{ h, k | f(row), align, money, mono, bold, title }]
function Tbl({ cols, rows, foot, dense, keyOf }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table" style={{ fontSize: dense ? '.76rem' : '.81rem' }}>
        <thead><tr>{cols.map(c => <th key={c.h} style={c.align === 'right' || c.money ? right : undefined}>{c.h}</th>)}</tr></thead>
        <tbody>
          {arr(rows).map((r, i) => (
            <tr key={keyOf ? keyOf(r, i) : i}>
              {cols.map(c => {
                const v = c.f ? c.f(r) : r?.[c.k]
                return (<td key={c.h} title={c.title ? c.title(r) : undefined}
                  style={{ ...(c.align === 'right' || c.money ? right : {}), ...(c.money || c.mono ? mono : {}), ...(c.bold ? { fontWeight: 700 } : {}), ...(c.color ? { color: c.color(r) } : {}), ...(c.wrap ? {} : {}) }}>
                  {c.money ? (num(v) || v === 0 || v === '0.00' ? fmtAUD(v) : '') : (v ?? '')}</td>)
              })}
            </tr>
          ))}
          {foot}
        </tbody>
      </table>
    </div>
  )
}
const FootRow = ({ cols, values }) => (
  <tr style={{ background: 'var(--surface-2)', borderTop: '2px solid var(--border)' }}>
    {cols.map((c, i) => <td key={c.h} style={{ fontWeight: 700, ...(c.align === 'right' || c.money ? right : {}), ...(c.money ? mono : {}) }}>{i === 0 ? (values[c.h] ?? 'Total') : (c.money && values[c.h] != null ? fmtAUD(values[c.h]) : (values[c.h] ?? ''))}</td>)}
  </tr>
)
const Stat = ({ label, value, color, sub }) => (
  <div style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: '12px 14px', borderTop: `3px solid ${color || 'var(--brand)'}` }}>
    <div style={{ fontSize: '.68rem', fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', marginBottom: 4 }}>{label}</div>
    <div style={{ ...mono, fontWeight: 700, fontSize: '1rem', color }}>{value}</div>
    {sub && <div style={{ fontSize: '.68rem', color: 'var(--text-3)', marginTop: 2 }}>{sub}</div>}
  </div>
)
const StatGrid = ({ children, cols = 4 }) => <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols},1fr)`, gap: 12, marginBottom: 16 }}>{children}</div>
const Panel = ({ title, children, accent }) => (
  <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden', background: 'var(--surface)' }}>
    <div style={{ padding: '9px 14px', background: 'var(--surface-2)', fontWeight: 700, fontSize: '.84rem', borderBottom: '1px solid var(--border)', borderLeft: `4px solid ${accent || 'var(--brand)'}` }}>{title}</div>
    {children}
  </div>
)
const Cols2 = ({ children }) => <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>{children}</div>

// ── General Ledger Summary ────────────────────────────────────────────────────
function GLSummary({ setExport }) {
  const r = useRange()
  const st = useReport(() => books.ledgerReport('gl-summary', { from: r.from, to: r.to }), [])
  const { data } = st
  useEffect(() => { if (data) setExport({ name: `gl-summary-${r.from}-${r.to}`, rows: [['Code', 'Account', 'Group', 'Opening', 'Debit', 'Credit', 'Closing'], ...arr(data.rows).map(x => [x.code, x.name, x.group, x.opening, x.debit, x.credit, x.closing])] }) }, [data])
  const cols = [{ h: 'Code', k: 'code', mono: true }, { h: 'Account', k: 'name' }, { h: 'Opening', k: 'opening', money: true }, { h: 'Debit', k: 'debit', money: true }, { h: 'Credit', k: 'credit', money: true }, { h: 'Closing', k: 'closing', money: true, bold: true }]
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading} />
    <Body state={st} emptyWhen={d => !arr(d.rows).length} empty={<EmptyState title="No ledger activity" detail="Nothing has been posted to the ledger up to the end of this period." />}>
      {d => (
        <div style={{ padding: 8 }}>
          {arr(d.groups).map(g => (
            <Sec key={g.type} label={`${g.label} (${g.count})`} total={num(g.closing)} accent="#2563eb" open={['bank', 'revenue', 'expense'].includes(g.type)}>
              <Tbl cols={cols} rows={arr(d.rows).filter(x => x.type === g.type)} keyOf={x => x.account_id} dense />
            </Sec>
          ))}
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 14px', background: 'var(--surface-2)', borderTop: '2px solid var(--border)', fontWeight: 700, fontSize: '.85rem' }}>
            <span>Period movement ({d.accounts} accounts)</span><span style={mono}>Debits {fmtAUD(d.total_debit)} · Credits {fmtAUD(d.total_credit)}</span></div>
          <Note warn={!d.balanced}>{d.balanced ? '✓ Period debits equal credits.' : '⚠ Period debits and credits differ.'} {d.note}</Note>
        </div>)}
    </Body>
  </>)
}

// ── Journal Report ────────────────────────────────────────────────────────────
function JournalReport({ setExport }) {
  const r = useRange(); const [src, setSrc] = useState(''); const [rev, setRev] = useState(true); const [open, setOpen] = useState({})
  const st = useReport(() => books.ledgerReport('journal-report', { from: r.from, to: r.to, source_type: src || undefined, include_reversed: rev, limit: 500 }), [])
  const { data } = st
  useEffect(() => {
    if (data) setExport({ name: `journals-${r.from}-${r.to}`, rows: [['Journal', 'Date', 'Source', 'Status', 'Narration', 'Account', 'Description', 'Debit', 'Credit', 'Tax code', 'Tax'],
      ...arr(data.journals).flatMap(j => arr(j.lines).map(l => [j.journal_no, j.date, j.source_type, j.status, j.narration, `${l.account_code} ${l.account_name}`, l.description, l.debit, l.credit, l.tax_code, l.tax_amount]))] })
  }, [data])
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading}>
      <select className="select-compact" value={src} onChange={e => setSrc(e.target.value)}><option value="">All sources</option>{arr(data?.sources).map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}</select>
      <label className="text-sm"><input type="checkbox" checked={rev} onChange={e => setRev(e.target.checked)} /> Include reversed</label>
    </RangeFilters>
    <Body state={st} emptyWhen={d => !arr(d.journals).length} empty={<EmptyState title="No journals in this period" detail="Approve invoices/bills, record payments or post manual journals to see them here." />}>
      {d => (
        <div style={{ padding: 8 }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', padding: '4px 6px 10px', fontSize: '.76rem', color: 'var(--text-2)' }}>
            <strong>{d.count}{d.truncated ? ` of ${d.total_count}` : ''} journals</strong>
            {Object.entries(d.by_source || {}).map(([k, v]) => <span key={k} style={{ background: 'var(--surface-2)', borderRadius: 100, padding: '1px 8px' }}>{k.replace(/_/g, ' ')} · {v.count}</span>)}
          </div>
          {arr(d.journals).map(j => (
            <div key={j.id} style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-md)', marginBottom: 6, overflow: 'hidden', opacity: j.status === 'reversed' ? 0.65 : 1 }}>
              <button onClick={() => setOpen(o => ({ ...o, [j.id]: !o[j.id] }))} style={{ width: '100%', display: 'flex', gap: 12, alignItems: 'center', padding: '7px 12px', background: 'var(--surface-2)', border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: '.8rem', textAlign: 'left' }}>
                <span style={{ ...mono, fontWeight: 700, minWidth: 44 }}>#{j.journal_no}</span><span style={{ minWidth: 78 }}>{fmtDate(j.date)}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.narration}</span>
                <span style={{ fontSize: '.68rem', color: 'var(--text-3)' }}>{j.source_type.replace(/_/g, ' ')}{j.status === 'reversed' ? ' · reversed' : j.reversal_of_id ? ' · reversal' : ''}</span>
                <span style={{ ...mono, fontWeight: 700 }}>{fmtAUD(j.total)}</span></button>
              {open[j.id] && (
                <Tbl dense keyOf={(l, i) => i} rows={j.lines} cols={[{ h: 'Account', f: l => `${l.account_code} · ${l.account_name}` }, { h: 'Description', k: 'description' }, { h: 'Tax', f: l => l.tax_code ? `${l.tax_code}${num(l.tax_amount) ? ` (${fmtAUD(l.tax_amount)})` : ''}` : '' },
                  { h: 'Debit', f: l => num(l.debit) ? l.debit : '', money: true }, { h: 'Credit', f: l => num(l.credit) ? l.credit : '', money: true }]} />)}
            </div>))}
          {d.truncated && <Note>Showing the first {d.count} of {d.total_count} journals — narrow the dates or pick a source to see the rest.</Note>}
          <Note warn={!d.balanced}>{d.balanced ? `✓ Every journal balances (total debits ${fmtAUD(d.total_debit)}).` : '⚠ A journal does not balance.'}</Note>
        </div>)}
    </Body>
  </>)
}

// ── Cash Summary ──────────────────────────────────────────────────────────────
function CashSummary({ setExport }) {
  const r = useRange()
  const st = useReport(() => books.ledgerReport('cash-summary', { from: r.from, to: r.to }), [])
  const { data } = st
  useEffect(() => {
    if (data) setExport({ name: `cash-summary-${r.from}-${r.to}`, rows: [['Section', 'Account', 'Cash received', 'Cash paid', 'Net'], ...arr(data.sections).flatMap(s => arr(s.rows).map(x => [s.section, `${x.code} ${x.name}`, x.receipts, x.payments, x.net])),
      ['', 'Opening cash', '', '', data.opening_cash], ['', 'Closing cash', '', '', data.closing_cash]] })
  }, [data])
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading} />
    <Body state={st} emptyWhen={d => d.has_bank === false} empty={<EmptyState title="No bank accounts" detail="Add a bank account in Reconciliation to see cash movements." />}>
      {d => (
        <div style={{ padding: 20 }}>
          <StatGrid>
            <Stat label="Opening cash" value={fmtAUD(d.opening_cash)} />
            <Stat label="Cash received" value={fmtAUD(d.total_receipts)} color="#16a34a" />
            <Stat label="Cash paid" value={fmtAUD(d.total_payments)} color="#dc2626" />
            <Stat label="Closing cash" value={fmtAUD(d.closing_cash)} color={num(d.closing_cash) < 0 ? '#dc2626' : undefined} sub={`Net ${num(d.net_movement) >= 0 ? '+' : ''}${fmtAUD(d.net_movement)}`} />
          </StatGrid>
          {arr(d.months).length > 1 && (
            <div style={{ height: 220, marginBottom: 16 }}>
              <ResponsiveContainer width="100%" height="100%"><ComposedChart data={arr(d.months).map(m => ({ month: monthLabel(m.month), Received: num(m.receipts), Paid: num(m.payments), Closing: num(m.closing) }))}>
                <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="month" fontSize={11} /><YAxis fontSize={11} tickFormatter={v => `${Math.round(v / 1000)}k`} /><Tooltip formatter={v => fmtAUD(v)} /><Legend />
                <Bar dataKey="Received" fill="#16a34a" /><Bar dataKey="Paid" fill="#dc2626" /><Line dataKey="Closing" stroke="#2563eb" dot={false} strokeWidth={2} /></ComposedChart></ResponsiveContainer>
            </div>)}
          {arr(d.sections).map(s => (
            <Sec key={s.section} label={s.section} total={num(s.net)} accent={num(s.net) >= 0 ? '#16a34a' : '#dc2626'} open={false}>
              <Tbl dense keyOf={x => x.account_id} rows={s.rows} cols={[{ h: 'Code', k: 'code', mono: true }, { h: 'Account', k: 'name' }, { h: 'Received', k: 'receipts', money: true }, { h: 'Paid', k: 'payments', money: true }, { h: 'Net', k: 'net', money: true, bold: true }]} />
            </Sec>))}
          <Tot label="Net cash movement" amount={d.net_movement} strong bg />
          <Panel title="By month" accent="#2563eb"><Tbl dense keyOf={m => m.month} rows={d.months} cols={[{ h: 'Month', f: m => monthLabel(m.month) }, { h: 'Received', k: 'receipts', money: true }, { h: 'Paid', k: 'payments', money: true }, { h: 'Net', k: 'net', money: true }, { h: 'Closing cash', k: 'closing', money: true, bold: true }]} /></Panel>
          <Note warn={!d.reconciled}>{d.reconciled ? '✓ Reconciles to the movement in bank account balances.' : `⚠ Off by ${fmtAUD(d.difference)}.`} {d.note}</Note>
        </div>)}
    </Body>
  </>)
}

// ── Account Summary ───────────────────────────────────────────────────────────
function AccountSummary({ setExport }) {
  const r = useRange()
  const st = useReport(() => books.ledgerReport('account-summary', { from: r.from, to: r.to }), [])
  const { data } = st
  useEffect(() => { if (data) setExport({ name: `account-summary-${r.from}-${r.to}`, rows: [['Account', 'Month', 'In', 'Out', 'Closing'], ...arr(data.accounts).flatMap(a => arr(a.months).map(m => [`${a.code} ${a.name}`, m.month, m.inflow, m.outflow, m.closing]))] }) }, [data])
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading} />
    <Body state={st} emptyWhen={d => !arr(d.accounts).length} empty={<EmptyState title="No bank or card accounts" detail="Add a bank account in Reconciliation to see monthly activity." />}>
      {d => (
        <div style={{ padding: 20, display: 'grid', gap: 16 }}>
          {arr(d.accounts).map(a => (
            <Panel key={a.account_id} title={`${a.code} · ${a.name}${a.type === 'credit_card' ? ' (credit card — amount owing)' : ''}`} accent={a.type === 'bank' ? '#2563eb' : '#d97706'}>
              <div style={{ display: 'flex', gap: 24, padding: '10px 14px', fontSize: '.8rem', flexWrap: 'wrap' }}>
                <span>Opening <strong style={mono}>{fmtAUD(a.opening)}</strong></span><span>{a.type === 'bank' ? 'In' : 'Repaid'} <strong style={{ ...mono, color: '#16a34a' }}>{fmtAUD(a.total_in)}</strong></span>
                <span>{a.type === 'bank' ? 'Out' : 'Spend'} <strong style={{ ...mono, color: '#dc2626' }}>{fmtAUD(a.total_out)}</strong></span><span>Closing <strong style={mono}>{fmtAUD(a.closing)}</strong></span>
                {a.unreconciled_lines > 0 && <Badge ok={false} yes="" no={`${a.unreconciled_lines} unreconciled lines`} />}
                {a.last_statement_date && <span style={{ color: 'var(--text-3)' }}>Last statement line {fmtDate(a.last_statement_date)}</span>}
              </div>
              <Tbl dense keyOf={m => m.month} rows={a.months} cols={[{ h: 'Month', f: m => monthLabel(m.month) }, { h: a.type === 'bank' ? 'Money in' : 'Repayments', k: 'inflow', money: true }, { h: a.type === 'bank' ? 'Money out' : 'Spend', k: 'outflow', money: true }, { h: 'Closing', k: 'closing', money: true, bold: true }]} />
            </Panel>))}
          <Note>{d.note}</Note>
        </div>)}
    </Body>
  </>)
}

// ── Bank Reconciliation ───────────────────────────────────────────────────────
function BankRecon({ setExport }) {
  const [accts, setAccts] = useState([]); const [acct, setAcct] = useState(''); const [asAt, setAsAt] = useState(todayISO()); const [stmt, setStmt] = useState('')
  const [st, setSt] = useState({ data: null, loading: false, error: '' })
  useEffect(() => { books.bankAccounts().then(x => { const items = arr(x.data?.items); setAccts(items); if (items[0]) setAcct(String(items[0].id)) }).catch(() => {}) }, [])
  const run = () => {
    if (!acct) return
    setSt({ data: null, loading: true, error: '' })
    books.reconciliationReport(acct, { as_at: asAt, statement_balance: stmt === '' ? undefined : stmt })
      .then(x => setSt({ data: x.data, loading: false, error: '' })).catch(e => setSt({ data: null, loading: false, error: books.errMsg(e, 'Could not load this reconciliation') }))
  }
  useEffect(() => { if (acct) run() }, [acct])
  const d = st.data
  useEffect(() => {
    if (d) setExport({ name: `bank-reconciliation-${d.account?.code}-${asAt}`, rows: [['Item', 'Date', 'Description', 'Amount'], ['Ledger balance', asAt, '', d.ledger_balance], ['Statement balance', asAt, '', d.statement_balance],
      ...arr(d.unreconciled_statement_lines?.lines).map(l => ['On statement, not in books', l.line_date || l.date, l.description, l.amount]), ...arr(d.unmatched_ledger_items?.items).map(l => ['In books, not on statement', l.date, l.description, l.amount])] })
  }, [d])
  const hasStmt = d && d.statement_balance != null
  return (<>
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
      <select className="input input-sm" style={{ maxWidth: 260 }} value={acct} onChange={e => setAcct(e.target.value)}><option value="">Choose account…</option>{accts.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select>
      <DateField label="As at" value={asAt} onChange={setAsAt} />
      <label className="text-sm">Statement balance <input className="input input-sm" style={{ width: 120 }} placeholder="from last line" value={stmt} onChange={e => setStmt(e.target.value)} /></label>
      <button className="btn btn-primary btn-sm" onClick={run} disabled={!acct || st.loading}>{st.loading ? 'Running…' : 'Run'}</button>
    </div>
    {st.error ? <ErrorState error={st.error} run={run} /> : !d ? (st.loading ? <ReportLoading /> : <EmptyState title="Choose a bank account" detail="Pick an account and press Run to compare the ledger with the bank statement." />) : (
      <div style={{ padding: 20 }}>
        <StatGrid cols={3}>
          <Stat label="Balance in AccFino (ledger)" value={fmtAUD(d.ledger_balance)} />
          <Stat label="Balance per bank statement" value={hasStmt ? fmtAUD(d.statement_balance) : '—'} sub={hasStmt ? undefined : 'No statement balance — enter one above'} />
          <Stat label="Unexplained difference" value={hasStmt ? fmtAUD(d.difference) : '—'} color={hasStmt ? (num(d.difference) === 0 ? '#16a34a' : '#dc2626') : undefined} />
        </StatGrid>
        <Cols2>
          <Panel title={`On the statement, not yet in the books (${d.unreconciled_statement_lines?.count ?? 0})`} accent="#d97706">
            {arr(d.unreconciled_statement_lines?.lines).length ? <Tbl dense keyOf={l => l.id} rows={d.unreconciled_statement_lines.lines} cols={[{ h: 'Date', f: l => fmtDate(l.line_date || l.date) }, { h: 'Description', k: 'description' }, { h: 'Amount', k: 'amount', money: true }]}
              foot={<FootRow cols={[{ h: 'Date' }, { h: 'Description' }, { h: 'Amount', money: true }]} values={{ Date: 'Net', Amount: d.unreconciled_statement_lines.net }} />} /> : <div style={{ padding: 14, fontSize: '.8rem', color: 'var(--text-3)' }}>Every statement line is matched or coded.</div>}
          </Panel>
          <Panel title={`In the books, not yet on the statement (${d.unmatched_ledger_items?.count ?? 0})`} accent="#7c3aed">
            {arr(d.unmatched_ledger_items?.items).length ? <Tbl dense keyOf={l => l.journal_id} rows={d.unmatched_ledger_items.items} cols={[{ h: 'Date', f: l => fmtDate(l.date) }, { h: 'Description', k: 'description' }, { h: 'Amount', k: 'amount', money: true }]}
              foot={<FootRow cols={[{ h: 'Date' }, { h: 'Description' }, { h: 'Amount', money: true }]} values={{ Date: 'Net', Amount: d.unmatched_ledger_items.net }} />} /> : <div style={{ padding: 14, fontSize: '.8rem', color: 'var(--text-3)' }}>Every ledger item has reached the statement.</div>}
          </Panel>
        </Cols2>
        {hasStmt && <Note warn={num(d.difference) !== 0}>{num(d.difference) === 0 ? '✓ The statement balance, adjusted for timing items, equals the ledger balance.' : `⚠ ${fmtAUD(d.difference)} is unexplained.`}{d.reconciled ? ' Fully reconciled — nothing outstanding.' : ' Outstanding items above still need matching or coding in Reconciliation.'}</Note>}
        {d.excluded_statement_lines?.count > 0 && <Note>{d.excluded_statement_lines.count} statement line(s) marked “excluded” (net {fmtAUD(d.excluded_statement_lines.net)}) are treated as not part of the books.</Note>}
        {d.explanation && <Note>{d.explanation}</Note>}
      </div>)}
  </>)
}

// ── Cash Validation ───────────────────────────────────────────────────────────
const humanKey = k => k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
function CashValidation({ setExport }) {
  const r = useRange()
  const st = useReport(() => books.ledgerReport('cash-validation', { from: r.from, to: r.to }), [])
  const { data } = st
  useEffect(() => { if (data) setExport({ name: `cash-validation-${r.from}-${r.to}`, rows: [['Check', 'Severity', 'Detail'], ...arr(data.checks).flatMap(c => arr(c.items).map(i => [c.title, c.severity, Object.entries(i).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join('/') : v}`).join('; ')]))] }) }, [data])
  const moneyKeys = new Set(['amount', 'total', 'balance', 'debit', 'credit', 'unallocated', 'typical'])
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading} />
    <Body state={st}>
      {d => (
        <div style={{ padding: 20 }}>
          <StatGrid cols={4}>
            <Stat label="Findings" value={d.issues} color={d.issues ? '#d97706' : '#16a34a'} /><Stat label="High" value={d.by_severity?.high ?? 0} color="#dc2626" />
            <Stat label="Medium" value={d.by_severity?.medium ?? 0} color="#d97706" /><Stat label="Low" value={d.by_severity?.low ?? 0} color="#2563eb" />
          </StatGrid>
          {d.clean && <Note>✓ Nothing unusual found in this period.</Note>}
          {arr(d.checks).map(c => {
            const [fg, bg] = sevColor[c.severity] || sevColor.low
            const keys = c.items?.[0] ? Object.keys(c.items[0]) : []
            return (
              <Sec key={c.key} label={`${c.title} — ${c.count}`} total={0} accent={c.count ? fg : '#16a34a'} open={c.count > 0}>
                <div style={{ padding: '6px 14px', fontSize: '.75rem', color: 'var(--text-3)' }}>
                  <span style={{ padding: '1px 7px', borderRadius: 100, fontWeight: 700, color: fg, background: bg, marginRight: 8 }}>{c.severity}</span>{c.why}</div>
                {c.count > 0 && <Tbl dense rows={c.items} cols={keys.map(k => ({ h: humanKey(k), f: i => Array.isArray(i[k]) ? i[k].filter(Boolean).join(', ') : i[k], money: moneyKeys.has(k) }))} />}
                {c.truncated && <Note>Showing the first {c.items.length} of {c.count}.</Note>}
              </Sec>)
          })}
          <Note>These are prompts to look, not proof of an error — each says what it searched for and why it matters.</Note>
        </div>)}
    </Body>
  </>)
}

// ── Expense Claims ────────────────────────────────────────────────────────────
const claimColor = { draft: '#6b7280', submitted: '#d97706', approved: '#2563eb', paid: '#16a34a', rejected: '#dc2626' }
function ExpenseClaimsReport({ setExport }) {
  const r = useRange()
  const st = useReport(() => books.ledgerReport('expense-claims', { from: r.from, to: r.to }), [])
  const { data } = st
  useEffect(() => { if (data) setExport({ name: `expense-claims-${r.from}-${r.to}`, rows: [['Claim', 'Claimant', 'Title', 'Date', 'Status', 'Net', 'GST', 'Total'], ...arr(data.claims).map(c => [c.number, c.claimant, c.title, c.date, c.status, c.net, c.gst, c.total])] }) }, [data])
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading} />
    <Body state={st} emptyWhen={d => !arr(d.claims).length} empty={<EmptyState title="No expense claims in this period" detail="Claims are dated by their latest expense item. Create claims in the Expenses tab." />}>
      {d => (
        <div style={{ padding: 20 }}>
          <StatGrid>
            <Stat label="Total claimed" value={fmtAUD(d.total)} sub={`${d.count} claims · GST ${fmtAUD(d.gst)}`} /><Stat label="Awaiting approval" value={fmtAUD(d.awaiting_approval)} color="#d97706" />
            <Stat label="Approved, unpaid" value={fmtAUD(d.approved_unpaid)} color="#2563eb" sub="Owed to staff" /><Stat label="Claimants" value={arr(d.by_claimant).length} />
          </StatGrid>
          <Cols2>
            <Panel title="By status" accent="#2563eb"><Tbl dense keyOf={x => x.name} rows={d.by_status} cols={[{ h: 'Status', f: x => x.name, color: x => claimColor[x.name], bold: true }, { h: 'Claims', k: 'count', align: 'right' }, { h: 'GST', k: 'gst', money: true }, { h: 'Total', k: 'total', money: true, bold: true }]} /></Panel>
            <Panel title="By claimant" accent="#7c3aed"><Tbl dense keyOf={x => x.name} rows={d.by_claimant} cols={[{ h: 'Claimant', k: 'name' }, { h: 'Claims', k: 'count', align: 'right' }, { h: 'GST', k: 'gst', money: true }, { h: 'Total', k: 'total', money: true, bold: true }]} /></Panel>
          </Cols2>
          <Panel title="By expense category" accent="#d97706"><Tbl dense keyOf={x => x.name} rows={d.by_category} cols={[{ h: 'Account', k: 'name' }, { h: 'Items', k: 'count', align: 'right' }, { h: 'Net', k: 'net', money: true }, { h: 'GST', k: 'gst', money: true }, { h: 'Gross', k: 'gross', money: true, bold: true }]} /></Panel>
          <div style={{ height: 16 }} />
          <Panel title="All claims" accent="#6b7280"><Tbl dense keyOf={c => c.id} rows={d.claims} cols={[{ h: 'Claim', k: 'number', mono: true }, { h: 'Claimant', k: 'claimant' }, { h: 'Title', k: 'title', title: c => c.rejected_reason || c.title }, { h: 'Date', f: c => fmtDate(c.date) },
            { h: 'Status', k: 'status', color: c => claimColor[c.status], bold: true }, { h: 'Total', k: 'total', money: true, bold: true }]} /></Panel>
        </div>)}
    </Body>
  </>)
}

// ── PAYG Summary ──────────────────────────────────────────────────────────────
function PaygSummary({ setExport }) {
  const r = useRange()
  const st = useReport(() => books.ledgerReport('payg-summary', { from: r.from, to: r.to }), [])
  const { data } = st
  useEffect(() => { if (data) setExport({ name: `payg-summary-${r.from}-${r.to}`, rows: [['BAS label', 'Amount'], ['W1 Total salary, wages and other payments', data.bas?.W1], ['W2 Amounts withheld from payments shown at W1', data.bas?.W2],
    [], ['Month', 'Gross wages', 'PAYG withheld', 'PAYG remitted', 'Super accrued', 'Super paid'], ...arr(data.months).map(m => [m.month, m.gross, m.withheld, m.remitted, m.super_accrued, m.super_paid])] }) }, [data])
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading} />
    <Body state={st} emptyWhen={d => !d.has_payroll} empty={<EmptyState title="No payroll in this period" detail="PAYG figures come from payroll journals posted to the ledger (wages 477, PAYG 825, super 826)." />}>
      {d => (
        <div style={{ padding: 20 }}>
          <Cols2>
            <Panel title="BAS — PAYG withholding" accent="#7c3aed">
              <R account="W1  Total salary, wages and other payments" amount={d.bas?.W1} /><R account="W2  Amounts withheld from payments shown at W1" amount={d.bas?.W2} />
              <R account="W3 / W4 / W5  Other withholding" amount={d.bas?.W3} /><Tot label="Total withheld (W2 + W3 + W4 + W5)" amount={d.bas?.total_withheld} strong bg /></Panel>
            <Panel title="Superannuation & liabilities" accent="#2563eb">
              <R account="Super accrued this period" amount={d.super?.accrued} /><R account="Super paid this period" amount={d.super?.paid} /><R account="PAYG remitted to the ATO" amount={d.remitted_to_ato} />
              <Tot label="PAYG still payable at period end" amount={d.liabilities_at_end?.payg_withholding} /><Tot label="Super still payable at period end" amount={d.liabilities_at_end?.superannuation} /></Panel>
          </Cols2>
          <Panel title="By month" accent="#16a34a"><Tbl dense keyOf={m => m.month} rows={d.months} cols={[{ h: 'Month', f: m => monthLabel(m.month) }, { h: 'Gross wages (W1)', k: 'gross', money: true }, { h: 'PAYG withheld (W2)', k: 'withheld', money: true }, { h: 'PAYG remitted', k: 'remitted', money: true },
            { h: 'Super accrued', k: 'super_accrued', money: true }, { h: 'Super paid', k: 'super_paid', money: true }]} /></Panel>
          {arr(d.runs).length > 0 && <><div style={{ height: 16 }} /><Panel title="Pay runs" accent="#d97706"><Tbl dense keyOf={x => x.journal_no} rows={d.runs} cols={[{ h: 'Journal', k: 'journal_no', mono: true }, { h: 'Date', f: x => fmtDate(x.date) }, { h: 'Narration', k: 'narration' }, { h: 'Gross', k: 'gross', money: true }, { h: 'PAYG', k: 'payg', money: true }, { h: 'Net pay', k: 'net_pay', money: true }, { h: 'Super', k: 'super', money: true }]} /></Panel></>}
          <Note warn={!d.check?.reconciled}>{d.check?.reconciled ? '✓ PAYG withheld less remitted equals the movement on the PAYG ledger account.' : '⚠ PAYG ledger movement does not agree with withheld less remitted.'}</Note>
          <Note warn>{d.note} Verify with your accountant before lodging a BAS.</Note>
        </div>)}
    </Body>
  </>)
}

// ── Inventory Item Details ────────────────────────────────────────────────────
function InventoryItems({ setExport }) {
  const r = useRange(); const [open, setOpen] = useState({})
  const st = useReport(() => books.ledgerReport('inventory-items', { from: r.from, to: r.to }), [])
  const { data } = st
  useEffect(() => { if (data) setExport({ name: `inventory-items-${r.from}-${r.to}`, rows: [['SKU', 'Item', 'Opening qty', 'Purchased', 'Sold', 'Adjusted', 'Closing qty', 'Average cost', 'Closing value'], ...arr(data.items).map(i => [i.sku, i.name, i.opening_qty, i.purchased_qty, i.sold_qty, i.adjustment_qty, i.closing_qty, i.average_cost, i.closing_value])] }) }, [data])
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading} />
    <Body state={st} emptyWhen={d => !arr(d.items).length} empty={<EmptyState title="No inventory items" detail="Add stock items in the Inventory tab." />}>
      {d => (
        <div style={{ padding: 20 }}>
          <StatGrid>
            <Stat label="Opening value" value={fmtAUD(d.totals?.opening_value)} /><Stat label="Purchases" value={fmtAUD(d.totals?.purchases_value)} color="#2563eb" />
            <Stat label="Cost of goods sold" value={fmtAUD(d.totals?.cogs_value)} color="#dc2626" /><Stat label="Closing value" value={fmtAUD(d.totals?.closing_value)} color="#16a34a" />
          </StatGrid>
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table" style={{ fontSize: '.8rem' }}>
              <thead><tr><th>SKU</th><th>Item</th><th style={right}>Opening</th><th style={right}>Bought</th><th style={right}>Sold</th><th style={right}>Adj.</th><th style={right}>On hand</th><th style={right}>Avg cost</th><th style={right}>Value</th><th style={right}>Margin</th></tr></thead>
              <tbody>
                {arr(d.items).map(i => (
                  <React.Fragment key={i.item_id}>
                    <tr onClick={() => setOpen(o => ({ ...o, [i.item_id]: !o[i.item_id] }))} style={{ cursor: 'pointer' }}>
                      <td style={{ ...mono, fontWeight: 700 }}>{i.sku}</td><td>{i.name}{i.low_stock && <span style={{ marginLeft: 6, fontSize: '.65rem', padding: '1px 6px', borderRadius: 100, background: '#fee2e2', color: '#991b1b', fontWeight: 700 }}>out of stock</span>}</td>
                      <td style={right}>{fmtNum(i.opening_qty)}</td><td style={right}>{fmtNum(i.purchased_qty)}</td><td style={right}>{fmtNum(i.sold_qty)}</td><td style={right}>{fmtNum(i.adjustment_qty)}</td>
                      <td style={{ ...right, fontWeight: 700 }}>{fmtNum(i.closing_qty)}</td><td style={{ ...right, ...mono }}>{fmtAUD(i.average_cost)}</td><td style={{ ...right, ...mono, fontWeight: 700 }}>{fmtAUD(i.closing_value)}</td><td style={right}>{pctText(i.margin_pct)}</td></tr>
                    {open[i.item_id] && <tr><td colSpan={10} style={{ background: 'var(--surface-2)', padding: 8 }}>
                      {arr(i.movements).length ? <Tbl dense keyOf={(m, k) => k} rows={i.movements} cols={[{ h: 'Date', f: m => fmtDate(m.date) }, { h: 'Type', k: 'kind' }, { h: 'Qty', f: m => fmtNum(m.quantity), align: 'right' }, { h: 'Unit cost', k: 'unit_cost', money: true }, { h: 'Value', k: 'amount', money: true },
                        { h: 'Balance qty', f: m => fmtNum(m.balance_qty), align: 'right' }, { h: 'Balance value', k: 'balance_value', money: true }, { h: 'Reference', k: 'reference' }]} /> : <span style={{ fontSize: '.78rem', color: 'var(--text-3)' }}>No movements in this period.</span>}</td></tr>}
                  </React.Fragment>))}
                <tr style={{ background: 'var(--surface-2)', borderTop: '2px solid var(--border)', fontWeight: 700 }}><td colSpan={8}>Total</td><td style={{ ...right, ...mono }}>{fmtAUD(d.totals?.closing_value)}</td><td /></tr>
              </tbody>
            </table>
          </div>
          <Note warn={!d.control?.reconciled}>{d.control?.reconciled ? '✓ Item values add up to the Inventory account in the ledger.' : `⚠ Items differ from the ledger by ${fmtAUD(d.control?.difference)}.`} Click a row to see its movements.</Note>
        </div>)}
    </Body>
  </>)
}

// ── Budget Variance ───────────────────────────────────────────────────────────
const varColor = s => (s === 'favourable' ? '#16a34a' : s === 'unfavourable' ? '#dc2626' : 'var(--text-2)')
function BudgetVariance({ setExport }) {
  const r = useRange(); const [scenario, setScenario] = useState('Budget'); const [byMonth, setByMonth] = useState(false); const [busy, setBusy] = useState(false)
  const st = useReport(() => books.ledgerReport('budget-variance', { from: r.from, to: r.to, scenario, by_month: byMonth }), [])
  const { data } = st
  const [scen, setScen] = useState(['Budget'])
  useEffect(() => { books.getBudget({ scenario }).then(x => setScen(arr(x.data?.scenarios).length ? x.data.scenarios : ['Budget'])).catch(() => {}) }, [data])
  const rowsOf = d => [['Income', d.income], ['Cost of sales', d.cost_of_sales], ['Operating expenses', d.expenses], ['Other income', d.other_income], ['Other expenses', d.other_expenses]]
  useEffect(() => { if (data) setExport({ name: `budget-variance-${r.from}-${r.to}`, rows: [['Section', 'Account', 'Actual', 'Budget', 'Variance', 'Variance %'], ...rowsOf(data).flatMap(([s, sec]) => arr(sec?.rows).map(x => [s, `${x.code} ${x.name}`, x.actual, x.budget, x.variance, x.variance_pct])), ['', 'Net profit', data.net_profit?.actual, data.net_profit?.budget, data.net_profit?.variance, data.net_profit?.variance_pct]] }) }, [data])
  const generate = async () => {
    const fy = fyStart()
    if (!window.confirm(`Create a "${scenario}" budget for the year starting ${fy} from last year's actuals plus 8%? Existing lines for the same accounts and months are replaced.`)) return
    setBusy(true)
    try { const x = await books.generateBudget({ scenario, fy_start: fy, uplift_pct: 8 }); toast.success(`Budget created: ${x.data.lines} lines`); st.run() } catch (e) { toast.error(books.errMsg(e)) } finally { setBusy(false) }
  }
  const money4 = v => (num(v) === 0 && v !== 0 ? '' : fmtAUD(v))
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading}>
      <select className="select-compact" value={scenario} onChange={e => setScenario(e.target.value)}>{scen.map(s => <option key={s} value={s}>{s}</option>)}</select>
      <label className="text-sm"><input type="checkbox" checked={byMonth} onChange={e => setByMonth(e.target.checked)} /> Month by month</label>
    </RangeFilters>
    <Body state={st}>
      {d => (
        <div style={{ padding: 20 }}>
          {!d.has_budget && (
            <div style={{ padding: 16, marginBottom: 16, border: '1px dashed var(--border)', borderRadius: 'var(--r-lg)', background: 'var(--surface-2)', fontSize: '.84rem' }}>
              <strong>No “{d.scenario}” budget yet.</strong> Actuals are shown below against $0. Start from last year’s results plus 8% and adjust from there.
              <div style={{ marginTop: 10 }}><button className="btn btn-primary btn-sm" onClick={generate} disabled={busy}>{busy ? 'Creating…' : 'Create budget from last year'}</button></div></div>)}
          <StatGrid>
            <Stat label="Income — actual" value={fmtAUD(d.income?.actual)} sub={`Budget ${fmtAUD(d.income?.budget)}`} color="#16a34a" />
            <Stat label="Expenses — actual" value={fmtAUD(num(d.cost_of_sales?.actual) + num(d.expenses?.actual))} sub={`Budget ${fmtAUD(num(d.cost_of_sales?.budget) + num(d.expenses?.budget))}`} color="#dc2626" />
            <Stat label="Net profit — actual" value={fmtAUD(d.net_profit?.actual)} sub={`Budget ${fmtAUD(d.net_profit?.budget)}`} />
            <Stat label="Profit variance" value={fmtAUD(d.net_profit?.variance)} color={num(d.net_profit?.variance) >= 0 ? '#16a34a' : '#dc2626'} sub={d.net_profit?.variance_pct != null ? `${pctText(d.net_profit.variance_pct)} vs budget` : 'No budget to compare'} />
          </StatGrid>
          {byMonth && arr(d.trend).length > 1 && (
            <div style={{ height: 200, marginBottom: 16 }}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={arr(d.trend).map(t => ({ month: monthLabel(t.month), Actual: num(t.actual_profit), Budget: num(t.budget_profit) }))}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="month" fontSize={11} /><YAxis fontSize={11} tickFormatter={v => `${Math.round(v / 1000)}k`} /><Tooltip formatter={v => fmtAUD(v)} /><Legend />
              <Bar dataKey="Actual" fill="#2563eb" /><Line dataKey="Budget" stroke="#d97706" strokeWidth={2} dot={false} /></ComposedChart></ResponsiveContainer></div>)}
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table" style={{ fontSize: '.8rem' }}>
              <thead><tr><th>Account</th><th style={right}>Actual</th><th style={right}>Budget</th><th style={right}>Variance</th><th style={right}>%</th></tr></thead>
              <tbody>
                {rowsOf(d).map(([label, sec]) => arr(sec?.rows).length > 0 && (
                  <React.Fragment key={label}>
                    <tr><td colSpan={5} style={{ fontWeight: 700, fontSize: '.72rem', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.06em', paddingTop: 12 }}>{label}</td></tr>
                    {arr(sec.rows).map(x => (
                      <React.Fragment key={x.account_id}>
                        <tr><td>{x.code} · {x.name}{x.unbudgeted && <span style={{ marginLeft: 6, fontSize: '.62rem', padding: '1px 5px', borderRadius: 100, background: '#fef3c7', color: '#92400e', fontWeight: 700 }}>unbudgeted</span>}</td>
                          <td style={{ ...right, ...mono }}>{fmtAUD(x.actual)}</td><td style={{ ...right, ...mono }}>{money4(x.budget)}</td><td style={{ ...right, ...mono, fontWeight: 600, color: varColor(x.status) }}>{fmtAUD(x.variance)}</td><td style={{ ...right, color: varColor(x.status) }}>{pctText(x.variance_pct)}</td></tr>
                        {byMonth && arr(x.monthly).length > 0 && <tr><td colSpan={5} style={{ padding: '0 0 6px 24px', fontSize: '.7rem', color: 'var(--text-3)' }}>{arr(x.monthly).map(m => `${monthLabel(m.month)}: ${fmtAUD(m.actual)} / ${fmtAUD(m.budget)}`).join('   ·   ')}</td></tr>}
                      </React.Fragment>))}
                    <tr style={{ background: 'var(--surface-2)', fontWeight: 700 }}><td>Total {label.toLowerCase()}</td><td style={{ ...right, ...mono }}>{fmtAUD(sec.actual)}</td><td style={{ ...right, ...mono }}>{fmtAUD(sec.budget)}</td><td style={{ ...right, ...mono }}>{fmtAUD(sec.variance)}</td><td /></tr>
                  </React.Fragment>))}
                <tr style={{ borderTop: '2px solid var(--border)', fontWeight: 700 }}><td>Gross profit</td><td style={{ ...right, ...mono }}>{fmtAUD(d.gross_profit?.actual)}</td><td style={{ ...right, ...mono }}>{fmtAUD(d.gross_profit?.budget)}</td><td style={{ ...right, ...mono }}>{fmtAUD(d.gross_profit?.variance)}</td><td /></tr>
                <tr style={{ background: 'var(--surface-2)', fontWeight: 700 }}><td>Net profit</td><td style={{ ...right, ...mono }}>{fmtAUD(d.net_profit?.actual)}</td><td style={{ ...right, ...mono }}>{fmtAUD(d.net_profit?.budget)}</td><td style={{ ...right, ...mono, color: num(d.net_profit?.variance) >= 0 ? '#16a34a' : '#dc2626' }}>{fmtAUD(d.net_profit?.variance)}</td><td style={{ ...right }}>{pctText(d.net_profit?.variance_pct)}</td></tr>
              </tbody>
            </table>
          </div>
          <Note>{d.note} Green is favourable, red is unfavourable.</Note>
          {d.has_budget && <div style={{ marginTop: 10 }}><button className="btn btn-outline btn-xs" onClick={generate} disabled={busy}>Regenerate this year from last year + 8%</button></div>}
        </div>)}
    </Body>
  </>)
}

// ── Management Report ─────────────────────────────────────────────────────────
function ManagementReport({ setExport }) {
  const r = useRange()
  const st = useReport(() => books.ledgerReport('management-report', { from: r.from, to: r.to }), [])
  const { data } = st
  useEffect(() => {
    if (data) setExport({ name: `management-report-${r.from}-${r.to}`, rows: [['Measure', 'This period', 'Prior period'], ['Income', data.pl?.total_income, data.pl_prior?.total_income], ['Cost of sales', data.pl?.total_cost_of_sales, data.pl_prior?.total_cost_of_sales],
      ['Gross profit', data.pl?.gross_profit, data.pl_prior?.gross_profit], ['Operating expenses', data.pl?.total_expenses, data.pl_prior?.total_expenses], ['Net profit', data.pl?.net_profit, data.pl_prior?.net_profit], [],
      ...Object.entries(data.kpis || {}).map(([k, v]) => [k.replace(/_/g, ' '), v]), [], ['Total assets', data.balance_sheet?.total_assets], ['Total liabilities', data.balance_sheet?.total_liabilities], ['Net assets', data.balance_sheet?.net_assets]] })
  }, [data])
  const chg = (a, b) => { const x = num(a), y = num(b); if (!y) return '—'; const p = ((x - y) / Math.abs(y)) * 100; return `${p >= 0 ? '+' : ''}${p.toFixed(1)}%` }
  const lvl = { danger: ['#991b1b', '#fee2e2'], warning: ['#92400e', '#fef3c7'], info: ['#1e40af', '#dbeafe'] }
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading} />
    <Body state={st}>
      {d => {
        const k = d.kpis || {}; const pl = d.pl || {}; const p0 = d.pl_prior || {}
        const plRows = [['Income', 'total_income'], ['Cost of sales', 'total_cost_of_sales'], ['Gross profit', 'gross_profit', 1], ['Operating expenses', 'total_expenses'], ['Other income', 'total_other_income'], ['Other expenses', 'total_other_expenses'], ['Net profit / (loss)', 'net_profit', 1]]
        return (
          <div style={{ padding: 20 }}>
            <div style={{ marginBottom: 14 }}><div style={{ fontSize: '1.15rem', fontWeight: 700 }}>{d.organisation?.name}</div>
              <div style={{ fontSize: '.78rem', color: 'var(--text-3)' }}>Management report · {fmtDate(d.date_from)} to {fmtDate(d.date_to)} · compared with {fmtDate(d.prior?.date_from)} – {fmtDate(d.prior?.date_to)}</div></div>
            {arr(d.alerts).map((a, i) => { const [fg, bg] = lvl[a.level] || lvl.info; return <div key={i} style={{ padding: '7px 12px', marginBottom: 6, borderRadius: 'var(--r-md)', background: bg, color: fg, fontSize: '.8rem', fontWeight: 600 }}>{a.text}</div> })}
            <div style={{ height: 10 }} />
            <StatGrid>
              <Stat label="Income" value={fmtAUD(pl.total_income)} sub={`${chg(pl.total_income, p0.total_income)} vs prior`} color="#16a34a" />
              <Stat label="Net profit" value={fmtAUD(pl.net_profit)} sub={`${pctText(k.net_margin_pct)} margin`} color={num(pl.net_profit) >= 0 ? '#16a34a' : '#dc2626'} />
              <Stat label="Cash at bank" value={fmtAUD(k.cash_balance)} sub={`Net movement ${fmtAUD(k.net_cash_movement)}`} />
              <Stat label="Net assets" value={fmtAUD(d.balance_sheet?.net_assets)} sub={`Working capital ${fmtAUD(k.working_capital)}`} />
            </StatGrid>
            {arr(d.trend).length > 1 && <Panel title="12-month trend" accent="#2563eb"><div style={{ height: 240, padding: 8 }}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={arr(d.trend).map(t => ({ month: monthLabel(t.month), Income: num(t.income), Expenses: num(t.expenses), Profit: num(t.profit) }))}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="month" fontSize={11} /><YAxis fontSize={11} tickFormatter={v => `${Math.round(v / 1000)}k`} /><Tooltip formatter={v => fmtAUD(v)} /><Legend />
              <Bar dataKey="Income" fill="#16a34a" /><Bar dataKey="Expenses" fill="#f59e0b" /><Line dataKey="Profit" stroke="#2563eb" strokeWidth={2} dot={false} /></ComposedChart></ResponsiveContainer></div></Panel>}
            <div style={{ height: 16 }} />
            <Cols2>
              <Panel title="Profit & loss" accent="#16a34a">
                <table className="data-table" style={{ fontSize: '.8rem' }}><thead><tr><th /><th style={right}>This period</th><th style={right}>Prior</th><th style={right}>Change</th></tr></thead><tbody>
                  {plRows.map(([l, key, strong]) => <tr key={key} style={strong ? { fontWeight: 700, background: 'var(--surface-2)' } : undefined}><td>{l}</td><td style={{ ...right, ...mono }}>{fmtAUD(pl[key])}</td><td style={{ ...right, ...mono }}>{fmtAUD(p0[key])}</td><td style={right}>{chg(pl[key], p0[key])}</td></tr>)}</tbody></table>
              </Panel>
              <Panel title="Key ratios" accent="#7c3aed">
                {[['Gross margin', pctText(k.gross_margin_pct)], ['Net margin', pctText(k.net_margin_pct)], ['Expenses as % of income', pctText(k.expense_ratio_pct)], ['Current ratio', k.current_ratio ?? '—'], ['Quick ratio', k.quick_ratio ?? '—'],
                  ['Debtor days', k.debtor_days ?? '—'], ['Creditor days', k.creditor_days ?? '—'], ['Income growth vs prior', pctText(k.income_change_pct)], ['Profit change vs prior', fmtAUD(k.profit_change)]].map(([l, v]) => (
                  <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 14px', borderBottom: '1px solid var(--border)', fontSize: '.8rem' }}><span style={{ color: 'var(--text-2)' }}>{l}</span><strong style={mono}>{v}</strong></div>))}
              </Panel>
            </Cols2>
            <Cols2>
              <Panel title="Balance sheet" accent="#2563eb"><R account="Total assets" amount={d.balance_sheet?.total_assets} /><R account="Total liabilities" amount={d.balance_sheet?.total_liabilities} /><Tot label="Net assets" amount={d.balance_sheet?.net_assets} strong bg />
                <R account="GST payable for the period (1A − 1B)" amount={d.gst?.net_gst_payable} /></Panel>
              <Panel title="Cash" accent="#0891b2"><R account="Opening cash" amount={d.cash?.opening} /><R account="Cash received" amount={d.cash?.receipts} /><R account="Cash paid" amount={d.cash?.payments} /><Tot label="Closing cash" amount={d.cash?.closing} strong bg /></Panel>
            </Cols2>
            <Cols2>
              {[['Receivables', d.aged_receivables, '#d97706'], ['Payables', d.aged_payables, '#dc2626']].map(([t, a, c]) => (
                <Panel key={t} title={`${t} — ${fmtAUD(a?.total)}`} accent={c}>
                  <Tbl dense rows={Object.entries(a?.buckets || {}).map(([b, v]) => ({ b, v }))} keyOf={x => x.b} cols={[{ h: 'Age', f: x => (x.b === 'current' ? 'Current' : `${x.b} days`) }, { h: 'Amount', k: 'v', money: true }]} />
                  {arr(a?.top).length > 0 && <div style={{ padding: '6px 14px', fontSize: '.72rem', color: 'var(--text-3)' }}>Largest: {arr(a.top).map(x => `${x.contact} ${fmtAUD(x.total)}`).join(' · ')}</div>}
                </Panel>))}
            </Cols2>
            <Cols2>
              <Panel title="Top customers" accent="#16a34a"><Tbl dense keyOf={x => x.contact_id} rows={d.top_customers} cols={[{ h: 'Customer', k: 'contact' }, { h: 'Gross', k: 'gross', money: true }]} /></Panel>
              <Panel title="Top suppliers" accent="#f59e0b"><Tbl dense keyOf={x => x.contact_id} rows={d.top_suppliers} cols={[{ h: 'Supplier', k: 'contact' }, { h: 'Gross', k: 'gross', money: true }]} /></Panel>
            </Cols2>
            <Note>Everything in this pack is computed from your posted ledger journals and sub-ledgers. Print or save as PDF with the button above.</Note>
          </div>)
      }}
    </Body>
  </>)
}


// ── General Ledger (detailed) ─────────────────────────────────────────────────
const GL_GROUPS = [['account', 'Account'], ['voucher', 'Journal (voucher)'], ['party', 'Party'], ['tracking', 'Tracking option'], ['source', 'Source'], ['month', 'Month'], ['none', 'No grouping']]
function GeneralLedgerDetail({ setExport }) {
  const r = useRange()
  const [f, setF] = useState({ group_by: 'account', accounts: [], contact: '', tracking: '', source: '', q: '', min: '', max: '', consolidate: false, reversed: true })
  const [accs, setAccs] = useState([]); const [cats, setCats] = useState([]); const [sources, setSources] = useState([])
  useEffect(() => {
    import('../../lib/platformApi.js').then(api => {
      api.accounts(true).then(x => setAccs(arr(x.data))).catch(() => {})
      api.tracking().then(x => setCats(arr(x.data))).catch(() => {})
      api.journalSources().then(x => setSources(arr(x.data?.items))).catch(() => {})
    })
  }, [])
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const params = () => ({ from: r.from, to: r.to, group_by: f.group_by, account_ids: f.accounts.length ? f.accounts.map(Number) : undefined, contact: f.contact || undefined,
    tracking_option_ids: f.tracking ? [Number(f.tracking)] : undefined, source_type: f.source || undefined, q: f.q || undefined, min_amount: f.min || undefined, max_amount: f.max || undefined,
    consolidate: f.consolidate, include_reversed: f.reversed })
  const st = useReport(() => books.ledgerReportMulti('general-ledger-detail', params()), [])
  const { data } = st
  useEffect(() => {
    if (data) setExport({ name: `general-ledger-${r.from}-${r.to}`, rows: [['Group', 'Date', 'Journal', 'Account', 'Description', 'Reference', 'Party', 'Source', 'Tracking', 'Debit', 'Credit', 'Balance'],
      ...arr(data.groups).flatMap(g => arr(g.rows).map(x => [g.label, x.date, x.journal_no, x.account, x.description, x.reference, x.contact, x.source_type, arr(x.tracking).join('; '), x.debit, x.credit, x.balance]))] })
  }, [data])
  const opts = arr(cats).flatMap(c => arr(c.options).map(o => ({ id: o.id, label: `${c.name}: ${o.name}` })))
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading}>
      <select aria-label="Group by" className="select-compact" value={f.group_by} onChange={e => set('group_by', e.target.value)}>{GL_GROUPS.map(([k, l]) => <option key={k} value={k}>Group by {l}</option>)}</select>
      <select aria-label="Accounts" multiple size={3} className="input input-sm" style={{ maxWidth: 230 }} value={f.accounts} onChange={e => set('accounts', Array.from(e.target.selectedOptions).map(o => o.value))}>{accs.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select>
      <input aria-label="Party" className="input input-sm" style={{ width: 120 }} placeholder="Party…" value={f.contact} onChange={e => set('contact', e.target.value)} />
      <select aria-label="Tracking option" className="select-compact" value={f.tracking} onChange={e => set('tracking', e.target.value)}><option value="">Any tracking</option>{opts.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}</select>
      <select aria-label="Source" className="select-compact" value={f.source} onChange={e => set('source', e.target.value)}><option value="">Any source</option>{sources.map(s => <option key={s.source} value={s.source}>{s.label}</option>)}</select>
      <input aria-label="Search" className="input input-sm" style={{ width: 130 }} placeholder="Search text…" value={f.q} onChange={e => set('q', e.target.value)} />
      <input aria-label="Min" className="input input-sm" style={{ width: 70 }} placeholder="Min $" value={f.min} onChange={e => set('min', e.target.value)} /><input aria-label="Max" className="input input-sm" style={{ width: 70 }} placeholder="Max $" value={f.max} onChange={e => set('max', e.target.value)} />
      <label className="text-sm"><input type="checkbox" checked={f.consolidate} onChange={e => set('consolidate', e.target.checked)} /> Consolidate</label>
      <label className="text-sm"><input type="checkbox" checked={f.reversed} onChange={e => set('reversed', e.target.checked)} /> Include reversed</label>
    </RangeFilters>
    <Body state={st} emptyWhen={d => !arr(d.groups).length} empty={<EmptyState title="No ledger lines match" detail="Widen the dates or clear some filters." />}>
      {d => (
        <div style={{ padding: 8 }}>
          <div style={{ padding: '2px 6px 8px', fontSize: '.76rem', color: 'var(--text-2)' }}><strong>{d.line_count} lines</strong> in {d.group_count} group(s) · debits {fmtAUD(d.total_debit)} · credits {fmtAUD(d.total_credit)}</div>
          {arr(d.groups).map(g => (
            <Sec key={g.key} label={`${g.label} (${g.count})`} total={num(g.closing ?? g.net)} accent="#2563eb" open={d.group_count <= 3}>
              {g.opening != null && <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 14px', fontSize: '.78rem', fontWeight: 600 }}><span>Opening balance</span><span style={mono}>{fmtAUD(g.opening)}</span></div>}
              <Tbl dense keyOf={(x, i) => i} rows={g.rows} cols={[{ h: 'Date', f: x => fmtDate(x.date) }, { h: 'Journal', k: 'journal_no', mono: true }, ...(d.group_by === 'account' ? [] : [{ h: 'Account', k: 'account' }]),
                { h: 'Description', k: 'description' }, { h: 'Ref', k: 'reference', mono: true }, { h: 'Party', k: 'contact' }, { h: 'Tracking', f: x => arr(x.tracking).join(', ') },
                { h: 'Debit', f: x => (num(x.debit) ? x.debit : ''), money: true }, { h: 'Credit', f: x => (num(x.credit) ? x.credit : ''), money: true }, { h: 'Balance', k: 'balance', money: true, bold: true }]} />
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 14px', fontSize: '.78rem', fontWeight: 700, background: 'var(--surface-2)' }}>
                <span>{g.closing != null ? 'Closing balance' : 'Group net (debit − credit)'}</span><span style={mono}>Dr {fmtAUD(g.debit)} · Cr {fmtAUD(g.credit)} · {fmtAUD(g.closing ?? g.net)}</span></div>
            </Sec>))}
          {d.truncated && <Note warn>Showing the first {d.limit} lines — narrow the filters to see the rest.</Note>}
          <Note warn={d.balanced === false}>{d.balanced === true ? '✓ Debits equal credits across the whole ledger for this period.' : ''} {d.note}</Note>
        </div>)}
    </Body>
  </>)
}

// ── Profit & Loss by tracking option ──────────────────────────────────────────
function ProfitLossByTracking({ setExport }) {
  const r = useRange()
  const [cats, setCats] = useState([]); const [cat, setCat] = useState('')
  useEffect(() => { import('../../lib/platformApi.js').then(api => api.tracking().then(x => { const l = arr(x.data); setCats(l); if (l.length) setCat(String(l[0].id)) }).catch(() => {})) }, [])
  const st = useReport(() => (cat ? books.ledgerReport('profit-loss-by-tracking', { from: r.from, to: r.to, category_id: Number(cat) }) : Promise.resolve({ data: { noCategory: true } })), [cat])
  const { data } = st
  useEffect(() => {
    if (data?.columns) setExport({ name: `profit-loss-by-${(data.category?.name || 'tracking').toLowerCase()}-${r.from}-${r.to}`, rows: [['Section', 'Code', 'Account', ...data.columns.map(c => c.name), 'Total'],
      ...arr(data.sections).flatMap(s => [...arr(s.rows).map(x => [s.label, x.code, x.name, ...data.columns.map(c => x.amounts[c.key]), x.total]), [s.label, '', `Total ${s.label}`, ...data.columns.map(c => s.totals[c.key]), s.totals.total]]),
      ['', '', 'Net profit', ...data.columns.map(c => data.net_profit[c.key]), data.net_profit.total]] })
  }, [data])
  const th = { textAlign: 'right', padding: '6px 8px', fontSize: '.72rem', whiteSpace: 'nowrap' }
  const td = { textAlign: 'right', padding: '4px 8px', fontSize: '.78rem', ...mono }
  return (<>
    <RangeFilters r={r} run={st.run} busy={st.loading}>
      <select aria-label="Tracking category" className="select-compact" value={cat} onChange={e => setCat(e.target.value)}>{cats.map(c => <option key={c.id} value={c.id}>By {c.name}</option>)}</select>
    </RangeFilters>
    {!cats.length ? <EmptyState title="No tracking categories yet" detail="Create a tracking category (for example Department or Job) under Settings, tag your transactions, and this report splits profit by each option." /> : (
      <Body state={st} emptyWhen={d => d.noCategory || !arr(d.sections).some(s => arr(s.rows).length)} empty={<EmptyState title="No income or expenses in this period" detail="Try a wider date range." />}>
        {d => (
          <div style={{ padding: 8, overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid="pl-tracking">
              <thead><tr style={{ borderBottom: '2px solid var(--border)' }}><th style={{ ...th, textAlign: 'left' }}>Account</th>{d.columns.map(c => <th key={c.key} style={th}>{c.name}</th>)}<th style={{ ...th, fontWeight: 800 }}>Total</th></tr></thead>
              <tbody>
                {arr(d.sections).filter(s => arr(s.rows).length).map(s => (
                  <React.Fragment key={s.key}>
                    <tr><td colSpan={d.columns.length + 2} style={{ padding: '10px 8px 2px', fontWeight: 700, fontSize: '.78rem', color: 'var(--text-2)' }}>{s.label}</td></tr>
                    {arr(s.rows).map(x => (<tr key={x.account_id}><td style={{ padding: '4px 8px', fontSize: '.78rem' }}>{x.code} · {x.name}</td>{d.columns.map(c => <td key={c.key} style={td}>{num(x.amounts[c.key]) ? fmtAUD(x.amounts[c.key]) : ''}</td>)}<td style={{ ...td, fontWeight: 700 }}>{fmtAUD(x.total)}</td></tr>))}
                    <tr style={{ background: 'var(--surface-2)', fontWeight: 700 }}><td style={{ padding: '4px 8px', fontSize: '.78rem' }}>Total {s.label}</td>{d.columns.map(c => <td key={c.key} style={td}>{fmtAUD(s.totals[c.key])}</td>)}<td style={td}>{fmtAUD(s.totals.total)}</td></tr>
                  </React.Fragment>))}
                {[['Gross profit', d.gross_profit], ['Operating profit', d.operating_profit], ['Net profit', d.net_profit]].map(([l, v]) => (
                  <tr key={l} style={{ borderTop: l === 'Net profit' ? '2px solid var(--border)' : undefined, fontWeight: 800 }}><td style={{ padding: '6px 8px', fontSize: '.8rem' }}>{l}</td>{d.columns.map(c => <td key={c.key} style={{ ...td, color: num(v[c.key]) < 0 ? 'var(--danger)' : undefined }}>{fmtAUD(v[c.key])}</td>)}<td style={td}>{fmtAUD(v.total)}</td></tr>))}
              </tbody>
            </table>
            <Note warn={!d.matches_profit_loss}>{d.matches_profit_loss ? '✓ The columns add up to the ordinary Profit & Loss for the same period.' : `The columns do not add up to the ordinary Profit & Loss (${fmtAUD(d.profit_loss_net)}) - please report this.`} “Unassigned” holds lines with no {d.category?.name} tag; a line tagged with several options is shared equally.</Note>
          </div>)}
      </Body>)}
  </>)
}

export const EXTRA_BODIES = {
  pl_tracking: p => <ProfitLossByTracking {...p} />,
  general_ledger: p => <GeneralLedgerDetail {...p} />,
  gl_summary: p => <GLSummary {...p} />,
  journal_report: p => <JournalReport {...p} />,
  cash_summary: p => <CashSummary {...p} />,
  account_summary: p => <AccountSummary {...p} />,
  bank_recon: p => <BankRecon {...p} />,
  cash_validation: p => <CashValidation {...p} />,
  expense_claims: p => <ExpenseClaimsReport {...p} />,
  payg_summary: p => <PaygSummary {...p} />,
  inventory_items: p => <InventoryItems {...p} />,
  budget_variance: p => <BudgetVariance {...p} />,
  management_report: p => <ManagementReport {...p} />,
}
