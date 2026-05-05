# LLM YouTube Tracker

A self-updating dashboard that monitors, transcribes, and analyzes what popular AI/LLM YouTubers are actually saying about Large Language Models.

![Screenshot](/images/screenshot.png)

Read the full technical report in [REPORT.md](REPORT.md).

**Live dashboard:** [https://track.ionce.me](https://track.ionce.me)

## What it does

- **Follows 12 popular LLM-focused YouTube channels** (Karpathy, 3Blue1Brown, Two Minute Papers, Yannic Kilcher, AI Explained, Fireship, Sam Witteveen, The AI Epiphany, Wes Roth, Dave Ebbelaar, All About AI, 1littlecoder)
- **Discovers recent videos** via yt-dlp flat-playlist enumeration
- **Transcribes content** using YouTube auto-generated subtitles (tier 1) with Cloudflare Whisper API fallback (tier 2)
- **Enriches with LLM analysis** — summaries, specific topics, key insights, creator stance, technical level, and notable quotes via the Hermes AI agent
- **Maps cross-channel connections** — topics that appear across multiple independent channels
- **Auto-updates twice daily** via cron (17:00 and 20:00 UTC)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install yt-dlp (also available via pip)
pip install yt-dlp

# Install ffmpeg (required for audio chunking on long videos)
# macOS:
brew install ffmpeg
# Ubuntu:
sudo apt install ffmpeg

# Configure environment
cp .env.example .env
# Edit .env with your Cloudflare and YouTube API credentials

# Add YouTube cookies for yt-dlp (required for subtitle access)
# Export from your browser as Netscape format → cookies.txt

# Run the pipeline
python3 fetch_and_analyze.py

# Start the web dashboard
python3 serve.py 8080

# Open in browser
open http://localhost:8080
```

### Production Deployment

For HTTPS with auto-renewing certificates, use Caddy:

```bash
# Install Caddy, then:
# Edit Caddyfile to set your domain
caddy run
```

Use `start.sh` to restart the server:

```bash
./start.sh 8080
```

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────┐
│  yt-dlp      │───>│  Cloudflare      │───>│  Hermes Agent    │───>│  Dashboard   │
│  (discover   │    │  Whisper API     │    │  (LLM analyze &  │    │  (serve.py   │
│   + subs)    │    │  (fallback       │    │   enrich)        │    │   + Caddy)   │
└─────────────┘    └──────────────────┘    └──────────────────┘    └──────────────┘
```

| File | Purpose |
|------|---------|
| `fetch_and_analyze.py` | Main pipeline: discover videos, transcribe, keyword-based topic extraction |
| `serve.py` | HTTP server serving the dashboard on port 8080 |
| `index.html` | Self-contained dashboard UI (D3.js word cloud, topic graph, filters, transcript viewer) |
| `graph.html` | Legacy standalone topic graph (now embedded in index.html) |
| `data.json` | All video data, enrichments, and transcripts (~16MB, auto-updated) |
| `channels.json` | 12 channel configurations with IDs and focus areas |
| `Caddyfile` | Caddy reverse proxy config for HTTPS |
| `start.sh` | Server restart helper |
| `subs/` | Cached SRT subtitle files |

## Topic Categories

The keyword-based layer in `fetch_and_analyze.py` classifies videos into 20 categories:

GPT, LLaMA, Claude, Gemini, Mistral, Fine-tuning, RAG, Agents, Reasoning, Multimodal, Open Source, Safety, Scaling, Training, Inference, Prompting, Code, Benchmark, Transformer, Diffusion

The Hermes agent layer produces 562+ specific subtopics (e.g., "BPE tokenization", "agentic RAG pipelines", "KV cache optimization") on top of these broad categories.

## Auto-Updates

Cron runs the full pipeline twice daily:

| Time (UTC) | Action |
|------------|--------|
| 17:00 | Discover new videos → transcribe → keyword extract → Hermes agent enrich → rebuild connections → restart server |
| 20:00 | Same as above |

The web server serves the latest `data.json` automatically.

## Adding Channels

Edit `channels.json` to add new channels:

```json
{
  "name": "Channel Name",
  "channel_id": "UC...",
  "handle": "@handle",
  "focus": "Description of channel's LLM focus",
  "url": "https://www.youtube.com/channel/UC...",
  "id": "UC..."
}
```

Find channel IDs: `yt-dlp --flat-playlist --dump-json "https://www.youtube.com/@handle/videos" | head -1 | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('channel_id',''))"`

## Environment Variables

See `.env.example` for required configuration:

| Variable | Purpose |
|----------|---------|
| `CF_ACCOUNT_ID` | Cloudflare account ID for Whisper API |
| `CF_API_TOKEN` | Cloudflare API token with Workers AI access |
| `YT_API_KEY` | YouTube Data API key (fallback discovery method) |

## Hermes Agent

The LLM enrichment layer is powered by [Hermes](https://github.com/NousResearch/hermes-agent), an open-source, self-improving AI agent developed by Nous Research that runs 24/7 on the server. During each cron cycle, Hermes reads transcript excerpts, generates structured enrichment (summaries, specific topics, key insights, creator stance, technical level, notable quotes), and writes the results back to `data.json`.
