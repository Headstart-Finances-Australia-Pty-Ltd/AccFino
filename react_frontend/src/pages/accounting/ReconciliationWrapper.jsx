/**
 * ReconciliationWrapper
 * Embeds the existing ReconciliationPage inside the Accounting module
 * without changing ReconciliationPage itself. Uses the shared
 * ReconciliationContext that already lives in Layout.
 */
import React, { useContext } from 'react'
import ReconciliationPage from '../ReconciliationPage.jsx'
import { ReconciliationContext } from '../../components/layout/Layout.jsx'

export default function ReconciliationWrapper({ userId }) {
  // ReconciliationPage reads its state from ReconciliationContext
  // which is provided by Layout — no changes needed to ReconciliationPage
  return <ReconciliationPage />
}
