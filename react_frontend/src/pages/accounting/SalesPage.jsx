import React, { useState, useEffect, useRef } from 'react'
import { useAuth } from '../../hooks/useAuth.jsx'
import {
  listDocuments, createDocument, patchDocument, deleteDocument, convertToInvoice,
} from '../../lib/accountingApi.js'
import toast from 'react-hot-toast'
import { Plus, Trash2, Download, Send, Check, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import ContactsTab from './ContactsTab.jsx'

// ── Reuse existing InvoiceGenerator for PDF output ───────────────────────────
import InvoiceGenerator from '../invoice/InvoiceGenerator.jsx'

const STATUS_COLORS = {
  draft:     { bg:'var(--surface-2)',    color:'var(--text-3)' },
  sent:      { bg:'#dbeafe',            color:'#1d4ed8' },
  accepted:  { bg:'#dcfce7',            color:'#16a34a' },
  paid:      { bg:'#dcfce7',            color:'#15803d' },
  converted: { bg:'#fef9c3',            color:'#854d0e' },
  declined:  { bg:'#fee2e2',            color:'#b91c1c' },
  void:      { bg:'#f3f4f6',            color:'#6b7280' },
  overdue:   { bg:'#fee2e2',            color:'#dc2626' },
}

const fmtAUD = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n||0)
const fmtDate = d => d ? new Date(d).toLocaleDateString('en-AU') : '—'

export default function SalesPage({ userId }) {
  const { user }   = useAuth()
  const _userId    = userId || user?.id
  const effectiveUserId = userId || user?.id
  const [tab, setTab] = useState('invoices')   // 'quotes' | 'invoices' | 'create'
  const [createType, setCreateType] = useState('invoice')

  const [quotes,   setQuotes]   = useState([])
  const [invoices, setInvoices] = useState([])
  const [loading,  setLoading]  = useState(false)
  const [expanded, setExpanded] = useState({})

  const load = async () => {
    if (!userId) return
    setLoading(true)
    try {
      const [qr, ir] = await Promise.all([
        listDocuments(userId, 'quote'),
        listDocuments(userId, 'invoice'),
      ])
      setQuotes(qr.data || [])
      setInvoices(ir.data || [])
    } catch { toast.error('Failed to load documents') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [userId])

  const handleStatusChange = async (id, status) => {
    try {
      await patchDocument(id, userId, { status })
      toast.success(`Status updated to ${status}`)
      load()
    } catch { toast.error('Update failed') }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this document?')) return
    try {
      await deleteDocument(id, userId)
      toast.success('Deleted')
      load()
    } catch { toast.error('Delete failed') }
  }

  const handleConvert = async (id) => {
    try {
      await convertToInvoice(id, userId)
      toast.success('Quote converted to Invoice ✓')
      load()
      setTab('invoices')
    } catch { toast.error('Conversion failed') }
  }

  const StatusBadge = ({ s }) => {
    const c = STATUS_COLORS[s] || STATUS_COLORS.draft
    return (
      <span style={{
        padding:'2px 10px', borderRadius:100, fontSize:'.72rem', fontWeight:700,
        background: c.bg, color: c.color, whiteSpace:'nowrap',
      }}>{s}</span>
    )
  }

  const DocTable = ({ docs, type }) => (
    docs.length === 0
      ? <div className="empty-state" style={{padding:40}}>
          <p>No {type}s yet. Click + New {type.charAt(0).toUpperCase()+type.slice(1)} to create one.</p>
        </div>
      : <table className="data-table">
          <thead>
            <tr>
              <th>Number</th><th>To</th><th>Date</th><th>Due</th>
              <th style={{textAlign:'right'}}>Total</th>
              <th>Status</th><th style={{width:130}}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {docs.map(doc => (
              <React.Fragment key={doc.id}>
                <tr>
                  <td>
                    <button
                      onClick={() => setExpanded(p => ({...p, [doc.id]: !p[doc.id]}))}
                      style={{background:'none',border:'none',cursor:'pointer',color:'var(--brand)',
                        fontFamily:'var(--font-mono)',fontSize:'.78rem',fontWeight:600,display:'flex',alignItems:'center',gap:4}}>
                      {expanded[doc.id] ? <ChevronUp size={12}/> : <ChevronDown size={12}/>}
                      {doc.document_number}
                    </button>
                  </td>
                  <td style={{fontSize:'.82rem'}}>{doc.party_name || '—'}</td>
                  <td style={{fontSize:'.78rem',whiteSpace:'nowrap'}}>{fmtDate(doc.document_date)}</td>
                  <td style={{fontSize:'.78rem',whiteSpace:'nowrap'}}>{fmtDate(doc.due_date)}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:600}}>{fmtAUD(doc.total_amount)}</td>
                  <td><StatusBadge s={doc.status}/></td>
                  <td>
                    <div style={{display:'flex',gap:4,alignItems:'center'}}>
                      {type === 'quote' && doc.status !== 'converted' && (
                        <button className="btn btn-outline btn-xs"
                          onClick={() => handleConvert(doc.id)}
                          title="Convert to Invoice"
                          style={{fontSize:'.65rem',padding:'2px 6px'}}>
                          → INV
                        </button>
                      )}
                      <select
                        value={doc.status}
                        onChange={e => handleStatusChange(doc.id, e.target.value)}
                        className="select-compact"
                        style={{fontSize:'.7rem',padding:'2px 4px',minWidth:70}}>
                        {type === 'quote'
                          ? ['draft','sent','accepted','declined','expired','converted'].map(s => <option key={s}>{s}</option>)
                          : ['draft','sent','paid','overdue','void'].map(s => <option key={s}>{s}</option>)
                        }
                      </select>
                      <button className="btn btn-danger btn-xs" onClick={() => handleDelete(doc.id)}
                        style={{padding:'2px 6px'}}><Trash2 size={11}/></button>
                    </div>
                  </td>
                </tr>
                {expanded[doc.id] && (
                  <tr style={{background:'var(--surface-2)'}}>
                    <td colSpan={7} style={{padding:'12px 16px'}}>
                      {doc.line_items.length > 0 && (
                        <table style={{width:'100%',borderCollapse:'collapse',fontSize:'.78rem'}}>
                          <thead>
                            <tr style={{borderBottom:'1px solid var(--border)'}}>
                              <th style={{padding:'4px 8px',textAlign:'left'}}>Description</th>
                              <th style={{padding:'4px 8px',textAlign:'right',width:60}}>Qty</th>
                              <th style={{padding:'4px 8px',textAlign:'right',width:100}}>Unit Price</th>
                              <th style={{padding:'4px 8px',textAlign:'right',width:100}}>Total</th>
                            </tr>
                          </thead>
                          <tbody>
                            {doc.line_items.map((li,i) => (
                              <tr key={i}>
                                <td style={{padding:'4px 8px'}}>{li.description}</td>
                                <td style={{padding:'4px 8px',textAlign:'right'}}>{li.quantity}</td>
                                <td style={{padding:'4px 8px',textAlign:'right'}}>{fmtAUD(li.unit_price)}</td>
                                <td style={{padding:'4px 8px',textAlign:'right',fontWeight:600}}>{fmtAUD(li.line_total)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                      <div style={{display:'flex',justifyContent:'flex-end',gap:24,marginTop:8,fontSize:'.8rem'}}>
                        <span>Subtotal: <strong>{fmtAUD(doc.subtotal)}</strong></span>
                        <span>GST ({doc.tax_percent}%): <strong>{fmtAUD(doc.tax_amount)}</strong></span>
                        <span style={{fontSize:'.9rem'}}>Total: <strong>{fmtAUD(doc.total_amount)}</strong></span>
                      </div>
                      {doc.notes && <div style={{marginTop:8,fontSize:'.75rem',color:'var(--text-3)'}}>Notes: {doc.notes}</div>}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
  )

  return (
    <div className="fade-in">
      <div style={{marginBottom:18,display:'flex',alignItems:'flex-start',justifyContent:'space-between',gap:12}}>
        <div>
          <h1>💼 Sales</h1>
          <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
            Customers · Quotes · Invoices
          </p>
        </div>
        <div style={{display:'flex',gap:8}}>
          <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}>
            <RefreshCw size={13} className={loading?'spin':''}/> Refresh
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => { setCreateType('quote'); setTab('create') }}>
            <Plus size={13}/> New Quote
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => { setCreateType('invoice'); setTab('create') }}>
            <Plus size={13}/> New Invoice
          </button>
        </div>
      </div>

      <div className="tabs-bar" style={{marginBottom:0}}>
        <button className={`tab-btn${tab==='customers'? ' active':''}`} onClick={() => setTab('customers')}>👥 Customers</button>
        <button className={`tab-btn${tab==='invoices'?' active':''}`} onClick={() => setTab('invoices')}>
          📄 Invoices ({invoices.length})
        </button>
        <button className={`tab-btn${tab==='quotes'?' active':''}`} onClick={() => setTab('quotes')}>
          📝 Quotes ({quotes.length})
        </button>
        <button className={`tab-btn${tab==='create'?' active':''}`} onClick={() => { setCreateType('invoice'); setTab('create') }}>
          ✏️ Create New
        </button>
      </div>

      <div style={{background:'var(--surface)',border:'1px solid var(--border)',
        borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        padding: tab === 'create' ? 0 : 0, overflow:'hidden', boxShadow:'var(--sh-sm)'}}>

        {tab === 'customers' && <ContactsTab userId={effectiveUserId} type="customer"/>}
        {tab === 'invoices' && <DocTable docs={invoices} type="invoice"/>}
        {tab === 'quotes'   && <DocTable docs={quotes}   type="quote"/>}
        {tab === 'create'   && (
          <div style={{padding:24}}>
            <div style={{display:'flex',gap:8,marginBottom:20}}>
              {['invoice','quote'].map(t => (
                <button key={t}
                  onClick={() => setCreateType(t)}
                  className={`btn btn-sm ${createType===t?'btn-primary':'btn-outline'}`}>
                  {t === 'invoice' ? '📄 Invoice' : '📝 Quote'}
                </button>
              ))}
            </div>
            {/* Reuse the existing InvoiceGenerator, enhanced to save to accounting_documents */}
            <SaleDocumentForm
              userId={userId}
              docType={createType}
              onSaved={() => { load(); setTab(createType === 'invoice' ? 'invoices' : 'quotes') }}
            />
          </div>
        )}
      </div>
    </div>
  )
}

// ── Inline document creation form ────────────────────────────────────────────
function SaleDocumentForm({ userId, docType, onSaved }) {
  const [lines, setLines]  = useState([{ description:'', quantity:1, unit_price:0 }])
  const [party, setParty]  = useState({ name:'', email:'', phone:'', address:'', abn:'' })
  const [meta,  setMeta]   = useState({
    document_date: new Date().toISOString().split('T')[0],
    due_date: '',
    notes: '',
    payment_terms: 'Net 30',
    tax_percent: 10,
    business_name: '',
  })
  const [saving, setSaving] = useState(false)

  const subtotal = lines.reduce((s,l) => s + (parseFloat(l.quantity)||0)*(parseFloat(l.unit_price)||0), 0)
  const tax      = subtotal * (meta.tax_percent / 100)
  const total    = subtotal + tax

  const setLine = (i, field, val) =>
    setLines(ls => ls.map((l,j) => j===i ? {...l, [field]: val} : l))

  const handleSave = async () => {
    if (!lines[0].description) { toast.error('Add at least one line item'); return }
    setSaving(true)
    try {
      await createDocument({
        user_id:       userId,
        document_type: docType,
        document_date: meta.document_date ? new Date(meta.document_date).toISOString() : null,
        due_date:      meta.due_date       ? new Date(meta.due_date).toISOString()      : null,
        party_name:    party.name,
        party_email:   party.email,
        party_phone:   party.phone,
        party_address: party.address,
        party_abn:     party.abn,
        business_name: meta.business_name,
        tax_percent:   parseFloat(meta.tax_percent) || 10,
        notes:         meta.notes,
        payment_terms: meta.payment_terms,
        line_items:    lines.filter(l => l.description).map((l,i) => ({
          sort_order:  i,
          description: l.description,
          quantity:    parseFloat(l.quantity) || 1,
          unit_price:  parseFloat(l.unit_price) || 0,
        })),
      })
      toast.success(`${docType === 'invoice' ? 'Invoice' : 'Quote'} created ✓`)
      onSaved()
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Save failed')
    } finally { setSaving(false) }
  }

  const fmtAUD = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n||0)

  return (
    <div style={{display:'flex',flexDirection:'column',gap:20}}>
      {/* Party details */}
      <div className="card card-flat" style={{background:'var(--surface-2)'}}>
        <h4 style={{marginBottom:12}}>Customer Details</h4>
        <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
          {[['name','Name *'],['email','Email'],['phone','Phone'],['abn','ABN']].map(([f,l]) => (
            <div key={f} className="input-group">
              <label>{l}</label>
              <input className="input input-sm" value={party[f]||''}
                onChange={e => setParty(p => ({...p,[f]:e.target.value}))}/>
            </div>
          ))}
          <div className="input-group" style={{gridColumn:'span 2'}}>
            <label>Address</label>
            <input className="input input-sm" value={party.address||''}
              onChange={e => setParty(p => ({...p, address:e.target.value}))}/>
          </div>
        </div>
      </div>

      {/* Document meta */}
      <div className="card card-flat" style={{background:'var(--surface-2)'}}>
        <h4 style={{marginBottom:12}}>Document Details</h4>
        <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12}}>
          {[
            ['document_date','Date','date'],
            ['due_date', docType==='quote'?'Expiry Date':'Due Date','date'],
            ['tax_percent','GST %','number'],
            ['payment_terms','Payment Terms','text'],
          ].map(([f,l,t]) => (
            <div key={f} className="input-group">
              <label>{l}</label>
              <input className="input input-sm" type={t} value={meta[f]||''}
                onChange={e => setMeta(m => ({...m,[f]:e.target.value}))}/>
            </div>
          ))}
          <div className="input-group">
            <label>Your Business Name</label>
            <input className="input input-sm" value={meta.business_name||''}
              onChange={e => setMeta(m => ({...m, business_name:e.target.value}))}/>
          </div>
        </div>
      </div>

      {/* Line items */}
      <div className="card card-flat" style={{background:'var(--surface-2)'}}>
        <h4 style={{marginBottom:12}}>Line Items</h4>
        <table style={{width:'100%',borderCollapse:'collapse',marginBottom:8}}>
          <thead>
            <tr style={{borderBottom:'1px solid var(--border)'}}>
              <th style={{padding:'4px 8px',textAlign:'left',fontSize:'.78rem'}}>Description</th>
              <th style={{padding:'4px 8px',textAlign:'right',width:70,fontSize:'.78rem'}}>Qty</th>
              <th style={{padding:'4px 8px',textAlign:'right',width:110,fontSize:'.78rem'}}>Unit Price</th>
              <th style={{padding:'4px 8px',textAlign:'right',width:110,fontSize:'.78rem'}}>Total</th>
              <th style={{width:32}}/>
            </tr>
          </thead>
          <tbody>
            {lines.map((line,i) => (
              <tr key={i}>
                <td style={{padding:'4px 4px'}}>
                  <input className="cell-input" style={{width:'100%',fontSize:'.82rem'}}
                    placeholder="Item description"
                    value={line.description}
                    onChange={e => setLine(i,'description',e.target.value)}/>
                </td>
                <td style={{padding:'4px 4px'}}>
                  <input className="cell-input" type="number" min="0" step="0.01"
                    style={{width:60,textAlign:'right',fontSize:'.82rem'}}
                    value={line.quantity}
                    onChange={e => setLine(i,'quantity',e.target.value)}/>
                </td>
                <td style={{padding:'4px 4px'}}>
                  <input className="cell-input" type="number" min="0" step="0.01"
                    style={{width:100,textAlign:'right',fontSize:'.82rem'}}
                    value={line.unit_price}
                    onChange={e => setLine(i,'unit_price',e.target.value)}/>
                </td>
                <td style={{padding:'4px 8px',textAlign:'right',fontWeight:600,fontSize:'.82rem',fontFamily:'var(--font-mono)'}}>
                  {fmtAUD((parseFloat(line.quantity)||0)*(parseFloat(line.unit_price)||0))}
                </td>
                <td>
                  {lines.length > 1 && (
                    <button onClick={() => setLines(ls => ls.filter((_,j)=>j!==i))}
                      style={{background:'none',border:'none',cursor:'pointer',color:'var(--danger)',padding:4}}>
                      <Trash2 size={12}/>
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn btn-ghost btn-xs" onClick={() => setLines(ls => [...ls,{description:'',quantity:1,unit_price:0}])}>
          <Plus size={12}/> Add Line
        </button>
      </div>

      {/* Totals + notes */}
      <div style={{display:'flex',gap:16,alignItems:'flex-start'}}>
        <div className="input-group" style={{flex:1}}>
          <label>Notes</label>
          <textarea className="input" rows={3} style={{resize:'vertical'}}
            value={meta.notes||''}
            onChange={e => setMeta(m => ({...m, notes:e.target.value}))}
            placeholder="Payment instructions, thank you note…"/>
        </div>
        <div style={{minWidth:220,background:'var(--surface-2)',borderRadius:'var(--r-md)',padding:16,border:'1px solid var(--border)'}}>
          {[
            ['Subtotal', fmtAUD(subtotal)],
            [`GST (${meta.tax_percent}%)`, fmtAUD(tax)],
          ].map(([l,v]) => (
            <div key={l} style={{display:'flex',justifyContent:'space-between',fontSize:'.82rem',marginBottom:6}}>
              <span style={{color:'var(--text-3)'}}>{l}</span>
              <span style={{fontFamily:'var(--font-mono)'}}>{v}</span>
            </div>
          ))}
          <div style={{display:'flex',justifyContent:'space-between',fontSize:'.95rem',fontWeight:700,borderTop:'1px solid var(--border)',paddingTop:8,marginTop:4}}>
            <span>Total</span>
            <span style={{fontFamily:'var(--font-mono)',color:'var(--brand)'}}>{fmtAUD(total)}</span>
          </div>
        </div>
      </div>

      <div style={{display:'flex',gap:8}}>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? <><span className="spinner spinner-sm"/> Saving…</> : <><Check size={14}/> Save {docType==='invoice'?'Invoice':'Quote'}</>}
        </button>
      </div>
    </div>
  )
}
