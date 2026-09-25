from __future__ import annotations

import argparse
import platform
import sys
import tempfile
from pathlib import Path

from p1102.constants import SUPPORTED_EXTENSIONS
from p1102.errors import EXIT_CONVERT
from p1102.document import as_pdf, pdf_page_count, resolve_page_range, supported_formats_hint, write_blank_pdf
from p1102 import linux, macos, windows
from p1102.models import PageRange
from p1102.profile import DEFAULT_PROFILE_ID, format_profile_list, resolve_profile
from p1102.util import die, log, vlog


def _dispatch_print(
    pdf: Path,
    *,
    system: str,
    profile,
    copies: int,
    verbose: bool,
    dry_run: bool,
    serial: str | None,
    device_index: int | None,
    printer: str | None,
    device_uri: str | None,
    page_range: PageRange,
) -> None:
    if system == "Linux":
        linux.print_pdf(
            pdf, profile, copies=copies, verbose=verbose, dry_run=dry_run,
            serial=serial, device_index=device_index, printer=printer,
            device_uri=device_uri, page_range=page_range,
        )
    elif system == "Darwin":
        macos.print_pdf(
            pdf, profile, copies=copies, verbose=verbose, dry_run=dry_run,
            printer=printer, page_range=page_range,
        )
    elif system == "Windows":
        windows.print_pdf(
            pdf, profile, copies=copies, verbose=verbose, dry_run=dry_run,
            printer=printer, page_range=page_range,
        )
    else:
        die(f"Unsupported platform: {system}")


def run_smoke_test(
    *,
    system: str,
    profile,
    copies: int,
    verbose: bool,
    dry_run: bool,
    serial: str | None,
    device_index: int | None,
    printer: str | None,
    device_uri: str | None,
) -> None:
    log('Smoke test: one test page (look for "print-p1102 test" on paper)')
    with tempfile.TemporaryDirectory(prefix="p1102-smoke-") as td:
        pdf = write_blank_pdf(Path(td) / "blank.pdf")
        _dispatch_print(
            pdf, system=system, profile=profile, copies=copies, verbose=verbose,
            dry_run=dry_run, serial=serial, device_index=device_index,
            printer=printer, device_uri=device_uri, page_range=PageRange.all_pages(),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="HP LaserJet P1102 USB document print")
    parser.add_argument("pdf", nargs="?", type=Path, help="Document to print")
    parser.add_argument("-n", "--copies", type=int, default=1, help="Number of copies")
    parser.add_argument("--from-page", type=int, metavar="N", help="First page (1-based)")
    parser.add_argument("--to-page", type=int, metavar="N", help="Last page (inclusive)")
    parser.add_argument("--pages", metavar="RANGE", help="Page range: 3-7, 5, or 8-")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose debug output")
    parser.add_argument("--dry-run", action="store_true", help="Check setup without printing")
    parser.add_argument("--pdf-only", action="store_true", help="Refuse non-PDF files (skip conversion)")
    parser.add_argument("--smoke-test", action="store_true", help="Print one blank page (end-to-end test)")
    parser.add_argument("--reset-usb", action="store_true", help="Reset USB before print (Linux)")
    parser.add_argument("--doctor", action="store_true", help="Diagnose setup")
    parser.add_argument("--list-devices", action="store_true", help="List USB P1102 devices (Linux)")
    parser.add_argument("--serial", help="USB serial when multiple printers connected")
    parser.add_argument("--device", type=int, metavar="N", help="Pick Nth printable USB device (1-based)")
    # hidden: other printers / power users (see profiles/README.md)
    parser.add_argument("--list-profiles", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile", metavar="ID", help=argparse.SUPPRESS)
    parser.add_argument("--printer", metavar="NAME", help=argparse.SUPPRESS)
    parser.add_argument("--uri", metavar="URI", help=argparse.SUPPRESS)
    args = parser.parse_args()

    system = platform.system()

    if args.list_profiles:
        format_profile_list()
        return

    profile = resolve_profile(args.profile)
    if profile.id != DEFAULT_PROFILE_ID:
        vlog(f"Profile: {profile.id} ({profile.label})", verbose=True)

    if args.list_devices:
        if system != "Linux":
            die("--list-devices is Linux only")
        linux.list_devices(profile)
        return

    if args.doctor:
        if system == "Linux":
            sys.exit(linux.doctor(
                profile, serial=args.serial, device_index=args.device,
                printer=args.printer, verbose=args.verbose,
            ))
        if system == "Darwin":
            sys.exit(macos.doctor(profile, printer=args.printer, verbose=args.verbose))
        if system == "Windows":
            sys.exit(windows.doctor(profile, printer=args.printer, verbose=args.verbose))
        die(f"--doctor not supported on {system}")

    if args.smoke_test:
        if args.copies < 1:
            die("--copies must be >= 1")
        run_smoke_test(
            system=system, profile=profile, copies=args.copies, verbose=args.verbose,
            dry_run=args.dry_run, serial=args.serial, device_index=args.device,
            printer=args.printer, device_uri=args.uri,
        )
        return

    if not args.pdf:
        parser.error("file is required (or use --doctor, --smoke-test, --list-devices)")
    if not args.pdf.is_file():
        die(f"File not found: {args.pdf}")
    ext = args.pdf.suffix.lower()
    if args.pdf_only and ext != ".pdf":
        die(f"--pdf-only: {ext or '(none)'} is not PDF. Save as PDF or omit --pdf-only.")
    if ext not in SUPPORTED_EXTENSIONS:
        die(f"Unsupported file type: {ext or '(none)'}. {supported_formats_hint()}")
    if args.copies < 1:
        die("--copies must be >= 1")

    page_range = resolve_page_range(pages=args.pages, from_page=args.from_page, to_page=args.to_page)

    if args.reset_usb and system == "Linux" and profile.linux_pipeline == "zjs":
        try:
            dev = linux.select_device(
                linux.find_devices(profile, args.verbose),
                profile,
                serial=args.serial, device_index=args.device, verbose=args.verbose,
            )
            linux.usb_reset(dev, verbose=args.verbose)
        except SystemExit:
            die("Cannot reset USB: no printer found")

    try:
        with as_pdf(args.pdf, verbose=args.verbose) as pdf_path:
            if ext != ".pdf":
                log(f"Converted to PDF ({pdf_path.stat().st_size} bytes)")
            total = pdf_page_count(pdf_path)
            page_range.validate(total)
            if page_range.scoped():
                extra = f" of {total}" if total else ""
                log(f"Scope: {page_range.label()}{extra}")
            elif total:
                vlog(f"Document: {total} pages", verbose=args.verbose)
            _dispatch_print(
                pdf_path, system=system, profile=profile, copies=args.copies,
                verbose=args.verbose, dry_run=args.dry_run, serial=args.serial,
                device_index=args.device, printer=args.printer, device_uri=args.uri,
                page_range=page_range,
            )
    except RuntimeError as exc:
        die(str(exc), code=EXIT_CONVERT)
