#!/usr/bin/env python3
"""Generate embeddings for YouTube tracker topics using sentence-transformers.

Usage:
    pip install sentence-transformers
    python3 embed_topics.py

Reads topics.json, generates embeddings, saves topic_embeddings.json.
Upload topic_embeddings.json back to the server when done.
"""
import json
import sys
import time

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("Install: pip install sentence-transformers")
    sys.exit(1)

# Load topics
with open("topics.json") as f:
    topics = json.load(f)

print(f"Loaded {len(topics)} topics")

model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
print(f"Model loaded: Qwen3-Embedding-0.6B")

# Embed in batches
start = time.time()
embeddings = model.encode(topics, batch_size=64, show_progress_bar=True)
elapsed = time.time() - start

print(f"Embedded {len(topics)} topics in {elapsed:.1f}s ({len(topics)/elapsed:.0f} topics/sec)")

# Save
output = {
    "model": "Qwen3-Embedding-0.6B",
    "dimension": len(embeddings[0]),
    "topics": topics,
    "embeddings": embeddings.tolist(),
}

with open("topic_embeddings.json", "w") as f:
    json.dump(output, f)

print(f"Saved to topic_embeddings.json ({len(embeddings)} vectors, dim={len(embeddings[0])})")
print("Upload this file back to the server.")
