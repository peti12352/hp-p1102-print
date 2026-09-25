from __future__ import annotations

import re
import subprocess

from p1102.constants import TIMEOUT_SEC
from p1102.models import PageRange
from p1102.profile import PrinterProfile
from p1102 import status
from p1102.util import die, log, vlog


def list_cups_printers(profile: PrinterProfile) -> list[dict[str, str]]:
    printers: list[dict[str, str]] = []
    proc = subprocess.run(["lpstat", "-p"], capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if not line.startswith("printer "):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1]
        if not profile.matches_cups_queue(name):
            continue
        printers.append({"queue": name, "status": line, "uri": ""})
    proc_v = subprocess.run(["lpstat", "-v"], capture_output=True, text=True)
    uri_map: dict[str, str] = {}
    for line in proc_v.stdout.splitlines():
        if "device for" in line:
            m = re.match(r"device for (\S+):\s*(.+)", line)
            if m:
                uri_map[m.group(1)] = m.group(2).strip()
    for p in printers:
        p["uri"] = uri_map.get(p["queue"], "")
    return printers


def find_cups_queue(profile: PrinterProfile, *, verbose: bool, explicit: str | None) -> str | None:
    if explicit:
        vlog(f"Using printer queue: {explicit}", verbose=verbose)
        return explicit
    printers = list_cups_printers(profile)
    if printers:
        q = printers[0]["queue"]
        vlog(f"CUPS queue: {q} uri={printers[0].get('uri', '')}", verbose=verbose)
        return q
    proc = subprocess.run(["lpinfo", "-v"], capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("direct ") and profile.matches_lpinfo_line(line):
            vlog(f"lpinfo: {line}", verbose=verbose)
            return line.split()[1]
    return None


def print_via_lp(
    pdf,
    queue: str,
    *,
    copies: int,
    verbose: bool,
    dry_run: bool,
    page_range: PageRange,
) -> None:
    log(f"Printer queue: {queue}")
    if dry_run:
        log(f"Dry run OK: PDF {pdf.stat().st_size} bytes")
        return
    status.preparing()
    for copy in range(copies):
        status.sending(copy + 1, copies)
        lp_cmd = ["lp", "-d", queue, "-o", "media=A4", "-o", "sides=one-sided", "-n", "1"]
        if page_range.scoped():
            lp_cmd.extend(["-o", f"page-ranges={page_range.cups_value()}"])
        lp_cmd.append(str(pdf))
        proc = subprocess.run(lp_cmd, capture_output=True, text=True, timeout=TIMEOUT_SEC)
        if verbose:
            if proc.stdout:
                vlog(proc.stdout, verbose=True)
            if proc.stderr:
                vlog(proc.stderr, verbose=True)
        if proc.returncode != 0:
            die(f"lp failed: {proc.stderr or proc.stdout}")
    status.submitted_queue(queue)
    status.done()
