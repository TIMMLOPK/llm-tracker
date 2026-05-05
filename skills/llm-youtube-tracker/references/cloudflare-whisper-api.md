# Cloudflare Workers AI — Whisper API

## Endpoint

```
POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/openai/whisper-large-v3-turbo
Authorization: Bearer {TOKEN}
```

## Input Schema

```json
{
  "audio": "<base64-encoded-audio>",  // required
  "language": "en",                    // optional, ISO 639-1, auto-detects if omitted
  "task": "transcribe",               // optional, "transcribe" or "translate"
  "vad_filter": false,                 // optional, voice activity detection
  "initial_prompt": "",                // optional, context hint for the model
  "beam_size": 5,                      // optional, beam search width
  "condition_on_previous_text": true,  // optional, set false to reduce hallucination loops
  "no_speech_threshold": 0.6,         // optional, skip low-speech segments
  "compression_ratio_threshold": 2.4,  // optional, filter repetitive text
  "log_prob_threshold": -1,           // optional, filter low-confidence segments
  "hallucination_silence_threshold": null  // optional, seconds — skip hallucination-prone silence
}
```

## Output Schema

```json
{
  "result": {
    "text": "Full transcription text...",
    "word_count": 15074,
    "transcription_info": {
      "language": "en"
    },
    "segments": [
      {
        "start": 0.0,
        "end": 5.2,
        "text": "Segment text...",
        "temperature": 0.0,
        "avg_logprob": -0.15,
        "compression_ratio": 1.2,
        "no_speech_prob": 0.01
      }
    ],
    "vtt": "WEBVTT\n\n00:00:00.000 --> 00:00:05.200\nSegment text..."
  }
}
```

## Tested Limits

| Audio Length | File Size | Base64 Size | Transcription Time | Status |
|---|---|---|---|---|
| 5 min | 2.5 MB | 3.5M chars | 16.5s | ✅ |
| 10 min | 5 MB | 6.9M chars | 20.5s | ✅ |
| 20 min | 10 MB | 13.7M chars | 54.4s | ✅ |
| 82 min | 41 MB | 56.3M chars | 180s | ✅ |

**No hard size limit observed.** First attempt at 41MB returned 500 (transient), succeeded on retry.

## Cost

$0.00051 per audio minute. An 82-min video costs ~$0.04.

## Chunking Strategy (for very long videos)

Pipeline auto-chunks videos >25MB using ffmpeg:

```bash
ffmpeg -y -i input.mp3 -ss 0 -t 1200 -acodec libmp3lame -b:a 64k chunk_0.mp3
ffmpeg -y -i input.mp3 -ss 1200 -t 1200 -acodec libmp3lame -b:a 64k chunk_1.mp3
# ... etc, offset timestamps accordingly
```

## Python Usage

```python
import requests, base64

url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/openai/whisper-large-v3-turbo"
headers = {"Authorization": "Bearer {TOKEN}"}

with open("audio.mp3", "rb") as f:
    audio_b64 = base64.b64encode(f.read()).decode()

resp = requests.post(url, headers=headers, json={
    "audio": audio_b64,
    "language": "en"
}, timeout=600)

result = resp.json()
segments = result["result"]["segments"]  # [{start, end, text}, ...]
full_text = result["result"]["text"]
```

## Notes

- Auto-detects language if `language` omitted — but specifying "en" is faster for English content
- Returns both segmented and full-text output — use segments for timestamped subtitles
- VTT format included in output — can be used directly for subtitle files
- Retry on 500 errors — they're transient, not permanent

## Rate Limits (IMPORTANT)

**Free tier: 10,000 neurons/day.** Each transcription consumes neurons proportional to audio length.

- HTTP 429 with `"used up your daily free allocation of 10,000 neurons"` = daily limit hit
- For 120 videos, expect to hit the limit after ~30-40 videos (varies by length)
- **Strategy:** Only use Whisper for videos WITHOUT subtitles (~5%). Don't waste quota on videos that already have yt-dlp subtitles.
- **3Blue1Brown math/visual videos:** Many return 0 segments even when transcribed — don't retry these, they're music/visual-heavy with less spoken content.
- Wait 24 hours for the limit to reset, or upgrade to Cloudflare Workers Paid plan.
