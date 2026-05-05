# LLM Analysis Batch Processing Pattern

## How to Analyze Videos in Batches

**NEVER use subagents.** Read transcript excerpts via terminal, analyze in your own context, write back.

### Step 1: Read Excerpts (10-20 at a time)

```bash
cd ~/llm-tracker && python3 << 'PYEOF'
import json
d = json.load(open('data.json'))
remaining = [v for v in d['videos'] if v.get('analysis_quality') != 'llm_enriched']

for v in remaining[0:15]:
    txt = v.get('transcript_text', '')
    print(f"=== [{v['channel_name']}] {v['title'][:55]} (ID: {v['id']}) ===")
    print(txt[:600] if txt else '[NO TRANSCRIPT]')
    print()
PYEOF
```

### Step 2: Generate Enrichment Dict

After reading excerpts, produce a Python dict with this structure:

```python
enrichments = {
    "VIDEO_ID": {
        "summary": "2-3 specific sentences about what the video covers",
        "specific_topics": ["precise_topic_1", "precise_topic_2", "precise_topic_3"],
        "key_insights": ["specific claim 1", "specific claim 2"],
        "creator_stance": "What the creator believes about the main topic (1-2 sentences)",
        "technical_level": "beginner",  # or "intermediate" or "advanced"
        "notable_quotes": ["direct quote from transcript"]
    },
}
```

### Step 3: Write Back to data.json

```bash
cd ~/llm-tracker && python3 << 'PYEOF'
import json
d = json.load(open('data.json'))

enrichments = {
    # ... paste your enrichment dict here
}

count = 0
for v in d['videos']:
    if v['id'] in enrichments and v.get('analysis_quality') != 'llm_enriched':
        v.update(enrichments[v['id']])
        v['analysis_quality'] = 'llm_enriched'
        count += 1

with open('data.json', 'w') as f:
    json.dump(d, f, indent=2, default=str)

enriched_total = sum(1 for v in d['videos'] if v.get('analysis_quality') == 'llm_enriched')
print(f"Enriched {count} this batch | Total: {enriched_total}/{len(d['videos'])}")
PYEOF
```

### Step 4: Repeat Until 100%

Check remaining count and repeat steps 1-3 until all videos are enriched.

## Quality Guidelines

### specific_topics — BE PRECISE
- ❌ "AI", "Machine Learning", "Technology"
- ✅ "KV cache optimization", "BPE tokenization algorithm", "Claude Design agent architecture"

### key_insights — BE SPECIFIC
- ❌ "The video talks about AI models"
- ✅ "GPT-5.5 is actually the 'Spud' model that OpenAI had been teasing — a new class of intelligence"

### creator_stance — CAPTURE THEIR VIEW
- ❌ "The creator discusses the topic"
- ✅ "Tokenization is the most underappreciated component of LLMs. Most users don't understand it, but it explains the majority of weird model behaviors."

### notable_quotes — EXACT WORDS
- ❌ Paraphrased summaries
- ✅ Direct quotes from the transcript text

## Cross-Channel Connection Building

After enrichment, rebuild connections using specific_topics:

```python
from collections import defaultdict
topic_videos = defaultdict(list)
for v in d['videos']:
    for topic in v.get('specific_topics', []):
        topic_videos[topic].append({'id': v['id'], 'title': v['title'], 'channel': v['channel_name']})

connections = []
for topic, vids in topic_videos.items():
    channels = set(v['channel'] for v in vids)
    if len(channels) >= 2:
        connections.append({'topic': topic, 'videos': vids[:6], 'channel_count': len(channels)})

connections.sort(key=lambda x: x['channel_count'], reverse=True)
d['connections'] = connections[:30]
```

**Expect fewer but more meaningful connections.** Specific topics produce 5-10 real connections vs 20+ noise connections from keyword matching.
