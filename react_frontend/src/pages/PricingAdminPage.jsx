import React, { useEffect, useState } from 'react'
import { getPricingPlans, updatePricingPlan } from '../lib/api'
import { Edit2, Check, X, RefreshCw, Save } from 'lucide-react'
import toast from 'react-hot-toast'

const MOD_OPTIONS = ['dashboard','reconciliation','trading','cash-flow','invoice']

const FIELD_LABELS = {
  name:          'Plan Name',
  description:   'Description',
  price_monthly: 'Monthly Price (cents AUD)',
  price_yearly:  'Yearly Price (cents AUD)',
  badge:         'Badge Text',
  highlight:     'Highlight',
}

export default function PricingAdminPage() {
  const [plans,   setPlans]   = useState({})
  const [editId,  setEditId]  = useState(null)
  const [editData,setEditData]= useState({})
  const [saving,  setSaving]  = useState(false)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    getPricingPlans()
      .then(r => setPlans(r.data || {}))
      .catch(() => toast.error('Failed to load pricing'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const startEdit = (planId) => {
    setEditId(planId)
    setEditData({ ...plans[planId] })
  }

  const saveEdit = async () => {
    setSaving(true)
    try {
      await updatePricingPlan(editId, editData)
      setPlans(p => ({ ...p, [editId]: editData }))
      toast.success(`${editData.name} pricing saved`)
      setEditId(null)
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Save failed')
    } finally { setSaving(false) }
  }

  const toggleMod = (mod) => {
    const mods = editData.modules || []
    setEditData(d => ({
      ...d,
      modules: mods.includes(mod) ? mods.filter(m => m !== mod) : [...mods, mod]
    }))
  }

  const fmt = (cents) => cents === 0 ? 'Free' : `$${(cents/100).toFixed(2)}/mo`

  return (
    <div>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:20 }}>
        <div>
          <h2 style={{ margin:0 }}>Plan Pricing</h2>
          <p style={{ color:'var(--text-3)', fontSize:'.85rem', margin:'4px 0 0' }}>
            Edit plan prices and features — changes take effect immediately
          </p>
        </div>
        <div style={{ flex:1 }}/>
        <button className="btn btn-outline btn-sm" onClick={load}>
          <RefreshCw size={13}/> Refresh
        </button>
      </div>

      {loading ? (
        <div style={{ textAlign:'center', padding:40, color:'var(--text-3)' }}>
          <span className="spinner"/> Loading…
        </div>
      ) : (
        <div style={{ overflowX:'auto' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'.82rem' }}>
            <thead>
              <tr style={{ background:'var(--surface-2)', borderBottom:'2px solid var(--border)' }}>
                {['Plan','Description','Monthly','Yearly','Effective From','Badge','Modules','Features','Actions']
                  .map(h => (
                    <th key={h} style={{ padding:'10px 12px', textAlign:'left',
                      fontWeight:600, color:'var(--text-2)', whiteSpace:'nowrap' }}>
                      {h}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(plans).map(([planId, plan], i) => {
                const isEdit = editId === planId
                return (
                  <tr key={planId} style={{ borderBottom:'1px solid var(--border)',
                    background: i%2===0 ? 'transparent' : 'var(--surface-2)' }}>

                    {/* Plan name */}
                    <td style={{ padding:'8px 12px', fontWeight:700 }}>
                      {isEdit
                        ? <input className="input input-sm" value={editData.name}
                            onChange={e => setEditData(d=>({...d,name:e.target.value}))}
                            style={{width:100}}/>
                        : <>{plan.name} {plan.highlight && <span style={{
                            fontSize:'.68rem',background:'var(--brand)',color:'#fff',
                            padding:'1px 6px',borderRadius:100,marginLeft:4
                          }}>{plan.badge||'⭐'}</span>}</>}
                    </td>

                    {/* Description */}
                    <td style={{ padding:'8px 12px', maxWidth:200 }}>
                      {isEdit
                        ? <input className="input input-sm" value={editData.description}
                            onChange={e => setEditData(d=>({...d,description:e.target.value}))}
                            style={{width:180}}/>
                        : <span style={{color:'var(--text-3)',fontSize:'.78rem'}}>{plan.description}</span>}
                    </td>

                    {/* Monthly price */}
                    <td style={{ padding:'8px 12px', whiteSpace:'nowrap' }}>
                      {isEdit
                        ? <div>
                            <input className="input input-sm" type="number"
                              value={editData.price_monthly}
                              onChange={e => setEditData(d=>({...d,
                              price_monthly: parseInt(e.target.value)||0,
                              price_effective_from: new Date().toISOString().slice(0,10),
                            }))}
                              style={{width:90}}/>
                            <div style={{fontSize:'.68rem',color:'var(--text-3)',marginTop:2}}>
                              = ${((editData.price_monthly||0)/100).toFixed(2)}
                            </div>
                          </div>
                        : <span style={{fontWeight:600,color:'var(--brand)'}}>
                            {fmt(plan.price_monthly)}
                          </span>}
                    </td>

                    {/* Yearly price */}
                    <td style={{ padding:'8px 12px', whiteSpace:'nowrap' }}>
                      {isEdit
                        ? <div>
                            <input className="input input-sm" type="number"
                              value={editData.price_yearly}
                              onChange={e => setEditData(d=>({...d,
                              price_yearly: parseInt(e.target.value)||0,
                              price_effective_from: new Date().toISOString().slice(0,10),
                            }))}
                              style={{width:90}}/>
                            <div style={{fontSize:'.68rem',color:'var(--text-3)',marginTop:2}}>
                              = ${((editData.price_yearly||0)/100).toFixed(2)}
                            </div>
                          </div>
                        : <span style={{color:'var(--text-2)'}}>
                            {plan.price_yearly === 0 ? 'Free' : `$${(plan.price_yearly/100).toFixed(2)}/yr`}
                          </span>}
                    </td>

                    {/* Badge */}
                    <td style={{ padding:'8px 12px' }}>
                      {isEdit
                        ? <input className="input input-sm" value={editData.badge||''}
                            placeholder="e.g. Best Value"
                            onChange={e => setEditData(d=>({...d,badge:e.target.value}))}
                            style={{width:100}}/>
                        : plan.badge || '—'}
                    </td>

                    {/* Effective From */}
                    <td style={{ padding:'8px 12px', whiteSpace:'nowrap' }}>
                      {isEdit
                        ? <input className="input input-sm" type="date"
                            value={editData.price_effective_from || ''}
                            onChange={e => setEditData(d=>({...d, price_effective_from: e.target.value}))}
                            style={{width:130}}/>
                        : <span style={{fontSize:'.78rem', color:'var(--text-3)'}}>
                            {plan.price_effective_from || '—'}
                          </span>}
                    </td>

                    {/* Modules */}
                    <td style={{ padding:'8px 12px', minWidth:160 }}>
                      {isEdit
                        ? <div style={{display:'flex',flexWrap:'wrap',gap:4}}>
                            {MOD_OPTIONS.map(m => {
                              const sel = (editData.modules||[]).includes(m)
                              return (
                                <label key={m} style={{
                                  display:'flex',alignItems:'center',gap:3,
                                  fontSize:'.7rem',cursor:'pointer',padding:'2px 6px',
                                  borderRadius:4,
                                  background: sel ? 'var(--brand-light)' : 'var(--surface-3)',
                                  color: sel ? 'var(--brand)' : 'var(--text-3)',
                                }}>
                                  <input type="checkbox" checked={sel}
                                    onChange={() => toggleMod(m)}
                                    style={{width:11,height:11}}/>
                                  {m}
                                </label>
                              )
                            })}
                          </div>
                        : <div style={{display:'flex',flexWrap:'wrap',gap:3}}>
                            {(plan.modules||[]).map(m => (
                              <span key={m} style={{fontSize:'.68rem',padding:'1px 5px',
                                borderRadius:3,background:'var(--surface-3)',color:'var(--text-2)'}}>
                                {m}
                              </span>
                            ))}
                          </div>}
                    </td>

                    {/* Features */}
                    <td style={{ padding:'8px 12px', maxWidth:200 }}>
                      {isEdit
                        ? <textarea className="input input-sm"
                            value={(editData.features||[]).join('\n')}
                            onChange={e => setEditData(d=>({
                              ...d, features: e.target.value.split('\n').filter(Boolean)
                            }))}
                            style={{width:180,height:80,fontSize:'.72rem'}}/>
                        : <div style={{fontSize:'.72rem',color:'var(--text-3)'}}>
                            {(plan.features||[]).slice(0,2).join(' · ')}
                            {(plan.features||[]).length > 2 && ` +${plan.features.length-2} more`}
                          </div>}
                    </td>

                    {/* Actions */}
                    <td style={{ padding:'8px 12px', whiteSpace:'nowrap' }}>
                      {isEdit ? (
                        <div style={{display:'flex',gap:4}}>
                          <button className="btn btn-primary btn-sm"
                            onClick={saveEdit} disabled={saving}>
                            <Check size={12}/> {saving ? '…' : 'Save'}
                          </button>
                          <button className="btn btn-ghost btn-sm"
                            onClick={() => { setEditId(null); setEditData({}) }}>
                            <X size={12}/>
                          </button>
                        </div>
                      ) : (
                        <button className="btn btn-outline btn-sm"
                          onClick={() => startEdit(planId)}>
                          <Edit2 size={12}/> Edit
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="card card-flat" style={{marginTop:20,padding:16}}>
        <p style={{margin:0,fontSize:'.82rem',color:'var(--text-3)'}}>
          💡 <strong>Prices are in AUD cents</strong> — e.g. $19.00/mo = 1900 · $190.00/yr = 19000.
          Changes are saved to <code>main_app/data/pricing.json</code> and take effect immediately
          without redeployment.
        </p>
      </div>
    </div>
  )
}
