import React from 'react'

// Placeholder shown for a module tab that's on the roadmap but not built yet.
// Keeps the tab reachable (no dead link / blank screen) while being clearly marked as upcoming.
export default function ComingSoonTab({ emoji, name, blurb, phase }) {
  return (
    <div style={{ padding: '56px 24px', textAlign: 'center' }}>
      <div style={{ fontSize: '2.2rem', marginBottom: 12 }}>{emoji}</div>
      <h3 style={{ margin: '0 0 6px' }}>{name}</h3>
      <p style={{ color: 'var(--text-3)', fontSize: '.85rem', maxWidth: 420, margin: '0 auto' }}>{blurb}</p>
      <span className="badge badge-neutral" style={{ marginTop: 14, display: 'inline-block' }}>
        Coming soon{phase ? ` · ${phase}` : ''}
      </span>
    </div>
  )
}
