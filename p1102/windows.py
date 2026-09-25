from __future__ import annotations

import re
import subprocess
from pathlib import Path

from p1102.constants import TIMEOUT_SEC
from p1102.document import converter_status, scoped_pdf
from p1102.models import PageRange
from p1102.profile import PrinterProfile, doctor_title
from p1102 import status
from p1102.util import die, doctor_check, log, vlog, which


def _powershell(script: str, *, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
    )


def _list_printers(profile: PrinterProfile) -> list[dict[str, str]]:
    ps = r"""
    Get-Printer | ForEach-Object {
        "$($_.Name)|$($_.DriverName)|$($_.PortName)|$($_.PrinterStatus)"
    }
    """
    proc = _powershell(ps)
    out: list[dict[str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        item = {"name": parts[0], "driver": parts[1], "port": parts[2], "status": parts[3]}
        if profile.matches_windows_printer(item["name"], item["driver"]):
            out.append(item)
    return out


def _find_printer(profile: PrinterProfile, *, verbose: bool, explicit: str | None) -> str | None:
    if explicit:
        vlog(f"Using printer: {explicit}", verbose=verbose)
        return explicit
    matches = _list_printers(profile)
    if not matches:
        return None
    name = matches[0]["name"]
    vlog(f"Found printer: {name} driver={matches[0]['driver']}", verbose=verbose)
    return name


def _send_pdf(printer: str, pdf_abs: str, page_range: PageRange, verbose: bool) -> bool:
    sumatra = which("SumatraPDF") or which("SumatraPDF.exe")
    if sumatra:
        cmd = [sumatra, "-print-to", printer, "-silent"]
        if page_range.scoped():
            cmd.extend(["-print-settings", page_range.sumatra_settings()])
        cmd.append(pdf_abs)
        proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_SEC)
        if proc.returncode == 0:
            vlog("Sent via SumatraPDF", verbose=True)
            return True
        if verbose:
            err = (proc.stderr or proc.stdout or b"").decode(errors="replace")
            vlog(f"SumatraPDF failed: {err}", verbose=True)
    ps = f"""
    $p = New-Object -ComObject WScript.Shell
    $tmp = [System.IO.Path]::GetTempFileName() + '.pdf'
    Copy-Item -LiteralPath '{pdf_abs.replace("'", "''")}' -Destination $tmp
    $p.ShellExecute($tmp, 'printto', '{printer.replace("'", "''")}', '', 0)
    Start-Sleep -Seconds 5
    """
    return _powershell(ps, timeout=TIMEOUT_SEC).returncode == 0


def doctor(profile: PrinterProfile, *, printer: str | None, verbose: bool) -> int:
    log(doctor_title(profile, "Windows"))
    issues = 0
    proc = _powershell("Get-Command Get-Printer | Select-Object -ExpandProperty Source")
    issues = doctor_check(issues, proc.returncode == 0, "Print subsystem", "Start Print Spooler service")
    found = _find_printer(profile, verbose=verbose, explicit=printer)
    if found:
        log(f"OK  printer: {found}")
    else:
        fix = "Install driver and add printer, or use --printer NAME"
        if profile.windows_driver_url:
            fix = f'Install driver: curl -fL -o driver.exe "{profile.windows_driver_url}"'
        issues = doctor_check(issues, False, f"No printer for profile {profile.id!r}", fix)
    sumatra = which("SumatraPDF") or which("SumatraPDF.exe")
    if sumatra:
        log(f"OK  SumatraPDF: {sumatra}")
    else:
        log("WARN  SumatraPDF not found (winget install SumatraPDF.SumatraPDF)")
    ok, hint = converter_status()
    log(f"{'OK' if ok else 'WARN'}  converter: {hint}")
    if issues:
        log(f"Doctor: {issues} blocking issue(s).")
        return 1
    log("Doctor: ready")
    return 0


def print_pdf(
    pdf: Path,
    profile: PrinterProfile,
    *,
    copies: int,
    verbose: bool,
    dry_run: bool,
    printer: str | None,
    page_range: PageRange,
) -> None:
    if verbose:
        for p in _list_printers(profile):
            vlog(f"printer {p['name']}: {p['driver']} {p['port']}", verbose=True)
    found = _find_printer(profile, verbose=verbose, explicit=printer)
    if not found:
        fix = profile.windows_driver_url or "install driver"
        die(f"No printer for profile {profile.id!r}. Run: print-p1102 --doctor\nDriver hint: {fix}")
    log(f"Printer: {found}")
    if dry_run:
        log(f"Dry run OK (printer queue found, PDF {pdf.stat().st_size} bytes)")
        return

    sumatra = which("SumatraPDF") or which("SumatraPDF.exe")

    def send(job: Path, pr: PageRange) -> None:
        pdf_abs = str(job.resolve())
        status.preparing()
        for copy in range(copies):
            status.sending(copy + 1, copies)
            if not _send_pdf(found, pdf_abs, pr, verbose):
                die("Windows print failed. Run: print-p1102 --doctor")
        status.submitted_windows()

    if page_range.scoped() and not sumatra:
        with scoped_pdf(pdf, page_range, verbose=verbose) as sliced:
            send(sliced, PageRange.all_pages())
    else:
        send(pdf, page_range)
    status.done()
