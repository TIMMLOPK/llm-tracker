#!/usr/bin/env python3
"""
LLM YouTube Tracker - Main Pipeline
Uses yt-dlp for video discovery + subtitles, Cloudflare Whisper API for fallback transcription.
"""
import json
import re
import subprocess
import base64
import math
import requests
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv
import os


load_dotenv()

# === CONFIG ===
WORKDIR = Path(__file__).parent
DATA_FILE = WORKDIR / "data.json"
CHANNELS_FILE = WORKDIR / "channels.json"
COOKIES_FILE = WORKDIR / "cookies.txt"

# Cloudflare API (from environment)
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
CF_WHISPER_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/openai/whisper-large-v3-turbo"

# YouTube Data API (from environment)
YT_API_KEY = os.environ.get("YT_API_KEY", "")

MAX_VIDEOS_PER_CHANNEL = 10
WHISPER_CHUNK_MINUTES = 20  # Chunk audio for Whisper if > this


def load_json(path, default=None):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return default or {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def fetch_recent_videos_ytdlp(channel_url, max_videos=MAX_VIDEOS_PER_CHANNEL):
    """Use yt-dlp to list recent videos from a channel (replaces broken RSS)."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--js-runtime", "node", "--cookies", str(COOKIES_FILE),
             "--flat-playlist", "--playlist-end", str(max_videos),
             "--dump-json", channel_url],
            capture_output=True, text=True, timeout=120
        )
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                videos.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "url": f"https://www.youtube.com/watch?v={item.get('id')}",
                    "published": item.get("upload_date") or datetime.now(timezone.utc).strftime("%Y%m%d"),
                    "duration": item.get("duration"),
                })
            except json.JSONDecodeError:
                continue
        return videos
    except Exception as e:
        print(f"  [WARN] yt-dlp listing failed: {e}")
        return []


def fetch_recent_videos_api(channel_id, max_videos=MAX_VIDEOS_PER_CHANNEL):
    """Fallback: YouTube Data API."""
    try:
        url = f"https://www.googleapis.com/youtube/v3/search?key={YT_API_KEY}&channelId={channel_id}&part=snippet&type=video&order=date&maxResults={max_videos}"
        resp = requests.get(url, timeout=30)
        data = resp.json()
        videos = []
        for item in data.get("items", []):
            videos.append({
                "id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "published": item["snippet"]["publishedAt"][:10].replace("-", ""),
            })
        return videos
    except Exception as e:
        print(f"  [WARN] API fetch failed: {e}")
        return []


def get_subtitles(video_id):
    """Try to get subtitles via yt-dlp (fast, no audio download)."""
    srt_path = WORKDIR / "subs" / f"{video_id}.en.srt"
    srt_path.parent.mkdir(exist_ok=True)

    if srt_path.exists():
        return parse_srt(srt_path.read_text())

    try:
        result = subprocess.run(
            ["yt-dlp", "--js-runtime", "node", "--cookies", str(COOKIES_FILE),
             "--write-auto-sub", "--sub-lang", "en", "--sub-format", "srt",
             "--skip-download", "-o", str(srt_path.with_suffix("")),
             f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, timeout=120
        )
        # yt-dlp appends .en.srt to the output path
        actual_path = srt_path
        if not actual_path.exists():
            # Try alternate naming
            for p in srt_path.parent.glob(f"{video_id}*"):
                if p.suffix == ".srt":
                    actual_path = p
                    break
        if actual_path.exists():
            return parse_srt(actual_path.read_text())
    except Exception as e:
        print(f"    [WARN] Subtitle fetch failed: {e}")
    return None


def parse_srt(srt_text):
    """Parse SRT into list of {start, end, text}."""
    segments = []
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        # Parse timestamp
        ts_match = re.match(r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})', lines[1])
        if not ts_match:
            continue
        text = ' '.join(lines[2:]).strip()
        text = re.sub(r'<[^>]+>', '', text)  # strip HTML tags
        if text:
            segments.append({
                "start": ts_match.group(1),
                "end": ts_match.group(2),
                "text": text,
            })
    return segments


def download_audio(video_id):
    """Download audio as mp3 for Whisper processing."""
    audio_dir = WORKDIR / "audio"
    audio_dir.mkdir(exist_ok=True)
    audio_path = audio_dir / f"{video_id}.mp3"

    if audio_path.exists() and audio_path.stat().st_size > 1000:
        return audio_path

    try:
        subprocess.run(
            ["yt-dlp", "--js-runtime", "node", "--cookies", str(COOKIES_FILE),
             "-x", "--audio-format", "mp3", "--max-filesize", "200M",
             "-o", str(audio_path),
             f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, timeout=300
        )
        if audio_path.exists() and audio_path.stat().st_size > 1000:
            return audio_path
    except Exception as e:
        print(f"    [WARN] Audio download failed: {e}")

    # Cleanup failed download
    if audio_path.exists():
        audio_path.unlink()
    return None


def transcribe_with_cloudflare(audio_path, language="en"):
    """Transcribe audio using Cloudflare Whisper API. Chunks long files."""
    file_size = audio_path.stat().st_size

    # If small enough, send directly (< 25MB)
    if file_size < 25 * 1024 * 1024:
        return _cf_transcribe_file(audio_path, language)

    # Chunk long audio
    print(f"    [INFO] Audio is {file_size//1024//1024}MB, chunking...")
    chunk_dir = WORKDIR / "audio" / "chunks"
    chunk_dir.mkdir(exist_ok=True)

    # Get duration
    probe = subprocess.run(
        ["ffprobe", "-i", str(audio_path), "-show_entries", "format=duration",
         "-v", "quiet", "-of", "csv=p=0"],
        capture_output=True, text=True
    )
    total_seconds = float(probe.stdout.strip())
    chunk_seconds = WHISPER_CHUNK_MINUTES * 60
    all_segments = []
    offset = 0.0

    for i, start in enumerate(range(0, int(total_seconds), chunk_seconds)):
        chunk_path = chunk_dir / f"{audio_path.stem}_chunk{i}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ss", str(start),
             "-t", str(chunk_seconds), "-acodec", "libmp3lame", "-b:a", "64k",
             str(chunk_path)],
            capture_output=True, timeout=120
        )
        if chunk_path.exists() and chunk_path.stat().st_size > 1000:
            segments = _cf_transcribe_file(chunk_path, language)
            # Offset timestamps
            for seg in segments:
                seg["start"] = _offset_timestamp(seg["start"], offset)
                seg["end"] = _offset_timestamp(seg["end"], offset)
                all_segments.append(seg)
            try:
                chunk_path.unlink()
            except FileNotFoundError:
                pass
        offset += chunk_seconds

    return all_segments


def _cf_transcribe_file(audio_path, language="en"):
    """Single file transcription via Cloudflare Whisper."""
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    try:
        resp = requests.post(
            CF_WHISPER_URL,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
            json={"audio": audio_b64, "language": language},
            timeout=600
        )
        result = resp.json()
        if "result" in result:
            segments = result["result"].get("segments", [])
            # Convert to our format
            return [{
                "start": _seconds_to_ts(s.get("start", 0)),
                "end": _seconds_to_ts(s.get("end", 0)),
                "text": s.get("text", "").strip(),
            } for s in segments if s.get("text", "").strip()]
        else:
            print(f"    [WARN] CF Whisper error: {result.get('errors', result)[:200]}")
            return []
    except Exception as e:
        print(f"    [WARN] CF Whisper request failed: {e}")
        return []


def _seconds_to_ts(seconds):
    """Convert seconds to HH:MM:SS,mmm format."""
    if isinstance(seconds, str):
        return seconds
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _offset_timestamp(ts, offset_seconds):
    """Add offset to a timestamp string."""
    # Parse HH:MM:SS,mmm
    parts = ts.replace(",", ".").split(":")
    total = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    total += offset_seconds
    return _seconds_to_ts(total)


def get_transcript(video_id):
    """Get transcript: try subtitles first, then Cloudflare Whisper."""
    # Try subtitles (fast, no audio download)
    subs = get_subtitles(video_id)
    if subs and len(subs) > 5:
        print(f"    [OK] Subtitles: {len(subs)} segments")
        return {"source": "subtitles", "segments": subs}

    # Fall back to Cloudflare Whisper
    print(f"    [INFO] No subtitles, using Cloudflare Whisper...")
    audio = download_audio(video_id)
    if not audio:
        print(f"    [WARN] Could not download audio")
        return None

    segments = transcribe_with_cloudflare(audio)
    if segments:
        print(f"    [OK] Whisper: {len(segments)} segments")
        # Cleanup audio after transcription to save disk
        # audio.unlink()  # Keep for now
        return {"source": "cloudflare_whisper", "segments": segments}

    return None


def extract_topics_and_claims(transcript_text, video_title):
    """Simple keyword-based topic extraction (no LLM needed)."""
    text_lower = transcript_text.lower()
    topic_keywords = {
        "GPT": ["gpt", "gpt-4", "gpt-3", "chatgpt", "openai"],
        "LLaMA": ["llama", "meta ai", "meta's"],
        "Claude": ["claude", "anthropic"],
        "Gemini": ["gemini", "google ai", "bard"],
        "Mistral": ["mistral", "mixtral"],
        "Fine-tuning": ["fine-tun", "finetun", "lora", "qlora", "rlhf"],
        "RAG": ["rag", "retrieval augmented", "vector database"],
        "Agents": ["agent", "agentic", "tool use", "function call"],
        "Reasoning": ["reasoning", "chain of thought", "cot", "o1", "o3"],
        "Multimodal": ["multimodal", "vision", "image", "dall-e", "stable diffusion"],
        "Open Source": ["open source", "open-source", "hugging face", "huggingface"],
        "Safety": ["safety", "alignment", "jailbreak", "guardrail"],
        "Scaling": ["scaling law", "scaling", "parameters", "billion"],
        "Training": ["training", "pretrain", "pre-train", "dataset"],
        "Inference": ["inference", "quantiz", "gguf", "ggml", "vllm"],
        "Prompting": ["prompt", "few-shot", "zero-shot", "system prompt"],
        "Code": ["code gen", "copilot", "coding", "codex"],
        "Benchmark": ["benchmark", "eval", "leaderboard", "mmlu"],
        "Transformer": ["transformer", "attention", "self-attention"],
        "Diffusion": ["diffusion", "stable diffusion", "midjourney", "dall-e"],
    }
    topics = []
    for topic, keywords in topic_keywords.items():
        if any(kw in text_lower for kw in keywords):
            topics.append(topic)
    claims = []
    claim_indicators = ["we found", "results show", "we show", "this means",
                        "the key insight", "importantly", "the main", "we propose"]
    for sentence in re.split(r'[.!?]+', transcript_text):
        sentence = sentence.strip()
        if any(ind in sentence.lower() for ind in claim_indicators):
            if 20 < len(sentence) < 300:
                claims.append(sentence)
    return topics[:8], claims[:5]


def find_cross_channel_connections(videos):
    """Find cross-channel connections using exact topic matching (fast baseline)."""
    connections = []
    topic_videos = {}

    # Use specific_topics (LLM-enriched) if available, fall back to keyword topics
    for vid in videos:
        topics = vid.get("specific_topics") or vid.get("topics") or []
        for topic in topics:
            topic_videos.setdefault(topic, []).append(vid)

    for topic, vids in topic_videos.items():
        channels = set(v["channel_name"] for v in vids)
        if len(channels) >= 2:
            connections.append({
                "topic": topic,
                "videos": [{"id": v["id"], "title": v["title"], "channel": v["channel_name"]} for v in vids[:6]],
                "channel_count": len(channels),
                "match_type": "exact",
            })

    return sorted(connections, key=lambda x: x["channel_count"], reverse=True)[:20]


def _cosine_similarity(a, b):
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def _get_embeddings(texts, batch_size=50):
    """Get embeddings from Cloudflare Qwen3 embedding model. Returns list of vectors."""
    all_embeddings = []
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/qwen/qwen3-embedding-0.6b"

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            resp = requests.post(url, headers=headers, json={"text": batch}, timeout=60)
            result = resp.json()
            if "result" in result and isinstance(result["result"], list):
                all_embeddings.extend(result["result"])
            else:
                print(f"    [WARN] Embedding batch {i//batch_size} failed: {str(result)[:200]}")
                # Return None to signal fallback needed
                return None
        except Exception as e:
            print(f"    [WARN] Embedding request failed: {e}")
            return None

    return all_embeddings


def find_semantic_connections(videos, embedding_threshold=0.8, jaccard_threshold=0.4):
    """Find cross-channel connections using pre-computed embeddings with Jaccard fallback.

    Strategy:
    1. Load pre-computed embeddings from topic_embeddings.json (generated locally)
    2. Fall back to Jaccard similarity on tokenized topic strings (local, no API)
    3. Always includes exact matches as baseline

    Clusters topic strings from different channels that are semantically similar
    (e.g., "RLHF training" ≈ "reinforcement learning from human feedback").
    """
    # Collect unique topics with their source videos
    topic_info = {}
    for vid in videos:
        topics = vid.get("specific_topics") or vid.get("topics") or []
        for topic in topics:
            topic_info.setdefault(topic, []).append({
                "id": vid["id"], "title": vid["title"], "channel": vid["channel_name"]
            })

    unique_topics = list(topic_info.keys())
    if len(unique_topics) < 2:
        return find_cross_channel_connections(videos)

    # Try pre-computed embeddings first, fall back to Jaccard
    use_embeddings = False
    emb_file = WORKDIR / "topic_embeddings.json"
    precomputed = None
    if emb_file.exists():
        try:
            with open(emb_file) as f:
                precomputed = json.load(f)
        except Exception:
            pass

    # Build embedding lookup: topic_string -> vector
    emb_lookup = {}
    if precomputed and "topics" in precomputed and "embeddings" in precomputed:
        for topic, vec in zip(precomputed["topics"], precomputed["embeddings"]):
            emb_lookup[topic] = vec

    # Check coverage: how many of our topics have pre-computed embeddings?
    covered = sum(1 for t in unique_topics if t in emb_lookup)
    if covered >= len(unique_topics) * 0.8:  # 80%+ coverage
        print(f"  [INFO] Using pre-computed embeddings ({covered}/{len(unique_topics)} topics covered)")
        use_embeddings = True
    else:
        print(f"  [INFO] Embedding coverage too low ({covered}/{len(unique_topics)}), using Jaccard")

    # Stop words to remove for Jaccard (prevents false matches on generic terms)
    STOP_WORDS = frozenset({
        "ai", "llm", "llms", "model", "models", "new", "release", "releases",
        "gpt", "claude", "gemini", "llama", "deepseek", "open", "vs", "and",
        "the", "for", "in", "of", "a", "an", "to", "with", "is", "are", "was",
        "by", "from", "how", "what", "why", "can", "its", "it", "this", "that",
        "on", "at", "be", "do", "has", "have", "had", "not", "but", "or", "if",
        "so", "up", "out", "about", "into", "over", "after",
    })

    def tokenize(s):
        return set(re.findall(r"[a-z]+", s.lower())) - STOP_WORDS

    topic_tokens = {t: tokenize(t) for t in unique_topics} if not use_embeddings else {}

    def similarity(i, j):
        if use_embeddings:
            ti, tj = unique_topics[i], unique_topics[j]
            vi, vj = emb_lookup.get(ti), emb_lookup.get(tj)
            if vi is None or vj is None:
                return 0.0
            return _cosine_similarity(vi, vj)
        ti, tj = topic_tokens[unique_topics[i]], topic_tokens[unique_topics[j]]
        if not ti or not tj:
            return 0.0
        inter = len(ti.intersection(tj))
        union = len(ti.union(tj))
        return inter / union if union else 0.0

    threshold = embedding_threshold if use_embeddings else jaccard_threshold

    # Union-Find clustering
    parent = list(range(len(unique_topics)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Compare cross-channel topic pairs
    for i in range(len(unique_topics)):
        for j in range(i + 1, len(unique_topics)):
            channels_i = set(v["channel"] for v in topic_info[unique_topics[i]])
            channels_j = set(v["channel"] for v in topic_info[unique_topics[j]])
            if channels_i.intersection(channels_j):
                continue
            if similarity(i, j) >= threshold:
                union(i, j)

    # Collect clusters
    raw_clusters = {}
    for i in range(len(unique_topics)):
        root = find(i)
        raw_clusters.setdefault(root, []).append(i)

    # Two-pass: split mega-clusters (>12 topics) at higher thresholds
    MAX_CLUSTER_SIZE = 12
    clusters = {}
    cluster_id = 0
    for root, indices in raw_clusters.items():
        if len(indices) <= MAX_CLUSTER_SIZE:
            clusters[cluster_id] = indices
            cluster_id += 1
        else:
            # Re-cluster at progressively higher thresholds
            for split_threshold in [0.86, 0.88, 0.90, 0.92]:
                sub_parent = {i: i for i in indices}
                def sub_find(x):
                    while sub_parent[x] != x:
                        sub_parent[x] = sub_parent[sub_parent[x]]
                        x = sub_parent[x]
                    return x
                def sub_union(a, b):
                    ra, rb = sub_find(a), sub_find(b)
                    if ra != rb: sub_parent[ra] = rb
                for ii, i in enumerate(indices):
                    for j in indices[ii+1:]:
                        ch_i = set(v["channel"] for v in topic_info[unique_topics[i]])
                        ch_j = set(v["channel"] for v in topic_info[unique_topics[j]])
                        if ch_i.intersection(ch_j): continue
                        if similarity(i, j) >= split_threshold:
                            sub_union(i, j)
                sub_clusters = defaultdict(list)
                for i in indices:
                    sub_clusters[sub_find(i)].append(i)
                max_size = max(len(c) for c in sub_clusters.values())
                for sub_indices in sub_clusters.values():
                    clusters[cluster_id] = sub_indices
                    cluster_id += 1
                if max_size <= MAX_CLUSTER_SIZE:
                    break

    # Build connections from clusters spanning 2+ channels
    connections = []
    for root, indices in clusters.items():
        cluster_topics = [unique_topics[i] for i in indices]
        all_videos = []
        all_channels = set()
        for topic in cluster_topics:
            for v in topic_info[topic]:
                all_channels.add(v["channel"])
                all_videos.append(v)
        if len(all_channels) < 2:
            continue
        seen_ids = set()
        deduped = []
        for v in all_videos:
            if v["id"] not in seen_ids:
                seen_ids.add(v["id"])
                deduped.append(v)
        label = cluster_topics[0] if len(cluster_topics) == 1 else " / ".join(cluster_topics[:3])
        connections.append({
            "topic": label,
            "cluster_topics": cluster_topics,
            "videos": deduped[:8],
            "channel_count": len(all_channels),
            "match_type": "embedding" if use_embeddings else "jaccard",
        })

    # Add exact matches not already captured
    exact = find_cross_channel_connections(videos)
    existing_topics = {c["topic"] for c in connections}
    for ec in exact:
        if ec["topic"] not in existing_topics:
            ec["match_type"] = "exact"
            connections.append(ec)

    return sorted(connections, key=lambda x: x["channel_count"], reverse=True)[:50]


def main():
    print(f"=== LLM YouTube Tracker Pipeline ===")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")

    channels = load_json(CHANNELS_FILE, [])
    existing = load_json(DATA_FILE, {"videos": [], "connections": [], "last_update": None})
    existing_ids = {v["id"] for v in existing.get("videos", [])}

    all_videos = existing.get("videos", [])
    new_count = 0

    for ch in channels:
        name = ch["name"]
        url = ch.get("url", "")
        channel_id = ch.get("id", "")
        print(f"\n[{name}]")

        # Try yt-dlp first, fall back to API
        videos = fetch_recent_videos_ytdlp(f"{url}/videos")
        if not videos:
            videos = fetch_recent_videos_api(channel_id)

        print(f"  Found {len(videos)} recent videos")

        for v in videos:
            if v["id"] in existing_ids:
                continue

            print(f"  New: {v['title'][:60]}...")
            transcript = get_transcript(v["id"])

            transcript_text = ""
            if transcript:
                transcript_text = " ".join(s["text"] for s in transcript["segments"])

            topics, claims = extract_topics_and_claims(transcript_text, v["title"])

            video_entry = {
                "id": v["id"],
                "title": v["title"],
                "url": v["url"],
                "channel_name": name,
                "channel_id": channel_id,
                "published": v.get("published", ""),
                "duration": v.get("duration"),
                "transcript_source": transcript["source"] if transcript else None,
                "transcript_segments": transcript["segments"] if transcript else [],
                "transcript_text": transcript_text[:50000],  # Cap for storage
                "topics": topics,
                "claims": claims,
                "added_at": datetime.now(timezone.utc).isoformat(),
            }

            all_videos.append(video_entry)
            existing_ids.add(v["id"])
            new_count += 1

    # Rebuild cross-channel connections
    connections = find_semantic_connections(all_videos)

    output = {
        "videos": all_videos,
        "connections": connections,
        "last_update": datetime.now(timezone.utc).isoformat(),
        "channel_count": len(channels),
        "video_count": len(all_videos),
    }
    save_json(DATA_FILE, output)

    print(f"\n=== DONE ===")
    print(f"Total videos: {len(all_videos)}")
    print(f"New videos added: {new_count}")
    print(f"Cross-channel connections: {len(connections)}")
    print(f"Finished: {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
