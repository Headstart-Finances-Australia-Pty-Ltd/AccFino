/**
 * PropertyCGT — Australian Property Capital Gains Tax Calculator
 * Covers: purchase/sale dates, cost base, improvements, agent fees,
 * CGT discount (50% for >12 months), main residence exemption
 */
import React, { useState } from 'react'
import { Plus, Trash2, Calculator, Download, Info } from 'lucide-react'
import toast from 'react-hot-toast'

const fmtAUD = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',minimumFractionDigits:2}).format(n||0)

const EMPTY_PROP = {
  address:'', purchase_date:'', sale_date:'',
  purchase_price:0, stamp_duty:0, legal_purchase:0, renovation:0,
  sale_price:0, agent_commission:0, legal_sale:0, advertising:0,
  main_residence_pct:0,
  notes:'',
}

function daysBetween(d1, d2) {
  return Math.abs((new Date(d2) - new Date(d1)) / 86400000)
}

function calcCGT(prop) {
  const p = prop
  // Cost base: purchase price + stamp duty + legal in + renovations
  const costBase = (parseFloat(p.purchase_price)||0)
    + (parseFloat(p.stamp_duty)||0)
    + (parseFloat(p.legal_purchase)||0)
    + (parseFloat(p.renovation)||0)

  // Sale proceeds less selling costs
  const netProceeds = (parseFloat(p.sale_price)||0)
    - (parseFloat(p.agent_commission)||0)
    - (parseFloat(p.legal_sale)||0)
    - (parseFloat(p.advertising)||0)

  const capitalGain = netProceeds - costBase
  if (capitalGain <= 0) return { costBase, netProceeds, capitalGain, taxableGain: capitalGain, discount: false, mainResidenceExempt: 0 }

  // Main residence exemption
  const mrPct = Math.min(100, Math.max(0, parseFloat(p.main_residence_pct)||0))
  const exemptAmount = capitalGain * (mrPct / 100)
  const taxableAfterMR = capitalGain - exemptAmount

  // 50% CGT discount if held > 12 months
  const days = p.purchase_date && p.sale_date ? daysBetween(p.purchase_date, p.sale_date) : 0
  const eligible = days >= 365
  const taxableGain = eligible ? taxableAfterMR * 0.5 : taxableAfterMR

  return { costBase, netProceeds, capitalGain, taxableGain, discount: eligible,
           days, mainResidenceExempt: exemptAmount, taxableAfterMR }
}

function PropertyForm({ prop, idx, onChange, onDelete }) {
  const F = ({ label, field, type='number', hint }) => (
    <div className="input-group">
      <label style={{display:'flex',alignItems:'center',gap:6}}>{label}
        {hint && <span title={hint} style={{cursor:'help',color:'var(--text-3)'}}><Info size={11}/></span>}
      </label>
      <input className="input input-sm" type={type}
        value={prop[field] ?? ''} step={type==='number'?'0.01':undefined}
        onChange={e => onChange(idx, field, type==='number' ? parseFloat(e.target.value)||0 : e.target.value)}/>
    </div>
  )

  const res = calcCGT(prop)

  return (
    <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden',marginBottom:16}}>
      {/* Header */}
      <div style={{background:'var(--surface-2)',padding:'12px 16px',display:'flex',
        alignItems:'center',justifyContent:'space-between',borderBottom:'1px solid var(--border)'}}>
        <div style={{fontWeight:700,fontSize:'.9rem'}}>
          🏠 {prop.address || `Property ${idx+1}`}
        </div>
        <button className="btn btn-danger btn-xs" onClick={() => onDelete(idx)}>
          <Trash2 size={11}/> Remove
        </button>
      </div>

      <div style={{padding:16}}>
        {/* Address */}
        <div className="input-group" style={{marginBottom:12}}>
          <label>Property Address</label>
          <input className="input input-sm" type="text" value={prop.address||''}
            onChange={e => onChange(idx,'address',e.target.value)}
            placeholder="123 Main St, Sydney NSW 2000"/>
        </div>

        <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12,marginBottom:16}}>
          <F label="Purchase Date" field="purchase_date" type="date"/>
          <F label="Sale Date"     field="sale_date"     type="date"/>
          <div className="input-group">
            <label>Held (days)</label>
            <div className="input input-sm" style={{background:'var(--surface-2)',color:'var(--text-3)'}}>
              {prop.purchase_date && prop.sale_date ? Math.round(daysBetween(prop.purchase_date,prop.sale_date)) : '—'}
            </div>
          </div>
        </div>

        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16}}>
          {/* Purchase costs */}
          <div style={{background:'var(--surface-2)',borderRadius:'var(--r-md)',padding:12}}>
            <div style={{fontWeight:700,marginBottom:10,fontSize:'.82rem',color:'var(--text-2)',
              textTransform:'uppercase',letterSpacing:'.04em'}}>📥 Purchase Costs (Cost Base)</div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
              <F label="Purchase Price *" field="purchase_price" hint="Contract purchase price"/>
              <F label="Stamp Duty"       field="stamp_duty"     hint="Transfer duty paid"/>
              <F label="Legal / Conveyancing" field="legal_purchase"/>
              <F label="Renovations / Improvements" field="renovation" hint="Capital improvements only"/>
            </div>
            <div style={{marginTop:8,padding:'6px 10px',background:'var(--surface)',
              borderRadius:'var(--r-sm)',fontSize:'.8rem',display:'flex',justifyContent:'space-between'}}>
              <span style={{color:'var(--text-3)'}}>Total Cost Base</span>
              <span style={{fontFamily:'var(--font-mono)',fontWeight:700}}>{fmtAUD(res.costBase)}</span>
            </div>
          </div>

          {/* Sale proceeds */}
          <div style={{background:'var(--surface-2)',borderRadius:'var(--r-md)',padding:12}}>
            <div style={{fontWeight:700,marginBottom:10,fontSize:'.82rem',color:'var(--text-2)',
              textTransform:'uppercase',letterSpacing:'.04em'}}>📤 Sale Proceeds</div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
              <F label="Sale Price *"          field="sale_price"       hint="Contract sale price"/>
              <F label="Agent Commission"      field="agent_commission" hint="Real estate agent fees"/>
              <F label="Legal / Conveyancing"  field="legal_sale"/>
              <F label="Advertising Costs"     field="advertising"/>
            </div>
            <div style={{marginTop:8,padding:'6px 10px',background:'var(--surface)',
              borderRadius:'var(--r-sm)',fontSize:'.8rem',display:'flex',justifyContent:'space-between'}}>
              <span style={{color:'var(--text-3)'}}>Net Proceeds</span>
              <span style={{fontFamily:'var(--font-mono)',fontWeight:700}}>{fmtAUD(res.netProceeds)}</span>
            </div>
          </div>
        </div>

        {/* Main residence exemption */}
        <div style={{marginTop:12,background:'#eff6ff',borderRadius:'var(--r-md)',
          padding:12,border:'1px solid #bfdbfe'}}>
          <div style={{fontWeight:700,marginBottom:8,fontSize:'.82rem',color:'#1d4ed8'}}>
            🏡 Main Residence Exemption
          </div>
          <div style={{display:'grid',gridTemplateColumns:'1fr 2fr',gap:12,alignItems:'center'}}>
            <div className="input-group" style={{margin:0}}>
              <label>Exempt % (0–100)</label>
              <input className="input input-sm" type="number" min="0" max="100" step="1"
                value={prop.main_residence_pct||0}
                onChange={e => onChange(idx,'main_residence_pct',parseFloat(e.target.value)||0)}/>
            </div>
            <div style={{fontSize:'.78rem',color:'#1e40af',lineHeight:1.5}}>
              Enter 100% if this was always your main home. Enter a partial % if you rented it out for part of the time or period.
            </div>
          </div>
        </div>

        {/* CGT result */}
        <div style={{marginTop:12,border:`2px solid ${res.capitalGain>0?'var(--brand)':'#16a34a'}`,
          borderRadius:'var(--r-lg)',overflow:'hidden'}}>
          <div style={{
            background: res.capitalGain > 0 ? 'var(--brand)' : '#16a34a',
            color:'#fff',padding:'9px 14px',fontWeight:700,fontSize:'.85rem',
            display:'flex',justifyContent:'space-between'
          }}>
            <span>CGT Result</span>
            <span>{res.discount && '✓ 50% CGT discount applies (held >12 months)'}</span>
          </div>
          <div style={{padding:14}}>
            <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:10}}>
              {[
                ['Capital Gain',      res.capitalGain,       res.capitalGain<0?'#16a34a':res.capitalGain>0?'var(--danger)':'var(--text-1)'],
                ['Exempt (MR)',       res.mainResidenceExempt,'#2563eb'],
                ['After MR Exempt',  res.taxableAfterMR,    'var(--text-1)'],
                ['Taxable CGT',      res.taxableGain,       res.taxableGain>0?'var(--danger)':'#16a34a'],
              ].map(([l,v,c])=>(
                <div key={l} style={{textAlign:'center',padding:10,background:'var(--surface-2)',borderRadius:'var(--r-md)'}}>
                  <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',marginBottom:4}}>{l}</div>
                  <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.9rem',color:c}}>{fmtAUD(v)}</div>
                </div>
              ))}
            </div>
            {res.taxableGain > 0 && (
              <div style={{marginTop:10,padding:'8px 12px',background:'#fef3c7',
                borderRadius:'var(--r-sm)',fontSize:'.75rem',color:'#92400e',border:'1px solid #fde68a'}}>
                ⚠️ This is the capital gain to include in your tax return at Item 18. Multiply by your marginal tax rate to estimate tax payable. Consult your accountant.
              </div>
            )}
          </div>
        </div>

        {/* Notes */}
        <div className="input-group" style={{marginTop:12}}>
          <label>Notes</label>
          <textarea className="input" rows={2} style={{resize:'vertical'}}
            value={prop.notes||''} onChange={e=>onChange(idx,'notes',e.target.value)}
            placeholder="Investment property, SMSF, joint ownership notes…"/>
        </div>
      </div>
    </div>
  )
}

export default function PropertyCGT() {
  const [properties, setProperties] = useState([{...EMPTY_PROP}])

  const addProp    = () => setProperties(p=>[...p,{...EMPTY_PROP}])
  const delProp    = i  => setProperties(p=>p.filter((_,j)=>j!==i))
  const changeProp = (i,field,val) => setProperties(p=>p.map((x,j)=>j===i?{...x,[field]:val}:x))

  const totals = properties.map(calcCGT)
  const totalCGT = totals.reduce((s,r)=>s+(r.taxableGain||0),0)

  return (
    <div style={{padding:24}}>
      <div style={{marginBottom:22}}>
        <h1>🏠 Property CGT</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          Australian property capital gains tax · Cost base · Main residence exemption · 50% CGT discount
        </p>
      </div>

      {/* Summary strip */}
      {properties.length > 0 && (
        <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:20}}>
          {[
            {l:'Properties',     v:properties.length,                                  c:'var(--brand)'},
            {l:'Total Proceeds', v:fmtAUD(totals.reduce((s,r)=>s+(r.netProceeds||0),0)), c:'#16a34a'},
            {l:'Total Cost Base',v:fmtAUD(totals.reduce((s,r)=>s+(r.costBase||0),0)),    c:'var(--text-1)'},
            {l:'Total Taxable CGT', v:fmtAUD(totalCGT),                               c:totalCGT>0?'var(--danger)':'#16a34a'},
          ].map(({l,v,c})=>(
            <div key={l} style={{background:'var(--surface)',border:'1px solid var(--border)',
              borderRadius:'var(--r-lg)',padding:'14px 16px',boxShadow:'var(--sh-xs)'}}>
              <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',marginBottom:4}}>{l}</div>
              <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1rem',color:c}}>{v}</div>
            </div>
          ))}
        </div>
      )}

      {properties.map((prop, i) => (
        <PropertyForm key={i} prop={prop} idx={i} onChange={changeProp} onDelete={delProp}/>
      ))}

      <button className="btn btn-primary btn-sm" onClick={addProp}>
        <Plus size={13}/> Add Property
      </button>

      <div style={{marginTop:20,padding:'12px 16px',background:'var(--surface-2)',
        borderRadius:'var(--r-md)',border:'1px solid var(--border)',fontSize:'.78rem',color:'var(--text-3)'}}>
        <strong>Disclaimer:</strong> This calculator is a guide only. For complex situations (SMSF, partial exemptions, deceased estates, foreign residents, pre-CGT assets), always consult a registered tax agent or accountant.
        ATO references: <em>Guide to capital gains tax 2024</em>, Schedule 7, <em>TR 2019/1</em>.
      </div>
    </div>
  )
}
