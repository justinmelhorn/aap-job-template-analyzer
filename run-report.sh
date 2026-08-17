#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RECENT_ANALYZER="${SCRIPT_DIR}/scripts/export_recent_team_resources.py"
IDENTITY_ANALYZER="${SCRIPT_DIR}/scripts/export_job_template_identity_access.py"

python_launcher=""
for candidate in python3 python py; do
  if command -v "${candidate}" >/dev/null 2>&1 && \
    "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' \
      >/dev/null 2>&1; then
    python_launcher="${candidate}"
    break
  fi
done

if [[ -z "${python_launcher}" ]]; then
  printf 'ERROR: no supported Python launcher was found. Tried python3, python, and py; Python 3.9 or newer is required.\n' >&2
  exit 1
fi

if [[ ! -f "${RECENT_ANALYZER}" || ! -f "${IDENTITY_ANALYZER}" ]]; then
  printf 'ERROR: one or more report scripts are missing from %s/scripts\n' "${SCRIPT_DIR}" >&2
  exit 1
fi

status_interval="${AAP_STATUS_INTERVAL:-15}"
if [[ ! "${status_interval}" =~ ^[1-9][0-9]*$ ]]; then
  printf 'ERROR: AAP_STATUS_INTERVAL must be a positive whole number of seconds.\n' >&2
  exit 2
fi

run_with_status() {
  local label=$1
  shift
  local started=${SECONDS}
  local command_pid
  local command_status
  local elapsed
  local next_status=${status_interval}

  printf '\nStarting: %s\n' "${label}"
  "$@" &
  command_pid=$!
  trap 'kill "${command_pid}" 2>/dev/null || true' INT TERM

  while kill -0 "${command_pid}" 2>/dev/null; do
    sleep 1 || true
    if kill -0 "${command_pid}" 2>/dev/null; then
      elapsed=$((SECONDS - started))
      if (( elapsed >= next_status )); then
        printf '[%dm %02ds] Still running: %s\n' \
          "$((elapsed / 60))" "$((elapsed % 60))" "${label}"
        next_status=$((next_status + status_interval))
      fi
    fi
  done

  if wait "${command_pid}"; then
    command_status=0
  else
    command_status=$?
  fi
  trap - INT TERM
  elapsed=$((SECONDS - started))
  if (( command_status == 0 )); then
    printf '[%dm %02ds] Finished: %s\n' \
      "$((elapsed / 60))" "$((elapsed % 60))" "${label}"
  else
    printf '[%dm %02ds] Failed with status %s: %s\n' \
      "$((elapsed / 60))" "$((elapsed % 60))" "${command_status}" "${label}" >&2
  fi
  return "${command_status}"
}

printf 'AAP Job Template Reports\n'
printf 'Credentials are used only for this run and are not written to disk.\n\n'

printf '  1) Recently used Job Templates with effective team access\n'
printf '  2) Complete Job Template identity access audit (Gateway + Controller)\n'
printf '  3) Run both reports\n'
read -r -p 'Choose a report [1/2/3] (1): ' report_type
case "${report_type:-1}" in
  1) report_type="recent" ;;
  2) report_type="identity_access" ;;
  3) report_type="both" ;;
  *)
    printf 'ERROR: choose report 1, 2, or 3.\n' >&2
    exit 2
    ;;
esac

aap_url=""
while [[ -z "${aap_url}" ]]; do
  read -r -p 'AAP Platform Gateway URL (for example, https://aap.example.com): ' aap_url
done
aap_url="${aap_url%/}"

read -r -p 'Authentication method [basic/token] (basic): ' auth_method
auth_method="${auth_method:-basic}"
username=""
password=""
token=""
case "${auth_method}" in
  basic|b)
    read -r -p 'AAP username (admin): ' username
    username="${username:-admin}"
    while [[ -z "${password}" ]]; do
      read -r -s -p 'AAP password: ' password
      printf '\n'
    done
    auth_method="basic"
    ;;
  token|t)
    while [[ -z "${token}" ]]; do
      read -r -s -p 'AAP OAuth2 token: ' token
      printf '\n'
    done
    auth_method="token"
    ;;
  *)
    printf 'ERROR: choose basic or token authentication.\n' >&2
    exit 2
    ;;
esac

read -r -p 'Validate the AAP TLS certificate? [Y/n]: ' validate_answer
case "${validate_answer:-y}" in
  y|Y|yes|YES|Yes) validate_certs="true" ;;
  n|N|no|NO|No) validate_certs="false" ;;
  *)
    printf 'ERROR: answer y or n for certificate validation.\n' >&2
    exit 2
    ;;
esac

days=""
yaml_output=""
recent_pdf_output=""
identity_yaml_output=""
identity_pdf_output=""
if [[ "${report_type}" == "recent" || "${report_type}" == "both" ]]; then
  read -r -p 'Number of days to report (365): ' days
  days="${days:-365}"
  if [[ ! "${days}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: days must be a positive whole number.\n' >&2
    exit 2
  fi

  read -r -p 'YAML output file (team-resources.yaml): ' yaml_output
  yaml_output="${yaml_output:-team-resources.yaml}"
  read -r -p 'PDF output file (team-resources.pdf): ' recent_pdf_output
  recent_pdf_output="${recent_pdf_output:-team-resources.pdf}"
fi
if [[ "${report_type}" == "identity_access" || "${report_type}" == "both" ]]; then
  read -r -p 'Identity audit YAML file (job-template-identity-access.yaml): ' identity_yaml_output
  identity_yaml_output="${identity_yaml_output:-job-template-identity-access.yaml}"
  read -r -p 'Identity audit PDF file (job-template-identity-access.pdf): ' identity_pdf_output
  identity_pdf_output="${identity_pdf_output:-job-template-identity-access.pdf}"
fi

printf '\nReady to run:\n'
printf '  Gateway: %s\n' "${aap_url}"
printf '  Authentication: %s\n' "${auth_method}"
printf '  Validate certificate: %s\n' "${validate_certs}"
printf '  Python launcher: %s\n' "${python_launcher}"
if [[ "${report_type}" == "recent" ]]; then
  printf '  Report: Recently used Job Templates with effective team access\n'
elif [[ "${report_type}" == "identity_access" ]]; then
  printf '  Report: Complete Job Template identity access audit\n'
else
  printf '  Report: Both reports\n'
fi
if [[ "${report_type}" == "recent" || "${report_type}" == "both" ]]; then
  printf '  Period: %s days\n' "${days}"
  printf '  YAML: %s\n' "${yaml_output}"
  printf '  Access PDF: %s\n' "${recent_pdf_output}"
fi
if [[ "${report_type}" == "identity_access" || "${report_type}" == "both" ]]; then
  printf '  Identity audit YAML: %s\n' "${identity_yaml_output}"
  printf '  Identity audit PDF: %s\n' "${identity_pdf_output}"
fi
read -r -p 'Continue? [Y/n]: ' continue_answer
case "${continue_answer:-y}" in
  y|Y|yes|YES|Yes) ;;
  *)
    printf 'Canceled.\n'
    exit 0
    ;;
esac

run_status=0
if (
  export AAP_URL="${aap_url}"
  export AAP_VALIDATE_CERTS="${validate_certs}"
  if [[ "${auth_method}" == "token" ]]; then
    export AAP_TOKEN="${token}"
    unset AAP_USERNAME AAP_PASSWORD
  else
    export AAP_USERNAME="${username}"
    export AAP_PASSWORD="${password}"
    unset AAP_TOKEN
  fi
  overall_status=0
  if [[ "${report_type}" == "recent" || "${report_type}" == "both" ]]; then
    if run_with_status "recent-use YAML and PDF" \
        "${python_launcher}" "${RECENT_ANALYZER}" \
        --days "${days}" \
        --output "${yaml_output}" \
        --pdf-output "${recent_pdf_output}"; then
      :
    else
      command_status=$?
      if (( command_status > overall_status )); then
        overall_status=${command_status}
      fi
    fi
  fi
  if [[ "${report_type}" == "identity_access" || "${report_type}" == "both" ]]; then
    if run_with_status "identity-access YAML and PDF" \
        "${python_launcher}" "${IDENTITY_ANALYZER}" \
        --yaml-output "${identity_yaml_output}" \
        --pdf-output "${identity_pdf_output}"; then
      :
    else
      command_status=$?
      if (( command_status > overall_status )); then
        overall_status=${command_status}
      fi
    fi
  fi
  exit "${overall_status}"
); then
  run_status=0
else
  run_status=$?
fi

password=""
token=""
if (( run_status == 0 )); then
  printf '\nReport complete.\n'
else
  printf '\nReports finished with status %s. Review any partial artifacts and errors above.\n' "${run_status}" >&2
fi
exit "${run_status}"
