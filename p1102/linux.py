from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from p1102.constants import CUPS_USB_BACKENDS, MAX_RETRIES, RETRY_DELAY_SEC, TIMEOUT_SEC
from p1102.cups_queue import find_cups_queue, list_cups_printers, print_via_lp
from p1102.document import converter_status, render_pdf_to_zjs, write_blank_pdf
from p1102 import status
from p1102.errors import EXIT_SETUP, explain_print_failure, stale_queue_hint
from p1102.models import PageRange, UsbPrinter
from p1102.profile import PrinterProfile, doctor_title
from p1102.util import die, log, run, sudo, sudo_passwordless, sudo_write_sys, vlog, which

_BACKEND_URIS: dict[str, str] | None = None


def parse_backend_uris(text: str) -> dict[str, str]:
    uris: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("direct usb://"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        uri = parts[1]
        m = re.search(r"serial=([^?&\s\"]+)", uri)
        if m:
            uris[m.group(1)] = uri
    return uris


def cups_uri_for_serial(serial: str, uris: dict[str, str]) -> str | None:
    if serial in uris:
        return uris[serial]
    for key, uri in uris.items():
        if key.endswith(serial) or serial.endswith(key):
            return uri
    return None


def clear_backend_uri_cache() -> None:
    global _BACKEND_URIS
    _BACKEND_URIS = None


def _read_sysfs(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _usb_bus_dev(sysfs_name: str) -> str | None:
    d = _read_sysfs(Path(f"/sys/bus/usb/devices/{sysfs_name}/devnum"))
    b = _read_sysfs(Path(f"/sys/bus/usb/devices/{sysfs_name}/busnum"))
    if d and b:
        return f"{int(b):03d}:{int(d):03d}"
    return None


def find_devices(profile: PrinterProfile, verbose: bool = False) -> list[UsbPrinter]:
    sysfs = Path("/sys/bus/usb/devices")
    if not sysfs.is_dir() or not profile.usb_vendor:
        return []
    vendor = profile.usb_vendor
    known = profile.usb_products
    devices: list[UsbPrinter] = []
    for dev in sorted(sysfs.iterdir()):
        dev_vendor = _read_sysfs(dev / "idVendor")
        product = _read_sysfs(dev / "idProduct")
        if dev_vendor != vendor or not product or product not in known:
            continue
        serial = _read_sysfs(dev / "serial") or "(no serial)"
        product_name = _read_sysfs(dev / "product") or known[product].name
        driver_link = dev / "driver"
        driver = driver_link.resolve().name if driver_link.is_symlink() else None
        item = UsbPrinter(
            sysfs=dev.name, vendor=dev_vendor, product=product, serial=serial,
            product_name=product_name, driver=driver, bus_dev=_usb_bus_dev(dev.name),
        )
        devices.append(item)
        vlog(
            f"USB {item.bus_dev or item.sysfs}: {product_name} "
            f"pid={product} serial={serial} driver={driver or 'none'}",
            verbose=verbose,
        )
    return devices


def select_device(
    devices: list[UsbPrinter],
    profile: PrinterProfile,
    *,
    serial: str | None,
    device_index: int | None,
    verbose: bool,
) -> UsbPrinter:
    printable = [d for d in devices if d.printable(profile)]
    label = profile.label
    if not printable:
        if any(d.smart_install(profile) for d in devices):
            expected = ", ".join(sorted(profile.printable_products()))
            die(
                f"{label} in Smart Install mode (not printer mode).\n"
                f"Power-cycle USB or disable Smart Install. Expected product: {expected or 'see profile'}."
            )
        die(f"{label} not found on USB. Plug in, power on, solid green light.")

    if serial:
        for d in printable:
            if d.serial == serial or d.serial.endswith(serial):
                return d
        die(f"No printer with serial matching {serial!r}. Found: {[d.serial for d in printable]}")

    if device_index is not None:
        if device_index < 1 or device_index > len(printable):
            die(f"--device must be 1..{len(printable)}")
        return printable[device_index - 1]

    if len(printable) > 1:
        lines = [f"Multiple printers; use --serial or --device:"]
        for i, d in enumerate(printable, 1):
            lines.append(f"  [{i}] serial={d.serial}  {d.product_name}  ({d.bus_dev})")
        die("\n".join(lines))
    return printable[0]


def find_cups_usb_backend(verbose: bool) -> Path | None:
    for path in CUPS_USB_BACKENDS:
        p = Path(path)
        if p.is_file():
            vlog(f"CUPS USB backend: {p}", verbose=verbose)
            return p
    return None


def _unbind_driver(dev: UsbPrinter, *, verbose: bool) -> None:
    sysfs = Path("/sys/bus/usb/devices") / dev.sysfs
    driver_link = sysfs / "driver"
    if not driver_link.is_symlink():
        return
    driver = driver_link.resolve().name
    if driver not in {"usbfs", "usblp"}:
        vlog(f"{dev.sysfs}: bound to {driver} (leaving as-is)", verbose=verbose)
        return
    unbind = Path(f"/sys/bus/usb/drivers/{driver}/unbind")
    if unbind.exists():
        vlog(f"Unbinding {dev.sysfs} from {driver}", verbose=verbose)
        if sudo_write_sys(unbind, dev.sysfs, verbose=verbose):
            time.sleep(0.3)


def _unload_usblp(verbose: bool) -> None:
    if Path("/sys/module/usblp").exists():
        vlog("Removing usblp module", verbose=verbose)
        sudo(["modprobe", "-r", "usblp"], verbose=verbose)


def prepare_usb(dev: UsbPrinter, *, verbose: bool) -> None:
    _unbind_driver(dev, verbose=verbose)
    _unload_usblp(verbose)


def usb_reset(dev: UsbPrinter, *, verbose: bool) -> None:
    authorized = Path("/sys/bus/usb/devices") / dev.sysfs / "authorized"
    if not authorized.exists():
        warn(f"Cannot reset USB: no authorized sysfs for {dev.sysfs}")
        return
    vlog(f"USB reset on {dev.sysfs}", verbose=verbose)
    clear_backend_uri_cache()
    sudo_write_sys(authorized, "0", verbose=verbose)
    time.sleep(1)
    sudo_write_sys(authorized, "1", verbose=verbose)
    time.sleep(1)


def discover_backend_uris(*, verbose: bool) -> dict[str, str]:
    global _BACKEND_URIS
    if _BACKEND_URIS is not None:
        return _BACKEND_URIS
    backend = find_cups_usb_backend(verbose)
    if not backend:
        _BACKEND_URIS = {}
        return _BACKEND_URIS
    try:
        proc = sudo([str(backend)], verbose=verbose, timeout=10)
    except subprocess.TimeoutExpired:
        vlog("CUPS backend discovery timed out", verbose=verbose)
        return {}
    text = proc.stdout.decode(errors="replace") + proc.stderr.decode(errors="replace")
    _BACKEND_URIS = parse_backend_uris(text)
    return _BACKEND_URIS


def resolve_uri(dev: UsbPrinter, profile: PrinterProfile, *, verbose: bool, discover: bool = True) -> str:
    built = dev.device_uri(profile)
    if not discover:
        return built
    uri = cups_uri_for_serial(dev.serial, discover_backend_uris(verbose=verbose))
    if uri:
        vlog(f"URI from CUPS backend: {uri}", verbose=verbose)
        return uri
    vlog(f"Using constructed URI: {built}", verbose=verbose)
    return built


def stale_queue_warning(dev: UsbPrinter | None, profile: PrinterProfile) -> str | None:
    if not dev:
        return None
    proc = run(["lpstat", "-v"], check=False, text=True)
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if not profile.stale_queue_line(line):
            continue
        hint = stale_queue_hint(line, dev.serial)
        if hint:
            return f"{hint} (direct USB ignores this queue)"
    return None


def list_devices(profile: PrinterProfile) -> None:
    devices = find_devices(profile, verbose=False)
    if not devices:
        die(f"No USB devices for profile {profile.id!r}.")
    for i, d in enumerate(devices, 1):
        flags = [
            f for f, ok in (
                ("printable", d.printable(profile)),
                ("smart-install", d.smart_install(profile)),
            ) if ok
        ]
        log(
            f"[{i}] {d.serial}  {d.product_name}  usb:{d.vendor}:{d.product}  "
            f"driver={d.driver or 'none'}  bus={d.bus_dev}  ({', '.join(flags)})"
        )


def doctor(
    profile: PrinterProfile,
    *,
    serial: str | None,
    device_index: int | None,
    printer: str | None,
    verbose: bool,
) -> int:
    log(doctor_title(profile, "Linux"))
    issues = 0

    if profile.linux_pipeline == "cups":
        for tool in profile.linux_tools or ("lp", "lpstat"):
            path = which(tool)
            if path:
                log(f"OK  {tool}: {path}")
            else:
                log(f"FAIL  missing {tool}")
                issues += 1
        queue = find_cups_queue(profile, verbose=verbose, explicit=printer)
        if queue:
            log(f"OK  CUPS queue: {queue}")
        else:
            log("FAIL  no matching CUPS queue (set match.cups_queue in profile or use --printer)")
            issues += 1
    else:
        for tool in profile.linux_tools or ("pdftops", "foo2zjs-wrapper"):
            path = which(tool)
            if path:
                log(f"OK  {tool}: {path}")
            else:
                log(f"FAIL  missing {tool}")
                issues += 1
        backend = find_cups_usb_backend(verbose)
        if backend:
            log(f"OK  CUPS USB backend: {backend}")
        else:
            log("FAIL  CUPS USB backend not found")
            issues += 1

        if sudo_passwordless():
            log("OK  sudo: passwordless (prints won't prompt)")
        else:
            log("WARN  sudo: password required for each print")
            log("      tip: NOPASSWD rule for CUPS USB backend, or stay in a sudo session")

        try:
            with tempfile.TemporaryDirectory(prefix="p1102-doc-") as td:
                blank = write_blank_pdf(Path(td) / "blank.pdf")
                payload = render_pdf_to_zjs(blank, verbose=verbose)
            log(f"OK  ZJS pipeline test: {len(payload)} bytes")
        except RuntimeError as exc:
            log(f"FAIL  ZJS pipeline test: {exc}")
            issues += 1

        dev: UsbPrinter | None = None
        devices = find_devices(profile, verbose=verbose)
        if not devices:
            log("FAIL  no matching USB printer")
            issues += 1
        else:
            try:
                dev = select_device(
                    devices, profile, serial=serial, device_index=device_index, verbose=verbose,
                )
                log(f"OK  USB {dev.product_name} serial={dev.serial}")
                log(f"    {resolve_uri(dev, profile, verbose=verbose, discover=False)}")
            except SystemExit:
                issues += 1

        stale = stale_queue_warning(dev, profile)
        if stale:
            log(f"WARN  {stale}")

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
    serial: str | None,
    device_index: int | None,
    printer: str | None,
    device_uri: str | None,
    page_range: PageRange,
) -> None:
    if profile.linux_pipeline == "cups":
        queue = find_cups_queue(profile, verbose=verbose, explicit=printer)
        if not queue:
            die(f"No CUPS queue for profile {profile.id!r}. Use --printer NAME or fix match.cups_queue.")
        print_via_lp(pdf, queue, copies=copies, verbose=verbose, dry_run=dry_run, page_range=page_range)
        return

    dev = select_device(
        find_devices(profile, verbose), profile,
        serial=serial, device_index=device_index, verbose=verbose,
    )
    uri = device_uri or resolve_uri(dev, profile, verbose=verbose)
    log(f"Printer: {uri}")

    try:
        job_data = render_pdf_to_zjs(pdf, verbose=verbose, page_range=page_range)
    except RuntimeError as exc:
        die(str(exc))

    if dry_run:
        log(f"Dry run OK: {len(job_data)} bytes, {copies} copy/copies")
        return

    backend = find_cups_usb_backend(verbose)
    if not backend:
        die("CUPS USB backend not found")

    user = os.environ.get("USER", "user")
    for attempt in range(1, MAX_RETRIES + 1):
        vlog(f"Attempt {attempt}/{MAX_RETRIES}", verbose=verbose)
        if attempt == 1:
            status.preparing()
        else:
            status.waking_retry(attempt, MAX_RETRIES)
        prepare_usb(dev, verbose=verbose)
        if attempt > 1:
            usb_reset(dev, verbose=verbose)
            time.sleep(RETRY_DELAY_SEC)
        failed_out = ""
        for copy in range(copies):
            status.sending(copy + 1, copies)
            try:
                proc = subprocess.run(
                    ["sudo", "env", f"DEVICE_URI={uri}", "timeout", str(TIMEOUT_SEC), str(backend),
                     "1", user, pdf.name, "1", ""],
                    input=job_data, capture_output=True, timeout=TIMEOUT_SEC + 10,
                )
            except subprocess.TimeoutExpired:
                failed_out = "backend timed out"
                break
            failed_out = proc.stdout.decode(errors="replace") + proc.stderr.decode(errors="replace")
            if verbose:
                for line in failed_out.splitlines():
                    vlog(f"backend: {line}", verbose=verbose)
            if proc.returncode != 0 or "Sent " not in failed_out:
                break
            m = re.search(r"Sent (\d+) bytes", failed_out)
            status.accepted(m.group(1) if m else "?")
        else:
            status.done()
            return
        if "Failed to detach" in failed_out or "usblp" in failed_out.lower():
            _unload_usblp(verbose)
        if "Waiting for printer" in failed_out:
            clear_backend_uri_cache()
            uri = resolve_uri(dev, profile, verbose=verbose)
    die(explain_print_failure(failed_out, uri=uri), code=EXIT_SETUP)
