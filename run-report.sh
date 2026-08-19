#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${SCRIPT_DIR}/scripts/export_recent_team_resources.py"

env_file="${AAP_ENV_FILE:-}"
if [[ -z "${env_file}" ]]; then
  if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    env_file="${SCRIPT_DIR}/.env"
  elif [[ -f "${SCRIPT_DIR}/lab.env" ]]; then
    env_file="${SCRIPT_DIR}/lab.env"
  fi
fi
if [[ -n "${env_file}" ]]; then
  if [[ ! -f "${env_file}" ]]; then
    printf 'ERROR: environment file not found: %s\n' "${env_file}" >&2
    exit 2
  fi
  set -a
  # shellcheck source=/dev/null
  source "${env_file}"
  set +a
  printf 'Loaded settings from %s\n' "${env_file}"
fi

printf 'AAP Job Template Report\n\n'
if [[ -z "${AAP_URL:-}" ]]; then
  read -r -p 'AAP Platform Gateway URL: ' AAP_URL
fi

if [[ -z "${AAP_TOKEN:-}" && \
      ( -z "${AAP_USERNAME:-}" || -z "${AAP_PASSWORD:-}" ) ]]; then
  read -r -p 'Use token authentication? [y/N]: ' token_answer
  if [[ "${token_answer:-n}" =~ ^[yY] ]]; then
    read -r -s -p 'AAP token: ' AAP_TOKEN
    printf '\n'
  else
    if [[ -z "${AAP_USERNAME:-}" ]]; then
      read -r -p 'AAP username: ' AAP_USERNAME
    fi
    read -r -s -p 'AAP password: ' AAP_PASSWORD
    printf '\n'
  fi
fi
export AAP_URL AAP_TOKEN AAP_USERNAME AAP_PASSWORD

report_mode="${AAP_REPORT_MODE:-recent}"
days="${AAP_REPORT_DAYS:-365}"
yaml_output="${AAP_YAML_OUTPUT:-job-templates.yaml}"
pdf_output="${AAP_PDF_OUTPUT:-job-templates.pdf}"

if [[ -z "${AAP_REPORT_MODE:-}" ]]; then
  read -r -p "Report recent, unused, or all jobs? [${report_mode}]: " answer
  report_mode="${answer:-${report_mode}}"
fi
if [[ -z "${AAP_REPORT_DAYS:-}" ]]; then
  read -r -p "Number of days [${days}]: " answer
  days="${answer:-${days}}"
fi
if [[ -z "${AAP_YAML_OUTPUT:-}" ]]; then
  read -r -p "YAML output [${yaml_output}]: " answer
  yaml_output="${answer:-${yaml_output}}"
fi
if [[ -z "${AAP_PDF_OUTPUT:-}" ]]; then
  read -r -p "PDF output [${pdf_output}]: " answer
  pdf_output="${answer:-${pdf_output}}"
fi

rbac_default="yes"
if [[ "${report_mode}" == "unused" ]]; then
  rbac_default="no"
fi
check_rbac="${AAP_CHECK_RBAC:-${rbac_default}}"
if [[ -z "${AAP_CHECK_RBAC:-}" ]]; then
  read -r -p "Check team and user permissions? [${rbac_default}]: " answer
  check_rbac="${answer:-${rbac_default}}"
fi

mode_argument=()
case "${report_mode}" in
  recent) ;;
  unused) mode_argument=(--unused) ;;
  all) mode_argument=(--all) ;;
  *) printf 'ERROR: choose recent, unused, or all.\n' >&2; exit 2 ;;
esac

rbac_argument=()
case "${check_rbac}" in
  y|Y|yes|YES|true|TRUE|1) ;;
  n|N|no|NO|false|FALSE|0) rbac_argument=(--no-rbac) ;;
  *) printf 'ERROR: AAP_CHECK_RBAC must be yes or no.\n' >&2; exit 2 ;;
esac

python3 "${SCRIPT}" \
  "${mode_argument[@]}" \
  "${rbac_argument[@]}" \
  --days "${days}" \
  --output "${yaml_output}" \
  --pdf-output "${pdf_output}"
