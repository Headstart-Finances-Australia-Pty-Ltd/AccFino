import React, { useState, useRef } from 'react'
import { cfDetect, cfRun, cfPredict } from '../lib/api.js'
import { Upload, PlayCircle, TrendingUp, Download } from 'lucide-react'
import toast from 'react-hot-toast'

const fmtAUD = n => new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD',maximumFractionDigits:0}).format(n||0)

export default function CashFlowPage() {
  const [step,     setStep]     = useState(1)   // 1=upload, 2=map, 3=train, 4=predict, 5=result
  const [fileData, setFileData] = useState(null) // {rows, columns, detected, row_count}
  const [colMap,   setColMap]   = useState({})
  const [runResult,setRunResult]= useState(null) // {run_id, leaderboard, model_names, ...}
  const [chosen,   setChosen]   = useState('')
  const [pred,     setPred]     = useState(null)
  const [busy,     setBusy]     = useState(false)
  const fileRef = useRef()

  // Step 1 — upload & detect
  const handleUpload = async e => {
    const file = e.target.files[0]; if (!file) return
    setBusy(true)
    try {
      const fd = new FormData(); fd.append('file', file, file.name)
      const { data } = await cfDetect(fd)
      setFileData(data)
      // Init col map from detected
      const cm = {}
      ;['date','debit','credit','balance','desc'].forEach(k => {
        cm[k] = data.detected[k] || '(none)'
      })
      setColMap(cm)
      setStep(2)
    } catch (e) { toast.error(e.response?.data?.detail||'Upload failed') }
    finally { setBusy(false) }
  }

  // Step 3 — run pipeline
  const handleRun = async () => {
    const missing = ['date','debit','credit'].filter(k => !colMap[k] || colMap[k]==='(none)')
    if (missing.length) { toast.error(`Map required columns: ${missing.join(', ')}`); return }
    setBusy(true)
    try {
      const { data } = await cfRun(fileData.rows || [], colMap)
      setRunResult(data)
      setChosen(data.model_names[0] || '')
      setStep(4)
      toast.success(`Trained ${data.model_names.length} models`)
    } catch (e) { toast.error(e.response?.data?.detail||'Training failed') }
    finally { setBusy(false) }
  }

  // Step 4 — predict
  const handlePredict = async () => {
    if (!runResult?.run_id || !chosen) { toast.error('Select a model first'); return }
    setBusy(true)
    try {
      const { data } = await cfPredict(runResult.run_id, JSON.stringify(chosen))
      setPred(data); setStep(5)
    } catch (e) { toast.error(e.response?.data?.detail||'Prediction failed') }
    finally { setBusy(false) }
  }

  const downloadCsv = (csvStr, fname) => {
    const blob = new Blob([csvStr], {type:'text/csv'})
    const a = document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=fname; a.click()
  }

  const opts = fileData ? ['(none)', ...fileData.columns] : ['(none)']
  const REQUIRED = ['date','debit','credit']

  return (
    <div className="fade-in">
      <div style={{marginBottom:22}}>
        <h1>💰 Cash Flow Forecast</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          Upload 12+ months of transactions · map columns · train 17 ML models · predict next month
        </p>
      </div>

      {/* Step indicators */}
      <div style={{display:'flex',gap:0,marginBottom:24,alignItems:'center'}}>
        {['Upload','Map Columns','Train Models','Choose Model','Forecast'].map((s,i)=>{
          const n=i+1; const done=step>n; const active=step===n
          return (
            <React.Fragment key={n}>
              <div style={{display:'flex',alignItems:'center',gap:8}}>
                <div style={{width:28,height:28,borderRadius:'50%',
                  background:done?'var(--success)':active?'var(--brand)':'var(--surface-3)',
                  color:done||active?'#fff':'var(--text-3)',display:'flex',alignItems:'center',
                  justifyContent:'center',fontSize:'.78rem',fontWeight:700,flexShrink:0}}>
                  {done?'✓':n}
                </div>
                <span style={{fontSize:'.8rem',fontWeight:active?700:400,
                  color:active?'var(--brand)':done?'var(--success)':'var(--text-3)',whiteSpace:'nowrap'}}>{s}</span>
              </div>
              {i<4&&<div style={{flex:1,height:2,background:done?'var(--success)':'var(--border)',margin:'0 8px',minWidth:12}}/>}
            </React.Fragment>
          )
        })}
      </div>

      {/* Step 1: Upload */}
      {step===1 && (
        <div className="card" style={{maxWidth:520}}>
          <h3 style={{marginBottom:14}}>1. Upload Transaction CSV</h3>
          <p style={{color:'var(--text-3)',fontSize:'.875rem',marginBottom:16}}>Minimum 12 months of data recommended for reliable forecasting.</p>
          <div className="drop-zone" onClick={()=>fileRef.current.click()} style={{marginBottom:12}}>
            <Upload size={22} className="drop-icon"/>
            <div style={{fontWeight:600,fontSize:'.875rem',color:'var(--text-2)'}}>Click to upload CSV file</div>
            <div style={{fontSize:'.75rem',color:'var(--text-3)'}}>Bank statement or transaction export</div>
          </div>
          <input ref={fileRef} type="file" accept=".csv" style={{display:'none'}} onChange={handleUpload}/>
          {busy && <div style={{display:'flex',alignItems:'center',gap:8,color:'var(--text-3)',fontSize:'.875rem'}}><span className="spinner spinner-sm"/>Detecting columns…</div>}
        </div>
      )}

      {/* Step 2: Column mapping */}
      {step>=2 && fileData && (
        <div className="card" style={{marginBottom:16}}>
          <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}}>
            <h3>2. Map Columns ({fileData.row_count?.toLocaleString()} rows loaded)</h3>
            <button className="btn btn-ghost btn-sm" onClick={()=>{setStep(1);setFileData(null)}}>↩ Re-upload</button>
          </div>
          <div style={{display:'grid',gridTemplateColumns:'repeat(5,1fr)',gap:12,marginBottom:16}}>
            {['date','debit','credit','balance','desc'].map(k=>(
              <div key={k} className="input-group">
                <label>{k.toUpperCase()}{REQUIRED.includes(k)?<span style={{color:'var(--danger)'}}>*</span>:''}</label>
                <select className="input" value={colMap[k]||'(none)'} onChange={e=>setColMap(m=>({...m,[k]:e.target.value}))}>
                  {opts.map(o=><option key={o} value={o}>{o}</option>)}
                </select>
              </div>
            ))}
          </div>
          {/* Sample preview */}
          {fileData.sample?.length>0 && (
            <details style={{marginBottom:16}}>
              <summary style={{cursor:'pointer',fontSize:'.8rem',color:'var(--text-3)',fontWeight:600}}>Preview first 5 rows</summary>
              <div style={{overflowX:'auto',marginTop:8}}>
                <table className="data-table" style={{fontSize:'.75rem'}}>
                  <thead><tr>{Object.keys(fileData.sample[0]).map(k=><th key={k}>{k}</th>)}</tr></thead>
                  <tbody>{fileData.sample.map((r,i)=><tr key={i}>{Object.values(r).map((v,j)=><td key={j}>{String(v??'')}</td>)}</tr>)}</tbody>
                </table>
              </div>
            </details>
          )}
          <button className="btn btn-primary" onClick={handleRun} disabled={busy||step>3}>
            {busy?<><span className="spinner spinner-sm"/>Training 17 models…</>:<><PlayCircle size={15}/>Run Pipeline</>}
          </button>
          {busy&&<p style={{color:'var(--text-3)',fontSize:'.8rem',marginTop:8}}>This may take 1–2 minutes. Training 17 ML models including ensemble methods…</p>}
        </div>
      )}

      {/* Step 3/4: Leaderboard */}
      {step>=4 && runResult && (
        <div className="card" style={{marginBottom:16}}>
          <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}}>
            <h3>3. Model Leaderboard <span style={{fontWeight:400,color:'var(--text-3)',fontSize:'.85rem'}}>{runResult.months_span} months · {runResult.date_min} → {runResult.date_max}</span></h3>
            <button className="btn btn-outline btn-sm" onClick={()=>downloadCsv(runResult.leaderboard?.map(r=>Object.values(r).join(',')).join('\n')||'','leaderboard.csv')}>
              <Download size={13}/> CSV
            </button>
          </div>
          {runResult.leaderboard_plot_b64 && (
            <img src={`data:image/png;base64,${runResult.leaderboard_plot_b64}`} alt="Model leaderboard" style={{width:'100%',borderRadius:'var(--r-md)',marginBottom:16}}/>
          )}
          <div style={{overflowX:'auto',marginBottom:16}}>
            <table className="data-table">
              <thead><tr><th>Rank</th><th>Model</th><th>CV RMSE</th><th>MAE</th><th>R²</th></tr></thead>
              <tbody>
                {(runResult.leaderboard||[]).map((r,i)=>(
                  <tr key={i} style={i===0?{background:'var(--brand-xlight)'}:{}}>
                    <td style={{fontWeight:700}}>{i+1}</td>
                    <td style={{fontWeight:i===0?700:400}}>{r.model}{i===0?' ⭐':''}</td>
                    <td className="mono" style={{textAlign:'right',fontSize:'.78rem'}}>{Number(r.cv_rmse||0).toFixed(2)}</td>
                    <td className="mono" style={{textAlign:'right',fontSize:'.78rem'}}>{Number(r.mae||0).toFixed(2)}</td>
                    <td className="mono" style={{textAlign:'right',fontSize:'.78rem'}}>{Number(r.r2||0).toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{display:'flex',gap:12,alignItems:'flex-end'}}>
            <div className="input-group" style={{flex:1,maxWidth:320}}>
              <label>Choose model for prediction</label>
              <select className="input" value={chosen} onChange={e=>setChosen(e.target.value)}>
                {(runResult.model_names||[]).map(m=><option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <button className="btn btn-primary" onClick={handlePredict} disabled={busy||!chosen}>
              {busy?<><span className="spinner spinner-sm"/>Predicting…</>:<><TrendingUp size={15}/>Predict Next Month</>}
            </button>
          </div>
        </div>
      )}

      {/* Step 5: Forecast results */}
      {step===5 && pred && (
        <div className="card">
          <h3 style={{marginBottom:16}}>4. Next-Month Forecast</h3>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:14,marginBottom:20}}>
            {[
              {label:'Predicted Net Cash Flow', val:fmtAUD(pred.predicted_net_cashflow), color:pred.predicted_net_cashflow>=0?'var(--success)':'var(--danger)'},
              {label:'Estimated Income',         val:fmtAUD(pred.estimated_income),       color:'var(--info)'},
              {label:'Estimated Expense',        val:fmtAUD(pred.estimated_expense),      color:'var(--warning)'},
            ].map(({label,val,color})=>(
              <div key={label} className="stat-card" style={{'--stat-accent':color}}>
                <div className="stat-label">{label}</div>
                <div className="stat-value" style={{fontSize:'1.25rem',color}}>{val}</div>
              </div>
            ))}
          </div>
          {/* Trend indicator */}
          {(() => {
            const net = pred.predicted_net_cashflow
            const trend = pred.avg_last_3m_net
            if (net > trend * 1.1) return <div className="alert alert-success">📈 Above recent trend — stronger month ahead.</div>
            if (net < trend * 0.9) return <div className="alert alert-warning">📉 Below recent trend — softer month ahead.</div>
            return <div className="alert" style={{background:'var(--info-bg)',borderColor:'var(--info-border)',color:'#1e40af'}}>➡️ In line with recent trend.</div>
          })()}
          {pred.forecast_plot_b64 && (
            <img src={`data:image/png;base64,${pred.forecast_plot_b64}`} alt="Forecast" style={{width:'100%',borderRadius:'var(--r-md)',marginTop:16,marginBottom:16}}/>
          )}
          {pred.forecast_csv && (
            <button className="btn btn-outline btn-sm" onClick={()=>downloadCsv(pred.forecast_csv,'next_month_prediction.csv')}>
              <Download size={13}/> Download Forecast CSV
            </button>
          )}
        </div>
      )}
    </div>
  )
}
