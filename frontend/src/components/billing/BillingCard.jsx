import React, { useCallback, useEffect, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { CreditCard, ShieldCheck } from 'lucide-react'
import * as api from '../../lib/booksApi.js'
import { fmtAUD, fmtDate } from '../books/Common.jsx'

const SDK = { production: 'https://web.squarecdn.com/v1/square.js', sandbox: 'https://sandbox.web.squarecdn.com/v1/square.js' }
let sdkPromise = null
function loadSquare(env) {                                           // Square's own script: the card number is typed into Square's secure fields, never into AccFino
  if (window.Square) return Promise.resolve(window.Square)
  if (!sdkPromise) sdkPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script'); s.src = SDK[env] || SDK.sandbox; s.async = true
    s.onload = () => resolve(window.Square); s.onerror = () => { sdkPromise = null; reject(new Error('Could not load the secure card form.')) }
    document.head.appendChild(s)
  })
  return sdkPromise
}

// Settings > Business Setup > Organisation > Subscription: pay for the plan by card, automatically every month or year.
export default function BillingCard() {
  const [v, setV] = useState(null)
  const [busy, setBusy] = useState('')
  const [editing, setEditing] = useState(false)
  const [period, setPeriod] = useState('monthly')
  const [formErr, setFormErr] = useState('')
  const cardRef = useRef(null)
  const boxRef = useRef(null)

  const load = useCallback(() => api.getBilling().then(r => { setV(r.data); if (r.data.billing_period) setPeriod(r.data.billing_period) }).catch(() => setV({ available: false })), [])
  useEffect(() => { load() }, [load])

  const showForm = !!v?.available && v?.can_manage && (editing || (!v.card && v.has_plan))
  useEffect(() => {                                                    // mount Square's card fields when the form is shown
    if (!showForm || !v?.square) return
    let dead = false
    ;(async () => {
      try {
        const Square = await loadSquare(v.square.environment)
        const payments = Square.payments(v.square.applicationId, v.square.locationId)
        const card = await payments.card()
        if (dead) return
        await card.attach(boxRef.current); cardRef.current = card
      } catch (e) { setFormErr(e.message || 'The secure card form could not start.') }
    })()
    return () => { dead = true; try { cardRef.current?.destroy?.() } catch {} cardRef.current = null }
  }, [showForm, v?.square?.applicationId])                             // eslint-disable-line

  const run = async (name, fn) => { setBusy(name); try { await fn() } catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(''); load() } }
  const saveCard = () => run('card', async () => {
    setFormErr('')
    const res = await cardRef.current.tokenize()
    if (res.status !== 'OK') { setFormErr(res.errors?.[0]?.message || 'Please check the card details.'); return }
    await api.saveBillingCard(res.token); setEditing(false); toast.success('Card saved')
  })
  const subscribe = () => run('sub', async () => {
    const { data } = await api.billingSubscribe(period)
    toast.success(data.charge?.status === 'paid' ? `Paid ${fmtAUD(data.charge.amount)} - automatic renewal is on` : 'Automatic renewal is on')
  })
  const stop = () => run('stop', async () => { await api.billingAutoRenew(false); toast.success('Automatic renewal turned off') })
  const removeCard = () => run('rm', async () => {
    if (!window.confirm('Remove this card? Automatic renewal will stop.')) return
    await api.deleteBillingCard(); toast.success('Card removed')
  })

  if (!v) return null
  if (!v.available) return <div className="text-xs text-muted" data-testid="billing-unavailable" style={{ marginTop: 14 }}>Card payments are not switched on for this platform yet. Please contact AccFino support.</div>
  if (!v.has_plan) return null
  const manage = v.can_manage
  const price = p => (v.prices ? fmtAUD(v.prices[p]) : '')

  return (
    <div data-testid="billing-card" style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
      <div className="text-sm fw-600" style={{ marginBottom: 6 }}><CreditCard size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />Payment</div>

      {v.failure_count > 0 && <div className="alert alert-warning text-sm" data-testid="billing-failed" style={{ marginBottom: 10 }}>Your last payment did not go through{v.last_error ? ` (${v.last_error})` : ''}. {manage ? 'Update your card to keep your organisation active.' : 'Ask your Organisation Admin to update the card.'}</div>}

      {v.auto_renew && v.card && (
        <div className="text-sm" data-testid="billing-active" style={{ marginBottom: 10 }}>
          <span className="badge badge-success">Automatic renewal on</span>{' '}
          {v.next_charge_on ? <>Next charge <b>{fmtAUD(v.amount_next)}</b> on <b>{fmtDate(v.next_charge_on)}</b> ({v.billing_period}).</> : null}
        </div>
      )}

      {v.card && !editing && (
        <div className="text-sm" style={{ marginBottom: 10 }} data-testid="billing-card-on-file">
          {v.card.brand} ···· {v.card.last4} · expires {String(v.card.exp_month).padStart(2, '0')}/{v.card.exp_year}
          {manage && <> <button className="btn btn-ghost btn-xs" onClick={() => setEditing(true)}>Change</button> <button className="btn btn-ghost btn-xs" onClick={removeCard} disabled={!!busy}>Remove</button></>}
        </div>
      )}

      {showForm && (
        <div style={{ maxWidth: 420, marginBottom: 10 }}>
          <div ref={boxRef} id="square-card" data-testid="square-card-box" style={{ minHeight: 90 }} />
          {formErr && <div className="alert alert-error text-xs" data-testid="billing-form-error">{formErr}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn btn-primary btn-sm" onClick={saveCard} disabled={!!busy} data-testid="billing-save-card">{busy === 'card' ? 'Saving…' : 'Save card'}</button>
            {editing && <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
          <div className="text-xs text-muted" style={{ marginTop: 6 }}><ShieldCheck size={12} style={{ verticalAlign: '-2px' }} /> Your card is entered into Square's secure form. AccFino never sees or stores the card number.</div>
        </div>
      )}

      {manage && v.card && !v.auto_renew && !editing && (
        <div data-testid="billing-subscribe" style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 14, marginBottom: 8, flexWrap: 'wrap' }}>
            {['monthly', 'yearly'].map(p => (
              <label key={p} className="text-sm" style={{ cursor: 'pointer' }}><input type="radio" name="bill-period" checked={period === p} onChange={() => setPeriod(p)} /> {p === 'monthly' ? 'Monthly' : 'Yearly (2 months free)'} <b>{price(p)}</b></label>
            ))}
          </div>
          <button className="btn btn-primary btn-sm" onClick={subscribe} disabled={!!busy} data-testid="billing-subscribe-btn">{busy === 'sub' ? 'Charging…' : `Pay ${price(period)} now and renew automatically`}</button>
          <div className="text-xs text-muted" style={{ marginTop: 4 }}>AUD, GST included. Your card is charged automatically at the start of each {period === 'yearly' ? 'year' : 'month'}; a receipt is emailed by Square. You can stop at any time.</div>
        </div>
      )}
      {manage && v.auto_renew && <button className="btn btn-outline btn-xs" onClick={stop} disabled={!!busy} data-testid="billing-stop">Turn off automatic renewal</button>}

      {v.charges?.length > 0 && (
        <table className="data-table" style={{ fontSize: '.78rem', marginTop: 12 }} data-testid="billing-history">
          <thead><tr><th>Date</th><th>Period</th><th style={{ textAlign: 'right' }}>Amount</th><th>Status</th><th /></tr></thead>
          <tbody>{v.charges.map(c => (
            <tr key={c.id}><td>{fmtDate(c.date)}</td><td>{c.period_start ? `${fmtDate(c.period_start)} – ${fmtDate(c.period_end)}` : '—'}</td><td style={{ textAlign: 'right' }}>{fmtAUD(c.amount)}</td>
              <td><span className={`badge ${c.status === 'paid' ? 'badge-success' : c.status === 'failed' ? 'badge-danger' : 'badge-neutral'}`}>{c.status}</span></td>
              <td>{c.receipt_url && <a href={c.receipt_url} target="_blank" rel="noreferrer">Receipt</a>}</td></tr>))}</tbody>
        </table>
      )}
    </div>
  )
}
