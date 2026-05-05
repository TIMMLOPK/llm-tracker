---
name: llm-youtube-tracker
description: Self-updating LLM YouTube Tracker — discover videos, transcribe, analyze with LLM, update dashboard.
triggers:
  - "youtube tracker"
  - "llm tracker"
  - "update tracker"
  - "new videos"
  - "analyze transcripts"
  - "tracker pipeline"
---

# LLM YouTube Tracker

Self-updating dashboard monitoring 12 popular LLM YouTube channels at `~/llm-tracker/`.

**Dashboard:** https://track.ionce.me/ (Caddy auto-HTTPS → localhost:8080)

## Architecture

```
yt-dlp (discover + subtitles) → Cloudflare Whisper (fallback) → Hermes LLM (analyze) → data.json → Dashboard
```

## Reference Files

- `references/cloudflare-whisper-api.md` — API endpoint, input/output schema, tested limits, cost, chunking strategy
- `references/llm-analysis-workflow.md` — Batch processing pattern for transcript analysis, quality guidelines, connection building
- `references/batch-enrichment-pattern.md` — Step-by-step pattern for reading excerpts, generating enrichments, writing back to data.json, rebuilding connections
- `references/dashboard-html-patterns.md` — Full update pattern for enriched fields, transcript viewer, search
- `references/caddy-https-setup.md` — Caddy install, config, pitfalls for ARM64 EC2
- `references/date-format-pitfall.md` — yt-dlp YYYYMMDD date parsing fix (Invalid Date bug)
- `references/d3-force-graph-integration.md` — Embedding D3 force-directed graphs in existing dashboards (variable ordering, data hooks, highlighting)
- `references/d3-cloud-word-cloud.md` — d3-cloud word cloud pattern for topic visualization (CDN, scale functions, async layout)

## Key Files

| File | Purpose |
|---|---|
| `~/llm-tracker/fetch_and_analyze.py` | Main pipeline: discover, transcribe, save raw data |
| `~/llm-tracker/data.json` | All video data + analysis + timestamped transcript segments (served to dashboard, ~16MB) |
| `~/llm-tracker/channels.json` | 12 channel configs (name, channel_id, url) |
| `~/llm-tracker/cookies.txt` | Signed-in YouTube cookies for yt-dlp |
| `~/llm-tracker/serve.py` | HTTP server (default port 8080) |
| ~~`redirect80.py`~~ | Removed: replaced by Caddy |
| `~/llm-tracker/Caddyfile` | Caddy reverse proxy config (auto-HTTPS for track.ionce.me) |
| `~/llm-tracker/index.html` | Dashboard UI |
| `~/llm-tracker/graph.html` | Legacy standalone topic graph — now embedded in index.html as a section |
| `~/llm-tracker/subs/` | Cached SRT subtitle files |

## Workflow: Processing New Videos

### Step 1: Discover & Transcribe
```bash
cd ~/llm-tracker && python3 -u fetch_and_analyze.py
```
This does:
- Lists recent videos from each channel via `yt-dlp --js-runtime node --cookies cookies.txt`
- Fetches subtitles via yt-dlp (fast, 114/120 had subtitles)
- Falls back to Cloudflare Whisper API for missing subtitles
- Saves to `data.json` with raw transcripts + keyword-based topics

**Important flags:** yt-dlp REQUIRES `--js-runtime node` on this AWS instance — without it, YouTube's n-challenge fails and only storyboard images are available.

### Step 2: LLM Analysis (Hermes does this DIRECTLY)
After the pipeline runs, check for new videos:
```bash
cd ~/llm-tracker && python3 << 'PYEOF'
import json
d = json.load(open('data.json'))
new = [v for v in d['videos'] if v.get('analysis_quality') != 'llm_enriched']
print(f'{len(new)} videos need LLM analysis')
for v in new[:5]:
    print(f"  [{v['channel_name']}] {v['title'][:60]}")
PYEOF
```

### Step 2.5: Regenerate Topic Embeddings (periodic, manual)
When new videos are added, their `specific_topics` won't have pre-computed embeddings. To regenerate:
```bash
# On MacBook:
scp ec2-user@54.165.122.89:~/llm-tracker/topics.json ~/topics.json
python3 embed_topics.py
scp ~/topic_embeddings.json ec2-user@54.165.122.89:~/llm-tracker/
```
The pipeline falls back to Jaccard similarity for uncovered topics until embeddings are refreshed.

**CRITICAL: Hermes analyzes transcripts DIRECTLY — do NOT delegate to subagents.** Subagents consistently time out on transcript data (3x timeout in this session). Instead, follow the pattern in `references/batch-enrichment-pattern.md`:

1. Use `terminal` to read transcript excerpts in batches (10-20 videos at a time, ~500-1000 char excerpts each)
2. Generate the enrichment dict in your own context
3. Write it back to `data.json` via a single `terminal` python3 script
4. Repeat until all videos are enriched

For each video, produce these fields (see `references/batch-enrichment-pattern.md` for quality guidelines):
- **summary**: 2-3 specific sentences about what the video covers
- **specific_topics**: 3-6 PRECISE topics (e.g. "KV cache optimization", NOT "AI")
- **key_insights**: 2-4 specific claims or findings
- **creator_stance**: what the creator believes about the main topic (1-2 sentences)
- **technical_level**: beginner | intermediate | advanced
- **notable_quotes**: 1-2 direct quotes from the transcript

Write enrichments directly into each video's entry in `data.json` with `analysis_quality: 'llm_enriched'`:
```python
# Pattern for batch enrichment
enrichments = {
    "VIDEO_ID": {
        "summary": "...",
        "specific_topics": [...],
        "key_insights": [...],
        "creator_stance": "...",
        "technical_level": "...",
        "notable_quotes": [...]
    },
    # ... more videos
}
for v in d['videos']:
    if v['id'] in enrichments:
        v.update(enrichments[v['id']])
        v['analysis_quality'] = 'llm_enriched'
```

### Step 3: Rebuild Cross-Channel Connections
After enrichment, rebuild connections by running `find_semantic_connections()` from `fetch_and_analyze.py`. This uses a 3-tier approach:

```python
# In fetch_and_analyze.py — called from main():
connections = find_semantic_connections(all_videos)
```

**Tier 1 — Embedding similarity (preferred, needs CF quota):** Embeds topic strings via `@cf/qwen/qwen3-embedding-0.6b`, clusters with Union-Find at cosine similarity ≥ 0.72. Best semantic quality.

**Tier 2 — Jaccard similarity (local fallback):** Tokenizes topics, removes domain stop words (`STOP_WORDS` set — "ai", "model", "gpt", "claude", etc.), clusters at Jaccard ≥ 0.4. No API needed. Produces ~30 connections across 11/12 channels.

**Tier 3 — Exact matching (baseline):** Always runs as safety net via `find_cross_channel_connections()`.

Each connection is tagged with `match_type` (`embedding` / `jaccard` / `exact`).

**Key pitfall:** Without the stop word list, Jaccard produces false positives from generic terms ("AI", "model"). The `STOP_WORDS` frozenset in the code is tuned for the LLM domain — don't remove it.

To rebuild manually (e.g., after agent enrichment):
```python
import json, sys
sys.path.insert(0, '/home/ec2-user/llm-tracker')
from fetch_and_analyze import find_semantic_connections
with open('/home/ec2-user/llm-tracker/data.json') as f:
    data = json.load(f)
data['connections'] = find_semantic_connections(data['videos'])
with open('/home/ec2-user/llm-tracker/data.json', 'w') as f:
    json.dump(data, f, indent=2, default=str)
```

### Step 4: Restart Server
```bash
cd ~/llm-tracker
pkill -f "serve.py" 2>/dev/null
python3 serve.py 8080 &   # Dashboard backend
sudo caddy start --config Caddyfile 2>&1  # Auto-HTTPS reverse proxy
```
Caddy auto-obtains Let's Encrypt SSL certs for track.ionce.me and reverse-proxies to port 8080. HTTP→HTTPS redirect is automatic.

## Cloudflare Whisper API

**Account:** `Ask Account ID from user`
**Token:** `Ask Token from user`
**Model:** `@cf/openai/whisper-large-v3-turbo`
**Cost:** $0.00051/audio-minute
**Limit:** Works for full 82-min videos (41MB). For >25MB, pipeline auto-chunks with ffmpeg.

API call:
```python
import requests, base64
url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/openai/whisper-large-v3-turbo"
headers = {"Authorization": "Bearer {TOKEN}"}
with open("audio.mp3", "rb") as f:
    audio_b64 = base64.b64encode(f.read()).decode()
resp = requests.post(url, headers=headers, json={"audio": audio_b64, "language": "en"}, timeout=600)
# resp.json()["result"]["segments"] — list of {start, end, text}
# resp.json()["result"]["text"] — full text
```

## Channels (12)

| Channel | ID |
|---|---|
| Andrej Karpathy | UCXUPKJO5MZQN11PqgIvyuvQ |
| 3Blue1Brown | UCYO_jab_esuFRV4b17AJtAw |
| Two Minute Papers | UCbfYPyITQ-7l4upoX8nvctg |
| Yannic Kilcher | UCZHmQk67mSJgfCCTn7xBfew |
| AI Explained | UCNJ1Ymd5yFuUPtn21xtRbbw |
| Fireship | UCsBjURrPoezykLs9EqgamOA |
| Sam Witteveen | UC55ODQSvARtgSyc8ThfiepQ |
| The AI Epiphany | UCj8shE7aIn4Yawwbo2FceCQ |
| Wes Roth | UCqcbQf6yw5KzRoDDcZ_wBSw |
| Dave Ebbelaar | UCn8ujwUInbJkBhffxqAPBVQ |
| All About AI | UCR9j1jqqB5Rse69wjUnbYwA |
| 1littlecoder | UCpV_X0VrL8-jg3t6wYGS-1g |

## Architecture Integrity (IMPORTANT)

The pipeline has a **two-layer enrichment architecture** — do NOT conflate them:

1. **Layer 1 (code — automated):** `fetch_and_analyze.py` runs `extract_topics_and_claims()` — keyword-based topic matching against 20 predefined categories + claim sentence extraction. This produces `topics` and `claims` fields. Runs automatically during every pipeline cycle.

2. **Layer 2 (agent — during cron runs):** The Hermes agent reads transcript excerpts (~500-1000 chars) and applies LLM reasoning to produce `summary`, `specific_topics`, `key_insights`, `creator_stance`, `technical_level`, `notable_quotes`. These are written back to `data.json` with `analysis_quality: "llm_enriched"`.

**Do NOT add LLM API calls to `fetch_and_analyze.py`** unless the user explicitly asks. The agent-driven enrichment is the intended architecture — the agent reasons about transcripts more effectively than a single API call, can build cross-video connections, and avoids JSON fragility.

## Credentials

Credentials are loaded from `~/llm-tracker/.env` at startup (auto-loaded by `fetch_and_analyze.py`, no python-dotenv needed). Required vars: `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `YT_API_KEY`. A `.env.example` file documents the required keys. `.env` is in `.gitignore`.

## Enrichment Architecture (Two-Layer)

The tracker uses a **two-layer enrichment** approach — this is critical to understand for accuracy:

**Layer 1 — Automated (in code):** `fetch_and_analyze.py` has `extract_topics_and_claims()`, a keyword-based function scanning for 20 predefined topic categories. This runs automatically and produces `topics` and `claims` fields.

**Layer 2 — Agent-driven (LLM):** During cron runs, the Hermes agent reads transcript excerpts and applies LLM reasoning to produce: `summary`, `specific_topics`, `key_insights`, `creator_stance`, `technical_level`, `notable_quotes`. The agent writes these back to `data.json` with `analysis_quality: 'llm_enriched'`.

## Cross-Channel Connection Detection (Three-Tier)

`find_semantic_connections()` in `fetch_and_analyze.py` uses a three-tier strategy:

1. **Embedding similarity (preferred):** CF Qwen3 embeddings + cosine similarity ≥ 0.72 via Union-Find clustering. Best quality — captures semantic equivalence across phrasings.
2. **Jaccard similarity (fallback):** Tokenized topic strings with domain stop words removed, Jaccard ≥ 0.4. Local, no API needed. Stop words include model names and generic terms (ai, llm, model, gpt, claude, etc.).
3. **Exact string matching (baseline):** Safety net for identical topic strings.

Results: exact=5 connections/6ch → jaccard=30 connections/11ch → embeddings=TBD (pending CF quota).

Each connection tagged with `match_type` (`embedding`/`jaccard`/`exact`) for transparency.

## Pitfalls

1. **yt-dlp n-challenge:** MUST use `--js-runtime node` flag. Without it, only storyboard images available. This is specific to this AWS instance — the JS runtime detection fails despite node being installed at `/home/ec2-user/.local/bin/node`.
2. **OOM:** Local Whisper + pyannote OOM on 3.7GB RAM. Use Cloudflare Whisper API instead — zero local RAM, handles 82-min videos.
3. **RSS feeds:** YouTube RSS feeds return 500/404 from this server. Use `yt-dlp --flat-playlist` for video discovery instead.
4. **HTTPS via Caddy:** Caddy handles port 80/443 with auto-HTTPS for track.ionce.me. Binary installed at `/usr/local/bin/caddy` (ARM64). Config: `~/llm-tracker/Caddyfile`. If port 80 is in use when starting Caddy, kill conflicting processes first: `sudo fuser -k 80/tcp`. See `references/caddy-https-setup.md` for full setup.
5. **Subagent analysis:** **NEVER** use `delegate_task`/subagents for transcript analysis — they consistently timeout on large data (3 failures in one session). Hermes must analyze transcripts directly by reading excerpts via `terminal` and generating enrichment dicts in its own context.
6. **Cookies:** cookies.txt must be refreshed periodically if YouTube sessions expire. Signs: yt-dlp returns "Sign in to confirm you're not a bot".
7. **data.json structure & size:** ~16MB for 120 videos with full timestamped segments. Structure is `{'videos': [...], 'connections': [...], 'last_update': '...', 'channel_count': N, 'video_count': N}` — NOT a bare list. Always load with `data = json.load(f)` then access `data['videos']`. **NEVER** read via `read_file` tool — it returns empty for files this large. Always use `terminal` with python3 to read/modify data.json. Pipeline now stores `transcript_segments` as array of `{start, end, text}` (not just count).
8. **Audio cleanup:** After Whisper transcription, delete audio files to save disk (only 15GB total). Use `find audio/ -name "*.mp3" -delete` (not `rm audio/*.mp3` which can timeout on large directories).
9. **execute_code JSON parsing:** `read_file` from hermes_tools returns empty content for large files. The `execute_code` tool also can't read data.json directly. Always use `terminal` with `python3 << 'PYEOF'` heredoc pattern for data.json operations.
10. **Connection detection — use semantic matching, not exact:** Exact string matching on `specific_topics` produces only ~5 connections across 6/12 channels — too few. `find_semantic_connections()` in `fetch_and_analyze.py` uses a 3-tier approach: CF embeddings (best) → Jaccard with stop words (fallback) → exact (baseline). Jaccard with stop word removal produces ~30 connections across 11/12 channels. When rebuilding connections manually, always call `find_semantic_connections()`, not the old `find_cross_channel_connections()`.

11. **CF neuron quota is SHARED across ALL models:** Whisper transcriptions, LLM calls, and embedding calls all consume from the same 10,000 neurons/day free tier. Transcribing 120 videos can exhaust the quota, leaving nothing for embeddings or LLM enrichment. Strategy: (a) only use Whisper for videos WITHOUT subtitles (~5%), (b) run embeddings/LLM enrichment on a different day than bulk transcription, (c) the Jaccard fallback works offline when quota is exhausted.
12. **Port 80 redirect verification:** Always verify both `localhost:80` and the external IP after restarting. The redirect proxy and serve.py are separate processes — both must be running.
12. **Cloudflare neuron quota is SHARED across ALL models:** The 10,000 neurons/day free tier is shared across Whisper, LLM, and embedding endpoints. A heavy transcription day (e.g., 120 videos) will exhaust the quota for ALL models. Plan accordingly — don't expect embeddings or LLM calls to work after a transcription run. **New API tokens don't help** — the limit is per-account, not per-token. Check dashboard for actual usage before assuming quota is available.
13. **CF quota reset timing may not be UTC midnight:** The dashboard may show 0/10k usage while the API still returns 429. The reset might be on a rolling 24h window. Don't assume quota is available just because the dashboard shows fresh allocation.
14. **Credentials must be in `.env`, never in code:** `fetch_and_analyze.py` loads from `.env` via `os.environ.get()`. Required vars: `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `YT_API_KEY`. A `.env.example` documents the required vars. `.gitignore` excludes `.env`. **Never commit API tokens to the repo.**
16. **Embedding evaluation is resource-constrained:** Embedding-based connections (CF Qwen3) produce the best results but consume from the shared neuron quota. If quota is exhausted, the system falls back to Jaccard similarity automatically. Document which method was used in the evaluation results.
17. **3Blue1Brown videos:** Many are math/visual-heavy with music — Cloudflare Whisper returns 0 segments for these. Don't waste API quota retrying them. Mark as "No transcript available" and move on.
14. **Dashboard HTML field mapping:** The dashboard HTML uses `v.topics` and `v.claims` by default. After LLM enrichment, the HTML MUST be updated to use `specific_topics`, `key_insights`, `summary`, `creator_stance`, `notable_quotes`. See `references/dashboard-html-patterns.md` for the full update pattern.
15. **EC2 architecture is ARM64:** This instance runs `aarch64`, not `x86-64`. Any binary downloads (Caddy, etc.) must use `arch=arm64`. Using the wrong arch gives "Exec format error".
16. **`--flat-playlist` returns FAKE dates:** yt-dlp's `--flat-playlist` mode returns today's date (YYYYMMDD) as `upload_date` for all videos — NOT the actual publish date. The `published` field in data.json will be wrong (all identical). To get real dates: run `yt-dlp -j --no-download <url>` for each video individually and read `upload_date`. The YouTube Data API key (`AIzaSy...`) is EXPIRED/INVALID (returns 400 "API key not valid"). Don't waste time trying it.
17. **Date fetching is slow:** Individual `yt-dlp -j` calls take ~3-5s each. For 120 videos = ~6-10 minutes. Use `python3 -u` (unbuffered) for background processes or output won't appear. Save data.json every 10 videos to avoid losing progress. Batch processing with `--flat-playlist` is fast but gives wrong dates.
18. **D3.js force graph pitfalls:** When embedding D3 force-directed graphs, define scale functions (e.g., `radiusScale`) BEFORE passing them to force configurations (`d3.forceCollide().radius(d => radiusScale(d.count))`). JavaScript `const` in temporal dead zone throws ReferenceError. Also: when graph JS references global data variables from the main app (e.g., `DATA.videos`), ensure the variable name matches exactly — don't invent new names like `videoData` if the app uses `DATA`.
19. **Embedded vs separate pages:** User prefers features embedded in the main dashboard as sections, not separate HTML pages. Add D3/external libs via `<script src>` in `<head>`, add CSS in the existing `<style>` block, add JS functions before the main `loadData()` call, and hook initialization into the existing `render()` function.
20. **Python background process output buffering:** Always use `python3 -u` (or `PYTHONUNBUFFERED=1`) for background terminal processes. Without it, output never appears in process logs and the agent can't track progress. Also use `flush=True` on print statements.
21. **Caddy auto-HTTPS works great:** Caddy reverse proxy on ARM64 EC2 with Let's Encrypt auto-SSL is the cleanest HTTPS solution. Config is 3 lines. Port 80 conflicts need `sudo fuser -k 80/tcp` before starting. The old Python redirect proxy (`redirect80.py`) can be deleted.
22. **d3-cloud word cloud:** The topic distribution uses d3-cloud (`d3.layout.cloud`). CDN: `https://cdn.jsdelivr.net/npm/d3-cloud@1.2.7/build/d3.layout.cloud.min.js`. Key gotcha: `d3.layout.cloud()` is async — the `draw` callback fires after layout completes. Use `d3.scaleSqrt` for font sizing (linear makes small topics invisible). Rotate ~30% of words 90° for visual variety. Limit to top 60 topics or the cloud becomes unreadable.
23. **Time-based video filtering:** Use YYYYMMDD string comparison (`v.published >= cutoffStr`) — it's correct because YYYYMMDD sorts lexicographically. Don't parse dates with `new Date()` per video (slow). Compute cutoff once, compare strings.
24. **Embedding features in the main dashboard:** When adding new visualizations/sections: (1) add CSS in the existing `<style>` block, (2) add external libs via `<script src>` in `<head>`, (3) add JS functions before `loadData()`, (4) hook initialization into `render()`, (5) add HTML section in the body. Never create a separate page unless user explicitly asks — user prefers everything in one dashboard.
25. **GitHub repo management:** User prefers to handle GitHub repo creation and pushes themselves. Don't spend time installing `gh` or setting up auth — just prepare the files and let the user upload.

## Cron Job

- **Job ID:** `fa758abfdc6d`
- **Schedule:** `0 17,20 * * *` → runs at 17:00 UTC and 20:00 UTC daily (within user's preferred 1600-2400 UTC window)
- **Loads skill:** `llm-youtube-tracker`
- **Pipeline:** discover → transcribe → LLM analyze → report

## Cleanup

Working dir should stay lean (~10MB). After transcription runs, clean up:
```bash
cd ~/llm-tracker
rm -f test_*.mp3 test_*.webm compact_batch*.json pipeline.log
rm -rf __pycache__
find audio/ -name "*.mp3" -delete 2>/dev/null; rmdir audio 2>/dev/null
```
**Never leave in the repo:** test audio files, node_modules, intermediate batch JSONs. The only files needed are: `fetch_and_analyze.py`, `serve.py`, `index.html`, `data.json`, `channels.json`, `cookies.txt`, `Caddyfile`, `start.sh`, `subs/`.
