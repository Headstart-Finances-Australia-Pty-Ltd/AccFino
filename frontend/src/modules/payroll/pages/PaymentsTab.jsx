import React, { useState } from 'react'
import * as api from '../lib/payrollApi.js'
import { act, Async, DataGrid, Modal, Money, Section, StatusBadge, useConfirm, useLoad } from '../components/kit.jsx'
import { download, fmtDate, fmtAUD } from '../lib/format.js'

export default function PaymentsTab({ me }) {
  const [open, setOpen] = useState(null)
  const [dialog, confirm] = useConfirm()
  const runs = useLoad(() => api.runs({ status: 'finalised' }), [])
  const pays = useLoad(() => api.payments(), [])
  const can = me.capabilities.includes('payments_manage')
  const live = new Set((pays.data || []).filter(p => ['prepared', 'completed'].includes(p.status)).map(p => p.run_id))
  const awaiting = (runs.data || []).filter(r => !live.has(r.id) && !r.reversed_by_run_id && r.run_type !== 'reversal')
  const prepare = async r => {
    const c = await confirm({ title: 'Prepare payment', confirmLabel: 'Prepare', message: `Prepare the payment batch for ${r.run_no}? Net pay ${fmtAUD(r.total_net)} is split across each employee's bank accounts.` })
    if (!c.ok) return
    const p = await act(() => api.preparePayment(r.id, {}), 'Payment batch prepared')
    if (p) { pays.reload(); runs.reload(); setOpen(p.id) }
  }
  return (
    <div>
      {dialog}
      <h3 style={{ marginTop: 0 }}>Payments</h3>
      <div className="alert alert-warning">AccFino does not connect to any bank. A bank file (ABA) can be downloaded for upload to your bank, and "Mark as paid" records the payment. Nothing is sent automatically.</div>
      <Section title="Finalised pay runs awaiting payment"><Async q={runs}>{() => <DataGrid rows={awaiting} empty="Nothing awaiting payment" columns={[{ key: 'run_no', label: 'Run' }, { key: 'pay_date', label: 'Pay date', date: true }, { key: 'employee_count', label: 'Employees', align: 'right' }, { key: 'total_net', label: 'Net pay', money: true },
        { key: 'x', label: '', render: r => can && <button className="btn btn-primary btn-xs" onClick={() => prepare(r)}>Prepare payment</button> }]} />}</Async></Section>
      <Section title="Payment batches"><Async q={pays}>{rows => <DataGrid rows={rows} empty="No payment batches yet" onRowClick={p => setOpen(p.id)} columns={[{ key: 'batch_ref', label: 'Batch' }, { key: 'payment_date', label: 'Payment date', date: true }, { key: 'item_count', label: 'Payments', align: 'right' },
        { key: 'total', label: 'Total', money: true }, { key: 'status', label: 'Status', render: p => <StatusBadge status={p.status} /> }]} />}</Async></Section>
      {open && <Batch id={open} can={can} onClose={() => { setOpen(null); pays.reload(); runs.reload() }} />}
    </div>
  )
}

function Batch({ id, can, onClose }) {
  const q = useLoad(() => api.payment(id), [id])
  const [dialog, confirm] = useConfirm()
  const doit = async (fn, ok) => { const r = await act(fn, ok); if (r) q.reload(); return r }
  const p = q.data
  const complete = async () => { const c = await confirm({ title: 'Mark as paid', confirmLabel: 'Mark as paid', message: `Record that ${fmtAUD(p.total)} was paid to ${p.item_count} accounts? This does not send any money; it records that you have paid via your bank.` }); if (c.ok) doit(() => api.paymentAction(id, 'complete'), 'Marked as paid') }
  const cancel = async () => { const c = await confirm({ title: 'Cancel batch', danger: true, confirmLabel: 'Cancel batch', reasonLabel: 'Reason', message: 'Cancel this payment batch?' }); if (c.ok) doit(() => api.paymentAction(id, 'cancel', { reason: c.reason }), 'Batch cancelled') }
  const ret = async i => { const c = await confirm({ title: 'Payment returned', danger: true, confirmLabel: 'Record', reasonLabel: 'Reason (e.g. account closed)', message: `Record that the payment to ${i.account_name} was returned by the bank?` }); if (c.ok) doit(() => api.paymentItemStatus(id, i.id, { status: 'returned', reason: c.reason }), 'Recorded') }
  const aba = async () => { const t = await act(() => api.abaFile(id)); if (t) download(`payroll-${p.batch_ref}.aba`, t) }
  return (
    <Modal title={p ? `Payment batch ${p.batch_ref}` : 'Payment batch'} onClose={onClose} width={860}>
      {dialog}
      <Async q={q}>{b => (
        <>
          <div className="flex items-center gap-1" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
            <StatusBadge status={b.status} /><span className="text-sm">Payment date {fmtDate(b.payment_date)} · {b.item_count} payments · <Money v={b.total} strong /></span><div style={{ flex: 1 }} />
            {can && b.status !== 'cancelled' && <button className="btn btn-outline btn-sm" onClick={aba}>Download bank file (ABA)</button>}
            {can && b.status === 'prepared' && <><button className="btn btn-success btn-sm" onClick={complete}>Mark as paid…</button><button className="btn btn-outline btn-sm" onClick={cancel}>Cancel batch</button></>}
            {can && b.status === 'completed' && <button className="btn btn-outline btn-sm" onClick={() => doit(() => api.paymentAction(id, 'reconcile'), 'Reconciled')}>Reconcile paid items</button>}
          </div>
          <DataGrid rows={b.items} pageSize={20} columns={[{ key: 'employee', label: 'Employee' }, { key: 'account_name', label: 'Account' }, { key: 'bsb', label: 'BSB' }, { key: 'account', label: 'Account no.' }, { key: 'reference', label: 'Reference' }, { key: 'amount', label: 'Amount', money: true },
            { key: 'status', label: 'Status', render: i => <><StatusBadge status={i.status} />{i.failure_reason && <div className="text-xs" style={{ color: 'var(--danger)' }}>{i.failure_reason}</div>}</> }, { key: 'reconciliation', label: 'Reconciliation', render: i => <StatusBadge status={i.reconciliation} /> },
            { key: 'x', label: '', render: i => can && b.status === 'completed' && i.status === 'paid' && <button className="btn btn-ghost btn-xs" onClick={() => ret(i)}>Returned…</button> }]} />
        </>)}</Async>
    </Modal>
  )
}
