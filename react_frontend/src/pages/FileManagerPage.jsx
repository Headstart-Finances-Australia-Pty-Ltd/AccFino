import React, { useEffect, useState, useCallback } from 'react'
import { fmTree, fmRead, fmSave, fmDeleteRow } from '../lib/api'
import { Database, Save, Trash2, Edit2, Check, X, RefreshCw, ChevronRight, Folder, PlusCircle } from 'lucide-react'
import toast from 'react-hot-toast'

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
                        <input className="input input-sm" style={{width:'100%',minWidth:70}}
                          value={editRow[c] ?? ''}
                          onChange={e => setERow(r => ({...r,[c]:e.target.value}))}/>
                      ) : (
                        <span title={String(row[c] ?? '').slice(0,300)}>
                          {String(row[c] ?? '').slice(0,150)}
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

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function FileManagerPage() {
  const [tree,     setTree]     = useState([])
  const [treeLoad, setTreeLoad] = useState(true)
  const [crumbs,   setCrumbs]   = useState([])
  const [openFile, setOpenFile] = useState(null)

  const loadTree = async () => {
    setTreeLoad(true)
    try {
      const { data } = await fmTree()
      setTree(data.tree || [])
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
      <div style={{display:'flex',alignItems:'center',gap:12,marginBottom:20}}>
        <div>
          <h2 style={{margin:0}}>File Manager</h2>
          <p style={{color:'var(--text-3)',fontSize:'.85rem',margin:'4px 0 0'}}>
            Browse, edit, add and delete records in files and tables
          </p>
        </div>
        <div style={{flex:1}}/>
        <button className="btn btn-outline btn-sm"
          onClick={() => { setCrumbs([]); setOpenFile(null); loadTree() }}>
          <RefreshCw size={13}/> Refresh
        </button>
      </div>

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
              {treeLoad ? 'Loading…' : `— ${fileCount} file(s)/table(s)  ·  ${folderCount} folder(s) —`}
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
        </div>
        <p style={{color:'var(--text-3)',fontSize:'.8rem',marginTop:8}}>
          Select 📁 to enter a folder · select a file or table to view, edit, add or delete records
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