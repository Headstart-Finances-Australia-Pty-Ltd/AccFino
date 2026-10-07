import React, { useEffect, useState, useCallback } from 'react'
import { fmTree, fmRead, fmSave, fmDeleteRow, dbListTables, dbTableRows, dbUpdateRow, dbDeleteRow, dbBulkDeleteRows, dbInsertRow, dbUploadCsv, dbRunQuery } from '../lib/api.js'
import { Database, Save, Upload, Trash2, Edit2, Check, X, RefreshCw, ChevronRight, ChevronLeft, Folder, PlusCircle, Search, Table2, FolderOpen } from 'lucide-react'
import toast from 'react-hot-toast'

// Renders a cell value for display -- JSON object/array columns (like
// pricing_plans.data) used to show as the literal string "[object Object]"
// because String(someObject) just calls its default toString(). This
// pretty-prints them as actual JSON instead.
function displayVal(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
// Converts a cell value into the string an edit textarea/input should show.
function editVal(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v, null, 2)
  return String(v)
}
// Converts an edited string back to whatever type it should be saved as --
// if it looks like JSON (started life as an object/array), parse it back;
// otherwise keep it as plain text. Throws if the user typed invalid JSON
// for a field that needs to stay JSON, so callers can show an error
// instead of silently corrupting the row.
function parseEditedVal(original, editedText) {
  if (original !== null && typeof original === 'object') {
    return JSON.parse(editedText)  // let a bad-JSON error bubble up to the caller
  }
  return editedText
}

function findNode(nodes, path) {
  for (const n of nodes) {
    if (n.path === path) return n
    if (n.children?.length) { const f = findNode(n.children, path); if (f) return f }
  }
  return null
}

function buildOptions(nodes) {
  const opts = []
  for (const n of nodes) {
    if (n.type === 'folder') {
      opts.push({ label: `📁 ${n.name}/`, value: `FOLDER|${n.path}`, isFolder: true })
    } else if (n.type === 'database') {
      for (const t of (n.tables || []))
        opts.push({ label: `🗄 ${n.name} → ${t}`, value: `DB|${n.path}|${t}`, isFolder: false, name: `${n.name} → ${t}` })
    } else {
      const ext = (n.name.split('.').pop() || '').toLowerCase()
      const ico = {csv:'📊',json:'📋',pkl:'🔢',pdf:'📄',py:'🐍',txt:'📝',jsonl:'📋'}[ext] || '📄'
      opts.push({ label: `${ico} ${n.name}`, value: `FILE|${n.path}`, isFolder: false, name: n.name })
    }
  }
  return opts
}

// ── Data Viewer ───────────────────────────────────────────────────────────────
function DataViewer({ filePath, table, name, onClose }) {
  const [cols,      setCols]      = useState([])
  const [rows,      setRows]      = useState([])
  const [srcInfo,   setSrc]       = useState('')
  const [isRaw,     setIsRaw]     = useState(false)
  const [loading,   setLoad]      = useState(true)
  const [err,       setErr]       = useState('')
  const [editIdx,   setEIdx]      = useState(null)
  const [editRow,   setERow]      = useState(null)
  const [saving,    setSaving]    = useState(false)
  const [addingRow, setAddingRow] = useState(false)
  const [newRow,    setNewRow]    = useState({})

  const load = useCallback(async (signal) => {
    setLoad(true); setErr(''); setCols([]); setRows([]); setIsRaw(false)
    setAddingRow(false); setNewRow({})
    try {
      const { data } = await fmRead(filePath, table || '')
      if (signal?.aborted) return
      setCols(data.columns || [])
      setRows(data.rows    || [])
      setSrc(data.source   || '')
      setIsRaw(data.display === 'raw')
    } catch (e) {
      if (signal?.aborted) return
      setErr(e.response?.data?.detail || e.message || 'Failed to load')
    } finally {
      if (!signal?.aborted) setLoad(false)
    }
  }, [filePath, table])

  useEffect(() => {
    const ctrl = new AbortController()
    load(ctrl.signal)
    return () => ctrl.abort()
  }, [load])

  const applyEdit = () => {
    setRows(r => r.map((row, i) => i === editIdx ? editRow : row))
    setEIdx(null); setERow(null)
  }

  const deleteRow = async i => {
    const pkCol = cols.includes('id') ? 'id' : cols[0]
    if (!table) { setRows(r => r.filter((_, j) => j !== i)); return }
    try {
      await fmDeleteRow({ path: filePath, table, source: 'sqlite', row_id: rows[i][pkCol], pk_col: pkCol })
      setRows(r => r.filter((_, j) => j !== i))
      toast.success('Row deleted')
    } catch { toast.error('Delete failed') }
  }

  const confirmNewRow = () => {
    setRows(r => [...r, newRow])
    setAddingRow(false)
    setNewRow({})
    toast.success('Row added — click Save to persist')
  }

  const saveAll = async () => {
    setSaving(true)
    try {
      await fmSave({ path: filePath, table: table || '', rows, source: srcInfo.split(' ')[0] || '' })
      toast.success('Saved')
    } catch (e) { toast.error(e.response?.data?.detail || 'Save failed') }
    finally { setSaving(false) }
  }

  return (
    <div className="card card-flat" style={{marginTop:16}}>
      {/* Header */}
      <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:14,flexWrap:'wrap'}}>
        <Database size={16} color="var(--brand)"/>
        <strong style={{fontSize:'.92rem'}}>{name}</strong>
        <code style={{fontSize:'.7rem',color:'var(--text-3)'}}>{filePath}</code>
        {!loading && !err && (
          <span style={{fontSize:'.72rem',color:'var(--text-3)'}}>
            · {rows.length} rows · {srcInfo}
          </span>
        )}
        <div style={{flex:1}}/>
        <button className="btn btn-outline btn-sm" onClick={load}><RefreshCw size={13}/></button>
        {!err && !isRaw && (<>
          <button
            className="btn btn-outline btn-sm"
            onClick={() => {
              setNewRow(Object.fromEntries(cols.map(c => [c, ''])))
              setAddingRow(true)
            }}
            disabled={addingRow || loading}
          >
            <PlusCircle size={13}/> Add Row
          </button>
          <button className="btn btn-primary btn-sm" onClick={saveAll} disabled={saving||loading}>
            <Save size={13}/>{saving?' Saving…':' Save'}
          </button>
        </>)}
        <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={13}/> Close</button>
      </div>

      {loading && <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}><span className="spinner"/> Loading…</div>}

      {!loading && err && (
        <div className="alert alert-error" style={{margin:8}}>
          {err}
          <button className="btn btn-ghost btn-xs" style={{marginLeft:8}} onClick={load}>Retry</button>
        </div>
      )}

      {!loading && !err && rows.length === 0 && !addingRow && (
        <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>
          No data found.
          {!isRaw && (
            <button className="btn btn-outline btn-sm" style={{marginLeft:12}}
              onClick={() => {
                setNewRow(Object.fromEntries(cols.map(c => [c, ''])))
                setAddingRow(true)
              }}>
              <PlusCircle size={13}/> Add first row
            </button>
          )}
        </div>
      )}

      {/* RAW view for CSV and PDF */}
      {!loading && !err && rows.length > 0 && isRaw && (
        <div style={{
          fontFamily:'monospace', fontSize:'.78rem', lineHeight:1.7,
          whiteSpace:'pre-wrap', wordBreak:'break-word',
          padding:'14px 16px', background:'var(--surface-2)',
          borderRadius:'var(--r-md)', maxHeight:600, overflowY:'auto',
          border:'1px solid var(--border)',
        }}>
          {rows.map((row, i) => {
            const hasPdf = Object.prototype.hasOwnProperty.call(row, 'page') &&
                           Object.prototype.hasOwnProperty.call(row, 'text')
            const prevPage = i > 0 ? rows[i - 1].page : null
            const showBreak = hasPdf && row.page !== prevPage
            const lineText = hasPdf ? String(row.text || '') : String(row.line || Object.values(row)[0] || '')
            return (
              <React.Fragment key={i}>
                {showBreak && (
                  <div style={{color:'var(--brand)',fontWeight:700,
                    marginTop: i > 0 ? 16 : 0, marginBottom:4,
                    fontSize:'.7rem',letterSpacing:'.06em'}}>
                    {'── Page ' + row.page + ' ──'}
                  </div>
                )}
                <div>{lineText}</div>
              </React.Fragment>
            )
          })}
        </div>
      )}

      {/* TABLE view for JSON, CSV (tabular), DB */}
      {!loading && !err && (rows.length > 0 || addingRow) && !isRaw && (
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse',fontSize:'.78rem'}}>
            <thead>
              <tr style={{background:'var(--surface-2)',borderBottom:'2px solid var(--border)'}}>
                <th style={{padding:'8px 10px',width:90,textAlign:'left'}}>Actions</th>
                {cols.map(c => (
                  <th key={c} style={{padding:'8px 10px',textAlign:'left',whiteSpace:'nowrap',
                    color:'var(--text-2)',fontWeight:600}}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>

              {/* ── New row input ── */}
              {addingRow && (
                <tr style={{borderBottom:'1px solid var(--border)',background:'rgba(200,150,62,.08)'}}>
                  <td style={{padding:'6px 10px',whiteSpace:'nowrap'}}>
                    <div style={{display:'flex',gap:4}}>
                      <button className="btn btn-primary btn-xs" onClick={confirmNewRow} title="Confirm">
                        <Check size={11}/>
                      </button>
                      <button className="btn btn-ghost btn-xs" onClick={() => { setAddingRow(false); setNewRow({}) }} title="Cancel">
                        <X size={11}/>
                      </button>
                    </div>
                  </td>
                  {cols.map(c => (
                    <td key={c} style={{padding:'6px 10px'}}>
                      <input
                        className="input input-sm"
                        style={{width:'100%',minWidth:70}}
                        placeholder={c}
                        value={newRow[c] ?? ''}
                        onChange={e => setNewRow(r => ({...r,[c]:e.target.value}))}
                      />
                    </td>
                  ))}
                </tr>
              )}

              {/* ── Existing rows ── */}
              {rows.map((row, i) => (
                <tr key={i} style={{borderBottom:'1px solid var(--border)',
                  background: i % 2 ? 'var(--surface-2)' : 'transparent'}}>
                  <td style={{padding:'6px 10px',whiteSpace:'nowrap'}}>
                    {editIdx === i ? (
                      <div style={{display:'flex',gap:4}}>
                        <button className="btn btn-primary btn-xs" onClick={applyEdit}><Check size={11}/></button>
                        <button className="btn btn-ghost btn-xs" onClick={() => {setEIdx(null);setERow(null)}}><X size={11}/></button>
                      </div>
                    ) : (
                      <div style={{display:'flex',gap:4}}>
                        <button className="btn btn-outline btn-xs" onClick={() => {setEIdx(i);setERow({...row})}}><Edit2 size={11}/></button>
                        <button className="btn btn-danger btn-xs" onClick={() => deleteRow(i)}><Trash2 size={11}/></button>
                      </div>
                    )}
                  </td>
                  {cols.map(c => (
                    <td key={c} style={{padding:'6px 10px',maxWidth:220,overflow:'hidden',
                      textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                      {editIdx === i ? (
                        typeof row[c] === 'object' && row[c] !== null ? (
                          <textarea className="input input-sm" style={{width:'100%',minWidth:180,minHeight:60,fontFamily:'monospace',fontSize:'.75rem'}}
                            defaultValue={editVal(row[c])}
                            onChange={e => setERow(r => ({...r,[c]:e.target.value, [`__raw_${c}`]:true}))}/>
                        ) : (
                          <input className="input input-sm" style={{width:'100%',minWidth:70}}
                            value={editRow[c] ?? ''}
                            onChange={e => setERow(r => ({...r,[c]:e.target.value}))}/>
                        )
                      ) : (
                        <span title={displayVal(row[c]).slice(0,300)}>
                          {displayVal(row[c]).slice(0,150)}
                        </span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Tables Browser (TalentIQ-style: table list -> paginated rows) ─────────────
function TableRowsGrid({ table, pkColumn, onBack }) {
  const [cols,      setCols]      = useState([])
  const [rows,      setRows]      = useState([])
  const [total,     setTotal]     = useState(0)
  const [page,      setPage]      = useState(1)
  const [pageSize]                = useState(50)
  const [search,    setSearch]    = useState('')
  const [loading,   setLoad]      = useState(true)
  const [err,       setErr]       = useState('')
  const [editPk,    setEditPk]    = useState(null)
  const [editRow,   setERow]      = useState(null)
  const [editOriginal, setEditOriginal] = useState(null)
  const [selected,  setSelected]  = useState(new Set())
  const [addingRow, setAddingRow] = useState(false)
  const [newRow,    setNewRow]    = useState({})
  const [uploading, setUploading] = useState(false)
  const csvInputRef = React.useRef(null)

  const load = useCallback(async () => {
    setLoad(true); setErr('')
    try {
      const { data } = await dbTableRows(table, { page, page_size: pageSize, search: search || undefined })
      setCols(data.columns || [])
      setRows(data.rows || [])
      setTotal(data.total || 0)
      setSelected(new Set())
    } catch (e) {
      setErr(e.response?.data?.detail || e.message || 'Failed to load rows')
    } finally {
      setLoad(false)
    }
  }, [table, page, pageSize, search])

  useEffect(() => { load() }, [load])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const startEdit = row => {
    setEditPk(row[pkColumn])
    setEditOriginal(row)
    // JSON/object columns get pretty-printed into the text box; saveEdit
    // converts them back to real objects before sending, using
    // editOriginal to know which fields need that round-trip.
    setERow(Object.fromEntries(Object.entries(row).map(([k, v]) => [k, editVal(v)])))
  }
  const cancelEdit = () => { setEditPk(null); setERow(null); setEditOriginal(null) }
  const saveEdit = async () => {
    let payload
    try {
      payload = Object.fromEntries(
        Object.entries(editRow).map(([k, v]) => [k, parseEditedVal(editOriginal?.[k], v)])
      )
    } catch (e) {
      toast.error(`Invalid JSON in one of the fields: ${e.message}`)
      return
    }
    try {
      await dbUpdateRow(table, editPk, payload)
      toast.success('Row updated')
      cancelEdit(); load()
    } catch (e) { toast.error(e.response?.data?.detail || 'Update failed') }
  }

  const deleteOne = async row => {
    if (!confirm('Delete this row?')) return
    try {
      await dbDeleteRow(table, row[pkColumn])
      toast.success('Row deleted')
      load()
    } catch (e) { toast.error(e.response?.data?.detail || 'Delete failed') }
  }

  const toggleSelect = pk => {
    setSelected(s => {
      const next = new Set(s)
      next.has(pk) ? next.delete(pk) : next.add(pk)
      return next
    })
  }

  const bulkDelete = async () => {
    if (selected.size === 0) return
    if (!confirm(`Delete ${selected.size} selected row(s)?`)) return
    try {
      await dbBulkDeleteRows(table, Array.from(selected))
      toast.success(`Deleted ${selected.size} row(s)`)
      load()
    } catch (e) { toast.error(e.response?.data?.detail || 'Bulk delete failed') }
  }

  const confirmNewRow = async () => {
    try {
      await dbInsertRow(table, newRow)
      toast.success('Row added')
      setAddingRow(false); setNewRow({})
      setPage(1); load()
    } catch (e) { toast.error(e.response?.data?.detail || 'Insert failed') }
  }

  const handleCsvUpload = async e => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const { data } = await dbUploadCsv(table, file)
      const parts = []
      if (data.inserted) parts.push(`${data.inserted} inserted`)
      if (data.updated) parts.push(`${data.updated} updated`)
      if (data.skipped) parts.push(`${data.skipped} skipped (no ${pkColumn})`)
      if (data.error_count) parts.push(`${data.error_count} failed`)
      const summary = parts.length ? parts.join(', ') : 'Nothing to import'

      if (data.error_count > 0) {
        toast.error(`${summary}. First error: ${data.errors[0]}`)
      } else if (data.unknown_columns?.length) {
        toast.success(`${summary}. Ignored unknown column(s): ${data.unknown_columns.join(', ')}`)
      } else {
        toast.success(summary)
      }
      setPage(1); load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'CSV upload failed')
    } finally {
      setUploading(false)
      if (csvInputRef.current) csvInputRef.current.value = ''
    }
  }

  return (
    <div>
      <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:14,flexWrap:'wrap'}}>
        {onBack && <button className="btn btn-ghost btn-sm" onClick={onBack}><ChevronLeft size={13}/> Tables</button>}
        <Table2 size={16} color="var(--brand)"/>
        <strong style={{fontSize:'.92rem'}}>{table}</strong>
        {!loading && !err && (
          <span style={{fontSize:'.72rem',color:'var(--text-3)'}}>· {total} rows total</span>
        )}
        <div style={{flex:1}}/>
        <div style={{position:'relative'}}>
          <Search size={12} style={{position:'absolute',left:8,top:'50%',transform:'translateY(-50%)',color:'var(--text-3)'}}/>
          <input
            className="input input-sm"
            style={{paddingLeft:26,width:200}}
            placeholder="Search all columns…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
        <button className="btn btn-outline btn-sm" onClick={load}><RefreshCw size={13}/></button>
        <button className="btn btn-outline btn-sm"
          onClick={() => { setNewRow(Object.fromEntries(cols.filter(c=>c!==pkColumn).map(c => [c, '']))); setAddingRow(true) }}
          disabled={addingRow || loading}>
          <PlusCircle size={13}/> Add Row
        </button>
        <input ref={csvInputRef} type="file" accept=".csv" style={{display:'none'}} onChange={handleCsvUpload}/>
        <button className="btn btn-outline btn-sm"
          onClick={() => csvInputRef.current?.click()}
          disabled={uploading || loading}
          title={`CSV must include a '${pkColumn}' column -- matching rows are updated, new ones inserted`}>
          {uploading ? <><span className="spinner spinner-sm"/> Uploading…</> : <><Upload size={13}/> Upload CSV</>}
        </button>
        {selected.size > 0 && (
          <button className="btn btn-danger btn-sm" onClick={bulkDelete}>
            <Trash2 size={13}/> Delete {selected.size} selected
          </button>
        )}
      </div>

      {loading && <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}><span className="spinner"/> Loading…</div>}
      {!loading && err && (
        <div className="alert alert-error" style={{margin:8}}>
          {err}
          <button className="btn btn-ghost btn-xs" style={{marginLeft:8}} onClick={load}>Retry</button>
        </div>
      )}

      {!loading && !err && rows.length === 0 && !addingRow && (
        <div style={{padding:40,textAlign:'center',color:'var(--text-3)'}}>
          {search ? 'No rows match your search.' : 'No rows in this table yet.'}
        </div>
      )}

      {!loading && !err && (rows.length > 0 || addingRow) && (
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse',fontSize:'.78rem'}}>
            <thead>
              <tr style={{background:'var(--surface-2)',borderBottom:'2px solid var(--border)'}}>
                <th style={{padding:'8px 10px',width:24}}></th>
                <th style={{padding:'8px 10px',width:90,textAlign:'left'}}>Actions</th>
                {cols.map(c => (
                  <th key={c} style={{padding:'8px 10px',textAlign:'left',whiteSpace:'nowrap',
                    color:'var(--text-2)',fontWeight:600}}>
                    {c}{c===pkColumn && <span title="Primary key" style={{marginLeft:4,opacity:.5}}>🔑</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {addingRow && (
                <tr style={{borderBottom:'1px solid var(--border)',background:'rgba(200,150,62,.08)'}}>
                  <td/>
                  <td style={{padding:'6px 10px',whiteSpace:'nowrap'}}>
                    <div style={{display:'flex',gap:4}}>
                      <button className="btn btn-primary btn-xs" onClick={confirmNewRow} title="Confirm"><Check size={11}/></button>
                      <button className="btn btn-ghost btn-xs" onClick={() => {setAddingRow(false);setNewRow({})}} title="Cancel"><X size={11}/></button>
                    </div>
                  </td>
                  {cols.map(c => (
                    <td key={c} style={{padding:'6px 10px'}}>
                      {c === pkColumn ? (
                        <input className="input input-sm" style={{width:'100%',minWidth:70}}
                          placeholder={`${c} (optional)`}
                          value={newRow[c] ?? ''}
                          onChange={e => setNewRow(r => ({...r,[c]:e.target.value}))}/>
                      ) : (
                        <input className="input input-sm" style={{width:'100%',minWidth:70}}
                          placeholder={c}
                          value={newRow[c] ?? ''}
                          onChange={e => setNewRow(r => ({...r,[c]:e.target.value}))}/>
                      )}
                    </td>
                  ))}
                </tr>
              )}
              {rows.map((row, i) => {
                const pk = row[pkColumn]
                const isEditing = editPk === pk
                return (
                  <tr key={pk ?? i} style={{borderBottom:'1px solid var(--border)',
                    background: selected.has(pk) ? 'rgba(59,130,246,.08)' : (i % 2 ? 'var(--surface-2)' : 'transparent')}}>
                    <td style={{padding:'6px 10px',textAlign:'center'}}>
                      <input type="checkbox" checked={selected.has(pk)} onChange={() => toggleSelect(pk)}/>
                    </td>
                    <td style={{padding:'6px 10px',whiteSpace:'nowrap'}}>
                      {isEditing ? (
                        <div style={{display:'flex',gap:4}}>
                          <button className="btn btn-primary btn-xs" onClick={saveEdit}><Check size={11}/></button>
                          <button className="btn btn-ghost btn-xs" onClick={cancelEdit}><X size={11}/></button>
                        </div>
                      ) : (
                        <div style={{display:'flex',gap:4}}>
                          <button className="btn btn-outline btn-xs" onClick={() => startEdit(row)}><Edit2 size={11}/></button>
                          <button className="btn btn-danger btn-xs" onClick={() => deleteOne(row)}><Trash2 size={11}/></button>
                        </div>
                      )}
                    </td>
                    {cols.map(c => (
                      <td key={c} style={{padding:'6px 10px',maxWidth:220,overflow:'hidden',
                        textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                        {isEditing && c !== pkColumn ? (
                          typeof editOriginal?.[c] === 'object' && editOriginal[c] !== null ? (
                            <textarea className="input input-sm" style={{width:'100%',minWidth:220,minHeight:80,fontFamily:'monospace',fontSize:'.75rem',whiteSpace:'pre'}}
                              value={editRow[c] ?? ''}
                              onChange={e => setERow(r => ({...r,[c]:e.target.value}))}/>
                          ) : (
                            <input className="input input-sm" style={{width:'100%',minWidth:70}}
                              value={editRow[c] ?? ''}
                              onChange={e => setERow(r => ({...r,[c]:e.target.value}))}/>
                          )
                        ) : (
                          <span title={displayVal(row[c]).slice(0,300)}>
                            {displayVal(row[c]).slice(0,150)}
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !err && totalPages > 1 && (
        <div style={{display:'flex',alignItems:'center',gap:10,justifyContent:'center',marginTop:14}}>
          <button className="btn btn-outline btn-xs" disabled={page<=1} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={12}/></button>
          <span style={{fontSize:'.78rem',color:'var(--text-3)'}}>Page {page} of {totalPages}</span>
          <button className="btn btn-outline btn-xs" disabled={page>=totalPages} onClick={()=>setPage(p=>p+1)}><ChevronRight size={12}/></button>
        </div>
      )}
    </div>
  )
}

// Groups table names into module categories by keyword matching -- works
// against whatever tables actually exist rather than a hardcoded list, so
// it stays correct as new modules/migrations add tables over time.
//
// `top` is the outer category shown in the left pane. `sub` is an optional
// nested subgroup within it (used for Administration, which contains two
// named subgroups rather than one flat table list). Rules are checked in
// order, first match wins -- more specific patterns (e.g. accounting_*)
// must come before looser ones (e.g. "customer") that would otherwise
// wrongly grab them first.
const _CATEGORY_RULES = [
  { top: 'Admin', sub: 'Auth & Licence',
    test: n => /^(users|licence_records|roles|permissions|role_permissions|user_roles|password_reset_tokens)$/.test(n) },
  { top: 'Admin', sub: 'AI Settings',
    test: n => /groq/.test(n) },
  { top: 'Admin', sub: 'Pricing & Plans',
    test: n => /pricing/.test(n) },
  // Purchases & Vendors checked before Sales & Customers -- otherwise
  // accounting_suppliers/accounting_documents/accounting_line_items would
  // never be reached (first-match-wins), since nothing here overlaps the
  // other way (Sales patterns don't match "supplier"/"line_item").
  { top: 'Accounting', sub: 'Purchases & Vendors',
    test: n => /(accounting_supplier|accounting_document|accounting_line_item)/.test(n) },
  { top: 'Accounting', sub: 'Sales & Customers',
    test: n => /(accounting_customer|^customers$|^invoices$|invoice_item|business_detail)/.test(n) },
  { top: 'Accounting', sub: 'Transactions & Reconciliation',
    test: n => /(^transaction|reconciliation_session|session_file|account_balance)/.test(n) },
  { top: 'Accounting', sub: 'Companies & Reference Data',
    test: n => /(^companies$|company_alias|knowledge_base|rdr_rules|chart_of_accounts|classifier_cache)/.test(n) },
  { top: 'Payroll', sub: null, test: n => /(payroll|payslip|stp_submission)/.test(n) },
  { top: 'Trading', sub: null, test: n => /trading/.test(n) },
  { top: 'Lending', sub: null, test: n => /lending/.test(n) },
]

// Admin is always shown first; these next four are the primary business
// modules and stay in this fixed order; anything else falls back to
// alphabetical, with "Other" always last.
const _TOP_ORDER = ['Admin', 'Accounting', 'Trading', 'Lending', 'Payroll']

function categorize(tableName) {
  const hit = _CATEGORY_RULES.find(r => r.test(tableName))
  return hit ? { top: hit.top, sub: hit.sub } : { top: 'Other', sub: null }
}

function TablesTab() {
  const [tables,       setTables]      = useState([])
  const [loading,      setLoad]        = useState(true)
  const [openTable,    setOpen]        = useState(null)
  const [mode,         setMode]        = useState('browser')  // 'browser' | 'query'
  const [collapsedTop, setCollapsedTop] = useState(new Set())
  const [collapsedSub, setCollapsedSub] = useState(new Set())

  const load = async () => {
    setLoad(true)
    try {
      const { data } = await dbListTables()
      setTables(data || [])
      if (data?.length) {
        const openT = openTable || data[0]
        if (!openTable) setOpen(openT)
        // Start with every top-level category (and subgroup) collapsed
        // except the path to whichever table ends up open, so the list
        // isn't one long wall on first load.
        const { top: keepTop, sub: keepSub } = categorize(openT.table)
        const allTops = new Set(data.map(t => categorize(t.table).top))
        allTops.delete(keepTop)
        setCollapsedTop(allTops)
        const allSubs = new Set(
          data.map(t => { const c = categorize(t.table); return c.sub ? `${c.top}::${c.sub}` : null }).filter(Boolean)
        )
        if (keepSub) allSubs.delete(`${keepTop}::${keepSub}`)
        setCollapsedSub(allSubs)
      }
    } catch { toast.error('Failed to load tables') }
    finally { setLoad(false) }
  }
  useEffect(() => { load() }, [])

  // Nested structure: [{ top, subs: [{ sub, items }] }]
  // Tables with no subgroup land in a single implicit sub with sub=null,
  // which the renderer treats as "no extra sub-header, just list them".
  const grouped = React.useMemo(() => {
    const tops = {}
    for (const t of tables) {
      const { top, sub } = categorize(t.table)
      if (!tops[top]) tops[top] = {}
      const subKey = sub || '__flat__'
      if (!tops[top][subKey]) tops[top][subKey] = { sub, items: [] }
      tops[top][subKey].items.push(t)
    }
    const topEntries = Object.entries(tops).map(([top, subMap]) => ({
      top, subs: Object.values(subMap),
    }))
    return topEntries.sort((a, b) => {
      const ai = _TOP_ORDER.indexOf(a.top), bi = _TOP_ORDER.indexOf(b.top)
      if (a.top === 'Other') return 1
      if (b.top === 'Other') return -1
      if (ai !== -1 && bi !== -1) return ai - bi
      if (ai !== -1) return -1
      if (bi !== -1) return 1
      return a.top.localeCompare(b.top)
    })
  }, [tables])

  const toggleTop = top => {
    setCollapsedTop(s => { const next = new Set(s); next.has(top) ? next.delete(top) : next.add(top); return next })
  }
  const toggleSub = key => {
    setCollapsedSub(s => { const next = new Set(s); next.has(key) ? next.delete(key) : next.add(key); return next })
  }

  return (
    <div className="card card-flat" style={{padding:0,overflow:'hidden'}}>
      {/* Sub-tabs: Table Browser / SQL Query */}
      <div style={{display:'flex',alignItems:'center',borderBottom:'1px solid var(--border)',padding:'10px 16px',gap:8}}>
        <button className={`tab-btn${mode==='browser'?' active':''}`} onClick={()=>setMode('browser')} style={{fontSize:'.82rem'}}>
          <Table2 size={13} style={{marginRight:5,verticalAlign:'middle'}}/> Table Browser
        </button>
        <button className={`tab-btn${mode==='query'?' active':''}`} onClick={()=>setMode('query')} style={{fontSize:'.82rem'}}>
          SQL Query
        </button>
        <div style={{flex:1}}/>
        <span style={{fontSize:'.78rem',color:'var(--text-3)'}}>Tables ({tables.length})</span>
        <button className="btn btn-outline btn-sm" onClick={load}><RefreshCw size={13}/></button>
      </div>

      {mode === 'query' ? (
        <SqlQueryPane />
      ) : (
        <div style={{display:'flex',minHeight:520}}>
          {/* Left pane: categorized table list */}
          <div style={{width:270,borderRight:'1px solid var(--border)',overflowY:'auto',maxHeight:640,flexShrink:0}}>
            {loading && <div style={{padding:20,textAlign:'center',color:'var(--text-3)',fontSize:'.8rem'}}><span className="spinner"/> Loading…</div>}
            {!loading && grouped.map(({ top, subs }) => {
              const topCount = subs.reduce((s, g) => s + g.items.length, 0)
              return (
                <div key={top}>
                  <button
                    onClick={() => toggleTop(top)}
                    style={{width:'100%',display:'flex',alignItems:'center',gap:6,padding:'8px 12px',
                      background:'var(--surface-2)',border:'none',borderBottom:'1px solid var(--border)',
                      cursor:'pointer',fontSize:'.72rem',fontWeight:700,textTransform:'uppercase',
                      letterSpacing:'.04em',color:'var(--text-2)',textAlign:'left'}}>
                    <ChevronRight size={11} style={{flexShrink:0,transform: collapsedTop.has(top) ? 'none' : 'rotate(90deg)', transition:'transform .12s'}}/>
                    <span style={{textAlign:'left'}}>{top}</span>
                    <span style={{marginLeft:'auto',fontWeight:400,color:'var(--text-3)'}}>{topCount}</span>
                  </button>

                  {!collapsedTop.has(top) && subs.map(({ sub, items }) => {
                    const subKey = `${top}::${sub}`
                    const isNamedSub = !!sub
                    return (
                      <div key={subKey}>
                        {isNamedSub && (
                          <button
                            onClick={() => toggleSub(subKey)}
                            style={{width:'100%',display:'flex',alignItems:'center',gap:6,padding:'6px 12px 6px 22px',
                              background:'transparent',border:'none',borderBottom:'1px solid var(--border)',
                              cursor:'pointer',fontSize:'.7rem',fontWeight:600,color:'var(--text-2)',textAlign:'left'}}>
                            <ChevronRight size={10} style={{flexShrink:0,transform: collapsedSub.has(subKey) ? 'none' : 'rotate(90deg)', transition:'transform .12s'}}/>
                            <span style={{textAlign:'left'}}>{sub}</span>
                            <span style={{marginLeft:'auto',fontWeight:400,color:'var(--text-3)'}}>{items.length}</span>
                          </button>
                        )}
                        {(!isNamedSub || !collapsedSub.has(subKey)) && items.map(t => (
                          <button key={t.table}
                            onClick={() => setOpen(t)}
                            style={{width:'100%',display:'flex',flexDirection:'column',alignItems:'flex-start',gap:2,
                              padding:`8px 12px 8px ${isNamedSub ? 38 : 26}px`,border:'none',borderBottom:'1px solid var(--border)',
                              background: openTable?.table === t.table ? 'rgba(59,130,246,.10)' : 'transparent',
                              cursor:'pointer',textAlign:'left'}}>
                            <strong style={{fontSize:'.8rem',textAlign:'left'}}>{t.table}</strong>
                            <span style={{fontSize:'.7rem',color:'var(--text-3)',textAlign:'left'}}>
                              {t.rows === null ? 'unknown rows' : `${t.rows} row${t.rows===1?'':'s'}`}
                            </span>
                            {t.note && <span style={{fontSize:'.68rem',color:'var(--warning,#b45309)',textAlign:'left'}}>{t.note}</span>}
                          </button>
                        ))}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>

          {/* Right pane: selected table's content */}
          <div style={{flex:1,padding:16,overflowX:'auto'}}>
            {!openTable && (
              <div style={{padding:60,textAlign:'center',color:'var(--text-3)'}}>
                <Table2 size={28} style={{opacity:.3,marginBottom:8}}/>
                <div>Select a table</div>
                <div style={{fontSize:'.78rem'}}>Click any table on the left to browse its records</div>
              </div>
            )}
            {openTable && (
              <TableRowsGrid key={openTable.table} table={openTable.table} pkColumn={openTable.pk_column || 'id'} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── SQL Query pane (read-only SELECT passthrough) ──────────────────────────────
function SqlQueryPane() {
  const [sql, setSql]         = useState('SELECT * FROM rdr_rules LIMIT 50;')
  const [cols, setCols]       = useState([])
  const [rows, setRows]       = useState([])
  const [running, setRunning] = useState(false)
  const [err, setErr]         = useState('')
  const [ran, setRan]         = useState(false)

  const run = async () => {
    setRunning(true); setErr('')
    try {
      const { data } = await dbRunQuery(sql)
      setCols(data.columns || [])
      setRows(data.rows || [])
      setRan(true)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message || 'Query failed')
      setCols([]); setRows([])
    } finally {
      setRunning(false)
    }
  }

  return (
    <div style={{padding:16}}>
      <p style={{fontSize:'.78rem',color:'var(--text-3)',marginTop:0}}>
        Read-only — only <code>SELECT</code> statements are allowed here.
      </p>
      <textarea
        className="input"
        style={{width:'100%',minHeight:100,fontFamily:'monospace',fontSize:'.82rem'}}
        value={sql}
        onChange={e => setSql(e.target.value)}
        spellCheck={false}
      />
      <div style={{marginTop:8}}>
        <button className="btn btn-primary btn-sm" onClick={run} disabled={running || !sql.trim()}>
          {running ? 'Running…' : 'Run Query'}
        </button>
      </div>

      {err && <div className="alert alert-error" style={{marginTop:12}}>{err}</div>}

      {ran && !err && (
        <div style={{marginTop:14}}>
          <div style={{fontSize:'.78rem',color:'var(--text-3)',marginBottom:8}}>{rows.length} row(s)</div>
          {rows.length > 0 && (
            <div style={{overflowX:'auto'}}>
              <table style={{width:'100%',borderCollapse:'collapse',fontSize:'.78rem'}}>
                <thead>
                  <tr style={{background:'var(--surface-2)',borderBottom:'2px solid var(--border)'}}>
                    {cols.map(c => <th key={c} style={{padding:'8px 10px',textAlign:'left',whiteSpace:'nowrap'}}>{c}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i} style={{borderBottom:'1px solid var(--border)',background: i%2 ? 'var(--surface-2)' : 'transparent'}}>
                      {cols.map(c => (
                        <td key={c} style={{padding:'6px 10px',maxWidth:260,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                          {displayVal(row[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Files Tab (existing folder/file browser) ───────────────────────────────────
function FilesTab() {
  const [tree,     setTree]     = useState([])
  const [treeLoad, setTreeLoad] = useState(true)
  const [crumbs,   setCrumbs]   = useState([])
  const [openFile, setOpenFile] = useState(null)

  const loadTree = async () => {
    setTreeLoad(true)
    try {
      const { data } = await fmTree()
      // The Postgres node is handled by the dedicated Tables tab now --
      // filter it out here so it isn't shown twice.
      setTree((data.tree || []).filter(n => n.path !== '__postgres_db__'))
    } catch { toast.error('Failed to load file list') }
    finally { setTreeLoad(false) }
  }
  useEffect(() => { loadTree() }, [])

  const currentNodes = React.useMemo(() => {
    if (!crumbs.length) return tree
    const node = findNode(tree, crumbs[crumbs.length - 1].path)
    return node?.children || []
  }, [tree, crumbs])

  const options     = buildOptions(currentNodes)
  const fileCount   = options.filter(o => !o.isFolder).length
  const folderCount = options.filter(o =>  o.isFolder).length

  const handleChange = e => {
    const v = e.target.value
    if (!v) { setOpenFile(null); return }
    if (v.startsWith('FOLDER|')) {
      const fp   = v.slice(7)
      const node = findNode(tree, fp)
      if (node) { setCrumbs(c => [...c, {name: node.name, path: fp}]); setOpenFile(null) }
      e.target.value = ''
      return
    }
    if (v.startsWith('DB|')) {
      const parts = v.split('|')
      const opt   = options.find(o => o.value === v)
      setOpenFile({ filePath: parts[1], table: parts[2], name: opt?.name || parts[2] })
      return
    }
    if (v.startsWith('FILE|')) {
      const fp  = v.slice(5)
      const opt = options.find(o => o.value === v)
      setOpenFile({ filePath: fp, table: '', name: opt?.name || fp.split('/').pop() })
      return
    }
  }

  const goTo   = i  => { setCrumbs(c => c.slice(0, i + 1)); setOpenFile(null) }
  const goRoot = () => { setCrumbs([]); setOpenFile(null) }
  const goBack = () => { setCrumbs(c => c.slice(0, -1)); setOpenFile(null) }

  return (
    <div>
      <div className="card card-flat">
        {/* Breadcrumb */}
        <div style={{display:'flex',alignItems:'center',gap:4,marginBottom:10,
          fontSize:'.82rem',flexWrap:'wrap'}}>
          <button className="btn btn-ghost btn-xs" onClick={goRoot}>
            <Folder size={12}/> Root
          </button>
          {crumbs.map((c, i) => (
            <React.Fragment key={i}>
              <ChevronRight size={12} color="var(--text-3)"/>
              <button className="btn btn-ghost btn-xs"
                style={{fontWeight: i === crumbs.length - 1 ? 700 : 400}}
                onClick={() => goTo(i)}>
                {c.name}
              </button>
            </React.Fragment>
          ))}
        </div>

        {/* Dropdown */}
        <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
          {crumbs.length > 0 && (
            <button className="btn btn-outline btn-sm" onClick={goBack}>← Back</button>
          )}
          <select
            key={crumbs.map(c => c.path).join('>')}
            className="input"
            style={{flex:1,minWidth:260,maxWidth:620}}
            defaultValue=""
            onChange={handleChange}
            disabled={treeLoad}
          >
            <option value="">
              {treeLoad ? 'Loading…' : `— ${fileCount} file(s) · ${folderCount} folder(s) —`}
            </option>
            {options.map((opt, i) => (
              <option key={i} value={opt.value} style={{fontWeight: opt.isFolder ? 700 : 400}}>
                {opt.label}
              </option>
            ))}
          </select>
          {openFile && (
            <button className="btn btn-ghost btn-sm" onClick={() => setOpenFile(null)}>
              <X size={13}/> Close
            </button>
          )}
          <button className="btn btn-outline btn-sm"
            onClick={() => { setCrumbs([]); setOpenFile(null); loadTree() }}>
            <RefreshCw size={13}/> Refresh
          </button>
        </div>
        <p style={{color:'var(--text-3)',fontSize:'.8rem',marginTop:8}}>
          Select 📁 to enter a folder · select a file to view, edit, add or delete records
        </p>
      </div>

      {openFile && (
        <DataViewer
          key={openFile.filePath + ':' + (openFile.table || '')}
          filePath={openFile.filePath}
          table={openFile.table}
          name={openFile.name}
          onClose={() => setOpenFile(null)}
        />
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function FileManagerPage() {
  const [tab, setTab] = useState('files')

  return (
    <div>
      <div style={{display:'flex',alignItems:'center',gap:12,marginBottom:20}}>
        <div>
          <h2 style={{margin:0}}>Data Manager</h2>
          <p style={{color:'var(--text-3)',fontSize:'.85rem',margin:'4px 0 0'}}>
            Browse and edit files, and every table in the application database
          </p>
        </div>
      </div>

      <div className="tabs-bar" style={{marginBottom:20}}>
        <button className={`tab-btn${tab==='files'?' active':''}`} onClick={() => setTab('files')}>
          <FolderOpen size={13} style={{marginRight:5,verticalAlign:'middle'}}/> Files
        </button>
        <button className={`tab-btn${tab==='tables'?' active':''}`} onClick={() => setTab('tables')}>
          <Table2 size={13} style={{marginRight:5,verticalAlign:'middle'}}/> Tables
        </button>
      </div>

      {tab === 'files' ? <FilesTab /> : <TablesTab />}
    </div>
  )
}