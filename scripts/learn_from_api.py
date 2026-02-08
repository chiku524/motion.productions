#!/usr/bin/env python3
"""
Learning pipeline: fetches events, feedback, and learning runs from the API,
correlates user interactions with outputs, and produces suggestions for improving
keywords, palettes, and intensity. Run periodically to tune the procedural engine.

Usage:
  python scripts/learn_from_api.py
  python scripts/learn_from_api.py --api-base https://motion.productions
  python scripts/learn_from_api.py --json   # machine-readable output
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from urllib.request import Request, urlopen


def fetch_json(api_base: str, path: str) -> dict:
    url = f"{api_base.rstrip('/')}{path}"
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req) as resp:
        return json.loads(resp.read().decode())


def words(prompt: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (prompt or "").lower()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch interaction data from API and produce learning suggestions."
    )
    parser.add_argument("--api-base", default="https://motion.productions", help="API base URL")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    try:
        events_data = fetch_json(args.api_base, "/api/events?limit=500")
        feedback_data = fetch_json(args.api_base, "/api/feedback?limit=500")
        stats_data = fetch_json(args.api_base, "/api/learning/stats")
    except Exception as e:
        print(f"Error fetching from API: {e}", file=sys.stderr)
        sys.exit(1)

    events = events_data.get("events", [])
    feedback_list = feedback_data.get("feedback", [])
    stats = stats_data

    # Build job_id -> feedback
    job_feedback: dict[str, int] = {f["job_id"]: f["rating"] for f in feedback_list}

    # Correlate events with jobs: which jobs got played, downloaded, thumbs up/down
    job_events: dict[str, list[str]] = defaultdict(list)
    job_prompts: dict[str, str] = {}
    for e in events:
        jid = e.get("job_id")
        if jid:
            job_events[jid].append(e["event_type"])
        if e["event_type"] == "prompt_submitted" and e.get("payload", {}).get("prompt"):
            job_prompts[jid or ""] = e["payload"]["prompt"]

    # Aggregate: prompts/keywords that led to good vs bad outcomes
    thumbs_up_keywords: defaultdict[str, int] = defaultdict(int)
    thumbs_down_keywords: defaultdict[str, int] = defaultdict(int)
    played_keywords: defaultdict[str, int] = defaultdict(int)
    downloaded_keywords: defaultdict[str, int] = defaultdict(int)

    for fb in feedback_list:
        jid = fb["job_id"]
        prompt = fb.get("prompt", "")
        for w in words(prompt):
            if fb["rating"] == 2:
                thumbs_up_keywords[w] += 1
            else:
                thumbs_down_keywords[w] += 1

    for e in events:
        if e["event_type"] == "video_played":
            jid = e.get("job_id")
            prompt = job_prompts.get(jid or "", "")
            for w in words(prompt):
                played_keywords[w] += 1
        elif e["event_type"] == "download_clicked":
            jid = e.get("job_id")
            prompt = job_prompts.get(jid or "", "")
            for w in words(prompt):
                downloaded_keywords[w] += 1

    # Suggestions from stats (learning runs)
    suggestions: list[dict] = []
    by_keyword = stats.get("by_keyword", {})
    MOTION_LOW, MOTION_HIGH = 2.0, 15.0
    for kw, data in by_keyword.items():
        if data.get("count", 0) < 2:
            continue
        mean_motion = data.get("mean_motion_level", 0)
        if mean_motion < MOTION_LOW:
            suggestions.append({
                "type": "intensity",
                "keyword": kw,
                "reason": f"low_motion ({mean_motion:.2f})",
                "action": "Consider increasing intensity in data/keywords.py",
            })
        elif mean_motion > MOTION_HIGH:
            suggestions.append({
                "type": "intensity",
                "keyword": kw,
                "reason": f"high_motion ({mean_motion:.2f})",
                "action": "Consider decreasing intensity",
            })

    # Event-driven: keywords with many thumbs down → flag for review
    for kw, count in thumbs_down_keywords.items():
        up = thumbs_up_keywords.get(kw, 0)
        total = up + count
        if total >= 2 and count > up:
            suggestions.append({
                "type": "review_keyword",
                "keyword": kw,
                "reason": f"thumbs_down ({count}) > thumbs_up ({up})",
                "action": "Review palette/motion mapping for this keyword",
            })

    report = {
        "events_count": len(events),
        "feedback_count": len(feedback_list),
        "learning_runs": stats.get("total_runs", 0),
        "thumbs_up_keywords": dict(thumbs_up_keywords),
        "thumbs_down_keywords": dict(thumbs_down_keywords),
        "suggestions": suggestions,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return

    # Human-readable
    print("=== Motion Learning Report ===\n")
    print(f"Events: {report['events_count']}")
    print(f"Feedback: {report['feedback_count']}")
    print(f"Learning runs: {report['learning_runs']}\n")
    print("--- Suggestions ---")
    for s in suggestions:
        print(f"  [{s['type']}] {s.get('keyword', s.get('palette', '?'))}: {s['reason']}")
        print(f"    → {s['action']}\n")
    if not suggestions:
        print("  No suggestions yet. Keep generating and providing feedback!\n")


if __name__ == "__main__":
    main()
