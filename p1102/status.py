from __future__ import annotations

from p1102.util import log


def preparing() -> None:
    log("Preparing printer...")


def sending(copy: int, total: int) -> None:
    if total == 1:
        log("Sending to printer...")
    else:
        log(f"Sending copy {copy}/{total}...")


def accepted(byte_count: str | int) -> None:
    log(f"Printer accepted job ({byte_count} bytes).")
    log("Processing: blinking green is normal. Paper should appear shortly.")


def done() -> None:
    log("Done.")


def waking_retry(attempt: int, maximum: int) -> None:
    log(f"Printer waking up, retry {attempt}/{maximum}...")


def submitted_queue(queue: str) -> None:
    log(f"Sent to {queue}.")
    log("Processing: blinking green is normal. Paper should appear shortly.")


def submitted_windows() -> None:
    log("Sent to printer.")
    log("Processing: blinking green is normal. Paper should appear shortly.")
