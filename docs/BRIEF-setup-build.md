# BRIEF: taxparse — Complete the App (Frontend build + Backend static serve + Coolify deploy)
## Repo: phanvuhoang/taxparse

---

## Context

`taxparse` is a standalone VN tax regulation parser app.
- Backend: FastAPI (Python) — `backend/` — already complete
- Frontend: React + Vite + Tailwind — `frontend/` — already has App.jsx, needs build setup
- Goal: Deploy on Coolify at `taxparse.gpt4vn.com`

---

## Task 1: Fix Dockerfile to build frontend first, then serve via FastAPI

Current `Dockerfile` builds backend only. Update to:

```dockerfile
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y antiword && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Task 2: Serve frontend static files from FastAPI

In `backend/main.py`, after all routes are defined, add at the BOTTOM of the file:

```python
from fastapi.staticfiles import StaticFiles

# Serve frontend — must be LAST (catch-all)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
```

Also add to requirements.txt:
```
aiofiles==23.2.1
```
(already there — just confirm it's present)

---

## Task 3: Remove bad content from backend/__init__.py

Current `backend/__init__.py` has Python code that shouldn't be there. Replace with empty file:

```python
# taxparse backend
```

---

## Task 4: Add .gitignore

Create `.gitignore`:
```
__pycache__/
*.pyc
*.pyo
node_modules/
frontend/dist/
.env
*.env
data/
```

---

## Task 5: Add frontend/src/index.css with proper Tailwind directives

Current file is fine — just verify it has:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

---

## Task 6: Fix package-lock.json

Run `npm install` inside `frontend/` to generate `package-lock.json` (needed for Docker build cache).

Steps:
1. `cd frontend && npm install`
2. Commit `package-lock.json` to repo

---

## SUMMARY

Files to create/modify:
| Action | File |
|--------|------|
| MODIFY | `Dockerfile` — multi-stage build (Node → Python) |
| MODIFY | `backend/main.py` — add StaticFiles mount at bottom |
| MODIFY | `backend/__init__.py` — replace with clean `# taxparse backend` |
| CREATE | `.gitignore` |
| CREATE | `frontend/package-lock.json` (via npm install) |

---

## NOTES FOR CLAUDE CODE

1. **Do NOT modify** `backend/parser.py`, `backend/enricher.py`, or `frontend/src/App.jsx` — these are complete
2. The backend API uses in-memory sessions (no DB needed for this tool)
3. After tasks are done: commit everything and push
4. The app will be deployed on Coolify — no env vars needed except optional `ANTHROPIC_API_KEY` for AI enrichment
5. `antiword` in Dockerfile is needed for .doc (old format) support — keep it
