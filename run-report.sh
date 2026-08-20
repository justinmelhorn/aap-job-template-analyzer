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

python_launcher=()
python_label=""
version_check='import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'

# Prefer a simple alias defined by the loaded environment file or current shell.
for candidate in python3 python py; do
  alias_definition="$(alias "${candidate}" 2>/dev/null || true)"
  if [[ -z "${alias_definition}" ]]; then
    continue
  fi
  alias_command="${alias_definition#*=}"
  alias_command="${alias_command#\'}"
  alias_command="${alias_command%\'}"
  read -r -a alias_parts <<< "${alias_command}"
  if [[ ${#alias_parts[@]} -gt 0 ]] && \
      "${alias_parts[@]}" -c "${version_check}" >/dev/null 2>&1; then
    python_launcher=("${alias_parts[@]}")
    python_label="${candidate} alias (${alias_command})"
    break
  fi
done

# If no usable alias exists, use the first supported executable on PATH.
if [[ ${#python_launcher[@]} -eq 0 ]]; then
  for candidate in python3 python py; do
    executable="$(type -P "${candidate}" 2>/dev/null || true)"
    if [[ -n "${executable}" ]] && \
        "${executable}" -c "${version_check}" >/dev/null 2>&1; then
      python_launcher=("${executable}")
      python_label="${candidate} (${executable})"
      break
    fi
  done
fi

if [[ ${#python_launcher[@]} -eq 0 ]]; then
  printf 'ERROR: Python 3.9 or newer was not found via python3, python, or py.\n' >&2
  exit 1
fi

printf 'AAP Job and Workflow Template Report\n\n'
printf 'Python launcher: %s\n\n' "${python_label}"
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

days="${AAP_REPORT_DAYS:-365}"
output_root="${AAP_OUTPUT_ROOT:-${SCRIPT_DIR}/output}"
if [[ -z "${AAP_REPORT_DAYS:-}" ]]; then
  read -r -p "Number of days [${days}]: " answer
  days="${answer:-${days}}"
fi
if [[ "${output_root}" != /* ]]; then
  output_root="${SCRIPT_DIR}/${output_root}"
fi
if [[ ! "${days}" =~ ^[1-9][0-9]*$ ]]; then
  printf 'ERROR: AAP_REPORT_DAYS must be a positive whole number.\n' >&2
  exit 2
fi

used_check_rbac=true
case "${AAP_USED_CHECK_RBAC:-true}" in
  y|Y|yes|YES|true|TRUE|1) ;;
  n|N|no|NO|false|FALSE|0) used_check_rbac=false ;;
  *) printf 'ERROR: AAP_USED_CHECK_RBAC must be true or false.\n' >&2; exit 2 ;;
esac

unused_check_rbac=false
case "${AAP_UNUSED_CHECK_RBAC:-false}" in
  y|Y|yes|YES|true|TRUE|1) unused_check_rbac=true ;;
  n|N|no|NO|false|FALSE|0) ;;
  *) printf 'ERROR: AAP_UNUSED_CHECK_RBAC must be true or false.\n' >&2; exit 2 ;;
esac

timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
run_name="${timestamp}-used-and-unused-${days}-day-report"
run_directory="${output_root%/}/${run_name}"
suffix=2
while [[ -e "${run_directory}" ]]; do
  run_directory="${output_root%/}/${run_name}-${suffix}"
  suffix=$((suffix + 1))
done
used_directory="${run_directory}/used"
unused_directory="${run_directory}/unused"
mkdir -p "${used_directory}" "${unused_directory}"

printf 'Report period: %s days\n' "${days}"
printf 'Output directory: %s\n\n' "${run_directory}"

run_report() {
  local mode=$1
  local check_rbac=$2
  local directory=$3
  local arguments=("${SCRIPT}")
  if [[ "${mode}" == "unused" ]]; then
    arguments+=(--unused)
  fi
  if [[ "${check_rbac}" == "false" ]]; then
    arguments+=(--no-rbac)
  fi
  arguments+=(
    --days "${days}"
    --output "${directory}/${mode}-job-templates.yaml"
    --pdf-output "${directory}/${mode}-job-templates.pdf"
  )
  "${python_launcher[@]}" "${arguments[@]}"
}

set +e
printf 'Running used template report...\n'
run_report used "${used_check_rbac}" "${used_directory}"
used_status=$?

printf '\nRunning unused template report...\n'
run_report unused "${unused_check_rbac}" "${unused_directory}"
unused_status=$?
set -e

if (( used_status != 0 || unused_status != 0 )); then
  printf '\nERROR: used status=%s; unused status=%s\n' \
    "${used_status}" "${unused_status}" >&2
  exit 1
fi

printf '\nComplete. Reports are in %s\n' "${run_directory}"
