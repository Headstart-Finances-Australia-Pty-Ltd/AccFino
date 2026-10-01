import { useEffect, useState } from 'react'
import * as books from '../lib/booksApi.js'

// Is bulk data import switched on platform-wide (Admin > Modules Management)? Fetched once and shared; Admin dispatches
// 'accfino:bulk-import-changed' after saving so open pages update at once. Fails open (shows the buttons) if the status
// cannot be read - the server refuses the import anyway when it is off, so this only controls what is shown.
let cached = null
const listeners = new Set()
function fetchStatus() {
  try { return Promise.resolve(books.bulkImportStatus()) } catch (e) { return Promise.reject(e) }     // fail open if the API client cannot answer
}
function refresh() {
  return fetchStatus().then(r => { cached = r.data?.enabled !== false }).catch(() => {}).finally(() => listeners.forEach(f => f(cached !== false)))
}
if (typeof window !== 'undefined') window.addEventListener('accfino:bulk-import-changed', () => { cached = null; refresh() })

export function useBulkImportEnabled() {
  const [on, setOn] = useState(cached !== false)
  useEffect(() => {
    listeners.add(setOn)
    if (cached === null) refresh()
    return () => { listeners.delete(setOn) }
  }, [])
  return on
}
