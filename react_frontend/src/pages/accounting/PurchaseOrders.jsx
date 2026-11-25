/**
 * PurchaseOrderTab — Create and manage Purchase Orders
 * Mirrors the Xero-style PO form shown in the screenshot:
 * Contact, Date raised, Delivery date, Order number, Reference, Currency,
 * Tax treatment, line items (Item, Description, Qty, Price, Disc, Account, Tax rate)
 * Delivery address, Subtotal/Tax/Total
 */
import React, { useState, useEffect } from 'react'
import { useAuth } from '../../hooks/useAuth.jsx'
import { Plus, Trash2, Check, ChevronDown, ChevronUp, RefreshCw, Send, Download } from 'lucide-react'
import axios from 'axios'
import toast from 'react-hot-toast'

const http = axios.create({ baseURL: '/api', withCredentials: true })
http.interceptors.request.use(cfg => {
  try { const u = JSON.parse(localStorage.getItem('af_user')||'{}'); if (u.token) cfg.headers['Authorization'] = `Bearer ${u.token}` } catch {}
  return cfg
})

const fmtAUD  = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n||0)
const today   = () => new Date().toISOString().split('T')[0]
const addDays = (d,n) => { const dt=new Date(d); dt.setDate(dt.getDate()+n); return dt.toISOString().split('T')[0] }

const TAX_RATES = ['GST on Expenses (10%)', 'GST Free Expenses (0%)', 'BAS Excluded (N/A)']
const CURRENCIES = ['Australian Dollar', 'US Dollar', 'British Pound', 'Euro', 'New Zealand Dollar']
const TAX_TREATMENTS = ['Tax exclusive', 'Tax inclusive', 'No tax']

const STATUS_STYLE = {
  draft:    { bg:'var(--surface-2)', color:'var(--text-3)', label:'Draft' },
  sent:     { bg:'#dbeafe',          color:'#1d4ed8',       label:'Sent'  },
  approved: { bg:'#dcfce7',          color:'#16a34a',       label:'Approved' },
  billed:   { bg:'#fef3c7',          color:'#92400e',       label:'Billed'   },
  cancelled:{ bg:'#fee2e2',          color:'#991b1b',       label:'Cancelled'},
}

const EMPTY_LINE = { item:'', description:'', quantity:1, unit_price:0, discount:0, account:'', tax_rate:'GST on Expenses (10%)' }

function nextPONumber(existing) {
  if (!existing.length) return 'PO-0001'
  const nums = existing.map(p => parseInt((p.order_number||'').replace(/[^0-9]/g,''))||0)
  return `PO-${String(Math.max(...nums)+1).padStart(4,'0')}`
}

// ── Purchase Order Form ───────────────────────────────────────────────────────
function POForm({ initial, onSave, onCancel, existingPOs, glAccounts }) {
  const [po, setPO] = useState(initial || {
    contact:         '',
    date_raised:     today(),
    delivery_date:   addDays(today(), 14),
    order_number:    nextPONumber(existingPOs),
    reference:       '',
    currency:        'Australian Dollar',
    tax_treatment:   'Tax exclusive',
    lines:           [{ ...EMPTY_LINE }],
    delivery_address:'',
    attention:       '',
    telephone:       '',
    notes:           '',
    status:          'draft',
  })
  const [saving, setSaving] = useState(false)

  const setLine = (i, field, val) =>
    setPO(p => ({ ...p, lines: p.lines.map((l,j) => j===i ? {...l,[field]:val} : l) }))

  const addLine = () => setPO(p => ({ ...p, lines: [...p.lines, { ...EMPTY_LINE }] }))
  const delLine = i  => setPO(p => ({ ...p, lines: p.lines.filter((_,j)=>j!==i) }))

  // Calculations
  const subtotal = po.lines.reduce((s,l) => {
    const base = (parseFloat(l.quantity)||0) * (parseFloat(l.unit_price)||0)
    const disc = base * ((parseFloat(l.discount)||0) / 100)
    return s + base - disc
  }, 0)

  const isTaxInclusive = po.tax_treatment === 'Tax inclusive'
  const isTaxExclusive = po.tax_treatment === 'Tax exclusive'
  const taxRate = 0.10

  const taxableLines = po.lines.filter(l => l.tax_rate === 'GST on Expenses (10%)')
  const taxableSubtotal = taxableLines.reduce((s,l) => {
    const base = (parseFloat(l.quantity)||0) * (parseFloat(l.unit_price)||0)
    const disc = base * ((parseFloat(l.discount)||0) / 100)
    return s + base - disc
  }, 0)

  const gst   = isTaxInclusive
    ? taxableSubtotal * taxRate / (1 + taxRate)
    : isTaxExclusive
      ? taxableSubtotal * taxRate
      : 0
  const total = isTaxInclusive ? subtotal : subtotal + gst

  const handleSave = async (status = 'draft') => {
    if (!po.contact) { toast.error('Contact / Supplier required'); return }
    setSaving(true)
    try {
      const payload = { ...po, status, subtotal: Math.round(subtotal*100)/100,
        gst: Math.round(gst*100)/100, total: Math.round(total*100)/100 }
      onSave(payload)
      toast.success(status === 'approved' ? 'PO approved ✓' : 'PO saved as draft ✓')
    } finally { setSaving(false) }
  }

  const F = ({label, field, type='text', opts, style, req}) => (
    <div className="input-group" style={style}>
      <label>{label}{req?' *':''}</label>
      {opts
        ? <select className="input input-sm" value={po[field]||''} onChange={e=>setPO(p=>({...p,[field]:e.target.value}))}>
            {opts.map(o=><option key={o}>{o}</option>)}
          </select>
        : <input className="input input-sm" type={type} value={po[field]||''}
            onChange={e=>setPO(p=>({...p,[field]:e.target.value}))}/>
      }
    </div>
  )

  return (
    <div>
      {/* Header bar */}
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',
        marginBottom:20,paddingBottom:16,borderBottom:'1px solid var(--border)'}}>
        <div>
          <h3 style={{margin:0}}>{initial ? `Edit ${po.order_number}` : 'New Purchase Order'}</h3>
          <div style={{fontSize:'.78rem',color:'var(--text-3)',marginTop:2}}>
            Contact your supplier · attach files · approve when ready
          </div>
        </div>
        <div style={{display:'flex',gap:8}}>
          {onCancel && <button className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>}
          <button className="btn btn-outline btn-sm" onClick={() => handleSave('draft')} disabled={saving}>
            {saving?'Saving…':'💾 Save as Draft'}
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => handleSave('approved')} disabled={saving}>
            <Check size={14}/> Approve
          </button>
        </div>
      </div>

      {/* Top fields row */}
      <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12,marginBottom:16}}>
        <F label="Contact / Supplier" field="contact" req style={{gridColumn:'span 1'}}/>
        <F label="Date Raised"  field="date_raised"   type="date"/>
        <F label="Delivery Date" field="delivery_date" type="date"/>
        <F label="Order Number"  field="order_number"/>
        <F label="Reference"     field="reference"/>
        <F label="Currency"      field="currency"   opts={CURRENCIES}/>
      </div>

      {/* Tax treatment */}
      <div style={{marginBottom:16}}>
        <F label="Amounts are" field="tax_treatment" opts={TAX_TREATMENTS} style={{maxWidth:220}}/>
      </div>

      {/* Line items */}
      <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-md)',overflow:'hidden',marginBottom:16}}>
        <table style={{width:'100%',borderCollapse:'collapse',fontSize:'.8rem'}}>
          <thead style={{background:'var(--surface-2)'}}>
            <tr>
              {['Item','Description','Qty','Price (AUD)','Disc %','Account','Tax Rate','Amount',''].map((h,i) => (
                <th key={i} style={{padding:'8px 10px',textAlign:i>=2&&i<=7?'right':'left',
                  fontWeight:700,fontSize:'.72rem',color:'var(--text-3)',
                  textTransform:'uppercase',letterSpacing:'.04em',whiteSpace:'nowrap'}}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {po.lines.map((line, i) => {
              const lineTotal = (parseFloat(line.quantity)||0) * (parseFloat(line.unit_price)||0)
                * (1 - (parseFloat(line.discount)||0)/100)
              return (
                <tr key={i} style={{borderTop:'1px solid var(--border)'}}>
                  <td style={{padding:'6px 8px',minWidth:80}}>
                    <input className="cell-input" style={{width:'100%',fontSize:'.8rem'}}
                      placeholder="Item code" value={line.item}
                      onChange={e=>setLine(i,'item',e.target.value)}/>
                  </td>
                  <td style={{padding:'6px 8px',minWidth:160}}>
                    <input className="cell-input" style={{width:'100%',fontSize:'.8rem'}}
                      placeholder="Description" value={line.description}
                      onChange={e=>setLine(i,'description',e.target.value)}/>
                  </td>
                  <td style={{padding:'6px 8px',width:60}}>
                    <input className="cell-input" type="number" min="0" step="0.5"
                      style={{width:55,textAlign:'right',fontSize:'.8rem'}}
                      value={line.quantity} onChange={e=>setLine(i,'quantity',e.target.value)}/>
                  </td>
                  <td style={{padding:'6px 8px',width:100}}>
                    <input className="cell-input" type="number" min="0" step="0.01"
                      style={{width:88,textAlign:'right',fontSize:'.8rem'}}
                      value={line.unit_price} onChange={e=>setLine(i,'unit_price',e.target.value)}/>
                  </td>
                  <td style={{padding:'6px 8px',width:60}}>
                    <input className="cell-input" type="number" min="0" max="100" step="0.1"
                      style={{width:52,textAlign:'right',fontSize:'.8rem'}}
                      value={line.discount} onChange={e=>setLine(i,'discount',e.target.value)}/>
                  </td>
                  <td style={{padding:'6px 8px',minWidth:140}}>
                    <select className="select-compact" style={{fontSize:'.75rem',width:'100%'}}
                      value={line.account} onChange={e=>setLine(i,'account',e.target.value)}>
                      <option value="">— Account —</option>
                      {glAccounts.map(g=><option key={g}>{g}</option>)}
                    </select>
                  </td>
                  <td style={{padding:'6px 8px',minWidth:160}}>
                    <select className="select-compact" style={{fontSize:'.75rem',width:'100%'}}
                      value={line.tax_rate} onChange={e=>setLine(i,'tax_rate',e.target.value)}>
                      {TAX_RATES.map(t=><option key={t}>{t}</option>)}
                    </select>
                  </td>
                  <td style={{padding:'6px 10px',textAlign:'right',fontFamily:'var(--font-mono)',
                    fontWeight:600,fontSize:'.82rem',whiteSpace:'nowrap'}}>
                    {fmtAUD(lineTotal)}
                  </td>
                  <td style={{padding:'6px 8px',width:32}}>
                    {po.lines.length > 1 && (
                      <button onClick={()=>delLine(i)}
                        style={{background:'none',border:'none',cursor:'pointer',color:'var(--danger)',padding:2}}>
                        <Trash2 size={13}/>
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div style={{padding:'8px 10px',borderTop:'1px solid var(--border)',background:'var(--surface-2)'}}>
          <button className="btn btn-ghost btn-xs" onClick={addLine}><Plus size={12}/> Add Row</button>
        </div>
      </div>

      {/* Bottom: delivery + totals */}
      <div style={{display:'grid',gridTemplateColumns:'1fr auto',gap:20,alignItems:'start'}}>
        {/* Delivery */}
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
          <div className="input-group" style={{gridColumn:'span 2'}}>
            <label>Delivery Address</label>
            <textarea className="input" rows={2} style={{resize:'vertical'}}
              value={po.delivery_address||''}
              onChange={e=>setPO(p=>({...p,delivery_address:e.target.value}))}/>
          </div>
          <div className="input-group">
            <label>Attention</label>
            <input className="input input-sm" value={po.attention||''}
              onChange={e=>setPO(p=>({...p,attention:e.target.value}))}/>
          </div>
          <div className="input-group">
            <label>Telephone</label>
            <input className="input input-sm" type="tel" value={po.telephone||''}
              onChange={e=>setPO(p=>({...p,telephone:e.target.value}))}/>
          </div>
          <div className="input-group" style={{gridColumn:'span 2'}}>
            <label>Notes to Supplier</label>
            <textarea className="input" rows={2} style={{resize:'vertical'}}
              value={po.notes||''}
              onChange={e=>setPO(p=>({...p,notes:e.target.value}))}/>
          </div>
        </div>

        {/* Totals */}
        <div style={{minWidth:240,border:'1px solid var(--border)',borderRadius:'var(--r-md)',overflow:'hidden'}}>
          {[
            ['Subtotal', fmtAUD(subtotal)],
            [`GST (10%)`, fmtAUD(gst)],
          ].map(([l,v]) => (
            <div key={l} style={{display:'flex',justifyContent:'space-between',
              padding:'9px 14px',borderBottom:'1px solid var(--border)',fontSize:'.82rem'}}>
              <span style={{color:'var(--text-2)'}}>{l}</span>
              <span style={{fontFamily:'var(--font-mono)'}}>{v}</span>
            </div>
          ))}
          <div style={{display:'flex',justifyContent:'space-between',
            padding:'12px 14px',background:'var(--surface-2)',fontWeight:700}}>
            <span>Total</span>
            <span style={{fontFamily:'var(--font-mono)',color:'var(--brand)',fontSize:'1rem'}}>
              {fmtAUD(total)}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── PO List ───────────────────────────────────────────────────────────────────
function POList({ pos, onEdit, onDelete, onApprove }) {
  const [expanded, setExpanded] = useState({})

  if (!pos.length)
    return (
      <div className="empty-state" style={{padding:40}}>
        <div style={{fontSize:'2rem',marginBottom:8}}>📋</div>
        <p>No purchase orders yet. Click "New Purchase Order" to create one.</p>
      </div>
    )

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Order #</th><th>Contact</th><th>Date Raised</th>
          <th>Delivery</th><th style={{textAlign:'right'}}>Total</th>
          <th>Status</th><th style={{width:130}}>Actions</th>
        </tr>
      </thead>
      <tbody>
        {pos.map(po => {
          const sc = STATUS_STYLE[po.status] || STATUS_STYLE.draft
          return (
            <React.Fragment key={po.id}>
              <tr>
                <td>
                  <button onClick={()=>setExpanded(p=>({...p,[po.id]:!p[po.id]}))}
                    style={{background:'none',border:'none',cursor:'pointer',
                      color:'var(--brand)',fontFamily:'var(--font-mono)',fontSize:'.82rem',
                      fontWeight:600,display:'flex',alignItems:'center',gap:4}}>
                    {expanded[po.id]?<ChevronUp size={12}/>:<ChevronDown size={12}/>}
                    {po.order_number}
                  </button>
                </td>
                <td style={{fontWeight:600,fontSize:'.85rem'}}>{po.contact}</td>
                <td style={{fontSize:'.78rem'}}>{po.date_raised}</td>
                <td style={{fontSize:'.78rem'}}>{po.delivery_date}</td>
                <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:700}}>
                  {fmtAUD(po.total)}
                </td>
                <td>
                  <span style={{padding:'2px 10px',borderRadius:100,fontSize:'.72rem',
                    fontWeight:700,background:sc.bg,color:sc.color}}>{sc.label}</span>
                </td>
                <td>
                  <div style={{display:'flex',gap:4}}>
                    {po.status === 'draft' && (
                      <button className="btn btn-outline btn-xs"
                        onClick={()=>onApprove(po.id)}
                        style={{fontSize:'.68rem',padding:'2px 6px'}}>
                        <Check size={10}/> Approve
                      </button>
                    )}
                    <button className="btn btn-ghost btn-xs" onClick={()=>onEdit(po)}>✏️</button>
                    <button className="btn btn-danger btn-xs" onClick={()=>onDelete(po.id)}>
                      <Trash2 size={11}/>
                    </button>
                  </div>
                </td>
              </tr>
              {expanded[po.id] && (
                <tr style={{background:'var(--surface-2)'}}>
                  <td colSpan={7} style={{padding:'12px 16px'}}>
                    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16,fontSize:'.78rem'}}>
                      <div>
                        <div style={{fontWeight:700,marginBottom:8}}>Line Items</div>
                        <table style={{width:'100%',borderCollapse:'collapse'}}>
                          <thead><tr style={{borderBottom:'1px solid var(--border)'}}>
                            <th style={{padding:'3px 6px',textAlign:'left'}}>Description</th>
                            <th style={{padding:'3px 6px',textAlign:'right'}}>Qty</th>
                            <th style={{padding:'3px 6px',textAlign:'right'}}>Price</th>
                            <th style={{padding:'3px 6px',textAlign:'right'}}>Total</th>
                          </tr></thead>
                          <tbody>
                            {(po.lines||[]).map((l,i)=>(
                              <tr key={i}>
                                <td style={{padding:'3px 6px'}}>{l.description||l.item||'—'}</td>
                                <td style={{padding:'3px 6px',textAlign:'right'}}>{l.quantity}</td>
                                <td style={{padding:'3px 6px',textAlign:'right'}}>{fmtAUD(l.unit_price)}</td>
                                <td style={{padding:'3px 6px',textAlign:'right',fontWeight:600}}>
                                  {fmtAUD((l.quantity||0)*(l.unit_price||0)*(1-(l.discount||0)/100))}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div>
                        {po.reference    && <div><strong>Reference:</strong> {po.reference}</div>}
                        {po.delivery_address && <div style={{marginTop:4}}><strong>Deliver to:</strong> {po.delivery_address}</div>}
                        {po.notes        && <div style={{marginTop:4}}><strong>Notes:</strong> {po.notes}</div>}
                        <div style={{marginTop:8,padding:10,background:'var(--surface)',borderRadius:'var(--r-md)'}}>
                          <div>Subtotal: <strong>{fmtAUD(po.subtotal)}</strong></div>
                          <div>GST: <strong>{fmtAUD(po.gst)}</strong></div>
                          <div style={{fontSize:'.9rem',fontWeight:700,marginTop:4}}>
                            Total: <span style={{color:'var(--brand)'}}>{fmtAUD(po.total)}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </React.Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────
export default function PurchaseOrders({ userId }) {
  const [pos,      setPOs]     = useState([])
  const [view,     setView]    = useState('list')   // 'list' | 'create' | 'edit'
  const [editPO,   setEditPO]  = useState(null)
  const [glAccounts, setGlAccounts] = useState([])

  // Load GL accounts for dropdowns
  useEffect(() => {
    fetch('/api/gl/accounts').then(r=>r.json()).then(d=>{ if(Array.isArray(d)) setGlAccounts(d.filter(Boolean)) }).catch(()=>{})
    // Load saved POs from localStorage (in production would be API)
    try {
      const saved = JSON.parse(localStorage.getItem(`accfino_pos_${userId}`) || '[]')
      setPOs(saved)
    } catch {}
  }, [userId])

  const savePOs = (updated) => {
    setPOs(updated)
    try { localStorage.setItem(`accfino_pos_${userId}`, JSON.stringify(updated)) } catch {}
  }

  const handleSave = (po) => {
    if (editPO) {
      savePOs(pos.map(p => p.id === editPO.id ? { ...po, id: editPO.id } : p))
    } else {
      savePOs([...pos, { ...po, id: Date.now().toString() }])
    }
    setView('list'); setEditPO(null)
  }

  const handleDelete = (id) => {
    if (!confirm('Delete this purchase order?')) return
    savePOs(pos.filter(p => p.id !== id))
    toast.success('PO deleted')
  }

  const handleApprove = (id) => {
    savePOs(pos.map(p => p.id === id ? { ...p, status:'approved' } : p))
    toast.success('PO approved ✓')
  }

  const handleEdit = (po) => { setEditPO(po); setView('edit') }

  const StatusCounts = () => {
    const counts = pos.reduce((a,p) => { a[p.status]=(a[p.status]||0)+1; return a }, {})
    return (
      <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
        {Object.entries(counts).map(([s,c]) => {
          const sc = STATUS_STYLE[s] || STATUS_STYLE.draft
          return (
            <span key={s} style={{padding:'2px 8px',borderRadius:100,fontSize:'.72rem',
              fontWeight:700,background:sc.bg,color:sc.color}}>
              {sc.label}: {c}
            </span>
          )
        })}
      </div>
    )
  }

  return (
    <div>
      {view === 'list' ? (
        <div style={{padding:24}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
            <div>
              <h3 style={{margin:0}}>Purchase Orders</h3>
              <div style={{marginTop:6}}><StatusCounts/></div>
            </div>
            <div style={{display:'flex',gap:8}}>
              <button className="btn btn-outline btn-sm" onClick={()=>{}}>
                <Download size={13}/> Export
              </button>
              <button className="btn btn-primary btn-sm" onClick={()=>{ setEditPO(null); setView('create') }}>
                <Plus size={13}/> New Purchase Order
              </button>
            </div>
          </div>
          <POList pos={pos} onEdit={handleEdit} onDelete={handleDelete} onApprove={handleApprove}/>
        </div>
      ) : (
        <div style={{padding:24}}>
          <POForm
            initial={editPO}
            existingPOs={pos}
            glAccounts={glAccounts}
            onSave={handleSave}
            onCancel={() => { setView('list'); setEditPO(null) }}
          />
        </div>
      )}
    </div>
  )
}
