/**
 * CompanyDBPage.jsx
 * ─────────────────────────────────────────────────────────────────────────
 * Admin page for managing the company / organisation database.
 * Allows searching, adding, editing, approving and deleting company records
 * and their aliases — the data that drives the 'Who' column in reconciliation.
 */
import React, { useState, useEffect, useCallback } from 'react'
import { Search, Plus, Pencil, Trash2, Check, X, Tag, Building2, Globe, AlertCircle } from 'lucide-react'
import toast from 'react-hot-toast'

const API = async (method, path, body) => {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body) opts.body = JSON.stringify(body)
  const r = await fetch(`/api/company${path}`, opts)
  if (!r.ok) throw new Error(await r.text())
  return r.status === 204 ? null : r.json()
}

const CATEGORIES = [
  'Bank','Government','Superannuation','Payment Processor','Utility',
  'Telecommunications','Retail','Food & Beverage','Transport','Insurance',
  'Software','Entertainment','Professional Services','International Organisation','Other',
]

const COUNTRIES = ['AU','US','GB','NZ','CA','SG','JP','CN','DE','FR','IN','XX']

const FLAG = c => ({ AU:'🇦🇺',US:'🇺🇸',GB:'🇬🇧',NZ:'🇳🇿',CA:'🇨🇦',SG:'🇸🇬',
                     JP:'🇯🇵',CN:'🇨🇳',DE:'🇩🇪',FR:'🇫🇷',IN:'🇮🇳' }[c] || '🌐')

// ── CompanyRow ──────────────────────────────────────────────────────────────
function CompanyRow({ co, onSaved, onDeleted }) {
  const [expanded, setExpanded] = useState(false)
  const [editing,  setEditing]  = useState(false)
  const [form,     setForm]     = useState(co)
  const [newAlias, setNewAlias] = useState('')
  const [saving,   setSaving]   = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      const updated = await API('PUT', `/${co.id}`, form)
      toast.success(`${updated.name} updated`)
      setEditing(false)
      onSaved(updated)
    } catch (e) { setError(e.message); toast.error('Company DB error: ' + e.message) }
    finally { setSaving(false) }
  }

  const del = async () => {
    if (!confirm(`Delete "${co.name}"?`)) return
    try { await API('DELETE', `/${co.id}`); onDeleted(co.id); toast.success('Deleted') }
    catch (e) { toast.error(e.message) }
  }

  const approve = async () => {
    try { const u = await API('POST', `/approve/${co.id}`); onSaved(u); toast.success('Approved') }
    catch (e) { toast.error(e.message) }
  }

  const addAlias = async () => {
    if (!newAlias.trim()) return
    try {
      await API('POST', `/${co.id}/alias`, { alias: newAlias.trim(), priority: 0 })
      toast.success(`Alias "${newAlias}" added`)
      setNewAlias('')
      // Refresh by triggering parent reload
      onSaved({ ...co })
    } catch (e) { setError(e.message); toast.error('Company DB error: ' + e.message) }
  }

  const removeAlias = async (alias) => {
    try {
      await API('DELETE', `/${co.id}/alias/${encodeURIComponent(alias)}`)
      toast.success(`Alias "${alias}" removed`)
      onSaved({ ...co })
    } catch (e) { setError(e.message); toast.error('Company DB error: ' + e.message) }
  }

  const f = (k) => e => setForm(p => ({ ...p, [k]: e.target.value }))

  return (
    <div style={{
      border:'1px solid var(--border)', borderRadius:'var(--r-md)',
      marginBottom:8, background: co.approved ? 'var(--surface)' : 'var(--warning-bg)',
      overflow:'hidden',
    }}>
      {/* Header row */}
      <div style={{display:'flex',alignItems:'center',gap:10,padding:'10px 14px',cursor:'pointer'}}
        onClick={() => setExpanded(e => !e)}>
        <span style={{fontSize:'1.1rem'}}>{FLAG(co.country)}</span>
        <div style={{flex:1,minWidth:0}}>
          <div style={{fontWeight:600,fontSize:'.88rem',color:'var(--text-1)',
            display:'flex',alignItems:'center',gap:6}}>
            {co.name}
            {!co.approved && (
              <span style={{fontSize:'.68rem',background:'var(--warning)',color:'white',
                borderRadius:4,padding:'1px 5px',fontWeight:700}}>PENDING</span>
            )}
          </div>
          <div style={{fontSize:'.75rem',color:'var(--text-3)',marginTop:1}}>
            {co.category}{co.subcategory ? ` · ${co.subcategory}` : ''}{co.abn ? ` · ABN ${co.abn}` : ''}
            {co.is_government && <span style={{marginLeft:6,color:'var(--brand)',fontWeight:600}}>🏛 Gov</span>}
          </div>
        </div>
        <span style={{fontSize:'.75rem',color:'var(--text-3)',flexShrink:0}}>
          {co.aliases?.length || 0} aliases
        </span>
        <span style={{color:'var(--text-3)',fontSize:'.8rem'}}>{expanded ? '▲' : '▼'}</span>
      </div>

      {expanded && (
        <div style={{padding:'0 14px 14px',borderTop:'1px solid var(--border)'}}>
          {editing ? (
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8,marginTop:10}}>
              {[['name','Name'],['short_name','Short Name'],['category','Category'],
                ['subcategory','Subcategory'],['country','Country'],['abn','ABN']].map(([k,lbl]) => (
                <div key={k}>
                  <label style={{fontSize:'.72rem',fontWeight:600,color:'var(--text-3)',display:'block',marginBottom:3}}>{lbl}</label>
                  {k === 'category' ? (
                    <select className="input input-sm" value={form[k]||''} onChange={f(k)} style={{width:'100%'}}>
                      {CATEGORIES.map(c => <option key={c}>{c}</option>)}
                    </select>
                  ) : k === 'country' ? (
                    <select className="input input-sm" value={form[k]||''} onChange={f(k)} style={{width:'100%'}}>
                      {COUNTRIES.map(c => <option key={c}>{c}</option>)}
                    </select>
                  ) : (
                    <input className="input input-sm" value={form[k]||''} onChange={f(k)} style={{width:'100%'}}/>
                  )}
                </div>
              ))}
              <div style={{display:'flex',alignItems:'center',gap:6,marginTop:4}}>
                <input type="checkbox" checked={!!form.is_government}
                  onChange={e => setForm(p => ({...p, is_government: e.target.checked}))}/>
                <label style={{fontSize:'.82rem'}}>Government entity</label>
              </div>
              <div style={{gridColumn:'span 2',display:'flex',gap:8,marginTop:6}}>
                <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>
                  <Check size={13}/> {saving ? 'Saving…' : 'Save'}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
              </div>
            </div>
          ) : (
            <div style={{display:'flex',gap:8,marginTop:10}}>
              {!co.approved && (
                <button className="btn btn-primary btn-sm" onClick={approve}>
                  <Check size={13}/> Approve
                </button>
              )}
              <button className="btn btn-outline btn-sm" onClick={() => setEditing(true)}>
                <Pencil size={13}/> Edit
              </button>
              <button className="btn btn-danger btn-sm" onClick={del}>
                <Trash2 size={13}/> Delete
              </button>
            </div>
          )}

          {/* Aliases */}
          <div style={{marginTop:12}}>
            <div style={{fontSize:'.75rem',fontWeight:700,color:'var(--text-3)',
              textTransform:'uppercase',letterSpacing:'.05em',marginBottom:6}}>
              Aliases (used for transaction matching)
            </div>
            <div style={{display:'flex',flexWrap:'wrap',gap:4,marginBottom:8}}>
              {(co.aliases||[]).map(a => (
                <span key={a.alias} style={{
                  display:'inline-flex',alignItems:'center',gap:4,
                  background:'var(--surface-2)',border:'1px solid var(--border)',
                  borderRadius:4,padding:'2px 7px',fontSize:'.75rem',
                }}>
                  {a.alias}
                  <X size={10} style={{cursor:'pointer',color:'var(--danger)'}}
                    onClick={() => removeAlias(a.alias)}/>
                </span>
              ))}
              {(!co.aliases || co.aliases.length === 0) && (
                <span style={{fontSize:'.75rem',color:'var(--text-3)'}}>No aliases</span>
              )}
            </div>
            <div style={{display:'flex',gap:6}}>
              <input className="input input-sm" style={{flex:1}} placeholder="Add alias keyword…"
                value={newAlias} onChange={e => setNewAlias(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addAlias()}/>
              <button className="btn btn-outline btn-sm" onClick={addAlias}><Plus size={13}/> Add</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── AddCompanyForm ──────────────────────────────────────────────────────────
function AddCompanyForm({ onAdded, onClose }) {
  const [form, setForm] = useState({
    name:'', short_name:'', category:'Other', subcategory:'',
    country:'AU', abn:'', is_government: false, aliases:'',
  })
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!form.name.trim()) { toast.error('Name is required'); return }
    setSaving(true)
    try {
      const aliases = form.aliases.split(',').map(a => a.trim()).filter(Boolean)
      const co = await API('POST', '', { ...form, aliases })
      toast.success(`${co.name} added`)
      onAdded(co)
      onClose()
    } catch (e) { setError(e.message); toast.error('Company DB error: ' + e.message) }
    finally { setSaving(false) }
  }

  const f = k => e => setForm(p => ({ ...p, [k]: e.target.value }))

  return (
    <div style={{
      position:'fixed',inset:0,background:'rgba(0,0,0,.4)',zIndex:9999,
      display:'flex',alignItems:'center',justifyContent:'center',
    }} onClick={onClose}>
      <div style={{
        background:'var(--surface)',borderRadius:'var(--r-lg)',padding:24,
        width:520,maxWidth:'95vw',boxShadow:'var(--sh-lg)',
      }} onClick={e => e.stopPropagation()}>
        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:16}}>
          <Building2 size={18} color="var(--brand)"/>
          <h3 style={{margin:0,fontSize:'1rem'}}>Add Company / Organisation</h3>
          <button className="btn btn-ghost btn-icon btn-sm" style={{marginLeft:'auto'}} onClick={onClose}>
            <X size={16}/>
          </button>
        </div>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
          {[['name','Name *'],['short_name','Short Name / Trading Name']].map(([k,lbl]) => (
            <div key={k} style={{gridColumn: k==='name' ? 'span 2' : 'auto'}}>
              <label style={{fontSize:'.75rem',fontWeight:600,display:'block',marginBottom:3}}>{lbl}</label>
              <input className="input input-sm" value={form[k]||''} onChange={f(k)} style={{width:'100%'}}/>
            </div>
          ))}
          <div>
            <label style={{fontSize:'.75rem',fontWeight:600,display:'block',marginBottom:3}}>Category</label>
            <select className="input input-sm" value={form.category} onChange={f('category')} style={{width:'100%'}}>
              {CATEGORIES.map(c => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label style={{fontSize:'.75rem',fontWeight:600,display:'block',marginBottom:3}}>Sub-category</label>
            <input className="input input-sm" value={form.subcategory||''} onChange={f('subcategory')} style={{width:'100%'}}/>
          </div>
          <div>
            <label style={{fontSize:'.75rem',fontWeight:600,display:'block',marginBottom:3}}>Country</label>
            <select className="input input-sm" value={form.country} onChange={f('country')} style={{width:'100%'}}>
              {COUNTRIES.map(c => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label style={{fontSize:'.75rem',fontWeight:600,display:'block',marginBottom:3}}>ABN / ACN</label>
            <input className="input input-sm" value={form.abn||''} onChange={f('abn')} style={{width:'100%'}} placeholder="Optional"/>
          </div>
          <div style={{gridColumn:'span 2'}}>
            <label style={{fontSize:'.75rem',fontWeight:600,display:'block',marginBottom:3}}>
              Aliases <span style={{fontWeight:400,color:'var(--text-3)'}}>(comma-separated keywords for transaction matching)</span>
            </label>
            <input className="input input-sm" value={form.aliases||''} onChange={f('aliases')} style={{width:'100%'}}
              placeholder="e.g. cba, commbank, commonwealth bank"/>
          </div>
          <div style={{display:'flex',alignItems:'center',gap:6}}>
            <input type="checkbox" checked={!!form.is_government}
              onChange={e => setForm(p => ({...p, is_government: e.target.checked}))}/>
            <label style={{fontSize:'.82rem'}}>Government / public entity</label>
          </div>
        </div>
        <div style={{display:'flex',gap:8,marginTop:16}}>
          <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>
            <Check size={13}/> {saving ? 'Adding…' : 'Add Company'}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────────
export default function CompanyDBPage() {
  const [companies,  setCompanies]  = useState([])
  const [search,     setSearch]     = useState('')
  const [catFilter,  setCatFilter]  = useState('')
  const [pending,    setPending]    = useState(false)
  const [loading,    setLoading]    = useState(false)
  const [showAdd,    setShowAdd]    = useState(false)
  const [categories, setCategories] = useState([])
  const [error,      setError]      = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      if (search.trim().length >= 2) {
        const r = await API('GET', `/search?q=${encodeURIComponent(search)}&limit=50`)
        setCompanies(r)
      } else {
        const params = new URLSearchParams({ limit: 500, skip: 0 })
        if (pending) params.set('approved', 'false')
        if (catFilter) params.set('category', catFilter)
        const r = await API('GET', `/list?${params}`)
        setCompanies(r)
      }
    } catch (e) { setError(e.message); toast.error('Company DB error: ' + e.message) }
    finally { setLoading(false) }
  }, [search, pending, catFilter])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    API('GET', '/categories').then(setCategories).catch(() => {})
  }, [])

  const onSaved = updated => {
    setCompanies(prev => prev.map(c => c.id === updated.id ? { ...c, ...updated } : c))
    // Force full reload to get fresh aliases
    setTimeout(load, 300)
  }
  const onDeleted = id => setCompanies(prev => prev.filter(c => c.id !== id))
  const onAdded   = co => { setCompanies(prev => [co, ...prev]); load() }

  const pendingCount = companies.filter(c => !c.approved).length

  return (
    <div style={{maxWidth:900, margin:'0 auto', padding:'24px 16px'}}>
      {/* Header */}
      <div style={{display:'flex',alignItems:'center',gap:12,marginBottom:20}}>
        <Globe size={22} color="var(--brand)"/>
        <div>
          <h2 style={{margin:0,fontSize:'1.15rem'}}>Company Database</h2>
          <p style={{margin:0,fontSize:'.78rem',color:'var(--text-3)'}}>
            {companies.length} entries · Drives the "Who" column in reconciliation
          </p>
        </div>
        <button className="btn btn-primary btn-sm" style={{marginLeft:'auto'}}
          onClick={() => setShowAdd(true)}>
          <Plus size={13}/> Add Company
        </button>
      </div>

      {/* Filters */}
      <div style={{display:'flex',gap:8,marginBottom:12,flexWrap:'wrap'}}>
        <div style={{position:'relative',flex:1,minWidth:220}}>
          <Search size={14} style={{position:'absolute',left:10,top:'50%',transform:'translateY(-50%)',color:'var(--text-3)'}}/>
          <input className="input input-sm" style={{paddingLeft:32,width:'100%'}}
            placeholder="Search name or alias…"
            value={search} onChange={e => setSearch(e.target.value)}/>
        </div>
        <select className="input input-sm" value={catFilter}
          onChange={e => setCatFilter(e.target.value)} style={{minWidth:160}}>
          <option value="">All categories</option>
          {categories.map(c => <option key={c}>{c}</option>)}
        </select>
        <label style={{display:'flex',alignItems:'center',gap:6,fontSize:'.82rem',
          cursor:'pointer',padding:'0 8px',border:'1px solid var(--border)',
          borderRadius:6,background: pending?'var(--warning-bg)':'var(--surface)'}}>
          <input type="checkbox" checked={pending} onChange={e => setPending(e.target.checked)}/>
          Pending only
          {pendingCount > 0 && (
            <span style={{background:'var(--warning)',color:'white',borderRadius:4,
              padding:'0 5px',fontSize:'.7rem',fontWeight:700}}>{pendingCount}</span>
          )}
        </label>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{background:'var(--danger-bg,#fef2f2)',border:'1px solid var(--danger,#ef4444)',
          borderRadius:8,padding:'10px 14px',marginBottom:12,fontSize:'.82rem',color:'var(--danger,#ef4444)',
          display:'flex',gap:8,alignItems:'center'}}>
          <AlertCircle size={14}/>
          <span><strong>API Error:</strong> {error}</span>
        </div>
      )}
      {/* Info banner */}
      <div style={{display:'flex',gap:8,alignItems:'flex-start',
        background:'var(--info-bg,#eff6ff)',border:'1px solid var(--info,#3b82f6)',
        borderRadius:8,padding:'8px 12px',marginBottom:12,fontSize:'.78rem',color:'var(--text-2)'}}>
        <AlertCircle size={14} style={{flexShrink:0,marginTop:1,color:'var(--info)'}}/>
        <span>
          Aliases are matched against transaction descriptions to populate the <strong>Who</strong> column.
          Transfers to/from your <strong>registered company</strong> are automatically marked as 🟢 Internal.
          New entities captured from bank feeds appear here as <em>Pending</em> — review and approve them.
        </span>
      </div>

      {loading && <div style={{textAlign:'center',padding:32,color:'var(--text-3)'}}>Loading…</div>}

      {/* Company list */}
      {!loading && companies.map(co => (
        <CompanyRow key={co.id} co={co} onSaved={onSaved} onDeleted={onDeleted}/>
      ))}

      {!loading && companies.length === 0 && (
        <div style={{textAlign:'center',padding:40,color:'var(--text-3)'}}>
          No companies found{search ? ` for "${search}"` : ''}
        </div>
      )}

      {showAdd && <AddCompanyForm onAdded={onAdded} onClose={() => setShowAdd(false)}/>}
    </div>
  )
}
