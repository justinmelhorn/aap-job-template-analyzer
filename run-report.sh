#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RECENT_ANALYZER="${SCRIPT_DIR}/scripts/export_recent_team_resources.py"
TEAM_ROLE_ANALYZER="${SCRIPT_DIR}/scripts/export_team_job_template_roles.py"

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

if [[ ! -f "${RECENT_ANALYZER}" || ! -f "${TEAM_ROLE_ANALYZER}" ]]; then
  printf 'ERROR: one or more report scripts are missing from %s/scripts\n' "${SCRIPT_DIR}" >&2
  exit 1
fi

printf 'AAP Job Template Reports\n'
printf 'Credentials are used only for this run and are not written to disk.\n\n'

printf '  1) Recently used Job Templates with effective team access\n'
printf '  2) All Controller team roles assigned directly to Job Templates (AAP 2.5 ID-safe)\n'
printf '  3) Run both reports\n'
read -r -p 'Choose a report [1/2/3] (1): ' report_type
case "${report_type:-1}" in
  1) report_type="recent" ;;
  2) report_type="team_roles" ;;
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
markdown_output=""
pdf_output=""
if [[ "${report_type}" == "recent" || "${report_type}" == "both" ]]; then
  read -r -p 'Number of days to report (365): ' days
  days="${days:-365}"
  if [[ ! "${days}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: days must be a positive whole number.\n' >&2
    exit 2
  fi

  read -r -p 'YAML output file (team-resources.yaml): ' yaml_output
  yaml_output="${yaml_output:-team-resources.yaml}"
  read -r -p 'Markdown output file (team-resources.md): ' markdown_output
  markdown_output="${markdown_output:-team-resources.md}"
fi
if [[ "${report_type}" == "team_roles" || "${report_type}" == "both" ]]; then
  read -r -p 'PDF output file (team-job-template-roles.pdf): ' pdf_output
  pdf_output="${pdf_output:-team-job-template-roles.pdf}"
fi

printf '\nReady to run:\n'
printf '  Gateway: %s\n' "${aap_url}"
printf '  Authentication: %s\n' "${auth_method}"
printf '  Validate certificate: %s\n' "${validate_certs}"
printf '  Python launcher: %s\n' "${python_launcher}"
if [[ "${report_type}" == "recent" ]]; then
  printf '  Report: Recently used Job Templates with effective team access\n'
elif [[ "${report_type}" == "team_roles" ]]; then
  printf '  Report: All direct team-to-Job-Template Controller roles\n'
else
  printf '  Report: Both reports\n'
fi
if [[ "${report_type}" == "recent" || "${report_type}" == "both" ]]; then
  printf '  Period: %s days\n' "${days}"
  printf '  YAML: %s\n' "${yaml_output}"
  printf '  Markdown: %s\n' "${markdown_output}"
fi
if [[ "${report_type}" == "team_roles" || "${report_type}" == "both" ]]; then
  printf '  PDF: %s\n' "${pdf_output}"
fi
read -r -p 'Continue? [Y/n]: ' continue_answer
case "${continue_answer:-y}" in
  y|Y|yes|YES|Yes) ;;
  *)
    printf 'Canceled.\n'
    exit 0
    ;;
esac

(
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
  if [[ "${report_type}" == "recent" || "${report_type}" == "both" ]]; then
    "${python_launcher}" "${RECENT_ANALYZER}" \
      --days "${days}" \
      --output "${yaml_output}" \
      --markdown-output "${markdown_output}"
  fi
  if [[ "${report_type}" == "team_roles" || "${report_type}" == "both" ]]; then
    "${python_launcher}" "${TEAM_ROLE_ANALYZER}" --output "${pdf_output}"
  fi
)

password=""
token=""
printf '\nReport complete.\n'
