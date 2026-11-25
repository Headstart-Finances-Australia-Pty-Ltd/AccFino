import React, { useState, useEffect, useRef } from 'react'
import { useAuth } from '../../hooks/useAuth.jsx'
import PurchaseOrders from './PurchaseOrders.jsx'
import {
  listDocuments, patchDocument, deleteDocument, extractPurchase,
  listSuppliers, createSupplier,
} from '../../lib/accountingApi.js'
import toast from 'react-hot-toast'
import { Upload, FileText, Trash2, Check, RefreshCw, Plus, ChevronDown, ChevronUp, ScanLine } from 'lucide-react'

const STATUS_COLORS = {
  pending:    { bg:'#fef3c7', color:'#92400e' },
  approved:   { bg:'#dcfce7', color:'#166534' },
  paid:       { bg:'#dcfce7', color:'#15803d' },
  disputed:   { bg:'#fee2e2', color:'#991b1b' },
  unmatched:  { bg:'#f3f4f6', color:'#374151' },
  matched:    { bg:'#dbeafe', color:'#1e40af' },
  reconciled: { bg:'#dcfce7', color:'#166534' },
}

const fmtAUD  = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(n||0)
const fmtDate = d => d ? new Date(d).toLocaleDateString('en-AU') : '—'

export default function PurchasePage() {
  const { user } = useAuth()
  const userId   = user?.id

  const [tab,       setTab]       = useState('po')
  const [bills,     setBills]     = useState([])
  const [receipts,  setReceipts]  = useState([])
  const [suppliers, setSuppliers] = useState([])
  const [loading,   setLoading]   = useState(false)
  const [expanded,  setExpanded]  = useState({})
  const [extracting, setExtracting] = useState(false)
  const [extractFiles, setExtractFiles] = useState([])
  const [extractType,  setExtractType]  = useState('bill')
  const [tessCmd, setTessCmd] = useState('')
  const [popBin,  setPopBin]  = useState('')
  const [showOCR, setShowOCR] = useState(false)
  const fileRef = useRef()

  const load = async () => {
    if (!userId) return
    setLoading(true)
    try {
      const [br, rr, sr] = await Promise.all([
        listDocuments(userId, 'bill'),
        listDocuments(userId, 'receipt'),
        listSuppliers(userId),
      ])
      setBills(br.data || [])
      setReceipts(rr.data || [])
      setSuppliers(sr.data || [])
    } catch { toast.error('Failed to load') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [userId])

  const handleExtract = async () => {
    if (!extractFiles.length) { toast.error('Upload at least one file'); return }
    setExtracting(true)
    try {
      const fd = new FormData()
      extractFiles.forEach(f => fd.append('files', f, f.name))
      fd.append('user_id',  userId)
      fd.append('doc_type', extractType)
      fd.append('save',     'true')
      if (tessCmd) fd.append('tesseract_cmd', tessCmd)
      if (popBin)  fd.append('poppler_bin',   popBin)

      const { data } = await extractPurchase(fd)
      const saved = data.saved || []
      toast.success(`Extracted and saved ${saved.length} ${extractType}(s) ✓`)
      setExtractFiles([])
      load()
      setTab(extractType === 'bill' ? 'bills' : 'receipts')
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Extraction failed')
    } finally { setExtracting(false) }
  }

  const handleStatusChange = async (id, status) => {
    try {
      await patchDocument(id, userId, { status })
      toast.success('Status updated')
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

  const StatusBadge = ({ s }) => {
    const c = STATUS_COLORS[s] || { bg:'var(--surface-2)', color:'var(--text-3)' }
    return (
      <span style={{
        padding:'2px 10px', borderRadius:100, fontSize:'.72rem', fontWeight:700,
        background: c.bg, color: c.color, whiteSpace:'nowrap',
      }}>{s}</span>
    )
  }

  const DocTable = ({ docs, type }) => {
    const statuses = type === 'bill'
      ? ['pending','approved','paid','disputed']
      : ['unmatched','matched','reconciled']

    return docs.length === 0
      ? <div className="empty-state" style={{padding:40}}>
          <p>No {type}s yet. Upload a PDF or image to extract data automatically.</p>
        </div>
      : <table className="data-table">
          <thead>
            <tr>
              <th>Number</th><th>Supplier / Source</th><th>Date</th>
              <th style={{textAlign:'right'}}>GST</th>
              <th style={{textAlign:'right'}}>Total</th>
              <th>Status</th><th>GL Account</th><th style={{width:110}}>Actions</th>
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
                  <td style={{fontSize:'.82rem'}}>
                    <div>{doc.party_name || doc.source_file || '—'}</div>
                    {doc.source_file && doc.party_name && (
                      <div style={{fontSize:'.68rem',color:'var(--text-3)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',maxWidth:160}}>
                        📎 {doc.source_file}
                      </div>
                    )}
                  </td>
                  <td style={{fontSize:'.78rem',whiteSpace:'nowrap'}}>{fmtDate(doc.document_date)}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontSize:'.78rem',color:'var(--brand)'}}>{fmtAUD(doc.tax_amount)}</td>
                  <td style={{textAlign:'right',fontFamily:'var(--font-mono)',fontWeight:600}}>{fmtAUD(doc.total_amount)}</td>
                  <td><StatusBadge s={doc.status}/></td>
                  <td>
                    <GLAccountCell doc={doc} userId={userId} onSaved={load}/>
                  </td>
                  <td>
                    <div style={{display:'flex',gap:4,alignItems:'center'}}>
                      <select
                        value={doc.status}
                        onChange={e => handleStatusChange(doc.id, e.target.value)}
                        className="select-compact"
                        style={{fontSize:'.7rem',padding:'2px 4px',minWidth:80}}>
                        {statuses.map(s => <option key={s}>{s}</option>)}
                      </select>
                      <button className="btn btn-danger btn-xs" onClick={() => handleDelete(doc.id)}
                        style={{padding:'2px 6px'}}><Trash2 size={11}/></button>
                    </div>
                  </td>
                </tr>
                {expanded[doc.id] && (
                  <tr style={{background:'var(--surface-2)'}}>
                    <td colSpan={8} style={{padding:'12px 16px'}}>
                      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16}}>
                        {/* Line items */}
                        <div>
                          {doc.line_items.length > 0 ? (
                            <table style={{width:'100%',borderCollapse:'collapse',fontSize:'.78rem'}}>
                              <thead><tr style={{borderBottom:'1px solid var(--border)'}}>
                                <th style={{padding:'3px 6px',textAlign:'left'}}>Description</th>
                                <th style={{padding:'3px 6px',textAlign:'right',width:60}}>Qty</th>
                                <th style={{padding:'3px 6px',textAlign:'right',width:90}}>Total</th>
                              </tr></thead>
                              <tbody>
                                {doc.line_items.map((li,i) => (
                                  <tr key={i}>
                                    <td style={{padding:'3px 6px'}}>{li.description}</td>
                                    <td style={{padding:'3px 6px',textAlign:'right'}}>{li.quantity}</td>
                                    <td style={{padding:'3px 6px',textAlign:'right',fontWeight:600}}>{fmtAUD(li.line_total)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          ) : <div style={{color:'var(--text-3)',fontSize:'.78rem'}}>No line items extracted</div>}
                        </div>
                        {/* Extracted data */}
                        <div style={{fontSize:'.75rem',color:'var(--text-3)'}}>
                          {doc.party_abn && <div><strong>ABN:</strong> {doc.party_abn}</div>}
                          {doc.notes && <div><strong>Notes:</strong> {doc.notes}</div>}
                          <div style={{display:'flex',justifyContent:'flex-end',gap:16,marginTop:8}}>
                            <span>Subtotal: <strong>{fmtAUD(doc.subtotal)}</strong></span>
                            <span>GST: <strong>{fmtAUD(doc.tax_amount)}</strong></span>
                            <span style={{fontSize:'.85rem'}}>Total: <strong>{fmtAUD(doc.total_amount)}</strong></span>
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
  }

  return (
    <div className="fade-in">
      <div style={{marginBottom:18,display:'flex',alignItems:'flex-start',justifyContent:'space-between',gap:12}}>
        <div>
          <h1>🧾 Purchase</h1>
          <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
            Extract and manage Bills and Receipts from PDF/image documents
          </p>
        </div>
        <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}>
          <RefreshCw size={13} className={loading?'spin':''}/> Refresh
        </button>
      </div>

      <div className="tabs-bar" style={{marginBottom:0}}>
        <button className={`tab-btn${tab==='po'?' active':''}`}        onClick={() => setTab('po')}>📋 Purchase Orders</button>
        <button className={`tab-btn${tab==='bills'?' active':''}`}     onClick={() => setTab('bills')}>🧾 Bills ({bills.length})</button>
        <button className={`tab-btn${tab==='receipts'?' active':''}`}  onClick={() => setTab('receipts')}>🗃 Receipts ({receipts.length})</button>
        <button className={`tab-btn${tab==='extract'?' active':''}`}   onClick={() => setTab('extract')}>📤 Upload & Extract</button>
        <button className={`tab-btn${tab==='suppliers'?' active':''}`} onClick={() => setTab('suppliers')}>🏭 Suppliers ({suppliers.length})</button>
      </div>

      <div style={{background:'var(--surface)',border:'1px solid var(--border)',
        borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        overflow:'hidden',boxShadow:'var(--sh-sm)'}}>

        {tab === 'po'      && <PurchaseOrders userId={userId}/>}
        {tab === 'bills'    && <DocTable docs={bills}    type="bill"/>}
        {tab === 'receipts' && <DocTable docs={receipts} type="receipt"/>}

        {tab === 'extract' && (
          <div style={{padding:24}}>
            <h3 style={{marginBottom:16}}>Upload Bills or Receipts</h3>

            {/* Type selector */}
            <div style={{display:'flex',gap:8,marginBottom:16}}>
              {['bill','receipt'].map(t => (
                <button key={t}
                  onClick={() => setExtractType(t)}
                  className={`btn btn-sm ${extractType===t?'btn-primary':'btn-outline'}`}>
                  {t === 'bill' ? '📋 Bill (Supplier Invoice)' : '🧾 Receipt (Proof of Payment)'}
                </button>
              ))}
            </div>

            {/* Drop zone */}
            <div className="drop-zone" style={{marginBottom:12}}
              onClick={() => fileRef.current?.click()}
              onDrop={e => { e.preventDefault(); setExtractFiles(p => [...p, ...Array.from(e.dataTransfer.files)]) }}
              onDragOver={e => e.preventDefault()}>
              <ScanLine size={22} className="drop-icon"/>
              <div style={{fontWeight:600,fontSize:'.875rem',color:'var(--text-2)'}}>
                Drop PDF / image files here or click to browse
              </div>
              <div style={{fontSize:'.75rem',color:'var(--text-3)'}}>
                Supports: PDF, PNG, JPG, TIFF, BMP, WEBP
              </div>
            </div>
            <input ref={fileRef} type="file"
              accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.webp" multiple
              style={{display:'none'}}
              onChange={e => setExtractFiles(p => [...p, ...Array.from(e.target.files)])}/>

            {extractFiles.length > 0 && (
              <div style={{display:'flex',flexDirection:'column',gap:4,marginBottom:12}}>
                {extractFiles.map((f,i) => (
                  <div key={i} style={{display:'flex',alignItems:'center',gap:8,
                    padding:'6px 10px',background:'var(--brand-xlight)',
                    border:'1px solid #A7F3D0',borderRadius:'var(--r-sm)'}}>
                    <FileText size={13} color="var(--brand)" style={{flexShrink:0}}/>
                    <span style={{flex:1,fontSize:'.78rem',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{f.name}</span>
                    <span style={{fontSize:'.72rem',color:'var(--text-3)'}}>{(f.size/1024).toFixed(0)}KB</span>
                    <button onClick={() => setExtractFiles(p => p.filter((_,j)=>j!==i))}
                      style={{background:'none',border:'none',cursor:'pointer',color:'var(--text-3)'}}>✕</button>
                  </div>
                ))}
              </div>
            )}

            {/* OCR settings */}
            <button className="btn btn-ghost btn-sm" onClick={() => setShowOCR(s=>!s)}
              style={{marginBottom:showOCR?12:8}}>
              ⚙️ OCR Settings {showOCR?'▲':'▼'}
            </button>
            {showOCR && (
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12,marginBottom:12,
                padding:12,background:'var(--surface-2)',borderRadius:'var(--r-md)'}}>
                <div className="input-group">
                  <label>Tesseract Path</label>
                  <input className="input input-sm" value={tessCmd} onChange={e=>setTessCmd(e.target.value)}
                    placeholder="C:\Program Files\Tesseract-OCR\tesseract.exe"/>
                </div>
                <div className="input-group">
                  <label>Poppler Bin Directory</label>
                  <input className="input input-sm" value={popBin} onChange={e=>setPopBin(e.target.value)}
                    placeholder="C:\poppler\bin"/>
                </div>
              </div>
            )}

            <div style={{display:'flex',gap:8,alignItems:'center'}}>
              <button className="btn btn-primary" onClick={handleExtract}
                disabled={!extractFiles.length || extracting}>
                {extracting
                  ? <><span className="spinner spinner-sm"/> Extracting…</>
                  : <><ScanLine size={15}/> Extract & Save {extractType === 'bill' ? 'Bills' : 'Receipts'}</>
                }
              </button>
              {extractFiles.length > 0 && (
                <button className="btn btn-ghost btn-sm" onClick={() => setExtractFiles([])}>Clear All</button>
              )}
            </div>

            <div style={{marginTop:24,padding:16,background:'var(--surface-2)',
              borderRadius:'var(--r-md)',border:'1px solid var(--border)'}}>
              <h4 style={{marginBottom:12,fontSize:'.875rem'}}>What gets extracted</h4>
              <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12,fontSize:'.8rem'}}>
                {[
                  {emoji:'📋',title:'Bills',desc:'Supplier name, ABN, invoice date, due date, line items, GST, total'},
                  {emoji:'🧾',title:'Receipts',desc:'Vendor name, date, items purchased, GST, total amount paid'},
                  {emoji:'🤖',title:'Auto-save',desc:'Extracted data is automatically saved to your Purchase register'},
                ].map(({emoji,title,desc}) => (
                  <div key={title} style={{padding:12,background:'var(--surface)',
                    borderRadius:'var(--r-md)',border:'1px solid var(--border)'}}>
                    <div style={{fontSize:'1.3rem',marginBottom:6}}>{emoji}</div>
                    <div style={{fontWeight:600,marginBottom:4}}>{title}</div>
                    <div style={{color:'var(--text-3)',lineHeight:1.5}}>{desc}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === 'suppliers' && <SuppliersTab userId={userId} suppliers={suppliers} onRefresh={load}/>}
      </div>
    </div>
  )
}

// ── Inline GL account editor ──────────────────────────────────────────────────
function GLAccountCell({ doc, userId, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(doc.gl_account || '')
  const [glList, setGlList] = useState([])

  useEffect(() => {
    fetch('/api/gl/accounts').then(r => r.json()).then(d => {
      if (Array.isArray(d)) setGlList(d.filter(Boolean))
    }).catch(() => {})
  }, [])

  const save = async () => {
    try {
      await patchDocument(doc.id, userId, { gl_account: val })
      setEditing(false)
      onSaved()
    } catch { toast.error('Failed to save GL') }
  }

  if (!editing)
    return (
      <button onClick={() => setEditing(true)}
        style={{background:'none',border:'none',cursor:'pointer',
          color: doc.gl_account ? 'var(--text-1)' : 'var(--text-3)',
          fontSize:'.78rem',textAlign:'left',padding:'2px 4px'}}>
        {doc.gl_account || '+ Set GL'}
      </button>
    )

  return (
    <div style={{display:'flex',gap:4}}>
      <select value={val} onChange={e => setVal(e.target.value)}
        className="select-compact" style={{fontSize:'.75rem',flex:1}}>
        <option value="">— GL Account —</option>
        {glList.map(g => <option key={g}>{g}</option>)}
      </select>
      <button className="btn btn-primary btn-xs" onClick={save}><Check size={11}/></button>
      <button className="btn btn-ghost btn-xs" onClick={() => setEditing(false)}>✕</button>
    </div>
  )
}

// ── Suppliers tab ─────────────────────────────────────────────────────────────
function SuppliersTab({ userId, suppliers, onRefresh }) {
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({ name:'', email:'', phone:'', abn:'', address:'', gl_account:'' })
  const [saving, setSaving] = useState(false)
  const [glList, setGlList] = useState([])

  useEffect(() => {
    fetch('/api/gl/accounts').then(r=>r.json()).then(d=>{if(Array.isArray(d))setGlList(d.filter(Boolean))}).catch(()=>{})
  }, [])

  const handleAdd = async () => {
    if (!form.name) { toast.error('Supplier name required'); return }
    setSaving(true)
    try {
      await createSupplier({ user_id: userId, ...form })
      toast.success('Supplier added ✓')
      setShowAdd(false)
      setForm({ name:'', email:'', phone:'', abn:'', address:'', gl_account:'' })
      onRefresh()
    } catch { toast.error('Failed to add supplier') }
    finally { setSaving(false) }
  }

  return (
    <div style={{padding:24}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
        <h3>Suppliers</h3>
        <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(s => !s)}>
          <Plus size={13}/> Add Supplier
        </button>
      </div>

      {showAdd && (
        <div className="card card-flat" style={{background:'var(--surface-2)',marginBottom:16}}>
          <h4 style={{marginBottom:12}}>New Supplier</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
            {[['name','Name *'],['email','Email'],['phone','Phone'],['abn','ABN'],['address','Address']].map(([f,l]) => (
              <div key={f} className="input-group">
                <label>{l}</label>
                <input className="input input-sm" value={form[f]||''}
                  onChange={e => setForm(p => ({...p, [f]: e.target.value}))}/>
              </div>
            ))}
            <div className="input-group">
              <label>Default GL Account</label>
              <select className="input input-sm" value={form.gl_account||''}
                onChange={e => setForm(p => ({...p, gl_account: e.target.value}))}>
                <option value="">— Select GL —</option>
                {glList.map(g => <option key={g}>{g}</option>)}
              </select>
            </div>
          </div>
          <div style={{display:'flex',gap:8,marginTop:12}}>
            <button className="btn btn-primary btn-sm" onClick={handleAdd} disabled={saving}>
              {saving ? 'Saving…' : <><Check size={13}/> Save</>}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}

      {suppliers.length === 0
        ? <div className="empty-state" style={{padding:40}}><p>No suppliers yet.</p></div>
        : <table className="data-table">
            <thead>
              <tr>
                <th>Name</th><th>Email</th><th>Phone</th><th>ABN</th><th>Default GL</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map(s => (
                <tr key={s.id}>
                  <td style={{fontWeight:600}}>{s.name}</td>
                  <td style={{fontSize:'.82rem'}}>{s.email||'—'}</td>
                  <td style={{fontSize:'.82rem'}}>{s.phone||'—'}</td>
                  <td style={{fontFamily:'var(--font-mono)',fontSize:'.78rem'}}>{s.abn||'—'}</td>
                  <td style={{fontSize:'.78rem'}}>{s.gl_account||'—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
      }
    </div>
  )
}
