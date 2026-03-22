# BRIEF: Add Favicon to taxparse
## Repo: phanvuhoang/taxparse

---

## Goal
Add a favicon to the taxparse app so the browser tab shows a proper icon instead of the default blank/browser icon.

---

## Design

Use an emoji-based SVG favicon — no image file needed, works in all modern browsers.

Icon concept: **📋** (clipboard/document) — fits "regulation parser" theme.
Color: blue-gray palette matching the app UI (`#3b82f6` blue, `#1e293b` dark).

---

## Implementation

### 1. Create `frontend/public/favicon.svg`

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <!-- Background circle -->
  <rect width="32" height="32" rx="8" fill="#1e40af"/>
  <!-- Document body -->
  <rect x="8" y="6" width="16" height="20" rx="2" fill="white" opacity="0.95"/>
  <!-- Clip/header bar -->
  <rect x="11" y="4" width="10" height="5" rx="2" fill="#93c5fd"/>
  <!-- Lines representing text -->
  <rect x="11" y="13" width="10" height="1.5" rx="0.75" fill="#3b82f6"/>
  <rect x="11" y="17" width="8" height="1.5" rx="0.75" fill="#3b82f6"/>
  <rect x="11" y="21" width="6" height="1.5" rx="0.75" fill="#bfdbfe"/>
</svg>
```

Save as `frontend/public/favicon.svg`.

### 2. Update `frontend/index.html`

Replace the existing `<title>` line area with favicon + updated title:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TaxParse — VN Tax Regulation Parser</title>
</head>
<body>
  <div id="root"></div>
</body>
</html>
```

(Just add the `<link rel="icon" ...>` line — keep everything else as-is.)

---

## NOTES FOR CLAUDE CODE

1. The SVG favicon works in Chrome, Firefox, Edge, Safari 15+ — no PNG needed
2. `frontend/public/` files are copied to `frontend/dist/` by Vite automatically — no config change needed
3. The existing `index.html` is at `frontend/index.html` (Vite root, NOT `frontend/public/`)
4. After done: commit + push
