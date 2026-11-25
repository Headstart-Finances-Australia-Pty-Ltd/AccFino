import React, { useEffect, useState } from 'react'
import { licenceList, licenceSave, licenceDeleteUser, licenceUpdateUser, register } from '../lib/api'
import { Edit2, Trash2, Check, X, Plus, RefreshCw, Save } from 'lucide-react'
import toast from 'react-hot-toast'

const LICENCE_TYPES  = ['demo', 'trial', 'paid', 'suspended']

const ALL_MODULES = [
  { key: 'dashboard',      label: '📊 Dashboard' },
  { key: 'reconciliation', label: '🔄 Reconciliation' },
  { key: 'trading',        label: '📈 Trading' },
  { key: 'cash-flow',      label: '📉 Cash Flow' },
  { key: 'invoice',        label: '🧾 Invoice' },
  { key: 'admin',          label: '🛡 Admin & ML' },
  { key: 'file-manager',   label: '📁 File Manager' },
  { key: 'licence',        label: '🏷 Licence' },
]
const PAYMENT_MODES  = ['', 'card', 'bank_transfer', 'invoice', 'paypal', 'other']

const EMPTY_LIC = {
  licence_type: 'demo', payment_mode: '', start_date: '', end_date: '', notes: ''
}

export default function LicencePage() {
  const [records,  setRecords]  = useState([])
  const [loading,  setLoading]  = useState(true)
  const [editId,      setEditId]      = useState(null)
  const [showAddUser, setShowAddUser] = useState(false)
  const [newUser,     setNewUser]     = useState({ username:'', full_name:'', email:'', password:'', role:'user' })
  const [addingUser,  setAddingUser]  = useState(false)
  const [editData, setEditData] = useState({})
  const [saving,   setSaving]   = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await licenceList()
      setRecords(data || [])
    } catch { toast.error('Failed to load licence data') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const startEdit = (rec) => {
    setEditId(rec.user_id)
    setEditData({
      username:     rec.username,
      full_name:    rec.full_name,
      email:        rec.email,
      licence_type: rec.licence_type || 'demo',
      payment_mode: rec.payment_mode || '',
      start_date:   rec.start_date   || '',
      end_date:     rec.end_date     || '',
      notes:        rec.notes        || '',
      modules:      rec.modules      || ALL_MODULES.map(m => m.key),
    })
  }

  const handleAddUser = async () => {
    if (!newUser.username || !newUser.email || !newUser.password) {
      toast.error('Username, email and password are required'); return
    }
    setAddingUser(true)
    try {
      await register({
        username:  newUser.username.trim(),
        full_name: newUser.full_name.trim(),
        email:     newUser.email.trim(),
        password:  newUser.password,
        role:      newUser.role || 'user',
        phone: '', address: '',
      })
      toast.success('User added')
      setShowAddUser(false)
      setNewUser({ username:'', full_name:'', email:'', password:'', role:'user' })
      await load()
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to add user')
    } finally { setAddingUser(false) }
  }

  const cancelEdit = () => { setEditId(null); setEditData({}) }

  const saveEdit = async (rec) => {
    setSaving(true)
    try {
      // Update user details
      await licenceUpdateUser(rec.user_id, {
        username:     editData.username,
        email:        editData.email,
        full_name:    editData.full_name,
        phone:        editData.phone        || '',
        home_company: editData.home_company || '',
      })
      // Save licence record
      await licenceSave({
        user_id:      rec.user_id,
        licence_type: editData.licence_type,
        payment_mode: editData.payment_mode,
        start_date:   editData.start_date,
        end_date:     editData.end_date,
        notes:        editData.notes,
        modules:      editData.modules || ALL_MODULES.map(m => m.key),
      })
      toast.success('Saved')
      setEditId(null)
      await load()
      // Notify Layout to re-fetch module permissions immediately
      window.dispatchEvent(new Event('accfino:modules-changed'))
    } catch { toast.error('Save failed') }
    finally { setSaving(false) }
  }

  const deleteUser = async (rec) => {
    if (!confirm(`Delete user "${rec.username}" and all their data?`)) return
    try {
      await licenceDeleteUser(rec.user_id)
      toast.success('User deleted')
      setRecords(r => r.filter(x => x.user_id !== rec.user_id))
    } catch { toast.error('Delete failed') }
  }

  const set = k => e => setEditData(d => ({ ...d, [k]: e.target.value }))
  const toggleModule = (key) => setEditData(d => {
    const mods = d.modules || ALL_MODULES.map(m => m.key)
    return { ...d, modules: mods.includes(key) ? mods.filter(m => m !== key) : [...mods, key] }
  })

  const statusColor = (type) => {
    if (type === 'paid')      return { bg: '#C6F6D5', color: '#276749' }
    if (type === 'trial')     return { bg: '#FEFCBF', color: '#975A16' }
    if (type === 'suspended') return { bg: '#FED7D7', color: '#9B2C2C' }
    return { bg: 'var(--surface-3)', color: 'var(--text-2)' }   // demo
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0 }}>Licence Management</h2>
          <p style={{ color: 'var(--text-3)', fontSize: '.85rem', margin: '4px 0 0' }}>
            Manage user accounts and licence details
          </p>
        </div>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: '.82rem', color: 'var(--text-3)' }}>
          {records.length} user{records.length !== 1 ? 's' : ''}
        </span>
        <button className="btn btn-primary btn-sm" onClick={() => setShowAddUser(s => !s)}>
          <Plus size={13} /> {showAddUser ? 'Cancel' : 'Add User'}
        </button>
        <button className="btn btn-outline btn-sm" onClick={load}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {showAddUser && (
        <div className="card card-flat" style={{marginBottom:16,padding:20}}>
          <h4 style={{margin:'0 0 14px'}}>Add New User</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(180px,1fr))',gap:10}}>
            {[['username','Username *','text'],['full_name','Full Name','text'],
              ['email','Email *','email'],['password','Password *','password']].map(([k,label,type]) => (
              <div key={k} className="input-group">
                <label style={{fontSize:'.78rem'}}>{label}</label>
                <input className="input input-sm" type={type} value={newUser[k]}
                  placeholder={label}
                  onChange={e => setNewUser(u => ({...u,[k]:e.target.value}))}/>
              </div>
            ))}
            <div className="input-group">
              <label style={{fontSize:'.78rem'}}>Role</label>
              <select className="input input-sm" value={newUser.role}
                onChange={e => setNewUser(u => ({...u,role:e.target.value}))}>
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </div>
          </div>
          <div style={{display:'flex',gap:8,marginTop:14}}>
            <button className="btn btn-primary btn-sm" onClick={handleAddUser} disabled={addingUser}>
              <Check size={13}/> {addingUser ? 'Adding…' : 'Add User'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowAddUser(false)}>
              <X size={13}/> Cancel
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}>
          <span className="spinner" /> Loading…
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.82rem' }}>
            <thead>
              <tr style={{ background: 'var(--surface-2)', borderBottom: '2px solid var(--border)' }}>
                {['Username', 'Full Name', 'Email', 'Phone', 'Company Name', 'Roles', 'Licence', 'Payment', 'Start', 'End', 'Notes', 'Modules', 'Actions']
                  .map(h => (
                    <th key={h} style={{ padding: '10px 12px', textAlign: 'left',
                      fontWeight: 600, color: 'var(--text-2)', whiteSpace: 'nowrap' }}>
                      {h}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {records.map((rec, i) => {
                const isEdit = editId === rec.user_id
                const sc = statusColor(isEdit ? editData.licence_type : rec.licence_type)
                return (
                  <tr key={rec.user_id}
                    style={{ borderBottom: '1px solid var(--border)',
                      background: i % 2 === 0 ? 'transparent' : 'var(--surface-2)' }}>

                    {/* Username */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit
                        ? <input className="input input-sm" value={editData.username} onChange={set('username')} style={{ width: 100 }} />
                        : <strong>{rec.username}</strong>}
                    </td>

                    {/* Full name */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit
                        ? <input className="input input-sm" value={editData.full_name} onChange={set('full_name')} style={{ width: 120 }} />
                        : rec.full_name || '—'}
                    </td>

                    {/* Email */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit
                        ? <input className="input input-sm" type="email" value={editData.email} onChange={set('email')} style={{ width: 160 }} />
                        : <span style={{ color: 'var(--text-2)' }}>{rec.email}</span>}
                    </td>

                    {/* Phone */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit
                        ? <input className="input input-sm" value={editData.phone||''} onChange={set('phone')}
                            placeholder="+61 4xx xxx xxx" style={{ width: 130 }} />
                        : <span style={{ color: 'var(--text-2)', fontSize: '.82rem' }}>{rec.phone || '—'}</span>}
                    </td>

                    {/* Company Name */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit
                        ? <input className="input input-sm" value={editData.home_company||''} onChange={set('home_company')}
                            placeholder="e.g. Acme Pty Ltd" style={{ width: 150 }} />
                        : <span style={{ color: 'var(--text-2)', fontSize: '.82rem' }}>{rec.home_company || '—'}</span>}
                    </td>

                    {/* Roles */}
                    <td style={{ padding: '8px 12px' }}>
                      {(rec.roles || []).map(r => (
                        <span key={r} style={{
                          fontSize: '.7rem', fontWeight: 700, padding: '2px 7px',
                          borderRadius: 100, marginRight: 4,
                          background: r === 'admin' ? 'var(--brand-light)' : 'var(--surface-3)',
                          color: r === 'admin' ? 'var(--brand)' : 'var(--text-2)',
                        }}>{r}</span>
                      ))}
                    </td>

                    {/* Licence type */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit ? (
                        <select className="input input-sm" value={editData.licence_type} onChange={set('licence_type')} style={{ width: 100 }}>
                          {LICENCE_TYPES.map(t => <option key={t}>{t}</option>)}
                        </select>
                      ) : (
                        <span style={{ ...sc, fontSize: '.72rem', fontWeight: 700, padding: '3px 9px',
                          borderRadius: 100, display: 'inline-block' }}>
                          {rec.licence_type || 'demo'}
                        </span>
                      )}
                    </td>

                    {/* Payment mode */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit ? (
                        <select className="input input-sm" value={editData.payment_mode} onChange={set('payment_mode')} style={{ width: 110 }}>
                          {PAYMENT_MODES.map(m => <option key={m} value={m}>{m || '—'}</option>)}
                        </select>
                      ) : rec.payment_mode || '—'}
                    </td>

                    {/* Start date */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit
                        ? <input className="input input-sm" type="date" value={editData.start_date} onChange={set('start_date')} style={{ width: 130 }} />
                        : rec.start_date || '—'}
                    </td>

                    {/* End date */}
                    <td style={{ padding: '8px 12px' }}>
                      {isEdit
                        ? <input className="input input-sm" type="date" value={editData.end_date} onChange={set('end_date')} style={{ width: 130 }} />
                        : rec.end_date || '—'}
                    </td>

                    {/* Notes */}
                    <td style={{ padding: '8px 12px', maxWidth: 180 }}>
                      {isEdit
                        ? <input className="input input-sm" value={editData.notes} onChange={set('notes')} style={{ width: 160 }} />
                        : <span style={{ color: 'var(--text-3)', fontSize: '.78rem' }}>{rec.notes || '—'}</span>}
                    </td>

                    {/* Modules */}
                    <td style={{ padding: '8px 12px', minWidth: 180 }}>
                      {isEdit ? (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {ALL_MODULES.map(m => {
                            const enabled = (editData.modules || []).includes(m.key)
                            return (
                              <label key={m.key} style={{
                                display: 'flex', alignItems: 'center', gap: 4,
                                fontSize: '.72rem', cursor: 'pointer', whiteSpace: 'nowrap',
                                padding: '2px 6px', borderRadius: 4,
                                background: enabled ? 'var(--brand-light)' : 'var(--surface-3)',
                                color: enabled ? 'var(--brand)' : 'var(--text-3)',
                              }}>
                                <input type="checkbox" checked={enabled}
                                  onChange={() => toggleModule(m.key)}
                                  style={{ width: 12, height: 12, cursor: 'pointer' }} />
                                {m.label}
                              </label>
                            )
                          })}
                        </div>
                      ) : (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                          {(rec.modules || ALL_MODULES.map(m => m.key)).map(k => {
                            const mod = ALL_MODULES.find(m => m.key === k)
                            return mod ? (
                              <span key={k} style={{
                                fontSize: '.68rem', padding: '1px 5px', borderRadius: 3,
                                background: 'var(--surface-3)', color: 'var(--text-2)',
                              }}>{mod.label}</span>
                            ) : null
                          })}
                        </div>
                      )}
                    </td>

                    {/* Actions */}
                    <td style={{ padding: '8px 12px', whiteSpace: 'nowrap' }}>
                      {isEdit ? (
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button className="btn btn-primary btn-sm" onClick={() => saveEdit(rec)} disabled={saving}>
                            <Check size={12}/> {saving ? '…' : 'Save'}
                          </button>
                          <button className="btn btn-ghost btn-sm" onClick={cancelEdit}>
                            <X size={12}/>
                          </button>
                        </div>
                      ) : (
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button className="btn btn-outline btn-sm" onClick={() => startEdit(rec)}>
                            <Edit2 size={12}/>
                          </button>
                          <button className="btn btn-danger btn-sm" onClick={() => deleteUser(rec)}>
                            <Trash2 size={12}/>
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}