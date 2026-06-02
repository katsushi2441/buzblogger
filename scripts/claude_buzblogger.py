#!/usr/bin/env python3
"""Ask Claude to pick the best buzz+product combo and write an article."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _find_claude_bin() -> str:
    if env := os.environ.get("CLAUDE_BIN"):
        return env
    # which claude
    r = subprocess.run(["which", "claude"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    # VS Code extension directory — pick latest version
    ext_dir = Path("/home/kojima/.vscode-server/extensions")
    candidates = sorted(ext_dir.glob("anthropic.claude-code-*/resources/native-binary/claude"), reverse=True)
    if candidates:
        return str(candidates[0])
    raise FileNotFoundError("claude binary not found. Set CLAUDE_BIN env var.")


CLAUDE_BIN = _find_claude_bin()
SKILL = ROOT / "skills" / "buzblogger" / "SKILL.md"
CANDIDATES = ROOT / "tasks" / "togetter_with_products.json"
SCHEMA = ROOT / "tasks" / "buzblog_post.schema.json"
OUT = ROOT / "tasks" / "buzblog_post.generated.json"
RAW_OUT = ROOT / "tasks" / "buzblog_post.claude_raw.json"


def compact_candidates(candidates):
    """Keep Claude input small; full product data is resolved after selection."""
    compact = []
    for candidate in candidates:
        products = []
        for product in (candidate.get("products") or [])[:6]:
            products.append({
                "id": product.get("id"),
                "name": product.get("name"),
                "maker": product.get("maker"),
                "genre": product.get("genre") or product.get("group_name"),
                "sale_price": product.get("sale_price"),
                "review_average": product.get("review_average"),
                "review_count": product.get("review_count"),
                "book_description_ai": (product.get("book_description_ai") or "")[:240],
            })
        compact.append({
            "title": candidate.get("title"),
            "url": candidate.get("url"),
            "source_tweet_url": candidate.get("source_tweet_url"),
            "point": candidate.get("point"),
            "hatebu": candidate.get("hatebu"),
            "summary": (candidate.get("summary") or candidate.get("description") or "")[:500],
            "genres": candidate.get("genres") or [],
            "products": products,
        })
    return compact


def main():
    if not CANDIDATES.exists():
        raise SystemExit(f"candidates not found: {CANDIDATES}")

    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    if not candidates:
        raise SystemExit("no candidates with products — skipping")

    candidates_text = json.dumps(compact_candidates(candidates), ensure_ascii=False, indent=2)
    prompt = f"""以下を読んで、AIxEC 商品への自然な導線になる記事を生成してください。

## 手順
1. candidates の中から、商品・書籍との関連が最も自然な1件を選ぶ
2. その候補に紐づく products リストから、記事で紹介する商品を 2〜4件選ぶ（selected_product_ids に id を入れる）
3. バズ話題を入口にして、選んだ商品を自然に紹介する考察記事を書く
4. 商品と話題がうまくつながらない場合は、最もましな候補を選んで対応する

必ず JSON のみ出力してください。Markdown や説明文は不要です。

SKILL:
{SKILL.read_text(encoding="utf-8")}

CANDIDATES_WITH_PRODUCTS:
{candidates_text}
"""

    cmd = [
        CLAUDE_BIN,
        "-p",
        "--input-format", "text",
        "--output-format", "json",
        "--json-schema", SCHEMA.read_text(encoding="utf-8"),
    ]

    MAX_ATTEMPTS = 3
    result = None
    for attempt in range(MAX_ATTEMPTS):
        result = subprocess.run(cmd, cwd=str(ROOT), input=prompt, text=True, capture_output=True, timeout=600)
        RAW_OUT.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
        if result.returncode == 0 and "error_max_structured_output_retries" not in result.stdout + result.stderr:
            break
        if attempt < MAX_ATTEMPTS - 1:
            print(f"[retry {attempt + 1}/{MAX_ATTEMPTS}] structured output failed, retrying in 15s...", file=sys.stderr)
            time.sleep(15)
        else:
            raise SystemExit(result.stderr or result.stdout)

    payload = json.loads(result.stdout)
    if isinstance(payload, dict) and isinstance(payload.get("structured_output"), dict):
        post = payload["structured_output"]
    else:
        text = payload.get("result") if isinstance(payload, dict) else payload
        post = json.loads(text) if isinstance(text, str) else text

    # selected_product_ids を使って products を解決してポストに埋め込む
    selected_ids = set(int(i) for i in (post.get("selected_product_ids") or []))
    matched_products = []
    for candidate in candidates:
        if candidate.get("url") == post.get("buzz_url"):
            for p in (candidate.get("products") or []):
                if not selected_ids or int(p["id"]) in selected_ids:
                    matched_products.append(p)
            break

    # フォールバック: buzz_url が一致しない場合は全候補から探す
    if not matched_products and selected_ids:
        for candidate in candidates:
            for p in (candidate.get("products") or []):
                if int(p["id"]) in selected_ids:
                    matched_products.append(p)

    post["resolved_products"] = matched_products

    # source_tweet_url を候補データから引き継ぐ
    for candidate in candidates:
        if candidate.get("url") == post.get("buzz_url"):
            post["source_tweet_url"] = candidate.get("source_tweet_url", "")
            break

    OUT.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)
    print(f"title: {post.get('title')}")
    print(f"buzz_url: {post.get('buzz_url')}")
    print(f"products: {[p['name'][:30] for p in matched_products]}")


if __name__ == "__main__":
    main()
