import React, { useState } from 'react'
import InvoiceGenerator from './invoice/InvoiceGenerator.jsx'
import InvoiceExtractor from './invoice/InvoiceExtractor.jsx'

export default function InvoicePage() {
  const [tab, setTab] = useState('generator')
  return (
    <div className="fade-in">
      <div style={{marginBottom:18}}>
        <h1>📄 Invoice</h1>
        <p style={{color:'var(--text-3)',marginTop:4,fontSize:'.9rem'}}>
          Create GST-compliant invoices and extract structured data from PDF documents
        </p>
      </div>
      <div className="tabs-bar" style={{marginBottom:0}}>
        <button className={`tab-btn${tab==='generator'?' active':''}`} onClick={()=>setTab('generator')}>📝 Invoice Generator</button>
        <button className={`tab-btn${tab==='extractor'?' active':''}`} onClick={()=>setTab('extractor')}>🔍 Invoice Extractor</button>
      </div>
      <div style={{background:'var(--surface)',border:'1px solid var(--border)',borderTop:'none',borderRadius:'0 0 var(--r-lg) var(--r-lg)',padding:'24px',boxShadow:'var(--sh-sm)'}}>
        {tab==='generator' && <InvoiceGenerator/>}
        {tab==='extractor' && <InvoiceExtractor/>}
      </div>
    </div>
  )
}
