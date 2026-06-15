from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Callable

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def run_json(script: str, timeout: int = 120) -> Any:
    wrapped = f"$ErrorActionPreference='Stop'; {script}"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "PowerShell failed").strip()
        raise RuntimeError(err[:500])
    text = (result.stdout or "").strip()
    if not text:
        return None
    return json.loads(text)


def run_json_async(
    script: str,
    timeout: int = 90,
    on_tick: Callable[[int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Any:
    wrapped = f"$ErrorActionPreference='Stop'; {script}"
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    started = time.time()
    last_second = -1
    while proc.poll() is None:
        elapsed = int(time.time() - started)
        if is_cancelled and is_cancelled():
            proc.kill()
            proc.wait(timeout=5)
            raise InterruptedError("Operation cancelled")
        if elapsed > timeout:
            proc.kill()
            proc.wait(timeout=5)
            raise subprocess.TimeoutExpired(cmd=proc.args, timeout=timeout)
        if on_tick and elapsed != last_second:
            last_second = elapsed
            on_tick(elapsed)
        time.sleep(0.4)

    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError((stderr or stdout or "PowerShell error")[:400])
    text = (stdout or "").strip()
    return json.loads(text) if text else None
