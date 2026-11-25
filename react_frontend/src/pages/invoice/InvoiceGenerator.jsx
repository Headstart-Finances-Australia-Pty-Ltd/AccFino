import React, { useState, useEffect } from 'react'
import { invoiceGetBusinesses, invoiceCreateBusiness, invoiceGetAll, invoiceCreate, invoiceNextNum, invoiceUpdateStatus } from '../../lib/api.js'
import { Plus, Building2, FileText, Download, Check } from 'lucide-react'
import toast from 'react-hot-toast'

const fmtAUD = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n||0)

const BLANK_BIZ = { name:'', email:'', phone:'', address:'', city:'', state:'', postal_code:'', country:'Australia', tax_id:'', website:'' }
const BLANK_INV = { invoice_number:'', invoice_date:new Date().toISOString().slice(0,10), due_date:'', bill_to_name:'', bill_to_email:'', bill_to_phone:'', bill_to_address:'', notes:'', payment_terms:'Net 30', tax_percent:10, items:[{description:'',quantity:1,unit_price:0}] }

export default function InvoiceGenerator() {
  const [businesses, setBusinesses] = useState([])
  const [selBiz,     setSelBiz]     = useState(null)
  const [invoices,   setInvoices]   = useState([])
  const [view,       setView]       = useState('list') // list | new-biz | new-inv | detail
  const [bizForm,    setBizForm]    = useState({...BLANK_BIZ})
  const [invForm,    setInvForm]    = useState({...BLANK_INV})
  const [selInv,     setSelInv]     = useState(null)
  const [loading,    setLoading]    = useState(false)

  useEffect(() => {
    invoiceGetBusinesses()
      .then(r => setBusinesses(Array.isArray(r.data) ? r.data : []))
      .catch(() => setBusinesses([]))
  }, [])

  useEffect(() => {
    if (!selBiz) return
    invoiceGetAll(selBiz.id)
      .then(r => setInvoices(Array.isArray(r.data) ? r.data : []))
      .catch(() => setInvoices([]))
  }, [selBiz])

  const createBiz = async () => {
    if (!bizForm.name) { toast.error('Business name required'); return }
    setLoading(true)
    try {
      const { data } = await invoiceCreateBusiness(bizForm)
      setBusinesses(b=>[...b, data])
      setSelBiz(data); setView('list'); setBizForm({...BLANK_BIZ})
      toast.success('Business created')
    } catch (e) { toast.error(e.response?.data?.detail||'Failed') }
    finally { setLoading(false) }
  }

  const startNewInv = async () => {
    try {
      const { data } = await invoiceNextNum()
      setInvForm(f=>({...BLANK_INV, invoice_number: data.next_number || '', invoice_date: new Date().toISOString().slice(0,10)}))
    } catch { setInvForm({...BLANK_INV}) }
    setView('new-inv')
  }

  const computeTotals = items => {
    const subtotal = items.reduce((s,it)=>s+(parseFloat(it.quantity||0)*parseFloat(it.unit_price||0)),0)
    const tax_amount = subtotal * (invForm.tax_percent/100)
    return { subtotal, tax_amount, total_amount: subtotal + tax_amount }
  }

  const createInv = async () => {
    if (!selBiz) { toast.error('Select a business first'); return }
    const { subtotal, tax_amount, total_amount } = computeTotals(invForm.items)
    setLoading(true)
    try {
      const payload = {...invForm, business_id: selBiz.id, subtotal, tax_amount, total_amount,
        invoice_date: new Date(invForm.invoice_date).toISOString(),
        due_date: invForm.due_date ? new Date(invForm.due_date).toISOString() : null}
      const { data } = await invoiceCreate(payload)
      setInvoices(inv=>[data,...inv]); setView('list')
      toast.success('Invoice created')
    } catch (e) { toast.error(e.response?.data?.detail||'Failed') }
    finally { setLoading(false) }
  }

  const updateStatus = async (id, status) => {
    try {
      await invoiceUpdateStatus(id, status)
      setInvoices(inv=>inv.map(i=>i.id===id?{...i,status}:i))
      if (selInv?.id===id) setSelInv(s=>({...s,status}))
      toast.success(`Status → ${status}`)
    } catch { toast.error('Update failed') }
  }

  const addItem = () => setInvForm(f=>({...f, items:[...f.items,{description:'',quantity:1,unit_price:0}]}))
  const removeItem = i => setInvForm(f=>({...f, items:f.items.filter((_,j)=>j!==i)}))
  const setItem = (i,k,v) => setInvForm(f=>({...f, items:f.items.map((it,j)=>j===i?{...it,[k]:v}:it)}))

  const {subtotal,tax_amount,total_amount} = computeTotals(invForm.items)

  const statusColor = s => s==='paid'?'badge-success':s==='sent'?'badge-info':s==='overdue'?'badge-danger':'badge-neutral'

  return (
    <div className="fade-in">
      <div style={{marginBottom:22,display:'flex',alignItems:'flex-end',justifyContent:'space-between',flexWrap:'wrap',gap:12}}>
        <div>
          <h1>📄 Invoice Manager</h1>
          <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>Create GST-compliant invoices, manage businesses, track payment status</p>
        </div>
        <div style={{display:'flex',gap:8}}>
          <button className="btn btn-outline" onClick={()=>setView('new-biz')}><Building2 size={15}/> New Business</button>
          {selBiz && <button className="btn btn-primary" onClick={startNewInv}><Plus size={15}/> New Invoice</button>}
        </div>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'220px 1fr',gap:20,alignItems:'start'}}>
        {/* Business list */}
        <div className="card" style={{padding:0,overflow:'hidden'}}>
          <div style={{padding:'12px 16px',borderBottom:'1px solid var(--border)',fontWeight:600,fontSize:'.875rem',color:'var(--text-2)'}}>Businesses</div>
          {businesses.length===0
            ? <div style={{padding:'24px 16px',textAlign:'center',color:'var(--text-3)',fontSize:'.8rem'}}>No businesses yet.<br/>Create one to start.</div>
            : businesses.map(b=>(
              <button key={b.id} onClick={()=>{setSelBiz(b);setView('list')}} style={{
                display:'block',width:'100%',padding:'10px 16px',background:selBiz?.id===b.id?'var(--brand-xlight)':'transparent',
                border:'none',borderBottom:'1px solid var(--border)',cursor:'pointer',textAlign:'left',transition:'all .12s',fontFamily:'inherit',
              }}>
                <div style={{fontWeight:600,fontSize:'.875rem',color:selBiz?.id===b.id?'var(--brand)':'var(--text-1)'}}>{b.name}</div>
                <div style={{fontSize:'.72rem',color:'var(--text-3)'}}>{b.email||b.tax_id||''}</div>
              </button>
            ))
          }
        </div>

        {/* Right panel */}
        <div>
          {view==='new-biz' && (
            <div className="card">
              <h3 style={{marginBottom:16}}>New Business Profile</h3>
              <div className="grid-2" style={{gap:12,marginBottom:12}}>
                {[['name','Business Name *'],['email','Email'],['phone','Phone'],['tax_id','ABN / Tax ID'],['address','Address'],['city','City'],['state','State'],['postal_code','Postcode'],['country','Country'],['website','Website']].map(([k,label])=>(
                  <div key={k} className="input-group">
                    <label>{label}</label>
                    <input className="input" value={bizForm[k]||''} onChange={e=>setBizForm(f=>({...f,[k]:e.target.value}))} placeholder={label.replace(' *','')}/>
                  </div>
                ))}
              </div>
              <div style={{display:'flex',gap:8}}>
                <button className="btn btn-primary" onClick={createBiz} disabled={loading}>{loading?<span className="spinner spinner-sm"/>:'Save Business'}</button>
                <button className="btn btn-ghost" onClick={()=>setView('list')}>Cancel</button>
              </div>
            </div>
          )}

          {view==='list' && selBiz && (
            <div className="card" style={{padding:0,overflow:'hidden'}}>
              <div style={{padding:'14px 20px',borderBottom:'1px solid var(--border)',display:'flex',alignItems:'center',gap:10}}>
                <Building2 size={17} color="var(--brand)"/><h3>{selBiz.name} — Invoices</h3>
                <span style={{marginLeft:'auto',background:'var(--surface-3)',borderRadius:100,padding:'1px 8px',fontSize:'.72rem',fontWeight:700}}>{invoices.length}</span>
              </div>
              {invoices.length===0
                ? <div className="empty-state" style={{padding:48}}><div className="empty-icon">📄</div><h3>No invoices yet</h3><p>Create your first invoice for {selBiz.name}</p><button className="btn btn-primary" style={{marginTop:12}} onClick={startNewInv}>Create Invoice</button></div>
                : <table className="data-table">
                    <thead><tr><th>Number</th><th>Date</th><th>Bill To</th><th>Total</th><th>Status</th><th></th></tr></thead>
                    <tbody>
                      {invoices.map(inv=>(
                        <tr key={inv.id} style={{cursor:'pointer'}} onClick={()=>{setSelInv(inv);setView('detail')}}>
                          <td className="mono" style={{fontWeight:600}}>{inv.invoice_number}</td>
                          <td style={{fontSize:'.8rem'}}>{inv.invoice_date?.slice(0,10)}</td>
                          <td style={{fontSize:'.8rem'}}>{inv.bill_to_name||'—'}</td>
                          <td className="mono" style={{fontWeight:700,textAlign:'right'}}>{fmtAUD(inv.total_amount)}</td>
                          <td><span className={`badge ${statusColor(inv.status)}`}>{inv.status}</span></td>
                          <td style={{fontSize:'.72rem',color:'var(--text-3)'}}>{inv.due_date?.slice(0,10)||''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
              }
            </div>
          )}

          {view==='new-inv' && selBiz && (
            <div className="card">
              <h3 style={{marginBottom:16}}>New Invoice — {selBiz.name}</h3>
              <div className="grid-2" style={{gap:12,marginBottom:14}}>
                {[['invoice_number','Invoice Number'],['invoice_date','Invoice Date'],['due_date','Due Date'],['payment_terms','Payment Terms']].map(([k,label])=>(
                  <div key={k} className="input-group"><label>{label}</label>
                    <input className="input" type={k.includes('date')?'date':'text'} value={invForm[k]||''} onChange={e=>setInvForm(f=>({...f,[k]:e.target.value}))}/>
                  </div>
                ))}
              </div>
              <h4 style={{marginBottom:10,marginTop:4}}>Bill To</h4>
              <div className="grid-2" style={{gap:12,marginBottom:14}}>
                {[['bill_to_name','Name'],['bill_to_email','Email'],['bill_to_phone','Phone'],['bill_to_address','Address']].map(([k,l])=>(
                  <div key={k} className="input-group"><label>{l}</label><input className="input" value={invForm[k]||''} onChange={e=>setInvForm(f=>({...f,[k]:e.target.value}))}/></div>
                ))}
              </div>
              <h4 style={{marginBottom:10}}>Line Items</h4>
              <table style={{width:'100%',borderCollapse:'collapse',marginBottom:8}}>
                <thead><tr style={{background:'var(--surface-2)'}}>
                  <th style={{padding:'6px 10px',textAlign:'left',fontSize:'.72rem',fontWeight:700,textTransform:'uppercase',letterSpacing:'.05em',borderBottom:'1px solid var(--border)'}}>Description</th>
                  <th style={{padding:'6px 10px',textAlign:'right',fontSize:'.72rem',fontWeight:700,textTransform:'uppercase',width:80,borderBottom:'1px solid var(--border)'}}>Qty</th>
                  <th style={{padding:'6px 10px',textAlign:'right',fontSize:'.72rem',fontWeight:700,textTransform:'uppercase',width:120,borderBottom:'1px solid var(--border)'}}>Unit Price</th>
                  <th style={{padding:'6px 10px',textAlign:'right',fontSize:'.72rem',fontWeight:700,textTransform:'uppercase',width:120,borderBottom:'1px solid var(--border)'}}>Total</th>
                  <th style={{width:40,borderBottom:'1px solid var(--border)'}}></th>
                </tr></thead>
                <tbody>
                  {invForm.items.map((it,i)=>(
                    <tr key={i}>
                      <td style={{padding:'5px 8px'}}><input className="input input-sm" value={it.description} onChange={e=>setItem(i,'description',e.target.value)} placeholder="Description"/></td>
                      <td style={{padding:'5px 8px'}}><input className="input input-sm" type="number" min="0" value={it.quantity} onChange={e=>setItem(i,'quantity',parseFloat(e.target.value)||0)} style={{textAlign:'right'}}/></td>
                      <td style={{padding:'5px 8px'}}><input className="input input-sm" type="number" min="0" step="0.01" value={it.unit_price} onChange={e=>setItem(i,'unit_price',parseFloat(e.target.value)||0)} style={{textAlign:'right'}}/></td>
                      <td style={{padding:'5px 14px',textAlign:'right',fontFamily:'var(--font-mono)',fontSize:'.8rem'}}>{fmtAUD(it.quantity*it.unit_price)}</td>
                      <td style={{padding:'5px 4px'}}>{invForm.items.length>1&&<button className="btn btn-ghost btn-icon btn-xs" onClick={()=>removeItem(i)} style={{color:'var(--danger)'}}>✕</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="btn btn-ghost btn-sm" onClick={addItem} style={{marginBottom:14}}><Plus size={13}/> Add Line Item</button>
              <div style={{display:'flex',gap:12,alignItems:'flex-end',marginBottom:16}}>
                <div className="input-group" style={{maxWidth:160}}>
                  <label>GST % <span style={{fontWeight:400,color:'var(--text-3)'}}>(10 = 10%)</span></label>
                  <input className="input" type="number" min="0" max="100" value={invForm.tax_percent} onChange={e=>setInvForm(f=>({...f,tax_percent:parseFloat(e.target.value)||0}))}/>
                </div>
                <div style={{marginLeft:'auto',textAlign:'right'}}>
                  <div style={{fontSize:'.8rem',color:'var(--text-3)',marginBottom:4}}>Subtotal: {fmtAUD(subtotal)}</div>
                  <div style={{fontSize:'.8rem',color:'var(--text-3)',marginBottom:4}}>GST ({invForm.tax_percent}%): {fmtAUD(tax_amount)}</div>
                  <div style={{fontSize:'1.1rem',fontWeight:700,fontFamily:'var(--font-mono)',color:'var(--brand)'}}>Total: {fmtAUD(total_amount)}</div>
                </div>
              </div>
              <div className="input-group" style={{marginBottom:16}}>
                <label>Notes</label>
                <textarea className="input" rows={2} value={invForm.notes||''} onChange={e=>setInvForm(f=>({...f,notes:e.target.value}))} placeholder="Payment instructions, thank you note…"/>
              </div>
              <div style={{display:'flex',gap:8}}>
                <button className="btn btn-primary" onClick={createInv} disabled={loading}>{loading?<><span className="spinner spinner-sm"/>Saving…</>:<><FileText size={15}/>Create Invoice</>}</button>
                <button className="btn btn-ghost" onClick={()=>setView('list')}>Cancel</button>
              </div>
            </div>
          )}

          {view==='detail' && selInv && (
            <div className="card">
              <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:20}}>
                <h3>Invoice #{selInv.invoice_number}</h3>
                <span className={`badge ${statusColor(selInv.status)}`}>{selInv.status}</span>
                <div style={{marginLeft:'auto',display:'flex',gap:6}}>
                  {['draft','sent','paid','overdue'].filter(s=>s!==selInv.status).map(s=>(
                    <button key={s} className="btn btn-outline btn-sm" onClick={()=>updateStatus(selInv.id,s)}>
                      {s==='paid'?<Check size={13}/>:null} Mark {s}
                    </button>
                  ))}
                  <button className="btn btn-ghost btn-sm" onClick={()=>setView('list')}>← Back</button>
                </div>
              </div>
              <div className="grid-2" style={{gap:24,marginBottom:20}}>
                <div>
                  <div style={{fontSize:'.72rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em',marginBottom:8}}>From</div>
                  <div style={{fontWeight:700}}>{selBiz?.name}</div>
                  <div style={{fontSize:'.8rem',color:'var(--text-2)'}}>{selBiz?.email}</div>
                  <div style={{fontSize:'.8rem',color:'var(--text-2)'}}>{selBiz?.tax_id}</div>
                </div>
                <div>
                  <div style={{fontSize:'.72rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em',marginBottom:8}}>Bill To</div>
                  <div style={{fontWeight:700}}>{selInv.bill_to_name||'—'}</div>
                  <div style={{fontSize:'.8rem',color:'var(--text-2)'}}>{selInv.bill_to_email}</div>
                  <div style={{fontSize:'.8rem',color:'var(--text-2)'}}>{selInv.bill_to_address}</div>
                </div>
              </div>
              <div style={{overflowX:'auto',marginBottom:16}}>
                <table className="data-table">
                  <thead><tr><th>Description</th><th style={{textAlign:'right'}}>Qty</th><th style={{textAlign:'right'}}>Unit</th><th style={{textAlign:'right'}}>Total</th></tr></thead>
                  <tbody>
                    {(selInv.items||[]).map((it,i)=>(
                      <tr key={i}>
                        <td>{it.description}</td>
                        <td className="mono" style={{textAlign:'right'}}>{it.quantity}</td>
                        <td className="mono" style={{textAlign:'right'}}>{fmtAUD(it.unit_price)}</td>
                        <td className="mono" style={{textAlign:'right',fontWeight:600}}>{fmtAUD(it.line_total||it.quantity*it.unit_price)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{textAlign:'right',fontSize:'.875rem',color:'var(--text-2)'}}>
                <div style={{marginBottom:4}}>Subtotal: {fmtAUD(selInv.subtotal)}</div>
                <div style={{marginBottom:4}}>GST: {fmtAUD(selInv.tax_amount)}</div>
                <div style={{fontSize:'1.1rem',fontWeight:700,fontFamily:'var(--font-mono)',color:'var(--brand)'}}>Total: {fmtAUD(selInv.total_amount)}</div>
              </div>
              {selInv.notes&&<div style={{marginTop:14,padding:'10px 14px',background:'var(--surface-2)',borderRadius:'var(--r-md)',fontSize:'.8rem',color:'var(--text-2)'}}><strong>Notes:</strong> {selInv.notes}</div>}
            </div>
          )}

          {!selBiz && view==='list' && (
            <div className="card">
              <div className="empty-state">
                <div className="empty-icon">🏢</div>
                <h3>Select or create a business</h3>
                <p>Choose a business profile from the left panel to manage its invoices.</p>
                <button className="btn btn-primary" style={{marginTop:12}} onClick={()=>setView('new-biz')}>Create Business</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
