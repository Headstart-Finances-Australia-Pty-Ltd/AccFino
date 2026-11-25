/**
 * TaxReturnData — Australian Individual Tax Return Data Aggregator
 * Covers all major income, deduction and offset items from the ATO
 * Individual tax return (ITR) for Australian residents.
 *
 * Sections match the ATO myTax / Tax Return for Individuals (supplementary) form:
 *  - Income: salary, interest, dividends, rent, capital gains, business, foreign
 *  - Deductions: work expenses, D1-D15, rental deductions, donations
 *  - Tax Offsets: LITO, LMITO, seniors, private health offset
 *  - Medicare
 *  - HELP / HECS repayment
 *
 * Links with AccFino's reconciliation DB (future: auto-populate from classified txns)
 */
import React, { useState, useEffect } from 'react'
import { Plus, Trash2, ChevronDown, ChevronRight, Download, Info } from 'lucide-react'
import axios from 'axios'

const http = axios.create({ baseURL: '/api', withCredentials: true })
http.interceptors.request.use(cfg => {
  try { const u = JSON.parse(localStorage.getItem('af_user')||'{}'); if (u.token) cfg.headers['Authorization'] = `Bearer ${u.token}` } catch {}
  return cfg
})

const fmtAUD = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',minimumFractionDigits:2}).format(n||0)
const CY = new Date().getFullYear()
const FYS = [`${CY-1}–${CY}`,`${CY-2}–${CY-1}`,`${CY-3}–${CY-2}`]

// ── Tax calculation helpers ───────────────────────────────────────────────────
function calcTax(taxableIncome) {
  // ATO 2024-25 individual tax rates (resident)
  if (taxableIncome <= 18200)  return 0
  if (taxableIncome <= 45000)  return (taxableIncome - 18200) * 0.19
  if (taxableIncome <= 120000) return 5092 + (taxableIncome - 45000) * 0.325
  if (taxableIncome <= 180000) return 29467 + (taxableIncome - 120000) * 0.37
  return 51667 + (taxableIncome - 180000) * 0.45
}

function calcLITO(income) {
  if (income <= 37500) return 700
  if (income <= 45000) return 700 - (income - 37500) * 0.05
  if (income <= 66667) return 325 - (income - 45000) * 0.015
  return 0
}

function calcMedicare(income) {
  // 2% Medicare levy with low-income threshold
  if (income <= 26000) return 0
  if (income <= 32500) return income * 0.1
  return income * 0.02
}

function calcHECS(repayableDebt, income) {
  if (!repayableDebt || income < 54435) return 0
  // Simplified HELP repayment rates 2024-25
  if (income < 62738)  return income * 0.01
  if (income < 66502)  return income * 0.02
  if (income < 70048)  return income * 0.025
  if (income < 73788)  return income * 0.03
  if (income < 77723)  return income * 0.035
  if (income < 81872)  return income * 0.04
  if (income < 86236)  return income * 0.045
  if (income < 90820)  return income * 0.05
  if (income < 95631)  return income * 0.055
  if (income < 100678) return income * 0.06
  if (income < 105996) return income * 0.065
  if (income < 111589) return income * 0.07
  if (income < 117481) return income * 0.075
  if (income < 123728) return income * 0.08
  if (income < 130093) return income * 0.085
  if (income < 136723) return income * 0.09
  if (income < 143825) return income * 0.095
  return income * 0.1
}

// ── Collapsible section ───────────────────────────────────────────────────────
function TaxSection({ title, total, color='var(--brand)', children, defaultOpen=true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{marginBottom:8,border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
      <button onClick={() => setOpen(o=>!o)} style={{
        width:'100%',display:'flex',alignItems:'center',justifyContent:'space-between',
        padding:'12px 16px',background:'var(--surface-2)',border:'none',cursor:'pointer',
        fontFamily:'inherit',borderLeft:`4px solid ${color}`,
      }}>
        <div style={{display:'flex',alignItems:'center',gap:8}}>
          {open ? <ChevronDown size={14} color="var(--text-3)"/> : <ChevronRight size={14} color="var(--text-3)"/>}
          <span style={{fontWeight:700,fontSize:'.875rem'}}>{title}</span>
        </div>
        {total != null && (
          <span style={{fontFamily:'var(--font-mono)',fontWeight:700,
            color:total<0?'var(--success)':'var(--text-1)'}}>{fmtAUD(Math.abs(total))}</span>
        )}
      </button>
      {open && <div style={{padding:16}}>{children}</div>}
    </div>
  )
}

// ── Number input row ──────────────────────────────────────────────────────────
function TaxRow({ label, field, value, onChange, hint, ato_ref, negative }) {
  return (
    <div style={{display:'flex',alignItems:'center',gap:12,marginBottom:8,
      padding:'6px 10px',borderRadius:'var(--r-sm)',
      background:'var(--surface)',border:'1px solid var(--border)'}}>
      <div style={{flex:1}}>
        <div style={{fontSize:'.82rem',fontWeight:500,color:'var(--text-1)'}}>{label}</div>
        {(hint || ato_ref) && (
          <div style={{fontSize:'.71rem',color:'var(--text-3)',marginTop:1}}>
            {ato_ref && <span style={{fontFamily:'var(--font-mono)',marginRight:6,color:'var(--brand)'}}>Item {ato_ref}</span>}
            {hint}
          </div>
        )}
      </div>
      <div style={{display:'flex',alignItems:'center',gap:4}}>
        {negative && <span style={{fontSize:'.8rem',color:'var(--text-3)'}}>–</span>}
        <span style={{fontSize:'.8rem',color:'var(--text-3)'}}>$</span>
        <input type="number" min="0" step="0.01"
          style={{width:120,textAlign:'right',fontFamily:'var(--font-mono)',fontSize:'.85rem',
            padding:'4px 8px',border:'1px solid var(--border)',borderRadius:'var(--r-sm)',
            background:'var(--surface-2)',color:'var(--text-1)'}}
          value={value||''}
          onChange={e => onChange(field, parseFloat(e.target.value)||0)}/>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function TaxReturnData() {
  const [fy, setFy] = useState(FYS[0])
  const [data, setData] = useState({
    // Income
    salary:0, allowances:0, employer_super:0,
    interest:0, dividends:0, franking_credits:0,
    rent_income:0, trust_income:0, partnership_income:0,
    business_income:0, foreign_income:0,
    capital_gains:0, cgt_discount:0,   // from crypto/stocks/property
    govt_payments:0, other_income:0,
    // Deductions
    work_car:0, work_travel:0, work_clothing:0, work_tools:0,
    work_education:0, work_home_office:0, work_other:0,
    tax_agent_fees:0, interest_investments:0,
    donations:0, low_value_pool:0,
    rent_interest:0, rent_agent_fees:0, rent_repairs:0,
    rent_depreciation:0, rent_rates:0, rent_insurance:0, rent_other:0,
    other_deductions:0,
    // Tax details
    withholding:0, help_debt:0, private_health_rebate:0,
    spouse_income:0, has_private_health: false,
  })

  const set = (field, val) => setData(d => ({...d, [field]: val}))
  const R = (label, field, hint, ato_ref, neg=false) =>
    <TaxRow label={label} field={field} value={data[field]} onChange={set} hint={hint} ato_ref={ato_ref} negative={neg}/>

  // ── Calculations ─────────────────────────────────────────────────────────────
  const grossIncome = [
    data.salary, data.allowances, data.interest, data.dividends,
    data.franking_credits, data.rent_income, data.trust_income,
    data.partnership_income, data.business_income, data.foreign_income,
    data.capital_gains, data.govt_payments, data.other_income,
  ].reduce((s,v)=>s+(v||0), 0)

  const workDeductions = [
    data.work_car, data.work_travel, data.work_clothing, data.work_tools,
    data.work_education, data.work_home_office, data.work_other,
  ].reduce((s,v)=>s+(v||0), 0)

  const otherDeductions = [
    data.tax_agent_fees, data.interest_investments, data.donations,
    data.low_value_pool, data.other_deductions,
  ].reduce((s,v)=>s+(v||0), 0)

  const rentDeductions = [
    data.rent_interest, data.rent_agent_fees, data.rent_repairs,
    data.rent_depreciation, data.rent_rates, data.rent_insurance, data.rent_other,
  ].reduce((s,v)=>s+(v||0), 0)

  const totalDeductions = workDeductions + otherDeductions + rentDeductions
  const taxableIncome   = Math.max(0, grossIncome - totalDeductions - (data.cgt_discount||0))
  const grossTax        = calcTax(taxableIncome)
  const lito            = calcLITO(taxableIncome)
  const medicare        = calcMedicare(taxableIncome)
  const hecsRepayment   = calcHECS(data.help_debt, taxableIncome)
  const taxPayable      = Math.max(0, grossTax - lito - (data.private_health_rebate||0) - (data.franking_credits||0))
  const totalLiability  = taxPayable + medicare + hecsRepayment
  const withheld        = data.withholding || 0
  const refundOrPayable = withheld - totalLiability

  return (
    <div style={{padding:24}}>
      <div style={{marginBottom:22}}>
        <h1>🗂 Tax Return Data</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          Australian Individual Tax Return (ITR) · All income, deductions, offsets · ATO-compliant estimates
        </p>
      </div>

      {/* FY selector + summary */}
      <div style={{display:'flex',gap:12,marginBottom:20,alignItems:'flex-start',flexWrap:'wrap'}}>
        <div className="input-group" style={{minWidth:160}}>
          <label>Financial Year</label>
          <select className="input input-sm" value={fy} onChange={e=>setFy(e.target.value)}>
            {FYS.map(f=><option key={f}>{f}</option>)}
          </select>
        </div>

        {/* Live estimate strip */}
        <div style={{display:'grid',gridTemplateColumns:'repeat(5,1fr)',gap:10,flex:1,minWidth:600}}>
          {[
            {l:'Gross Income',      v:fmtAUD(grossIncome),      c:'#16a34a'},
            {l:'Total Deductions',  v:fmtAUD(totalDeductions),  c:'#d97706'},
            {l:'Taxable Income',    v:fmtAUD(taxableIncome),    c:'var(--text-1)'},
            {l:'Tax Payable',       v:fmtAUD(totalLiability),   c:'var(--danger)'},
            {l:refundOrPayable>=0?'Est. Refund':'Est. Tax Owing',
              v:fmtAUD(Math.abs(refundOrPayable)),
              c:refundOrPayable>=0?'#16a34a':'var(--danger)'},
          ].map(({l,v,c})=>(
            <div key={l} style={{background:'var(--surface)',border:'1px solid var(--border)',
              borderRadius:'var(--r-lg)',padding:'10px 12px',boxShadow:'var(--sh-xs)',textAlign:'center'}}>
              <div style={{fontSize:'.68rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',marginBottom:4}}>{l}</div>
              <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.92rem',color:c}}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16}}>
        <div>
          {/* Income */}
          <TaxSection title="💰 Income" total={grossIncome} color="#16a34a">
            <div style={{marginBottom:8,padding:'6px 10px',background:'#dcfce7',borderRadius:'var(--r-sm)',
              fontSize:'.72rem',color:'#166534',fontWeight:600}}>Employment Income</div>
            {R('Salary, Wages & Allowances','salary','Total gross salary from payment summaries / income statement','1')}
            {R('Allowances, Loadings & Bonuses','allowances','Allowances separate from salary','2')}
            {R('Employer Super Contributions','employer_super','Concessional contributions (SG + salary sacrifice)','12')}

            <div style={{marginTop:10,marginBottom:8,padding:'6px 10px',background:'#dbeafe',borderRadius:'var(--r-sm)',
              fontSize:'.72rem',color:'#1e40af',fontWeight:600}}>Investment Income</div>
            {R('Interest','interest','Bank interest, term deposits','10')}
            {R('Dividends (unfranked)','dividends','Dividends received','11')}
            {R('Franking Credits','franking_credits','Imputation credits on dividends — offset against tax','11')}
            {R('Capital Gains (net)','capital_gains','Net capital gain after CGT discount (from Trading / Property tabs)','18')}

            <div style={{marginTop:10,marginBottom:8,padding:'6px 10px',background:'#fef3c7',borderRadius:'var(--r-sm)',
              fontSize:'.72rem',color:'#92400e',fontWeight:600}}>Rental & Business</div>
            {R('Rent / Gross Rental Income','rent_income','Total gross rent received','21')}
            {R('Business Income','business_income','Net income from business / sole trader','13')}
            {R('Partnership / Trust Income','partnership_income','Your share of net income','13')}

            <div style={{marginTop:10,marginBottom:8,padding:'6px 10px',background:'#f3f4f6',borderRadius:'var(--r-sm)',
              fontSize:'.72rem',color:'#374151',fontWeight:600}}>Other Income</div>
            {R('Foreign Income','foreign_income','Foreign employment or investment income','20')}
            {R('Government Payments','govt_payments','JobSeeker, Parental Leave, Youth Allowance','5')}
            {R('Other Income','other_income','Super lump sums, insurance, other assessable income','24')}
          </TaxSection>

          {/* Deductions */}
          <TaxSection title="🔻 Work-Related Deductions" total={-workDeductions} color="#d97706" defaultOpen={false}>
            {R('Car Expenses (cents/km or logbook)','work_car','Work-related car travel — not home to work','D1')}
            {R('Travel Expenses (not car)','work_travel','Fares, accommodation for work travel','D2')}
            {R('Clothing, Laundry & Dry-cleaning','work_clothing','Uniforms, protective clothing, occupation-specific','D3')}
            {R('Self-Education Expenses','work_education','Courses, textbooks related to current work','D4')}
            {R('Tools, Equipment & Other Assets','work_tools','Tools under $300 or depreciation on larger items','D5')}
            {R('Home Office Expenses','work_home_office','67c/hr fixed rate or actual method','D5')}
            {R('Other Work-Related Expenses','work_other','Union fees, professional memberships, phone (work %)','D5')}
          </TaxSection>

          <TaxSection title="🔻 Other Deductions" total={-otherDeductions} color="#7c3aed" defaultOpen={false}>
            {R('Tax Agent Fees','tax_agent_fees','Accountant / tax agent preparation fees','D10')}
            {R('Investment Interest','interest_investments','Interest on loans to buy investments','D8')}
            {R('Gifts & Donations','donations','DGR-registered charities only','D9')}
            {R('Low Value Pool Deductions','low_value_pool','Low value and software development pools','D6')}
            {R('Other Deductions','other_deductions','Income protection insurance, other deductions','D15')}
          </TaxSection>

          <TaxSection title="🔻 Rental Property Deductions" total={-rentDeductions} color="#0891b2" defaultOpen={false}>
            {R('Loan Interest','rent_interest','Interest on investment property loan','21')}
            {R('Agent Management Fees','rent_agent_fees','Real estate agent fees for rental management','21')}
            {R('Repairs & Maintenance','rent_repairs','Repairs (not capital improvements)','21')}
            {R('Depreciation / Capital Works','rent_depreciation','Div 43 / Div 40 building and plant depreciation','21')}
            {R('Council Rates & Water','rent_rates','','21')}
            {R('Landlord Insurance','rent_insurance','','21')}
            {R('Other Rental Expenses','rent_other','Advertising, cleaning, pest control, strata fees','21')}
          </TaxSection>
        </div>

        <div>
          {/* Tax calculation summary */}
          <TaxSection title="📋 Tax Calculation Summary" color="var(--brand)">
            {[
              ['Gross Income',              fmtAUD(grossIncome),         '#16a34a'],
              ['Less: Total Deductions',    `(${fmtAUD(totalDeductions)})`, '#d97706'],
              ['Less: CGT Discount',        `(${fmtAUD(data.cgt_discount||0)})`, '#7c3aed'],
              ['= Taxable Income',          fmtAUD(taxableIncome),        'var(--text-1)', true],
              ['Gross Tax',                 fmtAUD(calcTax(taxableIncome)), 'var(--danger)'],
              ['Less: LITO',                `(${fmtAUD(lito)})`,          '#16a34a'],
              ['Less: Franking Credits',    `(${fmtAUD(data.franking_credits||0)})`, '#2563eb'],
              ['Less: PHI Rebate',          `(${fmtAUD(data.private_health_rebate||0)})`, '#16a34a'],
              ['= Tax Payable',             fmtAUD(taxPayable),           'var(--danger)', true],
              ['+ Medicare Levy (2%)',       fmtAUD(medicare),             '#d97706'],
              ['+ HELP/HECS Repayment',     fmtAUD(hecsRepayment),        '#7c3aed'],
              ['= Total Liability',         fmtAUD(totalLiability),       'var(--danger)', true],
              ['Less: Tax Withheld (PAYG)', `(${fmtAUD(withheld)})`,      '#16a34a'],
            ].map(([l,v,c,bold])=>(
              <div key={l} style={{display:'flex',justifyContent:'space-between',
                padding:bold?'10px 0':'6px 0',
                borderBottom:bold?'2px solid var(--border)':'1px solid var(--border)',
                borderTop:bold?'1px solid var(--border)':'none',
                marginTop:bold?4:0}}>
                <span style={{fontSize:'.82rem',fontWeight:bold?700:400,color:'var(--text-2)'}}>{l}</span>
                <span style={{fontFamily:'var(--font-mono)',fontWeight:bold?700:500,fontSize:bold?'.88rem':'.82rem',color:c}}>{v}</span>
              </div>
            ))}
            <div style={{
              display:'flex',justifyContent:'space-between',padding:'14px 12px',marginTop:8,
              borderRadius:'var(--r-lg)',border:`2px solid ${refundOrPayable>=0?'#16a34a':'var(--danger)'}`,
              background:refundOrPayable>=0?'#dcfce7':'#fee2e2',
            }}>
              <span style={{fontWeight:700,fontSize:'.9rem',
                color:refundOrPayable>=0?'#166534':'#991b1b'}}>
                {refundOrPayable>=0 ? '💰 Estimated Refund' : '⚠️ Estimated Tax Owing'}
              </span>
              <span style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1.05rem',
                color:refundOrPayable>=0?'#166534':'#991b1b'}}>
                {fmtAUD(Math.abs(refundOrPayable))}
              </span>
            </div>
          </TaxSection>

          {/* Tax offsets & other */}
          <TaxSection title="🎯 Tax Offsets & Other" color="#2563eb" defaultOpen={false}>
            {R('PAYG Tax Withheld','withholding','From payment summaries / income statement','W1')}
            {R('HELP / HECS Outstanding Debt','help_debt','Your total outstanding HELP/HECS balance','')}
            {R('Private Health Insurance Rebate','private_health_rebate','PHI rebate if claimed as offset (not premium reduction)','')}
            <div className="input-group" style={{marginTop:8}}>
              <label style={{display:'flex',alignItems:'center',gap:6}}>
                <input type="checkbox" checked={!!data.has_private_health}
                  onChange={e=>set('has_private_health',e.target.checked)}/>
                I have private hospital cover (Medicare Levy Surcharge may not apply)
              </label>
            </div>
          </TaxSection>

          {/* ATO lodgement checklist */}
          <TaxSection title="✅ ATO Lodgement Checklist" color="#6b7280" defaultOpen={false}>
            {[
              {item:'Payment summary / income statement from employer', done: data.salary > 0},
              {item:'Bank interest statements', done: data.interest > 0},
              {item:'Dividend statements (unfranked + franked)', done: data.dividends > 0},
              {item:'CGT event records (crypto, shares, property)', done: data.capital_gains > 0},
              {item:'Rental property income & expense records', done: data.rent_income > 0},
              {item:'Work-related expense receipts', done: data.work_other > 0 || data.work_tools > 0},
              {item:'Tax agent invoice (D10)', done: data.tax_agent_fees > 0},
              {item:'Donation receipts (DGR charities)', done: data.donations > 0},
              {item:'Private health insurance statement', done: data.has_private_health},
              {item:'HELP account balance (ATO online services)', done: data.help_debt > 0},
            ].map(({item,done})=>(
              <div key={item} style={{display:'flex',alignItems:'flex-start',gap:8,
                padding:'6px 0',borderBottom:'1px solid var(--border)',fontSize:'.8rem'}}>
                <span style={{color:done?'#16a34a':'var(--text-3)',flexShrink:0,marginTop:1}}>
                  {done?'✅':'⬜'}
                </span>
                <span style={{color:done?'var(--text-1)':'var(--text-3)'}}>{item}</span>
              </div>
            ))}
          </TaxSection>

          {/* Disclaimer */}
          <div style={{marginTop:8,padding:'10px 14px',background:'#fef3c7',
            borderRadius:'var(--r-md)',border:'1px solid #fde68a',fontSize:'.74rem',color:'#92400e'}}>
            <strong>Important:</strong> This is an estimate only based on 2024–25 ATO tax rates.
            Actual tax may differ due to your full circumstances.
            Always lodge your tax return via myTax or a registered tax agent.
            ATO: <em>ato.gov.au/individuals-and-families/income-deductions-offsets-and-records</em>
          </div>
        </div>
      </div>
    </div>
  )
}
