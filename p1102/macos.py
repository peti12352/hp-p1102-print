from __future__ import annotations

from p1102.cups_queue import find_cups_queue, list_cups_printers, print_via_lp
from p1102.document import converter_status
from p1102.profile import PrinterProfile, doctor_title
from p1102.util import die, doctor_check, log, vlog, which


def doctor(profile: PrinterProfile, *, printer: str | None, verbose: bool) -> int:
    log(doctor_title(profile, "macOS"))
    issues = 0
    for cmd in ("lpstat", "lp"):
        path = which(cmd)
        issues = doctor_check(issues, bool(path), f"{cmd}: {path or 'missing'}", "macOS printing tools")
    healthy = [
        p for p in list_cups_printers(profile)
        if "disabled" not in p["status"].lower() and "unplugged" not in p["status"].lower()
    ]
    if printer:
        log(f"OK  queue (explicit): {printer}")
    elif healthy:
        for p in healthy:
            log(f"OK  queue {p['queue']}: {p['uri'] or 'USB'}")
    else:
        issues = doctor_check(
            issues, False, f"No healthy CUPS queue for profile {profile.id!r}",
            "Add USB printer in System Settings, or set match.cups_queue in profile / use --printer",
        )
    ok, hint = converter_status()
    log(f"{'OK' if ok else 'WARN'}  converter: {hint}")
    if issues:
        log(f"Doctor: {issues} blocking issue(s).")
        return 1
    log("Doctor: ready")
    return 0


def print_pdf(
    pdf,
    profile: PrinterProfile,
    *,
    copies: int,
    verbose: bool,
    dry_run: bool,
    printer: str | None,
    page_range,
) -> None:
    if verbose:
        for p in list_cups_printers(profile):
            vlog(f"queue {p['queue']}: {p['uri']}", verbose=True)
    queue = find_cups_queue(profile, verbose=verbose, explicit=printer)
    if not queue:
        die(f"No CUPS queue for profile {profile.id!r}. Run: print-p1102 --doctor")
    print_via_lp(pdf, queue, copies=copies, verbose=verbose, dry_run=dry_run, page_range=page_range)
