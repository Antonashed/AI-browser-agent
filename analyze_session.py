"""Quick analysis of agent session tool call patterns."""
import json
import sys
from collections import Counter

lines = open("data/agent_log.jsonl", encoding="utf-8").readlines()
sid = "c7c10a07-0a7a-485d-8853-c5efa8de6386"
entries = [json.loads(l) for l in lines if sid in l]

if not entries:
    print("No entries found for session", sid)
    sys.exit(0)

print(f"Total entries: {len(entries)}")

# Count URL navigations
nav_urls = Counter()
for e in entries:
    if e["tool"] == "browser_navigate":
        url = e["args"].get("url", "")
        # Normalize: strip query params for counting
        base = url.split("?")[0]
        nav_urls[base] += 1

print("\n=== Navigation URL counts (base) ===")
for url, count in nav_urls.most_common(20):
    print(f"  {count:3d}x  {url}")

# Count recall keys
recall_keys = Counter()
for e in entries:
    if e["tool"] == "recall":
        recall_keys[e["args"].get("key", "")] += 1

print("\n=== Recall key counts ===")
for key, count in recall_keys.most_common(20):
    print(f"  {count:3d}x  {key}")

# Tool sequence pattern: find repeating 3-grams
tools_seq = [e["tool"] for e in entries]
trigrams = Counter()
for i in range(len(tools_seq) - 2):
    tri = f"{tools_seq[i]} -> {tools_seq[i+1]} -> {tools_seq[i+2]}"
    trigrams[tri] += 1

print("\n=== Most common 3-step patterns ===")
for pattern, count in trigrams.most_common(10):
    if count >= 2:
        print(f"  {count:3d}x  {pattern}")

# Steps 94-end
print("\n=== Steps 94+ ===")
for e in entries:
    if e["step"] >= 94:
        args_short = str(e["args"])[:80]
        print(f"Step {e['step']:3d}: {e['tool']:25s} {args_short}")
