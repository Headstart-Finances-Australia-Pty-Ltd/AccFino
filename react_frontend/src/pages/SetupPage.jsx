import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { BookOpen, Plus, Pencil, Trash2, Check, X, Upload, Save, Download, ArrowUp, ArrowDown, ArrowUpDown, Zap } from 'lucide-react'
import { parseCSVText, toCSV, downloadCSV } from '../lib/csvUtils.js'
import { rdrList, rdrCreate, rdrUpdate, rdrDelete, coaAccounts, kbGet, kbVendorUpsert, kbVendorDelete, kbKeywordUpsert, kbKeywordDelete, companyList, companyUpdate, companyCreate, companyDelete, companyAddAlias } from '../lib/api.js'
import { useAuth } from '../hooks/useAuth.jsx'
import toast from 'react-hot-toast'

// - CsvBar: reusable upload/download button pair -----------------------
function CsvBar({ onUpload, onDownload, label='CSV' }) {
  const ref = React.useRef(null)
  return (
    <div style={{display:'flex',gap:6,paddingTop:10,borderTop:'1px solid var(--border)',marginTop:10}}>
      <input ref={ref} type="file" accept=".csv" style={{display:'none'}}
        onChange={e=>{if(e.target.files[0])onUpload(e.target.files[0]);e.target.value=''}}/>
      <button className="btn btn-outline btn-sm" style={{flex:1}} onClick={()=>ref.current.click()}>
        <Upload size={12}/> Upload {label}
      </button>
      <button className="btn btn-outline btn-sm" style={{flex:1}} onClick={onDownload}>
        <Download size={12}/> Download {label}
      </button>
    </div>
  )
}

// - Column filter popover (same pattern as OutputPanel) -------
function ColFilter({ values, active, onChange, onClose, anchorPos }) {
  const unique   = useMemo(() => [...new Set(values.map(v=>String(v||'')))].sort(), [values])
  const [selected, setSelected] = useState(() => active.size > 0 ? new Set(active) : new Set(unique))
  const hasSelection = selected.size > 0 && selected.size < unique.length
  const toggle = v => setSelected(s => { const n=new Set(s); n.has(v)?n.delete(v):n.add(v); return n })
  const apply  = () => { onChange(selected.size===unique.length ? new Set() : new Set(selected)); onClose() }
  const pos = anchorPos || {top:0,left:0,maxH:340}
  const popoverRef = useRef(null)

  useEffect(()=>{
    const h = e => { if(popoverRef.current && !popoverRef.current.contains(e.target)) onClose() }
    document.addEventListener('mousedown', h)
    return ()=>document.removeEventListener('mousedown', h)
  },[onClose])

  return createPortal(
    <div ref={popoverRef} data-colfilter-popover onClick={e=>e.stopPropagation()} style={{
      position:'fixed',top:pos.top,left:pos.left,zIndex:99999,
      background:'var(--surface)',border:'1px solid var(--border)',
      borderRadius:'var(--r-md)',boxShadow:'var(--sh-lg)',
      padding:'10px',minWidth:180,maxHeight:pos.maxH,display:'flex',flexDirection:'column',gap:6,
    }}>
      <div style={{display:'flex',gap:6,alignItems:'center'}}>
        <button className="btn btn-ghost btn-xs"
          style={{fontWeight:selected.size===unique.length?700:400,color:selected.size===unique.length?'var(--brand)':undefined}}
          onClick={()=>setSelected(new Set(unique))}>All</button>
        <button className="btn btn-ghost btn-xs"
          style={{fontWeight:selected.size===0?700:400}}
          onClick={()=>setSelected(new Set())}>None</button>
        {hasSelection && <span style={{fontSize:'.72rem',color:'var(--warning)',marginLeft:'auto'}}>{selected.size} selected</span>}
      </div>
      <div style={{borderTop:'1px solid var(--border)',margin:'0 -4px'}}/>
      <div style={{overflowY:'auto',flex:1,display:'flex',flexDirection:'column',gap:1}}>
        {(()=>{
          const sel   = unique.filter(v=> selected.has(v)).sort()
          const unsel = unique.filter(v=>!selected.has(v)).sort()
          const row = v => (
            <label key={v} style={{display:'flex',alignItems:'center',gap:6,cursor:'pointer',
              fontSize:'.78rem',padding:'3px 6px',borderRadius:4,
              background:selected.has(v)?'var(--brand-xlight)':'transparent',transition:'background .1s'}}>
              <input type="checkbox" checked={selected.has(v)} onChange={()=>toggle(v)}
                style={{accentColor:'var(--brand)',flexShrink:0}}/>
              <span style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',flex:1}}>{v||'(blank)'}</span>
            </label>
          )
          return <>{sel.map(row)}
            {sel.length>0&&unsel.length>0&&<div style={{borderTop:'1px dashed var(--border)',margin:'3px 0',fontSize:'.68rem',color:'var(--text-3)',paddingLeft:4}}>- unselected -</div>}
            {unsel.map(row)}</>
        })()}
      </div>
      <button className="btn btn-primary btn-xs" onClick={apply}>Apply{hasSelection?` (${selected.size})`:' (all)'}</button>
    </div>,
    document.body
  )
}

// - Resizable sortable/filterable header cell -----------
function CoaTh({ label, field, sort, setSort, colFilters, setColFilters, values, colWidth, onResize }) {
  const [open, setOpen]         = useState(false)
  const [anchorPos, setAnchorPos] = useState({top:0,left:0,maxH:340})
  const thRef    = useRef(null)
  const isAsc    = sort.field===field && sort.dir==='asc'
  const isDesc   = sort.field===field && sort.dir==='desc'
  const hasFilter = colFilters[field] && colFilters[field].size > 0

  useEffect(()=>{
    if(!open) return
    const h = e => {
      if(thRef.current && !thRef.current.contains(e.target)) {
        // Don't close if the click is inside the portaled popover (handled by ColFilter's own listener)
        const isPopoverClick = e.target.closest && e.target.closest('[data-colfilter-popover]')
        if(!isPopoverClick) setOpen(false)
      }
    }
    document.addEventListener('mousedown',h)

    const reposition = () => {
      if(!thRef.current) return
      const r = thRef.current.getBoundingClientRect(), vh = window.innerHeight
      setAnchorPos({top:r.bottom+4, left:Math.min(r.left, window.innerWidth-200), maxH:Math.max(120, vh-r.bottom-20)})
    }
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)

    return ()=>{
      document.removeEventListener('mousedown',h)
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  },[open])

  const openFilter = e => {
    e.stopPropagation()
    if(!thRef.current){setOpen(o=>!o);return}
    const r=thRef.current.getBoundingClientRect(), vh=window.innerHeight
    setAnchorPos({top:r.bottom+4,left:Math.min(r.left,window.innerWidth-200),maxH:Math.max(120,vh-r.bottom-20)})
    setOpen(o=>!o)
  }

  const startResize = e => {
    e.preventDefault(); e.stopPropagation()
    const startX = e.clientX
    const startW = thRef.current ? thRef.current.getBoundingClientRect().width : (colWidth||100)
    const onMove = mv => { if(onResize) onResize(Math.max(40, startW+mv.clientX-startX)) }
    const onUp   = ()  => { document.removeEventListener('mousemove',onMove); document.removeEventListener('mouseup',onUp) }
    document.addEventListener('mousemove',onMove)
    document.addEventListener('mouseup',onUp)
  }

  return (
    <th ref={thRef} style={{position:'relative',userSelect:'none',whiteSpace:'nowrap',
      ...(colWidth?{width:colWidth,minWidth:colWidth}:{})}}>
      <div style={{display:'inline-flex',alignItems:'center',gap:4,width:'100%'}}>
        <span style={{fontSize:'.82rem',fontWeight:600,cursor:'pointer'}}
          onClick={()=>setSort(s=>s.field===field?{field,dir:s.dir==='asc'?'desc':'asc'}:{field,dir:'asc'})}>
          {label}
        </span>
        <span style={{cursor:'pointer',display:'inline-flex',alignItems:'center'}}
          onClick={()=>setSort(s=>s.field===field?{field,dir:s.dir==='asc'?'desc':'asc'}:{field,dir:'asc'})}>
          {isAsc?<ArrowUp size={13} color="var(--brand)"/>:isDesc?<ArrowDown size={13} color="var(--brand)"/>:<ArrowUpDown size={13} color="var(--text-3)" opacity={0.4}/>}
        </span>
        <span onClick={openFilter} style={{cursor:'pointer',fontSize:'18px',lineHeight:1,padding:'0 2px',
          color:hasFilter?'var(--warning)':'var(--text-3)',fontWeight:hasFilter?700:400}}>-</span>
      </div>
      {open && values && (
        <ColFilter values={values} active={colFilters[field]||new Set()}
          onChange={v=>setColFilters(f=>({...f,[field]:v}))}
          onClose={()=>setOpen(false)} anchorPos={anchorPos}/>
      )}
      <div onMouseDown={startResize}
        style={{position:'absolute',right:0,top:0,bottom:0,width:5,cursor:'col-resize',
          borderRight:'2px solid transparent',transition:'border-color .15s'}}
        onMouseEnter={e=>e.currentTarget.style.borderRightColor='var(--brand)'}
        onMouseLeave={e=>e.currentTarget.style.borderRightColor='transparent'}/>
    </th>
  )
}

// - Chart of Accounts tab -----------------
function CoaTab() {
  const [rows,       setRows]      = useState([])
  const [loading,    setLoading]   = useState(true)
  const [saving,     setSaving]    = useState(false)
  const [editIdx,    setEditIdx]   = useState(null)
  const [editRow,    setEditRow]   = useState(null)
  const [showAdd,    setShowAdd]   = useState(false)
  const [newRow,     setNewRow]    = useState({Code:'',Name:'',Type:'',TaxCode:'',Description:'',Dashboard:''})
  const [sort,       setSort]      = useState({field:null,dir:'asc'})
  const [colFilters, setColFilters]= useState({})
  const [search,     setSearch]    = useState('')
  const fileRef = useRef()

  const COLS   = ['Code','Name','Type','TaxCode','Description','Dashboard']
  const LABELS = {Code:'Code',Name:'Account Name',Type:'Type',TaxCode:'Tax Code',Description:'Description',Dashboard:'Dashboard'}
  const DEFAULT_WIDTHS = {Code:70,Name:200,Type:110,TaxCode:150,Description:320,Dashboard:100}
  const [colWidths, setColWidths] = useState(DEFAULT_WIDTHS)
  const [loadError, setLoadError] = useState('')

  useEffect(()=>{
    let alive=true
    fetch('/api/gl/accounts/all').then(r=>{
      if(!r.ok) throw new Error('HTTP '+r.status)
      return r.json()
    }).then(d=>{
      if(!alive) return
      const arr = Array.isArray(d)?d:(d.rows||[])
      setRows(arr.length ? arr.map((r,i)=>({id:i,
        Code:r.Code||'', Name:r.Name||r.name||'',
        Type:r.Type||r.type||'', TaxCode:r.TaxCode||r.tax_code||r['Tax Code']||'',
        Description:r.Description||'', Dashboard:r.Dashboard||''})) : [])
    }).catch(e=>{ if(alive){ console.error('[CoaTab] load failed:',e?.message||e); setLoadError('Could not load Chart of Accounts: '+(e?.message||'server unreachable')) } })
     .finally(()=>{ if(alive) setLoading(false) })
    return ()=>{ alive=false }
  },[])

  const parseCSV = text => {
    const result=[]; const lines=text.replace(/\r/g,'').split('\n')
    for(const line of lines){
      if(!line.trim()) continue
      const cols=[]; let cur=''; let inQ=false
      for(let i=0;i<line.length;i++){
        const ch=line[i]
        if(ch==='"'){if(inQ&&line[i+1]==='"'){cur+='"';i++}else inQ=!inQ}
        else if(ch===','&&!inQ){cols.push(cur);cur=''}
        else cur+=ch
      }
      cols.push(cur); result.push(cols.map(v=>v.trim()))
    }
    return result
  }

  const handleUpload = async e => {
    const file=e.target.files[0]; if(!file) return
    const allRows=parseCSV(await file.text())
    if(allRows.length<2){toast.error('CSV appears empty');return}
    const header=allRows[0].map(h=>h.replace(/^\*/,'').trim())
    const parsed=allRows.slice(1).map((vals,i)=>{
      const obj={}; header.forEach((h,j)=>{obj[h]=vals[j]||''})
      const name=obj.Name||obj['*Name']||''; if(!name) return null
      return {id:i,Code:obj.Code||obj['*Code']||'',Name:name,
        Type:obj.Type||obj['*Type']||'',TaxCode:obj['Tax Code']||obj['*Tax Code']||obj.TaxCode||'',
        Description:obj.Description||'',Dashboard:obj.Dashboard||''}
    }).filter(Boolean)
    setRows(parsed); toast.success(`Loaded ${parsed.length} accounts from CSV`)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const q=v=>`"${(v||'').replace(/"/g,'""')}"`
      const csv=['*Code,*Name,*Type,*Tax Code,Description,Dashboard',
        ...rows.map(r=>[q(r.Code),q(r.Name),q(r.Type),q(r.TaxCode),q(r.Description),q(r.Dashboard)].join(','))
      ].join('\\n')
      const fd=new FormData()
      fd.append('file',new Blob([csv],{type:'text/csv'}),'ChartOfAccounts.csv')
      const resp=await fetch('/api/gl/accounts/upload',{method:'POST',body:fd})
      if(!resp.ok) throw new Error(await resp.text())
      const result=await resp.json()
      toast.success(result.message||`Saved ${rows.length} accounts`)
    } catch(e){ toast.error(`Save failed: ${e.message}`) }
    finally { setSaving(false) }
  }

  const handleDownload = () => {
    const q=v=>`"${(v||'').replace(/"/g,'""')}"`
    const csv=['*Code,*Name,*Type,*Tax Code,Description,Dashboard',
      ...rows.map(r=>[q(r.Code),q(r.Name),q(r.Type),q(r.TaxCode),q(r.Description),q(r.Dashboard)].join(','))
    ].join('\n')
    const a=document.createElement('a')
    a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}))
    a.download='ChartOfAccounts.csv'; a.click()
  }

  const startEdit = (row,i)=>{ setEditIdx(i); setEditRow({...row}) }
  const saveEdit  = ()=>{ if(!editRow?.Name?.trim()){toast.error('Name required');return} setRows(r=>r.map((x,i)=>i===editIdx?editRow:x)); setEditIdx(null); setEditRow(null); toast.success('Updated - click Save & Apply') }
  const deleteRow = i => setRows(r=>r.filter((_,j)=>j!==i))
  const addRow    = ()=>{ if(!newRow.Name.trim()){toast.error('Name required');return} setRows(r=>[...r,{...newRow,id:Date.now()}]); setNewRow({Code:'',Name:'',Type:'',TaxCode:'',Description:'',Dashboard:''}); toast.success('Added - click Save & Apply') }

  // All unique values per column (for filter dropdowns)
  const colVals = useCallback(field => rows.map(r=>String(r[field]||'')), [rows])

  // Filtered + sorted rows
  const displayed = useMemo(()=>{
    let r = rows
    // Search
    if(search.trim()){
      const q=search.toLowerCase()
      r=r.filter(row=>COLS.some(k=>String(row[k]||'').toLowerCase().includes(q)))
    }
    // Column filters
    for(const[field,included] of Object.entries(colFilters)){
      if(included&&included.size>0) r=r.filter(row=>included.has(String(row[field]||'')))
    }
    // Sort
    if(sort.field){
      r=[...r].sort((a,b)=>{
        const av=String(a[sort.field]||'').toLowerCase()
        const bv=String(b[sort.field]||'').toLowerCase()
        if(av<bv) return sort.dir==='asc'?-1:1
        if(av>bv) return sort.dir==='asc'?1:-1
        return 0
      })
    }
    return r
  },[rows,search,colFilters,sort])

  const thProps = field => ({
    field, sort, setSort, colFilters, setColFilters,
    values:   colVals(field),
    colWidth: colWidths[field],
    onResize: w => setColWidths(p=>({...p,[field]:w})),
  })

  return (
    <>
    {loadError && (
      <div style={{background:'var(--danger-bg,#fef2f2)',border:'1px solid var(--danger,#dc2626)',
        borderRadius:'var(--r-md)',padding:'10px 14px',marginBottom:12,
        color:'var(--danger,#dc2626)',fontSize:'.85rem'}}>
        ⚠ {loadError} — check that the API server is running and reachable.
      </div>
    )}
    <div style={{display:'grid',gridTemplateColumns:'320px 1fr',gap:16,
      height:'calc(100vh - 140px)',minHeight:500,alignItems:'start',overflow:'hidden'}}>

      {/* - Left: form - */}
      <div style={{background:'var(--surface-2)',borderRadius:'var(--r-md)',
        padding:'16px 18px',border:'1px solid var(--border)',
        position:'sticky',top:0,overflowY:'auto',maxHeight:'calc(100vh - 160px)'}}>
        <div style={{display:'flex',alignItems:'center',marginBottom:12}}>
          <h3 style={{margin:0,fontSize:'.95rem',flex:1}}>
            {editIdx!==null
              ? 'Edit: '+(editRow?.Name||'Account')
              : 'New Account'}
          </h3>
          {editIdx!==null && (
            <button className="btn btn-ghost btn-sm"
              style={{fontSize:'.75rem',padding:'2px 8px'}}
              onClick={()=>{setEditIdx(null);setEditRow(null)}}>
              <Plus size={12}/> New
            </button>
          )}
        </div>
        <div style={{display:'flex',flexDirection:'column',gap:8}}>
          {COLS.map(k=>(
            <div key={k} className="input-group">
              <label>{LABELS[k]}</label>
              <input className="input input-sm"
                value={editIdx!==null ? (editRow?.[k]||'') : (newRow[k]||'')}
                onChange={e=> editIdx!==null
                  ? setEditRow(r=>({...r,[k]:e.target.value}))
                  : setNewRow(r=>({...r,[k]:e.target.value}))}
                placeholder={LABELS[k]}/>
            </div>
          ))}
          <div style={{display:'flex',gap:6,marginTop:2}}>
            {editIdx!==null ? (
              <button className="btn btn-primary btn-sm" onClick={saveEdit} style={{flex:1}}>
                <Check size={13}/> Update
              </button>
            ) : (
              <button className="btn btn-primary btn-sm" onClick={addRow} style={{flex:1}}>
                <Plus size={13}/> Add Account
              </button>
            )}
          </div>
        </div>
        <div style={{marginTop:10,display:'flex',flexDirection:'column',gap:6}}>
          <CsvBar label="COA"
            onUpload={async file=>{
              const text=await file.text()
              const allRows=parseCSVText(text)
              if(allRows.length<2){toast.error('CSV appears empty');return}
              const header=allRows[0].map(h=>h.replace(/[*]/g,'').trim())
              const parsed=allRows.slice(1).map((vals,i)=>{
                const obj={}; header.forEach((h,j)=>{obj[h]=vals[j]||''})
                const name=obj.Name||obj['*Name']||''; if(!name) return null
                return {id:i,Code:obj.Code||obj['*Code']||'',Name:name,
                  Type:obj.Type||obj['*Type']||'',TaxCode:obj['Tax Code']||obj['*Tax Code']||obj.TaxCode||'',
                  Description:obj.Description||'',Dashboard:obj.Dashboard||''}
              }).filter(Boolean)
              const seen=new Set(); const deduped=parsed.filter(r=>{
                const k=r.Name.toLowerCase().trim()
                if(seen.has(k)) return false; seen.add(k); return true
              })
              setRows(deduped)
              setSaving(true)
              try{
                const q=v=>'"'+(v||'').split('"').join('""')+'"'
                const csv=['*Code,*Name,*Type,*Tax Code,Description,Dashboard',
                  ...deduped.map(r=>[q(r.Code),q(r.Name),q(r.Type),q(r.TaxCode),q(r.Description),q(r.Dashboard)].join(','))
                ].join(String.fromCharCode(10))
                const fd=new FormData()
                fd.append('file',new Blob([csv],{type:'text/csv'}),'ChartOfAccounts.csv')
                const resp=await fetch('/api/gl/accounts/upload',{method:'POST',body:fd})
                if(!resp.ok) throw new Error(await resp.text())
                toast.success('COA: '+deduped.length+' accounts saved ('+( parsed.length-deduped.length)+' dupes removed)')
              }catch(e){toast.error('Save failed: '+e.message)}
              finally{setSaving(false)}
            }}
            onDownload={handleDownload}
          />
        </div>
      </div>

      {/* - Right: table - */}
      <div style={{display:'flex',flexDirection:'column',
        height:'calc(100vh - 160px)',overflow:'hidden'}}>
      {/* Toolbar */}
      <div style={{display:'flex',gap:8,marginBottom:10,flexWrap:'wrap',alignItems:'center'}}>
        <div className="search-wrap" style={{flex:1}}>
          <svg className="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
          <input className="input input-sm" style={{width:200,paddingLeft:34}} placeholder="Search accounts-"
            value={search} onChange={e=>setSearch(e.target.value)}/>
        </div>
        <button className="btn btn-ghost btn-xs" onClick={()=>setColWidths(DEFAULT_WIDTHS)} title="Reset column widths">- Reset cols</button>
        {Object.values(colFilters).some(v=>v&&v.size>0) && (
          <button className="btn btn-ghost btn-xs" onClick={()=>setColFilters({})} style={{color:'var(--warning)'}}>
            <X size={11}/> Clear filters
          </button>
        )}
        <div style={{flex:1}}/>
        <span style={{fontSize:'.78rem',color:'var(--text-3)'}}>{displayed.length}/{rows.length} accounts</span>
      </div>

      {/* Table */}
      <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-md)',
        flex:1,display:'flex',flexDirection:'column',overflow:'hidden'}}>
        <div style={{overflowX:'auto',overflowY:'auto',flex:1}}>
          <table className="data-table" style={{minWidth:'100%',tableLayout:'fixed'}}>
            <thead>
              <tr>
                {COLS.map(k=>(
                  <CoaTh key={k} label={LABELS[k]} {...thProps(k)}/>
                ))}
                <th style={{width:72,whiteSpace:'nowrap'}}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={7} style={{textAlign:'center',padding:32,color:'var(--text-3)'}}>Loading-</td></tr>
              )}
              {!loading && displayed.length===0 && (
                <tr><td colSpan={7} style={{textAlign:'center',padding:32,color:'var(--text-3)'}}>
                  {rows.length===0 ? 'No accounts. Upload a CSV or add manually.' : 'No accounts match the current filters.'}
                </td></tr>
              )}
              {!loading && displayed.map((row,di)=>{
                const i = rows.indexOf(row)
                return (
                  <tr key={row.id??di} style={{cursor:'pointer',
                    background:editIdx===i?'var(--brand-bg,#eff6ff)':undefined}}
                    onClick={()=>startEdit(row,i)}>
                    {COLS.map(k=>(
                      <td key={k} title={row[k]} style={{overflow:'hidden'}}>
                        <span style={{display:'block',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                          {row[k]||<span style={{color:'var(--text-3)'}}>-</span>}
                        </span>
                      </td>
                    ))}
                    <td onClick={ev=>ev.stopPropagation()}>
                      <button className="btn btn-ghost btn-icon btn-xs"
                        onMouseEnter={e=>e.currentTarget.style.color='var(--danger)'}
                        onMouseLeave={e=>e.currentTarget.style.color=''}
                        onClick={()=>deleteRow(i)}>
                        <Trash2 size={11}/>
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
      </div>
    </div>
    </>
  )
}

// - SetupPage ---------------------
// - Business Rules (RDR) tab ----------------
const DIRECTION_OPTS = [
  { value:'', label:'Any direction' },
  { value:'debit_only', label:'- Outgoing only' },
  { value:'credit_only', label:'- Incoming only' },
]
const GST_OPTS = ['','GST on Expenses','GST on Capital','GST on Income','GST Free Expenses','GST Free Income','BAS Excluded']
const BLANK = { name:'', priority:100, keywords:'', gl:'', gst:'', direction:'' }

function RdrTab() {
  const [rules,    setRules]   = useState([])
  const [glList,   setGlList]  = useState([])
  const [form,     setForm]    = useState(BLANK)
  const [editId,   setEditId]  = useState(null)
  const [saving,   setSaving]  = useState(false)
  const [rdrSearch, setRdrSearch]= useState('')
  const [loadError, setLoadError]= useState('')

  useEffect(()=>{
    let alive=true
    rdrList().then(r=>{ if(alive) setRules(r.data||[]) }).catch(e=>{ if(alive){ console.error('[RdrTab] rdrList failed:',e?.message||e); setLoadError('Could not load rules: '+(e?.message||'server unreachable')) } })
    coaAccounts().then(r=>{ if(alive) setGlList(r.data||[]) }).catch(e=>{ if(alive){ console.error('[RdrTab] coaAccounts failed:',e?.message||e); setLoadError(p=>p||'Could not load GL accounts: '+(e?.message||'server unreachable')) } })
    return ()=>{ alive=false }
  },[])

  const set = k => e => setForm(f=>({...f,[k]:e.target.value}))

  const save = async () => {
    const kws = form.keywords.split(',').map(k=>k.trim().toLowerCase()).filter(Boolean)
    if(!kws.length){ toast.error('Add at least one keyword'); return }
    if(!form.gl && !form.gst){ toast.error('Set GL Account or GST Category'); return }
    const cond = { contains_any: kws }
    if(form.direction==='debit_only')  cond.debit_only  = true
    if(form.direction==='credit_only') cond.credit_only = true
    const rule = { id: editId||`rule_${Date.now()}`, name: form.name||kws[0],
      priority: parseInt(form.priority)||100, if: cond,
      then: form.gl, then_gst_category: form.gst }
    setSaving(true)
    try {
      if(editId) {
        const {data} = await rdrUpdate(editId, rule)
        setRules(r=>r.map(x=>x.id===editId?data:x))
        toast.success('Rule updated')
      } else {
        const {data} = await rdrCreate(rule)
        setRules(r=>[data,...r])
        toast.success('Rule created')
      }
      setForm(BLANK); setEditId(null)
    } catch { toast.error('Save failed') }
    setSaving(false)
  }

  const startEdit = r => {
    const dir = r.if?.debit_only?'debit_only':r.if?.credit_only?'credit_only':''
    setForm({ name:r.name||'', priority:r.priority||100,
      keywords:(r.if?.contains_any||[]).join(', '),
      gl: typeof r.then==='string'?r.then:'',
      gst: r.then_gst_category||'', direction:dir })
    setEditId(r.id)
    window.scrollTo({top:0,behavior:'smooth'})
  }

  const del = async id => {
    if(!confirm('Delete this rule?')) return
    await rdrDelete(id).catch(()=>{})
    setRules(r=>r.filter(x=>x.id!==id))
    toast.success('Deleted')
  }

  return (
    <>
    {loadError && (
      <div style={{background:'var(--danger-bg,#fef2f2)',border:'1px solid var(--danger,#dc2626)',
        borderRadius:'var(--r-md)',padding:'10px 14px',marginBottom:12,
        color:'var(--danger,#dc2626)',fontSize:'.85rem'}}>
        ⚠ {loadError} — check that the API server is running and reachable.
      </div>
    )}
    <div style={{display:'grid',gridTemplateColumns:'300px 1fr',gap:16,alignItems:'start',
      height:'calc(100vh - 220px)',minHeight:500}}>

      {/* Left: Editor - sticky, no scroll */}
      <div style={{background:'var(--surface-2)',borderRadius:'var(--r-md)',
        padding:'16px 18px',border:'1px solid var(--border)',
        position:'sticky',top:0,overflowY:'auto',maxHeight:'calc(100vh - 240px)'}}>
        <div style={{display:'flex',alignItems:'center',marginBottom:14}}>
          <h3 style={{margin:0,fontSize:'.95rem',flex:1}}>
            {editId ? 'Edit: '+(form.name||'Rule') : 'New Rule'}
          </h3>
          {editId && (
            <button className="btn btn-ghost btn-sm"
              style={{fontSize:'.75rem',padding:'2px 8px'}}
              onClick={()=>{setForm(BLANK);setEditId(null)}}>
              <Plus size={12}/> New
            </button>
          )}
        </div>
        <div style={{display:'flex',flexDirection:'column',gap:10}}>
          <div className="input-group">
            <label>Rule Name</label>
            <input className="input input-sm" value={form.name} onChange={set('name')} placeholder="e.g. Uber rides"/>
          </div>
          <div className="input-group">
            <label>Priority <span style={{fontWeight:400,color:'var(--text-3)',fontSize:'.75rem'}}>(higher = first)</span></label>
            <input className="input input-sm" type="number" value={form.priority} onChange={set('priority')}/>
          </div>
          <div className="input-group">
            <label>Keywords <span style={{fontWeight:400,color:'var(--text-3)',fontSize:'.75rem'}}>(comma-separated)</span></label>
            <input className="input input-sm" value={form.keywords} onChange={set('keywords')}
              placeholder="uber, didi, taxi"/>
          </div>
          <div className="input-group">
            <label>GL Account</label>
            <select className="input input-sm" value={form.gl} onChange={set('gl')}>
              <option value="">-- Select --</option>
              {glList.map((g,i)=>{const n=typeof g==='string'?g:String(g?.Name||g?.name||'');return n?(<option key={n} value={n}>{n}</option>):null})}
            </select>
          </div>
          <div className="input-group">
            <label>GST Category</label>
            <select className="input input-sm" value={form.gst} onChange={set('gst')}>
              {GST_OPTS.map(g=><option key={g} value={g}>{g||'-- Auto --'}</option>)}
            </select>
          </div>
          <div className="input-group">
            <label>Direction</label>
            <select className="input input-sm" value={form.direction} onChange={set('direction')}>
              {DIRECTION_OPTS.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div style={{display:'flex',gap:6}}>
            <button className="btn btn-primary btn-sm" onClick={save} disabled={saving} style={{flex:1}}>
              <Check size={13}/> {saving?'Saving...':(editId?'Update':'Save Rule')}
            </button>

          </div>
          <CsvBar label="Rules"
            onUpload={async file=>{
              const rows=parseCSVText(await file.text())
              if(rows.length<2){toast.error('Empty CSV');return}
              const hdr=rows[0].map(h=>h.trim().toLowerCase())
              const parsed=rows.slice(1).map(vals=>{
                const o={}; hdr.forEach((h,i)=>o[h]=vals[i]||'')
                if(!o.name&&!o.id) return null
                const kws=(o.keywords||o.contains_any||'').split('|').map(k=>k.trim()).filter(Boolean)
                return {id:o.id||('rule_'+Date.now()+'_'+Math.random().toString(36).slice(2,8)),
                  name:o.name||'', priority:parseInt(o.priority)||100,
                  if:{contains_any:kws,
                    ...(o.direction==='debit_only'?{debit_only:true}:{}),
                    ...(o.direction==='credit_only'?{credit_only:true}:{})},
                  then:o.gl||o.then||'', then_gst_category:o.gst||o.then_gst_category||''}
              }).filter(Boolean)
              const merged=[...rules]; let added=0,updated=0
              parsed.forEach(r=>{
                const idx=merged.findIndex(x=>x.id===r.id||x.name.toLowerCase()===r.name.toLowerCase())
                if(idx>=0){merged[idx]=r;updated++}else{merged.push(r);added++}
              })
              merged.sort((a,b)=>(b.priority||0)-(a.priority||0))
              for(const r of merged){ try{await rdrCreate(r)}catch{try{await rdrUpdate(r.id,r)}catch{}} }
              setRules(merged); toast.success('Rules: '+added+' added, '+updated+' updated')
            }}
            onDownload={()=>downloadCSV('business_rules.csv',toCSV(
              rules.map(r=>({id:r.id,name:r.name,priority:r.priority||100,
                keywords:(r.if?.contains_any||[]).join('|'),gl:r.then||'',
                gst:r.then_gst_category||'',
                direction:r.if?.debit_only?'debit_only':r.if?.credit_only?'credit_only':''})),
              ['id','name','priority','keywords','gl','gst','direction']))}
          />
        </div>
      </div>

      {/* Right: Rules list - scrollable */}
      <div style={{borderRadius:'var(--r-md)',border:'1px solid var(--border)',
        overflow:'hidden',display:'flex',flexDirection:'column',
        maxHeight:'calc(100vh - 240px)'}}>
        <div style={{padding:'10px 16px',borderBottom:'1px solid var(--border)',
          display:'flex',alignItems:'center',gap:10,background:'var(--surface-2)',flexWrap:'wrap'}}>
          <Zap size={14} color="var(--brand)"/>
          <span style={{fontWeight:700,fontSize:'.9rem'}}>Active Rules</span>
          <span style={{background:'var(--surface-3)',borderRadius:100,padding:'1px 8px',
            fontSize:'.72rem',fontWeight:700}}>{rules.length}</span>
          <input className="input input-sm" placeholder="Search rules..."
            value={rdrSearch} onChange={e=>setRdrSearch(e.target.value)}
            style={{marginLeft:'auto',width:200}}/>
        </div>
        {rules.length===0
          ? <div style={{padding:32,textAlign:'center',color:'var(--text-3)',fontSize:'.85rem'}}>
              No rules yet. Create one above, or edit a GL Account in Reconciliation to auto-create.
            </div>
          : <div style={{overflowY:'auto',flex:1}}>
            <table className="data-table" style={{width:'100%'}}>
              <thead>
                <tr>
                  <th style={{width:50}}>Pri.</th>
                  <th>Name</th>
                  <th>Keywords</th>
                  <th style={{width:60}}>Dir.</th>
                  <th>GL Account</th>
                  <th>GST</th>
                  <th style={{width:70}}></th>
                </tr>
              </thead>
              <tbody>
                {[...rules].filter(r=>!rdrSearch||(r.name||'').toLowerCase().includes(rdrSearch.toLowerCase())||(r.if?.contains_any||[]).some(k=>String(k||'').toLowerCase().includes(rdrSearch.toLowerCase()))).sort((a,b)=>(b.priority||0)-(a.priority||0)).map(r=>(
                  <tr key={r.id} style={{cursor:'pointer'}} onClick={()=>startEdit(r)}>
                    <td style={{fontFamily:'var(--font-mono)',fontWeight:700,fontSize:'.8rem'}}>{r.priority||0}</td>
                    <td style={{fontWeight:600,fontSize:'.85rem'}}>{r.name||r.id}</td>
                    <td style={{fontSize:'.75rem',color:'var(--text-2)'}}>
                      {(r.if?.contains_any||[]).slice(0,5).join(', ')}{(r.if?.contains_any||[]).length>5?'...':''}
                    </td>
                    <td style={{fontSize:'.78rem'}}>
                      {r.if?.debit_only?'- Out':r.if?.credit_only?'- In':'-'}
                    </td>
                    <td><span className="badge badge-neutral" style={{fontSize:'.75rem'}}>{r.then||'-'}</span></td>
                    <td style={{fontSize:'.72rem',color:'var(--text-3)'}}>{r.then_gst_category||'-'}</td>
                    <td onClick={ev=>ev.stopPropagation()}>
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={()=>del(r.id)} title="Delete"
                        style={{color:'var(--text-3)'}}
                        onMouseEnter={e=>e.currentTarget.style.color='var(--danger)'}
                        onMouseLeave={e=>e.currentTarget.style.color='var(--text-3)'}>
                        <Trash2 size={13}/>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
        }
      </div>
    </div>
    </>
  )
}

// - Knowledge Base tab ------------------
const DIRECTION_LABELS = { '': '-', 'debit': '- Out', 'credit': '- In' }


// CompaniesPane: proper component so hooks work correctly
function CompaniesPane({ companies, setCompanies, loading, filteredCo, pageCo, totalPages, page, setPage, coSearch, setCoSearch }) {
  const BLANK_CO = {name:'',short_name:'',category:'',subcategory:'',country:'AU',abn:'',is_government:false}
  const [coForm,   setCoForm]   = useState(BLANK_CO)
  const [coEdit,   setCoEdit]   = useState(null)
  const [coSaving, setCoSaving] = useState(false)
  const [newAlias, setNewAlias] = useState('')

  const startCoEdit = c => {
    setCoEdit(c)
    setCoForm({name:c.name||'',short_name:c.short_name||'',category:c.category||'',
      subcategory:c.subcategory||'',country:c.country||'AU',abn:c.abn||'',
      is_government:!!c.is_government})
    setNewAlias('')
  }
  const resetCo = () => { setCoEdit(null); setCoForm(BLANK_CO); setNewAlias('') }

  const saveCo = async () => {
    if(!coForm.name.trim()){toast.error('Company name required');return}
    setCoSaving(true)
    try {
      if(coEdit){
        const {data} = await companyUpdate(coEdit.id, coForm)
        const updated = {...data, aliases: coEdit.aliases||[]}
        setCompanies(prev=>prev.map(c=>c.id===coEdit.id?updated:c))
        setCoEdit(updated)
        toast.success('Company updated')
      } else {
        const {data} = await companyCreate(coForm)
        setCompanies(prev=>[{...data,aliases:[]},...prev])
        resetCo()
        toast.success('Company added')
      }
    } catch(e){ toast.error(e?.response?.data?.detail||'Save failed') }
    setCoSaving(false)
  }

  const delCo = async c => {
    if(!confirm('Delete "'+c.name+'"?')) return
    await companyDelete(c.id).catch(()=>{})
    setCompanies(prev=>prev.filter(x=>x.id!==c.id))
    if(coEdit?.id===c.id) resetCo()
    toast.success('Deleted')
  }

  const addAlias = async () => {
    if(!coEdit){toast.error('Select a company first');return}
    if(!newAlias.trim()){toast.error('Enter alias text');return}
    try {
      const {data} = await companyAddAlias(coEdit.id,{alias:newAlias.trim().toLowerCase(),priority:0})
      const updated = {...coEdit,aliases:[...(coEdit.aliases||[]),data]}
      setCoEdit(updated)
      setCompanies(prev=>prev.map(c=>c.id===coEdit.id?updated:c))
      setNewAlias('')
      toast.success('Alias added')
    } catch(e){ toast.error(e?.response?.data?.detail||'Failed') }
  }

  const delAlias = async (txt) => {
    if(!coEdit) return
    await fetch('/api/company/'+coEdit.id+'/alias/'+encodeURIComponent(txt),
      {method:'DELETE'}).catch(()=>{})
    const updated = {...coEdit,aliases:(coEdit.aliases||[]).filter(a=>(a.alias||a)!==txt)}
    setCoEdit(updated)
    setCompanies(prev=>prev.map(c=>c.id===coEdit.id?updated:c))
    toast.success('Alias removed')
  }

  const Pager = ({total,cur,set}) => total<=1?null:(
    <div style={{display:'flex',gap:4,alignItems:'center',justifyContent:'center',
      padding:'8px 0',fontSize:'.8rem',borderTop:'1px solid var(--border)'}}>
      <button className="btn btn-ghost btn-sm" onClick={()=>set(1)} disabled={cur===1}>«</button>
      <button className="btn btn-ghost btn-sm" onClick={()=>set(cur-1)} disabled={cur===1}>‹</button>
      <span style={{padding:'0 10px',color:'var(--text-2)'}}>Page {cur} / {total}</span>
      <button className="btn btn-ghost btn-sm" onClick={()=>set(cur+1)} disabled={cur===total}>›</button>
      <button className="btn btn-ghost btn-sm" onClick={()=>set(total)} disabled={cur===total}>»</button>
    </div>)

  return (
    <div style={{display:'grid',gridTemplateColumns:'320px 1fr',gap:16,
      height:'calc(100vh - 140px)',minHeight:500,alignItems:'start',overflow:'hidden'}}>

      {/* Left: form */}
      <div style={{background:'var(--surface-2)',borderRadius:'var(--r-md)',padding:16,
        border:'1px solid var(--border)',overflowY:'auto',maxHeight:'calc(100vh - 160px)',
        display:'flex',flexDirection:'column',gap:8}}>
        <div style={{display:'flex',alignItems:'center',marginBottom:4}}>
          <h3 style={{margin:0,fontSize:'.9rem',flex:1}}>
            {coEdit ? 'Edit: '+coEdit.name : 'New Company'}
          </h3>
          {coEdit && (
            <button className="btn btn-ghost btn-sm"
              style={{fontSize:'.75rem',padding:'2px 8px'}} onClick={resetCo}>
              <Plus size={12}/> New
            </button>
          )}
        </div>
        {[['name','Name *','e.g. Microsoft Australia'],
          ['short_name','Short Name','e.g. Microsoft'],
          ['category','Category','e.g. Software'],
          ['subcategory','Subcategory','e.g. Cloud Services'],
          ['country','Country','AU'],
          ['abn','ABN','e.g. 12 345 678 901'],
        ].map(([k,lbl,ph])=>(
          <div key={k} className="input-group">
            <label>{lbl}</label>
            <input className="input input-sm" placeholder={ph}
              value={coForm[k]||''}
              onChange={e=>setCoForm(f=>({...f,[k]:e.target.value}))}/>
          </div>
        ))}
        <label style={{display:'flex',alignItems:'center',gap:6,fontSize:'.82rem',cursor:'pointer'}}>
          <input type="checkbox" checked={!!coForm.is_government}
            onChange={e=>setCoForm(f=>({...f,is_government:e.target.checked}))}/>
          Government entity
        </label>
        <button className="btn btn-primary btn-sm" onClick={saveCo} disabled={coSaving}>
          <Check size={13}/> {coSaving?'Saving...': coEdit?'Update':'Add Company'}
        </button>
        {coEdit && (
          <button className="btn btn-ghost btn-sm"
            style={{color:'var(--danger)',fontSize:'.78rem'}} onClick={()=>delCo(coEdit)}>
            <Trash2 size={12}/> Delete Company
          </button>
        )}
        <CsvBar label="Companies"
          onUpload={async file=>{
            const rows=parseCSVText(await file.text())
            if(rows.length<2){toast.error('Empty CSV');return}
            const hdr=rows[0].map(h=>h.trim().toLowerCase())
            let added=0,updated=0
            for(const vals of rows.slice(1)){
              const o={}; hdr.forEach((h,i)=>o[h]=vals[i]||'')
              const name=(o.name||'').trim(); if(!name) continue
              const body={name,short_name:o.short_name||'',category:o.category||'',
                subcategory:o.subcategory||'',country:(o.country||'AU').toUpperCase(),
                abn:o.abn||'',is_government:o.is_government==='true'}
              try{
                const ex=companies.find(c=>c.name.toLowerCase()===name.toLowerCase())
                if(ex){const {data}=await companyUpdate(ex.id,body);setCompanies(prev=>prev.map(c=>c.id===ex.id?{...data,aliases:c.aliases}:c));updated++}
                else{const {data}=await companyCreate(body);setCompanies(prev=>[...prev,{...data,aliases:[]}]);added++}
              }catch{}
            }
            toast.success('Companies: '+added+' added, '+updated+' updated')
          }}
          onDownload={()=>downloadCSV('companies.csv',toCSV(
            companies.map(c=>({name:c.name,short_name:c.short_name||'',category:c.category||'',
              country:c.country||'AU',abn:c.abn||'',
              aliases:(c.aliases||[]).map(a=>typeof a==='string'?a:a.alias).join('|')})),
            ['name','short_name','category','country','abn','aliases']))}
        />
        {coEdit && (
          <div style={{borderTop:'1px solid var(--border)',paddingTop:10,marginTop:4}}>
            <div style={{fontWeight:700,fontSize:'.82rem',marginBottom:6}}>Aliases</div>
            <div style={{display:'flex',gap:4,marginBottom:6}}>
              <input className="input input-sm" style={{flex:1}} placeholder="add alias..."
                value={newAlias} onChange={e=>setNewAlias(e.target.value)}
                onKeyDown={e=>e.key==='Enter'&&addAlias()}/>
              <button className="btn btn-outline btn-sm" onClick={addAlias}>
                <Plus size={12}/>
              </button>
            </div>
            <div style={{display:'flex',flexWrap:'wrap',gap:4}}>
              {(coEdit.aliases||[]).map((a,i)=>{
                const txt=typeof a==='string'?a:a.alias
                return (
                  <span key={i} style={{display:'inline-flex',alignItems:'center',gap:3,
                    background:'var(--surface-3)',borderRadius:4,padding:'2px 6px',fontSize:'.72rem'}}>
                    {txt}
                    <button onClick={()=>delAlias(txt)}
                      style={{background:'none',border:'none',cursor:'pointer',
                        color:'var(--text-3)',lineHeight:1,padding:'0 1px'}}
                      onMouseEnter={e=>e.currentTarget.style.color='var(--danger)'}
                      onMouseLeave={e=>e.currentTarget.style.color='var(--text-3)'}>
                      x
                    </button>
                  </span>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Right: company list */}
      <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-md)',
        overflow:'hidden',display:'flex',flexDirection:'column',maxHeight:'calc(100vh - 160px)'}}>
        <div style={{padding:'10px 16px',background:'var(--surface-2)',
          borderBottom:'1px solid var(--border)',
          display:'flex',alignItems:'center',gap:8,flexShrink:0}}>
          <span style={{fontWeight:700,fontSize:'.85rem'}}>Company Database</span>
          <span style={{background:'var(--surface-3)',borderRadius:100,padding:'1px 8px',
            fontSize:'.72rem',fontWeight:700}}>{filteredCo.length}</span>
          <input className="input input-sm" placeholder="Search companies..."
            value={coSearch} onChange={e=>{setCoSearch(e.target.value);setPage(1)}}
            style={{marginLeft:'auto',width:200}}/>
        </div>
        {loading
          ? <div style={{padding:32,textAlign:'center',color:'var(--text-3)'}}>Loading...</div>
          : <><div style={{overflowX:'auto',overflowY:'auto',flex:1}}>
              <table className="data-table" style={{width:'100%'}}>
                <thead><tr>
                  <th>Company</th>
                  <th style={{width:90}}>Short</th>
                  <th style={{width:110}}>Category</th>
                  <th>Aliases</th>
                  <th style={{width:36}}></th>
                </tr></thead>
                <tbody>
                  {pageCo.map((c,i)=>(
                    <tr key={c.id||i} style={{cursor:'pointer',
                      background:coEdit?.id===c.id?'var(--brand-bg,#eff6ff)':undefined}}
                      onClick={()=>startCoEdit(c)}>
                      <td style={{fontWeight:600,fontSize:'.82rem'}}>{c.name}</td>
                      <td style={{fontSize:'.78rem',color:'var(--text-2)'}}>{c.short_name||'-'}</td>
                      <td style={{fontSize:'.75rem',color:'var(--text-3)'}}>{c.category||'-'}</td>
                      <td style={{fontSize:'.72rem'}}>
                        {(c.aliases||[]).slice(0,3).map((a,ai)=>(
                          <span key={ai} style={{display:'inline-block',
                            background:'var(--surface-3)',borderRadius:3,
                            padding:'1px 4px',margin:'1px 2px',whiteSpace:'nowrap'}}>
                            {typeof a==='string'?a:a.alias}
                          </span>
                        ))}
                        {(c.aliases||[]).length>3&&
                          <span style={{color:'var(--text-3)',fontSize:'.7rem'}}>
                            +{(c.aliases||[]).length-3}
                          </span>}
                      </td>
                      <td onClick={ev=>ev.stopPropagation()}>
                        <button className="btn btn-ghost btn-icon btn-sm"
                          onMouseEnter={e=>e.currentTarget.style.color='var(--danger)'}
                          onMouseLeave={e=>e.currentTarget.style.color=''}
                          onClick={()=>delCo(c)}><Trash2 size={11}/></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={totalPages} cur={page} set={setPage}/>
          </>
        }
      </div>
    </div>
  )
}

const KB_GST_OPTS=['','GST on Expenses','GST on Capital','GST on Income','GST Free Expenses','GST Free Income','BAS Excluded']

function GlSel({v,s,glList}) {
  return (
    <select className="input input-sm" value={v} onChange={e=>s(e.target.value)}>
      <option value="">-- GL Account --</option>
      {(glList||[]).map((g,i)=>{const n=typeof g==='string'?g:String(g?.Name||g?.name||'');return n?(<option key={n} value={n}>{n}</option>):null})}
    </select>
  )
}

function GstSel({v,s}) {
  return (
    <select className="input input-sm" value={v} onChange={e=>s(e.target.value)}>
      {KB_GST_OPTS.map(g=><option key={g} value={g}>{g||'-- Auto --'}</option>)}
    </select>
  )
}

function DirSel({v,s}) {
  return (
    <select className="input input-sm" value={v} onChange={e=>s(e.target.value)}>
      <option value="">- Any</option>
      <option value="debit">- Outgoing</option>
      <option value="credit">- Incoming</option>
    </select>
  )
}

function AddForm({keyVal,setKey,form,setForm,onSave,onNew,onDelete,label,ph,onUpload,onDownload,glList,saving}) {
  const fileRef2 = useRef(null)
  return (
    <div style={{background:'var(--surface-2)',borderRadius:'var(--r-md)',padding:16,
      border:'1px solid var(--border)',display:'flex',flexDirection:'column',gap:8,
      overflowY:'auto',maxHeight:'calc(100vh - 160px)'}}>
      <div style={{display:'flex',alignItems:'center',marginBottom:2}}>
        <h3 style={{margin:0,fontSize:'.9rem',flex:1}}>
          {keyVal ? `Edit: ${keyVal}` : `New ${label}`}
        </h3>
        {keyVal && onNew && (
          <button className="btn btn-ghost btn-sm"
            style={{fontSize:'.75rem',padding:'2px 8px'}} onClick={onNew}>
            <Plus size={12}/> New
          </button>
        )}
      </div>
      <div className="input-group">
        <label>{label} name</label>
        <input className="input input-sm" value={keyVal} onChange={e=>setKey(e.target.value)} placeholder={ph}/>
      </div>
      <div className="input-group"><label>GL Account</label>
        <GlSel v={form.gl} s={v=>setForm(f=>({...f,gl:v}))} glList={glList}/>
      </div>
      <div className="input-group"><label>GST</label>
        <GstSel v={form.gst} s={v=>setForm(f=>({...f,gst:v}))}/>
      </div>
      <div className="input-group"><label>Direction</label>
        <DirSel v={form.direction} s={v=>setForm(f=>({...f,direction:v}))}/>
      </div>
      <button className="btn btn-primary btn-sm" onClick={onSave} disabled={saving}>
        {saving ? 'Saving...' : keyVal ? 'Update' : '+ Save'}
      </button>
      {keyVal && onDelete && (
        <button className="btn btn-ghost btn-sm"
          style={{color:'var(--danger)',fontSize:'.78rem'}} onClick={onDelete}>
          <Trash2 size={12}/> Delete {label}
        </button>
      )}
      {onUpload && (
        <div style={{borderTop:'1px solid var(--border)',marginTop:4,paddingTop:10,
          display:'flex',flexDirection:'row',gap:6}}>
          <input ref={fileRef2} type="file" accept=".csv" style={{display:'none'}}
            onChange={e=>{if(e.target.files[0])onUpload(e.target.files[0]);e.target.value=''}}/>
          <button className="btn btn-outline btn-sm" style={{flex:1}}
            onClick={()=>fileRef2.current.click()}>
            <Upload size={12}/> Upload {label}
          </button>
          <button className="btn btn-outline btn-sm" style={{flex:1}} onClick={onDownload}>
            <Download size={12}/> Download {label}
          </button>
        </div>
      )}
    </div>
  )
}

function KbTab() {
  const [kb,         setKb]        = useState(null)
  const [glList,     setGlList]    = useState([])
  const [companies,  setCompanies] = useState([])
  const [loading,    setLoading]   = useState(false)
  const [subTab,     setSubTab]    = useState('companies')
  const [vendorKey,  setVendorKey] = useState('')
  const [vendorForm, setVendorForm]= useState({gl:'',gst:'',direction:'debit'})
  const [kwKey,      setKwKey]     = useState('')
  const [kwForm,     setKwForm]    = useState({gl:'',gst:'',direction:'debit'})
  const [saving,     setSaving]    = useState(false)
  const [search,     setSearch]    = useState('')
  const [page,       setPage]      = useState(1)
  const [vSearch,    setVSearch]   = useState('')
  const [kSearch,    setKSearch]   = useState('')
  const [coSearch,   setCoSearch]  = useState('')
  const [loadError,  setLoadError] = useState('')
  const PAGE_SIZE = 50

  useEffect(()=>{
    let alive=true
    kbGet().then(r=>{ if(alive) setKb(r.data||{}) }).catch(e=>{ if(alive){ console.error('[KbTab] kbGet failed:',e?.message||e); setKb({}); setLoadError('Could not load knowledge base: '+(e?.message||'server unreachable')) } })
    coaAccounts().then(r=>{ if(alive) setGlList(r.data||[]) }).catch(e=>{ if(alive){ console.error('[KbTab] coaAccounts failed:',e?.message||e); setLoadError(p=>p||'Could not load GL accounts: '+(e?.message||'server unreachable')) } })
    setLoading(true)
    companyList({limit:1000,skip:0}).then(r=>{
      if(!alive) return
      const data=Array.isArray(r.data)?r.data:[]
      if(data.length===0) console.warn('[KbTab] companyList returned 0 results')
      const normalised = data.map(c=>({...c,
        aliases:(c.aliases||[]).map(a=>typeof a==='string'?{id:0,alias:a}:a)
      }))
      setCompanies(normalised)
    }).catch(e=>{ if(alive){ console.error('[KbTab] companyList:',e?.message||e); setCompanies([]); setLoadError(p=>p||'Could not load companies: '+(e?.message||'server unreachable')) }
    }).finally(()=>{ if(alive) setLoading(false) })
    return ()=>{ alive=false }
  },[])

  useEffect(()=>setPage(1),[search,subTab])

  const GST_OPTS=['','GST on Expenses','GST on Capital','GST on Income','GST Free Expenses','GST Free Income','BAS Excluded']

  const saveVendor=async()=>{
    if(!vendorKey.trim()){toast.error('Enter vendor name');return}
    if(!vendorForm.gl){toast.error('Select GL Account');return}
    setSaving(true)
    try{
      await kbVendorUpsert(vendorKey.trim().toLowerCase(),vendorForm)
      setKb(p=>({...p,vendor_map:{...(p?.vendor_map||{}),[vendorKey.trim().toLowerCase()]:vendorForm}}))
      setVendorKey('');setVendorForm({gl:'',gst:'',direction:'debit'})
      toast.success('Vendor saved')
    }catch{toast.error('Save failed')}
    setSaving(false)
  }

  const delVendor=async(key)=>{
    await kbVendorDelete(key).catch(()=>{})
    setKb(p=>{const vm={...(p?.vendor_map||{})};delete vm[key];return{...p,vendor_map:vm}})
    toast.success('Removed')
  }

  const saveKw=async()=>{
    if(!kwKey.trim()){toast.error('Enter keyword');return}
    if(!kwForm.gl){toast.error('Select GL Account');return}
    setSaving(true)
    try{
      await kbKeywordUpsert(kwKey.trim().toLowerCase(),kwForm)
      setKb(p=>({...p,keyword_map:{...(p?.keyword_map||{}),[kwKey.trim().toLowerCase()]:kwForm}}))
      setKwKey('');setKwForm({gl:'',gst:'',direction:'debit'})
      toast.success('Keyword saved')
    }catch{toast.error('Save failed')}
    setSaving(false)
  }

  const delKw=async(key)=>{
    await kbKeywordDelete(key).catch(()=>{})
    setKb(p=>{const km={...(p?.keyword_map||{})};delete km[key];return{...p,keyword_map:km}})
    toast.success('Removed')
  }

  if(!kb) return <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>Loading...</div>

  const vendors  = Object.entries(kb.vendor_map||{})
  const keywords = Object.entries(kb.keyword_map||{})

  const _sq = String(coSearch||'').toLowerCase()
  const filteredCo = (companies||[]).filter(c=>{
    if(!_sq) return true
    try {
      if(String(c?.name||'').toLowerCase().includes(_sq)) return true
      if(String(c?.short_name||'').toLowerCase().includes(_sq)) return true
      return (Array.isArray(c?.aliases)?c.aliases:[]).some(a=>
        String(typeof a==='string'?a:a?.alias||'').toLowerCase().includes(_sq))
    } catch(err) { console.error('Search crash on company:',c,err); return false }
  })
  const totalPages = Math.max(1,Math.ceil(filteredCo.length/PAGE_SIZE))
  const pageCo = filteredCo.slice((page-1)*PAGE_SIZE, page*PAGE_SIZE)

  const _vq = String(vSearch||'').toLowerCase()
  const filtV = (vendors||[]).filter(([k,e])=>{
    if(!_vq) return true
    try {
      if(String(k||'').toLowerCase().includes(_vq)) return true
      return String(e?.gl||'').toLowerCase().includes(_vq)
    } catch(err) { console.error('Search crash on vendor:',k,err); return false }
  })
  const _kq = String(kSearch||'').toLowerCase()
  const filtK = (keywords||[]).filter(([k,e])=>{
    if(!_kq) return true
    try {
      if(String(k||'').toLowerCase().includes(_kq)) return true
      return String(e?.gl||'').toLowerCase().includes(_kq)
    } catch(err) { console.error('Search crash on keyword:',k,err); return false }
  })

  const Pager=({total,cur,set})=>total<=1?null:(
    <div style={{display:'flex',gap:4,alignItems:'center',justifyContent:'center',
      padding:'8px 0',fontSize:'.8rem',borderTop:'1px solid var(--border)'}}>
      <button className="btn btn-ghost btn-sm" onClick={()=>set(1)} disabled={cur===1}>-</button>
      <button className="btn btn-ghost btn-sm" onClick={()=>set(cur-1)} disabled={cur===1}>-</button>
      <span style={{padding:'0 10px',color:'var(--text-2)'}}>Page {cur} / {total}</span>
      <button className="btn btn-ghost btn-sm" onClick={()=>set(cur+1)} disabled={cur===total}>-</button>
      <button className="btn btn-ghost btn-sm" onClick={()=>set(total)} disabled={cur===total}>-</button>
    </div>)


  return (
    <div style={{display:'flex',flexDirection:'column',gap:12}}>
      {loadError && (
        <div style={{background:'var(--danger-bg,#fef2f2)',border:'1px solid var(--danger,#dc2626)',
          borderRadius:'var(--r-md)',padding:'10px 14px',
          color:'var(--danger,#dc2626)',fontSize:'.85rem'}}>
          ⚠ {loadError} — check that the API server is running and reachable.
        </div>
      )}
      <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
        {[
          ['companies',`- Companies (${companies.length})`],
          ['vendors',  `- Vendor Map (${vendors.length})`],
          ['keywords', `- Keywords (${keywords.length})`],
        ].map(([k,l])=>(
          <button key={k} onClick={()=>{setSubTab(k);setSearch('');setPage(1)}}
            className={`btn btn-sm ${subTab===k?'btn-primary':'btn-ghost'}`}>{l}</button>
        ))}
      </div>

      {subTab==='companies' && (
        <CompaniesPane companies={companies} setCompanies={setCompanies}
          loading={loading} filteredCo={filteredCo} pageCo={pageCo}
          totalPages={totalPages} page={page} setPage={setPage}
          coSearch={coSearch} setCoSearch={setCoSearch}/>
      )}

      {subTab==='vendors' && (
        <div style={{display:'grid',gridTemplateColumns:'320px 1fr',gap:16,
          height:'calc(100vh - 140px)',minHeight:500,alignItems:'start',overflow:'hidden'}}>
          <AddForm keyVal={vendorKey} setKey={setVendorKey} form={vendorForm} setForm={setVendorForm}
            glList={glList} saving={saving}
            onSave={saveVendor} label="Vendor" ph="e.g. uber, microsoft"
            onNew={()=>{setVendorKey('');setVendorForm({gl:'',gst:'',direction:'debit'})}}
            onDelete={vendorKey?()=>delVendor(vendorKey):undefined}
            onUpload={async file=>{
              const rows=parseCSVText(await file.text())
              if(rows.length<2){toast.error('Empty CSV');return}
              const hdr=rows[0].map(h=>h.trim().toLowerCase())
              let added=0,updated=0
              const vm={...(kb?.vendor_map||{})}
              rows.slice(1).forEach(vals=>{
                const o={}; hdr.forEach((h,i)=>o[h]=vals[i]||'')
                const k=(o.vendor||o.name||'').trim().toLowerCase()
                if(!k||!o.gl) return
                const entry={gl:o.gl,gst:o.gst||'',direction:o.direction||'debit'}
                if(vm[k]) updated++; else added++
                vm[k]=entry; kbVendorUpsert(k,entry).catch(()=>{})
              })
              setKb(p=>({...p,vendor_map:vm}))
              toast.success('Vendors: '+added+' added, '+updated+' updated')
            }}
            onDownload={()=>downloadCSV('vendor_map.csv',toCSV(
              Object.entries(kb?.vendor_map||{}).map(([k,e])=>({vendor:k,gl:e.gl||'',gst:e.gst||'',direction:e.direction||''})),
              ['vendor','gl','gst','direction']))}
          />
          <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-md)',
            overflow:'hidden',display:'flex',flexDirection:'column',maxHeight:'calc(100vh - 160px)'}}>
            <div style={{padding:'10px 14px',background:'var(--surface-2)',fontWeight:700,fontSize:'.85rem',
              borderBottom:'1px solid var(--border)',display:'flex',alignItems:'center',gap:8,flexShrink:0}}>
              Vendor Map <span style={{fontWeight:400,fontSize:'.72rem',color:'var(--text-3)'}}>({filtV.length})</span>
              <input className="input input-sm" placeholder="Search vendors..."
                value={vSearch} onChange={e=>setVSearch(e.target.value)}
                style={{marginLeft:'auto',width:200,fontWeight:'normal'}}/>
            </div>
            <div style={{overflowY:'auto',flex:1}}>
              <table className="data-table" style={{width:'100%'}}>
                <thead><tr>
                  <th>Vendor</th><th>GL</th><th>GST</th><th style={{width:60}}>Dir</th><th style={{width:36}}></th>
                </tr></thead>
                <tbody>
                  {filtV.sort(([a],[b])=>String(a).localeCompare(String(b))).map(([k,e])=>(
                    <tr key={k} style={{cursor:'pointer'}}
                      onClick={()=>{setVendorKey(k);setVendorForm({gl:e.gl||'',gst:e.gst||'',direction:e.direction||'debit'})}}>
                      <td style={{fontWeight:600,fontSize:'.82rem'}}>{k}</td>
                      <td><span className="badge badge-neutral" style={{fontSize:'.72rem'}}>{String(e?.gl||"")}</span></td>
                      <td style={{fontSize:'.72rem',color:'var(--text-3)'}}>{String(e?.gst||'-')}</td>
                      <td style={{fontSize:'.72rem'}}>{DIRECTION_LABELS[e.direction||'']}</td>
                      <td onClick={ev=>ev.stopPropagation()}>
                        <button className="btn btn-ghost btn-icon btn-sm"
                          title="Delete"
                          onMouseEnter={ev=>ev.currentTarget.style.color='var(--danger)'}
                          onMouseLeave={ev=>ev.currentTarget.style.color=''}
                          onClick={()=>delVendor(k)}><Trash2 size={11}/></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {subTab==='keywords' && (
        <div style={{display:'grid',gridTemplateColumns:'320px 1fr',gap:16,
          height:'calc(100vh - 140px)',minHeight:500,alignItems:'start',overflow:'hidden'}}>
          <AddForm keyVal={kwKey} setKey={setKwKey} form={kwForm} setForm={setKwForm}
            glList={glList} saving={saving}
            onSave={saveKw} label="Keyword" ph="e.g. broker fee, cleaning"
            onNew={()=>{setKwKey('');setKwForm({gl:'',gst:'',direction:'debit'})}}
            onDelete={kwKey?()=>delKw(kwKey):undefined}
            onUpload={async file=>{
              const rows=parseCSVText(await file.text())
              if(rows.length<2){toast.error('Empty CSV');return}
              const hdr=rows[0].map(h=>h.trim().toLowerCase())
              let added=0,updated=0
              const km={...(kb?.keyword_map||{})}
              rows.slice(1).forEach(vals=>{
                const o={}; hdr.forEach((h,i)=>o[h]=vals[i]||'')
                const k=(o.keyword||o.name||'').trim().toLowerCase()
                if(!k||!o.gl) return
                const entry={gl:o.gl,gst:o.gst||'',direction:o.direction||'debit'}
                if(km[k]) updated++; else added++
                km[k]=entry; kbKeywordUpsert(k,entry).catch(()=>{})
              })
              setKb(p=>({...p,keyword_map:km}))
              toast.success('Keywords: '+added+' added, '+updated+' updated')
            }}
            onDownload={()=>downloadCSV('keyword_map.csv',toCSV(
              Object.entries(kb?.keyword_map||{}).map(([k,e])=>({keyword:k,gl:e.gl||'',gst:e.gst||'',direction:e.direction||''})),
              ['keyword','gl','gst','direction']))}
          />
          <div style={{border:'1px solid var(--border)',borderRadius:'var(--r-md)',
            overflow:'hidden',display:'flex',flexDirection:'column',maxHeight:'calc(100vh - 160px)'}}>
            <div style={{padding:'10px 14px',background:'var(--surface-2)',fontWeight:700,fontSize:'.85rem',
              borderBottom:'1px solid var(--border)',display:'flex',alignItems:'center',gap:8,flexShrink:0}}>
              Keyword Map <span style={{fontWeight:400,fontSize:'.72rem',color:'var(--text-3)'}}>({filtK.length})</span>
              <input className="input input-sm" placeholder="Search keywords..."
                value={kSearch} onChange={e=>setKSearch(e.target.value)}
                style={{marginLeft:'auto',width:200,fontWeight:'normal'}}/>
            </div>
            <div style={{overflowY:'auto',flex:1}}>
              <table className="data-table" style={{width:'100%'}}>
                <thead><tr>
                  <th>Keyword</th><th>GL</th><th>GST</th><th style={{width:60}}>Dir</th><th style={{width:36}}></th>
                </tr></thead>
                <tbody>
                  {filtK.sort(([a],[b])=>String(a).localeCompare(String(b))).map(([k,e])=>(
                    <tr key={k} style={{cursor:'pointer'}}
                      onClick={()=>{setKwKey(k);setKwForm({gl:e.gl||'',gst:e.gst||'',direction:e.direction||'debit'})}}>
                      <td style={{fontWeight:600,fontSize:'.82rem'}}>{k}</td>
                      <td><span className="badge badge-neutral" style={{fontSize:'.72rem'}}>{String(e?.gl||"")}</span></td>
                      <td style={{fontSize:'.72rem',color:'var(--text-3)'}}>{String(e?.gst||'-')}</td>
                      <td style={{fontSize:'.72rem'}}>{DIRECTION_LABELS[e.direction||'']}</td>
                      <td onClick={ev=>ev.stopPropagation()}>
                        <button className="btn btn-ghost btn-icon btn-sm"
                          title="Delete"
                          onMouseEnter={ev=>ev.currentTarget.style.color='var(--danger)'}
                          onMouseLeave={ev=>ev.currentTarget.style.color=''}
                          onClick={()=>delKw(k)}><Trash2 size={11}/></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


const TABS = [
  { key:'business', label:'🏢 Business Account' },
  { key:'coa',      label:'📋 Chart of Accounts' },
  { key:'rdr',      label:'⚙️ Business Rules' },
  { key:'kb',       label:'📚 Knowledge Base' },
]

// ── Business Account Tab ──────────────────────────────────────────────────────
function BusinessAccountTab() {
  const { user } = useAuth()
  const [biz, setBiz] = React.useState({
    business_name: '', abn: '', acn: '', gst_registered: false,
    gst_registration_date: '', business_type: 'company',
    address_line1: '', suburb: '', state: 'NSW', postcode: '',
    phone: '', email: '', website: '',
    bank_name: '', bank_bsb: '', bank_account: '',
    financial_year_end: 'June', tax_agent_name: '', tax_agent_number: '',
    logo_url: '',
  })
  const [saved, setSaved] = React.useState(false)
  const BIZ_TYPES = ['company','sole_trader','partnership','trust','other']
  const AU_STATES = ['ACT','NSW','NT','QLD','SA','TAS','VIC','WA']

  const F = ({label, field, type='text', opts, hint}) => (
    <div className="input-group">
      <label>{label}{hint && <span title={hint} style={{marginLeft:4,cursor:'help',color:'var(--text-3)',fontSize:'.75rem'}}>ⓘ</span>}</label>
      {opts
        ? <select className="input input-sm" value={biz[field]||''} onChange={e=>setBiz(b=>({...b,[field]:e.target.value}))}>
            {opts.map(o=><option key={o.v||o} value={o.v||o}>{o.l||o.replace(/_/g,' ')}</option>)}
          </select>
        : type === 'checkbox'
          ? <label style={{display:'flex',alignItems:'center',gap:6,marginTop:4}}>
              <input type="checkbox" checked={!!biz[field]} onChange={e=>setBiz(b=>({...b,[field]:e.target.checked}))}/>
              <span style={{fontSize:'.82rem'}}>Yes</span>
            </label>
          : <input className="input input-sm" type={type} value={biz[field]||''}
              onChange={e=>setBiz(b=>({...b,[field]:e.target.value}))}/>
      }
    </div>
  )

  const handleSave = () => {
    try { localStorage.setItem('accfino_business_account', JSON.stringify(biz)) } catch {}
    setSaved(true); setTimeout(()=>setSaved(false), 3000)
    toast?.success?.('Business account saved ✓') || console.log('Saved')
  }

  React.useEffect(() => {
    try { const saved = JSON.parse(localStorage.getItem('accfino_business_account')||'{}'); if (saved.business_name) setBiz(b=>({...b,...saved})) } catch {}
  }, [])

  return (
    <div>
      <div style={{marginBottom:16,padding:'10px 14px',background:'var(--brand-xlight,#eff6ff)',
        borderRadius:'var(--r-md)',border:'1px solid #bfdbfe',fontSize:'.8rem',color:'#1e40af'}}>
        ℹ️ Your business details are used on Invoices, Purchase Orders and Reports. This information is stored locally.
      </div>

      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:24}}>
        {/* Business details */}
        <div>
          <h4 style={{marginBottom:12,paddingBottom:8,borderBottom:'1px solid var(--border)'}}>🏢 Business Details</h4>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
            <div style={{gridColumn:'span 2'}}><F label="Business / Trading Name *" field="business_name"/></div>
            <F label="ABN" field="abn" hint="11-digit Australian Business Number"/>
            <F label="ACN" field="acn" hint="9-digit Australian Company Number (companies only)"/>
            <F label="Business Type" field="business_type" opts={BIZ_TYPES}/>
            <F label="Financial Year End" field="financial_year_end" opts={['June','December','March','September']}/>
            <F label="GST Registered" field="gst_registered" type="checkbox"/>
            {biz.gst_registered && <F label="GST Registration Date" field="gst_registration_date" type="date"/>}
          </div>

          <h4 style={{marginTop:20,marginBottom:12,paddingBottom:8,borderBottom:'1px solid var(--border)'}}>📍 Address</h4>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
            <div style={{gridColumn:'span 2'}}><F label="Street Address" field="address_line1"/></div>
            <F label="Suburb / City" field="suburb"/>
            <F label="State" field="state" opts={AU_STATES}/>
            <F label="Postcode" field="postcode"/>
            <F label="Phone" field="phone" type="tel"/>
            <div style={{gridColumn:'span 2'}}><F label="Business Email" field="email" type="email"/></div>
            <div style={{gridColumn:'span 2'}}><F label="Website" field="website"/></div>
          </div>
        </div>

        {/* Banking & Tax */}
        <div>
          <h4 style={{marginBottom:12,paddingBottom:8,borderBottom:'1px solid var(--border)'}}>🏦 Banking Details</h4>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
            <F label="Bank Name" field="bank_name"/>
            <F label="BSB" field="bank_bsb"/>
            <div style={{gridColumn:'span 2'}}><F label="Account Number" field="bank_account"/></div>
          </div>

          <h4 style={{marginTop:20,marginBottom:12,paddingBottom:8,borderBottom:'1px solid var(--border)'}}>🧾 Tax Agent</h4>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
            <F label="Tax Agent Name" field="tax_agent_name"/>
            <F label="Tax Agent Number" field="tax_agent_number" hint="Registered tax agent number"/>
          </div>

          {/* Logo */}
          <h4 style={{marginTop:20,marginBottom:12,paddingBottom:8,borderBottom:'1px solid var(--border)'}}>🖼 Logo (for Invoices)</h4>
          <div className="input-group">
            <label>Logo URL</label>
            <input className="input input-sm" type="url" value={biz.logo_url||''}
              onChange={e=>setBiz(b=>({...b,logo_url:e.target.value}))}
              placeholder="https://yourwebsite.com/logo.png"/>
          </div>
          {biz.logo_url && (
            <div style={{marginTop:8,padding:8,background:'var(--surface-2)',borderRadius:'var(--r-md)',textAlign:'center'}}>
              <img src={biz.logo_url} alt="Logo preview" style={{maxHeight:60,maxWidth:200,objectFit:'contain'}}
                onError={e=>{e.target.style.display='none'}}/>
            </div>
          )}

          <div style={{marginTop:24}}>
            <button className="btn btn-primary" onClick={handleSave} style={{marginRight:8}}>
              {saved ? '✓ Saved!' : '💾 Save Business Account'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


export default function SetupPage() {
  const [tab, setTab] = useState('business')
  return (
    <div className="fade-in">
      <div style={{marginBottom:20}}>
        <h1>⚙️ Setup</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          Chart of Accounts · Business Rules · Knowledge Base · Invoice Generator
        </p>
      </div>
      <div className="tabs-bar" style={{marginBottom:0}}>
        {TABS.map(t=>(
          <button key={t.key} className={`tab-btn${tab===t.key?' active':''}`} onClick={()=>setTab(t.key)}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>
      <div style={{background:'var(--surface)',borderRadius:'0 0 var(--r-lg) var(--r-lg)',
        border:'1px solid var(--border)',borderTop:'none',padding:'20px 24px',boxShadow:'var(--sh-sm)'}}>
        {tab==='business' && <BusinessAccountTab/>}
        {tab==='coa' && <CoaTab/>}
        {tab==='rdr' && <RdrTab/>}
        {tab==='kb'  && <KbTab/>}
      </div>
    </div>
  )
}
