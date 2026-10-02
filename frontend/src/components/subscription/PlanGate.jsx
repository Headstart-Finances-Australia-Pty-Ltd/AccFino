import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Lock } from 'lucide-react'
import { useModuleVisibility } from '../../hooks/useModuleVisibility.jsx'
import useOrgRole from '../../hooks/useOrgRole.jsx'
import { moduleAtLocation } from '../../lib/modules.js'

// Wraps the page area. The menu, tab bars and Home already hide what the organisation's plan does not include; this covers the same thing when a page is
// opened from a typed address or bookmark: the page itself is not shown - only a short explanation (the server refuses the data as well).
export default function PlanGate({ children }) {
  const location = useLocation()
  const { isLocked, subscription } = useModuleVisibility()
  const { isOrgAdmin } = useOrgRole()
  const m = moduleAtLocation(location)
  if (!m || !isLocked(m.id)) return children
  return (
    <div className="fade-in" data-testid="not-in-plan" style={{ maxWidth: 520, margin: '60px auto', textAlign: 'center' }}>
      <div style={{ width: 56, height: 56, borderRadius: '50%', background: 'var(--surface-3)', display: 'grid', placeItems: 'center', margin: '0 auto 16px' }}><Lock size={24} /></div>
      <h2 style={{ marginBottom: 8 }}>{m.name} is not part of your plan</h2>
      <p style={{ color: 'var(--text-2)', marginBottom: 18 }}>
        {subscription?.plan_name ? <>Your <b>{subscription.plan_name}</b> plan doesn't include it. </> : null}
        {isOrgAdmin ? 'You can upgrade the plan or add this module in your organisation settings.' : 'Ask your Organisation Admin to upgrade the plan or add it.'}
      </p>
      <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
        {isOrgAdmin && <Link className="btn btn-primary" to="/settings/setup" data-testid="plan-gate-upgrade">View plan and add-ons</Link>}
        <Link className="btn btn-outline" to="/">Back to Home</Link>
      </div>
    </div>
  )
}
