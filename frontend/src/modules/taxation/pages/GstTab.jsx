import React, { useState } from 'react'
import BasTab from './BasTab.jsx'
import GstAdjustmentsPanel from './GstAdjustmentsPanel.jsx'
import ImportPanel from '../components/ImportPanel.jsx'

// GST = activity statements (BAS / IAS, from the ledger) + the GST adjustments register that feeds them.
export default function GstTab(props) {
  const [view, setView] = useState('statements')
  const [n, setN] = useState(0)
  return (
    <div>
      <div className="tabs-bar" style={{ margin: '12px 16px 0' }} role="tablist" aria-label="GST views">
        <button role="tab" aria-selected={view === 'statements'} className={`tab-btn${view === 'statements' ? ' active' : ''}`} onClick={() => setView('statements')}>Activity statements (BAS / IAS)</button>
        <button role="tab" aria-selected={view === 'adjustments'} className={`tab-btn${view === 'adjustments' ? ' active' : ''}`} onClick={() => setView('adjustments')}>GST adjustments</button>
        {view === 'statements' && <span style={{ marginLeft: 'auto', alignSelf: 'center', paddingRight: 8 }}><ImportPanel datasets={[{ key: 'gst_history', label: 'Activity statement history (lodged BAS / IAS)' }]} caps={props.me.capabilities} onDone={() => setN(x => x + 1)} buttonLabel="Bulk upload / Import CSV (statement history)" /></span>}
      </div>
      {view === 'statements' ? <BasTab key={n} {...props} /> : <GstAdjustmentsPanel {...props} />}
    </div>)
}
