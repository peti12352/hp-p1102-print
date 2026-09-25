# Printer profiles (advanced)

Default install targets the HP P1102. To use another printer, add a JSON profile under `~/.config/print-p1102/profiles/` or set `PRINT_P1102_PROFILE`.

```bash
export PRINT_P1102_PROFILE=my-printer
print-p1102 file.pdf
```

Hidden CLI flags (not shown in `--help`): `--profile`, `--printer`, `--uri`, `--list-profiles`.

## CUPS queue (most printers)

```bash
cp profiles/examples/example-cups-linux.json ~/.config/print-p1102/profiles/my-printer.json
# edit match.cups_queue → your queue name from lpstat -p
PRINT_P1102_PROFILE=my-printer print-p1102 --doctor
```

Or one-shot: `print-p1102 --printer "Queue_Name" file.pdf`

## Fields

| field | purpose |
|-------|---------|
| `linux.pipeline` | `zjs` = P1102-style direct USB; `cups` = `lp` queue |
| `linux.usb_vendor` / `products` | USB match (Linux `--list-devices`) |
| `match.cups_queue` | substrings for CUPS queue names |
| `match.windows` | substrings for Windows printer names |

Copy `profiles/p1102.json` for another ZJS/USB-direct printer and adjust USB IDs.
