#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ANALYZER="${SCRIPT_DIR}/scripts/export_recent_team_resources.py"

if ! command -v python3 >/dev/null 2>&1; then
  printf 'ERROR: python3 was not found in PATH. Python 3.9 or newer is required.\n' >&2
  exit 1
fi

if [[ ! -f "${ANALYZER}" ]]; then
  printf 'ERROR: analyzer not found at %s\n' "${ANALYZER}" >&2
  exit 1
fi

printf 'AAP Job Template Access Report\n'
printf 'Credentials are used only for this run and are not written to disk.\n\n'

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

printf '\nReady to run:\n'
printf '  Gateway: %s\n' "${aap_url}"
printf '  Authentication: %s\n' "${auth_method}"
printf '  Validate certificate: %s\n' "${validate_certs}"
printf '  Period: %s days\n' "${days}"
printf '  YAML: %s\n' "${yaml_output}"
printf '  Markdown: %s\n' "${markdown_output}"
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
  python3 "${ANALYZER}" \
    --days "${days}" \
    --output "${yaml_output}" \
    --markdown-output "${markdown_output}"
)

password=""
token=""
printf '\nReport complete.\n'
