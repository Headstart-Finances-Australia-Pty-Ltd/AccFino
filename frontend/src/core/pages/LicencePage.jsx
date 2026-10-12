import React, { useEffect, useState } from 'react'
import { licenceList, licenceSave, licenceDeleteUser, licenceUpdateUser, register, changePassword } from '../lib/api.js'
import { adminBulkDeleteUsers } from '../lib/adminApi.js'
import { useForceDeleteSwitch, useRowSelection, SelectAllCheckbox, RowCheckbox, ForceDeleteButton, reportBulkResult, announceDataChanged, DATA_CHANGED_EVENT } from '../components/ui/ForceDelete.jsx'
import { Edit2, Trash2, Check, X, Plus, RefreshCw, Save, BadgeCheck, UserCog, KeyRound, Building2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuth } from '../hooks/useAuth.jsx'
import IdentityPage from './settings/IdentityPage.jsx'
import OrgDirectoryPanel from './admin/OrgDirectoryPanel.jsx'
import UserPlansPanel from './admin/UserPlansPanel.jsx'

const LICENCE_TYPES  = ['demo', 'trial', 'paid', 'suspended']

const ALL_MODULES = [
  { key: 'dashboard',      label: '📊 Dashboard' },
  { key: 'reconciliation', label: '🔄 Reconciliation' },
  { key: 'trading',        label: '📈 Trading' },
  { key: 'cash-flow',      label: '📉 Cash Flow' },
  { key: 'invoice',        label: '🧾 Invoice' },
  { key: 'admin',          label: '🛡 Admin & ML' },
  { key: 'file-manager',   label: '📁 Data Manager' },
  { key: 'licence',        label: '🏷 Users & Licence' },
]
const PAYMENT_MODES  = ['', 'card', 'bank_transfer', 'invoice', 'paypal', 'other']

const EMPTY_LIC = {
  licence_type: 'demo', payment_mode: '', start_date: '', end_date: '', notes: ''
}

export default function LicencePage() {
  const { user } = useAuth()
  const [view, setView] = useState('organisations') // 'organisations' | 'licence' | 'platform-users' | 'password'
  const [records,  setRecords]  = useState([])
  const [loading,  setLoading]  = useState(true)
  const [editId,      setEditId]      = useState(null)
  const [showAddUser, setShowAddUser] = useState(false)
  const [newUser,     setNewUser]     = useState({ username:'', full_name:'', email:'', password:'', role:'user' })
  const [addingUser,  setAddingUser]  = useState(false)
  const [editData, setEditData] = useState({})
  const [saving,   setSaving]   = useState(false)

  // Row selection + Force delete. The platform administrator and the signed-in account can never be deleted, so they get no checkbox.
  const forceOn = useForceDeleteSwitch()
  const [bulkBusy, setBulkBusy] = useState(false)
  const isProtectedRec = rec => (rec.roles || []).includes('admin') || (rec.email || '').toLowerCase() === 'admin@accfino.com' || rec.user_id === user?.id
  const sel = useRowSelection(records.filter(r => !isProtectedRec(r)).map(r => r.user_id))

  // ── Change Password (moved here from Admin > API Keys) ──────────────
  const [pwForm, setPwForm] = useState({ old_password:'', new_password:'' })
  const changePw = async e => {
    e.preventDefault()
    try {
      await changePassword({ email: user.email, ...pwForm })
      toast.success('Password updated')
      setPwForm({ old_password:'', new_password:'' })
    } catch { toast.error('Failed — check current password') }
  }

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await licenceList()
      setRecords(data || [])
    } catch { toast.error('Failed to load licence data') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useEffect(() => {                                    // rows deleted elsewhere (Organisations & Users, Subscriptions): reload at once
    const again = async () => { try { const { data } = await licenceList(); setRecords(data || []) } catch {} }
    window.addEventListener(DATA_CHANGED_EVENT, again)
    return () => window.removeEventListener(DATA_CHANGED_EVENT, again)
  }, [])

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
      announceDataChanged()
    } catch (e) {
      // show the server's reason (e.g. "The platform administrator account cannot be deleted.") instead of a bare "Delete failed"
      const d = e?.response?.data?.detail
      toast.error(typeof d === 'string' && d ? d : 'Delete failed')
    }
  }

  const forceDeleteSelected = async () => {
    const ids = sel.ids
    if (!ids.length) return
    const names = records.filter(r => ids.includes(r.user_id)).map(r => r.username).join(', ')
    if (!confirm(`FORCE DELETE ${ids.length} user${ids.length === 1 ? '' : 's'} and all their data?\n\n${names}\n\nThis cannot be undone.`)) return
    setBulkBusy(true)
    try {
      const { data } = await adminBulkDeleteUsers(ids, true)
      const done = reportBulkResult(data, 'user')
      setRecords(r => r.filter(x => !done.includes(x.user_id)))
      sel.clear()
      announceDataChanged()
    } catch (e) {
      const d = e?.response?.data?.detail
      toast.error(typeof d === 'string' && d ? d : 'Force delete failed')
    } finally { setBulkBusy(false) }
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
      <div className="tabs-bar" style={{ marginBottom: 16 }} role="tablist">
        <button className={`tab-btn${view === 'organisations' ? ' active' : ''}`} onClick={() => setView('organisations')}>
          <Building2 size={14} style={{ marginRight: 5, verticalAlign: '-2px' }} />Organisations &amp; Users
        </button>
        <button className={`tab-btn${view === 'licence' ? ' active' : ''}`} onClick={() => setView('licence')}>
          <BadgeCheck size={14} style={{ marginRight: 5, verticalAlign: '-2px' }} />Plans by User
        </button>
        <button className={`tab-btn${view === 'platform-users' ? ' active' : ''}`} onClick={() => setView('platform-users')}>
          <UserCog size={14} style={{ marginRight: 5, verticalAlign: '-2px' }} />Platform Users
        </button>
        <button className={`tab-btn${view === 'password' ? ' active' : ''}`} onClick={() => setView('password')}>
          <KeyRound size={14} style={{ marginRight: 5, verticalAlign: '-2px' }} />Password
        </button>
      </div>

      {view === 'password' && (
        <div style={{ maxWidth: 400 }}>
          <div className="card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18, paddingBottom: 14, borderBottom: '1px solid var(--border)' }}>
              <KeyRound size={18} color="var(--brand)" /><h3>Change Password</h3>
            </div>
            <form onSubmit={changePw} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="input-group"><label>Current Password</label><input className="input" type="password" value={pwForm.old_password} onChange={e => setPwForm(p => ({ ...p, old_password: e.target.value }))} required /></div>
              <div className="input-group"><label>New Password</label><input className="input" type="password" value={pwForm.new_password} onChange={e => setPwForm(p => ({ ...p, new_password: e.target.value }))} required /></div>
              <button className="btn btn-primary" type="submit">Update Password</button>
            </form>
          </div>
        </div>
      )}

      {view === 'organisations' && <OrgDirectoryPanel />}

      {view === 'platform-users' && <IdentityPage />}

      {view === 'licence' && <UserPlansPanel />}
    </div>
  )
}