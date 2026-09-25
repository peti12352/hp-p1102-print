# print-p1102

Print to an **HP LaserJet P1102 / P1102w** over USB when normal Linux printing sends 0-byte jobs.

Works on **Linux** (direct USB), **macOS**, and **Windows**.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/peti12352/hp-p1102-print/main/install.sh | bash
print-p1102 --doctor
print-p1102 document.pdf
```

Windows (after [HP driver](#drivers)):

```powershell
irm https://raw.githubusercontent.com/peti12352/hp-p1102-print/main/install.ps1 | iex
print-p1102.ps1 document.pdf
```

PDF only needs the install above. For docx/xlsx on Linux: `install.sh --with-office`. On Windows/macOS: [LibreOffice](https://www.libreoffice.org/download/) optional.

## What you'll see

```
Preparing printer...
Sending to printer...
Printer accepted job (... bytes).
Processing: blinking green is normal. Paper should appear shortly.
Done.
```

**Blinking green, orange off** = processing (normal). **Slow blink** = sleep. **Orange on** = paper, door, or jam.

The tool wakes the printer and retries automatically; no extra flags needed.

## Examples

```bash
print-p1102 report.pdf
print-p1102 --from-page 8 --to-page 12 report.pdf
print-p1102 --pages 5 report.pdf
print-p1102 -n 2 report.pdf
print-p1102 --smoke-test          # test page ("print-p1102 test" on paper)
print-p1102 --list-devices        # Linux USB
```

## CLI

| Flag | Purpose |
|------|---------|
| `--doctor` | Check setup |
| `--dry-run` | Validate without printing |
| `--pdf-only` | Refuse non-PDF (no conversion) |
| `--from-page N` / `--to-page N` | Page range |
| `--pages RANGE` | e.g. `3-7`, `5`, `8-` |
| `-n N` | Copies |
| `-v` | Debug |
| `--serial S` / `--device N` | Pick USB printer (Linux) |

Formats: pdf, doc/docx, odt, rtf, txt, xls/xlsx, ods, ppt/pptx, odp, html, images (via LibreOffice or macOS textutil).

## Drivers

| OS | Tool deps | HP driver (once) |
|----|-----------|------------------|
| Linux | `install.sh` → foo2zjs, ghostscript, cups | Not needed |
| macOS | `brew install foo2zjs ghostscript` | [HP .dmg](https://ftp.hp.com/pub/softlib/software12/HP_Quick_Start/osx/Applications/ASU/HewlettPackardPrinterDrivers.dmg) |
| Windows | Python + script | [HP .exe](https://ftp.hp.com/pub/softlib/software13/COL32431/bi-80329-12/hp_LJP1100_P1560_P1600_Full_Solution-v20180815-50157037_1.exe) |

Linux prints via `sudo` (USB backend). `--doctor` reports if a password is needed each job.

USB IDs: `03f0:002a` P1102, `03f0:102a` P1102w

## Troubleshooting

```bash
print-p1102 --doctor -v
print-p1102 --smoke-test
```

| Problem | Fix |
|---------|-----|
| `--smoke-test` says Done but no paper | Normal for `--dry-run`; run `print-p1102 --smoke-test` without it |
| Blinking green, nothing yet | Wait, or press **Cancel** on printer once, retry |
| `sudo` password every print | Expected; configure NOPASSWD for CUPS USB backend if desired |
| Stale CUPS queue (wrong serial) | `sudo lpadmin -x QueueName` (direct USB ignores it) |
| Smart Install mode | Power-cycle USB; printer should show product `002a` or `102a` |

## Develop

```bash
./verify.sh                    # tests + doctor (local)
CI=true ./verify.sh            # tests only (no printer)
python3 -m unittest test_print_p1102.py -v
```

Other printers: see `profiles/README.md` (advanced, hidden flags).
