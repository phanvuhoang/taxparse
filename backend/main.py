"""
taxparse — FastAPI backend
Endpoints:
  POST /parse          — upload + parse .docx → items (no DB)
  POST /parse-all      — parse all files in a folder
  POST /enrich         — AI-enrich parsed items
  GET  /taxonomy       — list default taxonomy codes
  POST /taxonomy       — save custom taxonomy
  GET  /export/csv     — download CSV
  GET  /export/jsonl   — download JSONL
  POST /batch-process  — parse + enrich all GDrive files (background)
  GET  /jobs/{job_id}  — poll background job
"""
import os
import re
import uuid
import json
import csv
import io
import time
import logging
import threading
from typing import Optional, List, Dict
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, Response as FastAPIResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.parser import parse_regulation, parse_paragraphs, items_to_csv, items_to_jsonl
from backend.enricher import enrich_items_batch, DEFAULT_TAXONOMY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="taxparse", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory store (simple, no DB needed for this tool) ─────────────────────
_sessions: Dict[str, Dict] = {}   # session_id → {items, meta}
_jobs: Dict[str, Dict] = {}       # job_id → {status, progress, result}
_custom_taxonomy: Dict[str, Dict] = {}


# ── File docs mapping ─────────────────────────────────────────────────────────
FILE_CATALOG = [
    ('CIT - Decree 320_2025_ND-CP - ENG.docx',              'Decree 320/2025/ND-CP',          'Decree320-2025',    'CIT'),
    ('CIT - Law 67_2025_QH15 - ENG.docx',                   'Law 67/2025/QH15',               'Law67-2025',        'CIT'),
    ('CIT-FCT - Circular 20_2026_TT-BTC - ENG.docx',        'Circular 20/2026/TT-BTC',        'Circular20-2026',   'CIT/FCT'),
    ('FCT - 103_2014_TT-BTC - ENG.docx',                    'Circular 103/2014/TT-BTC',       'Circular103-2014',  'FCT'),
    ('PIT - Combined Circular 02_VBHN-BTC - ENG.docx',      'VBHN 02/BTC on PIT',             'VBHN02-PIT',        'PIT'),
    ('TP - Decree 132_2020_ND-CP - ENG.docx',               'Decree 132/2020/ND-CP',          'Decree132-2020',    'TP'),
    ('TP - Decree 20_2025_ND-CP - ENG.docx',                'Decree 20/2025/ND-CP',           'Decree20-2025',     'TP'),
    ('TaxAdmin - 15_VBHN-BTC_m_620919 - ENG.docx',          'VBHN 15/BTC on Tax Admin',       'VBHN15-TaxAdmin',   'TaxAdmin'),
    ('VAT - Decree 181_2025_ND-CP - ENG.docx',              'Decree 181/2025/ND-CP',          'Decree181-2025',    'VAT'),
    ('VAT - Invoice - Combined Decree 18_VBHN-BTC - ENG.docx', 'VBHN 18/BTC on Invoices',    'VBHN18-Invoice',    'VAT'),
    ('VAT Law - 48_2024_QH15 - ENG.docx',                   'Law 48/2024/QH15',               'Law48-2024',        'VAT'),
    ('VAT-FCT - 69_2025_TT-BTC - ENG.docx',                 'Circular 69/2025/TT-BTC',        'Circular69-2025',   'VAT/FCT'),
]

DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
REGS_DIR = os.path.join(DATA_DIR, 'regulations')


# ── AI helpers ────────────────────────────────────────────────────────────────

def _get_api_config_from_env():
    """Returns (endpoint, api_key, provider)"""
    claudible_key = os.environ.get('CLAUDIBLE_API_KEY', '').strip()
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if claudible_key:
        return 'https://claudible.io/v1/chat/completions', claudible_key, 'claudible'
    elif anthropic_key:
        return 'https://api.anthropic.com/v1/messages', anthropic_key, 'anthropic'
    return None, None, None


def _call_ai_openai(prompt: str, model: str, endpoint: str, api_key: str) -> str:
    """Call Claudible (OpenAI-compatible) or Anthropic API."""
    import urllib.request as ureq
    is_claudible = 'claudible' in endpoint
    payload = json.dumps({
        'model': model, 'max_tokens': 3000,
        'messages': [{'role': 'user', 'content': prompt}]
    }).encode()
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'OpenClaw/1.0',
        **(
            {'Authorization': f'Bearer {api_key}'} if is_claudible
            else {'x-api-key': api_key, 'anthropic-version': '2023-06-01'}
        )
    }
    req = ureq.Request(endpoint, data=payload, headers=headers)
    with ureq.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
        return d['choices'][0]['message']['content'] if is_claudible else d['content'][0]['text']


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get('/health')
def health():
    return {'status': 'ok', 'sessions': len(_sessions), 'jobs': len(_jobs)}


@app.post('/parse')
async def parse_upload(
    file: UploadFile = File(...),
    doc_ref:  str = Form(...),
    doc_slug: str = Form(...),
    tax_type: str = Form(...),
):
    """Upload a .docx or .txt file and parse it into items."""
    import tempfile

    suffix = os.path.splitext(file.filename)[1].lower()
    if suffix not in ('.docx', '.txt'):
        raise HTTPException(400, f"Unsupported file type: {suffix}")

    content = await file.read()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        items = parse_regulation(tmp_path, doc_ref, doc_slug, tax_type)
    finally:
        os.unlink(tmp_path)

    session_id = str(uuid.uuid4())[:8]
    _sessions[session_id] = {
        'items': items,
        'meta': {'doc_ref': doc_ref, 'doc_slug': doc_slug, 'tax_type': tax_type, 'filename': file.filename},
    }

    levels = {}
    for item in items:
        levels[item['level']] = levels.get(item['level'], 0) + 1

    return {
        'session_id': session_id,
        'total': len(items),
        'levels': levels,
        'items': items,
    }


@app.post('/parse-catalog')
def parse_catalog(background_tasks: BackgroundTasks):
    """Parse all files from the catalog (files must be in DATA_DIR/regulations/)."""
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {'status': 'running', 'progress': 0, 'total': len(FILE_CATALOG), 'result': None, 'errors': []}

    def run():
        all_items = []
        for i, (fname, doc_ref, doc_slug, tax_type) in enumerate(FILE_CATALOG):
            fpath = os.path.join(REGS_DIR, fname)
            if not os.path.exists(fpath):
                _jobs[job_id]['errors'].append(f'Not found: {fname}')
                continue
            try:
                items = parse_regulation(fpath, doc_ref, doc_slug, tax_type)
                all_items.extend(items)
                _jobs[job_id]['progress'] = i + 1
            except Exception as e:
                _jobs[job_id]['errors'].append(f'{fname}: {e}')

        session_id = str(uuid.uuid4())[:8]
        _sessions[session_id] = {'items': all_items, 'meta': {'source': 'catalog'}}
        _jobs[job_id]['status'] = 'done'
        _jobs[job_id]['session_id'] = session_id
        _jobs[job_id]['total_items'] = len(all_items)

    background_tasks.add_task(run)
    return {'job_id': job_id, 'catalog_size': len(FILE_CATALOG)}


@app.post('/enrich')
def enrich_session(data: dict, background_tasks: BackgroundTasks):
    """
    AI-enrich a parsed session. Runs as background job — returns job_id immediately.
    Body: { session_id, model?, batch_size?, custom_taxonomy? }
    """
    session_id = data.get('session_id')
    if session_id not in _sessions:
        raise HTTPException(404, 'Session not found')

    items = list(_sessions[session_id]['items'])  # snapshot
    tax_type = data.get('tax_type') or _sessions[session_id]['meta'].get('tax_type', 'CIT')
    custom_taxonomy = data.get('custom_taxonomy') or _custom_taxonomy.get(tax_type)
    model = data.get('model', 'claude-haiku-4.5')
    batch_size = data.get('batch_size', 15)

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        'status': 'running', 'progress': 0, 'total': len(items),
        'matched': 0, 'session_id': session_id,
    }

    def run():
        from backend.enricher import DEFAULT_TAXONOMY
        endpoint, key, _ = _get_api_config_from_env()
        if not key:
            _jobs[job_id]['status'] = 'failed'
            _jobs[job_id]['error'] = 'No API key configured'
            return

        tax_codes = {}
        if custom_taxonomy:
            tax_codes = custom_taxonomy
        else:
            for tt in tax_type.split('/'):
                tax_codes.update(DEFAULT_TAXONOMY.get(tt.strip(), {}))

        taxonomy_list = '\n'.join(
            '- [' + k + '] ' + v for k, v in list(tax_codes.items())[:40]
        )
        tagged = 0

        for idx in range(0, len(items), batch_size):
            batch = items[idx:idx + batch_size]
            items_text = '\n\n'.join(
                '[' + item['reg_code'] + ']\n' + item.get('paragraph_text', '')[:400]
                for item in batch
            )
            prompt = (
                'You are a senior Vietnamese tax consultant.\n'
                'Analyze these regulation paragraphs and classify each one.\n\n'
                'TAXONOMY (' + tax_type + '):\n' + taxonomy_list + '\n\n'
                'ITEMS:\n' + items_text + '\n\n'
                'Return ONLY valid JSON (no markdown, no code blocks) like:\n'
                '{"reg_code_here": {"taxonomy_codes": ["CIT-08"], '
                '"topics": "brief topic max 80 chars", '
                '"keywords": "kw1, kw2, kw3", '
                '"importance": "high", '
                '"cross_refs": ""}}'
            )
            try:
                response = _call_ai_openai(prompt, model, endpoint, key)
                logger.info('Enrich batch %d preview: %s', idx//batch_size+1, response[:150])
                brace_start = response.find('{')
                brace_end = response.rfind('}')
                if brace_start != -1 and brace_end != -1:
                    result = json.loads(response[brace_start:brace_end+1])
                    for item in batch:
                        r = result.get(item['reg_code'], {})
                        if r:
                            item['taxonomy_codes'] = ','.join(r.get('taxonomy_codes', []))
                            item['topics'] = r.get('topics', '')
                            item['keywords'] = r.get('keywords', '')
                            item['importance'] = r.get('importance', 'medium')
                            item['cross_refs'] = r.get('cross_refs', '')
                            tagged += 1
                else:
                    logger.warning('Enrich batch %d: no JSON in response: %s', idx//batch_size+1, response[:200])
            except Exception as e:
                logger.warning('Enrich batch %d failed: %s', idx//batch_size+1, str(e))

            _jobs[job_id]['progress'] = min(idx + batch_size, len(items))
            _jobs[job_id]['matched'] = tagged
            time.sleep(0.3)

        _sessions[session_id]['items'] = items
        _jobs[job_id]['status'] = 'done'
        _jobs[job_id]['matched'] = tagged
        _jobs[job_id]['total'] = len(items)

    background_tasks.add_task(run)
    return {'job_id': job_id, 'session_id': session_id, 'total': len(items)}


@app.get('/sessions/{session_id}')
def get_session(session_id: str, limit: int = 500, offset: int = 0,
                tax_type: Optional[str] = None, level: Optional[str] = None,
                article_no: Optional[str] = None, taxonomy_code: Optional[str] = None,
                search: Optional[str] = None):
    if session_id not in _sessions:
        raise HTTPException(404, 'Session not found')
    items = _sessions[session_id]['items']

    # Filter
    if tax_type:
        items = [i for i in items if i.get('tax_type') == tax_type]
    if level:
        items = [i for i in items if i.get('level') == level]
    if article_no:
        items = [i for i in items if article_no.lower() in i.get('article_no', '').lower()]
    if taxonomy_code:
        items = [i for i in items if taxonomy_code in (i.get('taxonomy_codes') or '')]
    if search:
        s = search.lower()
        items = [i for i in items if s in i.get('paragraph_text', '').lower()
                 or s in i.get('reg_code', '').lower()
                 or s in i.get('topics', '').lower()]

    total = len(items)
    return {
        'session_id': session_id,
        'total': total,
        'offset': offset,
        'items': items[offset:offset + limit],
        'meta': _sessions[session_id]['meta'],
    }


@app.get('/taxonomy')
def get_taxonomy(tax_type: Optional[str] = None):
    if tax_type:
        return _custom_taxonomy.get(tax_type) or DEFAULT_TAXONOMY.get(tax_type, {})
    return DEFAULT_TAXONOMY


@app.post('/taxonomy')
def save_taxonomy(data: dict):
    """Save custom taxonomy for a tax type. Body: { tax_type, codes: {code: description} }"""
    tax_type = data['tax_type']
    _custom_taxonomy[tax_type] = data['codes']
    return {'saved': len(data['codes']), 'tax_type': tax_type}


@app.get('/export/csv/{session_id}')
def export_csv(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(404, 'Session not found')
    items = _sessions[session_id]['items']

    FIELDS = [
        'reg_code', 'tax_type', 'doc_ref', 'chapter',
        'article_no', 'article_title', 'clause_no', 'letter', 'level',
        'topics', 'taxonomy_codes', 'matched_codes',
        'keywords', 'importance', 'cross_refs',
        'paragraph_text', 'notes',
    ]
    output = io.StringIO()
    # UTF-8 BOM for Excel compatibility
    output.write('\ufeff')
    writer = csv.DictWriter(output, fieldnames=FIELDS, extrasaction='ignore')
    writer.writeheader()
    for item in items:
        row = dict(item)
        for col in FIELDS:
            row.setdefault(col, '')
        writer.writerow(row)

    fname = _sessions[session_id]['meta'].get('doc_slug', session_id)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{fname}_parsed.csv"'},
    )


@app.get('/export/jsonl/{session_id}')
def export_jsonl(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(404, 'Session not found')
    items = _sessions[session_id]['items']

    lines = '\n'.join(json.dumps(i, ensure_ascii=False) for i in items)
    fname = _sessions[session_id]['meta'].get('doc_slug', session_id)
    return StreamingResponse(
        iter([lines]),
        media_type='application/x-ndjson',
        headers={'Content-Disposition': f'attachment; filename="{fname}_parsed.jsonl"'},
    )


@app.get('/jobs/{job_id}')
def get_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, 'Job not found')
    return _jobs[job_id]


@app.get('/catalog')
def list_catalog():
    """List files in catalog with availability status."""
    result = []
    for fname, doc_ref, doc_slug, tax_type in FILE_CATALOG:
        fpath = os.path.join(REGS_DIR, fname)
        result.append({
            'filename': fname,
            'doc_ref': doc_ref,
            'doc_slug': doc_slug,
            'tax_type': tax_type,
            'available': os.path.exists(fpath),
        })
    return result


@app.post('/sessions/load')
async def load_session(file: UploadFile = File(...)):
    """Load a saved .taxparse.json file. Creates a new session with the saved items."""
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

    enriched = sum(1 for i in items if i.get('taxonomy_codes'))
    matched = sum(1 for i in items if i.get('matched_codes'))

    return {
        'session_id': session_id,
        'total': len(items),
        'enriched': enriched,
        'matched': matched,
        'meta': meta,
    }


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


@app.post('/match-list')
async def upload_match_list(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    code_column: str = Form(default='code'),
    desc_column: str = Form(default='description'),
):
    """
    Upload CSV or JSON match list.
    Returns preview of parsed codes.
    """
    import csv as _csv, io as _io

    content = await file.read()
    suffix = os.path.splitext(file.filename)[1].lower()

    codes = {}  # {code: description_text}

    if suffix == '.json':
        data = json.loads(content)
        if isinstance(data, list):
            for row in data:
                code = str(row.get(code_column) or row.get('code') or row.get('Code') or '').strip()
                desc_parts = []
                for col in [desc_column, 'description', 'Description', 'detailed_syllabus',
                             'Detailed Syllabus', 'topic', 'Topic']:
                    if col in row and row[col]:
                        desc_parts.append(str(row[col]).strip())
                if code:
                    codes[code] = ' — '.join(dict.fromkeys(desc_parts))[:200]
        elif isinstance(data, dict):
            codes = {str(k): str(v)[:200] for k, v in data.items()}

    elif suffix == '.csv':
        reader = _csv.DictReader(_io.StringIO(content.decode('utf-8-sig')))
        for row in reader:
            code = None
            for col in [code_column, 'code', 'Code', 'CODE', 'syllabus_code', 'SyllabusCode']:
                if col in row:
                    code = str(row[col]).strip()
                    break

            desc_parts = []
            for col in [desc_column, 'description', 'Description', 'topic', 'Topic',
                        'detailed_syllabus', 'Detailed Syllabus', 'category', 'Category']:
                if col in row and row[col] and col != (code_column or 'code'):
                    desc_parts.append(str(row[col]).strip())

            if code:
                codes[code] = ' — '.join(dict.fromkeys(filter(None, desc_parts)))[:200]

    else:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Use .csv or .json")

    if not codes:
        raise HTTPException(400, "No codes found in file. Check column names.")

    if session_id not in _sessions:
        _sessions[session_id] = {'items': [], 'meta': {}}
    _sessions[session_id]['match_list'] = codes

    return {
        "loaded": len(codes),
        "preview": dict(list(codes.items())[:5]),
        "columns_detected": list(codes.keys())[:3],
    }


@app.post('/match')
def run_match(data: dict, background_tasks: BackgroundTasks):
    """
    Match parsed items against custom list using AI.
    Body: { session_id, model?, batch_size?, force? }
    Returns job_id for polling.
    """
    session_id = data.get('session_id')
    if session_id not in _sessions:
        raise HTTPException(404, 'Session not found')

    match_list = _sessions[session_id].get('match_list')
    if not match_list:
        raise HTTPException(400, 'No match list loaded. Upload one first via /match-list')

    items = _sessions[session_id]['items']
    if not items:
        raise HTTPException(400, 'No parsed items in session')

    force = data.get('force', False)
    model = data.get('model', 'claude-haiku-4.5')
    batch_size = data.get('batch_size', 15)

    to_match = items if force else [i for i in items if not i.get('matched_codes')]

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        'status': 'running',
        'progress': 0,
        'total': len(to_match),
        'matched': 0,
        'result': None,
    }

    def run():
        endpoint, key, provider = _get_api_config_from_env()
        if not key:
            _jobs[job_id]['status'] = 'failed'
            _jobs[job_id]['error'] = 'No API key configured'
            return

        match_list_text = '\n'.join(
            f'- [{code}] {desc}' for code, desc in list(match_list.items())[:80]
        )

        matched_count = 0
        for i in range(0, len(to_match), batch_size):
            batch = to_match[i:i + batch_size]
            items_text = '\n\n'.join(
                f'[{item["reg_code"]}]\n{item.get("paragraph_text","")[:300]}'
                for item in batch
            )

            prompt = f"""Match each regulation item to the most relevant codes from the list below.

MATCH LIST:
{match_list_text}

REGULATION ITEMS:
{items_text}

Return ONLY valid JSON mapping reg_code to array of matching codes:
{{
  "CIT-Decree320-2025-Art9.1.a": ["B2a", "B2b"],
  "CIT-Decree320-2025-Art23.1": ["C1a"]
}}

Rules:
- 1-3 codes per item that are DIRECTLY relevant
- Empty array [] if genuinely no match
- Use ONLY codes that appear in the match list above
"""
            try:
                response = _call_ai_openai(prompt, model, endpoint, key)
                json_match = re.search(r'\{[\s\S]+\}', response)
                if json_match:
                    result = json.loads(json_match.group())
                    for item in batch:
                        codes = result.get(item['reg_code'], [])
                        item['matched_codes'] = ','.join(codes)
                        if codes:
                            matched_count += 1
            except Exception as e:
                logger.warning(f"Match batch {i//batch_size+1} failed: {e}")

            _jobs[job_id]['progress'] = min(i + batch_size, len(to_match))
            _jobs[job_id]['matched'] = matched_count

            if i + batch_size < len(to_match):
                time.sleep(0.3)

        _jobs[job_id]['status'] = 'done'
        _jobs[job_id]['matched'] = matched_count
        _jobs[job_id]['total'] = len(to_match)

    background_tasks.add_task(run)
    return {'job_id': job_id, 'total': len(to_match)}


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if os.path.exists(FRONTEND_DIR):
    # Mount /assets explicitly — prevents /{session_id} route from catching it
    assets_dir = os.path.join(FRONTEND_DIR, 'assets')
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# SPA fallback — handle GET + HEAD only for non-API paths
# Using Starlette middleware approach to avoid FastAPI's 405 on path match
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse as StarletteFileResponse

class SPAMiddleware(BaseHTTPMiddleware):
    """Serve index.html for all GET requests that don't match API routes or /assets."""
    API_PATHS = {
        'health', 'parse', 'enrich', 'sessions', 'taxonomy',
        'export', 'jobs', 'catalog', 'match', 'match-list',
    }
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # If the route returned 404 or 405 for a GET browser request (not API/assets)
        if (response.status_code in (404, 405)
                and request.method == 'GET'
                and not request.url.path.startswith('/assets/')
                and request.url.path.split('/')[1] not in self.API_PATHS):
            index = os.path.join(FRONTEND_DIR, 'index.html')
            if os.path.exists(index):
                return StarletteFileResponse(index)
        return response

app.add_middleware(SPAMiddleware)





