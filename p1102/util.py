from __future__ import annotations

import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def vlog(msg: str, *, verbose: bool) -> None:
    if verbose:
        print(f"[debug] {msg}", flush=True)


def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"WARN: {msg}", flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def sudo_passwordless() -> bool:
    proc = run(["sudo", "-n", "true"], check=False)
    return proc.returncode == 0


def doctor_check(issues: int, ok: bool, msg: str, fix: str = "") -> int:
    if ok:
        log(f"OK  {msg}")
    else:
        log(f"FAIL  {msg}")
        if fix:
            log(f"      fix: {fix}")
        issues += 1
    return issues


@lru_cache(maxsize=32)
def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run(
    cmd: list[str],
    *,
    input_data: bytes | None = None,
    timeout: int | None = None,
    check: bool = True,
    verbose: bool = False,
    text: bool = False,
) -> subprocess.CompletedProcess:
    if verbose:
        vlog(f"$ {' '.join(cmd)}", verbose=True)
    return subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        timeout=timeout,
        check=check,
        text=text,
    )


def sudo(
    cmd: list[str],
    *,
    input_data: bytes | None = None,
    verbose: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    return run(
        ["sudo"] + cmd,
        input_data=input_data,
        verbose=verbose,
        check=False,
        timeout=timeout,
    )


def sudo_write_sys(path: Path, value: str, *, verbose: bool) -> bool:
    proc = sudo(["tee", str(path)], input_data=(value + "\n").encode(), verbose=verbose)
    if proc.returncode != 0:
        warn(f"Could not write {value!r} to {path}: {proc.stderr.decode(errors='replace').strip()}")
        return False
    return True
