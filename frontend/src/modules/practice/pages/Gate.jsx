import React from 'react'
import { Async } from '../components/kit.jsx'
import { useMe } from '../lib/useMe.js'
import NoPractice from './NoPractice.jsx'

// Renders the practice tabs only for an active practice member; otherwise explains why (no workspace / not a member).
export default function Gate({ children }) {
  const m = useMe()
  return <Async q={{ loading: m.loading, data: m.me, error: m.error, reload: m.reload }}>{me => (me.has_practice && me.is_member ? children(m.can) : <NoPractice me={me} reload={m.reload} />)}</Async>
}
