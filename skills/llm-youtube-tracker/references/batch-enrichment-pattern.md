# Batch Enrichment Pattern for Transcript Analysis

## Problem
Analyzing 120 video transcripts requires processing them in manageable batches. Subagents consistently timeout on this task (3 failures). Hermes must analyze directly.

## Pattern

### 1. Read Excerpts (10-20 videos per batch)
```bash
cd ~/llm-tracker && python3 << 'PYEOF'
import json
d = json.load(open('data.json'))
remaining = [v for v in d['videos'] if v.get('analysis_quality') != 'llm_enriched']
for v in remaining[0:10]:
    txt = v.get('transcript_text', '')
    print(f"=== [{v['channel_name']}] {v['title']} (ID: {v['id']}) ===")
    print(txt[:600] if txt else '[NO TRANSCRIPT]')
    print()
PYEOF
```

### 2. Generate Enrichment Dict in Context
Read the excerpts, then produce a Python dict literal with enrichments for each video. The dict uses video ID as key:

```python
enrichments = {
    "VIDEO_ID": {
        "summary": "2-3 specific sentences about what the video covers",
        "specific_topics": ["topic1", "topic2", "topic3"],  # 3-6 PRECISE topics
        "key_insights": ["insight1", "insight2"],  # 2-4 specific claims
        "creator_stance": "What the creator believes (1-2 sentences)",
        "technical_level": "beginner|intermediate|advanced",
        "notable_quotes": ["direct quote from transcript"]
    },
}
```

### 3. Apply Enrichments to data.json
```bash
cd ~/llm-tracker && python3 << 'PYEOF'
import json
d = json.load(open('data.json'))

enrichments = {
    # ... the dict from step 2
}

count = 0
for v in d['videos']:
    vid = v['id']
    if vid in enrichments and v.get('analysis_quality') != 'llm_enriched':
        e = enrichments[vid]
        v['summary'] = e['summary']
        v['specific_topics'] = e['specific_topics']
        v['key_insights'] = e['key_insights']
        v['creator_stance'] = e['creator_stance']
        v['technical_level'] = e['technical_level']
        v['notable_quotes'] = e['notable_quotes']
        v['analysis_quality'] = 'llm_enriched'
        count += 1

with open('data.json', 'w') as f:
    json.dump(d, f, indent=2, default=str)

enriched_total = sum(1 for v in d['videos'] if v.get('analysis_quality') == 'llm_enriched')
print(f"Enriched {count} this batch | Total: {enriched_total}/{len(d['videos'])}")
PYEOF
```

### 4. Rebuild Cross-Channel Connections
After all videos are enriched, rebuild connections using specific_topics:
```bash
cd ~/llm-tracker && python3 << 'PYEOF'
import json
from collections import defaultdict
d = json.load(open('data.json'))

topic_videos = defaultdict(list)
for v in d['videos']:
    for topic in v.get('specific_topics', []):
        topic_videos[topic].append({
            'id': v['id'], 'title': v['title'], 'channel': v['channel_name']
        })

connections = []
for topic, vids in topic_videos.items():
    channels = set(v['channel'] for v in vids)
    if len(channels) >= 2:
        connections.append({
            'topic': topic, 'videos': vids[:6], 'channel_count': len(channels)
        })

connections.sort(key=lambda x: x['channel_count'], reverse=True)
d['connections'] = connections[:30]

with open('data.json', 'w') as f:
    json.dump(d, f, indent=2, default=str)

print(f"Connections: {len(d['connections'])}")
for c in d['connections'][:5]:
    print(f"  {c['topic']} ({c['channel_count']} channels)")
PYEOF
```

## Quality Guidelines for Enrichment

### specific_topics (3-6 per video)
- GOOD: "KV cache optimization", "BPE tokenization algorithm", "GPT-2 124M reproduction"
- BAD: "AI", "machine learning", "technology", "GPT"

### key_insights (2-4 per video)
- Must be specific claims the creator makes, not generic observations
- Include numbers/quantifiers when present
- GOOD: "AlphaGeometry solved 25/30 IMO geometry problems, exceeding silver medalist performance"
- BAD: "AI is getting better at math"

### creator_stance (1-2 sentences)
- What the creator specifically believes about the main topic
- Not a summary — it's their opinion/perspective
- GOOD: "Tokenization is the most underappreciated component of LLMs. Most users don't understand it, but it explains the majority of weird model behaviors."
- BAD: "The creator talks about tokenization."

### notable_quotes (1-2 per video)
- Direct quotes from the transcript
- Choose quotes that are memorable, insightful, or capture the creator's voice
- Don't paraphrase — use exact words

## Expected Timeline
- Reading 10-20 excerpts: ~10 seconds (terminal call)
- Generating enrichments in context: depends on model speed
- Writing enrichments to data.json: ~5 seconds per batch
- Total for 120 videos: 6-12 batches, expect 30-60 minutes total

## Connection Quality
With LLM-enriched specific_topics, expect 5-15 cross-channel connections (vs 20+ with keyword matching). The connections are fewer but far more meaningful — they represent genuine topic overlap between channels, not just shared use of common words.
