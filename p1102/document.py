from __future__ import annotations

import platform
import re
import subprocess
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from p1102.constants import (
    BLANK_PDF,
    CONVERT_TIMEOUT_SEC,
    IMAGE_EXTENSIONS,
    LIBREOFFICE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    TEXTUTIL_EXTENSIONS,
)
from p1102.errors import conversion_error_message
from p1102.models import PageRange
from p1102.util import die, run, vlog, which


def supported_formats_hint() -> str:
    return f"supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"


def parse_pages_spec(spec: str) -> PageRange:
    spec = spec.strip()
    if not spec:
        die("--pages value is empty")
    if "-" in spec:
        start, end = spec.split("-", 1)
        first = int(start) if start else 1
        last = int(end) if end else None
        return PageRange(first, last)
    page = int(spec)
    return PageRange(page, page)


def resolve_page_range(
    *,
    pages: str | None,
    from_page: int | None,
    to_page: int | None,
) -> PageRange:
    if pages and (from_page is not None or to_page is not None):
        die("Use either --pages or --from-page/--to-page, not both")
    if pages:
        return parse_pages_spec(pages)
    first = from_page if from_page is not None else 1
    if first == 1 and to_page is None:
        return PageRange.all_pages()
    return PageRange(first, to_page)


def pdf_page_count(pdf: Path) -> int | None:
    pdfinfo = which("pdfinfo")
    if not pdfinfo:
        return None
    proc = run(["pdfinfo", str(pdf.resolve())], check=False, text=True, timeout=30)
    if proc.returncode != 0:
        return None
    m = re.search(r"^Pages:\s+(\d+)", proc.stdout, re.MULTILINE)
    return int(m.group(1)) if m else None


def slice_pdf(pdf: Path, out: Path, page_range: PageRange, *, verbose: bool) -> None:
    gs = which("gs")
    if not gs:
        raise RuntimeError("ghostscript (gs) required for page range on this platform")
    cmd = [
        gs, "-o", str(out), "-sDEVICE=pdfwrite", "-dNOPAUSE", "-dBATCH",
        f"-dFirstPage={page_range.first}",
    ]
    if page_range.last is not None:
        cmd.append(f"-dLastPage={page_range.last}")
    cmd.append(str(pdf.resolve()))
    proc = run(cmd, check=False, verbose=verbose, timeout=CONVERT_TIMEOUT_SEC)
    if proc.returncode != 0 or not out.is_file():
        err = (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()
        raise RuntimeError(f"PDF page slice failed: {err or proc.returncode}")


@contextmanager
def scoped_pdf(pdf: Path, page_range: PageRange, *, verbose: bool):
    if not page_range.scoped():
        yield pdf
        return
    tmp = tempfile.TemporaryDirectory(prefix="p1102-pages-")
    try:
        out = Path(tmp.name) / "slice.pdf"
        slice_pdf(pdf, out, page_range, verbose=verbose)
        vlog(f"Sliced PDF: {page_range.label()} -> {out.stat().st_size} bytes", verbose=verbose)
        yield out
    finally:
        tmp.cleanup()


@lru_cache(maxsize=1)
def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        path = which(name)
        if path:
            return path
    if platform.system() == "Windows":
        for candidate in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ):
            if Path(candidate).is_file():
                return candidate
    return None


def converter_status() -> tuple[bool, str]:
    soffice = find_soffice()
    if soffice:
        return True, f"LibreOffice ({soffice})"
    if platform.system() == "Darwin" and which("textutil"):
        return True, "textutil (office docs; install LibreOffice for xlsx/pptx/images)"
    if which("gs"):
        return True, "ghostscript (images only; install LibreOffice for office docs)"
    return False, "install LibreOffice for non-PDF files"


def _convert_with_libreoffice(src: Path, outdir: Path, *, verbose: bool) -> Path:
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice not found (soffice/libreoffice)")
    profile = outdir / "lo_profile"
    profile.mkdir(exist_ok=True)
    uri = profile.resolve().as_uri()
    proc = run(
        [
            soffice, f"-env:UserInstallation={uri}",
            "--headless", "--convert-to", "pdf",
            "--outdir", str(outdir), str(src.resolve()),
        ],
        timeout=CONVERT_TIMEOUT_SEC, check=False, verbose=verbose,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()
        raise RuntimeError(f"LibreOffice conversion failed: {err or proc.returncode}")
    pdf = outdir / f"{src.stem}.pdf"
    if not pdf.is_file():
        raise RuntimeError(f"LibreOffice did not create {pdf.name}")
    return pdf


def _convert_with_textutil(src: Path, outdir: Path, *, verbose: bool) -> Path:
    out = outdir / f"{src.stem}.pdf"
    proc = run(
        ["textutil", "-convert", "pdf", "-output", str(out), str(src.resolve())],
        timeout=CONVERT_TIMEOUT_SEC, check=False, verbose=verbose,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()
        raise RuntimeError(f"textutil conversion failed: {err or proc.returncode}")
    if not out.is_file():
        raise RuntimeError("textutil did not create a PDF")
    return out


def _convert_image_with_gs(src: Path, outdir: Path, *, verbose: bool) -> Path:
    gs = which("gs")
    if not gs:
        raise RuntimeError("ghostscript (gs) not found for image conversion")
    out = outdir / f"{src.stem}.pdf"
    proc = run(
        [gs, "-o", str(out), "-sDEVICE=pdfwrite", "-dBATCH", "-dNOPAUSE", str(src.resolve())],
        timeout=CONVERT_TIMEOUT_SEC, check=False, verbose=verbose,
    )
    if proc.returncode != 0 or not out.is_file():
        err = (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()
        raise RuntimeError(f"ghostscript image conversion failed: {err or proc.returncode}")
    return out


def convert_to_pdf(src: Path, outdir: Path, *, verbose: bool) -> Path:
    ext = src.suffix.lower()
    if ext == ".pdf":
        return src
    if ext not in SUPPORTED_EXTENSIONS:
        raise RuntimeError(f"Unsupported file type {ext}. {supported_formats_hint()}")

    if find_soffice() and ext in LIBREOFFICE_EXTENSIONS:
        pdf = _convert_with_libreoffice(src, outdir, verbose=verbose)
        vlog(f"Converted {src.name} to PDF via LibreOffice", verbose=verbose)
        return pdf

    if platform.system() == "Darwin" and ext in TEXTUTIL_EXTENSIONS:
        pdf = _convert_with_textutil(src, outdir, verbose=verbose)
        vlog(f"Converted {src.name} to PDF via textutil", verbose=verbose)
        return pdf

    if ext in IMAGE_EXTENSIONS:
        pdf = _convert_image_with_gs(src, outdir, verbose=verbose)
        vlog(f"Converted {src.name} to PDF via ghostscript", verbose=verbose)
        return pdf

    raise RuntimeError(conversion_error_message(ext))


@contextmanager
def as_pdf(src: Path, *, verbose: bool):
    if src.suffix.lower() == ".pdf":
        yield src
        return
    tmp = tempfile.TemporaryDirectory(prefix="p1102-conv-")
    try:
        yield convert_to_pdf(src, Path(tmp.name), verbose=verbose)
    finally:
        tmp.cleanup()


def render_pdf_to_zjs(
    pdf: Path,
    *,
    verbose: bool = False,
    page_range: PageRange | None = None,
) -> bytes:
    pr = page_range or PageRange.all_pages()
    for tool in ("pdftops", "foo2zjs-wrapper"):
        if not which(tool):
            raise RuntimeError(
                f"Missing {tool}. Install: sudo dnf install foo2zjs ghostscript  (Fedora/RHEL)\n"
                "                     sudo apt install foo2zjs ghostscript   (Debian/Ubuntu)"
            )
    with tempfile.TemporaryDirectory(prefix="p1102-") as tmp:
        ps = Path(tmp) / "job.ps"
        pdftops_cmd = ["pdftops", "-paper", "A4"]
        if pr.scoped():
            pdftops_cmd.extend(["-f", str(pr.first)])
            if pr.last is not None:
                pdftops_cmd.extend(["-l", str(pr.last)])
        pdftops_cmd.extend([str(pdf), str(ps)])
        proc_ps = subprocess.run(pdftops_cmd, capture_output=True, timeout=120)
        if proc_ps.returncode != 0:
            raise RuntimeError(f"pdftops failed: {proc_ps.stderr.decode(errors='replace')}")
        proc_zjs = subprocess.run(
            ["foo2zjs-wrapper", "-z2", "-p9", "-r600x600", "-P", str(ps)],
            capture_output=True, timeout=120,
        )
        if proc_zjs.returncode != 0:
            raise RuntimeError(f"foo2zjs-wrapper failed: {proc_zjs.stderr.decode(errors='replace')}")
        if verbose:
            vlog(f"ZJS payload: {len(proc_zjs.stdout)} bytes", verbose=True)
        return proc_zjs.stdout


def write_blank_pdf(path: Path) -> Path:
    """Test page with visible toner; truly empty PDFs are often skipped by the laser."""
    gs = which("gs")
    if gs:
        proc = run(
            [
                gs, "-o", str(path),
                "-sDEVICE=pdfwrite", "-dNOPAUSE", "-dBATCH",
                "-c",
                "/Helvetica findfont 14 scalefont setfont "
                "72 720 moveto (print-p1102 test) show showpage",
                "-f",
            ],
            check=False,
            timeout=30,
        )
        if proc.returncode == 0 and path.is_file() and path.stat().st_size > 200:
            return path
    path.write_bytes(BLANK_PDF)
    return path
