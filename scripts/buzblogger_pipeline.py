#!/usr/bin/env python3
"""buzblogger pipeline: fetch Togetter → Claude analysis → AIxSNS post."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "storage" / "buzblogger.lock"
LOG = ROOT / "storage" / "autonomous" / "buzblogger.log"
WORKER_REPORT_API = os.environ.get("WORKER_REPORT_API", "https://aixec.exbridge.jp/api.php?path=worker/report")
FIND_PRODUCTS_TIMEOUT = int(os.environ.get("BUZBLOGGER_FIND_PRODUCTS_TIMEOUT", "180"))
CLAUDE_TIMEOUT = int(os.environ.get("BUZBLOGGER_CLAUDE_TIMEOUT", "600"))
POST_TIMEOUT = int(os.environ.get("BUZBLOGGER_POST_TIMEOUT", "120"))


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd: list[str], timeout=None):
    log("run: " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
    if result.stdout:
        log("stdout:\n" + result.stdout[-4000:])
    if result.stderr:
        log("stderr:\n" + result.stderr[-2000:])
    if result.returncode != 0:
        raise RuntimeError("failed: " + " ".join(cmd))


def report_worker(status: str = "ok", items: int = 0, note: str = ""):
    payload = json.dumps({
        "name": "buzblogger-enqueue",
        "status": status,
        "items": items,
        "note": note[:200],
    }, ensure_ascii=False).encode("utf-8")
    req = Request(
        WORKER_REPORT_API,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "buzblogger/1.0"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as res:
            res.read()
        log(f"worker report: {status} items={items} note={note}")
    except Exception as exc:
        log(f"worker report failed: {exc}")


def acquire():
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)
            raise SystemExit("buzblogger already running pid=%s" % pid)
        except (ProcessLookupError, ValueError):
            pass
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")


def release():
    try:
        if LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK.unlink()
    except FileNotFoundError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="SNS投稿しない")
    parser.add_argument("--skip-claude", action="store_true", help="既存の buzblog_post.generated.json を再利用")
    args = parser.parse_args()

    acquire()
    try:
        log("pipeline start dry_run=%s" % args.dry_run)

        run([sys.executable, "scripts/fetch_togetter.py"], timeout=60)

        candidates_file = ROOT / "tasks" / "togetter_candidates.json"
        if not candidates_file.exists():
            raise RuntimeError("togetter_candidates.json not found")

        import json
        candidates = json.loads(candidates_file.read_text(encoding="utf-8"))
        if not candidates:
            log("no new candidates — skipping")
            report_worker("ok", 0, "候補なしでスキップ")
            return

        run([sys.executable, "scripts/find_related_products.py"], timeout=FIND_PRODUCTS_TIMEOUT)

        with_products_file = ROOT / "tasks" / "togetter_with_products.json"
        if not with_products_file.exists():
            raise RuntimeError("togetter_with_products.json not found")
        with_products = json.loads(with_products_file.read_text(encoding="utf-8"))
        if not with_products:
            log("no candidates found — skipping")
            report_worker("ok", 0, "関連商品0件でスキップ")
            return

        if not args.skip_claude:
            run([sys.executable, "scripts/claude_buzblogger.py"], timeout=CLAUDE_TIMEOUT)

        post_cmd = [sys.executable, "scripts/post_buzblog.py"]
        if args.dry_run:
            post_cmd.append("--dry-run")
        run(post_cmd, timeout=POST_TIMEOUT)

        if args.dry_run:
            report_worker("ok", 0, f"dry-run完了 候補{len(with_products)}件")
        else:
            report_worker("ok", len(with_products), f"投稿完了 候補{len(with_products)}件")
        log("pipeline complete")
    except Exception as exc:
        report_worker("down", 0, f"エラー: {exc}")
        raise
    finally:
        release()


if __name__ == "__main__":
    main()
