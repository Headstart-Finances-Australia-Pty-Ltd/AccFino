import { useEffect, useState } from 'react'
import { useAuth } from './useAuth.jsx'
import { currentOrg } from '../lib/platformApi.js'
import { currentOrgId } from '../lib/authFetch.js'

// Who am I in the organisation I'm working in?  isOrgAdmin = the Organisation Admin (the organisation's one primary administrator) or AccFino platform support.
//
// THIS ONLY DECIDES WHAT TO SHOW. Every organisation-level API call is checked again on the server (ctx.require_org_admin), so changing this value in the
// browser reveals a screen that then has nothing to display and whose requests are refused with 403.
function fromSession(user) {
  if (!user) return { loading: false, role: null, isOrgAdmin: false, org: null }
  const platform = user.is_admin === true || (Array.isArray(user.roles) && user.roles.includes('admin'))
  const wanted = Number(currentOrgId() || user.org_id)
  const mine = (user.organisations || []).find(o => o.id === wanted)
  if (platform) return { loading: false, role: mine?.role || 'owner', isOrgAdmin: true, org: null }
  if (mine) return { loading: false, role: mine.role, isOrgAdmin: mine.role === 'owner', org: null }
  return { loading: true, role: null, isOrgAdmin: false, org: null }              // unknown yet: show nothing administrative until the server answers
}

export default function useOrgRole() {
  const { user } = useAuth() || {}
  const [state, setState] = useState(() => fromSession(user))
  const org = currentOrgId()
  useEffect(() => {
    if (!user) { setState(fromSession(null)); return }
    setState(s => (s.loading ? fromSession(user) : s))
    let alive = true
    currentOrg().then(r => { if (alive) setState({ loading: false, role: r.data.role, isOrgAdmin: !!r.data.is_org_admin, org: r.data }) })
      .catch(() => { if (alive) setState({ loading: false, role: null, isOrgAdmin: false, org: null }) })
    return () => { alive = false }
  }, [user?.id, org]) // eslint-disable-line
  return state
}
