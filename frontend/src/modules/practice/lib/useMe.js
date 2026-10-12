import { useEffect, useState } from 'react'
import * as api from './practiceApi.js'

// The signed-in member's practice role and capabilities (decided by the backend; the UI only hides what the server would refuse anyway).
export function useMe() {
  const [s, set] = useState({ loading: true, me: null, error: null })
  useEffect(() => { let on = true; api.me().then(me => on && set({ loading: false, me, error: null })).catch(e => on && set({ loading: false, me: null, error: api.errMsg(e) })); return () => { on = false } }, [])
  const caps = new Set(s.me?.capabilities || [])
  return { ...s, can: c => caps.has(c), reload: () => api.me().then(me => set({ loading: false, me, error: null })) }
}
export const saveBlob = (name, data) => {
  const url = URL.createObjectURL(data)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
}
