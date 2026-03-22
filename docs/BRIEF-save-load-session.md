# BRIEF: Save / Load Session (Resume Enriching)
## Repo: phanvuhoang/taxparse

---

## Goal

Allow user to save current session (parsed items + enrichment progress) to a file,
and reload it later to continue enriching or download results.

**Use case:** User parses 490 items, enriches 200, closes browser.
Next day: load saved file → continue enriching from item 201.

---

## Save Format

Save as `.taxparse.json` file (downloaded to user's computer):

```json
{
  "version": 1,
  "saved_at": "2026-03-22T18:00:00Z",
  "meta": {
    "doc_slug": "CIT_Law67_2014",
    "tax_type": "CIT",
    "source": "upload",
    "total": 490
  },
  "items": [
    {
      "reg_code": "CIT-Law67-2014-Art9.1.a",
      "tax_type": "CIT",
      "doc_ref": "Law 67/2014/QH13",
      "article_no": "Article 9",
      "paragraph_text": "...",
      "taxonomy_codes": "CIT-08,CIT-09",
      "topics": "Deductible expenses — general",
      "keywords": "deductible, conditions",
      "importance": "high",
      "cross_refs": "",
      "matched_codes": "",
      "notes": ""
    }
  ]
}
```

---

## Backend Changes

### New endpoint: `POST /sessions/load`

Load a saved `.taxparse.json` file and create a new in-memory session.

```python
@app.post('/sessions/load')
async def load_session(file: UploadFile = File(...)):
    """
    Load a saved .taxparse.json file.
    Creates a new session with the saved items.
    Returns session_id + stats.
    """
    content = await file.read()
    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(400, 'Invalid JSON file')

    if data.get('version') != 1 or 'items' not in data:
        raise HTTPException(400, 'Invalid .taxparse.json format')

    items = data['items']
    meta = data.get('meta', {})

    session_id = str(uuid.uuid4())[:8]
    _sessions[session_id] = {
        'items': items,
        'meta': {
            **meta,
            'loaded_from_file': file.filename,
            'loaded_at': time.time(),
        }
    }

    # Stats
    enriched = sum(1 for i in items if i.get('taxonomy_codes'))
    matched = sum(1 for i in items if i.get('matched_codes'))

    return {
        'session_id': session_id,
        'total': len(items),
        'enriched': enriched,
        'matched': matched,
        'meta': meta,
    }
```

### New endpoint: `GET /sessions/{session_id}/save`

Return session as downloadable `.taxparse.json` file.

```python
from fastapi.responses import Response as FastAPIResponse
import time as _time_mod

@app.get('/sessions/{session_id}/save')
def save_session(session_id: str):
    """Download current session as .taxparse.json"""
    if session_id not in _sessions:
        raise HTTPException(404, 'Session not found')

    sess = _sessions[session_id]
    items = sess['items']
    meta = sess.get('meta', {})

    output = {
        'version': 1,
        'saved_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
        'meta': {
            'doc_slug': meta.get('doc_slug', meta.get('source', 'session')),
            'tax_type': meta.get('tax_type', 'CIT'),
            'source': meta.get('source', 'upload'),
            'total': len(items),
        },
        'items': items,
    }

    filename = f"{meta.get('doc_slug', session_id)}_taxparse.json"
    return FastAPIResponse(
        content=json.dumps(output, ensure_ascii=False, indent=2),
        media_type='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
```

---

## Frontend Changes

### 1. Add Save/Load buttons to toolbar

Add a "Session" section in the top toolbar (between the file upload and enrich panel):

```jsx
function SessionToolbar({ session, onLoad }) {
  const [loadError, setLoadError] = useState(null)

  const handleSave = () => {
    if (!session) return
    // Download via backend endpoint (preserves server-side enrichment)
    window.location.href = `${API}/sessions/${session.session_id}/save`
  }

  const handleLoad = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setLoadError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`${API}/sessions/load`, { method: 'POST', body: fd })
      const d = await res.json()
      if (!res.ok) { setLoadError(d.detail || 'Load failed'); return }
      onLoad(d)   // d = { session_id, total, enriched, matched, meta }
    } catch (e) {
      setLoadError(e.message)
    }
    e.target.value = ''   // reset input
  }

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {session && (
        <button onClick={handleSave}
          className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs rounded border border-gray-300 flex items-center gap-1.5">
          💾 Save session
        </button>
      )}
      <label className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs rounded border border-gray-300 cursor-pointer flex items-center gap-1.5">
        📂 Load session
        <input type="file" accept=".json" onChange={handleLoad} className="hidden" />
      </label>
      {loadError && <span className="text-xs text-red-500">{loadError}</span>}
    </div>
  )
}
```

### 2. Handle `onLoad` in App

When a session is loaded from file, fetch its items and set as current session:

```js
const handleSessionLoad = async (loadResult) => {
  // loadResult = { session_id, total, enriched, matched, meta }
  // Fetch full items
  try {
    const res = await fetch(`${API}/sessions/${loadResult.session_id}?limit=5000`)
    const data = await res.json()
    setSession({
      session_id: loadResult.session_id,
      items: data.items,
      total: loadResult.total,
      meta: loadResult.meta,
      _loaded_from_file: true,
      _enriched: loadResult.enriched,
      _matched: loadResult.matched,
    })
    setRestoredFromCache(false)   // don't show localStorage restore banner
  } catch (e) {
    console.error('Failed to load session items:', e)
  }
}
```

### 3. Show enrichment progress in session status

Above the results table, show a small status bar:

```jsx
{session && (
  <div className="flex items-center gap-4 text-xs text-gray-500 px-1">
    <span>📄 {session.total} items</span>
    {(() => {
      const enrichedCount = session.items?.filter(i => i.taxonomy_codes).length || 0
      const matchedCount = session.items?.filter(i => i.matched_codes).length || 0
      return (
        <>
          <span className={enrichedCount > 0 ? 'text-amber-700' : ''}>
            🏷 {enrichedCount}/{session.total} enriched
          </span>
          {matchedCount > 0 && (
            <span className="text-purple-700">🔗 {matchedCount}/{session.total} matched</span>
          )}
          {enrichedCount < session.total && enrichedCount > 0 && (
            <span className="text-blue-600 font-medium">
              ▸ {session.total - enrichedCount} items still need enrichment
            </span>
          )}
        </>
      )
    })()}
  </div>
)}
```

### 4. Add `SessionToolbar` to App render

```jsx
{/* Between file upload section and EnrichPanel */}
<SessionToolbar session={session} onLoad={handleSessionLoad} />
```

### 5. Also auto-save to localStorage on every session change (already done — keep it)

The existing localStorage auto-save works. This feature adds the **explicit file save/load** for cross-browser / cross-device use and as a permanent archive.

---

## SUMMARY — Files to Create/Modify

| Action | File | Change |
|--------|------|--------|
| MODIFY | `backend/main.py` | Add `POST /sessions/load` + `GET /sessions/{id}/save` endpoints |
| MODIFY | `frontend/src/App.jsx` | Add `SessionToolbar` component; add `handleSessionLoad`; add status bar showing enriched/matched counts |

---

## NOTES FOR CLAUDE CODE

1. `POST /sessions/load` uses `UploadFile` (multipart form), same as `/match-list`
2. `GET /sessions/{id}/save` returns JSON as file download with `Content-Disposition: attachment`
3. `SessionToolbar` Save button uses `window.location.href` to trigger download — simple, no fetch needed
4. Load button is a hidden file input wrapped in a `<label>` — no extra button
5. Status bar counts are computed from `session.items` client-side — no extra API call
6. Keep existing localStorage auto-save — it's complementary
7. Add `import time` at top of main.py if not already there
8. After done: commit + push
