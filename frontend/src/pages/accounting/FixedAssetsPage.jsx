import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Plus, RefreshCw, Wrench, PlayCircle, XCircle } from 'lucide-react'
import * as api from '../../lib/booksApi.js'
import { Modal, Field, StatusBadge, EmptyState, fmtAUD, fmtDate, todayISO } from '../../components/books/Common.jsx'
import { CsvImportButton } from '../../components/books/CsvImportModal.jsx'

export default function FixedAssetsPage() {
  const [register, setRegister] = useState(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState(null)
  const [runningDep, setRunningDep] = useState(false)
  const [accounts, setAccounts] = useState([])

  const load = () => {
    setLoading(true)
    api.assetRegister().then(r => setRegister(r.data)).catch(e => toast.error(api.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => { load(); api.ledgerAccounts().then(r => setAccounts(r.data || [])).catch(() => {}) }, [])

  const runDepreciation = async () => {
    setRunningDep(true)
    try {
      const r = await api.runDepreciation({ as_at: todayISO() })
      toast.success(`Depreciation posted for ${r.data.posted.length} asset(s), ${r.data.skipped.length} skipped`)
      load()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setRunningDep(false) }
  }

  const assets = register?.assets || []
  const totals = register?.totals

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 18, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="flex items-center gap-1"><Wrench size={22} /><h2 style={{ margin: 0 }}>Fixed Assets</h2></div>
          <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>Asset register, straight-line or diminishing-value depreciation, disposal.</p>
        </div>
        <div className="flex items-center gap-1">
          <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} /></button>
          <CsvImportButton entity="fixed_assets" onDone={load} />
          <button className="btn btn-outline btn-sm" onClick={runDepreciation} disabled={runningDep}><PlayCircle size={13} /> {runningDep ? 'Running…' : 'Run depreciation to today'}</button>
          <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}><Plus size={13} /> Register asset</button>
        </div>
      </div>

      {totals && (
        <div className="stats-grid" style={{ marginBottom: 16 }}>
          <div className="stat-card"><div className="stat-label">Cost</div><div className="stat-value">{fmtAUD(totals.cost)}</div></div>
          <div className="stat-card"><div className="stat-label">Accumulated Depreciation</div><div className="stat-value">{fmtAUD(totals.accumulated_depreciation)}</div></div>
          <div className="stat-card"><div className="stat-label">Book Value</div><div className="stat-value">{fmtAUD(totals.book_value)}</div></div>
        </div>
      )}

      {assets.length === 0 ? (
        <EmptyState icon="🏗" title="No assets registered yet" hint='Click "Register asset" to add your first fixed asset.' />
      ) : (
        <table className="data-table">
          <thead><tr><th>Number</th><th>Name</th><th>Method</th><th style={{ textAlign: 'right' }}>Cost</th>
            <th style={{ textAlign: 'right' }}>Book Value</th><th>Status</th></tr></thead>
          <tbody>
            {assets.map(a => (
              <tr key={a.id} style={{ cursor: 'pointer', opacity: a.status === 'disposed' ? .6 : 1 }} onClick={() => setOpenId(a.id)}>
                <td className="mono">{a.number}</td><td>{a.name}</td>
                <td className="text-sm">{a.method === 'straight_line' ? 'Straight-line' : 'Diminishing value'}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(a.cost)}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(a.book_value)}</td>
                <td><StatusBadge status={a.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {creating && <AssetFormModal accounts={accounts} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); load() }} />}
      {openId && <AssetDetailModal id={openId} accounts={accounts} onClose={() => setOpenId(null)} onChanged={load} />}
    </div>
  )
}

function AssetFormModal({ accounts, onClose, onSaved }) {
  const [name, setName] = useState(''); const [category, setCategory] = useState('')
  const [assetAccount, setAssetAccount] = useState(''); const [depAccount, setDepAccount] = useState('')
  const [purchaseDate, setPurchaseDate] = useState(todayISO()); const [cost, setCost] = useState('')
  const [residual, setResidual] = useState('0.00'); const [method, setMethod] = useState('straight_line')
  const [lifeMonths, setLifeMonths] = useState(''); const [dvRate, setDvRate] = useState('')
  const [saving, setSaving] = useState(false)

  const fixedAssetAccounts = accounts.filter(a => a.type === 'fixed_asset')

  const save = async () => {
    if (!name.trim() || !assetAccount || !depAccount || !cost) { toast.error('Name, cost, asset account and depreciation account are required'); return }
    if (method === 'straight_line' && !lifeMonths) { toast.error('Straight-line assets need an effective life in months'); return }
    if (method === 'diminishing_value' && !dvRate) { toast.error('Diminishing-value assets need an annual rate'); return }
    setSaving(true)
    try {
      await api.createAsset({
        name: name.trim(), category: category || undefined, asset_account: assetAccount, depreciation_account: depAccount,
        purchase_date: purchaseDate, cost, residual_value: residual, method,
        effective_life_months: method === 'straight_line' ? Number(lifeMonths) : undefined,
        dv_rate_pct: method === 'diminishing_value' ? dvRate : undefined,
      })
      toast.success('Asset registered'); onSaved()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Modal title="Register asset" onClose={onClose} width={480}>
      <Field label="Name *"><input className="input" value={name} onChange={e => setName(e.target.value)} /></Field>
      <Field label="Category"><input className="input" value={category} onChange={e => setCategory(e.target.value)} placeholder="e.g. Office Equipment" /></Field>
      <div className="grid-2" style={{ gap: 12 }}>
        <Field label="Asset account *" hint="A Fixed Asset-type account">
          <select className="select-compact" style={{ width: '100%' }} value={assetAccount} onChange={e => setAssetAccount(e.target.value)}>
            <option value="">Choose…</option>
            {fixedAssetAccounts.filter(a => !a.name.toLowerCase().startsWith('less accumulated')).map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
          </select>
        </Field>
        <Field label="Accum. depreciation account *">
          <select className="select-compact" style={{ width: '100%' }} value={depAccount} onChange={e => setDepAccount(e.target.value)}>
            <option value="">Choose…</option>
            {fixedAssetAccounts.filter(a => a.name.toLowerCase().startsWith('less accumulated')).map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
          </select>
        </Field>
      </div>
      <div className="grid-2" style={{ gap: 12 }}>
        <Field label="Purchase date"><input type="date" className="input" value={purchaseDate} onChange={e => setPurchaseDate(e.target.value)} /></Field>
        <Field label="Cost *"><input type="number" step="0.01" className="input" value={cost} onChange={e => setCost(e.target.value)} /></Field>
      </div>
      <Field label="Residual value" hint="Value left over at the end of its life"><input type="number" step="0.01" className="input" value={residual} onChange={e => setResidual(e.target.value)} /></Field>
      <Field label="Depreciation method">
        <select className="select-compact" style={{ width: '100%' }} value={method} onChange={e => setMethod(e.target.value)}>
          <option value="straight_line">Straight-line</option><option value="diminishing_value">Diminishing value</option>
        </select>
      </Field>
      {method === 'straight_line' ? (
        <Field label="Effective life (months)"><input type="number" className="input" value={lifeMonths} onChange={e => setLifeMonths(e.target.value)} /></Field>
      ) : (
        <Field label="Annual rate (%)"><input type="number" step="0.01" className="input" value={dvRate} onChange={e => setDvRate(e.target.value)} /></Field>
      )}
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Register'}</button>
      </div>
    </Modal>
  )
}

function AssetDetailModal({ id, accounts, onClose, onChanged }) {
  const [asset, setAsset] = useState(null)
  const [showDispose, setShowDispose] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = () => api.getAsset(id).then(r => setAsset(r.data)).catch(e => toast.error(api.errMsg(e)))
  useEffect(() => { load() }, [id])

  const runOne = async () => {
    setBusy(true)
    try { await api.runDepreciation({ as_at: todayISO(), asset_ids: [id] }); toast.success('Depreciation run'); load(); onChanged() }
    catch (e) { toast.error(api.errMsg(e)) } finally { setBusy(false) }
  }

  if (!asset) return <Modal title="Asset" onClose={onClose}><div className="spinner" /></Modal>

  return (
    <Modal title={`${asset.number} — ${asset.name}`} onClose={onClose} width={520}>
      <div className="flex items-center gap-4" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
        <StatusBadge status={asset.status} />
        <span className="text-sm text-muted">Purchased {fmtDate(asset.purchase_date)}</span>
        <div className="flex-1" />
        {asset.status === 'active' && (
          <>
            <button className="btn btn-outline btn-xs" onClick={runOne} disabled={busy}><PlayCircle size={12} /> Run depreciation</button>
            <button className="btn btn-ghost btn-xs" onClick={() => setShowDispose(true)}><XCircle size={12} /> Dispose</button>
          </>
        )}
      </div>
      <div className="grid-2" style={{ gap: 8, fontSize: '.85rem' }}>
        <div>Cost: <strong>{fmtAUD(asset.cost)}</strong></div>
        <div>Residual: <strong>{fmtAUD(asset.residual_value)}</strong></div>
        <div>Accumulated depreciation: <strong>{fmtAUD(asset.accumulated_depreciation)}</strong></div>
        <div>Book value: <strong>{fmtAUD(asset.book_value)}</strong></div>
        <div>Method: <strong>{asset.method === 'straight_line' ? 'Straight-line' : 'Diminishing value'}</strong></div>
        <div>{asset.method === 'straight_line' ? `Life: ${asset.effective_life_months} months` : `Rate: ${asset.dv_rate_pct}%/yr`}</div>
        <div>Asset account: {asset.asset_account}</div>
        <div>Accum. dep. account: {asset.depreciation_account}</div>
        {asset.last_depreciation_date && <div>Last run: {fmtDate(asset.last_depreciation_date)}</div>}
        {asset.status === 'disposed' && <div>Disposed {fmtDate(asset.disposal_date)}, proceeds {fmtAUD(asset.disposal_proceeds)}</div>}
      </div>

      {showDispose && <DisposeModal asset={asset} accounts={accounts} onClose={() => setShowDispose(false)} onDone={() => { setShowDispose(false); load(); onChanged() }} />}
    </Modal>
  )
}

function DisposeModal({ asset, accounts, onClose, onDone }) {
  const [date, setDate] = useState(todayISO())
  const [proceeds, setProceeds] = useState('0.00')
  const [bank, setBank] = useState('')
  const [saving, setSaving] = useState(false)
  const banks = accounts.filter(a => a.type === 'bank')

  const save = async () => {
    setSaving(true)
    try {
      const r = await api.disposeAsset(asset.id, { date, proceeds, bank_account: Number(proceeds) > 0 ? bank : undefined })
      toast.success(`Disposed - ${r.data.disposal.gain_or_loss >= 0 ? 'gain' : 'loss'} of ${fmtAUD(Math.abs(r.data.disposal.gain_or_loss))}`)
      onDone()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Modal title={`Dispose ${asset.number}`} onClose={onClose} width={400}>
      <Field label="Disposal date"><input type="date" className="input" value={date} onChange={e => setDate(e.target.value)} /></Field>
      <Field label="Proceeds"><input type="number" step="0.01" className="input" value={proceeds} onChange={e => setProceeds(e.target.value)} /></Field>
      {Number(proceeds) > 0 && (
        <Field label="Bank account">
          <select className="select-compact" style={{ width: '100%' }} value={bank} onChange={e => setBank(e.target.value)}>
            <option value="">Choose…</option>
            {banks.map(b => <option key={b.id} value={b.code}>{b.code} {b.name}</option>)}
          </select>
        </Field>
      )}
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-danger btn-sm" onClick={save} disabled={saving || (Number(proceeds) > 0 && !bank)}>{saving ? 'Saving…' : 'Dispose'}</button>
      </div>
    </Modal>
  )
}
