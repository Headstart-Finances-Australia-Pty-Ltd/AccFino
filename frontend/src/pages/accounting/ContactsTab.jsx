/**
 * ContactsTab — reusable for both Customers (Sales) and Suppliers (Purchases).
 * Features:
 *  - List with inline edit (click any cell to edit in place)
 *  - Add new via form
 *  - CSV upload (bulk import with upsert)
 *  - CSV download (export)
 *  - Delete (soft-delete via is_active=false)
 *  - All changes persisted to PostgreSQL via /accounting/customers or /accounting/suppliers
 */
import React, { useState, useEffect, useRef } from 'react'
import {
  Plus, Trash2, Check, X, Upload, Download, RefreshCw, Search, Pencil,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  listCustomers, createCustomer, patchCustomer, deleteCustomer, importCustomersCSV,
  listSuppliers, createSupplier, patchSupplier, deleteSupplier, importSuppliersCSV,
} from '../../lib/accountingApi.js'

// ── Field definitions per type ────────────────────────────────────────────────
const FIELDS = {
  customer: [
    { key:'name',         label:'Name',          required:true,  width:180 },
    { key:'email',        label:'Email',          type:'email',   width:170 },
    { key:'phone',        label:'Phone',          width:120 },
    { key:'contact_name', label:'Contact Person', width:150 },
    { key:'abn',          label:'ABN',            width:110 },
    { key:'address',      label:'Address',        width:180 },
    { key:'city',         label:'City',           width:100 },
    { key:'state',        label:'State',          width:70 },
    { key:'postcode',     label:'Postcode',       width:80 },
    { key:'gl_account',   label:'GL Account',     width:160 },
    { key:'notes',        label:'Notes',          width:150 },
  ],
  supplier: [
    { key:'name',         label:'Name',           required:true, width:180 },
    { key:'email',        label:'Email',           type:'email',  width:170 },
    { key:'phone',        label:'Phone',           width:120 },
    { key:'abn',          label:'ABN',             width:110 },
    { key:'address',      label:'Address',         width:180 },
    { key:'website',      label:'Website',         width:150 },
    { key:'gl_account',   label:'GL Account',      width:160 },
    { key:'gst_category', label:'GST Category',    width:150 },
    { key:'notes',        label:'Notes',           width:150 },
  ],
}

const CSV_TEMPLATE_CUSTOMER = 'name,email,phone,contact_name,abn,address,city,state,postcode,gl_account,notes\nAcme Corp,admin@acme.com,0400000001,Jane Smith,12345678901,1 Main St,Sydney,NSW,2000,Accounts Receivable,Key client\n'
const CSV_TEMPLATE_SUPPLIER = 'name,email,phone,abn,address,website,gl_account,gst_category,notes\nJB Hi-Fi,ap@jbhifi.com.au,0398000000,34506873233,1 Store St,Melbourne,VIC,3000,jbhifi.com.au,Accounts Payable,GST on Expenses,Regular supplier\n'

export default function ContactsTab({ userId, type }) {
  // type = 'customer' | 'supplier'
  const fields     = FIELDS[type]
  const isCustomer = type === 'customer'

  const [rows,      setRows]      = useState([])
  const [loading,   setLoading]   = useState(false)
  const [search,    setSearch]    = useState('')
  const [showAdd,   setShowAdd]   = useState(false)
  const [form,      setForm]      = useState({})
  const [saving,    setSaving]    = useState(false)
  const [editId,    setEditId]    = useState(null)
  const [editData,  setEditData]  = useState({})
  const [importing, setImporting] = useState(false)
  const fileRef = useRef()

  // ── API helpers ─────────────────────────────────────────────────────────────
  const apiList   = isCustomer ? listCustomers   : listSuppliers
  const apiCreate = isCustomer ? createCustomer  : createSupplier
  const apiPatch  = isCustomer ? patchCustomer   : patchSupplier
  const apiDelete = isCustomer ? deleteCustomer  : deleteSupplier
  const apiImport = isCustomer ? importCustomersCSV : importSuppliersCSV
  const csvTemplate = isCustomer ? CSV_TEMPLATE_CUSTOMER : CSV_TEMPLATE_SUPPLIER

  const load = async () => {
    if (!userId) return
    setLoading(true)
    try {
      const r = await apiList(userId)
      setRows(r.data || [])
    } catch { toast.error('Failed to load') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [userId, type])

  // ── Filtered rows ────────────────────────────────────────────────────────────
  const shown = rows.filter(r =>
    !search || fields.some(f => (r[f.key]||'').toLowerCase().includes(search.toLowerCase()))
  )

  // ── Add new ──────────────────────────────────────────────────────────────────
  const handleAdd = async () => {
    if (!form.name?.trim()) { toast.error('Name is required'); return }
    setSaving(true)
    try {
      await apiCreate({ ...form, user_id: userId })
      toast.success(`${isCustomer ? 'Customer' : 'Supplier'} added ✓`)
      setForm({}); setShowAdd(false); load()
    } catch(e) { toast.error(e.response?.data?.detail || 'Save failed') }
    finally { setSaving(false) }
  }

  // ── Inline edit ──────────────────────────────────────────────────────────────
  const startEdit = (row) => { setEditId(row.id); setEditData({ ...row }) }

  const cancelEdit = () => { setEditId(null); setEditData({}) }

  const saveEdit = async () => {
    if (!editData.name?.trim()) { toast.error('Name is required'); return }
    setSaving(true)
    try {
      await apiPatch(editId, userId, editData)
      toast.success('Saved ✓')
      setEditId(null); setEditData({}); load()
    } catch(e) { toast.error(e.response?.data?.detail || 'Save failed') }
    finally { setSaving(false) }
  }

  // ── Delete ───────────────────────────────────────────────────────────────────
  const handleDelete = async (id, name) => {
    if (!confirm(`Remove "${name}"?`)) return
    try {
      await apiDelete(id, userId)
      toast.success('Removed ✓')
      load()
    } catch { toast.error('Delete failed') }
  }

  // ── CSV import ───────────────────────────────────────────────────────────────
  const handleCSVImport = async (e) => {
    const file = e.target.files?.[0]; if (!file) return
    setImporting(true)
    try {
      const fd = new FormData()
      fd.append('file', file, file.name)
      fd.append('user_id', userId)
      const { data } = await apiImport(fd)
      toast.success(`✓ ${data.created} created, ${data.updated} updated${data.skipped ? `, ${data.skipped} skipped` : ''}`)
      load()
    } catch(e) { toast.error(e.response?.data?.detail || 'Import failed') }
    finally { setImporting(false); e.target.value = '' }
  }

  // ── CSV export ───────────────────────────────────────────────────────────────
  const handleExport = () => {
    const headers = fields.map(f => f.key).join(',')
    const csvRows = rows.map(r =>
      fields.map(f => `"${(r[f.key]||'').toString().replace(/"/g,'""')}"`).join(',')
    )
    const blob = new Blob([headers + '\n' + csvRows.join('\n')], { type:'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${type}s_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
  }

  const downloadTemplate = () => {
    const blob = new Blob([csvTemplate], { type:'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${type}_import_template.csv`
    a.click()
  }

  const label = isCustomer ? 'Customer' : 'Supplier'

  return (
    <div style={{padding:24}}>
      {/* Toolbar */}
      <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:16,flexWrap:'wrap'}}>
        <h3 style={{margin:0}}>{isCustomer ? 'Customers' : 'Suppliers'} ({rows.length})</h3>
        <div style={{flex:1}}/>

        {/* Search */}
        <div style={{position:'relative'}}>
          <Search size={13} style={{position:'absolute',left:8,top:'50%',transform:'translateY(-50%)',color:'var(--text-3)'}}/>
          <input className="input input-sm" style={{paddingLeft:26,width:180}} placeholder="Search…"
            value={search} onChange={e => setSearch(e.target.value)}/>
        </div>

        {/* Refresh */}
        <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}>
          <RefreshCw size={13} className={loading?'spin':''}/>
        </button>

        {/* CSV import */}
        <input ref={fileRef} type="file" accept=".csv,.tsv" style={{display:'none'}}
          onChange={handleCSVImport}/>
        <button className="btn btn-outline btn-sm" onClick={() => fileRef.current?.click()} disabled={importing}>
          {importing ? <><span className="spinner spinner-sm"/> Importing…</> : <><Upload size={13}/> Import CSV</>}
        </button>

        {/* Export */}
        <button className="btn btn-outline btn-sm" onClick={handleExport} disabled={!rows.length}>
          <Download size={13}/> Export CSV
        </button>

        {/* Template download */}
        <button className="btn btn-ghost btn-sm" onClick={downloadTemplate}
          title="Download CSV template" style={{fontSize:'.75rem',color:'var(--text-3)'}}>
          📄 Template
        </button>

        {/* Add new */}
        <button className="btn btn-primary btn-sm" onClick={() => { setShowAdd(s=>!s); setForm({}) }}>
          <Plus size={13}/> Add {label}
        </button>
      </div>

      {/* CSV info banner */}
      <div style={{marginBottom:12,padding:'8px 12px',background:'var(--surface-2)',
        borderRadius:'var(--r-md)',border:'1px solid var(--border)',
        fontSize:'.75rem',color:'var(--text-3)',display:'flex',alignItems:'center',gap:8}}>
        💡 CSV import supports bulk add and update. Rows matching an existing name are updated; new names are created.
        Click <strong>Template</strong> to download the correct column format.
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="card card-flat" style={{background:'var(--surface-2)',marginBottom:16}}>
          <h4 style={{marginBottom:12}}>New {label}</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
            {fields.map(f => (
              <div key={f.key} className="input-group">
                <label>{f.label}{f.required?' *':''}</label>
                <input className="input input-sm" type={f.type||'text'}
                  value={form[f.key]||''}
                  onChange={e => setForm(p => ({...p,[f.key]:e.target.value}))}/>
              </div>
            ))}
          </div>
          <div style={{display:'flex',gap:8,marginTop:14}}>
            <button className="btn btn-primary btn-sm" onClick={handleAdd} disabled={saving}>
              {saving ? 'Saving…' : <><Check size={13}/> Save {label}</>}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Table */}
      {shown.length === 0 ? (
        <div className="empty-state" style={{padding:40}}>
          <div style={{fontSize:'2rem',marginBottom:8}}>{isCustomer ? '👥' : '🏭'}</div>
          <p>{rows.length === 0
            ? `No ${type}s yet. Add one or import via CSV.`
            : `No ${type}s match "${search}".`}
          </p>
        </div>
      ) : (
        <div style={{overflowX:'auto'}}>
          <table className="data-table" style={{fontSize:'.78rem',minWidth:800}}>
            <thead>
              <tr>
                {fields.slice(0,6).map(f => (
                  <th key={f.key} style={{minWidth:f.width||100,whiteSpace:'nowrap'}}>{f.label}</th>
                ))}
                <th style={{width:90}}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {shown.map(row => {
                const isEditing = editId === row.id
                return (
                  <tr key={row.id}
                    style={{background: isEditing ? 'var(--brand-xlight,#eff6ff)' : undefined}}>
                    {fields.slice(0,6).map(f => (
                      <td key={f.key}>
                        {isEditing ? (
                          <input
                            className="cell-input"
                            style={{width:'100%',fontSize:'.78rem'}}
                            type={f.type||'text'}
                            value={editData[f.key]||''}
                            onChange={e => setEditData(p => ({...p,[f.key]:e.target.value}))}
                          />
                        ) : (
                          <span
                            onClick={() => startEdit(row)}
                            title="Click to edit"
                            style={{cursor:'text',display:'block',
                              color: row[f.key] ? 'var(--text-1)' : 'var(--text-3)',
                              fontStyle: row[f.key] ? 'normal' : 'italic'}}>
                            {row[f.key] || '—'}
                          </span>
                        )}
                      </td>
                    ))}
                    <td>
                      {isEditing ? (
                        <div style={{display:'flex',gap:4}}>
                          <button className="btn btn-primary btn-xs" onClick={saveEdit} disabled={saving}
                            title="Save changes">
                            <Check size={11}/>
                          </button>
                          <button className="btn btn-ghost btn-xs" onClick={cancelEdit} title="Cancel">
                            <X size={11}/>
                          </button>
                        </div>
                      ) : (
                        <div style={{display:'flex',gap:4}}>
                          <button className="btn btn-ghost btn-xs" onClick={() => startEdit(row)}
                            title="Edit">
                            <Pencil size={11}/>
                          </button>
                          <button className="btn btn-danger btn-xs"
                            onClick={() => handleDelete(row.id, row.name)} title="Remove">
                            <Trash2 size={11}/>
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {shown.length < rows.length && (
            <div style={{textAlign:'center',padding:'8px',fontSize:'.75rem',color:'var(--text-3)'}}>
              Showing {shown.length} of {rows.length} {type}s
            </div>
          )}
        </div>
      )}

      {/* Edit hint */}
      {rows.length > 0 && !showAdd && (
        <div style={{marginTop:8,fontSize:'.72rem',color:'var(--text-3)'}}>
          <Pencil size={10}/> Click any cell to edit inline · <Check size={10}/> to save · <X size={10}/> to cancel
        </div>
      )}
    </div>
  )
}
