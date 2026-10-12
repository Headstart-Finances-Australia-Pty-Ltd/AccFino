import React from 'react'
import { PayslipList } from './PayslipsTab.jsx'
import TimesheetsTab from './TimesheetsTab.jsx'
import LeaveTab from './LeaveTab.jsx'
import { Section } from '../components/kit.jsx'

// My Pay is strictly personal: payslips, leave and timesheets of the signed-in employee only (`mine`), even for a manager or payroll administrator.
// Team approvals live in Time & Leave. The server filters by the caller's employee id either way.
export default function MyPayTab({ me, onChanged }) {
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>My pay</h3>
      <p className="text-sm text-muted">Your own payslips, leave and timesheets. You only ever see your own information.</p>
      <Section title="My payslips"><PayslipList mine /></Section>
      <Section title="My leave"><LeaveTab me={me} mine onChanged={onChanged} /></Section>
      <Section title="My timesheets"><TimesheetsTab me={me} mine onChanged={onChanged} /></Section>
    </div>
  )
}
