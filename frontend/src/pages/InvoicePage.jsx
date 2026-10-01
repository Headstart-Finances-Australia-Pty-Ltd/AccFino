import React, { useState } from 'react'
import { FileText } from 'lucide-react'
import InvoiceGenerator from './invoice/InvoiceGenerator.jsx'
import InvoiceExtractor from './invoice/InvoiceExtractor.jsx'

export default function InvoicePage() {
  const [tab, setTab] = useState('generator')
  return (
    <div className="fade-in">
      <div style={{marginBottom:16}}>
        <div className="flex items-center gap-1">
          <FileText size={22} />
          <h2 style={{margin:0}}>Invoice</h2>
        </div>
        <p className="text-sm text-muted" style={{margin:'4px 0 0'}}>
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
