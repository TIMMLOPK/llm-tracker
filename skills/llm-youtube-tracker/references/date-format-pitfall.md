## Date Formatting Pitfall

yt-dlp returns `published` dates in `YYYYMMDD` format (e.g., `'20260504'`), NOT ISO 8601. JavaScript's `new Date('20260504')` returns **"Invalid Date"**.

### Fix — fmtDate function

```javascript
function fmtDate(iso) {
  if (!iso) return '—';
  // Handle YYYYMMDD format from yt-dlp
  if (/^\d{8}$/.test(iso)) {
    const y = iso.slice(0,4), m = iso.slice(4,6), d = iso.slice(6,8);
    return new Date(`${y}-${m}-${d}`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }
  try { return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
  catch { return iso.slice(0, 10); }
}
```

### Where it breaks

- Video card dates: `.video-card-date` in `renderGrid()`
- Table date cells: `.date-cell` in `renderTable()`
- Date sorting: `case 'date'` in sort comparator (string YYYYMMDD sorts correctly, no fix needed)

### Note

The `last_update` field in `data.json` IS ISO format (`2026-05-04T10:04:42.757059+00:00`) — that one works fine with `new Date()`.
