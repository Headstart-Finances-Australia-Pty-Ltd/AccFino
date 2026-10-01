import React, { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Plus, RefreshCw, Package, ArrowUpCircle, ArrowDownCircle, ClipboardList } from 'lucide-react'
import * as api from '../../lib/booksApi.js'
import { Modal, Field, EmptyState, fmtAUD, todayISO } from '../../components/books/Common.jsx'
import { CsvImportButton } from '../../components/books/CsvImportModal.jsx'

export default function InventoryPage() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState(null)
  const [accounts, setAccounts] = useState([])
  const [taxes, setTaxes] = useState([])
  const [totalValue, setTotalValue] = useState('0.00')

  const load = () => {
    setLoading(true)
    Promise.all([api.listStockItems(), api.inventoryValuation()])
      .then(([r, v]) => { setItems(r.data?.items || []); setTotalValue(v.data?.total_value || '0.00') })
      .catch(e => toast.error(api.errMsg(e))).finally(() => setLoading(false))
  }
  useEffect(() => {
    load()
    api.ledgerAccounts().then(r => setAccounts(r.data || [])).catch(() => {})
    api.taxCodes().then(r => setTaxes(r.data || [])).catch(() => {})
  }, [])

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 18, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="flex items-center gap-1"><Package size={22} /><h2 style={{ margin: 0 }}>Inventory & Trading</h2></div>
          <p className="text-sm text-muted" style={{ margin: '4px 0 0' }}>Stock items, weighted-average cost, and stocktakes.</p>
        </div>
        <div className="flex items-center gap-1">
          <CsvImportButton entity="inventory_items" label="Import items" onDone={load} />
          <CsvImportButton entity="stock_movements" label="Import movements" onDone={load} />
          <button className="btn btn-outline btn-sm" onClick={load} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} /></button>
          <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}><Plus size={13} /> New item</button>
        </div>
      </div>

      <div className="stats-grid" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-label">Total stock value on hand</div>
          <div className="stat-value">{fmtAUD(totalValue)}</div>
          <div className="stat-sub">{items.length} active item{items.length === 1 ? '' : 's'}</div>
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState icon="📦" title="No stock items yet" hint='Click "New item" to add your first product.' />
      ) : (
        <table className="data-table">
          <thead><tr><th>SKU</th><th>Name</th><th style={{ textAlign: 'right' }}>Qty on hand</th>
            <th style={{ textAlign: 'right' }}>Avg cost</th><th style={{ textAlign: 'right' }}>Value</th></tr></thead>
          <tbody>
            {items.map(it => (
              <tr key={it.id} style={{ cursor: 'pointer' }} onClick={() => setOpenId(it.id)}>
                <td className="mono">{it.sku}</td><td>{it.name}</td>
                <td style={{ textAlign: 'right' }} className="mono">{it.quantity_on_hand}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(it.average_cost)}</td>
                <td style={{ textAlign: 'right' }} className="mono">{fmtAUD(it.value_on_hand)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {creating && <ItemFormModal accounts={accounts} taxes={taxes} onClose={() => setCreating(false)} onSaved={id => { setCreating(false); load(); setOpenId(id) }} />}
      {openId && <ItemDetailModal id={openId} accounts={accounts} onClose={() => setOpenId(null)} onChanged={load} />}
    </div>
  )
}

function ItemFormModal({ accounts, taxes, onClose, onSaved }) {
  const [sku, setSku] = useState(''); const [name, setName] = useState(''); const [description, setDescription] = useState('')
  const [invAcc, setInvAcc] = useState(''); const [cogsAcc, setCogsAcc] = useState(''); const [salesAcc, setSalesAcc] = useState('')
  const [purchaseTax, setPurchaseTax] = useState(''); const [salesTax, setSalesTax] = useState(''); const [salePrice, setSalePrice] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!sku.trim() || !name.trim()) { toast.error('SKU and name are required'); return }
    setSaving(true)
    try {
      const r = await api.createStockItem({
        sku: sku.trim(), name: name.trim(), description: description || undefined, inventory_account: invAcc || undefined,
        cogs_account: cogsAcc || undefined, sales_account: salesAcc || undefined, purchase_tax_code: purchaseTax || undefined,
        sales_tax_code: salesTax || undefined, sale_price: salePrice || undefined,
      })
      toast.success('Item created'); onSaved(r.data.id)
    } catch (e) { toast.error(api.errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Modal title="New stock item" onClose={onClose} width={480}>
      <div className="grid-2" style={{ gap: 12 }}>
        <Field label="SKU *"><input className="input" value={sku} onChange={e => setSku(e.target.value)} /></Field>
        <Field label="Name *"><input className="input" value={name} onChange={e => setName(e.target.value)} /></Field>
      </div>
      <Field label="Description"><textarea className="input" rows={2} value={description} onChange={e => setDescription(e.target.value)} /></Field>
      <Field label="Inventory account" hint="Defaults to the organisation's Inventory account">
        <select className="select-compact" style={{ width: '100%' }} value={invAcc} onChange={e => setInvAcc(e.target.value)}>
          <option value="">Default</option>
          {accounts.filter(a => a.type === 'inventory').map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
        </select>
      </Field>
      <Field label="Cost of goods sold account" hint="Defaults to the organisation's COGS account">
        <select className="select-compact" style={{ width: '100%' }} value={cogsAcc} onChange={e => setCogsAcc(e.target.value)}>
          <option value="">Default</option>
          {accounts.filter(a => a.type === 'direct_costs').map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
        </select>
      </Field>
      <Field label="Sales account (optional)">
        <select className="select-compact" style={{ width: '100%' }} value={salesAcc} onChange={e => setSalesAcc(e.target.value)}>
          <option value="">None</option>
          {accounts.filter(a => ['revenue', 'other_income'].includes(a.type)).map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
        </select>
      </Field>
      <div className="grid-2" style={{ gap: 12 }}>
        <Field label="Purchase tax code">
          <select className="select-compact" style={{ width: '100%' }} value={purchaseTax} onChange={e => setPurchaseTax(e.target.value)}>
            <option value="">None</option>
            {taxes.filter(t => t.applies_to === 'purchases' || t.applies_to === 'both').map(t => <option key={t.id} value={t.code}>{t.code}</option>)}
          </select>
        </Field>
        <Field label="Sales tax code">
          <select className="select-compact" style={{ width: '100%' }} value={salesTax} onChange={e => setSalesTax(e.target.value)}>
            <option value="">None</option>
            {taxes.filter(t => t.applies_to === 'sales' || t.applies_to === 'both').map(t => <option key={t.id} value={t.code}>{t.code}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Sale price (optional)"><input type="number" step="0.01" className="input" value={salePrice} onChange={e => setSalePrice(e.target.value)} /></Field>
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </Modal>
  )
}

function ItemDetailModal({ id, accounts, onClose, onChanged }) {
  const [item, setItem] = useState(null)
  const [movements, setMovements] = useState([])
  const [showMove, setShowMove] = useState(null)   // 'buy' | 'sell' | 'adjustment' | null

  const load = () => {
    api.getStockItem(id).then(r => setItem(r.data)).catch(e => toast.error(api.errMsg(e)))
    api.itemMovements(id).then(r => setMovements(r.data?.items || [])).catch(() => {})
  }
  useEffect(() => { load() }, [id])

  if (!item) return <Modal title="Stock item" onClose={onClose}><div className="spinner" /></Modal>

  return (
    <Modal title={`${item.sku} — ${item.name}`} onClose={onClose} width={640}>
      <div className="flex items-center gap-4" style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <span className="text-sm">Qty on hand: <strong>{item.quantity_on_hand}</strong></span>
        <span className="text-sm">Avg cost: <strong>{fmtAUD(item.average_cost)}</strong></span>
        <span className="text-sm">Value: <strong>{fmtAUD(item.value_on_hand)}</strong></span>
        <div className="flex-1" />
        <button className="btn btn-outline btn-xs" onClick={() => setShowMove('buy')}><ArrowUpCircle size={12} /> Buy</button>
        <button className="btn btn-outline btn-xs" onClick={() => setShowMove('sell')}><ArrowDownCircle size={12} /> Sell</button>
        <button className="btn btn-outline btn-xs" onClick={() => setShowMove('adjustment')}><ClipboardList size={12} /> Stocktake</button>
      </div>

      <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>Movement history</div>
      {movements.length === 0 ? <p className="text-sm text-muted">No movements yet.</p> : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.8rem' }}>
          <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ textAlign: 'left', padding: '4px 6px' }}>Date</th><th style={{ padding: '4px 6px' }}>Kind</th>
            <th style={{ padding: '4px 6px' }}>Qty</th><th style={{ padding: '4px 6px' }}>Unit cost</th><th style={{ padding: '4px 6px' }}>Amount</th></tr></thead>
          <tbody>{movements.map(m => (
            <tr key={m.id}><td style={{ padding: '4px 6px' }}>{m.date}</td><td style={{ padding: '4px 6px' }}>{m.kind}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right' }}>{m.quantity}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right' }} className="mono">{m.unit_cost ? fmtAUD(m.unit_cost) : '—'}</td>
              <td style={{ padding: '4px 6px', textAlign: 'right' }} className="mono">{fmtAUD(m.amount)}</td></tr>
          ))}</tbody>
        </table>
      )}

      {showMove && (
        <MovementModal kind={showMove} item={item} accounts={accounts} onClose={() => setShowMove(null)}
          onDone={() => { setShowMove(null); load(); onChanged() }} />
      )}
    </Modal>
  )
}

function MovementModal({ kind, item, accounts, onClose, onDone }) {
  const [date, setDate] = useState(todayISO())
  const [quantity, setQuantity] = useState('')
  const [unitCost, setUnitCost] = useState('')
  const [countedQuantity, setCountedQuantity] = useState(item.quantity_on_hand)
  const [account, setAccount] = useState('')
  const [reference, setReference] = useState('')
  const [saving, setSaving] = useState(false)
  const label = { buy: 'Buy stock', sell: 'Sell stock', adjustment: 'Stocktake adjustment' }[kind]

  const save = async () => {
    setSaving(true)
    try {
      const body = kind === 'adjustment'
        ? { kind, date, counted_quantity: countedQuantity, account: account || undefined, reference: reference || undefined }
        : kind === 'buy'
        ? { kind, date, quantity, unit_cost: unitCost, credit_account: account || undefined, reference: reference || undefined }
        : { kind, date, quantity, debit_account: account || undefined, reference: reference || undefined }
      await api.recordMovement(item.id, body)
      toast.success('Recorded'); onDone()
    } catch (e) { toast.error(api.errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Modal title={label} onClose={onClose} width={420}>
      <Field label="Date"><input type="date" className="input" value={date} onChange={e => setDate(e.target.value)} /></Field>
      {kind === 'adjustment' ? (
        <Field label="Counted quantity" hint={`Currently ${item.quantity_on_hand} on hand`}>
          <input type="number" step="0.01" className="input" value={countedQuantity} onChange={e => setCountedQuantity(e.target.value)} />
        </Field>
      ) : (
        <>
          <Field label="Quantity"><input type="number" step="0.01" className="input" value={quantity} onChange={e => setQuantity(e.target.value)} /></Field>
          {kind === 'buy' && <Field label="Unit cost"><input type="number" step="0.0001" className="input" value={unitCost} onChange={e => setUnitCost(e.target.value)} /></Field>}
        </>
      )}
      <Field label={kind === 'buy' ? 'Credit account (e.g. Accounts Payable or Bank)' : kind === 'sell' ? 'Debit account (defaults to the item\'s COGS account)' : 'Adjustment account (defaults to the item\'s COGS account)'}>
        <select className="select-compact" style={{ width: '100%' }} value={account} onChange={e => setAccount(e.target.value)}>
          <option value="">Default</option>
          {accounts.map(a => <option key={a.id} value={a.code}>{a.code} {a.name}</option>)}
        </select>
      </Field>
      <Field label="Reference (optional)"><input className="input" value={reference} onChange={e => setReference(e.target.value)} /></Field>
      <div className="flex justify-between" style={{ marginTop: 12 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </Modal>
  )
}
