#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${SCRIPT_DIR}/scripts/export_recent_team_resources.py"

printf 'AAP Job Template Report\n\n'
read -r -p 'AAP Platform Gateway URL: ' AAP_URL
read -r -p 'Use token authentication? [y/N]: ' token_answer
if [[ "${token_answer:-n}" =~ ^[yY] ]]; then
  read -r -s -p 'AAP token: ' AAP_TOKEN
  printf '\n'
  export AAP_TOKEN
else
  read -r -p 'AAP username: ' AAP_USERNAME
  read -r -s -p 'AAP password: ' AAP_PASSWORD
  printf '\n'
  export AAP_USERNAME AAP_PASSWORD
fi
export AAP_URL

read -r -p 'Report recent, unused, or all jobs? [recent]: ' report_mode
read -r -p 'Number of days [365]: ' days
read -r -p 'YAML output [job-templates.yaml]: ' yaml_output
read -r -p 'PDF output [job-templates.pdf]: ' pdf_output

report_mode="${report_mode:-recent}"
days="${days:-365}"
yaml_output="${yaml_output:-job-templates.yaml}"
pdf_output="${pdf_output:-job-templates.pdf}"

mode_argument=()
case "${report_mode}" in
  recent) ;;
  unused) mode_argument=(--unused) ;;
  all) mode_argument=(--all) ;;
  *) printf 'ERROR: choose recent, unused, or all.\n' >&2; exit 2 ;;
esac

python3 "${SCRIPT}" \
  "${mode_argument[@]}" \
  --days "${days}" \
  --output "${yaml_output}" \
  --pdf-output "${pdf_output}"
