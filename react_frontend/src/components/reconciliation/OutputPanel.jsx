import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { saveSession, classifyGL, reclassifyGL, exportExcel, captureWho, getDbStats, clearUserDb, getAccountBalances, upsertAccountBalance, rdrCreate } from '../../lib/api.js'
import {
  Download, Trash2, Pencil, X, Check, ChevronLeft, ChevronRight,
  BookOpen, Database, Plus, ChevronDown, ChevronUp,
  TrendingUp, TrendingDown, RefreshCw, DollarSign,
  ArrowUpDown, ArrowUp, ArrowDown, Upload, Save,
} from 'lucide-react'
import toast from 'react-hot-toast'

const GST_CATS = ['GST on Expenses','GST on Income','GST on Capital','GST Free Expenses','GST Free Income','BAS Excluded','']
const PAGE_SZ  = 25

// Normalize backend classification values (e.g. "-Internal") to emoji-prefixed
// frontend values (e.g. "🟢Internal") used throughout the UI.
function normalizeClassification(val) {
  if (!val) return '⚪Unclassified'
  const v = String(val).trim()
  if (v.startsWith('🟢') || v.startsWith('🔵') || v.startsWith('🟡') || v.startsWith('⚪')) return v
  if (v.includes('Internal'))     return '🟢Internal'
  if (v.includes('Incoming'))     return '🔵Incoming'
  if (v.includes('Outgoing'))     return '🟡Outgoing'
  if (v.includes('Unclassified')) return '⚪Unclassified'
  return '⚪Unclassified'
}
function normalizeTransactions(txns) {
  if (!Array.isArray(txns)) return txns
  return txns.map(t => ({...t, classification: normalizeClassification(t.classification)}))
}

const fmtN   = n => (n == null || n === 0) ? '' : Number(n).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2})
const fmtAUD = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:2}).format(n||0)

function ClassBadge({ val }) {
  if (!val) return null
  const cls = val.includes('Internal') ? 'badge-cls-int'
    : val.includes('Incoming') ? 'badge-cls-in'
    : val.includes('Outgoing') ? 'badge-cls-out'
    : 'badge-neutral'
  return <span className={`badge ${cls}`}>{val}</span>
}

const BLANK = {date:'',bank:'',account:'',description:'',debit:0,credit:0,
  pairid:'',gl_account:'',gl_type:'',gst:0,gst_category:'Unknown',who:''}

function StatStrip({ stats }) {
  return (
    <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:16}}>
      {[
        {label:'Total Incoming',  val:fmtAUD(stats.totalIn),  icon:TrendingUp,  color:'var(--info)',    bg:'var(--info-bg)'},
        {label:'Total Outgoing',  val:fmtAUD(stats.totalOut), icon:TrendingDown, color:'var(--warning)', bg:'var(--warning-bg)'},
        {label:'Internal Pairs',  val:stats.intCount,          icon:RefreshCw,   color:'var(--success)', bg:'var(--success-bg)'},
        {label:'Total GST',       val:fmtAUD(stats.totalGST), icon:DollarSign,  color:'var(--brand)',   bg:'var(--brand-light)'},
      ].map(({label,val,icon:Icon,color,bg})=>(
        <div key={label} style={{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:'var(--r-lg)',padding:'14px 16px',display:'flex',alignItems:'center',gap:12,boxShadow:'var(--sh-xs)'}}>
          <div style={{width:36,height:36,borderRadius:'var(--r-md)',background:bg,display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0}}>
            <Icon size={17} color={color}/>
          </div>
          <div style={{minWidth:0}}>
            <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-3)',textTransform:'uppercase',letterSpacing:'.05em',marginBottom:2}}>{label}</div>
            <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.95rem',color:'var(--text-1)',whiteSpace:'nowrap'}}>{val}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Column filter popover ─────────────────────────────────────────────────────
// Rendered via React portal into document.body so it is never clipped by
// overflow:auto/hidden on ancestor table containers, and always appears
// directly below the column header that triggered it.
function ColFilter({ col, values, active, onChange, onClose, anchorPos }) {
  const unique   = useMemo(() => [...new Set(values.map(v => String(v||'')))].sort(), [values])
  const [selected, setSelected] = useState(() =>
    active.size > 0 ? new Set(active) : new Set(unique)
  )
  const [search, setSearch] = useState('')   // search box state
  const searchRef = useRef(null)
  const popRef    = useRef(null)

  const hasSelection = selected.size > 0 && selected.size < unique.length

  // Filter unique values by search term
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? unique.filter(v => v.toLowerCase().includes(q)) : unique
  }, [unique, search])

  const toggle = v => setSelected(s => {
    const n = new Set(s); n.has(v) ? n.delete(v) : n.add(v); return n
  })

  // Select / deselect only the currently visible (search-filtered) options
  const selectVisible   = () => setSelected(s => { const n = new Set(s); visible.forEach(v => n.add(v));    return n })
  const deselectVisible = () => setSelected(s => { const n = new Set(s); visible.forEach(v => n.delete(v)); return n })
  const allVisibleSel   = visible.length > 0 && visible.every(v => selected.has(v))

  const apply = () => {
    onChange(selected.size === unique.length ? new Set() : new Set(selected))
  }

  // Auto-focus search box when popover opens
  useEffect(() => { searchRef.current?.focus() }, [])

  // Close on outside click
  useEffect(() => {
    const handler = e => {
      if (popRef.current && !popRef.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', handler, true)
    return () => document.removeEventListener('mousedown', handler, true)
  }, [onClose])

  const popW = 240
  const top  = anchorPos.top
  const left = anchorPos.left

  const popover = (
    <div
      ref={popRef}
      onClick={e => e.stopPropagation()}
      style={{
        position:'fixed',
        top,
        left: Math.min(left, window.innerWidth - popW - 4),
        zIndex:999999,
        width: popW,
        maxHeight: anchorPos.maxH,
        background:'var(--surface)',
        border:'1px solid var(--border)',
        borderRadius:'0 0 var(--r-md) var(--r-md)',
        boxShadow:'0 6px 20px rgba(0,0,0,.15)',
        padding:'8px',
        display:'flex',
        flexDirection:'column',
        gap:5,
        overflow:'hidden',
      }}
    >
      {/* Search box */}
      <div style={{position:'relative'}}>
        <svg style={{position:'absolute',left:7,top:'50%',transform:'translateY(-50%)',
          pointerEvents:'none',opacity:.45}}
          width="12" height="12" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
        </svg>
        <input
          ref={searchRef}
          type="text"
          placeholder="Search…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => { if (e.key === 'Escape') { if (search) setSearch(''); else onClose() } }}
          style={{
            width:'100%', boxSizing:'border-box',
            padding:'4px 8px 4px 24px',
            fontSize:'.78rem', border:'1px solid var(--border)',
            borderRadius:'var(--r-sm,4px)', background:'var(--surface-2)',
            color:'var(--text-1)', outline:'none',
            fontFamily:'inherit',
          }}
          onFocus={e => e.target.style.borderColor='var(--brand)'}
          onBlur={e  => e.target.style.borderColor='var(--border)'}
        />
        {search && (
          <button onClick={() => setSearch('')}
            style={{position:'absolute',right:5,top:'50%',transform:'translateY(-50%)',
              background:'none',border:'none',cursor:'pointer',padding:2,
              color:'var(--text-3)',lineHeight:1,fontSize:12}}>✕</button>
        )}
      </div>

      {/* All / None — operate on visible (search-filtered) items */}
      <div style={{display:'flex',gap:4,alignItems:'center'}}>
        <button className="btn btn-ghost btn-xs"
          style={{fontWeight: allVisibleSel?700:400,
            color: allVisibleSel?'var(--brand)':undefined}}
          onClick={selectVisible}>
          {search ? 'Select shown' : 'All'}
        </button>
        <button className="btn btn-ghost btn-xs"
          onClick={deselectVisible}>
          {search ? 'Deselect shown' : 'None'}
        </button>
        {hasSelection && (
          <span style={{fontSize:'.7rem',color:'var(--warning)',marginLeft:'auto',whiteSpace:'nowrap'}}>
            {selected.size}/{unique.length}
          </span>
        )}
      </div>

      <div style={{borderTop:'1px solid var(--border)',margin:'0 -8px'}}/>

      {/* Option list — only shows items matching search */}
      <div style={{overflowY:'auto',flex:1,display:'flex',flexDirection:'column',gap:1,
        maxHeight: Math.min(260, anchorPos.maxH - 130)}}>
        {visible.length === 0 && (
          <div style={{padding:'8px 6px',fontSize:'.75rem',color:'var(--text-3)',textAlign:'center'}}>
            No matches for "{search}"
          </div>
        )}
        {(()=>{
          // Selected items first, then unselected — both filtered by search
          const sel   = visible.filter(v =>  selected.has(v))
          const unsel = visible.filter(v => !selected.has(v))
          const row = v => (
            <label key={v} style={{display:'flex',alignItems:'center',gap:6,cursor:'pointer',
              fontSize:'.78rem',padding:'3px 6px',borderRadius:4,
              background:selected.has(v)?'var(--brand-xlight)':'transparent',
              transition:'background .1s'}}>
              <input type="checkbox" checked={selected.has(v)} onChange={()=>toggle(v)}
                style={{accentColor:'var(--brand)',flexShrink:0}}/>
              <span style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',flex:1}}
                title={v}>
                {v||('(blank)')}
              </span>
            </label>
          )
          return <>
            {sel.map(row)}
            {sel.length>0 && unsel.length>0 && (
              <div key="__div" style={{borderTop:'1px dashed var(--border)',
                margin:'2px 0',fontSize:'.68rem',color:'var(--text-3)',
                paddingLeft:4,paddingTop:2}}>— unselected —</div>
            )}
            {unsel.map(row)}
          </>
        })()}
      </div>

      <div style={{borderTop:'1px solid var(--border)',margin:'0 -8px',marginTop:2}}/>

      {/* Footer: result count + Apply */}
      <div style={{display:'flex',alignItems:'center',gap:6,paddingTop:2}}>
        <span style={{fontSize:'.7rem',color:'var(--text-3)',flex:1}}>
          {search
            ? `${visible.length} of ${unique.length} shown`
            : `${unique.length} value${unique.length!==1?'s':''}`}
        </span>
        <button className="btn btn-primary btn-xs" onClick={apply}>
          Apply{hasSelection ? ` (${selected.size})` : ' (all)'}
        </button>
      </div>
    </div>
  )

  return createPortal(popover, document.body)
}

// ── Sort/Filter header cell ───────────────────────────────────────────────────
// onOpenFilter(field, anchorPos) is called on ▾ click — ColFilter is rendered
// at the OutputPanel level (outside all scroll containers) to avoid z-index and
// getBoundingClientRect issues with sticky/overflow ancestors.
function SortTh({ label, field, sort, setSort, colFilters, onOpenFilter, values, style, onResize, colWidth }) {
  const thRef     = React.useRef(null)
  const isAsc     = sort.field===field && sort.dir==='asc'
  const isDesc    = sort.field===field && sort.dir==='desc'
  const hasFilter = colFilters[field] && colFilters[field].size > 0

  // ── Resize handle drag logic ──────────────────────────────────────────────
  const startResize = e => {
    e.preventDefault(); e.stopPropagation()
    const startX = e.clientX
    const startW = thRef.current ? thRef.current.getBoundingClientRect().width : (colWidth || 100)
    const onMove = mv => { if (onResize) onResize(Math.max(40, startW + mv.clientX - startX)) }
    const onUp   = ()  => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
  }

  const handleFilterClick = e => {
    e.stopPropagation()
    if (!thRef.current) return
    const r = thRef.current.getBoundingClientRect()
    const vh = window.innerHeight
    // Layout has overflow:hidden + overflowY:auto ancestors which break position:fixed.
    // We render the portal as position:absolute into document.body,
    // so coordinates must be document-relative (viewport + scroll offset).
    const scrollY = window.pageYOffset || document.documentElement.scrollTop  || 0
    const scrollX = window.pageXOffset || document.documentElement.scrollLeft || 0
    onOpenFilter(field, {
      top:  r.bottom + scrollY,
      left: r.left   + scrollX,
      maxH: Math.max(160, vh - r.bottom - 8),
    })
  }

  const thStyle = {
    position:'relative', userSelect:'none', whiteSpace:'nowrap',
    ...(colWidth ? {width:colWidth, minWidth:colWidth} : {}),
    ...style,
  }
  return (
    <th ref={thRef} style={thStyle}>
      <div style={{display:'inline-flex',alignItems:'center',gap:4,width:'100%'}}>
        <span style={{fontSize:'.82rem',fontWeight:600,cursor:'pointer'}}
          onClick={()=>setSort(s=>s.field===field ? {field,dir:s.dir==='asc'?'desc':'asc'} : {field,dir:'asc'})}>
          {label}
        </span>
        <span style={{display:'inline-flex',alignItems:'center',gap:0,cursor:'pointer'}}
          onClick={()=>setSort(s=>s.field===field ? {field,dir:s.dir==='asc'?'desc':'asc'} : {field,dir:'asc'})}>
          {isAsc  ? <ArrowUp size={15} color="var(--brand)"/>
          :isDesc ? <ArrowDown size={15} color="var(--brand)"/>
          :         <ArrowUpDown size={15} color="var(--text-3)" opacity={0.5}/>}
        </span>
        <span onClick={handleFilterClick}
          style={{cursor:'pointer',fontSize:'20px',lineHeight:1,padding:'0 2px',
            color:hasFilter?'var(--warning)':'var(--text-3)',
            fontWeight:hasFilter?700:400}}>▾</span>
      </div>
      {/* Resize handle — visible bar matching sort arrow, brand on hover */}
      <div
        onMouseDown={startResize}
        style={{
          position:'absolute', right:0, top:'20%', bottom:'20%', width:4,
          cursor:'col-resize', userSelect:'none',
          borderRight:'2px solid var(--text-3)',
          opacity:0.5,
          transition:'opacity .15s, border-color .15s',
        }}
        onMouseEnter={e=>{e.currentTarget.style.opacity='1';e.currentTarget.style.borderRightColor='var(--brand)'}}
        onMouseLeave={e=>{e.currentTarget.style.opacity='0.5';e.currentTarget.style.borderRightColor='var(--text-3)'}}
      />
    </th>
  )
}

// ── Chart of Accounts Modal ───────────────────────────────────────────────────
function ChartOfAccountsModal({ onClose, glAccounts, setGlAccounts, onSaveAndReclassify, onCoaMapUpdate }) {
  const [rows,    setRows]    = useState([])
  const [loading, setLoading] = useState(true)

  React.useEffect(()=>{
    fetch('/api/gl/accounts/all').then(r=>r.json()).then(d=>{
      // API returns plain array of rows
      const arr = Array.isArray(d) ? d : (d.rows || [])
      if (arr.length) {
        setRows(arr.map((row,i)=>({
          id:          i,
          Code:        row.Code        || '',
          Name:        row.Name        || '',
          Type:        row.Type        || '',
          TaxCode:     row.TaxCode     || row['Tax Code'] || '',
          Description: row.Description || '',
          Dashboard:   row.Dashboard   || '',
        })))
      } else {
        setRows(glAccounts.map((name,i)=>({id:i,Code:'',Name:name,Type:'',TaxCode:'',Description:'',Dashboard:''})))
      }
    }).catch(()=>{
      setRows(glAccounts.map((name,i)=>({id:i,Code:'',Name:name,Type:'',TaxCode:'',Description:'',Dashboard:''})))
    }).finally(()=>setLoading(false))
  }, [])
  const [editIdx, setEditIdx] = useState(null)
  const [editRow, setEditRow] = useState(null)
  const [newRow,  setNewRow]  = useState({Code:'',Name:'',Type:'',TaxCode:'',Description:''})
  const [showAdd, setShowAdd] = useState(false)
  const [saving,  setSaving]  = useState(false)
  const fileRef = useRef()

  const COLS = ['Code','Name','Type','TaxCode','Description','Dashboard']

  const parseCSV = (text) => {
    // Proper CSV parser — handles quoted fields with commas inside
    const rows = []
    const lines = text.replace(/\r/g,'').split('\n')
    for (const line of lines) {
      if (!line.trim()) continue
      const cols = []; let cur = ''; let inQ = false
      for (let i = 0; i < line.length; i++) {
        const ch = line[i]
        if (ch === '"') {
          if (inQ && line[i+1] === '"') { cur += '"'; i++ }  // escaped quote
          else inQ = !inQ
        } else if (ch === ',' && !inQ) { cols.push(cur); cur = '' }
        else cur += ch
      }
      cols.push(cur)
      rows.push(cols.map(v=>v.trim()))
    }
    return rows
  }

  const handleUpload = async (e) => {
    const file = e.target.files[0]; if (!file) return
    const text = await file.text()
    const allRows = parseCSV(text)
    if (allRows.length < 2) { toast.error('CSV appears empty'); return }
    const header = allRows[0].map(h=>h.replace(/^\*/,'').trim())
    const parsed = allRows.slice(1).map((vals,i)=>{
      const obj = {}; header.forEach((h,j)=>{ obj[h]=vals[j]||'' })
      const name = obj.Name || obj['*Name'] || ''
      if (!name) return null
      return { id:i,
        Code:        obj.Code        || obj['*Code']        || '',
        Name:        name,
        Type:        obj.Type        || obj['*Type']        || '',
        TaxCode:     obj['Tax Code'] || obj['*Tax Code']    || obj.TaxCode || '',
        Description: obj.Description || '',
        Dashboard:   obj.Dashboard   || '',
      }
    }).filter(Boolean)
    setRows(parsed)
    toast.success(`Loaded ${parsed.length} accounts from CSV`)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      // Build CSV with all columns — quote all text fields to handle commas
      const q = v => `"${(v||'').replace(/"/g,'""')}"`
      const csvContent = ['*Code,*Name,*Type,*Tax Code,Description,Dashboard',
        ...rows.map(r=>[q(r.Code),q(r.Name),q(r.Type),q(r.TaxCode),q(r.Description),q(r.Dashboard||'')].join(','))
      ].join('\n')
      const blob = new Blob([csvContent], {type:'text/csv'})
      const fd = new FormData()
      fd.append('file', blob, 'ChartOfAccounts.csv')

      // Upload and wait for server to confirm rebuild
      const resp = await fetch('/api/gl/accounts/upload', {method:'POST', body:fd})
      if (!resp.ok) throw new Error(await resp.text())
      const result = await resp.json()

      // Refresh GL accounts dropdown and coaMap from server
      const allResp = await fetch('/api/gl/accounts/all')
      const allRows = await allResp.json()
      const arr = Array.isArray(allRows) ? allRows : (allRows.rows||[])
      const names = arr.map(r=>r.Name||r.name).filter(Boolean)
      setGlAccounts(names)

      // Rebuild coaMap so auto-fill picks up new accounts immediately
      if (typeof onCoaMapUpdate === 'function') {
        const map = {}
        arr.forEach(r=>{
          const name = r.Name||r.name
          if(name) map[name]={type:r.Type||r.type||'', tax_code:r.TaxCode||r.tax_code||''}
        })
        onCoaMapUpdate(map)
      }

      toast.success(`${result.message || `Saved ${names.length} accounts`} — re-classifying…`)
      onClose()
      if (onSaveAndReclassify) onSaveAndReclassify()
      // Mark COA as changed so Reclassify button activates
    } catch(err) {
      toast.error(`Save failed: ${err.message}`)
    } finally { setSaving(false) }
  }

  const startEdit = (row,i) => { setEditIdx(i); setEditRow({...row}) }
  const saveEdit  = () => {
    setRows(r=>r.map((x,i)=>i===editIdx?editRow:x))
    setEditIdx(null); setEditRow(null)
  }
  const deleteRow = (i) => setRows(r=>r.filter((_,j)=>j!==i))
  const addNewRow = () => {
    setRows(r=>[...r,{...newRow,id:Date.now()}])
    setNewRow({Code:'',Name:'',Type:'',TaxCode:'',Description:''})
    setShowAdd(false)
  }

  return (
    <div className="modal-overlay" onClick={onClose} style={{alignItems:'flex-start',paddingTop:'5vh'}}>
      <div className="modal" style={{maxWidth:860,width:'95vw',maxHeight:'85vh',display:'flex',flexDirection:'column',marginTop:'5vh',alignSelf:'flex-start'}}
        onClick={e=>e.stopPropagation()}>
        <div className="modal-header" style={{flexShrink:0}}>
          <BookOpen size={18} color="var(--brand)"/>
          <h3>Chart of Accounts (COA)</h3>
          <div style={{marginLeft:'auto',display:'flex',gap:8}}>
            <input ref={fileRef} type="file" accept=".csv" style={{display:'none'}} onChange={handleUpload}/>
            <button className="btn btn-outline btn-sm" onClick={()=>fileRef.current.click()}>
              <Upload size={13}/> Upload CSV
            </button>
            <button className="btn btn-outline btn-sm" onClick={()=>setShowAdd(s=>!s)}>
              <Plus size={13}/> Add Account
            </button>
            <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
              <Save size={13}/> {saving?'Saving…':'Save & Apply'}
            </button>
            <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}><X size={16}/></button>
          </div>
        </div>

        {showAdd && (
          <div style={{padding:'10px 16px',background:'var(--surface-2)',borderBottom:'1px solid var(--border)',display:'flex',gap:8,flexWrap:'wrap',alignItems:'flex-end',flexShrink:0}}>
            {COLS.map(k=>(
              <div key={k} className="input-group" style={{minWidth:80}}>
                <label>{k}</label>
                <input className="input input-sm" value={newRow[k]||''} onChange={e=>setNewRow(r=>({...r,[k]:e.target.value}))}/>
              </div>
            ))}
            <button className="btn btn-primary btn-sm" onClick={addNewRow}><Check size={13}/> Add</button>
            <button className="btn btn-ghost btn-sm" onClick={()=>setShowAdd(false)}>Cancel</button>
          </div>
        )}

        <p style={{padding:'8px 16px',fontSize:'.75rem',color:'var(--text-3)',flexShrink:0}}>
          {rows.length} accounts · Edit inline, upload a new CSV to replace, or add/delete rows. Click Save & Apply to update GL Account dropdown.
        </p>

        {loading && <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>Loading accounts…</div>}
        <div style={{overflowY:'auto',flex:1}}>
          <table className="data-table" style={{fontSize:'.78rem',display:loading?'none':'table'}}>
            <thead>
              <tr>
                {[['Code','Code'],['Name','Account Name'],['Type','Type'],['TaxCode','Tax Code'],['Description','Description'],['Dashboard','Dashboard']].map(([k,lbl])=>(
                  <th key={k} style={{whiteSpace:'nowrap'}}>{lbl}</th>
                ))}
                <th style={{width:70}}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row,i)=>(
                <tr key={row.id??i}>
                  {COLS.map(k=>(
                    <td key={k}>
                      {editIdx===i
                        ? <input className="input input-sm" style={{width:'100%',minWidth:60}}
                            value={editRow[k]||''} onChange={e=>setEditRow(r=>({...r,[k]:e.target.value}))}/>
                        : <span title={row[k]}>{row[k]}</span>
                      }
                    </td>
                  ))}
                  <td>
                    {editIdx===i
                      ? <div style={{display:'flex',gap:4}}>
                          <button className="btn btn-primary btn-xs" onClick={saveEdit}><Check size={11}/></button>
                          <button className="btn btn-ghost btn-xs" onClick={()=>setEditIdx(null)}><X size={11}/></button>
                        </div>
                      : <div style={{display:'flex',gap:4}}>
                          <button className="btn btn-outline btn-xs" onClick={()=>startEdit(row,i)}><Pencil size={11}/></button>
                          <button className="btn btn-danger btn-xs" onClick={()=>deleteRow(i)}><Trash2 size={11}/></button>
                        </div>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ── Main OutputPanel ──────────────────────────────────────────────────────────
// ── Save as RDR Rule modal ─────────────────────────────────────────────────
function SaveAsRuleModal({ row, onClose, onSaved }) {
  const [name,     setName]     = useState(row.who || '')
  const [keywords, setKeywords] = useState(
    [row.who?.toLowerCase(),
     ...(row.desc||'').toLowerCase().split(/\s+/)
       .filter(w=>w.length>4&&!/\d/.test(w)&&!['from','with','card','date','value'].includes(w))
       .slice(0,4)
    ].filter(Boolean).join(', ')
  )
  const [priority, setPriority] = useState(950)
  const [saving,   setSaving]   = useState(false)

  const save = async () => {
    const kws = keywords.split(',').map(k=>k.trim().toLowerCase()).filter(Boolean)
    if (!kws.length) { toast.error('Add at least one keyword'); return }
    const cond = { contains_any: kws }
    if (row.direction === 'debit_only')  cond.debit_only  = true
    if (row.direction === 'credit_only') cond.credit_only = true
    setSaving(true)
    try {
      await rdrCreate({ id:`rule_${Date.now()}`, name:name||kws[0],
        priority:parseInt(priority)||100, if:cond,
        then:row.gl, then_gst_category:row.gst })
      onSaved()
    } catch { toast.error('Failed to save rule') }
    finally { setSaving(false) }
  }

  return (
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,.45)',zIndex:9999,
      display:'flex',alignItems:'center',justifyContent:'center'}} onClick={onClose}>
      <div style={{background:'var(--surface)',borderRadius:'var(--r-lg)',padding:24,
        width:500,maxWidth:'95vw',boxShadow:'var(--sh-lg)'}} onClick={e=>e.stopPropagation()}>
        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:16}}>
          <span>📋</span>
          <h3 style={{margin:0,fontSize:'1rem'}}>Save as RDR Rule</h3>
          <button className="btn btn-ghost btn-icon btn-sm" style={{marginLeft:'auto'}} onClick={onClose}>✕</button>
        </div>
        <div style={{background:'var(--surface-2)',borderRadius:'var(--r-md)',padding:'10px 14px',
          marginBottom:14,fontSize:'.82rem'}}>
          GL: <strong>{row.gl}</strong> · GST: {row.gst||'—'} ·{' '}
          {row.direction==='debit_only'?'🟡 Outgoing only':row.direction==='credit_only'?'🔵 Incoming only':'↔ Any direction'}
        </div>
        <div style={{display:'flex',flexDirection:'column',gap:10,marginBottom:16}}>
          <div className="input-group">
            <label>Rule Name</label>
            <input className="input input-sm" value={name} onChange={e=>setName(e.target.value)}/>
          </div>
          <div className="input-group">
            <label>Keywords (comma-separated) — match if description contains any</label>
            <input className="input input-sm" value={keywords} onChange={e=>setKeywords(e.target.value)}/>
            <div style={{fontSize:'.72rem',color:'var(--text-3)',marginTop:3}}>Broaden keywords to catch similar transactions</div>
          </div>
          <div className="input-group" style={{maxWidth:140}}>
            <label>Priority</label>
            <input className="input input-sm" type="number" value={priority} onChange={e=>setPriority(e.target.value)}/>
          </div>
        </div>
        <div style={{display:'flex',gap:8}}>
          <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>
            {saving?'Saving…':'✅ Save Rule'}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

// ── Rule Reclassification Preview Modal ──────────────────────────────────────
function RulePreviewModal({ preview, onAccept, onReject, onClose }) {
  const [pending, setPending] = useState(preview.matches.map(m=>m.ai))

  const accept = (ai) => {
    onAccept(ai, preview.matches.find(m=>m.ai===ai))
    setPending(p=>p.filter(x=>x!==ai))
  }
  const reject = (ai) => {
    setPending(p=>p.filter(x=>x!==ai))
    onReject(ai)
  }

  const visibleMatches = preview.matches.filter(m=>pending.includes(m.ai))

  return (
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,.5)',zIndex:9999,
      display:'flex',alignItems:'center',justifyContent:'center',padding:16}}>
      <div style={{background:'var(--surface)',borderRadius:'var(--r-lg)',
        width:700,maxWidth:'96vw',maxHeight:'85vh',display:'flex',flexDirection:'column',
        boxShadow:'var(--sh-lg)'}}>

        {/* Header */}
        <div style={{display:'flex',alignItems:'center',gap:10,padding:'14px 18px',
          borderBottom:'1px solid var(--border)',flexShrink:0}}>
          <span style={{fontSize:'1.1rem'}}>📋</span>
          <div>
            <div style={{fontWeight:700,fontSize:'.95rem'}}>
              Rule: {preview.rule.name}
            </div>
            <div style={{fontSize:'.75rem',color:'var(--text-3)',marginTop:1}}>
              GL: <strong>{preview.rule.then}</strong> · {preview.matches.length} similar transaction{preview.matches.length!==1?'s':''} found
            </div>
          </div>
          <button onClick={onClose} className="btn btn-ghost btn-icon btn-sm"
            style={{marginLeft:'auto',fontSize:'1.1rem',lineHeight:1}}>✕</button>
        </div>

        {/* Body */}
        <div style={{overflowY:'auto',flex:1}}>
          {visibleMatches.length === 0 ? (
            <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>
              All transactions reviewed.
              <div style={{marginTop:12}}>
                <button onClick={onClose} className="btn btn-primary btn-sm">Done</button>
              </div>
            </div>
          ) : (
            <table style={{width:'100%',borderCollapse:'collapse',fontSize:'.82rem'}}>
              <thead>
                <tr style={{background:'var(--surface-2)'}}>
                  <th style={{padding:'8px 12px',textAlign:'left',fontWeight:600,color:'var(--text-2)'}}>Date</th>
                  <th style={{padding:'8px 12px',textAlign:'left',fontWeight:600,color:'var(--text-2)'}}>Description</th>
                  <th style={{padding:'8px 12px',textAlign:'right',fontWeight:600,color:'var(--text-2)'}}>Amount</th>
                  <th style={{padding:'8px 12px',textAlign:'left',fontWeight:600,color:'var(--text-2)'}}>Who</th>
                  <th style={{padding:'8px 12px',textAlign:'left',fontWeight:600,color:'var(--text-2)'}}>New GL</th>
                  <th style={{padding:'8px 12px',textAlign:'center',fontWeight:600,color:'var(--text-2)',width:110}}>Action</th>
                </tr>
              </thead>
              <tbody>
                {visibleMatches.map(({ai, row, newGl}) => (
                  <tr key={ai} style={{borderBottom:'1px solid var(--border)'}}>
                    <td style={{padding:'8px 12px',color:'var(--text-3)',whiteSpace:'nowrap'}}>
                      {row.date||''}
                    </td>
                    <td style={{padding:'8px 12px',maxWidth:200,overflow:'hidden',
                      textOverflow:'ellipsis',whiteSpace:'nowrap'}} title={row.description}>
                      {row.description||''}
                    </td>
                    <td style={{padding:'8px 12px',textAlign:'right',
                      color:(row.debit||0)>0?'var(--danger)':'var(--success)',fontWeight:600,whiteSpace:'nowrap'}}>
                      {(row.debit||0)>0 ? `-$${(row.debit).toFixed(2)}` : `+$${(row.credit||0).toFixed(2)}`}
                    </td>
                    <td style={{padding:'8px 12px',color:'var(--text-2)',whiteSpace:'nowrap'}}>
                      {row.who||'—'}
                    </td>
                    <td style={{padding:'8px 12px'}}>
                      <span style={{background:'var(--brand-bg,#eff6ff)',color:'var(--brand)',
                        borderRadius:4,padding:'2px 6px',fontSize:'.75rem',fontWeight:600}}>
                        {newGl}
                      </span>
                    </td>
                    <td style={{padding:'8px 12px',textAlign:'center'}}>
                      <div style={{display:'flex',gap:4,justifyContent:'center'}}>
                        <button onClick={()=>accept(ai)}
                          className="btn btn-sm"
                          style={{padding:'2px 10px',fontSize:'.72rem',
                            background:'var(--success,#22c55e)',color:'#fff',border:'none',
                            borderRadius:4,cursor:'pointer'}}>
                          OK
                        </button>
                        <button onClick={()=>reject(ai)}
                          className="btn btn-ghost btn-sm"
                          style={{padding:'2px 8px',fontSize:'.72rem'}}>
                          No
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        {visibleMatches.length > 0 && (
          <div style={{padding:'10px 18px',borderTop:'1px solid var(--border)',
            display:'flex',gap:8,justifyContent:'flex-end',flexShrink:0}}>
            <button onClick={()=>visibleMatches.forEach(m=>accept(m.ai))}
              className="btn btn-primary btn-sm">
              Accept All ({visibleMatches.length})
            </button>
            <button onClick={()=>visibleMatches.forEach(m=>reject(m.ai))}
              className="btn btn-ghost btn-sm">
              Reject All
            </button>
            <button onClick={onClose} className="btn btn-ghost btn-sm">Close</button>
          </div>
        )}
      </div>
      {/* Rule Preview Popup — fires when + Save Rule is clicked */}
      {rulePreview && (
        <RulePreviewModal
          preview={rulePreview}
          onAccept={(matchAi, match) => {
            setTransactions(prev => prev.map((t,i) =>
              i === matchAi
                ? {...t, gl_account: match.newGl,
                    gst_category: match.newGst||t.gst_category,
                    gl_type: match.newGlType||t.gl_type}
                : t
            ))
          }}
          onReject={()=>{}}
          onClose={() => setRulePreview(null)}
        />
      )}
      {saveRuleRow && (
        <SaveAsRuleModal row={saveRuleRow}
          onClose={()=>setSaveRuleRow(null)}
          onSaved={()=>{setSaveRuleRow(null);toast.success('Rule saved')}}
        />
      )}
    </div>
  )
}

export default function OutputPanel({
  transactions, setTransactions, monthlySummary, setMonthlySummary,
  sessionId, username, userId, onRefresh, classifying: externalClassifying
}) {
  const [page,        setPage]        = useState(1)
  const [filters,     setFilters]     = useState({internal:true,incoming:true,outgoing:true,unclassified:true})
  const [search,      setSearch]      = useState('')
  const [selected,    setSelected]    = useState(new Set())
  const [sort,        setSort]        = useState({field:null,dir:'asc'})
  const [colFilters,  setColFilters]  = useState({})
  const [inlineEdits, setInlineEdits] = useState({})   // {absIdx: {field: val}}
  const [showAdd,     setShowAdd]     = useState(false)
  const [newRow,      setNewRow]      = useState({...BLANK})
  const [saving,      setSaving]      = useState(false)
  const [showSummary, setShowSummary] = useState(false)  // collapsed by default
  const [coaChanged, setCoaChanged]   = useState(false)
  const [saveRuleRow, setSaveRuleRow] = useState(null)
  const [editedRows,   setEditedRows]   = useState({})
  const [rulePreview,  setRulePreview]  = useState(null) // {rule, matches:[{ai, row, newGl, newGst}]}
  const [userChecked, setUserChecked] = useState({})    // {rowIndex: true} — user reviewed rows
  const [showTxn,     setShowTxn]     = useState(true)
  const [expandedLoans, setExpandedLoans] = useState({}) // {origIdx: true} — expanded loan sub-rows
  const [dbStats,       setDbStats]       = useState(null)  // DB storage stats
  const [dbStatsOpen,   setDbStatsOpen]   = useState(false) // panel open/closed
  const [dbStatsLoading,setDbStatsLoading]= useState(false)
  const [confirmClear,  setConfirmClear]  = useState(false) // Clear My Data confirm
  const [clearing,      setClearing]      = useState(false) // Clear My Data in progress
  const [accountBalances,   setAccountBalances]   = useState({})  // "bank|account|year|month" -> {balance,source,is_manual}
  const [editingBalance,    setEditingBalance]    = useState(null) // {key,bank,account,year,month,value} | null
  const [savingBalance,     setSavingBalance]     = useState(false)

  // Fetch DB stats + account balances whenever transactions change
  React.useEffect(() => {
    if (!userId || !transactions || transactions.length === 0) return
    setDbStatsLoading(true)
    getDbStats(userId)
      .then(r => setDbStats(r.data))
      .catch(() => setDbStats(null))
      .finally(() => setDbStatsLoading(false))
    getAccountBalances(userId)
      .then(r => setAccountBalances(r.data || {}))
      .catch(() => {})
  }, [userId, transactions?.length])
  const [glAccounts,  setGlAccounts]  = useState([
    'Revenue','Direct Costs','Expense','Inventory','Fixed Asset','GST','Equity','Transfer','Liability',''
  ])
  const [coaMap, setCoaMap] = useState({})

  React.useEffect(()=>{
    fetch('/api/gl/accounts').then(r=>r.json()).then(d=>{
      if(Array.isArray(d) && d.length) setGlAccounts(d)
    }).catch(()=>{})
    fetch('/api/gl/accounts/all').then(r=>r.json()).then(d=>{
      const rows = Array.isArray(d) ? d : (d.rows||[])
      if(rows.length){
        const map = {}
        // API row has both PascalCase (for modal) and snake_case (for coaMap)
        rows.forEach(r=>{
          const name = r.Name || r.name
          if(name) map[name] = {
            type:     r.Type     || r.type     || '',
            tax_code: r.TaxCode  || r.tax_code || r['Tax Code'] || '',
          }
        })
        setCoaMap(map)
      }
    }).catch(()=>{})
  },[])

  // ── GL accounts grouped by GL Type for grouped <select> ──────────────────
  const glByType = useMemo(() => {
    const groups = {}
    glAccounts.forEach(name => {
      if (!name) return
      const type = coaMap[name]?.type || 'Other'
      if (!groups[type]) groups[type] = []
      groups[type].push(name)
    })
    // Sort group names; put 'Other' last
    return Object.entries(groups).sort(([a],[b]) =>
      a === 'Other' ? 1 : b === 'Other' ? -1 : a.localeCompare(b)
    )
  }, [glAccounts, coaMap])

  // ── filtered + sorted rows ────────────────────────────────────────────────
  const filtered = useMemo(() => {
    let rows = transactions.map((t,i)=>({...t,_origIdx:i,
      // Normalize classification at display time — handles both "-Internal" and "🟢Internal"
      classification: normalizeClassification(t.classification)
    })).filter(t => {
      const cl = t.classification || ''
      if (!filters.internal     && cl.includes('Internal'))    return false
      if (!filters.incoming     && cl.includes('Incoming'))    return false
      if (!filters.outgoing     && cl.includes('Outgoing'))    return false
      if (!filters.unclassified && cl.includes('Unclassified')) return false
      // Column filters (excluded values)
      for (const [field, included] of Object.entries(colFilters)) {
        if (included && included.size > 0) {
          const v = String(t[field]||'')
          if (!included.has(v)) return false
        }
      }
      return true
    })
    if (search.trim()) {
      const q = search.toLowerCase()
      rows = rows.filter(t =>
        (t.description||'').toLowerCase().includes(q) ||
        (t.bank||'').toLowerCase().includes(q) ||
        (t.account||'').toLowerCase().includes(q) ||
        (t.who||'').toLowerCase().includes(q)
      )
    }
    if (sort.field) {
      const parseVal = (v, field) => {
        if (field === 'date') {
          // Parse dd/mm/yyyy or ISO date for correct year-month-day comparison
          const s = String(v||'').trim()
          const dm = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/)
          if (dm) return new Date(+dm[3], +dm[2]-1, +dm[1]).getTime()
          const iso = Date.parse(s)
          return isNaN(iso) ? 0 : iso
        }
        const n = parseFloat(v)
        return isNaN(n) ? String(v??'').toLowerCase() : n
      }
      rows = [...rows].sort((a,b)=>{
        const av = parseVal(a[sort.field], sort.field)
        const bv = parseVal(b[sort.field], sort.field)
        if (av < bv) return sort.dir==='asc' ? -1 : 1
        if (av > bv) return sort.dir==='asc' ?  1 : -1
        return 0
      })
    }
    return rows
  }, [transactions, filters, search, sort, colFilters])

  const totalPages = Math.max(1, Math.ceil(filtered.length/PAGE_SZ))
  const safePage   = Math.min(page, totalPages)
  const pageRows   = filtered.slice((safePage-1)*PAGE_SZ, safePage*PAGE_SZ)

  // ── Running balance: prefer bank-supplied, fall back to cumulative computed ─
  const balanceByOrigIdx = useMemo(() => {
    // Check if any transaction has a real bank balance
    const hasRealBalance = transactions.some(t => t.balance != null && t.balance !== '')
    if (hasRealBalance) return null  // signal: use row.balance directly
    // Fallback: compute running balance over filtered+sorted set
    const map = {}
    let running = 0
    filtered.forEach(row => {
      running += (parseFloat(row.credit) || 0) - (parseFloat(row.debit) || 0)
      map[row._origIdx] = running
    })
    return map
  }, [transactions, filtered])

  const stats = useMemo(() => {
    const inc  = filtered.filter(t=>(t.classification||'').includes('Incoming'))
    const out  = filtered.filter(t=>(t.classification||'').includes('Outgoing'))
    const int_ = filtered.filter(t=>(t.classification||'').includes('Internal'))
    return {
      totalIn:  inc.reduce((s,t)=>s+(t.credit||0),0),
      totalOut: out.reduce((s,t)=>s+(t.debit||0),0),
      totalGST: filtered.reduce((s,t)=>s+(t.gst||0),0),
      intCount: int_.length,
    }
  }, [filtered])

  // colVals reads ALL transactions so options never disappear when filter is active
  const colVals = useCallback((field) =>
    transactions.map(t=>String(t[field]||'')), [transactions])

  // ── inline edit helpers ───────────────────────────────────────────────────
  // originalVals stores the transaction snapshot BEFORE any edits on a row,
  // so Cancel can restore the exact previous state.
  const [originalVals, setOriginalVals] = useState({})  // {absIdx: {field: originalVal}}

  const getCell = (ai, field, fallback) => {
    return inlineEdits[ai]?.[field] !== undefined ? inlineEdits[ai][field] : fallback
  }

  const setCell = (ai, field, val) => {
    // Snapshot original value the FIRST time this row is edited
    setOriginalVals(prev => {
      if (prev[ai]?.[field] !== undefined) return prev   // already saved
      const orig = transactions[ai]?.[field]
      return {...prev, [ai]: {...(prev[ai]||{}), [field]: orig}}
    })
    setInlineEdits(e=>({...e,[ai]:{...(e[ai]||{}),[field]:val}}))
  }

  // Cancel all edits on one row — restores to snapshot taken before editing began
  const cancelRowEdits = (ai) => {
    setInlineEdits(e => { const n={...e}; delete n[ai]; return n })
    setOriginalVals(v => { const n={...v}; delete n[ai]; return n })
    // Also revert any direct updateCell changes on this row
    setTransactions(prev => prev.map((t,i) => {
      if (i !== ai) return t
      const orig = originalVals[ai]
      return orig ? {...t, ...orig} : t
    }))
    toast('Row changes cancelled', {icon:'↩️'})
  }

  const hasEdits = Object.keys(inlineEdits).length > 0

  // Save all inline edits to transactions state
  const commitEdits = () => {
    if (!hasEdits) return
    // Collect rows that had Who changes before clearing edits
    const whoChangedRows = Object.entries(inlineEdits)
      .filter(([_, edits]) => edits.who !== undefined)
      .map(([ai, edits]) => ({
        ...transactions[parseInt(ai)],
        ...edits,
      }))
    setTransactions(prev => prev.map((t,i) => {
      const edits = inlineEdits[i]
      return edits ? {...t,...edits} : t
    }))
    setInlineEdits({})
    setOriginalVals({})
    toast.success('Changes applied')
    // Capture Who edits to company DB (async, best-effort)
    captureWhoEdits(whoChangedRows)
  }

  // ── Capture Who edits to company DB ────────────────────────────────────────
  // Called after commitEdits — finds rows where Who was changed, sends to backend
  // for auto-capture as pending company + alias creation.
  const captureWhoEdits = async (editedRows) => {
    if (!editedRows || editedRows.length === 0) return
    const whoEdits = editedRows.filter(r => r.who && r.who.trim())
    if (!whoEdits.length) return
    // Deduplicate by who name — one capture per unique company name
    const seen = new Set()
    for (const row of whoEdits) {
      const key = (row.who || '').trim().toLowerCase()
      if (!key || seen.has(key)) continue
      seen.add(key)
      try {
        const res = await captureWho(row.who.trim(), row.description || '', username)
        const d = res.data
        if (d?.action === 'company_created_pending') {
          toast(`🏢 "${row.who}" added as pending company — approve in Company DB`,
            { duration: 5000, icon: '🔔' })
        } else if (d?.action === 'aliases_added' && d.aliases_added > 0) {
          // Silent — existing company got new aliases, no need to notify
        }
      } catch (_) {
        // Silent — capturing is best-effort, never block the save flow
      }
    }
  }

  // ── selection ─────────────────────────────────────────────────────────────
  const toggleS   = ai => setSelected(s=>{const n=new Set(s);n.has(ai)?n.delete(ai):n.add(ai);return n})
  const toggleAll = () => {
    const idxs = pageRows.map(r=>r._origIdx)
    const allSel = idxs.every(i=>selected.has(i))
    if (allSel) setSelected(s=>{const n=new Set(s);idxs.forEach(i=>n.delete(i));return n})
    else setSelected(s=>{const n=new Set(s);idxs.forEach(i=>n.add(i));return n})
  }
  const toggleF = k => {
    setFilters(f=>({...f,[k]:!f[k]}))
    setColFilters(cf => {
      if (!cf.classification || cf.classification.size === 0) return cf
      const next = {...cf}
      delete next.classification
      return next
    })
    setPage(1)
  }

  // ── direct cell update (GL/GST selects in table) ──────────────────────────
  const updateCell = useCallback((ai, field, val) => {
    setTransactions(prev => prev.map((t,i) => i===ai ? {...t,[field]:val} : t))
  }, [setTransactions])

  // ── delete ────────────────────────────────────────────────────────────────
  const deleteSelected = () => {
    const idxs = new Set(selected)
    setTransactions(prev=>prev.filter((_,i)=>!idxs.has(i)))
    setSelected(new Set()); setInlineEdits({})
    toast.success(`Deleted ${idxs.size} row(s)`)
  }

  // ── add row ───────────────────────────────────────────────────────────────
  const addRow = () => {
    setTransactions(prev=>[...prev,{...newRow}])
    setShowAdd(false); setNewRow({...BLANK}); toast.success('Row added')
  }

  // ── classify ─────────────────────────────────────────────────────────────
  const handleClassify = async () => {
    if (!sessionId) { toast.error('Process files first'); return }
    try { await saveSession({session_id:sessionId,username,transactions,pending_changes:{},page_number:safePage}) } catch {}
    try {
      const { data } = await classifyGL(sessionId, username)
      if (data?.transactions) {
        setTransactions(normalizeTransactions(data.transactions))
        if (data.monthly_summary) setMonthlySummary(data.monthly_summary)
        toast.success('GL & GST classification complete')
        // Auto-save session after classify completes
        try { await saveSession({session_id:sessionId,username,transactions:data.transactions,pending_changes:{},page_number:safePage}) } catch {}
      }
    } catch (e) { toast.error(e.response?.data?.detail||'Classification failed') }
  }

  // Full reclassify — clears existing GL/GST and re-runs from current COA
  const handleReclassify = async () => {
    if (!sessionId) { toast.error('Process files first'); return }
    try { await saveSession({session_id:sessionId,username,transactions,pending_changes:{},page_number:safePage}) } catch {}
    try {
      toast.loading('Reclassifying all rows…', {id:'reclassify'})
      const { data } = await reclassifyGL(sessionId, username)
      if (data?.transactions) {
        setTransactions(normalizeTransactions(data.transactions))
        if (data.monthly_summary) setMonthlySummary(data.monthly_summary)
        toast.success('Reclassification complete', {id:'reclassify'})
        setCoaChanged(false)
        // Auto-save session after reclassify completes
        try { await saveSession({session_id:sessionId,username,transactions:data.transactions,pending_changes:{},page_number:safePage}) } catch {}
      }
    } catch (e) {
      toast.error(e.response?.data?.detail||'Reclassification failed', {id:'reclassify'})
    }
  }

  // ── manual pair ── FIX 3 (unique ID) + FIX 4 (validation) ──────────────────
  const handleManualPair = () => {
    if (selected.size < 2) { toast.error('Select 2 or more transactions to pair'); return }

    // FIX 4a: must be even number of rows
    if (selected.size % 2 !== 0) {
      toast.error(`Selected ${selected.size} rows — pairing requires an even number. Please select ${selected.size + 1} or ${selected.size - 1} rows.`)
      return
    }

    const idxs = [...selected].sort((a,b)=>a-b)
    const selRows = idxs.map(i => transactions[i])

    // FIX 4b: debit total must equal credit total (within $0.01)
    const totalDebit  = selRows.reduce((s,t) => s + (parseFloat(t.debit)  || 0), 0)
    const totalCredit = selRows.reduce((s,t) => s + (parseFloat(t.credit) || 0), 0)
    if (Math.abs(totalDebit - totalCredit) > 0.01) {
      toast.error(
        `Debit total ($${totalDebit.toFixed(2)}) ≠ credit total ($${totalCredit.toFixed(2)}). ` +
        `Difference: $${Math.abs(totalDebit - totalCredit).toFixed(2)}. ` +
        `Internal transfers must balance.`
      )
      return
    }

    // FIX 4c: credit date must not be earlier than debit date
    const parseDate = s => {
      if (!s) return null
      const dm = String(s).match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/)
      if (dm) return new Date(+dm[3], +dm[2]-1, +dm[1])
      const d = new Date(s); return isNaN(d) ? null : d
    }
    const debitRows  = selRows.filter(t => (parseFloat(t.debit)  || 0) > 0)
    const creditRows = selRows.filter(t => (parseFloat(t.credit) || 0) > 0)
    if (debitRows.length && creditRows.length) {
      const minDebitDate  = debitRows.reduce((m,t)  => { const d=parseDate(t.date); return d&&(!m||d<m)?d:m }, null)
      const minCreditDate = creditRows.reduce((m,t) => { const d=parseDate(t.date); return d&&(!m||d<m)?d:m }, null)
      if (minDebitDate && minCreditDate && minCreditDate < minDebitDate) {
        toast.error(
          `Credit date (${minCreditDate.toLocaleDateString('en-AU')}) is earlier than ` +
          `debit date (${minDebitDate.toLocaleDateString('en-AU')}). ` +
          `The receiving transaction cannot precede the sending transaction.`
        )
        return
      }
    }

    // FIX 3: Generate unique PairID per pairing action
    const now = new Date()
    const pad = n => String(n).padStart(2,'0')
    const datePart = `${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}`
    const timePart = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
    const randPart = Math.random().toString(16).slice(2,8)
    const pid = `MPAIR-${datePart}-${timePart}-${randPart}`

    setTransactions(prev => prev.map((t,i) => {
      if (!selected.has(i)) return t
      return { ...t, classification: '🟢Internal', pairid: pid,
               gl_account: '', gl_type: '', gst_category: '', gst: 0 }
    }))
    setSelected(new Set())
    toast.success(`${idxs.length} transactions paired (${pid})`)
  }

  // ── save session ──────────────────────────────────────────────────────────
  const handleSaveSession = async () => {
    if (!sessionId) { toast.error('No active session'); return }
    // commit any pending inline edits first
    if (hasEdits) commitEdits()
    try {
      await saveSession({session_id:sessionId,username,transactions,pending_changes:{},page_number:safePage})
      toast.success('Session saved')
    } catch { toast.error('Session save failed') }
  }

  // ── save to DB ─────────────────────────────────────────────────────────────
  // ── export ────────────────────────────────────────────────────────────────
  const handleExport = async () => {
    try {
      const { data } = await exportExcel(transactions)
      const url = URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a'); a.href=url; a.download='accfino_reconciliation.xlsx'; a.click()
      URL.revokeObjectURL(url)
    } catch { toast.error('Export failed') }
  }

  const SH = {field:sort.field, dir:sort.dir}
  // Column widths — default + user-draggable
  const DEFAULT_WIDTHS = {
    date:90,           // 10 chars: dd/mm/yyyy
    bank:160,
    description:240,   // user can drag to expand
    debit:90, credit:90, balance:100,
    pairid:80,
    gl_account:160, gst:80, gst_category:140, who:90,
  }
  const [colWidths, setColWidths] = useState(DEFAULT_WIDTHS)
  const [colsResized, setColsResized] = useState(false)
  const setColWidth = (field, w) => { setColWidths(prev => ({...prev, [field]: w})); setColsResized(true) }

  // ── Single shared filter popover state — rendered OUTSIDE the table ────────
  // This is the fix for the dropdown not appearing below the column header.
  // Previously ColFilter was a child of <th> in the JSX tree. Even with a portal
  // it shared React's event propagation with the <th>, causing outside-click
  // handlers to fire immediately and the anchor position to be unreliable.
  // Now: SortTh calls onOpenFilter(field, rect) → state lives here in OutputPanel
  // → ONE ColFilter portal renders after the table, with no scroll-container ancestors.
  const [activeFilter, setActiveFilter] = useState(null)  // {field, anchorPos} | null

  const openFilterFor = useCallback((field, anchorPos) => {
    setActiveFilter(prev => (prev && prev.field === field) ? null : { field, anchorPos })
  }, [])

  const closeFilter = useCallback(() => setActiveFilter(null), [])

  const thProps = (label, field, style) => ({
    label, field,
    style: {textAlign: style?.textAlign},
    sort:SH, setSort,
    colFilters,
    onOpenFilter: openFilterFor,   // replaces setColFilters in SortTh — filter state stays here
    values:   colVals(field),
    colWidth: colWidths[field] || undefined,
    onResize: w => setColWidth(field, w),
  })

  return (
    <div>
      <StatStrip stats={stats} />

      {/* Monthly Summary */}
      {monthlySummary?.length > 0 && (
        <div style={{marginBottom:16,border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden'}}>
          <button onClick={()=>setShowSummary(s=>!s)} style={{
            width:'100%',display:'flex',alignItems:'center',gap:8,padding:'11px 18px',
            background:'var(--surface-2)',border:'none',cursor:'pointer',fontFamily:'inherit',justifyContent:'space-between',
          }}>
            <div style={{display:'flex',alignItems:'center',gap:8,fontWeight:600,fontSize:'.875rem',color:'var(--text-1)'}}>
              📊 Monthly Summary
              <span style={{fontWeight:400,fontSize:'.78rem',color:'var(--text-3)'}}>{monthlySummary.length-1} months</span>
            </div>
            {showSummary ? <ChevronUp size={15} color="var(--text-3)"/> : <ChevronDown size={15} color="var(--text-3)"/>}
          </button>
          {showSummary && (
            <div style={{overflowX:'auto'}}>
              <table className="summary-table">
                <thead>
                  <tr>
                    {['Bank/Account','Year/Month','Opening Balance','🟢Internal Transfers','🔵Incoming Count','🟡Outgoing Count',
                      'Total 🔵Incoming Income','Total 🟡Outgoing Expense',
                      'Total 🔵Incoming GST','Total 🟡Outgoing GST','Closing Balance'].map(h=>(
                      <th key={h} style={h==='Opening Balance'||h==='Closing Balance'?{color:'var(--brand)'}:{}}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {monthlySummary.map((row,i)=>{
                    const rt = row['_row_type'] || (row['Year/Month']==='Grand Total' ? 'grand_total' : 'month')
                    const isYearTotal  = rt === 'year_total'
                    const isGrandTotal = rt === 'grand_total'
                    const isMonth      = rt === 'month'
                    const rowStyle = isGrandTotal
                      ? {fontWeight:700, background:'#FFFDE7', borderTop:'2px solid #E0C840'}
                      : isYearTotal
                        ? {fontWeight:600, background:'var(--surface-2)', borderTop:'1px solid var(--border)', borderBottom:'2px solid var(--border)', fontStyle:'italic'}
                        : {}
                    const labelStyle = isGrandTotal
                      ? {fontSize:'.82rem', fontWeight:700, color:'var(--brand)'}
                      : isYearTotal
                        ? {fontSize:'.8rem', fontWeight:600, color:'var(--text-2)', paddingLeft:8}
                        : {fontSize:'.8rem', fontFamily:'var(--font-mono)', paddingLeft:16}

                    // Balance display helpers
                    // ob/cb come from monthlySummary (set by backend on process)
                    // But also check accountBalances state (updated by manual entry or DB load)
                    const obFromSummary = row['opening_balance']
                    const cbFromSummary = row['closing_balance']
                    const bsrc = row['balance_source']
                    const balKey = `${row['_bank']||''}|${row['_account']||''}|${row['Year/Month']?.split('/')[0]}|${parseInt(row['Year/Month']?.split('/')[1])}`
                    const dbBal = accountBalances[balKey]
                    // Manual/DB balance overrides backend-computed one
                    const ob = dbBal?.balance != null ? dbBal.balance : obFromSummary
                    // Use CSV-derived closing from backend — never recompute from income/expense
                    // because internal transfers affect balance but are excluded from those totals
                    const cb  = cbFromSummary != null ? cbFromSummary : (ob != null ? ob : null)
                    const effectiveSrc = dbBal ? (dbBal.is_manual ? 'manual' : dbBal.source) : bsrc
                    const isEditing = editingBalance?.key === balKey

                    const fmtBal = (v) => v == null ? '—' : (
                      <span style={{fontFamily:'var(--font-mono)',fontWeight:600,
                        color: v < 0 ? 'var(--danger,#ef4444)' : 'var(--success,#16a34a)'}}>
                        {v < 0 ? '-' : ''}${Math.abs(v).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2})}
                      </span>
                    )

                    return (
                      <tr key={i} style={rowStyle}>
                        <td style={{whiteSpace:'nowrap'}}>
                          {isMonth ? (
                            <span style={{fontSize:'.78rem',color:'var(--text-2)',fontWeight:500}}>
                              {row['_bank']||''}
                              {(row['_account_name']||row['_account']) && (
                                <span style={{color:'var(--text-3)',fontWeight:400}}>
                                  {'/'}{(row['_account_name']||'')+(row['_account']||'')}
                                </span>
                              )}
                            </span>
                          ) : ''}
                        </td>
                        <td><span style={labelStyle}>{row['Year/Month']}</span></td>

                        {/* Opening Balance cell — editable for month rows */}
                        <td style={{minWidth:140}}>
                          {isMonth ? (
                            isEditing ? (
                              <div style={{display:'flex',alignItems:'center',gap:4}}>
                                <input
                                  type="number" step="0.01"
                                  value={editingBalance.value}
                                  onChange={e=>setEditingBalance(p=>({...p,value:e.target.value}))}
                                  autoFocus
                                  style={{width:100,fontFamily:'var(--font-mono)',fontSize:'.78rem',
                                    border:'1px solid var(--brand)',borderRadius:4,padding:'2px 6px'}}
                                  onKeyDown={e=>{
                                    if (e.key==='Enter') {
                                      const parts = row['Year/Month'].split('/')
                                      setSavingBalance(true)
                                      upsertAccountBalance({
                                        user_id: userId,
                                        bank: row['_bank']||'',
                                        account: row['_account']||'',
                                        year: parseInt(parts[0]),
                                        month: parseInt(parts[1]),
                                        balance: parseFloat(editingBalance.value)||0,
                                        is_manual: true,
                                      }).then(()=>{
                                        setAccountBalances(p=>({...p,[balKey]:{balance:parseFloat(editingBalance.value)||0,is_manual:true,source:'manual'}}))
                                        toast.success('Opening balance saved')
                                      }).catch(()=>toast.error('Save failed'))
                                        .finally(()=>{setSavingBalance(false);setEditingBalance(null)})
                                    }
                                    if (e.key==='Escape') setEditingBalance(null)
                                  }}
                                />
                                <button onClick={()=>setEditingBalance(null)}
                                  style={{background:'none',border:'none',cursor:'pointer',color:'var(--text-3)',padding:0}}>
                                  <X size={12}/>
                                </button>
                              </div>
                            ) : (
                              <div style={{display:'flex',alignItems:'center',gap:6}}>
                                {fmtBal(ob)}
                                {effectiveSrc==='csv'&&<span title="From bank CSV" style={{fontSize:'.6rem',color:'var(--success)',opacity:.7}}>csv</span>}
                                {effectiveSrc==='derived'&&<span title="Derived from net movement" style={{fontSize:'.6rem',color:'var(--text-3)'}}>~</span>}
                                {effectiveSrc==='manual'&&<span title="Manually entered" style={{fontSize:'.6rem',color:'var(--brand)'}}>✎</span>}
                                <button
                                  title="Click to enter opening balance"
                                  onClick={()=>setEditingBalance({key:balKey,value:ob??''})}
                                  style={{background:'none',border:'none',cursor:'pointer',color:'var(--text-3)',
                                    padding:'1px 3px',opacity:.5,':hover':{opacity:1}}}>
                                  <Pencil size={10}/>
                                </button>
                              </div>
                            )
                          ) : fmtBal(ob)}
                        </td>

                        <td>{row['🟢Internal Transfers']}</td>
                        <td>{row['🔵Incoming Count']}</td>
                        <td>{row['🟡Outgoing Count']}</td>
                        <td className="num">{fmtAUD(row['Total 🔵Incoming Income'])}</td>
                        <td className="num">{fmtAUD(row['Total 🟡Outgoing Expense'])}</td>
                        <td className="num">{fmtAUD(row['Total 🔵Incoming GST'])}</td>
                        <td className="num">{fmtAUD(row['Total 🟡Outgoing GST'])}</td>

                        {/* Closing Balance */}
                        <td style={{minWidth:120}}>{fmtBal(cb)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>

            </div>
          )}
        </div>
      )}

      {/* Transaction Details */}
      <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-lg)',overflow:'hidden',marginBottom:8}}>
        <button onClick={()=>setShowTxn(s=>!s)} style={{
          width:'100%',display:'flex',alignItems:'center',gap:8,padding:'11px 18px',
          background:'var(--surface-2)',border:'none',cursor:'pointer',fontFamily:'inherit',justifyContent:'space-between',
        }}>
          <div style={{display:'flex',alignItems:'center',gap:8,fontWeight:600,fontSize:'.875rem',color:'var(--text-1)'}}>
            📋 Transaction Details
            <span style={{fontWeight:400,fontSize:'.78rem',color:'var(--text-3)'}}>{filtered.length} rows</span>
          </div>
          {showTxn ? <ChevronUp size={15} color="var(--text-3)"/> : <ChevronDown size={15} color="var(--text-3)"/>}
        </button>

        {showTxn && <div style={{padding:'8px'}}>

          {/* Toolbar */}
          <div style={{display:'flex',gap:8,marginBottom:6,flexWrap:'wrap',alignItems:'center'}}>
            <div className="search-wrap" style={{flex:'none'}}>
              <svg className="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
              <input className="input input-sm" style={{width:220,paddingLeft:34}} placeholder="Search description, bank, who…"
                value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}}/>
            </div>
            <div style={{flex:1}}/>
            <button className="btn btn-outline btn-sm" onClick={()=>setShowAdd(s=>!s)}><Plus size={13}/> Add Row</button>
            {selected.size >= 2 && (
              <button className="btn btn-outline btn-sm" onClick={handleManualPair}
                style={{borderColor:'var(--success)',color:'var(--success)'}}
                title={`Pair ${selected.size} selected transactions as Internal transfer`}>
                🔗 Pair ({selected.size})
              </button>
            )}

            <button className="btn btn-accent btn-sm" onClick={()=>{setCoaChanged(false);handleReclassify()}}
              disabled={false}
              title={coaChanged ? "Re-classify all rows using current COA" : "Make GL edits first, or just click to force re-classify"}
              style={{opacity: coaChanged ? 1 : 0.5}}>
              <RefreshCw size={13}/> Reclassify
            </button>
            {hasEdits && (
              <button className="btn btn-warning btn-sm" onClick={commitEdits}>
                <Check size={13}/> Apply Edits ({Object.keys(inlineEdits).length})
              </button>
            )}
            <button className="btn btn-outline btn-sm" onClick={handleExport}><Download size={13}/> Excel</button>
            {/* DB Status indicator */}
            <button
              className={`btn btn-sm${dbStats ? ' btn-success' : ' btn-ghost'}`}
              onClick={() => {
                setDbStatsOpen(o => !o)
                if (!dbStats && userId) {
                  setDbStatsLoading(true)
                  getDbStats(userId).then(r => setDbStats(r.data)).catch(()=>setDbStats(null)).finally(()=>setDbStatsLoading(false))
                }
              }}
              title="View database storage status"
              style={{
                background: dbStats ? 'var(--success-bg,#dcfce7)' : 'var(--surface-3)',
                color:       dbStats ? 'var(--success,#16a34a)' : 'var(--text-3)',
                border:      dbStats ? '1px solid #86efac' : '1px solid var(--border)',
                gap: 4,
              }}
            >
              <Database size={13}/>
              {dbStatsLoading
                ? <span className="spinner spinner-sm" style={{width:10,height:10}}/>
                : dbStats
                  ? <span style={{fontFamily:'var(--font-mono)',fontWeight:700}}>{dbStats.total.toLocaleString()} rows</span>
                  : 'DB Status'
              }
            </button>
            {selected.size>0 && (
              <button className="btn btn-danger btn-sm" onClick={deleteSelected}><Trash2 size={13}/> Delete ({selected.size})</button>
            )}
          </div>

          {/* ── DB Status Panel ── */}
          {dbStatsOpen && (
            <div style={{
              margin:'0 0 8px 0',
              border:'1px solid var(--border)',
              borderRadius:'var(--r-lg)',
              background:'var(--surface)',
              overflow:'hidden',
              boxShadow:'var(--sh-xs)',
            }}>
              {/* Header */}
              <div style={{
                display:'flex',alignItems:'center',gap:10,
                padding:'10px 16px',
                background: dbStats ? 'var(--success-bg,#dcfce7)' : 'var(--surface-2)',
                borderBottom:'1px solid var(--border)',
              }}>
                <Database size={15} color={dbStats ? 'var(--success,#16a34a)' : 'var(--text-3)'}/>
                <span style={{fontWeight:700,fontSize:'.875rem',color:'var(--text-1)'}}>
                  Database Storage Status
                </span>
                {dbStats && (
                  <span style={{
                    marginLeft:'auto',fontFamily:'var(--font-mono)',fontSize:'.75rem',
                    color:'var(--text-3)',
                  }}>
                    Last saved: {dbStats.latest_saved_at
                      ? new Date(dbStats.latest_saved_at).toLocaleString('en-AU',{dateStyle:'short',timeStyle:'short'})
                      : '—'}
                  </span>
                )}
                <button onClick={()=>setDbStatsOpen(false)} style={{
                  background:'none',border:'none',cursor:'pointer',color:'var(--text-3)',
                  display:'flex',padding:2,marginLeft: dbStats ? 0 : 'auto',
                }}>
                  <X size={13}/>
                </button>
              </div>

              {dbStatsLoading && (
                <div style={{padding:'20px',textAlign:'center',color:'var(--text-3)',fontSize:'.875rem'}}>
                  <span className="spinner spinner-sm"/> Checking database…
                </div>
              )}

              {!dbStatsLoading && !dbStats && (
                <div style={{padding:'16px 20px',color:'var(--text-3)',fontSize:'.875rem'}}>
                  No data found in database for this account. Data is saved automatically after each processing run.
                </div>
              )}

              {!dbStatsLoading && dbStats && (
                <div style={{padding:'16px 20px'}}>
                  {/* Row count summary */}
                  <div style={{
                    display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))',gap:10,
                    marginBottom:16,
                  }}>
                    {[
                      {
                        label:'Total Rows Stored',
                        value: dbStats.total.toLocaleString(),
                        sub: 'transactions in DB',
                        color:'var(--brand)', bg:'var(--brand-light)',
                        icon:'🗄️',
                      },
                      {
                        label:'GL Account',
                        value: `${dbStats.columns.gl_account ?? 0}`,
                        sub: `of ${dbStats.total} rows`,
                        pct: dbStats.total ? Math.round((dbStats.columns.gl_account??0)/dbStats.total*100) : 0,
                        color:'var(--info,#0ea5e9)', bg:'var(--info-bg,#e0f2fe)',
                        icon:'📒',
                      },
                      {
                        label:'GST Category',
                        value: `${dbStats.columns.gst_category ?? 0}`,
                        sub: `of ${dbStats.total} rows`,
                        pct: dbStats.total ? Math.round((dbStats.columns.gst_category??0)/dbStats.total*100) : 0,
                        color:'var(--brand)', bg:'var(--brand-light)',
                        icon:'💰',
                      },
                      {
                        label:'Who (Counterparty)',
                        value: `${dbStats.columns.who ?? 0}`,
                        sub: `of ${dbStats.total} rows`,
                        pct: dbStats.total ? Math.round((dbStats.columns.who??0)/dbStats.total*100) : 0,
                        color:'var(--warning,#f59e0b)', bg:'var(--warning-bg,#fef3c7)',
                        icon:'🏢',
                      },
                      {
                        label:'Bank Balance',
                        value: `${dbStats.columns.bank_balance ?? 0}`,
                        sub: `of ${dbStats.total} rows`,
                        pct: dbStats.total ? Math.round((dbStats.columns.bank_balance??0)/dbStats.total*100) : 0,
                        color:'var(--success,#16a34a)', bg:'var(--success-bg,#dcfce7)',
                        icon:'⚖️',
                      },
                      {
                        label:'Loan Payments',
                        value: `${dbStats.columns.is_loan_payment ?? 0}`,
                        sub: `${dbStats.columns.loan_split ?? 0} with P/I split`,
                        color:'var(--danger,#ef4444)', bg:'#fee2e2',
                        icon:'🏦',
                      },
                    ].map(({label,value,sub,pct,color,bg,icon})=>(
                      <div key={label} style={{
                        background:'var(--surface-2)',border:'1px solid var(--border)',
                        borderRadius:'var(--r-md)',padding:'12px 14px',
                        display:'flex',flexDirection:'column',gap:4,
                      }}>
                        <div style={{fontSize:'1rem'}}>{icon}</div>
                        <div style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'1.1rem',color}}>
                          {value}
                        </div>
                        <div style={{fontSize:'.7rem',fontWeight:700,color:'var(--text-2)'}}>{label}</div>
                        <div style={{fontSize:'.68rem',color:'var(--text-3)'}}>{sub}</div>
                        {pct != null && (
                          <div style={{marginTop:2,height:3,background:'var(--border)',borderRadius:2}}>
                            <div style={{height:'100%',borderRadius:2,background:color,width:`${pct}%`,transition:'width .4s'}}/>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Currency row */}
                  {dbStats.currencies && dbStats.currencies.length > 0 && (
                    <div style={{
                      display:'flex',alignItems:'center',gap:8,
                      padding:'8px 12px',
                      background:'var(--surface-2)',borderRadius:'var(--r-md)',
                      border:'1px solid var(--border)',fontSize:'.78rem',
                    }}>
                      <span style={{color:'var(--text-3)',fontWeight:600}}>Currencies stored:</span>
                      {dbStats.currencies.map(c=>(
                        <span key={c} style={{
                          fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.75rem',
                          background: c === 'AUD' ? 'var(--brand-light)' : 'var(--warning-bg,#fef3c7)',
                          color:      c === 'AUD' ? 'var(--brand)'       : 'var(--warning,#b45309)',
                          padding:'2px 8px',borderRadius:100,
                        }}>{c}</span>
                      ))}
                      {dbStats.columns.currency_non_aud > 0 && (
                        <span style={{color:'var(--text-3)',fontSize:'.7rem',marginLeft:4}}>
                          ({dbStats.columns.currency_non_aud} converted to AUD)
                        </span>
                      )}
                    </div>
                  )}

                    {/* Helpful note + Clear Data button */}
                  <div style={{marginTop:10,display:'flex',alignItems:'flex-start',gap:10}}>
                    <div style={{
                      flex:1,padding:'8px 12px',
                      background:'var(--brand-xlight,#eff6ff)',borderRadius:'var(--r-sm)',
                      fontSize:'.72rem',color:'var(--text-3)',lineHeight:1.5,
                      border:'1px solid #bfdbfe',
                    }}>
                      ✅ Data is saved automatically after every processing run — original transaction fields
                      (date, bank, account, description, debit, credit, balance) <em>and</em> all processed
                      columns (GL Account, GST Category, Who, Classification, Loan split, Currency/rate) are
                      stored. Duplicate rows are skipped; updated classifications are upserted.
                    </div>
                    <div style={{display:'flex',flexDirection:'column',gap:4,alignItems:'flex-end',flexShrink:0}}>
                      {!confirmClear ? (
                        <button onClick={()=>setConfirmClear(true)} className="btn btn-ghost btn-xs"
                          style={{color:'var(--danger,#ef4444)',border:'1px solid var(--danger,#ef4444)',
                            whiteSpace:'nowrap',padding:'4px 10px',fontSize:'.72rem'}}>
                          🗑 Clear My Data
                        </button>
                      ) : (
                        <>
                          <span style={{fontSize:'.70rem',color:'var(--danger)',fontWeight:600,textAlign:'right'}}>
                            Delete all {dbStats.total.toLocaleString()} rows?
                          </span>
                          <div style={{display:'flex',gap:4}}>
                            <button onClick={()=>setConfirmClear(false)} className="btn btn-ghost btn-xs"
                              style={{fontSize:'.70rem',padding:'3px 8px'}}>Cancel</button>
                            <button onClick={async()=>{
                              setClearing(true)
                              try {
                                await clearUserDb(userId)
                                setDbStats(null); setDbStatsOpen(false); setConfirmClear(false)
                                toast.success('Database cleared — your data has been removed')
                              } catch { toast.error('Failed to clear database') }
                              finally { setClearing(false) }
                            }} disabled={clearing} className="btn btn-xs"
                              style={{background:'var(--danger,#ef4444)',color:'#fff',border:'none',
                                fontSize:'.70rem',padding:'3px 10px',fontWeight:600}}>
                              {clearing ? 'Clearing…' : '✓ Confirm Delete'}
                            </button>
                          </div>
                        </>
                      )}
                      <span style={{fontSize:'.65rem',color:'var(--text-3)',textAlign:'right',maxWidth:140,lineHeight:1.3}}>
                        Only your data.<br/>Other users unaffected.
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Filter chips — same box as toolbar */}
          <div style={{display:'flex',alignItems:'center',gap:4,
            padding:'6px 10px',background:'var(--surface-2)',borderRadius:'var(--r-md)',
            border:'1px solid var(--border)',flexWrap:'wrap',marginBottom:6}}>
            <span style={{fontSize:'.72rem',color:'var(--text-3)',marginRight:4,fontWeight:600}}>Show:</span>
            {[['internal','🟢','active-int'],['incoming','🔵','active-in'],
              ['outgoing','🟡','active-out'],['unclassified','⚪','']].map(([k,emoji,activeClass])=>(
              <button key={k} onClick={()=>toggleF(k)}
                className={`chip${filters[k] && activeClass ? ` ${activeClass}` : ''}`}
                style={{opacity:filters[k]?1:.4,transition:'opacity .15s',fontSize:'.75rem',padding:'4px 10px'}}>
                {emoji} {k.charAt(0).toUpperCase()+k.slice(1)}
              </button>
            ))}
            {Object.values(colFilters).some(v=>v&&v.size>0) && (
              <button className="btn btn-ghost btn-xs" style={{marginLeft:4}} onClick={()=>setColFilters({})}>
                <X size={11}/> Clear col filters
              </button>
            )}
            <span style={{flex:1}}/>
            {colsResized && (
              <button className="btn btn-ghost btn-xs"
                onClick={()=>{setColWidths(DEFAULT_WIDTHS);setColsResized(false)}}
                title="Reset all column widths to default"
                style={{padding:'3px 8px',fontSize:'.70rem',color:'var(--text-3)',
                  border:'1px solid var(--border)',borderRadius:'var(--r-sm)'}}>
                ⊞ Reset cols
              </button>
            )}
            <span style={{flex:1}}/>
            <span style={{marginLeft:'auto',fontSize:'.72rem',color:'var(--text-3)'}}>
              {filtered.length} row{filtered.length!==1?'s':''}
              {Object.values(userChecked).filter(Boolean).length > 0 &&
                <span style={{marginLeft:6,color:'#22c55e',fontWeight:600}}>
                  · ✅ {Object.values(userChecked).filter(Boolean).length} reviewed
                </span>}
            </span>
          </div>

        </div>}
      </div>



      {/* Add Row panel */}
      {showAdd && (
        <div className="card card-flat" style={{marginBottom:12,background:'var(--surface-2)'}}>
          <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:12}}>
            <h4>Add Transaction</h4>
            <button className="btn btn-ghost btn-icon btn-xs" onClick={()=>setShowAdd(false)} style={{marginLeft:'auto'}}><X size={14}/></button>
          </div>
          <div style={{display:'grid',gridTemplateColumns:'repeat(6,1fr)',gap:10}}>
            <div className="input-group"><label>Date</label><input className="input" type="date" value={newRow.date} onChange={e=>setNewRow(r=>({...r,date:e.target.value}))}/></div>
            <div className="input-group"><label>Bank</label><input className="input" value={newRow.bank} onChange={e=>setNewRow(r=>({...r,bank:e.target.value}))}/></div>
            <div className="input-group"><label>Account</label><input className="input" value={newRow.account} onChange={e=>setNewRow(r=>({...r,account:e.target.value}))}/></div>
            <div className="input-group" style={{gridColumn:'span 2'}}><label>Description</label><input className="input" value={newRow.description} onChange={e=>setNewRow(r=>({...r,description:e.target.value}))}/></div>
            <div className="input-group"><label>Debit</label><input className="input" type="number" min="0" step="0.01" value={newRow.debit} onChange={e=>setNewRow(r=>({...r,debit:parseFloat(e.target.value)||0}))}/></div>
            <div className="input-group"><label>Credit</label><input className="input" type="number" min="0" step="0.01" value={newRow.credit} onChange={e=>setNewRow(r=>({...r,credit:parseFloat(e.target.value)||0}))}/></div>
            <div className="input-group"><label>GL Account</label>
              <select className="input" value={newRow.gl_account} onChange={e=>setNewRow(r=>({...r,gl_account:e.target.value}))}>
                <option value="">— Select GL Account —</option>
                {glByType.map(([type, names]) => (
                  <optgroup key={type} label={type}>
                    {names.map(o=><option key={o} value={o}>{o}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
            <div className="input-group"><label>GST Category</label><select className="input" value={newRow.gst_category} onChange={e=>setNewRow(r=>({...r,gst_category:e.target.value}))}>{GST_CATS.map(o=><option key={o}>{o}</option>)}</select></div>
            <div className="input-group"><label>Who</label><input className="input" value={newRow.who} onChange={e=>setNewRow(r=>({...r,who:e.target.value}))}/></div>
          </div>
          <div style={{display:'flex',gap:8,marginTop:12}}>
            <button className="btn btn-primary btn-sm" onClick={addRow}><Check size={13}/> Add</button>
            <button className="btn btn-ghost btn-sm" onClick={()=>setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* ── Column filter portal — rendered HERE, outside all scroll containers ── */}
      {activeFilter && (
        <ColFilter
          col={activeFilter.field}
          values={colVals(activeFilter.field)}
          active={colFilters[activeFilter.field] || new Set()}
          onChange={v => {
            setColFilters(f => ({...f, [activeFilter.field]: v}))
            closeFilter()
          }}
          onClose={closeFilter}
          anchorPos={activeFilter.anchorPos}
        />
      )}

      {/* Data Table with sort + filter headers + inline editing */}
      <div className="data-table-wrap" style={{width:'100%'}}>
        <div style={{overflowX:'auto',width:'100%'}}>
          <table className="data-table" style={{width:'100%',tableLayout:'fixed'}}>
            <thead>
              <tr>
                <th style={{width:36,paddingLeft:14}}>
                  <input type="checkbox" style={{cursor:'pointer',accentColor:'var(--brand)'}}
                    checked={pageRows.length>0 && pageRows.every(r=>selected.has(r._origIdx))} onChange={toggleAll}/>
                </th>
                <SortTh {...thProps('Date',        'date',           {})}/>
                <SortTh {...thProps('Bank/Account','bank',           {})}/>
                <SortTh {...thProps('Description', 'description',    {})}/>
                <SortTh {...thProps('Debit',       'debit',          {textAlign:'right'})}/>
                <SortTh {...thProps('Credit',      'credit',         {textAlign:'right'})}/>
                <SortTh {...thProps('Balance',     'balance',        {textAlign:'right'})}/>
                <SortTh {...thProps('Pair ID',     'pairid',         {})}/>
                <SortTh {...thProps('GL Account',  'gl_account',     {})}/>
                <SortTh {...thProps('GST',         'gst',            {textAlign:'right'})}/>
                <SortTh {...thProps('GST Cat',     'gst_category',   {})}/>
                <SortTh {...thProps('Who',         'who',            {})}/>
                <th style={{padding:'8px 10px',textAlign:'center',cursor:'default',
                  fontSize:'.72rem',fontWeight:700,whiteSpace:'nowrap',
                  background:'var(--surface-2)',position:'sticky',top:0,zIndex:2}}
                  title="Tick to mark row as reviewed">
                  User<br/>Checked
                </th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((row)=>{
                const ai  = row._origIdx
                const sel = selected.has(ai)
                const cl  = row.classification||''
                const hasRowEdits = !!inlineEdits[ai]

                // Light green background for internal transfers only; no colour for other rows.
                const isInternal = cl.includes('Internal')
                const rowBg = isInternal ? 'rgba(34,197,94,.07)' : undefined

                const rowClass = [
                  isInternal ? 'row-internal' : '',
                  cl.includes('Incoming')?'row-incoming':'',
                  cl.includes('Outgoing')?'row-outgoing':'',
                  sel?'row-selected':'',
                  hasRowEdits?'row-edited':'',
                ].filter(Boolean).join(' ')

                // Helper: get current value (inline edit overrides original)
                const v = (field) => getCell(ai, field, row[field])
                const setV = (field) => (e) => setCell(ai, field, e.target ? e.target.value : e)

                return (
                  <React.Fragment key={ai}>
                  <tr className={rowClass} style={rowBg && !sel ? {backgroundColor: rowBg} : undefined}>
                    <td style={{paddingLeft:14}}>
                      <input type="checkbox" checked={sel} onChange={()=>toggleS(ai)} style={{cursor:'pointer',accentColor:'var(--brand)'}}/>
                    </td>
                    {/* Date */}
                    <td style={{overflow:'hidden'}}>
                      <input className="cell-input" type="text"
                        value={v('date')||''} onChange={setV('date')}
                        title={v('date')||''} placeholder="dd/mm/yyyy"
                        style={{width:'100%',fontFamily:'var(--font-mono)',fontSize:'.78rem'}}/>
                    </td>
                    {/* Bank/Account combined: e.g. Macquarie/CMA1 */}
                    <td style={{overflow:'hidden',whiteSpace:'nowrap'}}>
                      <span style={{fontSize:'.78rem',color:'var(--text-2)',fontWeight:500}}>
                        {v('bank')||''}
                        {(v('account_name')||v('account')) && (
                          <span style={{color:'var(--text-3)',fontWeight:400}}>
                            {'/'}{(v('account_name')||'')+(v('account')||'')}
                          </span>
                        )}
                      </span>
                    </td>
                    {/* Description — full value, truncated display, hover shows full */}
                    <td style={{overflow:'hidden'}}>
                      <div style={{display:'flex',alignItems:'center',gap:4}}>
                        {row.is_loan_payment && (
                          <button
                            onClick={()=>setExpandedLoans(p=>({...p,[ai]:!p[ai]}))}
                            title={expandedLoans[ai] ? 'Collapse loan split' : 'Expand principal/interest split'}
                            style={{
                              flexShrink:0,background:'none',border:'none',cursor:'pointer',
                              color:'var(--brand)',padding:'0 2px',lineHeight:1,fontSize:'.85rem',
                              transition:'transform .15s',
                              transform: expandedLoans[ai] ? 'rotate(90deg)' : 'rotate(0deg)',
                            }}>
                            ▶
                          </button>
                        )}
                        <input className="cell-input" value={v('description')||''} onChange={setV('description')}
                          title={v('description')||''}
                          style={{flex:1,fontSize:'.8rem',overflow:'hidden',
                            textOverflow:'ellipsis',whiteSpace:'nowrap'}}/>
                      </div>
                    </td>
                    {/* Debit */}
                    <td style={{textAlign:'right'}}>
                      <input className="cell-input" type="number" min="0" step="0.01"
                        value={v('debit')||''} onChange={e=>setCell(ai,'debit',parseFloat(e.target.value)||0)}
                        style={{width:90,textAlign:'right',fontFamily:'var(--font-mono)',fontSize:'.8rem',color:'var(--warning)',fontWeight:600}}/>
                    </td>
                    {/* Credit */}
                    <td style={{textAlign:'right'}}>
                      <input className="cell-input" type="number" min="0" step="0.01"
                        value={v('credit')||''} onChange={e=>setCell(ai,'credit',parseFloat(e.target.value)||0)}
                        style={{width:90,textAlign:'right',fontFamily:'var(--font-mono)',fontSize:'.8rem',color:'var(--info)',fontWeight:600}}/>
                    </td>
                    {/* Balance — bank-supplied (preferred) or computed running total */}
                    <td style={{textAlign:'right',paddingRight:10}}>
                      {(() => {
                        // Use real bank balance if available, else computed running total
                        const realBal = row.balance != null && row.balance !== '' ? parseFloat(row.balance) : null
                        const bal = realBal !== null ? realBal : (balanceByOrigIdx ? balanceByOrigIdx[ai] : null)
                        if (bal == null) return null
                        const isNeg = bal < 0
                        return (
                          <span style={{
                            fontFamily:'var(--font-mono)',fontSize:'.8rem',fontWeight:700,
                            color: isNeg ? 'var(--danger,#ef4444)' : 'var(--success,#22c55e)',
                            whiteSpace:'nowrap',
                          }}
                            title={realBal !== null ? 'Bank balance from statement' : 'Computed running balance'}>
                            {isNeg ? '-' : ''}${Math.abs(bal).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2})}
                            {realBal === null && <span style={{fontSize:'.6rem',opacity:.5,marginLeft:2}}>~</span>}
                          </span>
                        )
                      })()}
                    </td>
                    {/* Pair ID */}
                    <td>
                      <input className="cell-input" value={v('pairid')||v('pair_id')||''} onChange={setV('pairid')}
                        style={{width:80,fontFamily:'var(--font-mono)',fontSize:'.72rem',color:'var(--text-3)'}}/>
                    </td>
                    {/* GL Account — grouped by GL Type via <optgroup> */}
                    <td>
                      {isInternal
                        ? <span style={{color:'var(--text-3)',fontSize:'.75rem',padding:'0 4px'}}>—</span>
                        : (<>
                      <select value={v('gl_account')||''} onChange={e=>{setEditedRows(p=>({...p,[ai]:true}));
                          const name = e.target.value
                          const coa  = coaMap[name]
                          const cls  = v('classification') || ''

                          // Warn (don't block) if user manually picks wrong direction GL
                          if (coa && coa.type) {
                            const t = (coa.type || '').toLowerCase()
                            const expenseTypes = ['expense','direct costs','overhead']
                            const incomeTypes  = ['revenue','income','other income','sales']
                            if (cls.includes('Incoming') && expenseTypes.includes(t))
                              toast(`⚠️ "${name}" is an Expense account — Incoming rows usually use Income accounts.`, {icon:'⚠️', duration:4000})
                            if (cls.includes('Outgoing') && incomeTypes.includes(t))
                              toast(`⚠️ "${name}" is an Income account — Outgoing rows usually use Expense accounts.`, {icon:'⚠️', duration:4000})
                          }

                          setCell(ai,'gl_account', name)
                          updateCell(ai,'gl_account', name)
                          if (coa) {
                            setCell(ai,'gl_type', coa.type||'')
                            updateCell(ai,'gl_type', coa.type||'')
                            if (coa.tax_code) {
                              setCell(ai,'gst_category', coa.tax_code)
                              updateCell(ai,'gst_category', coa.tax_code)
                              // FIX 5: recalculate GST amount immediately from new tax code
                              const debit  = parseFloat(v('debit'))  || 0
                              const credit = parseFloat(v('credit')) || 0
                              const tc     = (coa.tax_code || '').toLowerCase()
                              let   gst    = 0
                              if (tc.includes('gst on')) {
                                if (credit > 0) gst = Math.round(credit * 10 / 110 * 100) / 100
                                else if (debit > 0) gst = Math.round(debit * 10 / 110 * 100) / 100
                              }
                              setCell(ai,'gst', gst)
                              updateCell(ai,'gst', gst)
                            }
                          }
                        }}
                        title={v('gl_account')||''} className="select-compact" style={{width:'100%'}}>
                        <option value="">— Select GL Account —</option>
                        {glByType.map(([type, names]) => (
                          <optgroup key={type} label={type}>
                            {names.map(o=><option key={o} value={o}>{o}</option>)}
                          </optgroup>
                        ))}
                      </select>
                      {editedRows[ai] === true && (
                        <div style={{display:'flex',gap:3,marginTop:3}}>
                          <button
                            onClick={async ()=>{
                              const gl   = v('gl_account')||''
                              const gst  = v('gst_category')||''
                              const glTp = v('gl_type')||''
                              const cls  = v('classification')||''
                              const desc = v('description')||''
                              const who  = v('who')||''
                              if(!gl){ toast.error('Set a GL Account first'); return }
                              const dir = cls.includes('Incoming')?'credit_only'
                                        : cls.includes('Outgoing')?'debit_only':''

                              // Keywords: WHO is most reliable; add desc words as fallback
                              const whoKw = who.toLowerCase().trim()
                              const descKws = desc.toLowerCase().split(/[\s\-#*.,]+/)
                                .filter(w=>w.length>4&&!/\d/.test(w)&&!w.includes(':')
                                  &&!['from','with','card','date','value','direct',
                                      'credit','debit','transfer','sydney','melbourne',
                                      'brisbane','perth','adelaide','australia'].includes(w))
                                .slice(0,2)
                              // If WHO is available, use it alone (most precise)
                              // If no WHO, fall back to desc keywords
                              const kws = [...new Set(
                                whoKw ? [whoKw] : descKws
                              )].filter(Boolean)
                              if(!kws.length){ toast.error('Cannot determine keywords'); return }

                              const cond = { contains_any: kws }
                              if(dir==='debit_only')  cond.debit_only  = true
                              if(dir==='credit_only') cond.credit_only = true

                              const rule = { id:`rule_${Date.now()}`,
                                name: who||kws[0]||gl, priority:100,
                                if: cond, then: gl, then_gst_category: gst }

                              // Find all similar transactions immediately
                              const matches = transactions.reduce((acc, row, idx) => {
                                if(idx === ai) return acc
                                const rowWho  = (row.who||'').toLowerCase()
                                const rowDesc = (row.description||'').toLowerCase()
                                const combined = rowDesc + ' ' + rowWho
                                const _rd = parseFloat(row.debit||0)
                                const _rc = parseFloat(row.credit||0)
                                const dirOk = dir===''
                                  || (dir==='debit_only'  && _rd>0 && _rc===0)
                                  || (dir==='credit_only' && _rc>0 && _rd===0)
                                if(dirOk && kws.some(k=>k && combined.includes(k))) {
                                  acc.push({ai:idx, row, newGl:gl, newGst:gst, newGlType:glTp})
                                }
                                return acc
                              }, [])

                              try {
                                await rdrCreate(rule)
                                setEditedRows(p=>({...p,[ai]:'done'}))
                                if(matches.length > 0) {
                                  setRulePreview({rule, matches})
                                } else {
                                  toast.success('Rule saved — no other similar transactions found')
                                }
                              } catch { toast.error('Failed to save rule') }
                            }}
                            className="btn btn-ghost btn-xs"
                            style={{flex:1,fontSize:'.65rem',padding:'1px 4px',
                              color:'var(--brand)',border:'1px dashed var(--brand-light)'}}>
                            + Save Rule
                          </button>
                          <button
                            onClick={()=>setEditedRows(p=>({...p,[ai]:'done'}))}
                            className="btn btn-ghost btn-xs"
                            style={{fontSize:'.65rem',padding:'1px 6px',
                              color:'var(--text-3)',border:'1px solid var(--border)'}}>
                            No
                          </button>
                        </div>
                      )}
                      </>)}
                    </td>
                    {/* GST */}
                    <td style={{textAlign:'right'}}>
                      <input className="cell-input" type="number" min="0" step="0.01"
                        value={v('gst')||''} onChange={e=>setCell(ai,'gst',parseFloat(e.target.value)||0)}
                        style={{width:80,textAlign:'right',fontFamily:'var(--font-mono)',fontSize:'.78rem',color:'var(--brand)'}}/>
                    </td>
                    {/* GST Category — blank for internal transfers */}
                    <td>
                      {(v('classification')||'').includes('Internal')
                        ? <span style={{color:'var(--text-3)',fontSize:'.75rem',padding:'0 4px'}}>—</span>
                        : <select value={v('gst_category')||''} onChange={e=>{ setCell(ai,'gst_category',e.target.value); updateCell(ai,'gst_category',e.target.value) }}
                            className="select-compact" style={{minWidth:142}}>
                            {GST_CATS.map(o=><option key={o}>{o}</option>)}
                          </select>
                      }
                    </td>
                    {/* Who + per-row Cancel button */}
                    <td style={{overflow:'visible',whiteSpace:'nowrap'}}>
                      <div style={{display:'flex',alignItems:'center',gap:4}}>
                      <input className="cell-input" value={v('who')||''} onChange={setV('who')}
                        title={v('who')||''} style={{flex:1,minWidth:80,fontSize:'.78rem',color:'var(--text-2)'}}/>
                      {/* Cancel button — only visible when this row has unsaved edits */}
                      {inlineEdits[ai] && (
                        <button
                          onClick={() => cancelRowEdits(ai)}
                          title="Cancel changes on this row and restore original values"
                          style={{
                            flexShrink:0,
                            background:'none',
                            border:'1px solid var(--danger,#ef4444)',
                            borderRadius:'var(--r-sm,4px)',
                            color:'var(--danger,#ef4444)',
                            cursor:'pointer',
                            fontSize:'.68rem',
                            fontWeight:600,
                            lineHeight:1,
                            padding:'2px 5px',
                            whiteSpace:'nowrap',
                            transition:'background .12s,color .12s',
                          }}
                          onMouseEnter={e=>{e.currentTarget.style.background='var(--danger,#ef4444)';e.currentTarget.style.color='#fff'}}
                          onMouseLeave={e=>{e.currentTarget.style.background='none';e.currentTarget.style.color='var(--danger,#ef4444)'}}
                        >↩ Cancel</button>
                      )}
                      </div>
                    </td>
                    {/* User Checked */}
                    <td style={{textAlign:'center',width:60,padding:'4px 10px 4px 4px',cursor:'pointer',verticalAlign:'middle'}}
                      onClick={()=>setUserChecked(prev=>({...prev,[ai]:!prev[ai]}))}
                      title={userChecked[ai] ? 'Reviewed — click to unmark' : 'Click to mark as reviewed'}>
                      {userChecked[ai]
                        ? <span style={{color:'#22c55e',fontSize:'1.15rem',lineHeight:1}}>✅</span>
                        : <span style={{color:'var(--border)',fontSize:'1rem',lineHeight:1}}>☐</span>}
                    </td>
                  </tr>

                  {/* ── Loan Payment Sub-rows (collapsible) ── */}
                  {row.is_loan_payment && expandedLoans[ai] && (() => {
                    const isDebit   = (parseFloat(row.debit)  || 0) > 0
                    const loanTotal = isDebit ? (parseFloat(row.debit)||0) : (parseFloat(row.credit)||0)
                    const pVal      = parseFloat(v('loan_principal') ?? row.loan_principal ?? 0) || 0
                    const iVal      = parseFloat(v('loan_interest')  ?? row.loan_interest  ?? 0) || 0
                    const amtColor  = isDebit ? 'var(--warning)' : 'var(--info)'

                    const AmtInput = ({field, onAmt}) => (
                      <input type="number" min="0" step="0.01"
                        value={(field==='loan_principal' ? pVal : iVal) || ''}
                        onChange={onAmt}
                        className="cell-input"
                        style={{width:90,textAlign:'right',fontFamily:'var(--font-mono)',
                          fontSize:'.8rem',fontWeight:700,color:amtColor}}
                      />
                    )

                    const onPrincipal = e => {
                      const newP = parseFloat(e.target.value) || 0
                      setCell(ai, 'loan_principal', newP)
                      setCell(ai, 'loan_interest', Math.max(0, parseFloat((loanTotal - newP).toFixed(2))))
                    }
                    const onInterest = e => {
                      const newI = parseFloat(e.target.value) || 0
                      setCell(ai, 'loan_interest', newI)
                      const newP = Math.max(0, parseFloat((loanTotal - newI).toFixed(2)))
                      setCell(ai, 'loan_principal', newP)
                      if (newP > 0) setCell(ai, 'loan_interest_rate', parseFloat(((newI/newP)*12*100).toFixed(2)))
                    }

                    return (
                      <>
                        {/* ── Principal sub-row ── */}
                        <tr style={{background:'var(--surface-2)',borderLeft:'3px solid var(--brand)'}}>
                          <td/>
                          <td/>{/* Date */}
                          <td/>{/* Bank/Account */}
                          <td style={{paddingLeft:32,paddingTop:5,paddingBottom:5,whiteSpace:'nowrap'}}>
                            <span style={{fontSize:'.72rem',fontWeight:700,color:'var(--brand)'}}>Principal Repayment</span>
                          </td>
                          <td style={{textAlign:'right'}}>{isDebit  && <AmtInput field="loan_principal" onAmt={onPrincipal}/>}</td>
                          <td style={{textAlign:'right'}}>{!isDebit && <AmtInput field="loan_principal" onAmt={onPrincipal}/>}</td>
                          <td/>{/* Balance */}
                          <td/>{/* Pair ID */}
                          <td/>{/* GL Account */}
                          <td/>{/* GST */}
                          <td/>{/* GST Cat */}
                          <td/>{/* Who */}
                          <td/>{/* User Checked */}
                        </tr>

                        {/* ── Interest sub-row ── */}
                        <tr style={{background:'var(--surface-2)',borderLeft:'3px solid var(--warning)',borderBottom:'2px solid var(--border)'}}>
                          <td/>
                          <td/>{/* Date */}
                          <td/>{/* Bank/Account */}
                          <td style={{paddingLeft:32,paddingTop:5,paddingBottom:7}}>
                            <div style={{display:'flex',alignItems:'center',gap:6,flexWrap:'nowrap'}}>
                              <span style={{fontSize:'.72rem',fontWeight:700,color:'var(--warning)',whiteSpace:'nowrap'}}>
                                {isDebit ? 'Interest Expense' : 'Interest Earned'}
                              </span>
                              <input type="number" min="0" max="100" step="0.01" placeholder="Rate %"
                                value={v('loan_interest_rate') ?? ''}
                                onChange={e => {
                                  const rate = parseFloat(e.target.value)
                                  setCell(ai, 'loan_interest_rate', isNaN(rate) ? null : rate)
                                  if (!isNaN(rate) && rate > 0 && loanTotal > 0) {
                                    const r    = rate / 100 / 12
                                    const newP = parseFloat((loanTotal / (1 + r)).toFixed(2))
                                    const newI = parseFloat((loanTotal - newP).toFixed(2))
                                    setCell(ai, 'loan_principal', Math.max(0, newP))
                                    setCell(ai, 'loan_interest',  Math.max(0, newI))
                                  }
                                }}
                                className="cell-input"
                                style={{width:58,textAlign:'right',fontFamily:'var(--font-mono)',fontSize:'.75rem',color:'var(--info)'}}
                              />
                              <span style={{fontSize:'.70rem',color:'var(--text-3)',whiteSpace:'nowrap'}}>% p.a.</span>
                            </div>
                          </td>
                          <td style={{textAlign:'right'}}>{isDebit  && <AmtInput field="loan_interest" onAmt={onInterest}/>}</td>
                          <td style={{textAlign:'right'}}>{!isDebit && <AmtInput field="loan_interest" onAmt={onInterest}/>}</td>
                          <td/>{/* Balance */}
                          <td/>{/* Pair ID */}
                          <td/>{/* GL Account */}
                          <td style={{paddingLeft:4}}>
                            {(() => {
                              const diff = Math.abs(loanTotal - pVal - iVal)
                              return diff > 0.01
                                ? <span style={{fontSize:'.65rem',color:'var(--danger)',fontWeight:600}}>⚠ ${diff.toFixed(2)} off</span>
                                : <span style={{fontSize:'.65rem',color:'var(--success)'}}>✓ balanced</span>
                            })()}
                          </td>
                          <td/>{/* GST Cat */}
                          <td/>{/* Who */}
                          <td/>{/* User Checked */}
                        </tr>
                      </>
                    )
                  })()}
                  </React.Fragment>
                )
              })}
              {pageRows.length===0&&(
                <tr><td colSpan={16}>
                  <div className="empty-state" style={{padding:'32px 24px'}}>
                    <p>No transactions match the current filters.</p>
                  </div>
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
        {/* Pagination */}
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'10px 16px',borderTop:'1px solid var(--border)',background:'var(--surface-2)'}}>
          <span style={{fontSize:'.78rem',color:'var(--text-3)'}}>
            <strong style={{color:'var(--text-1)'}}>{filtered.length}</strong> transaction{filtered.length!==1?'s':''}
            {' · '}Page <strong style={{color:'var(--text-1)'}}>{safePage}</strong> of {totalPages}
            {hasEdits && <span style={{marginLeft:8,color:'var(--warning)',fontWeight:600}}>· {Object.keys(inlineEdits).length} unsaved edit{Object.keys(inlineEdits).length!==1?'s':''}</span>}
          </span>
          <div className="pagination">
            <button className="page-btn" disabled={safePage<=1} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={14}/></button>
            {(()=>{
              const WINDOW = 9
              let start = Math.max(1, safePage - Math.floor(WINDOW/2))
              let end   = Math.min(totalPages, start + WINDOW - 1)
              start = Math.max(1, end - WINDOW + 1)
              const pages = []
              if (start > 1) pages.push(<button key="first" className="page-btn" onClick={()=>setPage(1)}>1</button>, <span key="el1" style={{padding:'0 2px',color:'var(--text-3)'}}>…</span>)
              for (let p = start; p <= end; p++)
                pages.push(<button key={p} onClick={()=>setPage(p)} className={`page-btn${p===safePage?' active':''}`}>{p}</button>)
              if (end < totalPages) pages.push(<span key="el2" style={{padding:'0 2px',color:'var(--text-3)'}}>…</span>, <button key="last" className="page-btn" onClick={()=>setPage(totalPages)}>{totalPages}</button>)
              return pages
            })()}
            <button className="page-btn" disabled={safePage>=totalPages} onClick={()=>setPage(p=>p+1)}><ChevronRight size={14}/></button>
          </div>
        </div>
      </div>
    </div>
  )
}