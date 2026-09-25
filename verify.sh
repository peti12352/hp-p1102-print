#!/usr/bin/env bash
# Local: ./verify.sh
# CI sets CI=true → unit tests only (no printer/USB required)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
python3 -m unittest test_print_p1102.py -v
if [[ -z "${CI:-}" ]]; then
  python3 print_p1102.py --doctor
  python3 print_p1102.py --smoke-test --dry-run
  if [[ "${VERIFY_PRINT:-}" == "1" ]]; then
    python3 print_p1102.py --smoke-test
  fi
fi
echo "verify: OK"
