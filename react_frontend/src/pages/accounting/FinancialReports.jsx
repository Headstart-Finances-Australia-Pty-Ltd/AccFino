/**
 * FinancialReports — all Xero-equivalent accounting reports for AccFino (Australia).
 *
 * Categories (matching Xero AU):
 *  1. Financial Performance   — Executive Summary, P&L, Budget Variance, Cash Summary
 *  2. Financial Statements    — Balance Sheet, Cash Flow Statement, Management Report
 *  3. Payables & Receivables  — Aged Receivables, Aged Payables, Invoice Summary
 *  4. Taxes & Balances        — GST / BAS Report, Trial Balance, General Ledger Summary, PAYG
 *  5. Reconciliation          — Bank Reconciliation, Account Summary, Cash Validation
 *  6. Transactions            — Account Transactions, Journal Report, Inventory Items
 */
import React, { useState, useEffect } from 'react'
import { Download, ChevronDown, ChevronRight } from 'lucide-react'
import axios from 'axios'

const http = axios.create({ baseURL: '/api', withCredentials: true })
http.interceptors.request.use(cfg => {
  try { const u = JSON.parse(localStorage.getItem('af_user')||'{}'); if (u.token) cfg.headers['Authorization'] = `Bearer ${u.token}` } catch {}
  return cfg
})

const CY = new Date().getFullYear()
const fmtAUD = n => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const s = new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',minimumFractionDigits:2}).format(abs)
  return n < 0 ? `(${s.replace('-','').replace('$','')})` : s
}
const fmtPct  = n => n == null ? '—' : `${(n*100).toFixed(1)}%`
const fmtDate = d => d ? new Date(d).toLocaleDateString('en-AU') : '—'

// ── All Xero AU report types ──────────────────────────────────────────────────
const MENU = [
  { group:'📈 Financial Performance', color:'#16a34a', items:[
    { key:'executive_summary', label:'Executive Summary',      live:true,  desc:'Cash, profitability and balance sheet KPIs at a glance' },
    { key:'pl',                label:'Profit & Loss',          live:true,  desc:'Income, expenses and net profit for a period' },
    { key:'budget_variance',   label:'Budget Variance',        live:false, desc:'Actual vs budget for income and expenses' },
    { key:'cash_summary',      label:'Cash Summary',           live:false, desc:'Movement of cash in and out for the period' },
  ]},
  { group:'📋 Financial Statements', color:'#2563eb', items:[
    { key:'balance_sheet',     label:'Balance Sheet',          live:true,  desc:'Assets, liabilities and equity at a point in time' },
    { key:'cash_flow',         label:'Cash Flow Statement',    live:false, desc:'Operating, investing and financing cash flows' },
    { key:'management_report', label:'Management Report',      live:false, desc:'P&L + Balance Sheet + Aged reports combined' },
  ]},
  { group:'💳 Payables & Receivables', color:'#d97706', items:[
    { key:'aged_receivables',  label:'Aged Receivables',       live:true,  desc:'Customer invoices by how long they are overdue' },
    { key:'aged_payables',     label:'Aged Payables',          live:true,  desc:'Supplier bills by how long they are overdue' },
    { key:'invoice_summary',   label:'Invoice Summary',        live:true,  desc:'All sales invoices with status and amounts' },
    { key:'expense_claims',    label:'Expense Claims',         live:false, desc:'Summary of submitted and approved expense claims' },
  ]},
  { group:'🏛 Taxes & Balances', color:'#7c3aed', items:[
    { key:'gst_bas',           label:'GST / BAS Report',       live:true,  desc:'GST collected and paid — BAS ready (Australia)' },
    { key:'trial_balance',     label:'Trial Balance',          live:false, desc:'All GL account balances — debits equal credits' },
    { key:'gl_summary',        label:'General Ledger Summary', live:false, desc:'All account balances and movements for the period' },
    { key:'payg_summary',      label:'PAYG Summary',           live:false, desc:'PAYG withholding for BAS lodgement' },
  ]},
  { group:'🏦 Reconciliation', color:'#0891b2', items:[
    { key:'bank_recon',        label:'Bank Reconciliation',    live:true,  desc:'AccFino records vs bank statement balances' },
    { key:'account_summary',   label:'Account Summary',        live:false, desc:'Monthly account activity for all bank accounts' },
    { key:'cash_validation',   label:'Cash Validation',        live:false, desc:'Identify duplicate or unusual transactions' },
  ]},
  { group:'📝 Transactions', color:'#6b7280', items:[
    { key:'account_transactions', label:'Account Transactions',live:true,  desc:'All transactions for a selected GL account' },
    { key:'journal_report',    label:'Journal Report',         live:false, desc:'All journal entries posted for the period' },
    { key:'inventory_items',   label:'Inventory Item Details', live:false, desc:'Inventory quantities, values and movements' },
  ]},
]

// ── Shared UI atoms ───────────────────────────────────────────────────────────
function Sec({ label, total, accent='var(--brand)', children, open:init=true }) {
  const [open, setOpen] = useState(init)
  return (
    <div style={{marginBottom:3}}>
      <button onClick={()=>setOpen(o=>!o)} style={{
        width:'100%',display:'flex',alignItems:'center',justifyContent:'space-between',
        padding:'9px 14px',background:'var(--surface-2)',border:'none',cursor:'pointer',
        fontFamily:'inherit',borderRadius:'var(--r-md)',borderLeft:`4px solid ${accent}`,marginBottom:open?3:0,
      }}>
        <div style={{display:'flex',alignItems:'center',gap:7}}>
          {open?<ChevronDown size={12} color="var(--text-3)"/>:<ChevronRight size={12} color="var(--text-3)"/>}
          <span style={{fontWeight:700,fontSize:'.85rem'}}>{label}</span>
        </div>
        <span style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.85rem',
          color:total<0?'var(--danger)':'var(--text-1)'}}>{fmtAUD(total)}</span>
      </button>
      {open && <div style={{paddingLeft:3}}>{children}</div>}
    </div>
  )
}
const R = ({account,amount}) => (
  <div style={{display:'flex',justifyContent:'space-between',padding:'5px 14px',
    borderBottom:'1px solid var(--border)',fontSize:'.8rem'}}>
    <span style={{color:'var(--text-2)'}}>{account}</span>
    <span style={{fontFamily:'var(--font-mono)',color:amount<0?'var(--danger)':'var(--text-1)',
      fontWeight:amount<0?600:400}}>{fmtAUD(amount)}</span>
  </div>
)
const Tot = ({label,amount,strong=false,bg=false}) => (
  <div style={{display:'flex',justifyContent:'space-between',
    padding:strong?'10px 14px':'7px 14px',
    background:bg?'var(--surface-2)':'transparent',
    borderTop:strong?'2px solid var(--border)':'1px solid var(--border)',
    borderBottom:strong?'2px solid var(--border)':'none',
    fontSize:strong?'.9rem':'.82rem'}}>
    <span style={{fontWeight:strong?700:600}}>{label}</span>
    <span style={{fontFamily:'var(--font-mono)',fontWeight:strong?700:600,
      color:amount<0?'var(--danger)':amount>0?'var(--success)':'var(--text-1)'}}>{fmtAUD(amount)}</span>
  </div>
)
const GH = ({label}) => (
  <div style={{padding:'8px 14px',fontWeight:700,fontSize:'.72rem',color:'var(--text-3)',
    textTransform:'uppercase',letterSpacing:'.07em',marginTop:6}}>{label}</div>
)

// ── P&L ──────────────────────────────────────────────────────────────────────
const PL = { income:[
  {a:'Consulting Income',v:215724.03},{a:'Sales',v:57657.04},{a:'Sales – Car Parts',v:40000.00},{a:'Service Income',v:115454.55}],
  cos:[{a:'Freight & Delivery',v:363.64},{a:'Purchases – Car Parts',v:5779.98},{a:'Tools',v:1287.25}],
  other:[{a:'Interest Income',v:0.73},{a:'Other Revenue',v:124750.04},{a:'Realised Gain/Loss on Investments',v:-9547.89},{a:'Unrealised Gain/Loss on Investments',v:145992.23}],
  exp:[{a:'Advertising & Promotion',v:4545.45},{a:'Assets Immediate Write-Off',v:2453.64},{a:'Bank Fees',v:4.40},{a:'Catering',v:14.55},
    {a:'Cleaning & Laundry',v:42.82},{a:'Client Gifts',v:604.84},{a:'Client Meeting',v:255.00},{a:'Contractor',v:7350.00},
    {a:'Entertainment',v:90.00},{a:'Fees & Permits',v:738.00},{a:'Freight & Courier',v:1232.45},{a:'Income Tax Expense',v:56902.23},
    {a:'Insurance',v:3125.92},{a:'Interest on Loan – BMW',v:4637.08},{a:'Motor Vehicles – Fuel & Oil',v:1570.71},
    {a:'Motor Vehicles – Rego & Insurance',v:2036.03},{a:'Motor Vehicles – Repairs',v:2318.17},{a:'Motor Vehicles – Tolls & Parking',v:3103.62},
    {a:'Office Expenses',v:293.91},{a:'Project Purchases',v:291204.07},{a:'Repairs & Maintenance',v:15933.27},
    {a:'Staff Amenities',v:393.06},{a:'Subcontractors',v:136959.97},{a:'Subscriptions & Memberships',v:863.45},
    {a:'Superannuation',v:11384.97},{a:'Telephone & Internet',v:2146.28},{a:'Training & Conferences',v:1200.00},
    {a:'Travel – National',v:-118.88},{a:'Wages & Salaries',v:53376.20},{a:'Workcover Insurance',v:157.25}],
}
function PLReport() {
  const inc=PL.income.reduce((s,r)=>s+r.v,0), cos=PL.cos.reduce((s,r)=>s+r.v,0)
  const gross=inc-cos, oth=PL.other.reduce((s,r)=>s+r.v,0), exp=PL.exp.reduce((s,r)=>s+r.v,0)
  return (
    <div style={{padding:8}}>
      <Sec label="Trading Income" total={inc} accent="#16a34a">{PL.income.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Sec label="Cost of Sales" total={cos} accent="#dc2626">{PL.cos.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Tot label="Gross Profit" amount={gross} strong bg/>
      <Sec label="Other Income" total={oth} accent="#2563eb" open={false}>{PL.other.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Sec label="Operating Expenses" total={exp} accent="#d97706" open={false}>{PL.exp.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Tot label="Net Profit / (Loss)" amount={gross+oth-exp} strong bg/>
    </div>
  )
}

// ── Balance Sheet ─────────────────────────────────────────────────────────────
const BS = {
  bank:[{a:'Equipment & Machinery Rental',v:8969.17},{a:'Proexec ANZ Account',v:209959.10},{a:'Proexec PTY #405',v:23446.39}],
  cur:[{a:'Accounts Receivable',v:5000.00},{a:'Loans to Directors',v:-20000.00},{a:'Marketable Equities',v:226544.34}],
  fix:[{a:'2019 BMW (Motor Vehicle)',v:56058.46},{a:'Inventory',v:32578.42},{a:'Less: Accumulated Depreciation',v:-23094.00},{a:'Motor Vehicles Net',v:39806.72}],
  clib:[{a:'Accounts Payable',v:60280.48},{a:'GST',v:15851.50},{a:'PAYG Income Tax Payable',v:-58234.00},{a:'PAYG Withholdings',v:4027.56},{a:'Rounding',v:0.01},{a:'Superannuation Payable',v:5167.24},{a:'Suspense',v:205.66},{a:'Wages Payable',v:1532.77}],
  eq:[{a:'Current Year Earnings',v:77781.40},{a:'Gifting',v:-94.90},{a:'Retained Earnings',v:452750.88}],
}
function BSReport() {
  const bank=BS.bank.reduce((s,r)=>s+r.v,0),cur=BS.cur.reduce((s,r)=>s+r.v,0),fix=BS.fix.reduce((s,r)=>s+r.v,0)
  const ta=bank+cur+fix, tl=BS.clib.reduce((s,r)=>s+r.v,0), te=BS.eq.reduce((s,r)=>s+r.v,0)
  return (
    <div style={{padding:8}}>
      <GH label="Assets"/>
      <Sec label="Bank" total={bank} accent="#2563eb">{BS.bank.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Sec label="Current Assets" total={cur} accent="#0891b2" open={false}>{BS.cur.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Sec label="Fixed Assets" total={fix} accent="#7c3aed" open={false}>{BS.fix.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Tot label="Total Assets" amount={ta} strong bg/>
      <GH label="Liabilities"/>
      <Sec label="Current Liabilities" total={tl} accent="#dc2626">{BS.clib.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Tot label="Total Liabilities" amount={tl} strong bg/>
      <Tot label="Net Assets" amount={ta-tl} strong/>
      <GH label="Equity"/>
      <Sec label="Equity" total={te} accent="#16a34a">{BS.eq.map((r,i)=><R key={i} account={r.a} amount={r.v}/>)}</Sec>
      <Tot label="Total Equity" amount={te} strong bg/>
    </div>
  )
}

// ── Executive Summary ─────────────────────────────────────────────────────────
function ExecutiveSummary({ db }) {
  const inc=db?.totals?.credits||0, exp=db?.totals?.debits||0, net=inc-exp, gst=db?.totals?.gst||0, txns=db?.total||0
  const KPI=({label,val,color,sub})=>(
    <div style={{background:'var(--surface-2)',border:'1px solid var(--border)',borderRadius:'var(--r-lg)',
      padding:'14px 16px',borderTop:`3px solid ${color||'var(--brand)'}`}}>
      <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',marginBottom:5}}>{label}</div>
      <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1rem',color,marginBottom:3}}>{val}</div>
      {sub&&<div style={{fontSize:'.7rem',color:'var(--text-3)'}}>{sub}</div>}
    </div>
  )
  const Row2=({l,v,s})=>(
    <div style={{display:'flex',justifyContent:'space-between',padding:'8px 0',borderBottom:'1px solid var(--border)',fontSize:'.82rem'}}>
      <span style={{color:'var(--text-2)'}}>{l}</span>
      <div style={{textAlign:'right'}}>
        <div style={{fontFamily:'var(--font-mono)',fontWeight:700}}>{v}</div>
        {s&&<div style={{fontSize:'.7rem',color:'var(--text-3)'}}>{s}</div>}
      </div>
    </div>
  )
  return (
    <div style={{padding:20}}>
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:20}}>
        <KPI label="Total Income"    val={fmtAUD(inc)}  color="#16a34a" sub={`${txns} transactions`}/>
        <KPI label="Total Expenses"  val={fmtAUD(exp)}  color="#dc2626" sub="From reconciliation DB"/>
        <KPI label="Net Profit/(Loss)" val={fmtAUD(net)} color={net>=0?'#16a34a':'#dc2626'} sub={net>=0?'Surplus':'Deficit'}/>
        <KPI label="GST Position"    val={fmtAUD(gst)}  color="#7c3aed" sub="Estimated"/>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16}}>
        <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
          <div style={{padding:'9px 14px',background:'var(--surface-2)',fontWeight:700,fontSize:'.84rem',borderBottom:'1px solid var(--border)'}}>📊 Performance Ratios</div>
          <div style={{padding:'0 14px'}}>
            <Row2 l="Net Profit Margin"      v={fmtPct(inc>0?net/inc:0)}               s="Net / Income"/>
            <Row2 l="Income vs Expenses"     v={exp>0?`${(inc/exp).toFixed(2)}x`:'—'}  s="Income ÷ Expenses"/>
            <Row2 l="Total Transactions"     v={txns.toLocaleString()}                  s="In AccFino DB"/>
            <Row2 l="Avg Transaction (Income)" v={txns>0?fmtAUD(inc/txns):'—'}         s="Income ÷ Txns"/>
          </div>
        </div>
        <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
          <div style={{padding:'9px 14px',background:'var(--surface-2)',fontWeight:700,fontSize:'.84rem',borderBottom:'1px solid var(--border)'}}>💡 Financial Position</div>
          <div style={{padding:'0 14px'}}>
            <Row2 l="Bank Accounts"        v={fmtAUD(242374.66)} s="Cash & equivalents"/>
            <Row2 l="Accounts Receivable"  v={fmtAUD(5000.00)}   s="Outstanding invoices"/>
            <Row2 l="Accounts Payable"     v={fmtAUD(60280.48)}  s="Outstanding bills"/>
            <Row2 l="Net Assets"           v={fmtAUD(530436.78)} s="Assets − Liabilities"/>
          </div>
        </div>
      </div>
      <div style={{marginTop:14,padding:'8px 12px',background:'#fef3c7',borderRadius:'var(--r-md)',
        fontSize:'.74rem',color:'#92400e',border:'1px solid #fde68a'}}>
        💡 Income & expense from your reconciliation DB. Balance sheet uses sample data until your COA is fully connected.
      </div>
    </div>
  )
}

// ── Aged Receivables ──────────────────────────────────────────────────────────
const AR = [
  {c:'Acme Corporation',  cur:5000,  d30:0,    d60:0,    d90:0,    total:5000  },
  {c:'BuildCo Pty Ltd',   cur:0,     d30:3200, d60:0,    d90:0,    total:3200  },
  {c:'City Council',      cur:0,     d30:0,    d60:1500, d90:0,    total:1500  },
  {c:'Delta Solutions',   cur:0,     d30:0,    d60:0,    d90:2800, total:2800  },
]
function AgedRec() {
  const tots=AR.reduce((a,r)=>({cur:a.cur+r.cur,d30:a.d30+r.d30,d60:a.d60+r.d60,d90:a.d90+r.d90,total:a.total+r.total}),{cur:0,d30:0,d60:0,d90:0,total:0})
  const H=['Customer','Current','1–30 days','31–60 days','61–90 days','Total']
  return (
    <div style={{overflowX:'auto',padding:8}}>
      <table className="data-table" style={{fontSize:'.81rem'}}>
        <thead><tr>{H.map(h=><th key={h} style={{textAlign:h==='Customer'?'left':'right'}}>{h}</th>)}</tr></thead>
        <tbody>
          {AR.map((r,i)=>(
            <tr key={i}>
              <td style={{fontWeight:600}}>{r.c}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'#16a34a'}}>{r.cur?fmtAUD(r.cur):'—'}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:r.d30?'#d97706':'var(--text-3)'}}>{r.d30?fmtAUD(r.d30):'—'}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:r.d60?'#dc2626':'var(--text-3)'}}>{r.d60?fmtAUD(r.d60):'—'}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:r.d90?'#7c3aed':'var(--text-3)'}}>{r.d90?fmtAUD(r.d90):'—'}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:700}}>{fmtAUD(r.total)}</td>
            </tr>
          ))}
          <tr style={{background:'var(--surface-2)',borderTop:'2px solid var(--border)'}}>
            <td style={{fontWeight:700}}>Total</td>
            {[tots.cur,tots.d30,tots.d60,tots.d90,tots.total].map((v,i)=><td key={i} style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:700}}>{fmtAUD(v)}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// ── Aged Payables ─────────────────────────────────────────────────────────────
const AP = [
  {s:'JB Hi-Fi',               cur:12000,    d30:0,   d60:0,   d90:0,   total:12000    },
  {s:'Office National',        cur:0,        d30:860, d60:0,   d90:0,   total:860      },
  {s:'Telstra Business',       cur:0,        d30:0,   d60:450, d90:0,   total:450      },
  {s:'ATO / GST',              cur:15851.50, d30:0,   d60:0,   d90:0,   total:15851.50 },
  {s:'Superannuation Fund',    cur:5167.24,  d30:0,   d60:0,   d90:0,   total:5167.24  },
]
function AgedPay() {
  const tots=AP.reduce((a,r)=>({cur:a.cur+r.cur,d30:a.d30+r.d30,d60:a.d60+r.d60,d90:a.d90+r.d90,total:a.total+r.total}),{cur:0,d30:0,d60:0,d90:0,total:0})
  return (
    <div style={{overflowX:'auto',padding:8}}>
      <table className="data-table" style={{fontSize:'.81rem'}}>
        <thead><tr>
          <th>Supplier</th>
          {['Current','1–30 days','31–60 days','61–90 days','Total'].map(h=><th key={h} style={{textAlign:'right'}}>{h}</th>)}
        </tr></thead>
        <tbody>
          {AP.map((r,i)=>(
            <tr key={i}>
              <td style={{fontWeight:600}}>{r.s}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'#16a34a'}}>{r.cur?fmtAUD(r.cur):'—'}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:r.d30?'#d97706':'var(--text-3)'}}>{r.d30?fmtAUD(r.d30):'—'}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:r.d60?'#dc2626':'var(--text-3)'}}>{r.d60?fmtAUD(r.d60):'—'}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:r.d90?'#7c3aed':'var(--text-3)'}}>{r.d90?fmtAUD(r.d90):'—'}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:700}}>{fmtAUD(r.total)}</td>
            </tr>
          ))}
          <tr style={{background:'var(--surface-2)',borderTop:'2px solid var(--border)'}}>
            <td style={{fontWeight:700}}>Total</td>
            {[tots.cur,tots.d30,tots.d60,tots.d90,tots.total].map((v,i)=><td key={i} style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:700}}>{fmtAUD(v)}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// ── Invoice Summary ───────────────────────────────────────────────────────────
function InvoiceSummary({ userId }) {
  const [docs,setDocs]=useState([]), [loading,setLoading]=useState(true)
  useEffect(()=>{
    if(!userId) return
    http.get('/accounting/documents',{params:{user_id:userId,document_type:'invoice'}})
      .then(r=>setDocs(r.data||[])).catch(()=>{}).finally(()=>setLoading(false))
  },[userId])
  if(loading) return <div style={{padding:32,textAlign:'center',color:'var(--text-3)'}}>Loading…</div>
  if(!docs.length) return <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>No invoices yet. Create invoices in the Sales tab.</div>
  const SC={draft:'var(--text-3)',sent:'#2563eb',paid:'#16a34a',overdue:'#dc2626',void:'#6b7280'}
  return (
    <div style={{overflowX:'auto',padding:8}}>
      <table className="data-table" style={{fontSize:'.8rem'}}>
        <thead><tr>
          <th>Invoice #</th><th>Customer</th><th>Date</th><th>Due</th>
          <th style={{textAlign:'right'}}>Subtotal</th><th style={{textAlign:'right'}}>GST</th>
          <th style={{textAlign:'right'}}>Total</th><th>Status</th>
        </tr></thead>
        <tbody>
          {docs.map(d=>(
            <tr key={d.id}>
              <td style={{fontFamily:'var(--font-mono)',fontWeight:600}}>{d.document_number}</td>
              <td>{d.party_name||'—'}</td><td>{fmtDate(d.document_date)}</td><td>{fmtDate(d.due_date)}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)'}}>{fmtAUD(d.subtotal)}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'#7c3aed'}}>{fmtAUD(d.tax_amount)}</td>
              <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:700}}>{fmtAUD(d.total_amount)}</td>
              <td><span style={{padding:'2px 8px',borderRadius:100,fontSize:'.7rem',fontWeight:700,
                color:SC[d.status]||'var(--text-3)',background:'var(--surface-2)'}}>{d.status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── GST / BAS ─────────────────────────────────────────────────────────────────
function GSTReport({ userId }) {
  const [stats,setStats]=useState(null)
  useEffect(()=>{ if(userId) http.get(`/db/stats/${userId}`).then(r=>setStats(r.data)).catch(()=>{}) },[userId])
  const col=stats?.totals?.gst||0, paid=col*0.3, net=col-paid
  const BR=({f,l,v,hi})=>(
    <div style={{display:'flex',justifyContent:'space-between',padding:'8px 14px',
      borderBottom:'1px solid var(--border)',background:hi?'var(--surface-2)':'transparent',fontSize:'.82rem'}}>
      <span style={{color:'var(--text-2)'}}><strong>{f}</strong> {l}</span>
      <span style={{fontFamily:'var(--font-mono)',fontWeight:hi?700:400,color:hi?'var(--brand)':'var(--text-1)'}}>{fmtAUD(v)}</span>
    </div>
  )
  return (
    <div style={{padding:20}}>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16,marginBottom:16}}>
        <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
          <div style={{padding:'9px 14px',background:'var(--surface-2)',fontWeight:700,fontSize:'.84rem',borderBottom:'1px solid var(--border)',borderLeft:'4px solid var(--brand)'}}>GST on Sales (G1/1A)</div>
          <BR f="G1" l="Total Sales" v={col/0.1||0}/>
          <BR f="G2" l="Export Sales (GST Free)" v={0}/>
          <BR f="G3" l="Other GST Free Sales" v={0}/>
          <BR f="G4" l="Input Taxed Sales" v={0}/>
          <BR f="1A" l="GST on Sales" v={col} hi/>
        </div>
        <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
          <div style={{padding:'9px 14px',background:'var(--surface-2)',fontWeight:700,fontSize:'.84rem',borderBottom:'1px solid var(--border)',borderLeft:'4px solid #d97706'}}>GST on Purchases (G10/1B)</div>
          <BR f="G10" l="Total Purchases" v={paid/0.1||0}/>
          <BR f="G11" l="Non-deductible Purchases" v={0}/>
          <BR f="1B" l="GST on Purchases" v={paid} hi/>
        </div>
      </div>
      <div style={{border:'2px solid var(--brand)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
        <div style={{background:'var(--brand)',color:'#fff',padding:'9px 14px',fontWeight:700,fontSize:'.85rem'}}>Net GST Position</div>
        <div style={{display:'flex',gap:12,padding:14}}>
          {[['GST Collected (1A)',col,'#7c3aed'],['Input Tax Credits (1B)',paid,'#d97706'],['Net GST Payable',net,net>=0?'#dc2626':'#16a34a']].map(([l,v,c])=>(
            <div key={l} style={{flex:1,textAlign:'center',padding:12,background:'var(--surface-2)',borderRadius:'var(--r-md)'}}>
              <div style={{fontSize:'.7rem',color:'var(--text-3)',fontWeight:700,textTransform:'uppercase',marginBottom:5}}>{l}</div>
              <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1rem',color:c}}>{fmtAUD(v)}</div>
            </div>
          ))}
        </div>
      </div>
      <div style={{marginTop:12,padding:'8px 12px',background:'#fef3c7',borderRadius:'var(--r-md)',
        fontSize:'.73rem',color:'#92400e',border:'1px solid #fde68a'}}>
        ⚠️ GST figures are estimated from your reconciliation data. Always verify with your accountant before lodging a BAS with the ATO.
      </div>
    </div>
  )
}

// ── Bank Reconciliation ───────────────────────────────────────────────────────
function BankRecon({ userId }) {
  const [stats,setStats]=useState(null)
  useEffect(()=>{ if(userId) http.get(`/db/stats/${userId}`).then(r=>setStats(r.data)).catch(()=>{}) },[userId])
  const txns=stats?.total||0
  return (
    <div style={{padding:20}}>
      <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12,marginBottom:20}}>
        {[
          {l:'Transactions in DB', v:txns.toLocaleString(), c:'var(--brand)'},
          {l:'Last Saved',         v:stats?.last_saved?fmtDate(stats.last_saved):'—', c:'#16a34a'},
          {l:'Accounts Tracked',   v:Object.keys(stats?.columns?.bank_balance||{}).length||0, c:'#2563eb'},
        ].map(({l,v,c})=>(
          <div key={l} style={{background:'var(--surface-2)',border:'1px solid var(--border)',borderRadius:'var(--r-lg)',padding:'14px 16px'}}>
            <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',marginBottom:5}}>{l}</div>
            <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1rem',color:c}}>{v}</div>
          </div>
        ))}
      </div>
      <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
        <div style={{padding:'9px 14px',background:'var(--surface-2)',fontWeight:700,fontSize:'.84rem',borderBottom:'1px solid var(--border)'}}>Account Status</div>
        {!txns ? (
          <div style={{padding:32,textAlign:'center',color:'var(--text-3)'}}>No transactions saved yet. Run a reconciliation session and save to DB first.</div>
        ) : (
          <div style={{padding:'4px 14px'}}>
            {Object.entries(stats?.columns?.bank_balance||{}).slice(0,10).map(([acct,count])=>(
              <div key={acct} style={{display:'flex',justifyContent:'space-between',padding:'8px 0',borderBottom:'1px solid var(--border)',fontSize:'.81rem'}}>
                <span style={{fontFamily:'var(--font-mono)',color:'var(--text-2)'}}>{acct}</span>
                <span style={{color:'#16a34a',fontWeight:600}}>✓ {count} transactions saved</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Account Transactions ──────────────────────────────────────────────────────
function AccTxns({ userId }) {
  const [txns,setTxns]=useState([]), [filter,setFilter]=useState(''), [loading,setLoading]=useState(true)
  useEffect(()=>{
    if(!userId) return
    http.get(`/cashflow/from-db/${userId}`).then(r=>setTxns(r.data?.rows||[])).catch(()=>{}).finally(()=>setLoading(false))
  },[userId])
  const shown=txns.filter(t=>!filter||t.description?.toLowerCase().includes(filter.toLowerCase())).slice(0,50)
  if(loading) return <div style={{padding:32,textAlign:'center',color:'var(--text-3)'}}>Loading…</div>
  return (
    <div style={{padding:16}}>
      <div style={{display:'flex',gap:8,marginBottom:12,alignItems:'center'}}>
        <input className="input input-sm" style={{maxWidth:260}} placeholder="Filter descriptions…"
          value={filter} onChange={e=>setFilter(e.target.value)}/>
        <span style={{fontSize:'.76rem',color:'var(--text-3)'}}>{txns.length} total · showing {shown.length}</span>
      </div>
      {!txns.length
        ? <div style={{textAlign:'center',padding:32,color:'var(--text-3)'}}>No transactions in DB. Save a reconciliation session first.</div>
        : <div style={{overflowX:'auto'}}>
            <table className="data-table" style={{fontSize:'.78rem'}}>
              <thead><tr>
                <th>Date</th><th>Description</th>
                <th style={{textAlign:'right'}}>Debit</th>
                <th style={{textAlign:'right'}}>Credit</th>
                <th style={{textAlign:'right'}}>Balance</th>
              </tr></thead>
              <tbody>
                {shown.map((t,i)=>(
                  <tr key={i}>
                    <td style={{whiteSpace:'nowrap'}}>{t.date}</td>
                    <td style={{maxWidth:260,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}} title={t.description}>{t.description}</td>
                    <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'var(--warning)'}}>{t.debit?fmtAUD(t.debit):''}</td>
                    <td style={{textAlign:'right',fontFamily:'var(--font-mono)',color:'var(--info)'}}>{t.credit?fmtAUD(t.credit):''}</td>
                    <td style={{textAlign:'right',fontFamily:'var(--font-mono)'}}>{t.balance?fmtAUD(t.balance):''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
      }
    </div>
  )
}

// ── Render active report ──────────────────────────────────────────────────────
function ComingSoon({ report }) {
  return (
    <div style={{padding:56,textAlign:'center',color:'var(--text-3)'}}>
      <div style={{fontSize:'2.5rem',marginBottom:12}}>🏗️</div>
      <div style={{fontWeight:700,fontSize:'1rem',color:'var(--text-1)',marginBottom:8}}>{report.label}</div>
      <div style={{maxWidth:380,margin:'0 auto',lineHeight:1.6,marginBottom:16}}>{report.desc}</div>
      <div style={{padding:'8px 14px',background:'var(--surface-2)',borderRadius:'var(--r-md)',display:'inline-block',fontSize:'.78rem'}}>
        This report will use your AccFino reconciliation and accounting data automatically when available.
      </div>
    </div>
  )
}

function ReportBody({ rkey, userId, dbStats, hasProReports }) {
  const FREE_REPORTS = new Set(['pl', 'balance_sheet'])
  const allItems = MENU.flatMap(g=>g.items)
  const rep = allItems.find(i=>i.key===rkey)
  if (!rep) return null
  if (!rep.live) return <ComingSoon report={rep}/>
  if (rep.live && !FREE_REPORTS.has(rkey) && !hasProReports) return (
    <div style={{padding:56,textAlign:'center',color:'var(--text-3)'}}>
      <div style={{fontSize:'2.5rem',marginBottom:12}}>🔒</div>
      <div style={{fontWeight:700,fontSize:'1rem',color:'var(--text-1)',marginBottom:8}}>{rep.label}</div>
      <div style={{maxWidth:380,margin:'0 auto',lineHeight:1.6,marginBottom:20}}>{rep.desc}</div>
      <div style={{padding:'12px 20px',background:'#fef3c7',borderRadius:'var(--r-lg)',
        display:'inline-block',fontSize:'.82rem',color:'#92400e',border:'1px solid #fde68a',marginBottom:16}}>
        📊 Available on <strong>Accounting Pro</strong> and above
      </div>
      <br/>
      <a href="/upgrade" className="btn btn-primary btn-sm"
        style={{display:'inline-flex',alignItems:'center',gap:6,marginTop:8}}>
        ⚡ Upgrade to Accounting Pro
      </a>
    </div>
  )
  const bodies = {
    executive_summary:    <ExecutiveSummary db={dbStats}/>,
    pl:                   <PLReport/>,
    balance_sheet:        <BSReport/>,
    aged_receivables:     <AgedRec/>,
    aged_payables:        <AgedPay/>,
    invoice_summary:      <InvoiceSummary userId={userId}/>,
    gst_bas:              <GSTReport userId={userId}/>,
    bank_recon:           <BankRecon userId={userId}/>,
    account_transactions: <AccTxns userId={userId}/>,
  }
  const titles = {
    executive_summary:'Executive Summary', pl:'Profit & Loss', balance_sheet:'Balance Sheet',
    aged_receivables:'Aged Receivables', aged_payables:'Aged Payables', invoice_summary:'Invoice Summary',
    gst_bas:'GST / BAS Report', bank_recon:'Bank Reconciliation', account_transactions:'Account Transactions',
  }
  return (
    <>
      <div style={{padding:'12px 16px',borderBottom:'1px solid var(--border)',background:'var(--surface-2)',
        display:'flex',alignItems:'center',justifyContent:'space-between'}}>
        <h3 style={{margin:0,fontSize:'.95rem'}}>{titles[rkey]||rep.label}</h3>
        <div style={{display:'flex',gap:6}}>
          <button className="btn btn-outline btn-xs"><Download size={11}/> PDF</button>
          <button className="btn btn-outline btn-xs"><Download size={11}/> Excel</button>
        </div>
      </div>
      {bodies[rkey] || <ComingSoon report={rep}/>}
    </>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function FinancialReports({ userId }) {
  const [sel,           setSel]           = useState('pl')
  const [dbSt,          setDbSt]          = useState(null)
  const [exp,           setExp]           = useState({'📈 Financial Performance':true,'📋 Financial Statements':true})
  const [hasProReports, setHasProReports] = useState(false)

  useEffect(()=>{ if(userId) http.get(`/db/stats/${userId}`).then(r=>setDbSt(r.data)).catch(()=>{}) },[userId])

  // Check plan — Vault gets P&L + Balance Sheet only; Pro+ gets all reports
  useEffect(()=>{
    if(!userId) return
    http.get(`/payments/my-plan/${userId}`).then(r=>{
      const planId = r.data?.plan_id || 'base'
      const VAULT_PLANS = new Set(['base','accounting_starter',''])
      setHasProReports(!VAULT_PLANS.has(planId))
    }).catch(()=>{})
  },[userId])

  const totalReports = MENU.flatMap(g=>g.items).length
  const liveReports  = MENU.flatMap(g=>g.items).filter(i=>i.live).length
  const FREE_REPORTS = new Set(['pl', 'balance_sheet'])
  const canViewReport = (key) => hasProReports || FREE_REPORTS.has(key)

  return (
    <div style={{padding:24}}>
      <div style={{marginBottom:16,display:'flex',alignItems:'center',gap:12}}>
        <span style={{fontSize:'.78rem',color:'var(--text-3)'}}>
          {liveReports} live · {totalReports-liveReports} coming soon · {totalReports} total reports
        </span>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'240px 1fr',gap:20,alignItems:'start'}}>
        {/* Sidebar */}
        <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'var(--r-lg)',
          overflow:'hidden',boxShadow:'var(--sh-xs)',position:'sticky',top:0,maxHeight:'82vh',overflowY:'auto'}}>
          <div style={{padding:'10px 13px',borderBottom:'1px solid var(--border)',background:'var(--surface-2)',
            fontSize:'.73rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.06em'}}>
            All Reports
          </div>
          {MENU.map(group => {
            const open = exp[group.group] !== false
            return (
              <div key={group.group}>
                <button onClick={()=>setExp(p=>({...p,[group.group]:!open}))}
                  style={{width:'100%',textAlign:'left',padding:'6px 12px',border:'none',cursor:'pointer',
                    fontFamily:'inherit',background:'var(--surface-2)',fontSize:'.7rem',fontWeight:700,
                    color:group.color,textTransform:'uppercase',letterSpacing:'.04em',
                    borderTop:'1px solid var(--border)',display:'flex',alignItems:'center',justifyContent:'space-between'}}>
                  <span>{group.group}</span>
                  {open?<ChevronDown size={10}/>:<ChevronRight size={10}/>}
                </button>
                {open && group.items.map(item=>{
                  const locked = item.live && !canViewReport(item.key)
                  return (
                    <button key={item.key}
                      onClick={()=>{ if(item.live && !locked) setSel(item.key) }}
                      title={locked?'Upgrade to Accounting Pro':undefined}
                      style={{width:'100%',textAlign:'left',padding:'7px 14px',border:'none',
                        cursor:(item.live&&!locked)?'pointer':'default',fontFamily:'inherit',
                        background:sel===item.key?'var(--brand)':'transparent',
                        color:sel===item.key?'#fff':item.live?'var(--text-2)':'var(--text-3)',
                        fontSize:'.81rem',fontWeight:sel===item.key?700:400,
                        transition:'background .1s,color .1s',opacity:item.live?1:0.6,
                        display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                      <span>{item.label}</span>
                      {!item.live&&(
                        <span style={{fontSize:'.6rem',padding:'1px 4px',borderRadius:3,
                          background:sel===item.key?'rgba(255,255,255,.2)':'#fef3c7',
                          color:sel===item.key?'#fff':'#92400e',fontWeight:700}}>Soon</span>
                      )}
                      {item.live&&locked&&(
                        <span style={{fontSize:'.6rem',padding:'1px 4px',borderRadius:3,
                          background:sel===item.key?'rgba(255,255,255,.2)':'#fee2e2',
                          color:sel===item.key?'#fff':'#991b1b',fontWeight:700}}>Pro</span>
                      )}
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>

        {/* Report body */}
        <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'var(--r-lg)',
          overflow:'hidden',boxShadow:'var(--sh-xs)',minHeight:500}}>
          <ReportBody rkey={sel} userId={userId} dbStats={dbSt} hasProReports={hasProReports}/>
        </div>
      </div>
    </div>
  )
}
