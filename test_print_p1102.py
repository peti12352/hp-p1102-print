#!/usr/bin/env python3
"""Unit tests (no printer required). Run: python3 -m unittest test_print_p1102.py"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p1102.constants import SUPPORTED_EXTENSIONS  # noqa: E402
from p1102.document import (  # noqa: E402
    parse_pages_spec,
    render_pdf_to_zjs,
    resolve_page_range,
    write_blank_pdf,
)
from p1102.errors import (  # noqa: E402
    conversion_error_message,
    explain_print_failure,
    stale_queue_hint,
)
from p1102.linux import cups_uri_for_serial, parse_backend_uris  # noqa: E402
from p1102.models import PageRange, UsbPrinter  # noqa: E402
from p1102.profile import find_profile_file, load_profile_file, resolve_profile  # noqa: E402
from p1102.util import which  # noqa: E402


class DeviceUriTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = resolve_profile("p1102")

    def _dev(self, name: str) -> UsbPrinter:
        return UsbPrinter("1-2", "03f0", "002a", "SERIAL123", name, "usb", "001:016")

    def test_strips_hp_prefix(self) -> None:
        uri = self._dev("HP LaserJet Professional P1102").device_uri(self.profile)
        self.assertEqual(uri, "usb://HP/LaserJet%20Professional%20P1102?serial=SERIAL123")

    def test_keeps_non_hp_model(self) -> None:
        uri = self._dev("LaserJet Professional P1102").device_uri(self.profile)
        self.assertEqual(uri, "usb://HP/LaserJet%20Professional%20P1102?serial=SERIAL123")


class BackendParseTests(unittest.TestCase):
    SAMPLE = (
        'direct usb://HP/LaserJet%20Professional%20P1102?serial=ABC "HP" "" "" ""\n'
        'direct usb://HP/Other?serial=XYZ "x" "" "" ""\n'
    )

    def test_parse_backend_uris(self) -> None:
        uris = parse_backend_uris(self.SAMPLE)
        self.assertEqual(uris["ABC"], "usb://HP/LaserJet%20Professional%20P1102?serial=ABC")
        self.assertEqual(uris["XYZ"], "usb://HP/Other?serial=XYZ")

    def test_cups_uri_for_serial_suffix(self) -> None:
        uris = parse_backend_uris(self.SAMPLE)
        self.assertEqual(cups_uri_for_serial("BC", uris), "usb://HP/LaserJet%20Professional%20P1102?serial=ABC")


class PageRangeTests(unittest.TestCase):
    def test_parse_pages_range(self) -> None:
        pr = parse_pages_spec("3-7")
        self.assertEqual((pr.first, pr.last), (3, 7))

    def test_parse_single_page(self) -> None:
        pr = parse_pages_spec("5")
        self.assertEqual((pr.first, pr.last), (5, 5))

    def test_parse_from_page_to_end(self) -> None:
        pr = parse_pages_spec("8-")
        self.assertEqual(pr.first, 8)
        self.assertIsNone(pr.last)

    def test_resolve_from_to(self) -> None:
        pr = resolve_page_range(pages=None, from_page=2, to_page=4)
        self.assertEqual((pr.first, pr.last), (2, 4))

    def test_validate_rejects_out_of_range(self) -> None:
        with self.assertRaises(RuntimeError):
            PageRange(5, 10).validate(3)

    def test_cups_value(self) -> None:
        self.assertEqual(PageRange(3, 7).cups_value(), "3-7")
        self.assertEqual(PageRange(8, None).cups_value(), "8-")


class FormatTests(unittest.TestCase):
    def test_pdf_supported(self) -> None:
        self.assertIn(".pdf", SUPPORTED_EXTENSIONS)

    def test_docx_supported(self) -> None:
        self.assertIn(".docx", SUPPORTED_EXTENSIONS)

    def test_exe_not_supported(self) -> None:
        self.assertNotIn(".exe", SUPPORTED_EXTENSIONS)


class ProfileTests(unittest.TestCase):
    def test_builtin_p1102_loads(self) -> None:
        path = find_profile_file("p1102")
        self.assertIsNotNone(path)
        profile = load_profile_file(path)
        self.assertEqual(profile.id, "p1102")
        self.assertEqual(profile.linux_pipeline, "zjs")
        self.assertIn("002a", profile.printable_products())

    def test_default_profile(self) -> None:
        profile = resolve_profile(None)
        self.assertEqual(profile.id, "p1102")

    def test_matches_cups_queue(self) -> None:
        profile = resolve_profile("p1102")
        self.assertTrue(profile.matches_cups_queue("HP_LaserJet_P1102"))
        self.assertFalse(profile.matches_cups_queue("Brother_HL-L2350DW"))

    def test_example_cups_profile(self) -> None:
        root = Path(__file__).resolve().parent
        path = root / "profiles" / "examples" / "example-cups-linux.json"
        profile = load_profile_file(path)
        self.assertEqual(profile.linux_pipeline, "cups")
        self.assertFalse(profile.direct_usb)


class StatusMessageTests(unittest.TestCase):
    def test_processing_message(self) -> None:
        from p1102.status import accepted

        with mock.patch("p1102.status.log") as log_mock:
            accepted(759)
        joined = "\n".join(c.args[0] for c in log_mock.call_args_list)
        self.assertIn("blinking green is normal", joined)
        self.assertIn("759", joined)


class ErrorHintTests(unittest.TestCase):
    def test_waiting_for_printer_hint(self) -> None:
        msg = explain_print_failure("Waiting for printer to become available")
        self.assertIn("automatic retries", msg)
        self.assertNotIn("--reset-usb", msg)

    def test_usblp_hint(self) -> None:
        msg = explain_print_failure("Failed to detach usblp")
        self.assertIn("modprobe -r usblp", msg)

    def test_includes_uri_when_given(self) -> None:
        msg = explain_print_failure("error", uri="usb://HP/P1102?serial=ABC")
        self.assertIn("usb://HP/P1102", msg)

    def test_stale_queue_suggests_lpadmin(self) -> None:
        line = "device for HP-P1102: hp:/usb/HP_P1102?serial=WRONG"
        hint = stale_queue_hint(line, "CORRECT")
        self.assertIsNotNone(hint)
        self.assertIn("lpadmin -x HP-P1102", hint)

    def test_stale_queue_skips_matching_serial(self) -> None:
        line = "device for HP-P1102: hp:/usb/HP_P1102?serial=MINE"
        self.assertIsNone(stale_queue_hint(line, "MINE"))

    def test_conversion_error_mentions_pdf(self) -> None:
        msg = conversion_error_message(".docx")
        self.assertIn(".docx", msg)
        self.assertIn("PDF", msg)
        self.assertIn("--with-office", msg)


class ZjsPipelineTests(unittest.TestCase):
    def test_render_blank_pdf(self) -> None:
        if not which("pdftops") or not which("foo2zjs-wrapper"):
            self.skipTest("foo2zjs not installed")
        with tempfile.TemporaryDirectory() as td:
            pdf = write_blank_pdf(Path(td) / "blank.pdf")
            payload = render_pdf_to_zjs(pdf)
        self.assertGreater(len(payload), 100)


class CliTests(unittest.TestCase):
    def test_pdf_only_rejects_docx(self) -> None:
        root = Path(__file__).resolve().parent
        with tempfile.NamedTemporaryFile(suffix=".docx") as f:
            f.write(b"not a real docx")
            f.flush()
            proc = subprocess.run(
                [sys.executable, str(root / "print_p1102.py"), "--pdf-only", f.name],
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--pdf-only", proc.stderr + proc.stdout)

    def test_sudo_passwordless_check(self) -> None:
        from p1102.util import sudo_passwordless

        with mock.patch("p1102.util.run") as run_mock:
            run_mock.return_value = mock.Mock(returncode=0)
            self.assertTrue(sudo_passwordless())
            run_mock.return_value = mock.Mock(returncode=1)
            self.assertFalse(sudo_passwordless())


if __name__ == "__main__":
    unittest.main()
