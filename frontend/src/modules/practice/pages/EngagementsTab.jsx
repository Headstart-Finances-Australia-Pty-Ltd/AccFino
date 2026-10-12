import React, { useState } from 'react'
import { BulkLoadButton } from '../../../core/components/ui/BulkLoadButton.jsx'
import { Async, Section, Table, StatusBadge, useLoad, act, Input, Select, useForm, Modal } from '../components/kit.jsx'
import * as api from '../lib/practiceApi.js'
import { label, fmtDate } from '../lib/format.js'

const DL_BADGE = { overdue: 'high', due_soon: 'medium', upcoming: 'low', completed: 'resolved' }

function EngagementView({ id, can, onClose, onChanged }) {
  const q = useLoad(() => api.engagements.get(id), [id])
  const rules = useLoad(() => api.engagements.rules(), [])
  const [dl, setDl] = useForm({ rule_id: '' })
  const act2 = async (fn, msg) => { if (await act(fn, msg)) { q.reload(); onChanged() } }
  return (
    <Modal title="Engagement" onClose={onClose} wide>
      <Async q={q}>{e => (
        <>
          <h4 style={{ margin: 0 }}>{e.title} <StatusBadge status={e.status === 'active' ? 'active' : 'draft'} text={label(e.status)} /></h4>
          <div className="text-sm text-muted">{label(e.service_type)} · {e.period_from} to {e.period_to} · {e.billing_basis === 'fixed' ? `Fixed fee $${e.fixed_fee}` : 'Hourly'}{e.accepted_by ? ` · accepted by ${e.accepted_by}` : ''}</div>
          {can('engagements') && <div className="flex gap-1" style={{ margin: '8px 0', flexWrap: 'wrap' }}>
            {e.status === 'draft' && <button className="btn btn-outline btn-sm" onClick={() => act2(() => api.engagements.transition(id, { action: 'propose' }), 'Proposed')}>Propose</button>}
            {['draft', 'proposed'].includes(e.status) && <button className="btn btn-outline btn-sm" onClick={() => { const by = window.prompt('Who at the client accepted?', ''); if (by) act2(() => api.engagements.transition(id, { action: 'accept', accepted_by: by }), 'Accepted') }}>Record acceptance</button>}
            {e.status === 'accepted' && <button className="btn btn-primary btn-sm" onClick={() => act2(() => api.engagements.transition(id, { action: 'start' }), 'Started')}>Start</button>}
            {e.status === 'active' && <button className="btn btn-primary btn-sm" onClick={() => act2(() => api.engagements.transition(id, { action: 'complete' }), 'Completed')}>Complete</button>}
            {['accepted', 'active'].includes(e.status) && <button className="btn btn-outline btn-sm" onClick={() => { const r = window.prompt('Reason for terminating', ''); if (r) act2(() => api.engagements.transition(id, { action: 'terminate', reason: r }), 'Terminated') }}>Terminate</button>}
            {['completed', 'terminated'].includes(e.status) && <button className="btn btn-outline btn-sm" onClick={() => act2(() => api.engagements.transition(id, { action: 'archive' }), 'Archived')}>Archive</button>}
            {['active', 'completed'].includes(e.status) && <button className="btn btn-outline btn-sm" onClick={() => act2(() => api.engagements.renew(id), 'Renewed for next period')}>Renew</button>}</div>}
          {e.jobs.map(j => (
            <Section key={j.id} title={`${j.title} — ${label(j.status)}`} hint={j.due_date ? `Internal target ${fmtDate(j.due_date)}` : ''}>
              {j.tasks.map(t => <div key={t.id} className="text-sm" style={{ marginBottom: 4 }}>{t.status === 'completed' ? '☑' : '☐'} {t.title} {!t.mandatory && <span className="text-muted">(optional)</span>} <span className="text-muted">{label(t.status)}</span>
                {t.checklist.map(c => <label key={c.id} style={{ display: 'block', marginLeft: 20 }}><input type="checkbox" checked={c.done} disabled={t.status === 'completed' || !can('engagements')} onChange={ev => act2(() => api.engagements.tick(c.id, ev.target.checked))} /> {c.text}</label>)}
                {can('engagements') && e.status === 'active' && t.status !== 'completed' && <span className="flex gap-1">{t.status === 'not_started' && <button className="btn btn-outline btn-sm" onClick={() => act2(() => api.engagements.taskAction(t.id, 'start'))}>Start</button>}
                  <button className="btn btn-outline btn-sm" onClick={() => act2(() => api.engagements.taskAction(t.id, 'complete'), 'Task completed')}>Complete</button></span>}</div>)}
              {can('engagements') && e.status === 'active' && <div className="flex gap-1">
                {j.status === 'in_progress' && <button className="btn btn-primary btn-sm" onClick={() => act2(() => api.engagements.jobTransition(j.id, 'submit_review'), 'Sent for review')}>Submit for review</button>}
                {j.status === 'ready_for_review' && can('wp_review') && <><button className="btn btn-primary btn-sm" onClick={() => act2(() => api.engagements.jobTransition(j.id, 'complete'), 'Job completed')}>Approve & complete</button>
                  <button className="btn btn-outline btn-sm" onClick={() => { const r = window.prompt('What must change?', ''); if (r) act2(() => api.engagements.jobTransition(j.id, 'request_changes', r)) }}>Request changes</button></>}</div>}
            </Section>))}
          <Section title="Deadlines" hint="Internal targets and statutory dates are separate. Statutory dates are entered by the practice with a source, and shown as unverified until a manager verifies them.">
            <Table caption="Deadlines" rows={e.deadlines} empty="None" columns={[{ key: 'title', label: 'Deadline' }, { key: 'label', label: 'Kind' }, { key: 'due_date', label: 'Due', date: true }, { key: 'state', label: 'State', render: r => <StatusBadge status={DL_BADGE[r.state]} text={label(r.state)} /> },
              { key: 'source', label: 'Source' }, { key: 'x', label: '', render: r => r.status === 'open' && <span className="flex gap-1">
                {r.kind === 'statutory' && !r.verified && <button className="btn btn-outline btn-sm" onClick={() => { const s = window.prompt('Source checked (e.g. page and date)', r.source || ''); if (s) act2(() => api.engagements.verifyDeadline(r.id, s), 'Verified') }}>Verify</button>}
                <button className="btn btn-outline btn-sm" onClick={() => { const nd = window.prompt('New date (YYYY-MM-DD)', r.due_date); const why = nd && window.prompt('Reason for override', ''); if (why) act2(() => api.engagements.overrideDeadline(r.id, nd, why), 'Overridden (audited)') }}>Override</button>
                <button className="btn btn-outline btn-sm" onClick={() => act2(() => api.engagements.completeDeadline(r.id), 'Completed')}>Done</button></span> }]} />
            {can('engagements') && <div className="flex items-center gap-1"><Async q={rules}>{rs => <Select label="Rule" value={dl.rule_id} onChange={setDl('rule_id')} blank="Choose a rule" options={rs.map(r => ({ value: r.id, label: `${r.name} (${r.kind})` }))} />}</Async>
              <button className="btn btn-outline btn-sm" disabled={!dl.rule_id} onClick={() => act2(() => api.engagements.addDeadline(id, { rule_id: Number(dl.rule_id) }), 'Deadline added')}>Add deadline</button></div>}
          </Section>
        </>)}
      </Async>
    </Modal>)
}

export default function EngagementsTab({ can }) {
  const [status, setStatus] = useState('')
  const q = useLoad(() => api.engagements.list({ status: status || undefined, size: 50 }), [status])
  const dls = useLoad(() => api.engagements.deadlines({ status: 'open', size: 20 }), [])
  const work = useLoad(() => api.engagements.myWork({ size: 20 }), [])
  const tpl = useLoad(() => api.engagements.templates(), [])
  const [open, setOpen] = useState(null)
  const [n, setN] = useForm({ client_id: '', title: '', service_type: 'bookkeeping', template_id: '', period_from: '', period_to: '', billing_basis: 'hourly', fixed_fee: '' })
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><BulkLoadButton base="/practice/bulk" areas={["Engagements"]} onDone={() => window.location.reload()} /></div>
      <Section title="My work"><Async q={work}>{d => <Table caption="My jobs" rows={d.items} empty="Nothing assigned to you" columns={[{ key: 'title', label: 'Job' }, { key: 'client_id', label: 'Client' }, { key: 'status', label: 'Status', render: r => label(r.status) }, { key: 'due_date', label: 'Internal target', date: true }]} />}</Async></Section>
      <Section title="Upcoming deadlines"><Async q={dls}>{d => <Table caption="Deadlines" rows={d.items} empty="No open deadlines" columns={[{ key: 'title', label: 'Deadline' }, { key: 'client_id', label: 'Client' }, { key: 'label', label: 'Kind' }, { key: 'due_date', label: 'Due', date: true },
        { key: 'state', label: 'State', render: r => <StatusBadge status={DL_BADGE[r.state]} text={label(r.state)} /> }]} />}</Async></Section>
      <Section title="Engagements" actions={can('engagements') && <button className="btn btn-outline btn-sm" onClick={async () => { const r = await act(() => api.engagements.runRecurrences()); if (r) { window.alert(`${r.created.length} engagement(s) created, ${r.reminders.created} reminder(s) queued`); q.reload() } }}>Run recurring work</button>}>
        <Select label="Status" value={status} onChange={e => setStatus(e.target.value)} options={['draft', 'proposed', 'accepted', 'active', 'completed', 'terminated', 'archived']} blank="All" />
        <Async q={q}>{d => <Table caption="Engagements" rows={d.items} empty="No engagements" onRowClick={r => setOpen(r.id)} columns={[{ key: 'title', label: 'Engagement' }, { key: 'client_id', label: 'Client' }, { key: 'service_type', label: 'Service', render: r => label(r.service_type) },
          { key: 'status', label: 'Status', render: r => label(r.status) }, { key: 'period_to', label: 'Period end', date: true }]} />}</Async>
        {can('engagements') && <div className="flex items-center gap-1" style={{ flexWrap: 'wrap', marginTop: 10 }}>
          <Input label="Client id" type="number" value={n.client_id} onChange={setN('client_id')} /><Input label="Title" value={n.title} onChange={setN('title')} />
          <Select label="Service" value={n.service_type} onChange={setN('service_type')} options={['bookkeeping', 'financial_statements', 'tax_return', 'bas', 'payroll', 'advisory', 'other']} />
          <Async q={tpl}>{ts => <Select label="Template" value={n.template_id} onChange={setN('template_id')} blank="None" options={ts.map(t => ({ value: t.id, label: t.name }))} />}</Async>
          <Input label="Period from" type="date" value={n.period_from} onChange={setN('period_from')} /><Input label="Period to" type="date" value={n.period_to} onChange={setN('period_to')} />
          <Select label="Billing" value={n.billing_basis} onChange={setN('billing_basis')} options={['hourly', 'fixed']} />{n.billing_basis === 'fixed' && <Input label="Fixed fee" value={n.fixed_fee} onChange={setN('fixed_fee')} />}
          <button className="btn btn-primary btn-sm" disabled={!n.client_id || !n.title} onClick={async () => {
            const body = { ...n, client_id: Number(n.client_id), template_id: n.template_id ? Number(n.template_id) : undefined, period_from: n.period_from || undefined, period_to: n.period_to || undefined, fixed_fee: n.billing_basis === 'fixed' ? n.fixed_fee : undefined }
            if (await act(() => api.engagements.create(body), 'Engagement created')) q.reload() }}>Create engagement</button></div>}
      </Section>
      {open && <EngagementView id={open} can={can} onClose={() => setOpen(null)} onChanged={() => { q.reload(); dls.reload(); work.reload() }} />}
    </div>)
}
