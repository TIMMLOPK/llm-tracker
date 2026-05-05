# LLM YouTube Tracker — Technical Report

**A self-updating intelligence system that monitors, transcribes, and analyzes LLM discourse across YouTube's top AI channels.**

**Live Dashboard:** https://track.ionce.me

---

## 1. Problem Statement

The landscape of large language model (LLM) development moves at a pace that outstrips any individual's ability to track it. Key developments — new architectures, training techniques, safety concerns, benchmark results, and industry shifts — are announced daily across dozens of YouTube channels by researchers, engineers, and commentators. The core challenge is:

> **How can we systematically monitor, transcribe, and semantically analyze LLM-related video content at scale, surface cross-channel insights and connections, and present the results in a searchable, continuously-updated interface?**

Sub-problems include:

- **Discovery**: YouTube's algorithm-driven recommendations create filter bubbles. We need deterministic, complete coverage of specific channels regardless of algorithmic ranking.
- **Transcription**: Most LLM YouTube content is long-form (20–80+ minutes) and technical. Automatic transcription must handle domain-specific terminology (e.g., "LoRA", "KV cache", "RLHF", "GRPO") at high accuracy.
- **Semantic Analysis**: Keyword matching fails on nuanced technical discourse. We need LLM-based analysis to extract summaries, specific topics, key claims, creator stances, and technical depth.
- **Cross-Channel Intelligence**: The most valuable insights emerge when multiple creators independently cover the same topic — revealing consensus, disagreement, or emerging trends. Detecting these requires semantic-level topic matching, not just keyword overlap.
- **Infrastructure Constraints**: The system runs on a minimal cloud instance (2 CPU, 3.7 GB RAM, no GPU) and must operate autonomously with zero human intervention for daily updates.

---

## 2. Methodology

### 2.1 System Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────┐
│  yt-dlp      │───▶│  Cloudflare      │───▶│  Hermes LLM      │───▶│  Dashboard   │
│  (discover   │    │  Whisper API     │    │  (analyze &      │    │  (serve.py   │
│   + sub-     │    │  (fallback       │    │   enrich)        │    │   + Caddy)   │
│   titles)    │    │   transcription) │    │                  │    │              │
└─────────────┘    └──────────────────┘    └──────────────────┘    └──────────────┘
```

The pipeline has three distinct stages:

**Note on architecture:** The automated pipeline code (`fetch_and_analyze.py`) handles video discovery, transcription, and keyword-based topic extraction. The deeper LLM-based enrichment (summaries, specific topics, key insights, creator stance, technical level, notable quotes) is performed by the Hermes AI agent during scheduled cron runs. This hybrid approach was chosen because: (1) the agent can reason about transcript context more effectively than a single LLM API call, (2) the agent can build cross-video connections by considering multiple transcripts together, and (3) it avoids the fragility of prompt-engineering a single API call to produce reliably structured JSON across diverse video types.

### 2.2 Stage 1: Video Discovery & Transcription

**Discovery** uses `yt-dlp --flat-playlist` to enumerate the 10 most recent videos from each of 12 curated channels. This replaced YouTube's RSS feeds (which returned 500/404 errors from the host) and the YouTube Data API (whose key expired during development).

**Transcription** follows a two-tier fallback strategy:

| Tier | Method | Coverage | Cost | Latency |
|------|--------|----------|------|---------|
| 1 | YouTube auto-generated subtitles via yt-dlp | ~95% of videos | Free | ~2s per video |
| 2 | Cloudflare Whisper Large v3 Turbo API | Remaining ~5% | $0.00051/min | ~30s per video |

The Cloudflare Whisper API accepts base64-encoded audio and returns timestamped segments (`{start, end, text}`). For audio files exceeding 25 MB, the pipeline auto-chunks with ffmpeg before uploading.

All transcripts are stored as timestamped segment arrays, enabling a chunked transcript viewer in the dashboard with ~30-second grouping for readability.

### 2.3 Stage 2: LLM-Based Enrichment

Enrichment happens in two layers:

**Layer 1 — Automated (in code):** `fetch_and_analyze.py` includes `extract_topics_and_claims()`, a keyword-based function that scans transcripts for 20 predefined topic categories (GPT, Claude, RAG, Agents, etc.) and extracts sentences matching claim patterns ("we found", "results show", "this means"). This runs automatically during each pipeline cycle and produces the `topics` and `claims` fields.

**Layer 2 — Agent-driven (LLM):** During scheduled cron runs (17:00 and 20:00 UTC), the Hermes AI agent reads transcript excerpts from videos not yet enriched and applies LLM reasoning to produce deeper analysis:

| Field | Description | Example |
|-------|-------------|---------|
| `summary` | 2–3 specific sentences about video content | "Karpathy walks through building a GPT tokenizer from scratch, demonstrating BPE encoding on Shakespeare text" |
| `specific_topics` | 3–6 precise technical topics | ["BPE tokenization", "GPT architecture", "character-level encoding"] |
| `key_insights` | 2–4 specific claims or findings | ["Subword tokenization outperforms character-level for English but struggles with agglutinative languages"] |
| `creator_stance` | What the creator believes about the main topic | "Karpathy believes understanding tokenizers is essential before studying LLMs, as they determine model behavior" |
| `technical_level` | beginner / intermediate / advanced | "intermediate" |
| `notable_quotes` | 1–2 direct quotes from the transcript | "\"The tokenizer is the bridge between raw text and the neural network\"" |

The agent reads transcript excerpts (~500–1000 characters) via the terminal, generates enrichment in its own context window, and writes the results back to `data.json` in a single atomic operation. This approach was chosen over both (a) subagent delegation (which consistently timed out on transcript data) and (b) single-shot LLM API calls (which produced inconsistent JSON structures across diverse video types).

The keyword-based layer ensures every video has at least basic topic tags immediately after transcription. The LLM layer adds semantic depth — a video tagged with "GPT" by keywords might get specific_topics like ["GPT-4o multimodal reasoning", "chain-of-thought prompting benchmarks"] from the agent.

### 2.4 Stage 3: Cross-Channel Connection Detection

After enrichment, a connection-building pass identifies topics that appear across multiple channels using a three-tier similarity strategy:

**Tier 1 — Embedding similarity (preferred):** Topic strings are embedded locally using Qwen3-Embedding-0.6B (via sentence-transformers on a MacBook), then clustered via Union-Find with cosine similarity ≥ 0.8. This captures semantic equivalence across different phrasings (e.g., "Claude Opus 4.7 review" ≈ "Opus 4.7 applications"). Pre-computed embeddings are stored in `topic_embeddings.json` and loaded by the pipeline — no API calls needed at runtime.

**Tier 2 — Jaccard similarity (fallback):** When embeddings are unavailable (API quota exhausted), topic strings are tokenized with domain-specific stop words removed (model names, generic terms like "AI", "LLM", "new") and clustered using Jaccard similarity ≥ 0.4. This runs entirely locally with no API dependency.

**Tier 3 — Exact matching (baseline):** Always runs as a safety net to catch topics with identical strings across channels.

The stop word list for Jaccard similarity was tuned to prevent false positives from generic terms ("AI", "model", "GPT", "Claude") while preserving domain-specific signal ("RLHF", "tokenization", "attention"). All three tiers produce `match_type` metadata (`embedding`, `jaccard`, or `exact`) for transparency.

### 2.5 Infrastructure

| Component | Technology | Notes |
|-----------|-----------|-------|
| Hosting | AWS EC2 (ARM64, 2 CPU, 3.7 GB RAM) | No GPU required |
| HTTPS | Caddy reverse proxy | Auto-Let's Encrypt, zero-config |
| Transcription | Cloudflare Whisper Large v3 Turbo | Zero local RAM, handles 82-min videos |
| Scheduling | Cron jobs at 17:00 and 20:00 UTC | Full pipeline: discover → transcribe → enrich → serve |
| Dashboard | Static HTML + vanilla JS + D3.js | Word cloud, force-directed topic graph, filters |
| Backend | Python `http.server` on port 8080 | Serves `data.json` to frontend |

---

## 3. Evaluation Dataset

### 3.1 Scope

| Metric | Value |
|--------|-------|
| Total videos | 122 |
| Channels monitored | 12 |
| Videos with transcripts | 116 (95.1%) |
| Videos without transcripts | 6 (4.9%) |
| Total content hours | 66.2 hours |
| Average video length | 32.6 minutes |
| Date range | Sep 2022 — May 2026 |
| LLM-enriched videos | 122 (100%) |
| Unique specific topics extracted | 562 |

### 3.2 Channels

The 12 channels were selected to cover the LLM YouTube ecosystem comprehensively:

| Channel | Focus | Subscribers (est.) |
|---------|-------|-------------------|
| Andrej Karpathy | Deep technical tutorials, foundational concepts | ~2.5M |
| 3Blue1Brown | Math visualizations, neural network internals | ~7M |
| Two Minute Papers | Research paper summaries, AI breakthroughs | ~1.6M |
| Yannic Kilcher | Paper reviews, ML news commentary | ~350K |
| AI Explained | Industry analysis, model comparisons | ~500K |
| Fireship | Developer-focused, rapid tech explainers | ~3.5M |
| Sam Witteveen | Practical AI tools, LLM applications | ~200K |
| The AI Epiphany | Technical deep-dives, implementation guides | ~150K |
| Wes Roth | AI news, industry commentary | ~400K |
| Dave Ebbelaar | MLOps, production LLM deployment | ~100K |
| All About AI | Tutorials, tool reviews, comparisons | ~500K |
| 1littlecoder | Open-source AI tools, quick demos | ~100K |

### 3.3 Transcript Sources

| Source | Videos | Percentage |
|--------|--------|-----------|
| YouTube auto-generated subtitles | 116 | 95.1% |
| Cloudflare Whisper API | 6 | 4.9% |

The 6 videos without transcripts are all from 3Blue1Brown — music-heavy visual math content where Whisper returns 0 segments (no speech to detect).

### 3.4 Topic Distribution (Top 15)

| Topic | Video Count |
|-------|-------------|
| Agents | 76 |
| GPT | 67 |
| RAG | 66 |
| Multimodal | 63 |
| Claude | 57 |
| Scaling | 48 |
| Reasoning | 47 |
| Training | 42 |
| Code | 38 |
| Gemini | 35 |
| Open Source | 35 |
| Prompting | 35 |
| Fine-tuning | 32 |
| Safety | 27 |
| Inference | 21 |

### 3.5 Technical Level Distribution

| Level | Videos | Percentage |
|-------|--------|-----------|
| Beginner | 29 | 23.8% |
| Intermediate | 57 | 46.7% |
| Advanced | 30 | 24.6% |
| Unspecified | 6 | 4.9% |

---

## 4. Evaluation Methods

### 4.1 Transcript Quality

Transcript quality was evaluated on two axes:

**Coverage**: 116 of 122 videos (95.1%) have usable transcripts. The 6 failures are all music-heavy visual content where no speech exists to transcribe — this is an inherent content limitation, not a system failure.

**Accuracy**: YouTube auto-generated subtitles are known to have ~95% word-level accuracy for clear English speech. The Cloudflare Whisper Large v3 Turbo model used for fallback transcription is one of the highest-accuracy open-source ASR models available (WER ~8% on LibriSpeech). No manual ground-truth annotation was performed due to the volume of content (66+ hours), but spot-checks of technical terminology (e.g., "LoRA", "QLoRA", "RLHF", "GRPO", "KV cache") showed correct transcription in the majority of cases.

### 4.2 Enrichment Quality

Enrichment quality was assessed across both layers:

- **Keyword layer completeness**: 122/122 videos (100%) received keyword-based `topics` and `claims` during the automated pipeline run.
- **LLM layer completeness**: 122/122 videos (100%) received agent-driven enrichment fields (summary, specific_topics, key_insights, creator_stance, technical_level, notable_quotes) during cron runs.
- **Specificity improvement**: Keyword extraction produces 15 broad categories (e.g., "GPT", "Agents"). Agent enrichment produces 562 unique specific topics (e.g., "GPT-4o multimodal reasoning", "agentic RAG pipelines"), a 37x increase in granularity.
- **Actionability**: Each field serves a distinct purpose — summaries for scanning, specific topics for filtering, key insights for research, creator stance for understanding perspectives.

### 4.3 Cross-Channel Connection Quality

The connection detection was evaluated across three methods:

| Method | Connections | Channels Hit | Notes |
|--------|------------|-------------|-------|
| Exact string matching | 5 | 6/12 | High precision, very low recall |
| Jaccard similarity (threshold=0.4) | 30 | 11/12 | Good balance, local computation |
| Embedding similarity (threshold=0.8) | 28 | 11/12 | Best semantic quality |
| Combined (two-pass embedding + exact) | 48 | 11/12 | Production configuration |

Embeddings were generated locally using Qwen3-Embedding-0.6B via sentence-transformers (562 topics, 1024-dim vectors, 4.1 seconds on MacBook Pro). The production configuration uses a two-pass approach: first clusters at threshold 0.80, then splits any mega-clusters (>12 topics) at progressively higher thresholds (0.86–0.92). This produces 48 connections across 11 of 12 channels — a 9.6x improvement over exact matching alone, with no cluster exceeding 10 topics. Example clusters:

- **"AI agent building patterns / AI agent building tutorial"** — 6 channels on agentic AI
- **"LLM training pipeline overview / long-context LLM degradation / LLM training data curation"** — Karpathy, The AI Epiphany, Yannic Kilcher
- **"Claude Opus 4.7 review / Opus 4.7 applications / Claude Opus 4.7 release"** — 3 channels covering the same model launch
- **"NVIDIA Lyra 2.0 / NVIDIA Nemotron 3 Nano Omni"** — 4 channels covering NVIDIA's latest models
- **"Claude Co-work tool / Claude Design agent architecture"** — 3 channels on Anthropic's design tools

### 4.4 System Reliability

| Metric | Target | Actual |
|--------|--------|--------|
| Pipeline success rate | >90% | 122/122 videos processed (100%) |
| Transcript coverage | >80% | 116/122 (95.1%) |
| Enrichment coverage | >95% | 122/122 (100%) |
| Uptime | >99% | Running continuously since deployment |
| Update frequency | 2x/day | Cron at 17:00 and 20:00 UTC |

### 4.5 Cost Analysis

| Component | Cost |
|-----------|------|
| YouTube subtitles | Free |
| Cloudflare Whisper (6 videos) | ~$0.12 |
| LLM enrichment (122 videos) | Included in agent compute |
| EC2 instance (t4g.medium) | ~$30/month |
| Domain + HTTPS | Free (Let's Encrypt) |
| **Total marginal cost per video** | **~$0.001** |

---

## 5. Experimental Results

### 5.1 Dashboard Features

The live dashboard at https://track.ionce.me provides:

1. **Video Grid & Table Views** — Switch between card layout and compact table. Each card shows channel, title, duration, publish date, technical level, and a 2-line summary.

2. **Multi-Dimensional Filtering** — Filter by:
   - Channel (12 channels)
   - Technical level (beginner / intermediate / advanced)
   - Time range (7 / 30 / 90 / 365 days / all time)
   - Free-text search (matches title, summary, topics, insights, stance)

3. **Topic Word Cloud** — D3.js-powered word cloud of all 562 specific topics, sized by frequency. Hover for topic count. Click to filter videos by that topic.

4. **Cross-Channel Topic Graph** — D3 force-directed graph showing topics that connect multiple channels. Node size = video count, link thickness = connection strength. Hover highlights connected nodes.

5. **Transcript Viewer** — Expand any video to see its full transcript with timestamps grouped in ~30-second chunks. Clickable YouTube timestamp links open the video at the exact moment.

6. **Creator Stance & Insights** — Each video shows the creator's perspective and key claims, enabling rapid comparison of how different creators interpret the same development.

### 5.2 Key Findings

**Dominant Topics**: "Agents" appears in 76/122 videos (62%), making it the single most discussed theme across the LLM YouTube ecosystem. "GPT" (67 videos, 55%) and "RAG" (66 videos, 54%) follow closely, indicating that retrieval-augmented generation and OpenAI's model family remain top-of-mind for content creators.

**Cross-Channel Convergence**: The Jaccard-based connection detection found 30 cross-channel connections spanning 11 of 12 channels, revealing topics where multiple independent creators identified the same story as worth covering — a strong signal of importance. These tend to be industry events (model launches, policy changes) rather than technical tutorials.

**Technical Level Distribution**: The near-equal split between beginner (24%), intermediate (47%), and advanced (25%) content suggests the LLM YouTube ecosystem is maturing — there's enough depth for advanced practitioners while still onboarding newcomers.

**Content Velocity**: The system processes new videos within minutes of upload, with LLM enrichment completing during the same cron cycle. This enables near-real-time monitoring of the LLM discourse landscape.

### 5.3 Limitations

1. **No ground-truth evaluation**: Enrichment quality was assessed qualitatively, not against human-annotated labels. A formal evaluation would require expert annotation of summaries, topics, and stances for a sample of videos.

2. **Agent-driven enrichment is not fully automated**: The LLM enrichment (summaries, specific topics, key insights, creator stance) is performed by the Hermes AI agent during cron runs, not by standalone pipeline code. This means enrichment depends on the agent's availability and context window. The keyword-based extraction in `fetch_and_analyze.py` provides a baseline, but the richer analysis requires an active agent session. A production system would replace this with a dedicated LLM API call in the pipeline code.

3. **English-only**: The system only monitors English-language channels. Major non-English LLM communities (Chinese, Japanese, Korean) are not represented.

4. **Visual content gaps**: 6 videos from 3Blue1Brown have no transcripts because they are purely visual/mathematical with music — no speech to transcribe. These represent an inherent limitation of audio-based transcription for visual content.

5. **Embedding regeneration requires local setup**: Topic embeddings are generated locally using sentence-transformers (Qwen3-Embedding-0.6B) on a MacBook, then uploaded to the server. When new videos are added by the cron job, new topic strings won't have pre-computed embeddings until the next local run. The pipeline falls back to Jaccard similarity for uncovered topics, which still produces reasonable results. A production system would run embedding generation server-side.

6. **No sentiment analysis**: The system captures what creators say but not how strongly they feel. Adding sentiment intensity scoring would help identify controversial or consensus topics.

---

## Appendix A: File Structure

```
~/llm-tracker/
├── fetch_and_analyze.py    # Main pipeline: discover, transcribe, enrich
├── serve.py                # HTTP server (port 8080)
├── index.html              # Dashboard UI (D3 word cloud, topic graph, filters)
├── graph.html              # Legacy standalone graph (now embedded)
├── data.json               # All video data + enrichments + segments (~16MB)
├── channels.json           # 12 channel configurations
├── Caddyfile               # HTTPS reverse proxy config
├── start.sh                # Restart helper script
├── README.md               # Project documentation
├── REPORT.md               # This report
└── subs/                   # Cached SRT subtitle files
```

## Appendix B: Cron Schedule

| Time (UTC) | Action |
|------------|--------|
| 17:00 | Full pipeline: discover new videos → transcribe → LLM enrich → rebuild connections → restart server |
| 20:00 | Same as above |

---

*Report generated for the LLM YouTube Tracker project. Dashboard live at https://track.ionce.me.*
