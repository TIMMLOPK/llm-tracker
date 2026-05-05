# Dashboard HTML Update Patterns

When LLM-enriched data is added to `data.json`, the dashboard HTML (`index.html`) must be updated to use the new fields. The default HTML uses `v.topics` and `v.claims` which are the old keyword-based fields.

## Field Mapping

| Old Field | New Field | Description |
|---|---|---|
| `v.topics` | `v.specific_topics` | Precise LLM-identified topics (3-6 per video) |
| `v.claims` | `v.key_insights` | Specific claims/findings from the creator |
| (none) | `v.summary` | 2-3 sentence video summary |
| (none) | `v.creator_stance` | Creator's perspective/opinion |
| (none) | `v.technical_level` | beginner / intermediate / advanced |
| (none) | `v.notable_quotes` | Direct quotes from transcript |
| (none) | `v.analysis_quality` | 'llm_enriched' when processed |

## JavaScript Fallback Pattern

Every field access should fall back to the old field if enriched data is missing:

```javascript
// Topics fallback
(v.specific_topics && v.specific_topics.length ? v.specific_topics : (v.topics || [])).slice(0, 4)

// Claims/insights fallback
(v.key_insights && v.key_insights.length) ? v.key_insights : (v.claims || [])
```

## Video Card Update (renderGrid function)

The video card should show in order:
1. **Channel name + date**
2. **Title** (clickable to open YouTube modal)
3. **Topic pills** (use specific_topics with fallback)
4. **Summary** (if available, skip if it says "No transcript available")
5. **Key insights** (with fallback to claims, then creator_stance)
6. **Notable quote** (if available, styled with left border)
7. **Footer**: transcript badge + "📄 Transcript" button + "Watch" button

### Transcript Button
```javascript
${v.transcript_text ? `<span class="play-button" onclick="openTranscript('${v.id}')" title="Read transcript">📄 Transcript</span>` : ''}
```

## Transcript Viewer Modal

Add a second modal for viewing full transcripts:

```html
<!-- Transcript Viewer Modal -->
<div class="modal-overlay" id="transcript-modal">
  <div class="modal-content" style="max-width:800px;max-height:85vh;display:flex;flex-direction:column">
    <button class="modal-close" onclick="closeTranscript()">&times;</button>
    <div style="padding:24px;overflow-y:auto;flex:1" id="transcript-body">
      <!-- transcript content here -->
    </div>
  </div>
</div>
```

### openTranscript Function
```javascript
function openTranscript(videoId) {
  const v = DATA.videos.find(x => x.id === videoId);
  if (!v || !v.transcript_text) return;
  const body = document.getElementById('transcript-body');
  const topics = (v.specific_topics && v.specific_topics.length ? v.specific_topics : v.topics || []);
  body.innerHTML = `
    <div style="margin-bottom:20px">
      <div style="font-size:11px;color:var(--text-secondary);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">${esc(v.channel_name)}</div>
      <h2 style="font-size:20px;font-weight:700;line-height:1.3;margin-bottom:8px">${esc(v.title)}</h2>
      ${v.summary ? `<p style="font-size:14px;color:var(--text-dark);line-height:1.6;margin-bottom:12px">${esc(v.summary)}</p>` : ''}
      ${v.creator_stance ? `<p style="font-size:13px;color:var(--text-secondary);font-style:italic;margin-bottom:12px;border-left:3px solid var(--primary-blue);padding-left:12px">${esc(v.creator_stance)}</p>` : ''}
      <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px">${topics.map(t => '<span class="topic-pill">' + t + '</span>').join('')}</div>
      ${v.technical_level ? '<span class="badge" style="background:var(--tag-blue-bg);color:var(--primary-blue);font-size:11px">' + v.technical_level + '</span>' : ''}
    </div>
    <div style="border-top:1px solid var(--border-light);padding-top:16px">
      <div style="font-size:11px;color:var(--text-secondary);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">Full Transcript</div>
      <div style="font-size:14px;line-height:1.8;color:var(--text-dark);white-space:pre-wrap">${esc(v.transcript_text)}</div>
    </div>
  `;
  document.getElementById('transcript-modal').classList.add('active');
  document.body.style.overflow = 'hidden';
}
```

## Stats Bar Update

Show enriched count instead of just transcript count:
```javascript
const enriched = DATA.videos.filter(v => v.analysis_quality === 'llm_enriched').length;
// Label: "LLM Analyzed" instead of "Transcribed"
```

## Topic Bars / Channel Cards / Filters

All places that iterate `v.topics` must use the fallback pattern:
```javascript
(v.specific_topics && v.specific_topics.length ? v.specific_topics : v.topics || [])
```

## Search Enhancement

Add `v.summary` to the search filter:
```javascript
if (q) vids = vids.filter(v =>
  v.title.toLowerCase().includes(q) ||
  (v.specific_topics || v.topics || []).some(t => t.toLowerCase().includes(q)) ||
  (v.key_insights || v.claims || []).some(c => c.toLowerCase().includes(q)) ||
  (v.summary || '').toLowerCase().includes(q) ||
  v.channel_name.toLowerCase().includes(q)
);
```
