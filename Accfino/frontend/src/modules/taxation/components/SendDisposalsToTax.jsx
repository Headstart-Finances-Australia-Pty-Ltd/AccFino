import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Modal } from './kit.jsx'

// "Send to Tax (CGT)": hands the disposals an Investments analysis produced to the Taxation CGT register. Used by the Investments screens through taxation/public.js.
// A preview (dry run) always comes first; re-sending the same rows is safe (duplicates are skipped).
export default function SendDisposalsToTax({ rows = [], assetClass = 'shares' }) {
  const [open, setOpen] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const run = async dry => {
    setErr('')
    const r = await act(() => api.cgt.importRows({ rows, asset_class: assetClass, dry_run: dry }), dry ? undefined : 'Disposals sent to Tax > CGT')
    if (r) { setRes(r); if (!dry) setOpen(false) } else setErr('Could not reach Tax. You need an Accountant, Bookkeeper or Admin role in Taxation & Compliance.')
  }
  if (!rows.length) return null
  return (
    <>
      <button className="btn btn-outline btn-sm" onClick={() => { setOpen(true); setRes(null); run(true) }}>Send to Tax (CGT)</button>
      {open && (
        <Modal title="Send disposals to Tax > CGT" onClose={() => setOpen(false)} width={520}>
          <p className="text-sm" style={{ marginTop: 0 }}>{rows.length} disposal row(s) from this analysis will be added to the CGT event register for the income year of each disposal. Rows already sent are skipped. Nothing is lodged.</p>
          {err && <div role="alert" className="alert alert-error">{err}</div>}
          {res && <div className="text-sm" role="status">Preview: {res.added} to add · {res.skipped_duplicates} already in Tax · {res.rejected} rejected
            {res.errors.slice(0, 5).map(e => <div key={e.row} style={{ color: 'var(--danger)' }}>Row {e.row}: {e.error}</div>)}</div>}
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 12 }}>
            <button className="btn btn-outline" onClick={() => setOpen(false)}>Cancel</button>
            <button className="btn btn-primary" disabled={!res || res.added === 0} onClick={() => run(false)}>Send {res ? res.added : ''}</button>
          </div>
        </Modal>)}
    </>)
}
