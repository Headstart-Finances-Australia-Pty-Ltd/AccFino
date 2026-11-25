/**
 * SmartLendingPage — v3
 * Results match Saar/OPICA reference:
 *   LEFT  — Statement metadata · Category table (Items / Count / Total / Monthly)
 *           with expandable rows showing individual transactions
 *   RIGHT — Classification donut (Classified / Unknown %)
 *           Monthly finance bar chart (Income / Oneoff / Mandatory / Discretionary / Balance)
 *           High-level insights list
 *           Lending metrics panel (NDI / UMI / DSR / HEM / Risk / Serviceability)
 */
import React, { useState, useRef, useCallback } from 'react'
import {
  Upload, CheckCircle, XCircle, Clock, RefreshCw, X,
  Plus, Trash2, ChevronDown, ChevronRight, ChevronUp,
  TrendingUp, TrendingDown, AlertTriangle, Info,
} from 'lucide-react'
import { uploadMultipleStatements, analyseTransactions } from '../../lib/lendingApi.js'
import {
  PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts'
import toast from 'react-hot-toast'

const fmtAUD = n => n == null ? '—' : new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:2}).format(n)
const fmtPct = n => `${(n||0).toFixed(1)}%`
const fmtM   = n => `${(n||0).toFixed(2)}`

const FILE_ICONS = {pdf:'📄',csv:'📊',jpg:'🖼',jpeg:'🖼',png:'🖼',webp:'🖼'}
const fileExt  = f => (f||'').split('.').pop().toLowerCase()
const fileIcon = f => FILE_ICONS[fileExt(f)] || '📁'

// Category → display label with count placeholder
const CAT_LABELS = {
  'Food & Groceries':         'Food & Groceries',
  'Recreation':               'Recreation',
  'Clothing & Personal':      'Clothing & Personal',
  'Transport':                'Transport',
  'Fuel':                     'Fuel',
  'Health & Medical':         'Health & Medical',
  'Medicines and Supplements':'Medicines & Supplements',
  'Childcare':                'Childcare',
  'Education':                'Education',
  'Rent':                     'Rent',
  'Home Services':            'Home Services',
  'Electricity':              'Electricity',
  'Gas Bills':                'Gas Bills',
  'Water Bills':              'Water Bills',
  'Phone Bill':               'Phone Bill',
  'Internet':                 'Internet',
  'Health Insurance':         'Health Insurance',
  'Life Insurance':           'Life Insurance',
  'General Insurance':        'General Insurance',
  'Loans':                    'Loans',
  'Interest Payment':         'Interest Payment',
  'Credit Card Payment':      'Credit Card Payment',
  'Income':                   'Income',
  'Fund Transfer':            'Fund Transfer',
  'Cash Out':                 'Cash Out',
  'Gambling':                 'Gambling',
  'Hotel & Travel':           'Hotel & Travel',
  'Air Travel':               'Air Travel',
  'Goods':                    'Goods',
  'Beauty & Spas':            'Beauty & Spas',
  'Active Life':              'Active Life',
  'TV Subscription':          'TV Subscription',
  'Maintenance':              'Maintenance',
  'Services Charge':          'Services Charge',
  'Council Rates':            'Council Rates',
  'Car Parking':              'Car Parking',
  'Membership Fee':           'Membership Fee',
  'Public Services & Government': 'Government & Taxes',
  'Donation':                 'Donations',
  'Pets':                     'Pets',
  'Other':                    'Other / Unknown',
}

const MANDATORY_CATS = new Set([
  'Rent','Home Services','Electricity','Gas Bills','Water Bills','Phone Bill','Internet',
  'Food & Groceries','Transport','Fuel','Health & Medical','Medicines and Supplements',
  'Health Insurance','Life Insurance','General Insurance','Childcare','Education',
  'Loans','Interest Payment','Credit Card Payment','Council Rates','Maintenance',
])

const HOUSEHOLD_TYPES = [
  {value:'single_no_children', label:'Single — No children'},
  {value:'couple_no_children', label:'Couple — No children'},
  {value:'couple_1_child',     label:'Couple — 1 child'},
  {value:'couple_2_children',  label:'Couple — 2 children'},
]

// ── Small components ──────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const C = {
    pending:    {bg:'#fef3c7',color:'#92400e',icon:<Clock size={10}/>},
    extracting: {bg:'#dbeafe',color:'#1d4ed8',icon:<RefreshCw size={10}/>},
    done:       {bg:'#dcfce7',color:'#166534',icon:<CheckCircle size={10}/>},
    failed:     {bg:'#fee2e2',color:'#991b1b',icon:<XCircle size={10}/>},
  }[status] || {bg:'var(--surface-2)',color:'var(--text-3)',icon:null}
  return <span style={{display:'inline-flex',alignItems:'center',gap:3,padding:'2px 7px',
    borderRadius:100,fontSize:'.65rem',fontWeight:700,background:C.bg,color:C.color}}>
    {C.icon} {status}
  </span>
}

// ── Results panel sub-components ──────────────────────────────────────────────

/** Left panel: statement info + category table */
function CategoryTable({ transactions, meta, months, fileSummaries }) {
  const [expanded, setExpanded] = useState(new Set())
  const toggle = cat => setExpanded(s => { const n=new Set(s); n.has(cat)?n.delete(cat):n.add(cat); return n })

  // Group by category
  const groups = {}
  for (const t of transactions) {
    const cat  = t.category || 'Other'
    const isIn = t.is_income
    if (!groups[cat]) groups[cat] = {items:[], total:0, monthly:0}
    const amt = t.is_debit ? -(t.debit||0) : (t.credit||0)
    groups[cat].items.push(t)
    groups[cat].total   += isIn ? (t.credit||0) : -(t.debit||0)
    groups[cat].monthly += isIn ? (t.credit||0) : -(t.debit||0)
  }
  Object.values(groups).forEach(g => { g.monthly /= Math.max(months,1) })

  const sorted = Object.entries(groups)
    .sort(([,a],[,b]) => Math.abs(b.total) - Math.abs(a.total))

  const totalAmt   = sorted.reduce((s,[,g])=>s+g.total,0)
  const monthlyAmt = totalAmt / Math.max(months,1)

  // Statement metadata from file summaries
  const allDates = transactions.map(t=>t.date).filter(Boolean).sort()
  const dateFrom = allDates[0] || '—'
  const dateTo   = allDates[allDates.length-1] || '—'
  const nDays    = allDates.length > 1
    ? Math.round((new Date(dateTo)-new Date(dateFrom))/86400000)
    : 0
  const fileNames = (fileSummaries||[]).map(f=>f.filename)

  return (
    <div style={{display:'flex',flexDirection:'column',height:'100%'}}>
      {/* Statement metadata */}
      <div style={{padding:'10px 12px',background:'#fafafa',borderBottom:'1px solid var(--border)',
        fontSize:'.78rem',color:'var(--text-2)'}}>
        <div style={{fontWeight:700,color:'#1e40af',marginBottom:6}}>Statement period</div>
        <div>from: <strong>{dateFrom}</strong></div>
        <div>to: <strong>{dateTo}</strong></div>
        {nDays>0 && <div style={{marginTop:3}}>No of Days: <strong>{nDays}</strong></div>}
        {fileNames.length>0 && <>
          <div style={{fontWeight:700,color:'#1e40af',marginTop:8,marginBottom:3}}>File(s) processed</div>
          {fileNames.map((f,i)=><div key={i} style={{color:'var(--text-3)',fontSize:'.73rem'}}>{f}</div>)}
        </>}
        {meta?.bank && meta.bank !== 'unknown' &&
          <div style={{marginTop:4,color:'var(--text-3)',fontSize:'.73rem',textTransform:'capitalize'}}>
            Bank: {meta.bank} · {(meta.account_type||'').replace(/_/g,' ')}
          </div>}
      </div>

      {/* Table header */}
      <div style={{display:'grid',gridTemplateColumns:'1fr auto auto auto',
        padding:'6px 12px',background:'#e5e7eb',
        fontWeight:700,fontSize:'.73rem',color:'var(--text-2)',gap:8,flexShrink:0}}>
        <span>Items</span>
        <span style={{textAlign:'right',minWidth:90}}>Total Amount</span>
        <span style={{textAlign:'right',minWidth:90}}>Monthly Value</span>
        <span style={{width:16}}/>
      </div>

      {/* Category rows */}
      <div style={{flex:1,overflowY:'auto'}}>
        {sorted.map(([cat, g]) => {
          const open = expanded.has(cat)
          const isIncome = cat === 'Income' || g.total > 0
          const totalColor = isIncome ? '#166534' : '#991b1b'
          return (
            <React.Fragment key={cat}>
              {/* Category row */}
              <div
                onClick={()=>toggle(cat)}
                style={{display:'grid',gridTemplateColumns:'1fr auto auto auto',
                  padding:'5px 12px',cursor:'pointer',gap:8,
                  background: open ? '#f0f9ff' : 'transparent',
                  borderBottom:'1px solid var(--border)',alignItems:'center',
                  ':hover':{background:'#f9fafb'},
                }}>
                <span style={{fontSize:'.8rem',fontWeight:500,color:'var(--text-1)'}}>
                  {CAT_LABELS[cat]||cat} <span style={{color:'var(--text-3)',fontWeight:400}}>({g.items.length})</span>
                </span>
                <span style={{fontFamily:'var(--font-mono)',fontSize:'.78rem',
                  color:totalColor,textAlign:'right',minWidth:90}}>
                  {g.total.toFixed(2)}
                </span>
                <span style={{fontFamily:'var(--font-mono)',fontSize:'.78rem',
                  color:totalColor,textAlign:'right',minWidth:90}}>
                  {g.monthly.toFixed(2)}
                </span>
                <span style={{color:'var(--text-3)',width:16,display:'flex',justifyContent:'center'}}>
                  {open ? <ChevronUp size={11}/> : <ChevronDown size={11}/>}
                </span>
              </div>

              {/* Expanded transaction rows */}
              {open && g.items.map((t,i) => {
                const amt = t.is_debit ? -(t.debit||0) : (t.credit||0)
                return (
                  <div key={i} style={{display:'grid',gridTemplateColumns:'auto 1fr auto auto auto',
                    padding:'3px 12px 3px 28px',gap:8,alignItems:'center',
                    background:'#f8fafc',borderBottom:'1px solid #f1f5f9',fontSize:'.72rem',color:'var(--text-3)'}}>
                    <span style={{whiteSpace:'nowrap'}}>{t.date}</span>
                    <span style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}
                      title={t.description}>{t.description}</span>
                    <span style={{fontSize:'.65rem',padding:'1px 4px',borderRadius:3,
                      background:MANDATORY_CATS.has(cat)?'#dbeafe':'#fef3c7',
                      color:MANDATORY_CATS.has(cat)?'#1d4ed8':'#92400e',fontWeight:700,whiteSpace:'nowrap'}}>
                      {MANDATORY_CATS.has(cat)?'M':'D'}
                    </span>
                    <span style={{fontFamily:'var(--font-mono)',textAlign:'right',minWidth:80,
                      color:amt>=0?'#16a34a':'#dc2626'}}>
                      {amt.toFixed(2)}
                    </span>
                    <span style={{width:16}}/>
                  </div>
                )
              })}
            </React.Fragment>
          )
        })}

        {/* Balance row */}
        <div style={{display:'grid',gridTemplateColumns:'1fr auto auto auto',
          padding:'7px 12px',gap:8,borderTop:'2px solid var(--text-2)',
          background:'#f9fafb',fontWeight:700,fontSize:'.8rem'}}>
          <span>Balance</span>
          <span style={{fontFamily:'var(--font-mono)',textAlign:'right',minWidth:90,
            color:totalAmt>=0?'#166534':'#991b1b'}}>{totalAmt.toFixed(2)}</span>
          <span style={{fontFamily:'var(--font-mono)',textAlign:'right',minWidth:90,
            color:monthlyAmt>=0?'#166534':'#991b1b'}}>{monthlyAmt.toFixed(2)}</span>
          <span style={{width:16}}/>
        </div>
      </div>
    </div>
  )
}

/** Right panel: Classification donut + Finance bar + Insights + Metrics */
function AnalysisPanel({ transactions, metrics, months }) {
  const m    = metrics || {}
  const exp  = m.expenses || {}
  const lend = m.lending_metrics || {}
  const loan = m.loan_assessment || {}
  const risk = m.risk || {}
  const inc  = m.income || {}

  // Classification donut data
  const total      = transactions.length
  const classified = transactions.filter(t=>t.category && t.category!=='Other').length
  const unknown    = total - classified
  const classRate  = total>0 ? Math.round(classified/total*100) : 0
  const donutData  = [
    {name:`Classified`, value:classified, color:'#2563eb'},
    {name:`Unknown`,    value:unknown,    color:'#e5e7eb'},
  ]

  // Bar chart: Income / Oneoff / Mandatory Spend / Discretionary / Balance
  const income    = inc.total_monthly || 0
  const mandatory = exp.total_mandatory || 0
  const disc      = exp.total_discretionary || 0
  const balance   = income - mandatory - disc

  // Separate income into regular vs one-off
  const incomeRegular = inc.regular_monthly || income
  const incomeOneoff  = income - incomeRegular

  const barData = [
    {name:'Income\nRegular', value: incomeRegular,  fill:'#dc2626'},
    {name:'Payment\nOneoff', value: incomeOneoff,   fill:'#9ca3af'},
    {name:'Mandatory\nSpend',value: mandatory,      fill:'#60a5fa'},
    {name:'Discretionary\nExpense', value:disc,     fill:'#4ade80'},
    {name:'Balance',         value: balance,        fill: balance>=0?'#16a34a':'#dc2626'},
  ]

  // Percentage labels for bar chart
  const barPct = [
    income>0 ? Math.round(incomeRegular/income*100) : 0,
    income>0 ? Math.round(incomeOneoff/income*100)  : 0,
    income>0 ? Math.round(mandatory/income*100)     : 0,
    income>0 ? Math.round(disc/income*100)          : 0,
    income>0 ? Math.round(Math.abs(balance)/income*100):0,
  ]

  // High-level insights (matching Saar's ∎-style bullet list)
  const insights = []
  if (income > 0) {
    const houseExpRatio = ((mandatory/income)*100).toFixed(0)
    if (mandatory/income > 0.30) {
      insights.push(`${houseExpRatio}% of income in household expense, which is more than 30% limit.`)
    } else {
      insights.push(`${houseExpRatio}% of income in household expense, within the 30% limit.`)
    }
    const discRatio = ((disc/income)*100).toFixed(0)
    insights.push(`${discRatio}% discretionary expense — can be reduced.`)
    if (lend.dsr > 43) {
      insights.push(`${lend.dsr.toFixed(1)}% of income goes to loans repayment, exceeding the 43% 'debt to income ratio' limit.`)
    } else if (lend.dsr > 0) {
      insights.push(`${lend.dsr.toFixed(1)}% of income to loans repayment — below the 43% limit.`)
    }
    if (lend.gambling_ratio > 5) {
      insights.push(`Gambling spend of ${fmtPct(lend.gambling_ratio)} of income — responsible lending concern.`)
    }
    if (lend.umi < 200) {
      insights.push(`UMI ${fmtAUD(lend.umi)}/month is below the minimum ${fmtAUD(200)} threshold.`)
    } else {
      insights.push(`Uncommitted monthly income (UMI) ${fmtAUD(lend.umi)} — serviceability buffer available.`)
    }
    if (loan.max_borrowing_capacity > 0) {
      insights.push(`Estimated maximum borrowing capacity: ${fmtAUD(loan.max_borrowing_capacity)}.`)
    }
  }

  const riskColor = {Low:'#16a34a',Medium:'#d97706',High:'#dc2626','Very High':'#9b1c1c'}[risk.category]||'#16a34a'

  const CustomLabel = ({ x, y, width, value, index }) => (
    <text x={x+width/2} y={y-4} textAnchor="middle"
      style={{fontSize:'9px',fontWeight:600,fill:'#374151'}}>
      {barPct[index] ? `${barPct[index]}%` : '0%'}
    </text>
  )

  return (
    <div style={{display:'flex',flexDirection:'column',height:'100%',gap:0}}>
      {/* Row 1: Donut + Bar chart side by side */}
      <div style={{display:'grid',gridTemplateColumns:'1fr 1.3fr',gap:0,
        borderBottom:'1px solid var(--border)',padding:'12px 10px'}}>

        {/* Classification donut */}
        <div style={{textAlign:'center'}}>
          <div style={{fontWeight:700,color:'#1e40af',fontSize:'.82rem',marginBottom:6}}>
            Classification
          </div>
          <div style={{position:'relative',height:160}}>
            <ResponsiveContainer width="100%" height={160}>
              <PieChart>
                <Pie data={donutData} cx="50%" cy="50%" innerRadius={42} outerRadius={68}
                  dataKey="value" startAngle={90} endAngle={-270}>
                  {donutData.map((e,i)=><Cell key={i} fill={e.color}/>)}
                </Pie>
                <Tooltip formatter={(v,n)=>[`${v} (${Math.round(v/total*100)}%)`,n]}/>
              </PieChart>
            </ResponsiveContainer>
            {/* Centre label */}
            <div style={{position:'absolute',top:'50%',left:'50%',
              transform:'translate(-50%,-50%)',textAlign:'center',pointerEvents:'none'}}>
              <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.85rem'}}>
                Total {total}
              </div>
            </div>
          </div>
          {/* Legend */}
          <div style={{display:'flex',justifyContent:'center',gap:12,fontSize:'.7rem',marginTop:4}}>
            <span style={{color:'#6b7280'}}>Unknown {unknown} ({100-classRate}%)</span>
          </div>
          <div style={{display:'flex',justifyContent:'center',gap:12,fontSize:'.7rem'}}>
            <span style={{color:'#2563eb'}}>Classified {classified} ({classRate}%)</span>
          </div>
        </div>

        {/* Bar chart */}
        <div>
          <div style={{fontWeight:700,color:'#1e40af',fontSize:'.82rem',marginBottom:6,textAlign:'center'}}>
            Monthly finance analysis
          </div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={barData} margin={{top:18,right:4,left:4,bottom:0}} barSize={28}>
              <CartesianGrid strokeDasharray="3 3" vertical={false}/>
              <XAxis dataKey="name" tick={{fontSize:7,fill:'#6b7280'}} tickLine={false}
                axisLine={false} interval={0}/>
              <YAxis tick={{fontSize:7}} width={38} tickFormatter={v=>`$${Math.abs(v/1000).toFixed(0)}k`}/>
              <Tooltip formatter={(v)=>[fmtAUD(v)]}/>
              <Bar dataKey="value" label={<CustomLabel/>}>
                {barData.map((e,i)=><Cell key={i} fill={e.fill}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div style={{display:'flex',justifyContent:'center',gap:8,flexWrap:'wrap',fontSize:'.65rem',marginTop:2}}>
            {barData.map(b=>(
              <span key={b.name} style={{display:'flex',alignItems:'center',gap:2}}>
                <span style={{width:8,height:8,borderRadius:2,background:b.fill,display:'inline-block'}}/>
                {b.name.replace('\n',' ')}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Row 2: High-level insights */}
      <div style={{padding:'10px 14px',borderBottom:'1px solid var(--border)'}}>
        <div style={{fontWeight:700,color:'#1e40af',fontSize:'.85rem',
          textDecoration:'underline',marginBottom:8}}>High level insights</div>
        {insights.length === 0 && (
          <div style={{fontSize:'.78rem',color:'var(--text-3)'}}>No income detected — upload a statement with salary/income transactions.</div>
        )}
        {insights.map((ins,i)=>(
          <div key={i} style={{display:'flex',gap:6,marginBottom:4,fontSize:'.78rem',color:'var(--text-2)'}}>
            <span style={{flexShrink:0,fontWeight:700}}>∎</span>
            <span>{ins}</span>
          </div>
        ))}
      </div>

      {/* Row 3: Lending metrics grid */}
      <div style={{padding:'10px 14px',flex:1}}>
        <div style={{fontWeight:700,color:'#1e40af',fontSize:'.85rem',marginBottom:8}}>
          Lending Metrics
          <span style={{marginLeft:10,padding:'2px 8px',borderRadius:100,fontSize:'.7rem',
            background:riskColor,color:'#fff',fontWeight:700}}>
            {risk.category||'—'} Risk {risk.score||0}/100
          </span>
        </div>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:6}}>
          {[
            ['NDI /mo',     fmtAUD(lend.ndi),                  lend.ndi<0],
            ['UMI /mo',     fmtAUD(lend.umi),                  lend.umi<200],
            ['DSR',         fmtPct(lend.dsr),                  lend.dsr>43],
            ['HH Exp %',    fmtPct(lend.household_expense_ratio), lend.household_expense_ratio>30],
            ['vs HEM',      `${(lend.actual_vs_hem_pct||0)>0?'+':''}${(lend.actual_vs_hem_pct||0).toFixed(0)}%`, false],
            ['Gambling',    fmtPct(lend.gambling_ratio),        lend.gambling_ratio>5],
            ...(loan.proposed_repayment>0 ? [
              ['Repayment/mo',fmtAUD(loan.proposed_repayment), loan.proposed_repayment>lend.umi],
              ['Max Borrow', fmtAUD(loan.max_borrowing_capacity), false],
              ['LTI',        `${(loan.lti||0).toFixed(2)}x`,   loan.lti>6],
              ['Post-loan UMI',fmtAUD(loan.serviced_umi),      loan.serviced_umi<200],
            ] : []),
          ].map(([l,v,w])=>(
            <div key={l} style={{padding:'5px 8px',background: w?'#fee2e2':'var(--surface-2)',
              borderRadius:'var(--r-sm)',border:`1px solid ${w?'#fca5a5':'var(--border)'}`}}>
              <div style={{fontSize:'.64rem',fontWeight:700,color:'var(--text-3)',marginBottom:2,textTransform:'uppercase'}}>{l}</div>
              <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.82rem',
                color:w?'#dc2626':'var(--text-1)'}}>{v}</div>
            </div>
          ))}
        </div>

        {/* ASIC risk flags */}
        {(risk.flags||[]).length > 0 && (
          <div style={{marginTop:10}}>
            <div style={{fontWeight:700,fontSize:'.75rem',color:'#92400e',marginBottom:4}}>Risk Flags</div>
            {(risk.flags||[]).map((f,i)=>(
              <div key={i} style={{fontSize:'.72rem',color:'#92400e',padding:'2px 0',
                display:'flex',gap:5}}>
                <span>∎</span><span>{f.replace(/^[🚨⚠️ℹ️✅]+\s*/,'')}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Gap report panel ──────────────────────────────────────────────────────────
function GapReport({ gap }) {
  if (!gap || !gap.flags) return null
  return (
    <div style={{borderTop:'1px solid var(--border)',padding:'10px 14px',background:'#fafafa'}}>
      <div style={{fontWeight:700,fontSize:'.8rem',color:'#1e40af',marginBottom:6}}>
        Traceability Report
        {gap.coverage_summary?.coverage_pct != null && (
          <span style={{marginLeft:8,fontWeight:400,color:'var(--text-3)',fontSize:'.72rem'}}>
            {gap.coverage_summary.coverage_pct}% coverage · {gap.coverage_summary.covered_days} days
          </span>
        )}
      </div>
      {gap.flags.map((f,i) => {
        const icon = f.startsWith('✅') ? '✅' : f.startsWith('🚨') ? '🚨' : f.startsWith('⚠️') ? '⚠️' : 'ℹ️'
        const colors = {'✅':'#166534|#dcfce7','🚨':'#991b1b|#fee2e2','⚠️':'#92400e|#fef3c7','ℹ️':'#1e40af|#eff6ff'}
        const [clr,bg] = (colors[icon]||'#6b7280|#f9fafb').split('|')
        return (
          <div key={i} style={{display:'flex',gap:6,padding:'4px 8px',marginBottom:3,
            borderRadius:'var(--r-sm)',background:bg,fontSize:'.75rem',color:clr}}>
            <span style={{flexShrink:0}}>{icon}</span>
            <span>{f.replace(/^[✅🚨⚠️ℹ️]+\s*/,'')}</span>
          </div>
        )
      })}
    </div>
  )
}


// ── TransactionsTab ────────────────────────────────────────────────────────────
/**
 * Shows all extracted transactions in tabular form:
 *  - Period validation banner (3-month check)
 *  - Max borrowing capacity prominently displayed
 *  - Grouped by source file + bank (collapsible)
 *  - Columns: Date · Description · Debit · Credit · Balance · Category · M/D
 *  - Running balance computed where bank statement balance is missing
 *  - Files outside reference period are highlighted and user warned
 */
function TransactionsTab({ transactions, fileSummaries, periodCheck, maxBorrowing, metrics }) {
  const [collapsed, setCollapsed] = useState(new Set())
  const [search,    setSearch]    = useState('')
  const [filterCat, setFilterCat] = useState('all')

  const toggle = key => setCollapsed(s => {
    const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n
  })

  const lend = metrics?.lending_metrics || {}
  const loan = metrics?.loan_assessment || {}
  const inc  = metrics?.income || {}

  // Group transactions by source_file
  const groups = {}
  for (const t of transactions) {
    const key = t.source_file || 'Unknown File'
    if (!groups[key]) groups[key] = []
    groups[key].push(t)
  }

  // Build file→bank map from fileSummaries
  const bankMap = {}
  ;(fileSummaries||[]).forEach(s => { bankMap[s.filename] = s.bank || '' })

  // Determine which files are outside the reference period
  const outsideFiles = new Set((periodCheck.files_outside||[]).map(f=>f.filename))

  // All categories for filter
  const allCats = ['all', ...new Set(transactions.map(t=>t.category||'Other').filter(Boolean))]

  // Filter transactions
  const filterTxns = txns => txns.filter(t => {
    const matchSearch = !search ||
      (t.description||'').toLowerCase().includes(search.toLowerCase()) ||
      (t.date||'').includes(search)
    const matchCat = filterCat === 'all' || (t.category||'Other') === filterCat
    return matchSearch && matchCat
  })

  // Running balance per group (use bank balance if available, else compute)
  const withRunningBalance = (txns) => {
    const hasBankBal = txns.some(t => t.balance != null && t.balance !== '' && t.balance !== undefined)
    if (hasBankBal) return txns.map(t => ({...t, _displayBal: t.balance}))
    // Compute running balance
    let bal = 0
    return txns.map(t => {
      bal += (t.credit||0) - (t.debit||0)
      return {...t, _displayBal: bal}
    })
  }

  const periodOk    = periodCheck.valid !== false
  const periodColor = periodOk ? '#166534' : '#991b1b'
  const periodBg    = periodOk ? '#dcfce7'  : '#fee2e2'
  const periodBdr   = periodOk ? '#86efac'  : '#fca5a5'

  return (
    <div style={{display:'flex',flexDirection:'column',height:'100%'}}>

      {/* ── Top: Max Borrowing + Period validation side by side ── */}
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:0,
        borderBottom:'2px solid var(--border)'}}>

        {/* Max Borrowing Capacity — prominent */}
        <div style={{padding:'16px 20px',
          background:'linear-gradient(135deg,#1e40af 0%,#2563eb 100%)',
          borderRight:'2px solid rgba(255,255,255,.15)'}}>
          <div style={{fontSize:'.72rem',fontWeight:700,color:'rgba(255,255,255,.7)',
            textTransform:'uppercase',letterSpacing:'.08em',marginBottom:4}}>
            Maximum Borrowing Capacity
          </div>
          <div style={{fontFamily:'var(--font-mono)',fontWeight:900,fontSize:'2rem',
            color:'#fff',lineHeight:1,marginBottom:6}}>
            {maxBorrowing > 0
              ? new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:0}).format(maxBorrowing)
              : '—'}
          </div>
          <div style={{fontSize:'.72rem',color:'rgba(255,255,255,.75)',lineHeight:1.5}}>
            {maxBorrowing > 0 ? (
              <>
                Based on UMI&nbsp;
                <strong style={{color:'#fff'}}>
                  {new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:0}).format(lend.umi||0)}/mo
                </strong>
                {' '}at assessment rate&nbsp;
                <strong style={{color:'#fff'}}>{(loan.assessment_rate_pct||0).toFixed(2)}%</strong>
                {' '}({metrics?.months_analysed||3}-month analysis)
              </>
            ) : 'Enter a proposed loan above to calculate'}
          </div>
          {/* Mini metric row */}
          {maxBorrowing > 0 && (
            <div style={{display:'flex',gap:16,marginTop:10,flexWrap:'wrap'}}>
              {[
                ['NDI', `${new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:0}).format(lend.ndi||0)}/mo`, lend.ndi<0],
                ['UMI', `${new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:0}).format(lend.umi||0)}/mo`, lend.umi<200],
                ['DSR', `${(lend.dsr||0).toFixed(1)}%`, lend.dsr>43],
                ['LTI', loan.lti > 0 ? `${(loan.lti||0).toFixed(2)}×` : '—', loan.lti>6],
              ].map(([l,v,w])=>(
                <div key={l} style={{textAlign:'center'}}>
                  <div style={{fontSize:'.6rem',color:'rgba(255,255,255,.6)',fontWeight:700,
                    textTransform:'uppercase',marginBottom:1}}>{l}</div>
                  <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.8rem',
                    color:w?'#fca5a5':'rgba(255,255,255,.9)'}}>{v}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Period validation */}
        <div style={{padding:'14px 18px',background:periodBg,
          border:`1px solid ${periodBdr}`,margin:0}}>
          <div style={{display:'flex',alignItems:'flex-start',gap:10}}>
            <span style={{fontSize:'1.3rem',flexShrink:0,marginTop:2}}>
              {periodOk ? '✅' : '⚠️'}
            </span>
            <div style={{flex:1}}>
              <div style={{fontWeight:700,color:periodColor,fontSize:'.85rem',marginBottom:4}}>
                {periodOk ? 'Period Validation Passed' : 'Period Validation Warning'}
              </div>
              <div style={{fontSize:'.78rem',color:periodColor,lineHeight:1.5}}>
                {periodCheck.message || 'Checking statement periods…'}
              </div>
              {periodCheck.months_covered != null && (
                <div style={{marginTop:6,display:'flex',gap:12,flexWrap:'wrap',fontSize:'.72rem'}}>
                  <span style={{color:periodColor,fontWeight:600}}>
                    📅 {periodCheck.reference_start} → {periodCheck.reference_end}
                  </span>
                  <span style={{color:periodColor,fontWeight:600}}>
                    📊 {periodCheck.months_covered} months
                  </span>
                </div>
              )}
              {(periodCheck.files_outside||[]).length > 0 && (
                <div style={{marginTop:8,padding:'6px 10px',background:'rgba(255,255,255,.5)',
                  borderRadius:'var(--r-sm)',fontSize:'.72rem',color:periodColor}}>
                  <strong>Files outside period:</strong>{' '}
                  {periodCheck.files_outside.map(f=>`${f.filename} (${f.start}→${f.end})`).join('; ')}
                  <div style={{marginTop:3,fontWeight:600}}>
                    ⚡ Transactions from these files are included but flagged.
                    ASIC RG 209 requires a consistent 3-month period.
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Search + filter bar ── */}
      <div style={{padding:'10px 16px',background:'var(--surface-2)',
        borderBottom:'1px solid var(--border)',display:'flex',gap:10,alignItems:'center',flexWrap:'wrap'}}>
        <div style={{position:'relative',flex:'1 1 240px'}}>
          <input
            className="input input-sm"
            placeholder="Search description, date…"
            value={search}
            onChange={e=>setSearch(e.target.value)}
            style={{width:'100%',paddingLeft:28}}/>
          <span style={{position:'absolute',left:8,top:'50%',transform:'translateY(-50%)',
            color:'var(--text-3)',pointerEvents:'none',fontSize:'.8rem'}}>🔍</span>
        </div>
        <select className="input input-sm" style={{width:'auto',minWidth:160}}
          value={filterCat} onChange={e=>setFilterCat(e.target.value)}>
          {allCats.map(c=><option key={c} value={c}>{c==='all'?'All Categories':c}</option>)}
        </select>
        <span style={{fontSize:'.75rem',color:'var(--text-3)',whiteSpace:'nowrap'}}>
          {transactions.length} transactions · {Object.keys(groups).length} file(s)
        </span>
        <button className="btn btn-ghost btn-xs"
          onClick={()=>setCollapsed(new Set(Object.keys(groups)))}
          style={{marginLeft:'auto'}}>Collapse all</button>
        <button className="btn btn-ghost btn-xs"
          onClick={()=>setCollapsed(new Set())}>Expand all</button>
      </div>

      {/* ── Transaction groups ── */}
      <div style={{flex:1,overflowY:'auto'}}>
        {Object.entries(groups).map(([filename, txns]) => {
          const bank       = bankMap[filename] || ''
          const isOutside  = outsideFiles.has(filename)
          const isCollapsed= collapsed.has(filename)
          const filtered   = filterTxns(txns)
          const withBal    = withRunningBalance(filtered)

          // Date range for this file
          const dates = txns.map(t=>t.date).filter(Boolean).sort()
          const dr    = dates.length ? `${dates[0]} → ${dates[dates.length-1]}` : ''

          // Totals for this file
          const totalDebit  = txns.reduce((s,t)=>s+(t.debit||0),0)
          const totalCredit = txns.reduce((s,t)=>s+(t.credit||0),0)

          return (
            <div key={filename} style={{borderBottom:'2px solid var(--border)'}}>
              {/* Group header */}
              <div
                onClick={()=>toggle(filename)}
                style={{
                  display:'flex',alignItems:'center',gap:10,
                  padding:'8px 14px',cursor:'pointer',
                  background: isOutside ? '#fff7ed' : 'var(--surface-2)',
                  borderLeft:`4px solid ${isOutside?'#f97316':'var(--brand)'}`,
                }}>
                <span style={{flexShrink:0,fontSize:'1rem'}}>
                  {isCollapsed ? '▶' : '▼'}
                </span>
                <span style={{fontSize:'1rem',flexShrink:0}}>📄</span>
                <div style={{flex:1,minWidth:0}}>
                  <div style={{fontWeight:700,fontSize:'.85rem',
                    overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                    {filename}
                    {isOutside && (
                      <span style={{marginLeft:8,padding:'1px 6px',borderRadius:100,
                        background:'#fed7aa',color:'#9a3412',fontSize:'.65rem',fontWeight:700}}>
                        ⚠ Outside Reference Period
                      </span>
                    )}
                  </div>
                  <div style={{fontSize:'.72rem',color:'var(--text-3)',marginTop:1,
                    display:'flex',gap:12,flexWrap:'wrap'}}>
                    {bank && bank!=='unknown' && (
                      <span style={{textTransform:'capitalize',fontWeight:600,color:'var(--brand)'}}>
                        🏦 {bank}
                      </span>
                    )}
                    {dr && <span>📅 {dr}</span>}
                    <span>{txns.length} transactions</span>
                  </div>
                </div>
                {/* File totals */}
                <div style={{display:'flex',gap:16,flexShrink:0,fontSize:'.75rem'}}>
                  <div style={{textAlign:'right'}}>
                    <div style={{color:'var(--text-3)',fontSize:'.65rem',marginBottom:1}}>DEBITS</div>
                    <div style={{fontFamily:'var(--font-mono)',fontWeight:700,color:'#dc2626'}}>
                      {new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:2}).format(totalDebit)}
                    </div>
                  </div>
                  <div style={{textAlign:'right'}}>
                    <div style={{color:'var(--text-3)',fontSize:'.65rem',marginBottom:1}}>CREDITS</div>
                    <div style={{fontFamily:'var(--font-mono)',fontWeight:700,color:'#16a34a'}}>
                      {new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:2}).format(totalCredit)}
                    </div>
                  </div>
                  <div style={{textAlign:'right'}}>
                    <div style={{color:'var(--text-3)',fontSize:'.65rem',marginBottom:1}}>NET</div>
                    <div style={{fontFamily:'var(--font-mono)',fontWeight:700,
                      color:(totalCredit-totalDebit)>=0?'#16a34a':'#dc2626'}}>
                      {new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:2}).format(totalCredit-totalDebit)}
                    </div>
                  </div>
                </div>
              </div>

              {/* Transaction table */}
              {!isCollapsed && (
                <div style={{overflowX:'auto'}}>
                  {filtered.length === 0 ? (
                    <div style={{padding:'12px 14px',fontSize:'.8rem',color:'var(--text-3)',textAlign:'center'}}>
                      No transactions match the current filter.
                    </div>
                  ) : (
                    <table style={{width:'100%',borderCollapse:'collapse',fontSize:'.78rem'}}>
                      <thead>
                        <tr style={{background:'#f1f5f9',borderBottom:'2px solid var(--border)'}}>
                          <th style={TH}>Date</th>
                          <th style={{...TH,textAlign:'left',minWidth:220}}>Description</th>
                          <th style={{...TH,textAlign:'right',minWidth:90}}>Debit</th>
                          <th style={{...TH,textAlign:'right',minWidth:90}}>Credit</th>
                          <th style={{...TH,textAlign:'right',minWidth:100}}>Balance</th>
                          <th style={{...TH,minWidth:120}}>Category</th>
                          <th style={{...TH,width:28}}>M/D</th>
                        </tr>
                      </thead>
                      <tbody>
                        {withBal.map((t,i) => {
                          const isMand = MANDATORY_CATS.has(t.category||'')
                          const bal    = t._displayBal
                          return (
                            <tr key={i} style={{
                              borderBottom:'1px solid #f1f5f9',
                              background: isOutside ? '#fffbf5' : (i%2===0?'#fff':'#fafafa'),
                            }}>
                              <td style={{...TD,whiteSpace:'nowrap',color:'var(--text-3)',
                                fontFamily:'var(--font-mono)',fontSize:'.73rem'}}>{t.date}</td>
                              <td style={{...TD,maxWidth:300,overflow:'hidden',
                                textOverflow:'ellipsis',whiteSpace:'nowrap'}}
                                title={t.description}>{t.description}</td>
                              <td style={{...TD,textAlign:'right',fontFamily:'var(--font-mono)',
                                color:'#dc2626',fontWeight:t.debit>0?600:300}}>
                                {t.debit>0 ? new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(t.debit) : ''}
                              </td>
                              <td style={{...TD,textAlign:'right',fontFamily:'var(--font-mono)',
                                color:'#16a34a',fontWeight:t.credit>0?600:300}}>
                                {t.credit>0 ? new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(t.credit) : ''}
                              </td>
                              <td style={{...TD,textAlign:'right',fontFamily:'var(--font-mono)',
                                fontSize:'.72rem',
                                color: bal==null ? 'var(--text-3)' : bal>=0 ? '#1e40af' : '#dc2626'}}>
                                {bal != null
                                  ? new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(bal)
                                  : '—'}
                              </td>
                              <td style={{...TD}}>
                                <span style={{fontSize:'.68rem',padding:'1px 5px',borderRadius:3,
                                  background:'var(--surface-2)',color:'var(--text-2)',
                                  whiteSpace:'nowrap'}}>
                                  {t.category||'Other'}
                                </span>
                              </td>
                              <td style={{...TD,textAlign:'center'}}>
                                <span style={{fontSize:'.65rem',fontWeight:800,
                                  color:isMand?'#1d4ed8':'#d97706',
                                  padding:'1px 4px',borderRadius:3,
                                  background:isMand?'#dbeafe':'#fef3c7'}}>
                                  {isMand?'M':'D'}
                                </span>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                      {/* File total row */}
                      <tfoot>
                        <tr style={{background:'#e5e7eb',borderTop:'2px solid var(--border)',fontWeight:700}}>
                          <td style={{...TD,color:'var(--text-2)'}} colSpan={2}>
                            {filename} — {filtered.length} transactions
                          </td>
                          <td style={{...TD,textAlign:'right',fontFamily:'var(--font-mono)',color:'#dc2626'}}>
                            {new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(
                              filtered.reduce((s,t)=>s+(t.debit||0),0))}
                          </td>
                          <td style={{...TD,textAlign:'right',fontFamily:'var(--font-mono)',color:'#16a34a'}}>
                            {new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(
                              filtered.reduce((s,t)=>s+(t.credit||0),0))}
                          </td>
                          <td colSpan={3}/>
                        </tr>
                      </tfoot>
                    </table>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const TH = {padding:'6px 10px',fontWeight:700,fontSize:'.72rem',color:'var(--text-2)',
  textTransform:'uppercase',letterSpacing:'.03em',whiteSpace:'nowrap',textAlign:'center'}
const TD = {padding:'5px 10px',verticalAlign:'middle'}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function SmartLendingPage() {
  const fileRef = useRef()
  const [files,         setFiles]         = useState([])
  const [dragging,      setDragging]      = useState(false)
  const [uploading,     setUploading]     = useState(false)
  const [uploadPct,     setUploadPct]     = useState(0)
  const [result,        setResult]        = useState(null)
  const [activeTab,     setActiveTab]     = useState('upload')
  const [proposedLoan,  setProposedLoan]  = useState('')
  const [interestRate,  setInterestRate]  = useState('6.5')
  const [loanTerm,      setLoanTerm]      = useState('30')
  const [householdType, setHouseholdType] = useState('single_no_children')
  const [manualTxns,    setManualTxns]    = useState([{date:'',description:'',debit:'',credit:''}])

  const addFiles = useCallback(incoming => {
    const ok = ['pdf','jpg','jpeg','png','webp','csv']
    const valid = Array.from(incoming).filter(f=>ok.includes(fileExt(f.name)))
    if (!valid.length) { toast.error('PDF, CSV, JPEG, PNG accepted'); return }
    setFiles(prev => {
      const existing = new Set(prev.map(f=>f.file.name+f.file.size))
      return [...prev, ...valid.filter(f=>!existing.has(f.name+f.size))
              .map(f=>({file:f,status:'pending',count:0,error:null,dateRange:null}))]
    })
  }, [])

  const onDrop  = e => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }
  const onDragO = e => { e.preventDefault(); setDragging(true)  }
  const onDragL = () => setDragging(false)

  const handleAnalyse = async () => {
    if (!files.length) { toast.error('Add at least one bank statement'); return }
    setUploading(true); setUploadPct(0)
    setFiles(p=>p.map(f=>({...f,status:'extracting'})))
    try {
      const fd = new FormData()
      files.forEach(({file})=>fd.append('files', file, file.name))
      fd.append('proposed_loan',   proposedLoan||'0')
      fd.append('interest_rate',   String(parseFloat(interestRate||'6.5')/100))
      fd.append('loan_term_years', loanTerm||'30')
      fd.append('household_type',  householdType)
      fd.append('analysis_months', '0')
      const { data } = await uploadMultipleStatements(fd, e=>{
        if (e.total) setUploadPct(Math.round(e.loaded/e.total*100))
      })
      const sumMap = {}
      ;(data.file_summaries||[]).forEach(s=>{ sumMap[s.filename]=s })
      setFiles(p=>p.map(f=>{
        const s=sumMap[f.file.name]
        return {...f, status:s?(s.ok?'done':'failed'):'done',
          count:s?.transaction_count||0, error:s?.error||null,
          dateRange:s?.date_range||null, method:s?.extraction_method}
      }))
      setResult(data)
      setActiveTab('results')
      toast.success(`✓ ${data.transaction_count} transactions · ${files.length} file(s)`)
    } catch(err) {
      toast.error(err.response?.data?.detail||'Analysis failed')
      setFiles(p=>p.map(f=>({...f,status:f.status==='extracting'?'failed':f.status})))
    } finally { setUploading(false) }
  }

  const handleManualAnalyse = async () => {
    const txns = manualTxns.filter(t=>t.description&&t.date)
    if (!txns.length) { toast.error('Add at least one transaction'); return }
    setUploading(true)
    try {
      const {data} = await analyseTransactions({
        transactions: txns.map(t=>({date:t.date,description:t.description,
          debit:parseFloat(t.debit||0),credit:parseFloat(t.credit||0)})),
        proposed_loan:parseFloat(proposedLoan||0), interest_rate:parseFloat(interestRate||6.5)/100,
        loan_term_years:parseInt(loanTerm||30), household_type:householdType, analysis_months:3,
      })
      setResult({...data, months_analysed:3, file_summaries:[], gap_report:{}})
      setActiveTab('results')
      toast.success(`✓ ${data.transactions?.length} transactions`)
    } catch(e) { toast.error(e.response?.data?.detail||'Failed') }
    finally { setUploading(false) }
  }

  // Merge meta from file_summaries
  const primaryMeta = result?.file_summaries?.[0] || {}

  return (
    <div style={{padding:24}}>
      <div style={{marginBottom:18}}>
        <h1>🏦 Smart Lending</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.88rem'}}>
          Upload bank statements · AI transaction extraction · Expense classification · Australian Responsible Lending (ASIC RG 209 · APRA · HEM)
        </p>
      </div>

      <div className="tabs-bar" style={{marginBottom:0}}>
        {[
          {key:'upload', label:'📤 Upload Statements'},
          {key:'manual', label:'✏️ Manual Entry'},
          {key:'results',label:`📊 Results${result?` (${result.transaction_count})`:''}`},
          {key:'txns',   label:`📋 Transactions${result?` (${result.transaction_count})`:''}`},
          {key:'guide',  label:'ℹ️ AU Framework'},
        ].map(t=>(
          <button key={t.key}
            className={`tab-btn${activeTab===t.key?' active':''}`}
            onClick={()=>(!result&&(t.key==='results'||t.key==='txns'))?null:setActiveTab(t.key)}
            style={!result&&(t.key==='results'||t.key==='txns')?{opacity:.4,cursor:'not-allowed'}:undefined}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderTop:'none',
        borderRadius:'0 0 var(--r-lg) var(--r-lg)',boxShadow:'var(--sh-sm)'}}>

        {/* ── UPLOAD ─────────────────────────────────────────────────────── */}
        {activeTab==='upload' && (
          <div style={{padding:24}}>
            <div style={{display:'grid',gridTemplateColumns:'1fr 320px',gap:20,alignItems:'start'}}>
              <div>
                {/* Drop zone */}
                <div
                  onDrop={onDrop} onDragOver={onDragO} onDragLeave={onDragL}
                  onClick={()=>fileRef.current?.click()}
                  style={{border:`2px dashed ${dragging?'var(--brand)':'var(--border)'}`,
                    borderRadius:'var(--r-xl)',padding:'28px 24px',textAlign:'center',cursor:'pointer',
                    background:dragging?'#eff6ff':'var(--surface-2)',transition:'all .15s',marginBottom:14}}>
                  <Upload size={30} color="var(--brand)" style={{marginBottom:8}}/>
                  <div style={{fontWeight:700,marginBottom:5}}>
                    Drag &amp; drop multiple bank statements, or click to browse
                  </div>
                  <div style={{fontSize:'.78rem',color:'var(--text-3)',lineHeight:1.7}}>
                    Mix <strong>PDF</strong> · <strong>JPEG/PNG</strong> · <strong>CSV</strong> · Up to 20 files<br/>
                    ANZ · CBA · Westpac · NAB · Macquarie · St George · Suncorp · HSBC
                  </div>
                  <input ref={fileRef} type="file" multiple
                    accept=".pdf,.jpg,.jpeg,.png,.webp,.csv"
                    style={{display:'none'}}
                    onChange={e=>addFiles(e.target.files)}/>
                </div>

                {files.length>0 && (
                  <div>
                    <div style={{display:'flex',justifyContent:'space-between',
                      alignItems:'center',marginBottom:8}}>
                      <span style={{fontWeight:700,fontSize:'.84rem'}}>
                        {files.length} file{files.length!==1?'s':''} queued
                      </span>
                      <button className="btn btn-ghost btn-xs"
                        onClick={()=>{setFiles([]);setResult(null)}}>Clear all</button>
                    </div>
                    {files.map((f,i)=>(
                      <div key={i} style={{display:'flex',alignItems:'center',gap:10,
                        padding:'7px 12px',background:'var(--surface-2)',
                        borderRadius:'var(--r-md)',border:'1px solid var(--border)',marginBottom:5}}>
                        <span style={{fontSize:'1.1rem',flexShrink:0}}>{fileIcon(f.file.name)}</span>
                        <div style={{flex:1,minWidth:0}}>
                          <div style={{fontWeight:600,fontSize:'.8rem',overflow:'hidden',
                            textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{f.file.name}</div>
                          <div style={{fontSize:'.68rem',color:'var(--text-3)',marginTop:1,display:'flex',gap:8}}>
                            <span>{(f.file.size/1024).toFixed(0)} KB</span>
                            {f.count>0 && <span>· {f.count} txns</span>}
                            {f.dateRange?.start && <span>· {f.dateRange.start} → {f.dateRange.end}</span>}
                            {f.method && <span style={{color:'#6366f1'}}>· {f.method}</span>}
                          </div>
                        </div>
                        <StatusBadge status={f.status}/>
                        {!uploading && <button style={{background:'none',border:'none',
                          cursor:'pointer',color:'var(--text-3)',padding:2}}
                          onClick={()=>setFiles(p=>p.filter((_,j)=>j!==i))}>
                          <X size={13}/>
                        </button>}
                      </div>
                    ))}
                  </div>
                )}

                {uploading && (
                  <div style={{marginTop:10}}>
                    <div style={{display:'flex',justifyContent:'space-between',
                      fontSize:'.73rem',marginBottom:3}}>
                      <span>Extracting &amp; classifying…</span><span>{uploadPct}%</span>
                    </div>
                    <div style={{height:5,background:'var(--surface-2)',borderRadius:3,overflow:'hidden'}}>
                      <div style={{height:'100%',width:`${uploadPct}%`,background:'var(--brand)',
                        borderRadius:3,transition:'width .2s'}}/>
                    </div>
                  </div>
                )}
              </div>

              {/* Params */}
              <div style={{background:'var(--surface-2)',borderRadius:'var(--r-lg)',
                border:'1px solid var(--border)',padding:16}}>
                <h4 style={{margin:'0 0 12px'}}>Assessment Parameters</h4>
                <div style={{display:'flex',flexDirection:'column',gap:9}}>
                  <div className="input-group" style={{margin:0}}>
                    <label>Household Type</label>
                    <select className="input input-sm" value={householdType} onChange={e=>setHouseholdType(e.target.value)}>
                      {HOUSEHOLD_TYPES.map(h=><option key={h.value} value={h.value}>{h.label}</option>)}
                    </select>
                  </div>
                  <div className="input-group" style={{margin:0}}>
                    <label>Proposed Loan (AUD)</label>
                    <input className="input input-sm" type="number" min="0" placeholder="0 = no loan assessment"
                      value={proposedLoan} onChange={e=>setProposedLoan(e.target.value)}/>
                  </div>
                  <div className="input-group" style={{margin:0}}>
                    <label>Interest Rate (%)</label>
                    <input className="input input-sm" type="number" step="0.1" min="0"
                      value={interestRate} onChange={e=>setInterestRate(e.target.value)}/>
                  </div>
                  <div className="input-group" style={{margin:0}}>
                    <label>Loan Term (years)</label>
                    <input className="input input-sm" type="number" min="1" max="30"
                      value={loanTerm} onChange={e=>setLoanTerm(e.target.value)}/>
                  </div>
                  <div style={{fontSize:'.71rem',color:'#1e40af',padding:'6px 8px',
                    background:'#eff6ff',borderRadius:'var(--r-sm)',border:'1px solid #bfdbfe'}}>
                    🏛 Assessment rate: <strong>{(parseFloat(interestRate||0)+3).toFixed(1)}%</strong> (contract + 3% APRA buffer)<br/>
                    📅 Statement period auto-detected from transaction dates
                  </div>
                </div>
                <button className="btn btn-primary" style={{width:'100%',marginTop:14}}
                  onClick={handleAnalyse} disabled={uploading||!files.length}>
                  {uploading ? <><span className="spinner spinner-sm"/> Extracting…</>
                    : `🔍 Analyse ${files.length||0} Statement${files.length!==1?'s':''}`}
                </button>
                {!files.length && <div style={{textAlign:'center',marginTop:6,
                  fontSize:'.7rem',color:'var(--text-3)'}}>Add files above to enable</div>}
              </div>
            </div>
          </div>
        )}

        {/* ── MANUAL ENTRY ───────────────────────────────────────────────── */}
        {activeTab==='manual' && (
          <div style={{padding:24}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:12}}>
              <h3 style={{margin:0}}>Manual Transaction Entry</h3>
              <button className="btn btn-outline btn-sm"
                onClick={()=>setManualTxns(p=>[...p,{date:'',description:'',debit:'',credit:''}])}>
                <Plus size={13}/> Add Row
              </button>
            </div>
            <div style={{overflowX:'auto'}}>
              <table className="data-table" style={{fontSize:'.8rem'}}>
                <thead><tr>
                  <th style={{minWidth:120}}>Date</th>
                  <th style={{minWidth:240}}>Description</th>
                  <th style={{width:120,textAlign:'right'}}>Debit ($)</th>
                  <th style={{width:120,textAlign:'right'}}>Credit ($)</th>
                  <th style={{width:36}}/>
                </tr></thead>
                <tbody>
                  {manualTxns.map((t,i)=>(
                    <tr key={i}>
                      <td><input className="cell-input" type="date" value={t.date}
                        onChange={e=>setManualTxns(p=>p.map((r,j)=>j===i?{...r,date:e.target.value}:r))}
                        style={{width:'100%'}}/></td>
                      <td><input className="cell-input" value={t.description}
                        onChange={e=>setManualTxns(p=>p.map((r,j)=>j===i?{...r,description:e.target.value}:r))}
                        placeholder="WOOLWORTHS, SALARY, RENT…" style={{width:'100%'}}/></td>
                      <td><input className="cell-input" type="number" min="0" step="0.01" value={t.debit}
                        onChange={e=>setManualTxns(p=>p.map((r,j)=>j===i?{...r,debit:e.target.value}:r))}
                        style={{textAlign:'right',width:'100%'}}/></td>
                      <td><input className="cell-input" type="number" min="0" step="0.01" value={t.credit}
                        onChange={e=>setManualTxns(p=>p.map((r,j)=>j===i?{...r,credit:e.target.value}:r))}
                        style={{textAlign:'right',width:'100%'}}/></td>
                      <td><button className="btn btn-danger btn-xs"
                        onClick={()=>setManualTxns(p=>p.filter((_,j)=>j!==i))}>
                        <Trash2 size={11}/></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:10,marginTop:12}}>
              <div className="input-group"><label>Household</label>
                <select className="input input-sm" value={householdType} onChange={e=>setHouseholdType(e.target.value)}>
                  {HOUSEHOLD_TYPES.map(h=><option key={h.value} value={h.value}>{h.label}</option>)}
                </select>
              </div>
              <div className="input-group"><label>Loan ($)</label>
                <input className="input input-sm" type="number" min="0" value={proposedLoan} onChange={e=>setProposedLoan(e.target.value)}/>
              </div>
              <div className="input-group"><label>Rate (%)</label>
                <input className="input input-sm" type="number" step="0.1" value={interestRate} onChange={e=>setInterestRate(e.target.value)}/>
              </div>
              <div className="input-group"><label>Term (yrs)</label>
                <input className="input input-sm" type="number" min="1" max="30" value={loanTerm} onChange={e=>setLoanTerm(e.target.value)}/>
              </div>
            </div>
            <button className="btn btn-primary" style={{marginTop:12}} onClick={handleManualAnalyse} disabled={uploading}>
              {uploading?<><span className="spinner spinner-sm"/> Analysing…</>:'📊 Run Analysis'}
            </button>
          </div>
        )}

        {/* ── RESULTS ────────────────────────────────────────────────────── */}
        {activeTab==='results' && result && (
          <div>
            {/* Main 2-panel layout exactly like Saar */}
            <div style={{display:'grid',gridTemplateColumns:'44% 56%',
              height:580,borderBottom:'1px solid var(--border)'}}>
              {/* LEFT: category table */}
              <div style={{borderRight:'1px solid var(--border)',overflow:'hidden',
                display:'flex',flexDirection:'column'}}>
                <CategoryTable
                  transactions={result.transactions||[]}
                  meta={primaryMeta}
                  months={result.months_analysed||3}
                  fileSummaries={result.file_summaries||[]}/>
              </div>
              {/* RIGHT: charts + insights + metrics */}
              <div style={{overflow:'hidden',display:'flex',flexDirection:'column'}}>
                <AnalysisPanel
                  transactions={result.transactions||[]}
                  metrics={result.metrics}
                  months={result.months_analysed||3}/>
              </div>
            </div>

            {/* Gap / traceability report */}
            <GapReport gap={result.gap_report||{}}/>

            {/* Footer bar: files processed */}
            <div style={{padding:'8px 14px',background:'var(--surface-2)',
              borderTop:'1px solid var(--border)',display:'flex',
              gap:16,flexWrap:'wrap',fontSize:'.74rem',color:'var(--text-3)'}}>
              {(result.file_summaries||[]).map((s,i)=>(
                <span key={i} style={{display:'flex',alignItems:'center',gap:4}}>
                  {fileIcon(s.filename)}
                  <span>{s.filename}</span>
                  <StatusBadge status={s.ok?'done':'failed'}/>
                  {s.ok && <span style={{color:'#16a34a',fontFamily:'var(--font-mono)'}}>{s.transaction_count} txns</span>}
                  {s.bank && s.bank!=='unknown' && <span style={{textTransform:'capitalize'}}>· {s.bank}</span>}
                </span>
              ))}
              {result.duplicate_count > 0 && (
                <span style={{marginLeft:'auto',color:'#d97706'}}>
                  🔁 {result.duplicate_count} duplicate(s) removed
                </span>
              )}
            </div>
          </div>
        )}

        {/* ── TRANSACTIONS TAB ──────────────────────────────────────────── */}
        {activeTab==='txns' && result && (
          <TransactionsTab
            transactions={result.transactions||[]}
            fileSummaries={result.file_summaries||[]}
            periodCheck={result.period_check||{}}
            maxBorrowing={result.max_borrowing_capacity||result.metrics?.loan_assessment?.max_borrowing_capacity||0}
            metrics={result.metrics||{}}
          />
        )}

        {/* ── GUIDE ──────────────────────────────────────────────────────── */}
        {activeTab==='guide' && (
          <div style={{padding:24,maxWidth:800}}>
            <h3>Australian Responsible Lending Framework</h3>
            {[
              {title:'🔍 Statement Extraction Engine', items:[
                'PDFs: AccFino\'s bank-specific parsers (ANZ, CBA, Westpac, NAB, Macquarie, HSBC, Suncorp, St George)',
                'Scanned PDFs & images: Claude AI vision extracts all transaction rows automatically',
                'CSV: auto-detect date, description, debit/credit columns from any bank export format',
                'Multiple files merged and deduplicated — overlapping statement dates handled automatically',
                'Traceability gaps (missing periods) are detected and flagged per ASIC requirements',
              ]},
              {title:'📊 Classification (2,387 keywords)', items:[
                '2,387 AU merchant keywords from the Saar classification database',
                'Each keyword maps to category (Food & Groceries, Rent, Transport, Loans etc.) + Mandatory/Discretionary flag',
                'Income detection: Salary, wages, Centrelink, dividends, rent received',
                'Loan detection: home loan, car loan, personal loan, BNPL, credit card repayments',
                'Unmatched transactions are flagged as "Other" — classification rate target is ≥80%',
              ]},
              {title:'🏛 ASIC RG 209 — Responsible Lending', items:[
                'Lenders must verify income and living expenses before approving credit',
                'Debt-to-income ratio must not exceed 43% (existing repayments ÷ gross income)',
                'Household expenses > 30% of income flagged for further review',
                'Gambling > 5% of income is a mandatory disclosure and responsible lending concern',
                'UMI (Uncommitted Monthly Income) must remain ≥$200/mo after all repayments',
              ]},
              {title:'🏦 APRA APS 220 / APG 223', items:[
                '3% serviceability buffer applied on top of the quoted interest rate',
                'Loans assessed at: contract rate + 3% (e.g. 6.5% contract → tested at 9.5%)',
                'Loan-to-Income ratio > 6× requires additional scrutiny from 2021 APRA guidelines',
                'At least 3 months continuous bank statements required; 12 months recommended',
              ]},
              {title:'📈 HEM — Household Expenditure Measure', items:[
                'Melbourne Institute quarterly benchmark for household living expenses',
                'Banks use HEM as minimum floor — whichever is higher: HEM or actual declared expenses',
                'Single adult no children: approximately $2,000/month basic benchmark',
                'Actual expenses significantly above HEM may indicate under-declaration in other files',
              ]},
            ].map(s=>(
              <div key={s.title} style={{marginBottom:12,border:'1px solid var(--border)',
                borderRadius:'var(--r-lg)',overflow:'hidden'}}>
                <div style={{padding:'8px 14px',background:'var(--surface-2)',fontWeight:700,fontSize:'.875rem'}}>{s.title}</div>
                <div style={{padding:'6px 14px'}}>
                  {s.items.map((item,i)=>(
                    <div key={i} style={{display:'flex',gap:7,padding:'4px 0',
                      borderBottom:i<s.items.length-1?'1px solid var(--border)':'none',
                      fontSize:'.79rem',color:'var(--text-2)'}}>
                      <span style={{color:'var(--brand)',flexShrink:0}}>▸</span>{item}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div style={{padding:'8px 12px',background:'#fef3c7',borderRadius:'var(--r-md)',
              border:'1px solid #fde68a',fontSize:'.73rem',color:'#92400e'}}>
              <strong>Disclaimer:</strong> Indicative analysis only — not credit advice.
              All lending decisions must be made by qualified credit professionals under the NCCP Act 2009.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
