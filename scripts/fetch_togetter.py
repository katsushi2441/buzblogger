#!/usr/bin/env python3
"""Scrape Togetter trending posts via embedded JSON and output candidates."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tasks" / "togetter_candidates.json"
POSTED = ROOT / "storage" / "posted_urls.txt"

MIN_POINT = 50
MAX_CANDIDATES = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
}


def load_posted() -> set:
    if not POSTED.exists():
        return set()
    return set(line.strip() for line in POSTED.read_text(encoding="utf-8").splitlines() if line.strip())


def fetch_html(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as res:
        return res.read().decode("utf-8", errors="ignore")


def extract_json_url(html: str) -> str | None:
    m = re.search(r"(https://s\.tgstc\.com/static/web/api/[^\"]+json\.pc\.\d+\.js)", html)
    return m.group(1) if m else None


def fetch_matomes(json_url: str) -> list[dict]:
    req = Request(json_url, headers={"User-Agent": HEADERS["User-Agent"]})
    with urlopen(req, timeout=20) as res:
        js = res.read().decode("utf-8", errors="ignore")

    m = re.search(r'"recent-popular-matomes-initial-state"\s*:\s*"((?:[^"\\]|\\.)*)"', js)
    if not m:
        return []

    raw = m.group(1).replace('\\"', '"').replace("\\/", "/")
    try:
        data = json.loads(raw)
    except Exception:
        return []

    return data.get("matomeSlims", [])


def fetch_source_tweet_url(togetter_url: str) -> str:
    try:
        html = fetch_html(togetter_url)
        m = re.search(r'https://x\.com/\w+/status/\d+', html)
        return m.group(0) if m else ""
    except Exception:
        return ""


def main():
    posted = load_posted()

    html = fetch_html("https://togetter.com/")
    json_url = extract_json_url(html)
    if not json_url:
        print("ERROR: JSON URL not found in Togetter HTML")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("[]", encoding="utf-8")
        return

    matomes = fetch_matomes(json_url)
    if not matomes:
        print("ERROR: no matomes found")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("[]", encoding="utf-8")
        return

    candidates = []
    for item in matomes:
        url = item.get("url", "").replace("\\/", "/")
        title = item.get("title", "")
        point = int(item.get("point") or 0)
        hatena = int(item.get("hatebuCount") or 0)
        tweet = int(item.get("tweetCount") or 0)
        views = int(item.get("viewCount") or 0)
        is_promo = bool(item.get("isPromo"))

        if not url or not title:
            continue
        if is_promo:
            continue
        if url in posted:
            continue
        if point < MIN_POINT and hatena < 30 and tweet < 30:
            continue

        candidates.append({
            "url": url,
            "title": title,
            "point": point,
            "hatebu": hatena,
            "tweet": tweet,
            "views": views,
            "comments": point,  # point をコメント数の代替として使用
        })

    # point 降順でソートしてから上位10件に絞る
    candidates.sort(key=lambda x: x["point"], reverse=True)
    candidates = candidates[:MAX_CANDIDATES]

    # 元ツイートURL取得（上位10件）
    for c in candidates:
        src = fetch_source_tweet_url(c["url"])
        c["source_tweet_url"] = src
        if src:
            print(f"  source: {src}")
        time.sleep(0.3)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"candidates: {len(candidates)}")
    for item in candidates:
        print(f"  [point={item['point']} hatebu={item['hatebu']}] {item['title'][:60]}")
    print(OUT)


if __name__ == "__main__":
    main()
