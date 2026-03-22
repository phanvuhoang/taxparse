# BRIEF: Fix 5 bugs in taxparse
## Repo: phanvuhoang/taxparse

---

## Bug 1: POST /match-list returns 405 (Method Not Allowed)

### Root Cause
`SPAMiddleware` intercepts the response from `POST /match-list` after `call_next`.
When `/match-list` is called with missing form fields, FastAPI returns 422 — OK.
But when called correctly, `StaticFiles("/assets")` is somehow interfering.

The real fix: **remove `SPAMiddleware` entirely** and revert to a clean architecture:
- Mount `/assets` explicitly (already done — keeps JS working)
- Add a proper `GET /` catch-all **using `add_api_route`** with `methods=["GET"]` only

### Fix in `backend/main.py`

Replace the entire bottom section (from `from fastapi.staticfiles import StaticFiles` to end of file) with:

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')

# 1. Mount /assets first — prevents /{session_id} route from catching it
if os.path.exists(FRONTEND_DIR):
    assets_dir = os.path.join(FRONTEND_DIR, 'assets')
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# 2. SPA index.html — explicit GET routes only (does NOT interfere with POST/PUT/DELETE)
_index_html = os.path.join(FRONTEND_DIR, 'index.html')

@app.get("/", include_in_schema=False)
async def spa_root():
    return FileResponse(_index_html)

# Do NOT add a catch-all /{path} route — it causes 405 on POST routes with same path name.
# The frontend is a SPA that only needs / — deep links are not used in this app.
```

**Remove `SPAMiddleware` class and `app.add_middleware(SPAMiddleware)` completely.**

---

## Bug 2: Page requires multiple refreshes before loading

### Root Cause
On first load, `useEffect` restores session from `localStorage`. But `session.session_id`
no longer exists in the backend (in-memory — reset on deploy). When user clicks
Enrich/Match/Export, the backend returns 404. The app silently fails and shows nothing.

Also: the `API` constant might resolve to wrong URL on first render if `window.location`
isn't stable yet.

### Fix in `frontend/src/App.jsx`

**Fix A: Validate restored session against backend on mount**

Replace the auto-restore `useEffect` (around line 646):

```javascript
// Auto-restore session on mount — validate against backend first
useEffect(() => {
  try {
    const saved = localStorage.getItem('taxparse_session')
    const savedAtVal = localStorage.getItem('taxparse_session_saved_at')
    if (!saved) return
    const parsed = JSON.parse(saved)
    if (!parsed?.items?.length) return

    // Try to validate session still exists in backend
    fetch(`${API}/sessions/${parsed.session_id}?limit=1`)
      .then(r => {
        if (r.ok) {
          // Backend session still alive — restore normally
          setSession(parsed)
          setSavedAt(savedAtVal)
          setRestoredFromCache(true)
        } else {
          // Backend session gone (redeployed) — restore from localStorage only
          // Mark as local-only so Export uses client-side fallback
          setSession({ ...parsed, _local_only: true })
          setSavedAt(savedAtVal)
          setRestoredFromCache(true)
        }
      })
      .catch(() => {
        // Network error — still restore from localStorage
        setSession({ ...parsed, _local_only: true })
        setSavedAt(savedAtVal)
        setRestoredFromCache(true)
      })
  } catch {}
}, [])
```

**Fix B: Harden `API` constant**

Replace:
```javascript
const API = window.location.origin === 'http://localhost:5173'
  ? 'http://localhost:8000'
  : window.location.origin
```

With:
```javascript
const getAPI = () => {
  try {
    return window.location.origin === 'http://localhost:5173'
      ? 'http://localhost:8000'
      : window.location.origin
  } catch { return '' }
}
const API = getAPI()
```

---

## Bug 3: Paragraph text truncated in view/edit modal and in CSV export

### Root Cause A — `backend/parser.py` line 124: `'paragraph_text': text[:2000]`
Truncates at 2000 chars. Vietnamese regulations have sub-clauses that can be 3000–5000 chars.

### Root Cause B — `backend/main.py` line 230: `item.get('paragraph_text', '')[:400]`
Only sends first 400 chars to AI for enrichment prompt. This is intentional for token economy — **do not change this** (AI context, not storage).

### Root Cause C — Frontend `line-clamp-3` in table row (line 321)
Table shows max 3 lines. This is fine for the table. The modal (line 124) has `max-h-64` which limits visible height but text is scrollable — also fine.

### Fix: Remove the 2000-char truncation in `backend/parser.py`

```python
# Change line 124:
'paragraph_text': text[:2000],
# To:
'paragraph_text': text,   # no truncation — full text preserved
```

Also remove the `intro[:200]` truncation on line 135:
```python
# Change:
full_text = (intro[:200] + '\n' + text) if intro and intro not in text else text
# To:
full_text = (intro + '\n' + text) if intro and intro not in text else text
```

### Fix: Make modal paragraph text box taller

```jsx
// Change line 124 (modal paragraph text div):
// From:
<div className="bg-gray-50 border rounded-lg p-3 text-sm text-gray-800 whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto">
// To:
<div className="bg-gray-50 border rounded-lg p-3 text-sm text-gray-800 whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto">
```

(`max-h-64` = 16rem → `max-h-96` = 24rem — taller but still scrollable)

---

## Bug 4: Export JSONL returns "Session not found"

### Root Cause
Export JSONL uses an `<a href={...}>` link which does a browser GET navigation.
If the backend session has been reset (deploy), it returns 404. Also the export endpoints
at `GET /export/csv/{session_id}` and `GET /export/jsonl/{session_id}` contain the word
`export` which is in `SPAMiddleware.API_PATHS` (if middleware still exists) — causing issues.

More importantly: when session is `_local_only` (restored from localStorage but not in backend),
the export must fall back to client-side generation.

### Fix A: Export JSONL — same client-side fallback as CSV

Replace the `<a href>` Export JSONL link with a button that generates JSONL client-side
(same pattern as `handleExportCSV` which already has a client-side fallback):

```javascript
const handleExportJSONL = async () => {
  // Try backend first
  try {
    const res = await fetch(`${API}/export/jsonl/${session.session_id}`)
    if (res.ok) {
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url
      a.download = `${session.meta?.doc_slug || 'taxparse'}_parsed.jsonl`
      a.click(); URL.revokeObjectURL(url)
      return
    }
  } catch {}

  // Fallback: client-side JSONL from session items in localStorage
  const lines = session.items.map(i => JSON.stringify(i)).join('\n')
  const blob = new Blob([lines], { type: 'application/x-ndjson' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url
  a.download = `${session.meta?.doc_slug || 'taxparse'}_parsed.jsonl`
  a.click(); URL.revokeObjectURL(url)
}
```

Replace the `<a href>` with a `<button onClick={handleExportJSONL}>`:
```jsx
// Replace:
<a href={`${API}/export/jsonl/${session.session_id}`}
  className="px-3 py-1 bg-gray-600 text-white text-xs rounded hover:bg-gray-700">
  ⬇ Export JSONL
</a>
// With:
<button onClick={handleExportJSONL}
  className="px-3 py-1 bg-gray-600 text-white text-xs rounded hover:bg-gray-700">
  ⬇ Export JSONL
</button>
```

### Fix B: handleExportCSV — also use client-side fallback when `_local_only`

The CSV export already has a client-side fallback — but it only triggers when `res.ok` fails.
Ensure the fallback includes ALL fields including enriched ones from localStorage:

No change needed — the existing fallback at lines 239–254 already reads from `session.items`
which includes enrichment data saved to localStorage. ✅

---

## Bug 5: "Refresh table to see results" — but no refresh button

### Root Cause
After enrich completes, `onEnriched(null)` is called which fetches from backend:
```javascript
fetch(`${API}/sessions/${session.session_id}?limit=5000`)
```
If this fails (network error or session gone), the table doesn't update.
The toast says "Refresh table to see results" but there's no refresh button.

### Fix A: Add a "🔄 Refresh Table" button next to Export buttons

```jsx
{/* Add next to Export CSV button */}
<button
  onClick={() => {
    fetch(`${API}/sessions/${session.session_id}?limit=5000`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.items) setSession(s => ({ ...s, items: data.items, total: data.total }))
      })
      .catch(() => {})
  }}
  className="px-3 py-1 bg-blue-500 text-white text-xs rounded hover:bg-blue-600"
  title="Re-fetch enrichment results from backend"
>
  🔄 Refresh
</button>
```

### Fix B: After enrich done — update table from localStorage (not just backend)

When enrich completes (`status === 'done'`), the enriched items are in the backend session.
`onEnriched()` re-fetches from backend. But if backend is gone, show items from the job result.

In `EnrichPanel`, after `onEnriched(null)` is called, also update the job status to 'done'
with a clear message:

```jsx
// Change jobStatus 'done' display:
{jobStatus.status === 'done' && (
  <span className="text-green-700 font-medium">
    ✓ Done — tagged {jobStatus.matched}/{jobStatus.total} items.
    {' '}<button
      className="underline text-blue-600 hover:text-blue-800"
      onClick={() => onEnriched(null)}
    >
      Refresh table ↻
    </button>
  </span>
)}
```

---

## SUMMARY — Files to Create/Modify

| Action | File | Change |
|--------|------|--------|
| MODIFY | `backend/main.py` | Remove SPAMiddleware; replace with `@app.get("/")` only; keep `/assets` mount |
| MODIFY | `backend/parser.py` | Remove `[:2000]` truncation on paragraph_text; remove `intro[:200]` truncation |
| MODIFY | `frontend/src/App.jsx` | Validate session against backend on restore; harden `API` const; Export JSONL → client-side fallback button; add Refresh button; clickable "Refresh table" link in enrich done message; increase modal max-h-64 → max-h-96 |

---

## NOTES FOR CLAUDE CODE

1. **Bug 1 is the highest priority** — remove SPAMiddleware completely, use `@app.get("/")` only
2. **Do NOT add `/{full_path:path}` catch-all** — it causes 405 on POST routes with same path
3. **`_local_only` flag** — when session is restored from localStorage but not in backend, export falls back to client-side; enrich/match will fail with "session not found" — that's expected (user needs to re-parse)
4. **Parser truncation**: only remove the `[:2000]` in `parser.py` line 124 and `intro[:200]` line 135 — do not change `[:400]` in `main.py` line 230 (AI prompt context, not storage)
5. **Modal max-h**: increase from `max-h-64` to `max-h-96` — still scrollable, just shows more
6. **Export JSONL**: convert from `<a href>` to `<button onClick={handleExportJSONL}>` — client-side generation as fallback
7. **Refresh button**: place it in `ResultsTable` component header, next to Export CSV/JSONL buttons
8. After done: commit + push
