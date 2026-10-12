/**
 * FinancialReports - grouped report menu (Xero-style) for the current ORGANISATION.
 *
 * Every report is computed from the organisation's posted ledger journals and its sales/purchase
 * documents (the /ledger, /sales and /purchases APIs), not from the old single-user tables.
 * Each report renders inside its own error boundary and never assumes a field exists, so one bad
 * response shows an inline message instead of taking the whole page down.
 */
import React, { useEffect, useMemo, useState, useCallback } from 'react'
import { Download, ChevronDown, ChevronRight, Printer } from 'lucide-react'
import * as ledger__0 from '../lib/ledgerApi.js'
import * as ledger__1 from '../../../core/lib/platformApi.js'
import * as books from '../lib/booksApi.js'
import * as legacy from '../../../core/lib/api.js'
import { num, fmtAUD, fmtPct, fmtDate, iso, todayISO, fyStart, arr, sum, Sec, R, Rows, Tot, GH, EmptyState, ReportLoading, Note, Badge, Filters, DateField, useReport, ErrorState, ReportBoundary } from './reportKit.jsx'
import { EXTRA_BODIES } from './ExtraReports.jsx'

// ── report menu (same groups as before; more reports are now live) ────────────
const MENU = [
  { group: '📈 Financial Performance', color: '#16a34a', items: [
    { key: 'executive_summary', label: 'Executive Summary',   live: true,  desc: 'Cash, profitability and balance sheet KPIs at a glance' },
    { key: 'pl',                label: 'Profit & Loss',       live: true,  desc: 'Income, expenses and net profit for a period' },
    { key: 'pl_tracking',       label: 'Tracking Profit & Loss', live: true, desc: 'Profit split by job, department or region - one column per tracking option' },
    { key: 'budget_variance',   label: 'Budget Variance',     live: true, desc: 'Actual vs budget for income and expenses' },
    { key: 'cash_summary',      label: 'Cash Summary',        live: true, desc: 'Movement of cash in and out for the period' },
  ]},
  { group: '📋 Financial Statements', color: '#2563eb', items: [
    { key: 'balance_sheet',     label: 'Balance Sheet',       live: true,  desc: 'Assets, liabilities and equity at a point in time' },
    { key: 'cash_flow',         label: 'Cash Flow Statement', live: true,  desc: 'Operating, investing and financing cash flows' },
    { key: 'management_report', label: 'Management Report',   live: true, desc: 'P&L + Balance Sheet + Aged reports combined' },
  ]},
  { group: '💳 Payables & Receivables', color: '#d97706', items: [
    { key: 'aged_receivables',  label: 'Aged Receivables',    live: true,  desc: 'Customer invoices by how long they are overdue' },
    { key: 'aged_payables',     label: 'Aged Payables',       live: true,  desc: 'Supplier bills by how long they are overdue' },
    { key: 'invoice_summary',   label: 'Invoice Summary',     live: true,  desc: 'All sales invoices with status and amounts' },
    { key: 'by_customer',       label: 'Sales by Customer',   live: true,  desc: 'Invoiced net, GST and gross per customer' },
    { key: 'by_supplier',       label: 'Purchases by Supplier', live: true, desc: 'Billed net, GST and gross per supplier' },
    { key: 'expense_claims',    label: 'Expense Claims',      live: true, desc: 'Summary of submitted and approved expense claims' },
  ]},
  { group: '🏛 Taxes & Balances', color: '#7c3aed', items: [
    { key: 'gst_bas',           label: 'GST / BAS Report',    live: true,  desc: 'GST collected and paid — BAS ready (Australia)' },
    { key: 'trial_balance',     label: 'Trial Balance',       live: true,  desc: 'All GL account balances — debits equal credits' },
    { key: 'gl_summary',        label: 'General Ledger Summary', live: true, desc: 'All account balances and movements for the period' },
    { key: 'payg_summary',      label: 'PAYG Summary',        live: true, desc: 'PAYG withholding for BAS lodgement' },
  ]},
  { group: '🏦 Reconciliation', color: '#0891b2', items: [
    { key: 'control_check',     label: 'Sub-ledger Control Check', live: true, desc: 'Invoices and bills agree with the AR / AP control accounts' },
    { key: 'bank_recon',        label: 'Bank Reconciliation', live: true, desc: 'AccFino records vs bank statement balances' },
    { key: 'account_summary',   label: 'Account Summary',     live: true, desc: 'Monthly account activity for all bank accounts' },
    { key: 'cash_validation',   label: 'Cash Validation',     live: true, desc: 'Identify duplicate or unusual transactions' },
  ]},
  { group: '📝 Transactions', color: '#6b7280', items: [
    { key: 'general_ledger',    label: 'General Ledger (detailed)', live: true, desc: 'Every posting line, filtered by account, party, tracking or source, grouped your way' },
    { key: 'account_transactions', label: 'Account Transactions', live: true, desc: 'All transactions for a selected GL account' },
    { key: 'journal_report',    label: 'Journal Report',      live: true, desc: 'All journal entries posted for the period' },
    { key: 'inventory_items',   label: 'Inventory Item Details', live: true, desc: 'Inventory quantities, values and movements' },
  ]},
]
const ALL_ITEMS = MENU.flatMap(g => g.items)
const FREE_REPORTS = new Set(['pl', 'balance_sheet'])

// ── Profit & Loss ─────────────────────────────────────────────────────────────
function PLReport({ setExport }) {
  const [from, setFrom] = useState(fyStart()); const [to, setTo] = useState(todayISO())
  const { data, loading, error, run } = useReport(() => ledger__0.profitLoss(from, to), [])
  useEffect(() => {
    if (data) setExport({ name: `profit-loss-${from}-${to}`, rows: [['Section', 'Account', 'Amount'],
      ...[['Income', data.income], ['Cost of Sales', data.cost_of_sales], ['Operating Expenses', data.expenses], ['Other Income', data.other_income], ['Other Expenses', data.other_expenses]]
        .flatMap(([s, rs]) => arr(rs).map(r => [s, `${r.code} ${r.name}`, r.amount])), ['', 'Net Profit', data.net_profit]] })
  }, [data])
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="From" value={from} onChange={setFrom} /><DateField label="To" value={to} onChange={setTo} /></Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : (
      <div style={{ padding: 8 }}>
        <Sec label="Trading Income" total={num(data.total_income)} accent="#16a34a"><Rows rows={data.income} /></Sec>
        <Sec label="Cost of Sales" total={num(data.total_cost_of_sales)} accent="#dc2626"><Rows rows={data.cost_of_sales} /></Sec>
        <Tot label="Gross Profit" amount={data.gross_profit} strong bg />
        <Sec label="Operating Expenses" total={num(data.total_expenses)} accent="#d97706" open={false}><Rows rows={data.expenses} /></Sec>
        {arr(data.other_income).length > 0 && <Sec label="Other Income" total={num(data.total_other_income)} accent="#0891b2" open={false}><Rows rows={data.other_income} /></Sec>}
        {arr(data.other_expenses).length > 0 && <Sec label="Other Expenses" total={num(data.total_other_expenses)} accent="#7c3aed" open={false}><Rows rows={data.other_expenses} /></Sec>}
        <Tot label="Net Profit / (Loss)" amount={data.net_profit} strong bg />
        {!arr(data.income).length && !arr(data.expenses).length && !arr(data.cost_of_sales).length &&
          <Note>No income or expense has been posted in this period. Post journals, approve invoices/bills, or sync bank transactions from the Ledger tab.</Note>}
      </div>)}
  </>)
}

// ── Balance Sheet ─────────────────────────────────────────────────────────────
const BS_LABEL = { bank: 'Bank', current_asset: 'Current Assets', inventory: 'Inventory', fixed_asset: 'Fixed Assets', non_current_asset: 'Non-current Assets',
  credit_card: 'Credit Cards', current_liability: 'Current Liabilities', non_current_liability: 'Non-current Liabilities' }
const BS_COLOR = { bank: '#2563eb', current_asset: '#0891b2', inventory: '#0891b2', fixed_asset: '#7c3aed', non_current_asset: '#7c3aed',
  credit_card: '#dc2626', current_liability: '#dc2626', non_current_liability: '#b91c1c' }
function BSReport({ setExport }) {
  const [asAt, setAsAt] = useState(todayISO())
  const { data, loading, error, run } = useReport(() => ledger__0.balanceSheet(asAt), [])
  useEffect(() => {
    if (data) setExport({ name: `balance-sheet-${asAt}`, rows: [['Group', 'Account', 'Amount'],
      ...Object.entries({ ...(data.assets || {}), ...(data.liabilities || {}) }).flatMap(([g, rs]) => arr(rs).map(r => [BS_LABEL[g] || g, `${r.code} ${r.name}`, r.amount])),
      ...arr(data.equity).map(r => ['Equity', `${r.code} ${r.name}`, r.amount]),
      ['Equity', 'Retained earnings (prior years)', data.retained_earnings_prior_years], ['Equity', 'Current year earnings', data.current_year_earnings]] })
  }, [data])
  const groupSecs = obj => Object.entries(obj || {}).filter(([, rs]) => arr(rs).length > 0)
    .map(([g, rs]) => <Sec key={g} label={BS_LABEL[g] || g} total={sum(rs)} accent={BS_COLOR[g]} open={g === 'bank'}><Rows rows={rs} /></Sec>)
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="As at" value={asAt} onChange={setAsAt} /></Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : (
      <div style={{ padding: 8 }}>
        <GH label="Assets" />{groupSecs(data.assets)}<Tot label="Total Assets" amount={data.total_assets} strong bg />
        <GH label="Liabilities" />{groupSecs(data.liabilities)}<Tot label="Total Liabilities" amount={data.total_liabilities} strong bg />
        <Tot label="Net Assets" amount={data.net_assets} strong />
        <GH label="Equity" />
        {arr(data.equity).length > 0 && <Sec label="Equity accounts" total={sum(data.equity)} accent="#16a34a"><Rows rows={data.equity} /></Sec>}
        <R account="Retained earnings (prior years)" amount={data.retained_earnings_prior_years} />
        <R account={`Current year earnings (from ${fmtDate(data.financial_year_start)})`} amount={data.current_year_earnings} />
        <Tot label="Total Equity" amount={data.total_equity} strong bg />
        <Note warn={!data.balanced}>{data.balanced ? '✓ Net assets equal total equity.' : '⚠ Balance sheet does not balance — check for unbalanced imports and contact support.'}</Note>
      </div>)}
  </>)
}

// ── Trial Balance ─────────────────────────────────────────────────────────────
function TrialBalance({ setExport }) {
  const [asAt, setAsAt] = useState(todayISO())
  const { data, loading, error, run } = useReport(() => ledger__0.trialBalance(asAt), [])
  useEffect(() => { if (data) setExport({ name: `trial-balance-${asAt}`, rows: [['Code', 'Account', 'Debit', 'Credit'], ...arr(data.rows).map(r => [r.code, r.name, r.debit, r.credit])] }) }, [data])
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="As at" value={asAt} onChange={setAsAt} /></Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : (
      <div style={{ overflowX: 'auto', padding: 8 }}>
        <table className="data-table" style={{ fontSize: '.81rem' }}>
          <thead><tr><th>Code</th><th>Account</th><th style={{ textAlign: 'right' }}>Debit</th><th style={{ textAlign: 'right' }}>Credit</th></tr></thead>
          <tbody>
            {arr(data.rows).map((r, i) => (
              <tr key={r.account_id ?? i}><td style={{ fontFamily: 'var(--font-mono)' }}>{r.code}</td><td>{r.name}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{num(r.debit) ? fmtAUD(r.debit) : ''}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{num(r.credit) ? fmtAUD(r.credit) : ''}</td></tr>))}
            <tr style={{ background: 'var(--surface-2)', borderTop: '2px solid var(--border)' }}><td colSpan={2} style={{ fontWeight: 700 }}>Total</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(data.total_debit)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(data.total_credit)}</td></tr>
          </tbody>
        </table>
        <Note warn={!data.balanced}>{data.balanced ? '✓ Debits equal credits.' : '⚠ Trial balance does not balance.'}</Note>
      </div>)}
  </>)
}

// ── Cash Flow ─────────────────────────────────────────────────────────────────
function CashFlow({ setExport }) {
  const [from, setFrom] = useState(fyStart()); const [to, setTo] = useState(todayISO())
  const { data, loading, error, run } = useReport(() => books.ledgerReport('cash-flow', { from, to }), [])
  useEffect(() => {
    if (data) setExport({ name: `cash-flow-${from}-${to}`, rows: [['Section', 'Item', 'Amount'], ['Operating', 'Net profit', data.operating?.net_profit],
      ...arr(data.operating?.adjustments).map(a => ['Operating', a.label, a.amount]), ...arr(data.investing?.items).map(a => ['Investing', a.label, a.amount]),
      ...arr(data.financing?.items).map(a => ['Financing', a.label, a.amount]), ['', 'Net change in cash', data.net_change_in_cash], ['', 'Opening cash', data.opening_cash], ['', 'Closing cash', data.closing_cash]] })
  }, [data])
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="From" value={from} onChange={setFrom} /><DateField label="To" value={to} onChange={setTo} /></Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : (
      <div style={{ padding: 8 }}>
        <Sec label="Operating activities" total={num(data.operating?.total)} accent="#16a34a">
          <R account="Net profit" amount={data.operating?.net_profit} />
          {arr(data.operating?.adjustments).map((a, i) => <R key={i} account={a.label} amount={a.amount} />)}
        </Sec>
        <Sec label="Investing activities" total={num(data.investing?.total)} accent="#7c3aed" open={arr(data.investing?.items).length > 0}>
          {arr(data.investing?.items).map((a, i) => <R key={i} account={a.label} amount={a.amount} />)}</Sec>
        <Sec label="Financing activities" total={num(data.financing?.total)} accent="#d97706" open={arr(data.financing?.items).length > 0}>
          {arr(data.financing?.items).map((a, i) => <R key={i} account={a.label} amount={a.amount} />)}</Sec>
        <Tot label="Net change in cash" amount={data.net_change_in_cash} strong bg />
        <R account="Opening cash" amount={data.opening_cash} /><R account="Closing cash" amount={data.closing_cash} />
        <Note warn={!data.reconciled}>{data.reconciled ? '✓ Reconciles to the movement in bank accounts.' : `⚠ Off by ${fmtAUD(data.difference)}. ${data.note || ''}`}</Note>
      </div>)}
  </>)
}

// ── Aged Receivables / Payables ───────────────────────────────────────────────
function Aged({ side, setExport }) {
  const [asAt, setAsAt] = useState(todayISO())
  const fetcher = () => (side === 'sales' ? books.salesReport('aged-receivables', { as_at: asAt }) : books.purchasesReport('aged-payables', { as_at: asAt }))
  const { data, loading, error, run } = useReport(fetcher, [side])
  const who = side === 'sales' ? 'Customer' : 'Supplier'
  const H = [who, 'Current', '1–30 days', '31–60 days', '61–90 days', '90+ days', 'Total']
  const K = ['current', '1-30', '31-60', '61-90', '90+']
  useEffect(() => { if (data) setExport({ name: `aged-${side}-${asAt}`, rows: [H, ...arr(data.contacts).map(c => [c.contact, ...K.map(k => c[k]), c.total]), ['Total', ...K.map(k => data.buckets?.[k]), data.total]] }) }, [data])
  const color = ['#16a34a', '#d97706', '#dc2626', '#7c3aed', '#7c3aed']
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="As at" value={asAt} onChange={setAsAt} />
      {data?.control && <Badge ok={data.control.reconciled} yes="Reconciles to the ledger" no={`Off by ${fmtAUD(data.control.difference)}`} />}</Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : !arr(data.contacts).length ? (
      <EmptyState title={side === 'sales' ? 'No outstanding receivables' : 'No outstanding payables'}
        detail={side === 'sales' ? 'Approved invoices that are not fully paid appear here.' : 'Approved bills that are not fully paid appear here.'} />
    ) : (
      <div style={{ overflowX: 'auto', padding: 8 }}>
        <table className="data-table" style={{ fontSize: '.81rem' }}>
          <thead><tr>{H.map(h => <th key={h} style={{ textAlign: h === who ? 'left' : 'right' }}>{h}</th>)}</tr></thead>
          <tbody>
            {arr(data.contacts).map((c, i) => (
              <tr key={c.contact_id ?? i}><td style={{ fontWeight: 600 }}>{c.contact}</td>
                {K.map((k, j) => <td key={k} style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', color: num(c[k]) ? color[j] : 'var(--text-3)' }}>{num(c[k]) ? fmtAUD(c[k]) : '—'}</td>)}
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(c.total)}</td></tr>))}
            <tr style={{ background: 'var(--surface-2)', borderTop: '2px solid var(--border)' }}><td style={{ fontWeight: 700 }}>Total</td>
              {K.map(k => <td key={k} style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(data.buckets?.[k])}</td>)}
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(data.total)}</td></tr>
          </tbody>
        </table>
      </div>)}
  </>)
}

// ── Invoice Summary ───────────────────────────────────────────────────────────
function InvoiceSummary({ setExport }) {
  const [from, setFrom] = useState(fyStart()); const [to, setTo] = useState(todayISO())
  const { data, loading, error, run } = useReport(() => books.listDocs('sales', 'main', { from, to, limit: 500 }), [])
  const docs = arr(data?.items)
  useEffect(() => { if (data) setExport({ name: `invoice-summary-${from}-${to}`, rows: [['Invoice #', 'Customer', 'Date', 'Due', 'Subtotal', 'GST', 'Total', 'Due amount', 'Status'],
    ...docs.map(d => [d.number, d.contact, d.issue_date, d.due_date, d.subtotal, d.tax_total, d.total, d.amount_due, d.status])] }) }, [data])
  const SC = { draft: 'var(--text-3)', approved: '#2563eb', paid: '#16a34a', void: '#6b7280' }
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="From" value={from} onChange={setFrom} /><DateField label="To" value={to} onChange={setTo} /></Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : !docs.length ? <EmptyState title="No invoices in this period" detail="Create invoices in the Sales tab." /> : (
      <div style={{ overflowX: 'auto', padding: 8 }}>
        <table className="data-table" style={{ fontSize: '.8rem' }}>
          <thead><tr><th>Invoice #</th><th>Customer</th><th>Date</th><th>Due</th><th style={{ textAlign: 'right' }}>Subtotal</th><th style={{ textAlign: 'right' }}>GST</th>
            <th style={{ textAlign: 'right' }}>Total</th><th style={{ textAlign: 'right' }}>Owing</th><th>Status</th></tr></thead>
          <tbody>
            {docs.map(d => (
              <tr key={d.id}><td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{d.number}</td><td>{d.contact || '—'}</td><td>{fmtDate(d.issue_date)}</td><td>{fmtDate(d.due_date)}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmtAUD(d.subtotal)}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', color: '#7c3aed' }}>{fmtAUD(d.tax_total)}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(d.total)}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{d.status === 'approved' ? fmtAUD(d.amount_due) : '—'}</td>
                <td><span style={{ padding: '2px 8px', borderRadius: 100, fontSize: '.7rem', fontWeight: 700, color: SC[d.status] || 'var(--text-3)', background: 'var(--surface-2)' }}>{d.status}</span></td></tr>))}
          </tbody>
        </table>
        {data.total > docs.length && <Note>Showing the latest {docs.length} of {data.total} invoices — narrow the date range to see the rest.</Note>}
      </div>)}
  </>)
}

// ── Sales by customer / Purchases by supplier ─────────────────────────────────
function ByContact({ side, setExport }) {
  const [from, setFrom] = useState(fyStart()); const [to, setTo] = useState(todayISO())
  const fetcher = () => (side === 'sales' ? books.salesReport('by-customer', { from, to }) : books.purchasesReport('by-supplier', { from, to }))
  const { data, loading, error, run } = useReport(fetcher, [side])
  const rows = arr(data?.rows); const who = side === 'sales' ? 'Customer' : 'Supplier'
  useEffect(() => { if (data) setExport({ name: `${side}-by-contact-${from}-${to}`, rows: [[who, 'Net', 'GST', 'Gross', 'Documents'], ...rows.map(r => [r.contact, r.net, r.gst, r.gross, r.documents])] }) }, [data])
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="From" value={from} onChange={setFrom} /><DateField label="To" value={to} onChange={setTo} /></Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : !rows.length ? <EmptyState title="Nothing in this period" detail="Approved documents dated within the range appear here." /> : (
      <div style={{ overflowX: 'auto', padding: 8 }}>
        <table className="data-table" style={{ fontSize: '.81rem' }}>
          <thead><tr><th>{who}</th><th style={{ textAlign: 'right' }}>Net</th><th style={{ textAlign: 'right' }}>GST</th><th style={{ textAlign: 'right' }}>Gross</th><th style={{ textAlign: 'right' }}>Docs</th></tr></thead>
          <tbody>
            {rows.map((r, i) => <tr key={r.contact_id ?? i}><td style={{ fontWeight: 600 }}>{r.contact}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmtAUD(r.net)}</td><td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmtAUD(r.gst)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(r.gross)}</td><td style={{ textAlign: 'right' }}>{r.documents}</td></tr>)}
            <tr style={{ background: 'var(--surface-2)', borderTop: '2px solid var(--border)' }}><td style={{ fontWeight: 700 }}>Total</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(data.totals?.net)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(data.totals?.gst)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtAUD(data.totals?.gross)}</td><td /></tr>
          </tbody>
        </table>
      </div>)}
  </>)
}

// ── GST / BAS ─────────────────────────────────────────────────────────────────
function GSTReport({ setExport }) {
  const [from, setFrom] = useState(fyStart()); const [to, setTo] = useState(todayISO()); const [basis, setBasis] = useState('accrual')
  const { data, loading, error, run } = useReport(() => books.ledgerReport('gst-summary', { from, to, basis }), [])
  useEffect(() => { if (data) setExport({ name: `gst-bas-${from}-${to}`, rows: [['BAS label', 'Amount'], ...Object.entries(data.fields || {}), ['Net GST payable', data.net_gst_payable]] }) }, [data])
  const f = data?.fields || {}
  const BR = ({ f: code, l, v, hi }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 14px', borderBottom: '1px solid var(--border)', background: hi ? 'var(--surface-2)' : 'transparent', fontSize: '.82rem' }}>
      <span style={{ color: 'var(--text-2)' }}><strong>{code}</strong> {l}</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: hi ? 700 : 400, color: hi ? 'var(--brand)' : 'var(--text-1)' }}>{fmtAUD(v)}</span>
    </div>)
  const box = { border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }
  const head = c => ({ padding: '9px 14px', background: 'var(--surface-2)', fontWeight: 700, fontSize: '.84rem', borderBottom: '1px solid var(--border)', borderLeft: `4px solid ${c}` })
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="From" value={from} onChange={setFrom} /><DateField label="To" value={to} onChange={setTo} />
      <select className="select-compact" value={basis} onChange={e => setBasis(e.target.value)}><option value="accrual">Accrual</option><option value="cash">Cash</option></select></Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : (
      <div style={{ padding: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <div style={box}><div style={head('var(--brand)')}>GST on Sales (G1/1A)</div>
            <BR f="G1" l="Total Sales" v={f.G1} /><BR f="G2" l="Export Sales (GST Free)" v={f.G2} /><BR f="G3" l="Other GST Free Sales" v={f.G3} /><BR f="G4" l="Input Taxed Sales" v={f.G4} />
            <BR f="1A" l="GST on Sales" v={data.gst_on_sales_1A} hi /></div>
          <div style={box}><div style={head('#d97706')}>GST on Purchases (G10/1B)</div>
            <BR f="G10" l="Capital Purchases" v={f.G10} /><BR f="G11" l="Non-capital Purchases" v={f.G11} />
            <BR f="1B" l="GST on Purchases" v={data.gst_on_purchases_1B} hi /></div>
        </div>
        <div style={{ border: '2px solid var(--brand)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
          <div style={{ background: 'var(--brand)', color: '#fff', padding: '9px 14px', fontWeight: 700, fontSize: '.85rem' }}>Net GST Position</div>
          <div style={{ display: 'flex', gap: 12, padding: 14 }}>
            {[['GST Collected (1A)', data.gst_on_sales_1A, '#7c3aed'], ['Input Tax Credits (1B)', data.gst_on_purchases_1B, '#d97706'], ['Net GST Payable', data.net_gst_payable, num(data.net_gst_payable) >= 0 ? '#dc2626' : '#16a34a']].map(([l, v, c]) => (
              <div key={l} style={{ flex: 1, textAlign: 'center', padding: 12, background: 'var(--surface-2)', borderRadius: 'var(--r-md)' }}>
                <div style={{ fontSize: '.7rem', color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase', marginBottom: 5 }}>{l}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '1rem', color: c }}>{fmtAUD(v)}</div></div>))}
          </div>
        </div>
        {data.ledger_check?.reconciled != null
          ? <Note warn={!data.ledger_check.reconciled}>{data.ledger_check.reconciled ? '✓ GST account movement agrees with 1A less 1B.' : `⚠ GST account is off by ${fmtAUD(data.ledger_check.difference)}. ${data.ledger_check.note || ''}`}</Note>
          : data.ledger_check?.note && <Note>{data.ledger_check.note}</Note>}
        <Note warn>⚠️ Verify with your accountant before lodging a BAS with the ATO.</Note>
      </div>)}
  </>)
}

// ── Sub-ledger control check ──────────────────────────────────────────────────
function ControlCheck() {
  const [asAt, setAsAt] = useState(todayISO())
  const { data, loading, error, run } = useReport(() => books.ledgerReport('subledger-control', { as_at: asAt }), [])
  return (<>
    <Filters onRun={run} busy={loading}><DateField label="As at" value={asAt} onChange={setAsAt} /></Filters>
    {error ? <ErrorState error={error} run={run} /> : !data ? <ReportLoading /> : (
      <div style={{ padding: 20, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {[['receivables', 'Accounts Receivable'], ['payables', 'Accounts Payable']].map(([k, title]) => {
          const c = data[k] || {}
          return (<div key={k} style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
            <div style={{ padding: '9px 14px', background: 'var(--surface-2)', fontWeight: 700, fontSize: '.84rem', borderBottom: '1px solid var(--border)' }}>{title}</div>
            <R account="Ledger balance" amount={c.ledger_balance} /><R account="Sub-ledger total" amount={c.subledger_total} /><R account="Difference" amount={c.difference} />
            <div style={{ padding: '10px 14px' }}><Badge ok={!!c.reconciled} yes="Reconciled" no="Not reconciled" /></div>
            {!c.reconciled && c.note && <div style={{ padding: '0 14px 12px', fontSize: '.74rem', color: 'var(--text-3)' }}>{c.note}</div>}
          </div>)
        })}
      </div>)}
  </>)
}

// ── Account Transactions ──────────────────────────────────────────────────────
function AccTxns({ setExport }) {
  const [from, setFrom] = useState(fyStart()); const [to, setTo] = useState(todayISO()); const [acct, setAcct] = useState('')
  const [accs, setAccs] = useState([]); const [filter, setFilter] = useState('')
  useEffect(() => { ledger__0.accounts(true).then(r => setAccs(arr(r.data))).catch(() => {}) }, [])
  const [st, setSt] = useState({ data: null, loading: false, error: '' })
  const run = () => {
    if (!acct) return
    setSt({ data: null, loading: true, error: '' })
    ledger__0.generalLedger(acct, from, to).then(r => setSt({ data: r.data, loading: false, error: '' }))
      .catch(e => setSt({ data: null, loading: false, error: ledger__1.errMsg(e, 'Could not load this account') }))
  }
  const { data, loading, error } = st
  const rows = arr(data?.rows).filter(t => !filter || `${t.description || ''} ${t.narration || ''}`.toLowerCase().includes(filter.toLowerCase()))
  useEffect(() => { if (data) setExport({ name: `account-transactions-${data.account?.code}`, rows: [['Date', 'Journal', 'Description', 'Debit', 'Credit', 'Balance'], ...arr(data.rows).map(t => [t.date, t.journal_no, t.description || t.narration, t.debit, t.credit, t.balance])] }) }, [data])
  return (<>
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
      <select className="input input-sm" style={{ maxWidth: 280 }} value={acct} onChange={e => setAcct(e.target.value)}>
        <option value="">Choose account…</option>{accs.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select>
      <DateField label="From" value={from} onChange={setFrom} /><DateField label="To" value={to} onChange={setTo} />
      <button className="btn btn-primary btn-sm" onClick={run} disabled={!acct || loading}>{loading ? 'Running…' : 'Run'}</button>
      {data && <input className="input input-sm" style={{ maxWidth: 220 }} placeholder="Filter descriptions…" value={filter} onChange={e => setFilter(e.target.value)} />}
    </div>
    {error ? <EmptyState title="This report could not be loaded" detail={error} /> : !data ? (
      <EmptyState title="Choose an account" detail="Pick a GL account and a date range, then press Run." />
    ) : (
      <div style={{ overflowX: 'auto', padding: 8 }}>
        <div style={{ padding: '4px 6px 10px', fontWeight: 700, fontSize: '.86rem' }}>{data.account?.code} · {data.account?.name}</div>
        <table className="data-table" style={{ fontSize: '.78rem' }}>
          <thead><tr><th>Date</th><th>Journal</th><th>Description</th><th style={{ textAlign: 'right' }}>Debit</th><th style={{ textAlign: 'right' }}>Credit</th><th style={{ textAlign: 'right' }}>Balance</th></tr></thead>
          <tbody>
            <tr style={{ fontWeight: 600 }}><td colSpan={5}>Opening balance</td><td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmtAUD(data.opening_balance)}</td></tr>
            {rows.map((t, i) => (
              <tr key={i}><td style={{ whiteSpace: 'nowrap' }}>{fmtDate(t.date)}</td><td style={{ fontFamily: 'var(--font-mono)' }}>{t.journal_no}</td>
                <td style={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.description || t.narration}>{t.description || t.narration}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{num(t.debit) ? fmtAUD(t.debit) : ''}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{num(t.credit) ? fmtAUD(t.credit) : ''}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmtAUD(t.balance)}</td></tr>))}
            <tr style={{ fontWeight: 700, background: 'var(--surface-2)' }}><td colSpan={5}>Closing balance</td><td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmtAUD(data.closing_balance)}</td></tr>
          </tbody>
        </table>
      </div>)}
  </>)
}

// ── Executive Summary ─────────────────────────────────────────────────────────
function ExecutiveSummary() {
  const [state, setState] = useState({ loading: true, pl: null, bs: null, ar: null, ap: null, gst: null, failed: [] })
  const load = useCallback(() => {
    const t = todayISO(), f = fyStart()
    const calls = { pl: ledger__0.profitLoss(f, t), bs: ledger__0.balanceSheet(t), ar: books.salesReport('aged-receivables', { as_at: t }),
      ap: books.purchasesReport('aged-payables', { as_at: t }), gst: books.ledgerReport('gst-summary', { from: f, to: t }) }
    Promise.allSettled(Object.values(calls)).then(res => {
      const out = { loading: false, failed: [] }
      Object.keys(calls).forEach((k, i) => { if (res[i].status === 'fulfilled') out[k] = res[i].value?.data ?? null; else { out[k] = null; out.failed.push(k) } })
      setState(out)
    })
  }, [])
  useEffect(() => { load() }, [load])
  if (state.loading) return <ReportLoading />
  const { pl, bs, ar, ap, gst } = state
  const inc = num(pl?.total_income) + num(pl?.total_other_income)
  const exp = num(pl?.total_cost_of_sales) + num(pl?.total_expenses) + num(pl?.total_other_expenses)
  const net = num(pl?.net_profit)
  const bank = bs ? sum(bs.assets?.bank) : null
  const KPI = ({ label, val, color, sub }) => (
    <div style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: '14px 16px', borderTop: `3px solid ${color || 'var(--brand)'}` }}>
      <div style={{ fontSize: '.7rem', fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', marginBottom: 5 }}>{label}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '1rem', color, marginBottom: 3 }}>{val}</div>
      {sub && <div style={{ fontSize: '.7rem', color: 'var(--text-3)' }}>{sub}</div>}</div>)
  const Row2 = ({ l, v, s }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
      <span style={{ color: 'var(--text-2)' }}>{l}</span>
      <div style={{ textAlign: 'right' }}><div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{v}</div>{s && <div style={{ fontSize: '.7rem', color: 'var(--text-3)' }}>{s}</div>}</div></div>)
  const card = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }
  const cardHead = { padding: '9px 14px', background: 'var(--surface-2)', fontWeight: 700, fontSize: '.84rem', borderBottom: '1px solid var(--border)' }
  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
        <KPI label="Total Income" val={pl ? fmtAUD(inc) : '—'} color="#16a34a" sub={`Since ${fmtDate(fyStart())}`} />
        <KPI label="Total Expenses" val={pl ? fmtAUD(exp) : '—'} color="#dc2626" sub="Cost of sales + expenses" />
        <KPI label="Net Profit/(Loss)" val={pl ? fmtAUD(net) : '—'} color={net >= 0 ? '#16a34a' : '#dc2626'} sub={net >= 0 ? 'Surplus' : 'Deficit'} />
        <KPI label="Net GST Payable" val={gst ? fmtAUD(gst.net_gst_payable) : '—'} color="#7c3aed" sub="1A less 1B, this financial year" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={card}><div style={cardHead}>📊 Performance Ratios</div><div style={{ padding: '0 14px' }}>
          <Row2 l="Net Profit Margin" v={pl ? fmtPct(inc > 0 ? net / inc : 0) : '—'} s="Net / Income" />
          <Row2 l="Income vs Expenses" v={pl && exp > 0 ? `${(inc / exp).toFixed(2)}x` : '—'} s="Income ÷ Expenses" />
          <Row2 l="Gross Profit" v={pl ? fmtAUD(pl.gross_profit) : '—'} s="Income less cost of sales" /></div></div>
        <div style={card}><div style={cardHead}>💡 Financial Position</div><div style={{ padding: '0 14px' }}>
          <Row2 l="Bank Accounts" v={bank == null ? '—' : fmtAUD(bank)} s="Ledger balance today" />
          <Row2 l="Accounts Receivable" v={ar ? fmtAUD(ar.total) : '—'} s="Unpaid invoices" />
          <Row2 l="Accounts Payable" v={ap ? fmtAUD(ap.total) : '—'} s="Unpaid bills" />
          <Row2 l="Net Assets" v={bs ? fmtAUD(bs.net_assets) : '—'} s="Assets less liabilities" /></div></div>
      </div>
      {state.failed.length > 0 && <Note warn>Some figures could not be loaded ({state.failed.join(', ')}) and show “—”. <button className="btn btn-outline btn-xs" onClick={load}>Retry</button></Note>}
      <Note>All figures come from your organisation's posted ledger journals.</Note>
    </div>
  )
}

// ── shell ─────────────────────────────────────────────────────────────────────
const ComingSoon = ({ report }) => (
  <div style={{ padding: 56, textAlign: 'center', color: 'var(--text-3)' }}>
    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>🏗️</div>
    <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-1)', marginBottom: 8 }}>{report.label}</div>
    <div style={{ maxWidth: 380, margin: '0 auto', lineHeight: 1.6, marginBottom: 16 }}>{report.desc}</div>
    <div style={{ padding: '8px 14px', background: 'var(--surface-2)', borderRadius: 'var(--r-md)', display: 'inline-block', fontSize: '.78rem' }}>Coming soon.</div>
  </div>
)

function csvOf(rows) {
  const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`
  return arr(rows).map(r => arr(r).map(q).join(',')).join('\n')
}

function ReportBody({ rkey, hasProReports }) {
  const rep = ALL_ITEMS.find(i => i.key === rkey)
  const [exp, setExp] = useState(null)
  useEffect(() => { setExp(null) }, [rkey])
  if (!rep) return null
  if (!rep.live) return <ComingSoon report={rep} />
  if (!FREE_REPORTS.has(rkey) && !hasProReports) return (
    <div style={{ padding: 56, textAlign: 'center', color: 'var(--text-3)' }}>
      <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>🔒</div>
      <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-1)', marginBottom: 8 }}>{rep.label}</div>
      <div style={{ maxWidth: 380, margin: '0 auto', lineHeight: 1.6, marginBottom: 20 }}>{rep.desc}</div>
      <div style={{ padding: '12px 20px', background: '#fef3c7', borderRadius: 'var(--r-lg)', display: 'inline-block', fontSize: '.82rem', color: '#92400e', border: '1px solid #fde68a', marginBottom: 16 }}>
        📊 Available on <strong>Accounting Pro</strong> and above</div><br />
      <a href="/upgrade" className="btn btn-primary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 8 }}>⚡ Upgrade to Accounting Pro</a>
    </div>
  )
  const props = { setExport: setExp }
  const bodies = {
    executive_summary: <ExecutiveSummary />, pl: <PLReport {...props} />, balance_sheet: <BSReport {...props} />, cash_flow: <CashFlow {...props} />,
    aged_receivables: <Aged side="sales" {...props} />, aged_payables: <Aged side="purchases" {...props} />, invoice_summary: <InvoiceSummary {...props} />,
    by_customer: <ByContact side="sales" {...props} />, by_supplier: <ByContact side="purchases" {...props} />,
    gst_bas: <GSTReport {...props} />, trial_balance: <TrialBalance {...props} />, control_check: <ControlCheck />, account_transactions: <AccTxns {...props} />,
    ...Object.fromEntries(Object.entries(EXTRA_BODIES).map(([k, make]) => [k, make(props)])),
  }
  const download = () => {
    if (!exp) return
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csvOf(exp.rows)], { type: 'text/csv' })); a.download = `${exp.name}.csv`; a.click()
  }
  return (
    <div className="report-print-area">
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ margin: 0, fontSize: '.95rem' }}>{rep.label}</h3>
        <div style={{ display: 'flex', gap: 6 }} className="no-print">
          <button className="btn btn-outline btn-xs" onClick={() => window.print()}><Printer size={11} /> PDF</button>
          <button className="btn btn-outline btn-xs" onClick={download} disabled={!exp} title={exp ? 'Download as CSV (opens in Excel)' : 'Run the report first'}><Download size={11} /> Excel (CSV)</button>
        </div>
      </div>
      <ReportBoundary resetKey={rkey}>{bodies[rkey] || <ComingSoon report={rep} />}</ReportBoundary>
    </div>
  )
}

export default function FinancialReports({ userId }) {
  const [sel, setSel] = useState('pl')
  const [exp, setExp] = useState({ '📈 Financial Performance': true, '📋 Financial Statements': true })
  const [hasProReports, setHasProReports] = useState(false)

  // Plan check — base plans get P&L + Balance Sheet only; Pro+ gets all reports
  useEffect(() => {
    if (!userId) return
    legacy.getMyPlan(userId).then(r => {
      setHasProReports(true)                                          // every financial report is part of Books & Accounting, so on every plan
    }).catch(() => {})
  }, [userId])

  const total = ALL_ITEMS.length, live = ALL_ITEMS.filter(i => i.live).length
  const canView = key => hasProReports || FREE_REPORTS.has(key)

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: '.78rem', color: 'var(--text-3)' }}>{live} live · {total - live} coming soon · {total} total reports</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 20, alignItems: 'start' }}>
        <div className="no-print" style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden', boxShadow: 'var(--sh-xs)', position: 'sticky', top: 0, maxHeight: '82vh', overflowY: 'auto' }}>
          <div style={{ padding: '10px 13px', borderBottom: '1px solid var(--border)', background: 'var(--surface-2)', fontSize: '.73rem', fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.06em' }}>All Reports</div>
          {MENU.map(group => {
            const open = exp[group.group] !== false
            return (
              <div key={group.group}>
                <button onClick={() => setExp(p => ({ ...p, [group.group]: !open }))} style={{ width: '100%', textAlign: 'left', padding: '6px 12px', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                  background: 'var(--surface-2)', fontSize: '.7rem', fontWeight: 700, color: group.color, textTransform: 'uppercase', letterSpacing: '.04em',
                  borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>{group.group}</span>{open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                </button>
                {open && group.items.map(item => {
                  const locked = item.live && !canView(item.key)
                  return (
                    <button key={item.key} onClick={() => { if (item.live && !locked) setSel(item.key) }} title={locked ? 'Upgrade to Accounting Pro' : undefined}
                      style={{ width: '100%', textAlign: 'left', padding: '7px 14px', border: 'none', cursor: (item.live && !locked) ? 'pointer' : 'default', fontFamily: 'inherit',
                        background: sel === item.key ? 'var(--brand)' : 'transparent', color: sel === item.key ? '#fff' : item.live ? 'var(--text-2)' : 'var(--text-3)',
                        fontSize: '.81rem', fontWeight: sel === item.key ? 700 : 400, transition: 'background .1s,color .1s', opacity: item.live ? 1 : 0.6,
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>{item.label}</span>
                      {!item.live && <span style={{ fontSize: '.6rem', padding: '1px 4px', borderRadius: 3, background: sel === item.key ? 'rgba(255,255,255,.2)' : '#fef3c7', color: sel === item.key ? '#fff' : '#92400e', fontWeight: 700 }}>Soon</span>}
                      {item.live && locked && <span style={{ fontSize: '.6rem', padding: '1px 4px', borderRadius: 3, background: sel === item.key ? 'rgba(255,255,255,.2)' : '#fee2e2', color: sel === item.key ? '#fff' : '#991b1b', fontWeight: 700 }}>Pro</span>}
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden', boxShadow: 'var(--sh-xs)', minHeight: 500 }}>
          <ReportBody rkey={sel} hasProReports={hasProReports} />
        </div>
      </div>
    </div>
  )
}
