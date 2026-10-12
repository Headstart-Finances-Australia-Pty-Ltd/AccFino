import React, { useEffect, useRef, useState, useCallback } from 'react'
import { Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { adminGetForceDelete } from '../../lib/adminApi.js'
import { errMsg } from '../../lib/platformHttp.js'

export const FORCE_DELETE_EVENT = 'accfino:force-delete-changed'

/** Is the platform "Force delete" switch (Admin > Modules Management > Platform features) on? Off until an administrator ticks it. */
export function useForceDeleteSwitch() {
  const [enabled, setEnabled] = useState(false)
  const load = useCallback(() => { adminGetForceDelete().then(r => setEnabled(!!r.data?.enabled)).catch(() => setEnabled(false)) }, [])
  useEffect(() => {
    load()
    window.addEventListener(FORCE_DELETE_EVENT, load)
    return () => window.removeEventListener(FORCE_DELETE_EVENT, load)
  }, [load])
  return enabled
}

/** Row selection for a table: `ids` = the ids of the rows currently shown. */
export function useRowSelection(ids) {
  const [selected, setSelected] = useState(() => new Set())
  // forget ids that are no longer in the table (deleted / filtered out)
  useEffect(() => {
    setSelected(prev => {
      const keep = new Set([...prev].filter(id => ids.includes(id)))
      return keep.size === prev.size ? prev : keep
    })
  }, [ids.join(',')]) // eslint-disable-line
  const allSelected = ids.length > 0 && ids.every(id => selected.has(id))
  const someSelected = ids.some(id => selected.has(id))
  const toggle = id => setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(ids))
  const clear = () => setSelected(new Set())
  return { selected, count: selected.size, allSelected, someSelected, toggle, toggleAll, clear, ids: [...selected] }
}

/** The single checkbox in the table header: ticks / unticks every row. Shows the "some selected" (dash) state. */
export function SelectAllCheckbox({ sel, label = 'Select all rows' }) {
  const ref = useRef(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = sel.someSelected && !sel.allSelected }, [sel.someSelected, sel.allSelected])
  return <input ref={ref} type="checkbox" aria-label={label} title={label} checked={sel.allSelected} onChange={sel.toggleAll} style={{ width: 15, height: 15, cursor: 'pointer' }} />
}

export function RowCheckbox({ sel, id, label }) {
  return <input type="checkbox" aria-label={label || `Select row ${id}`} checked={sel.selected.has(id)} onChange={() => sel.toggle(id)} style={{ width: 15, height: 15, cursor: 'pointer' }} />
}

/** "Force delete selected (n)": NOT SHOWN AT ALL while the platform switch is off. When on, clickable only while at least one row is ticked. */
export function ForceDeleteButton({ enabled, count, busy, onClick, noun = 'row' }) {
  if (!enabled) return null
  const disabled = count === 0 || busy
  const title = count === 0 ? `Tick one or more ${noun}s first` : `Permanently delete the ${count} selected ${noun}${count === 1 ? '' : 's'}`
  return (
    <button className="btn btn-danger btn-sm" disabled={disabled} title={title} onClick={onClick} data-testid="force-delete-btn">
      <Trash2 size={13} /> {busy ? 'Deleting…' : `Force delete selected${count ? ` (${count})` : ''}`}
    </button>
  )
}

/** Tell every open admin table that rows were deleted so each reloads at once (no page refresh needed). */
export const DATA_CHANGED_EVENT = 'accfino:data-changed'
export const announceDataChanged = () => window.dispatchEvent(new Event(DATA_CHANGED_EVENT))

/** Report the outcome of a bulk delete: one toast for the successes, one per failure with the server's reason. */
export function reportBulkResult(data, noun) {
  const results = data?.results || []
  const ok = results.filter(r => r.ok)
  if (ok.length) {
    const users = ok.reduce((n, r) => n + (r.users_deleted?.length || 0), 0)
    toast.success(`${ok.length} ${noun}${ok.length === 1 ? '' : 's'} deleted` + (users ? ` (and ${users} user${users === 1 ? '' : 's'} of ${ok.length === 1 ? 'it' : 'them'})` : ''))
  }
  results.filter(r => !r.ok).forEach(r => toast.error(`#${r.id}: ${typeof r.error === 'string' ? r.error : 'Delete failed'}`, { duration: 7000 }))
  return ok.map(r => r.id)
}

export { errMsg }
