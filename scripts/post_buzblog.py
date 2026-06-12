#!/usr/bin/env python3
"""Build and post AIxSNS article from Claude output (products already resolved)."""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
POST_FILE = ROOT / "tasks" / "buzblog_post.generated.json"
POSTED = ROOT / "storage" / "posted_urls.txt"


def post_to_sns(content: str) -> dict:
    payload = json.dumps({"author": "buzblogger", "content": content}, ensure_ascii=False).encode("utf-8")
    req = Request(
        os.environ.get("AIXSNS_API", "http://127.0.0.1:8081/posts"),
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "buzblogger/1.0"},
        method="POST",
    )
    with urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def post_via_email(title: str, body: str, to_addr: str) -> bool:
    smtp_host = os.environ.get("SMTP_HOST", "mail18.heteml.jp")
    smtp_port = int(os.environ.get("SMTP_PORT", 465))
    smtp_from = os.environ.get("SMTP_FROM", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    if not all([smtp_from, smtp_pass, to_addr]):
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = title
    msg["From"] = smtp_from
    msg["To"] = to_addr
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as s:
        s.login(smtp_from, smtp_pass)
        s.sendmail(smtp_from, [to_addr], msg.as_bytes())
    return True


def mark_posted(url: str):
    POSTED.parent.mkdir(parents=True, exist_ok=True)
    with POSTED.open("a", encoding="utf-8") as fh:
        fh.write(url.strip() + "\n")


def build_content(post: dict, dry_run: bool = False) -> str:
    search_query = (post.get("search_query") or "").strip()
    title = search_query or post.get("title", "")
    article = post.get("article", "")
    buzz_url = post.get("buzz_url", "")
    products = post.get("resolved_products") or []

    lines = [f"【{title}】", "", article, ""]

    if products:
        lines.append("■ 関連商品・書籍")
        for p in products[:4]:
            name = p.get("name", "")
            go_url = p.get("go_url", "")
            short = name[:40] + ("…" if len(name) > 40 else "")
            lines.append(f"・{short}")
            if go_url:
                lines.append(go_url)
        lines.append("")

    cta = post.get("cta", "")
    if cta:
        lines += [cta, ""]

    source_tweet_url = post.get("source_tweet_url", "")
    ref_url = source_tweet_url or buzz_url
    buzz_summary = (post.get("buzz_summary") or "").strip()
    if buzz_summary:
        lines += ["参考：この話題が注目された背景", buzz_summary, ""]
    if ref_url:
        lines.append(f"元記事：{ref_url}")

    if dry_run:
        lines += ["", "[DRY RUN]"]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not POST_FILE.exists():
        raise SystemExit(f"not found: {POST_FILE}")

    post = json.loads(POST_FILE.read_text(encoding="utf-8"))
    products = post.get("resolved_products") or []
    print(f"title: {post.get('title')}")
    print(f"products: {len(products)}件")

    content = build_content(post, dry_run=args.dry_run)
    print("--- preview ---")
    print(content[:800])
    print("---")

    if args.dry_run:
        print("dry-run: skipped")
        return

    res = post_to_sns(content)
    post_id = res.get("item", {}).get("id")
    print(f"AIxSNS posted id={post_id}")
    print(f"https://aixec.exbridge.jp/sns.php?id={post_id}")

    title = post.get("title", "")
    if title:
        hatena = os.environ.get("HATENA_POST_EMAIL", "")
        blogger = os.environ.get("BLOGGER_POST_EMAIL", "")
        if hatena:
            ok = post_via_email(title, content, hatena)
            print(f"はてなブログ投稿: {'ok' if ok else 'skipped'}")
        # Blogger投稿は無効化
        # if blogger:
        #     ok = post_via_email(title, content, blogger)
        #     print(f"Blogger投稿: {'ok' if ok else 'skipped'}")

    buzz_url = post.get("buzz_url", "")
    if buzz_url:
        mark_posted(buzz_url)


if __name__ == "__main__":
    main()
