import React from 'react'
import { EmptyState, Input, useForm } from '../components/kit.jsx'
import * as api from '../lib/practiceApi.js'
import { act } from '../components/kit.jsx'

// Shown when the organisation has no practice workspace or the user is not a member. Only the Organisation Admin can create the workspace.
export default function NoPractice({ me, reload }) {
  const [f, set] = useForm({ name: '' })
  if (me?.has_practice) return <EmptyState icon="🔒" title="You are not a member of this practice" hint="Ask a practice admin to add you (Practice > Members)." />
  if (!me?.can_create) return <EmptyState icon="🗂" title="This organisation has no practice workspace yet" hint="The Organisation Admin can create it." />
  return (
    <div style={{ padding: 20, maxWidth: 420 }}>
      <h4>Create the practice workspace</h4>
      <Input label="Practice name" value={f.name} onChange={set('name')} />
      <button className="btn btn-primary" disabled={!f.name.trim()} onClick={async () => { if (await act(() => api.workspace.create({ name: f.name }), 'Practice created')) reload() }}>Create practice</button>
    </div>)
}
