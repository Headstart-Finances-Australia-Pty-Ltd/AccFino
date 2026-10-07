import React, { useState } from 'react'
import * as api from '../lib/taxApi.js'
import { act, Modal, Select } from './kit.jsx'

// "Send to Tax (CGT)" for the Investments CRYPTO screen: it hands over the individual trades; the Taxation module matches each sell to the earlier purchases (FIFO, LIFO or highest cost)
// so every disposal has its own acquisition date. A preview always comes first and repeat sends are safe.
export default function SendCryptoTradesToTax({ trades = [] }) {
  const [open, setOpen] = useState(false)
  const [method, setMethod] = useState('fifo')
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const run = async (dry, m = method) => {
    setErr('')
    const r = await act(() => api.cgt.importTrades({ trades, method: m, dry_run: dry }), dry ? undefined : 'Disposals sent to Tax > CGT')
    if (r) { setRes(r); if (!dry) setOpen(false) } else setErr('Could not reach Tax. You need an Accountant, Bookkeeper or Admin role in Taxation & Compliance.')
  }
  if (!trades.length) return null
  return (
    <>
      <button className="btn btn-outline btn-sm" onClick={() => { setOpen(true); setRes(null); run(true) }}>Send to Tax (CGT)</button>
      {open && (
        <Modal title="Send crypto disposals to Tax > CGT" onClose={() => setOpen(false)} width={560}>
          <p className="text-sm" style={{ marginTop: 0 }}>{trades.length} trade(s) will be matched sell-by-sell to your earlier purchases and added to the CGT register for the income year of each sale. Nothing is lodged.</p>
          <Select label="Which parcels are treated as sold first?" value={method} onChange={e => { setMethod(e.target.value); run(true, e.target.value) }}
            options={[{ value: 'fifo', label: 'First in, first out (oldest first)' }, { value: 'lifo', label: 'Last in, first out (newest first)' }, { value: 'hifo', label: 'Highest cost first' }]} hint="Use the same method every year and keep your records." />
          {err && <div role="alert" className="alert alert-error">{err}</div>}
          {res && <div className="text-sm" role="status">Preview: {res.disposals} disposal piece(s) · {res.added} to add · {res.skipped_duplicates} already in Tax · {res.rejected} rejected
            {res.unmatched.slice(0, 5).map((u, i) => <div key={i} style={{ color: 'var(--danger)' }}>▲ {u.reason}</div>)}
            <details style={{ marginTop: 6 }}><summary className="text-xs" style={{ cursor: 'pointer' }}>What is and is not handled</summary><div className="text-xs text-muted">{res.note}</div></details></div>}
          <div className="flex gap-1" style={{ justifyContent: 'flex-end', marginTop: 12 }}>
            <button className="btn btn-outline" onClick={() => setOpen(false)}>Cancel</button>
            <button className="btn btn-primary" disabled={!res || res.added === 0} onClick={() => run(false)}>Send {res ? res.added : ''}</button>
          </div>
        </Modal>)}
    </>)
}
