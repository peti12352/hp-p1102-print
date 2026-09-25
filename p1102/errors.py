from __future__ import annotations

import re

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_SETUP = 2
EXIT_CONVERT = 3


def explain_print_failure(output: str, *, uri: str | None = None) -> str:
    text = output or ""
    lower = text.lower()
    hints: list[str] = []

    if "waiting for printer" in lower:
        hints.append("Printer did not respond after automatic retries. Check USB cable and paper tray")
    if "usblp" in lower or "failed to detach" in lower:
        hints.append("Kernel printer driver blocking USB: sudo modprobe -r usblp")
    if "permission denied" in lower:
        hints.append("Permission denied: printing needs sudo (see --doctor sudo check)")
    if "password" in lower and "sudo" in lower:
        hints.append("sudo password required; you will be prompted each print")
    if "timeout" in lower or "timed out" in lower:
        hints.append("USB backend timed out: replug printer, try --reset-usb, check power")
    if "no such device" in lower or "device not found" in lower:
        hints.append("USB device lost: replug cable, run print-p1102 --list-devices")
    if not hints:
        snippet = text.strip().splitlines()[-1] if text.strip() else "unknown error"
        hints = [f"Backend: {snippet[:200]}"]
    if uri:
        hints.append(f"URI: {uri}")
    hints.append("Still stuck? print-p1102 --doctor -v")
    return "\n".join(hints)


def stale_queue_hint(line: str, device_serial: str) -> str | None:
    if device_serial in line:
        return None
    if "usb://" not in line and "hp:/" not in line:
        return None
    m = re.search(r"device for (\S+):", line)
    queue = m.group(1) if m else None
    base = f"Stale CUPS queue (wrong serial): {line.strip()}"
    if queue:
        return f"{base}\n      fix: sudo lpadmin -x {queue}"
    return f"{base}\n      fix: remove stale queue in CUPS (lpadmin -x <name>)"


def conversion_error_message(ext: str) -> str:
    return (
        f"Cannot convert {ext} to PDF (no converter installed).\n"
        "  • Print PDF instead: save/export as PDF, then print-p1102 file.pdf\n"
        "  • Linux: curl install.sh | bash -s -- --with-office\n"
        "  • Or install LibreOffice: https://www.libreoffice.org/download/"
    )
