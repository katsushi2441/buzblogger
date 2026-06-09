#!/usr/bin/env python3
"""Ask Claude to pick the best buzz+product combo and write an article."""
from __future__ import annotations

import json
import os
import re
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
OLLAMA_API = os.environ.get("BUZBLOGGER_OLLAMA_API", os.environ.get("OLLAMA_API", "https://exbridge.ddns.net/api/generate"))
OLLAMA_MODEL = os.environ.get("BUZBLOGGER_OLLAMA_MODEL", os.environ.get("OLLAMA_MODEL", "gemma4:e4b"))
OLLAMA_TIMEOUT = int(os.environ.get("BUZBLOGGER_OLLAMA_TIMEOUT", "180"))
CLAUDE_MODEL = os.environ.get("BUZBLOGGER_CLAUDE_MODEL", os.environ.get("CLAUDE_MODEL", "haiku"))
CODEX_MODEL = os.environ.get("BUZBLOGGER_CODEX_MODEL", os.environ.get("CODEX_MODEL", "gpt-5.5"))
CODEX_TIMEOUT = int(os.environ.get("BUZBLOGGER_CODEX_TIMEOUT", "240"))


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


def _extract_json(text: str):
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model output")
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if match:
        return json.loads(match.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("json object not found")


def run_ollama(prompt: str) -> dict:
    fallback_prompt = prompt + """

重要:
- 必ずJSONオブジェクトのみを返す
- required: title, buzz_url, buzz_summary, genres, article, product_keywords
- selected_product_ids は candidates 内の products[].id から2〜4件
- hashtags は配列
- cta は1行
"""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": fallback_prompt,
        "stream": False,
        "format": "json",
    }, ensure_ascii=False)
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "--max-time",
            str(OLLAMA_TIMEOUT),
            OLLAMA_API,
            "-H",
            "Content-Type: application/json",
            "-d",
            payload,
        ],
        capture_output=True,
        text=True,
        timeout=OLLAMA_TIMEOUT + 20,
    )
    RAW_OUT.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"ollama failed returncode={result.returncode}: {result.stderr[:500]}")
    data = json.loads(result.stdout)
    response = data.get("response", "")
    return _extract_json(response)


def _find_codex_bin() -> str:
    r = subprocess.run(["which", "codex"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    candidate = Path("/home/kojima/.vscode-server/extensions/openai.chatgpt-26.513.21555-linux-x64/bin/linux-x86_64/codex")
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError("codex binary not found")


def run_codex(prompt: str) -> dict:
    codex_prompt = prompt + """

必ずJSONオブジェクトのみで返してください。説明文、Markdown、コードフェンスは禁止です。
"""
    result = subprocess.run(
        [
            _find_codex_bin(),
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            CODEX_MODEL,
            "--cd",
            str(ROOT),
            codex_prompt,
        ],
        capture_output=True,
        text=True,
        timeout=CODEX_TIMEOUT,
    )
    RAW_OUT.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"codex failed returncode={result.returncode}: {(result.stderr or result.stdout)[:500]}")
    return _extract_json(result.stdout)


def build_rule_based_post(candidates: list[dict]) -> dict:
    def candidate_score(candidate: dict) -> tuple:
        products = candidate.get("products") or []
        genres = [g for g in (candidate.get("genres") or []) if g and g != "人気書籍"]
        product_names = " ".join(str(p.get("name", "")) for p in products[:4])
        generic_penalty = product_names.count("歯ブラシ") + product_names.count("送料無料")
        return (1 if products else 0, len(genres), int(candidate.get("point") or 0), -generic_penalty)

    candidate = max(candidates, key=candidate_score) if candidates else {}
    products = (candidate.get("products") or [])[:4]
    title = (candidate.get("title") or "話題の商品・書籍を考える").strip()
    short_title = re.sub(r"\s+", " ", title)
    short_title = re.split(r"[。！？!?]", short_title)[0].strip()
    if len(short_title) > 34:
        short_title = short_title[:34] + "…"
    summary = (candidate.get("summary") or candidate.get("description") or title).strip()
    genres = candidate.get("genres") or []
    if not genres:
        genres = ["人気書籍"]
    selected_ids = [int(p["id"]) for p in products if p.get("id")][:4]
    product_names = [p.get("name", "") for p in products if p.get("name")]
    product_keywords = sorted({g for g in genres if g} | {"話題", "商品", "書籍"})
    product_line = "、".join(name[:28] for name in product_names[:2]) if product_names else "関連商品"
    article = (
        f"SNSで話題になっている「{title}」は、単なる一過性のネタではなく、"
        "生活者の関心や購買行動がどこに向いているかを読む材料になる。\n\n"
        f"話題の要点は、{summary[:220]}。こうした反応が集まる背景には、"
        "日常の違和感、学び、消費体験への共感がある。AIxECの視点では、"
        "バズを入口にして関連する商品や書籍を見つけることで、検索だけでは拾いにくい需要を発見できる。\n\n"
        f"今回の関連候補としては、{product_line} などがある。"
        "話題を読んで終わりにせず、そこから学びや買い物のヒントへつなげることが、"
        "バズ活用の実用的な使い方だ。"
    )
    return {
        "title": f"{short_title}から考える、今チェックしたい関連商品",
        "buzz_url": candidate.get("url") or "",
        "buzz_summary": summary[:320],
        "genres": genres,
        "article": article,
        "selected_product_ids": selected_ids,
        "hashtags": ["AIxEC", "バズ", "商品紹介"],
        "cta": "AIxECで話題に関連する商品・書籍をチェックしてみよう。",
        "product_keywords": json.dumps(product_keywords, ensure_ascii=False),
    }


def is_valid_post(post: dict) -> bool:
    required = ["title", "buzz_url", "buzz_summary", "genres", "article", "product_keywords"]
    return isinstance(post, dict) and all(post.get(k) for k in required)


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
        "--model",
        CLAUDE_MODEL,
    ]

    MAX_ATTEMPTS = 3
    result = None
    claude_error = ""
    for attempt in range(MAX_ATTEMPTS):
        result = subprocess.run(cmd, cwd=str(ROOT), input=prompt, text=True, capture_output=True, timeout=600)
        RAW_OUT.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
        if result.returncode == 0 and "error_max_structured_output_retries" not in result.stdout + result.stderr:
            break
        claude_error = result.stderr or result.stdout
        if attempt < MAX_ATTEMPTS - 1:
            print(f"[retry {attempt + 1}/{MAX_ATTEMPTS}] structured output failed, retrying in 15s...", file=sys.stderr)
            time.sleep(15)
        else:
            if "session limit" in claude_error.lower() or "api_error_status\":429" in claude_error:
                print("[fallback] Claude limit reached; using Codex", file=sys.stderr)
                try:
                    post = run_codex(prompt)
                except Exception as exc:
                    print(f"[fallback] Codex failed: {exc}; using Ollama", file=sys.stderr)
                    try:
                        post = run_ollama(prompt)
                    except Exception as ollama_exc:
                        print(f"[fallback] Ollama failed: {ollama_exc}; using rule-based generator", file=sys.stderr)
                        post = build_rule_based_post(candidates)
                if not is_valid_post(post):
                    print("[fallback] fallback model returned invalid post; using rule-based generator", file=sys.stderr)
                    try:
                        post = run_ollama(prompt)
                    except Exception:
                        post = build_rule_based_post(candidates)
                    if not is_valid_post(post):
                        post = build_rule_based_post(candidates)
                break
            raise SystemExit(result.stderr or result.stdout)

    if "post" not in locals():
        payload = json.loads(result.stdout)
        if isinstance(payload, dict) and isinstance(payload.get("structured_output"), dict):
            post = payload["structured_output"]
        else:
            text = payload.get("result") if isinstance(payload, dict) else payload
            post = json.loads(text) if isinstance(text, str) else text

    if not is_valid_post(post):
        print("[fallback] model returned invalid post; using rule-based generator", file=sys.stderr)
        post = build_rule_based_post(candidates)

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
