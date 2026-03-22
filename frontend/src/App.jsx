import React, { useState, useCallback } from 'react'

const API = ''

function useApi() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const call = useCallback(async (fn) => {
    setLoading(true); setError('')
    try { return await fn() }
    catch (e) { setError(e.message); return null }
    finally { setLoading(false) }
  }, [])
  return { loading, error, call }
}

// ── Upload & Parse Panel ──────────────────────────────────────────────────────
function ParsePanel({ onParsed }) {
  const { loading, error, call } = useApi()
  const [file, setFile] = useState(null)
  const [docRef, setDocRef] = useState('')
  const [docSlug, setDocSlug] = useState('')
  const [taxType, setTaxType] = useState('CIT')

  const TAX_TYPES = ['CIT', 'VAT', 'PIT', 'FCT', 'TP', 'TaxAdmin', 'CIT/FCT', 'VAT/FCT']

  const handleFile = (e) => {
    const f = e.target.files[0]
    if (!f) return
    setFile(f)
    // Auto-suggest doc_ref and slug from filename
    const base = f.name.replace(/\s*-\s*ENG\.docx?$/i, '').replace(/\s*-\s*VIE\.docx?$/i, '').trim()
    setDocRef(base)
    setDocSlug(base.replace(/[^a-zA-Z0-9]/g, '').substring(0, 25))
  }

  const handleParse = async () => {
    if (!file) return
    const result = await call(async () => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('doc_ref', docRef)
      fd.append('doc_slug', docSlug)
      fd.append('tax_type', taxType)
      const res = await fetch(`${API}/parse`, { method: 'POST', body: fd })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Parse failed') }
      return res.json()
    })
    if (result) onParsed(result)
  }

  return (
    <div className="bg-white rounded-xl border p-5 space-y-4">
      <h2 className="font-semibold text-gray-800">📄 Upload & Parse</h2>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Regulation file (.docx or .txt)</label>
        <input type="file" accept=".docx,.txt" onChange={handleFile}
          className="text-sm text-gray-600 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-xs file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Document Reference</label>
          <input value={docRef} onChange={e => setDocRef(e.target.value)}
            placeholder="e.g. Decree 320/2025/ND-CP"
            className="w-full border rounded px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Doc Slug (URL-safe)</label>
          <input value={docSlug} onChange={e => setDocSlug(e.target.value)}
            placeholder="e.g. Decree320-2025"
            className="w-full border rounded px-3 py-1.5 text-sm" />
        </div>
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Tax Type</label>
        <select value={taxType} onChange={e => setTaxType(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm">
          {TAX_TYPES.map(t => <option key={t}>{t}</option>)}
        </select>
      </div>

      {error && <p className="text-red-500 text-xs">{error}</p>}

      <button onClick={handleParse} disabled={!file || loading}
        className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
        {loading ? 'Parsing...' : '▶ Parse Document'}
      </button>
    </div>
  )
}

// ── Results Table ─────────────────────────────────────────────────────────────
function ResultsTable({ session }) {
  const [filter, setFilter] = useState({ search: '', level: '', article: '', taxonomy: '' })
  const [page, setPage] = useState(0)
  const PER_PAGE = 50

  if (!session) return null

  let items = session.items || []

  if (filter.search) {
    const s = filter.search.toLowerCase()
    items = items.filter(i =>
      i.reg_code.toLowerCase().includes(s) ||
      i.paragraph_text.toLowerCase().includes(s) ||
      (i.topics || '').toLowerCase().includes(s)
    )
  }
  if (filter.level) items = items.filter(i => i.level === filter.level)
  if (filter.article) items = items.filter(i => i.article_no?.includes(filter.article))
  if (filter.taxonomy) items = items.filter(i => (i.taxonomy_codes || '').includes(filter.taxonomy))

  const total = items.length
  const paged = items.slice(page * PER_PAGE, (page + 1) * PER_PAGE)
  const pages = Math.ceil(total / PER_PAGE)

  const LEVEL_COLORS = { letter: 'bg-blue-50 text-blue-700', clause: 'bg-green-50 text-green-700', article: 'bg-purple-50 text-purple-700' }
  const IMP_COLORS = { high: 'text-red-600 font-semibold', medium: 'text-gray-700', low: 'text-gray-400' }

  return (
    <div className="space-y-3">
      {/* Summary */}
      <div className="flex items-center gap-4 text-sm text-gray-600">
        <span className="font-medium">{session.total} items parsed</span>
        {Object.entries(session.levels || {}).map(([k, v]) => (
          <span key={k} className={`px-2 py-0.5 rounded text-xs ${LEVEL_COLORS[k] || 'bg-gray-100'}`}>{k}: {v}</span>
        ))}
        <a href={`${API}/export/csv/${session.session_id}`}
          className="ml-auto px-3 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700">
          ⬇ Export CSV
        </a>
        <a href={`${API}/export/jsonl/${session.session_id}`}
          className="px-3 py-1 bg-gray-600 text-white text-xs rounded hover:bg-gray-700">
          ⬇ Export JSONL
        </a>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <input value={filter.search} onChange={e => { setFilter(f => ({...f, search: e.target.value})); setPage(0) }}
          placeholder="Search text / reg_code / topic..." className="border rounded px-3 py-1.5 text-sm flex-1 min-w-48" />
        <input value={filter.article} onChange={e => { setFilter(f => ({...f, article: e.target.value})); setPage(0) }}
          placeholder="Article..." className="border rounded px-3 py-1.5 text-sm w-28" />
        <select value={filter.level} onChange={e => { setFilter(f => ({...f, level: e.target.value})); setPage(0) }}
          className="border rounded px-3 py-1.5 text-sm">
          <option value="">All levels</option>
          <option value="letter">Letter</option>
          <option value="clause">Clause</option>
        </select>
        <input value={filter.taxonomy} onChange={e => { setFilter(f => ({...f, taxonomy: e.target.value})); setPage(0) }}
          placeholder="Taxonomy code..." className="border rounded px-3 py-1.5 text-sm w-36" />
        {(filter.search || filter.level || filter.article || filter.taxonomy) && (
          <button onClick={() => { setFilter({ search:'', level:'', article:'', taxonomy:'' }); setPage(0) }}
            className="text-xs text-gray-500 underline hover:text-gray-700">Clear</button>
        )}
        <span className="text-xs text-gray-400 self-center ml-auto">Showing {paged.length} of {total}</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto border rounded-lg">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2 text-left w-56">Reg Code</th>
              <th className="px-3 py-2 text-left w-20">Level</th>
              <th className="px-3 py-2 text-left w-24">Article</th>
              <th className="px-3 py-2 text-left">Paragraph Text</th>
              <th className="px-3 py-2 text-left w-32">Topics</th>
              <th className="px-3 py-2 text-left w-28">Taxonomy</th>
              <th className="px-3 py-2 text-left w-16">Imp.</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((item, idx) => (
              <tr key={item.reg_code} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                <td className="px-3 py-2 font-mono text-blue-700 whitespace-nowrap">{item.reg_code}</td>
                <td className="px-3 py-2">
                  <span className={`px-1.5 py-0.5 rounded text-xs ${LEVEL_COLORS[item.level] || ''}`}>{item.level}</span>
                </td>
                <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{item.article_no}</td>
                <td className="px-3 py-2 text-gray-700 max-w-md">
                  <div className="line-clamp-3">{item.paragraph_text}</div>
                </td>
                <td className="px-3 py-2 text-gray-600 italic">{item.topics}</td>
                <td className="px-3 py-2">
                  {(item.taxonomy_codes || '').split(',').filter(Boolean).map(c => (
                    <span key={c} className="inline-block bg-amber-100 text-amber-800 text-xs px-1 rounded mr-1 mb-0.5">{c}</span>
                  ))}
                </td>
                <td className={`px-3 py-2 text-xs ${IMP_COLORS[item.importance] || ''}`}>{item.importance}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center gap-2 justify-center text-sm">
          <button onClick={() => setPage(p => Math.max(0, p-1))} disabled={page === 0}
            className="px-3 py-1 border rounded disabled:opacity-40">← Prev</button>
          <span className="text-gray-500">Page {page+1} / {pages}</span>
          <button onClick={() => setPage(p => Math.min(pages-1, p+1))} disabled={page === pages-1}
            className="px-3 py-1 border rounded disabled:opacity-40">Next →</button>
        </div>
      )}
    </div>
  )
}

// ── Enrich Panel ──────────────────────────────────────────────────────────────
function EnrichPanel({ sessionId, onEnriched }) {
  const { loading, error, call } = useApi()
  const [model, setModel] = useState('claude-haiku-4-5')

  const handleEnrich = async () => {
    const result = await call(async () => {
      const res = await fetch(`${API}/enrich`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, model }),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Enrich failed') }
      return res.json()
    })
    if (result) onEnriched()
  }

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center gap-4">
      <div>
        <p className="text-sm font-medium text-amber-800">🏷 AI Taxonomy Enrichment</p>
        <p className="text-xs text-amber-600">Classify items into topics & taxonomy codes using AI</p>
      </div>
      <select value={model} onChange={e => setModel(e.target.value)}
        className="border rounded px-2 py-1 text-sm ml-auto">
        <option value="claude-haiku-4-5">Haiku (fast/cheap)</option>
        <option value="claude-sonnet-4-5">Sonnet (better quality)</option>
      </select>
      {error && <p className="text-red-500 text-xs">{error}</p>}
      <button onClick={handleEnrich} disabled={loading}
        className="px-4 py-2 bg-amber-600 text-white text-sm rounded hover:bg-amber-700 disabled:opacity-50 whitespace-nowrap">
        {loading ? 'Enriching...' : '▶ Run AI Enrich'}
      </button>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [session, setSession] = useState(null)

  const handleParsed = (result) => {
    setSession(result)
  }

  const handleEnriched = async () => {
    if (!session) return
    // Re-fetch session to get enriched items
    try {
      const res = await fetch(`${API}/sessions/${session.session_id}?limit=5000`)
      const data = await res.json()
      setSession(s => ({ ...s, items: data.items, total: data.total }))
    } catch {}
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-6 py-4">
        <h1 className="text-xl font-bold text-gray-900">
          ⚖️ <span className="text-blue-600">taxparse</span>
          <span className="text-gray-400 font-normal text-sm ml-3">VN Tax Regulation Parser & Classifier</span>
        </h1>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-5">
        <ParsePanel onParsed={handleParsed} />

        {session && (
          <>
            <EnrichPanel sessionId={session.session_id} onEnriched={handleEnriched} />
            <ResultsTable session={session} />
          </>
        )}

        {!session && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-4xl mb-3">📋</p>
            <p>Upload a .docx regulation file to get started</p>
            <p className="text-sm mt-1">Supports: CIT · VAT · PIT · FCT · TP · TaxAdmin</p>
          </div>
        )}
      </main>
    </div>
  )
}
