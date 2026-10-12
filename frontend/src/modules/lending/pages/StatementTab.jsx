import React, { useState } from 'react'
import ApplicantsTab from './ApplicantsTab.jsx'

// Applicant-first analysis (saved against the applicant) beside the original quick check (nothing is saved).
export default function StatementTab({ me, quickCheck }) {
  const [view, setView] = useState('applicants')
  return (
    <div>
      <div className="tabs-bar" role="tablist" aria-label="Statement analysis views" style={{ padding: '0 16px' }}>
        <button role="tab" aria-selected={view === 'applicants'} className={`tab-btn${view === 'applicants' ? ' active' : ''}`} onClick={() => setView('applicants')}>Applicants and saved analyses</button>
        {quickCheck && <button role="tab" aria-selected={view === 'quick'} className={`tab-btn${view === 'quick' ? ' active' : ''}`} onClick={() => setView('quick')}>Quick check (not saved)</button>}
      </div>
      {view === 'applicants' ? <ApplicantsTab me={me} /> : <div style={{ margin: 0 }}>{quickCheck}</div>}
    </div>)
}
