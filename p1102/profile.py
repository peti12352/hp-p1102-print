from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from p1102.util import die

DEFAULT_PROFILE_ID = "p1102"
PROFILE_ENV = "PRINT_P1102_PROFILE"
PROFILE_DIR_ENV = "PRINT_P1102_PROFILE_DIR"


@dataclass(frozen=True)
class UsbProduct:
    name: str
    printable: bool = False
    smart_install: bool = False


@dataclass(frozen=True)
class PrinterProfile:
    id: str
    label: str
    linux_pipeline: str
    usb_vendor: str | None
    uri_brand: str
    direct_usb: bool
    linux_tools: tuple[str, ...]
    usb_products: dict[str, UsbProduct]
    cups_queue_patterns: tuple[str, ...]
    windows_patterns: tuple[str, ...]
    windows_driver_url: str | None
    source: Path | None = None

    def printable_products(self) -> frozenset[str]:
        return frozenset(pid for pid, p in self.usb_products.items() if p.printable)

    def smart_install_products(self) -> frozenset[str]:
        return frozenset(pid for pid, p in self.usb_products.items() if p.smart_install)

    def product_label(self, product_id: str) -> str:
        if product_id in self.usb_products:
            return self.usb_products[product_id].name
        return product_id

    def matches_cups_queue(self, name: str) -> bool:
        return _matches_patterns(name, self.cups_queue_patterns)

    def matches_windows_printer(self, name: str, driver: str = "") -> bool:
        hay = f"{name} {driver}"
        return _matches_patterns(hay, self.windows_patterns)

    def matches_lpinfo_line(self, line: str) -> bool:
        return _matches_patterns(line, self.cups_queue_patterns)

    def stale_queue_line(self, line: str) -> bool:
        if not self.cups_queue_patterns:
            return False
        return _matches_patterns(line, self.cups_queue_patterns)


def _matches_patterns(text: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return False
    lower = text.lower()
    return any(p.lower() in lower for p in patterns)


def _bundled_profiles_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "profiles"


def profile_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    if extra := os.environ.get(PROFILE_DIR_ENV):
        dirs.append(Path(extra).expanduser())
    dirs.append(Path.home() / ".config" / "print-p1102" / "profiles")
    dirs.append(_bundled_profiles_dir())
    return dirs


def doctor_title(profile: PrinterProfile, platform: str) -> str:
    if profile.id == DEFAULT_PROFILE_ID:
        return f"=== HP P1102 doctor ({platform}) ==="
    return f"=== {profile.label} doctor ({platform}) ==="


def _parse_products(raw: dict) -> dict[str, UsbProduct]:
    products: dict[str, UsbProduct] = {}
    for pid, info in raw.items():
        if not isinstance(info, dict):
            continue
        products[pid.lower()] = UsbProduct(
            name=str(info.get("name", pid)),
            printable=bool(info.get("printable", False)),
            smart_install=bool(info.get("smart_install", False)),
        )
    return products


def load_profile_file(path: Path) -> PrinterProfile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"Invalid profile {path}: {exc}")

    profile_id = str(data.get("id") or path.stem)
    label = str(data.get("label") or profile_id)
    linux = data.get("linux") or {}
    match = data.get("match") or {}
    drivers = data.get("drivers") or {}

    pipeline = str(linux.get("pipeline", "cups")).lower()
    if pipeline not in {"zjs", "cups"}:
        die(f"Profile {path}: linux.pipeline must be 'zjs' or 'cups', got {pipeline!r}")

    usb_vendor = linux.get("usb_vendor")
    if usb_vendor:
        usb_vendor = str(usb_vendor).lower().removeprefix("0x")

    return PrinterProfile(
        id=profile_id,
        label=label,
        linux_pipeline=pipeline,
        usb_vendor=usb_vendor,
        uri_brand=str(linux.get("uri_brand", "HP")),
        direct_usb=bool(linux.get("direct_usb", pipeline == "zjs")),
        linux_tools=tuple(str(t) for t in linux.get("tools", ())),
        usb_products=_parse_products(linux.get("products") or {}),
        cups_queue_patterns=tuple(str(p) for p in match.get("cups_queue", ())),
        windows_patterns=tuple(str(p) for p in match.get("windows", ())),
        windows_driver_url=drivers.get("windows"),
        source=path.resolve(),
    )


def find_profile_file(spec: str) -> Path | None:
    candidate = Path(spec).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    if candidate.suffix == ".json":
        missing = candidate
    else:
        missing = candidate.with_suffix(".json")
        if missing.is_file():
            return missing.resolve()
    stem = Path(spec).stem
    for directory in profile_search_dirs():
        path = directory / f"{stem}.json"
        if path.is_file():
            return path.resolve()
    return None


def resolve_profile(spec: str | None = None) -> PrinterProfile:
    chosen = spec or os.environ.get(PROFILE_ENV) or DEFAULT_PROFILE_ID
    path = find_profile_file(chosen)
    if not path:
        dirs = ", ".join(str(d) for d in profile_search_dirs())
        die(f"Profile not found: {chosen!r}. Searched: {dirs}")
    return load_profile_file(path)


def list_profiles() -> list[tuple[str, str, Path]]:
    seen: dict[str, tuple[str, Path]] = {}
    for directory in profile_search_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                profile = load_profile_file(path)
            except SystemExit:
                continue
            if profile.id in seen:
                continue
            seen[profile.id] = (profile.label, path.resolve())
    return [(pid, label, path) for pid, (label, path) in sorted(seen.items())]


def format_profile_list() -> None:
    from p1102.util import log

    rows = list_profiles()
    if not rows:
        log("No profiles found.")
        return
    log("Available printer profiles:")
    for pid, label, path in rows:
        bundled = _bundled_profiles_dir() in path.parents or path.parent == _bundled_profiles_dir()
        origin = "bundled" if bundled else str(path.parent)
        log(f"  {pid:20}  {label}  ({origin})")
    log("")
    log("Use: print-p1102 --profile <id> file.pdf")
    log(f"Custom profiles: ~/.config/print-p1102/profiles/<id>.json  (or ${PROFILE_DIR_ENV})")
