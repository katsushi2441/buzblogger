from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_PROJECT_DIR = "/home/kojima/work/buzblogger"
DEFAULT_PIPELINE = "scripts/buzblogger_pipeline.py"
DEFAULT_TIMEOUT = 900


def _tail(value: str, limit: int = 4000) -> str:
    if not value:
        return ""
    return value[-limit:]


def worker_auto_cycle_job(dry_run: bool = False, **_meta: Any) -> dict[str, Any]:
    """Run the existing buzblogger pipeline from an RQDB4AI worker."""
    project_dir = Path(os.environ.get("BUZBLOGGER_DIR", DEFAULT_PROJECT_DIR)).expanduser()
    pipeline = os.environ.get("BUZBLOGGER_PIPELINE", DEFAULT_PIPELINE)
    timeout = int(os.environ.get("BUZBLOGGER_JOB_TIMEOUT", str(DEFAULT_TIMEOUT)))

    if not project_dir.is_dir():
        raise RuntimeError(f"buzblogger project directory not found: {project_dir}")

    pipeline_path = project_dir / pipeline
    if not pipeline_path.is_file():
        raise RuntimeError(f"buzblogger pipeline not found: {pipeline_path}")

    command = ["python3", pipeline]
    if dry_run:
        command.append("--dry-run")

    env = os.environ.copy()
    claude_bin = _meta.get("CLAUDE_BIN") or _meta.get("claude_bin")
    if claude_bin:
        env["CLAUDE_BIN"] = str(claude_bin)

    started_at = dt.datetime.now(dt.timezone.utc)
    result = subprocess.run(
        command,
        cwd=str(project_dir),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    finished_at = dt.datetime.now(dt.timezone.utc)

    response = {
        "created_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "dry_run": bool(dry_run),
        "cwd": str(project_dir),
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }

    if result.returncode != 0 and "already running" in (result.stderr or "").lower():
        response["status"] = "skipped"
        response["reason"] = "already_running"
        return response

    if result.returncode != 0:
        raise RuntimeError(
            "buzblogger pipeline failed "
            f"returncode={result.returncode}\n"
            f"stdout tail:\n{response['stdout_tail']}\n"
            f"stderr tail:\n{response['stderr_tail']}"
        )

    return response
