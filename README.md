# AAP Job Template Access Report

This read-only Python utility exports one YAML record for every Ansible
Automation Platform Job Template run during a selected period. Each record
contains the template's related resources and the teams that can currently
access it.

## Requirements

- Python 3.9 or newer
- Network access to the AAP Platform Gateway
- An AAP account allowed to read Controller resources and RBAC assignments

There are no third-party Python dependencies. The script uses only modules
included with Python, so no virtual environment or `pip install` is required.
It does not require Ansible, PyYAML, requests, or a container runtime.

## Configure the connection

Set the Platform Gateway URL and either Basic Auth credentials or an OAuth2
token:

```bash
export AAP_URL=https://aap.example.com
export AAP_USERNAME=admin
export AAP_PASSWORD='your-password'
```

Alternatively:

```bash
export AAP_URL=https://aap.example.com
export AAP_TOKEN='your-token'
```

Basic Auth is useful when the default administrator is associated with an
external authentication provider and cannot create an OAuth2 token.

Certificate validation is enabled by default. For an isolated lab using a
self-signed certificate only:

```bash
export AAP_VALIDATE_CERTS=false
```

Do not disable certificate validation in production.

## Run the report

From the repository root:

```bash
python3 scripts/export_recent_team_resources.py \
  --days 365 \
  --output team-resources.yaml
```

Omit `--output` to write YAML to standard output. `--days` must be at least 1
and defaults to 365.

The command only sends HTTP `GET` requests. It does not launch jobs, modify
RBAC, change templates, or clean up AAP data.

## Output

```yaml
job_templates:
  - name: "Payments | Deploy Development"
    organization: "Payments"
    api_url: "https://aap.example.com/api/controller/v2/job_templates/24/"
    last_job_run: "2026-08-12T15:20:12Z"
    playbook: "payments/playbooks/deploy.yml"
    project:
      name: "Payments Automation"
      api_url: "https://aap.example.com/api/controller/v2/projects/8/"
    inventory:
      name: "Payments Development"
      api_url: "https://aap.example.com/api/controller/v2/inventories/2/"
    credentials:
      - name: "Payments Target SSH"
        type: "ssh"
        api_url: "https://aap.example.com/api/controller/v2/credentials/3/"
    access:
      - organization: "Payments"
        team: "Payments Developers"
        level: "execute"
        sources:
          - "direct"
```

Access levels are reduced to `view`, `execute`, or `admin`. Sources are
`direct`, `organization_role`, or both. A recently used template with no
current team assignment is retained with `access: []`.

The credential entries contain only names, types, and API URLs. The reporter
does not request or export passwords, tokens, private keys, or credential
inputs.

## What the report means

The time filter uses the Job Template's `last_job_run` field rather than
retained job records. Normal job cleanup can delete job records without
preventing the template from appearing, provided AAP retains that timestamp.

Team access is a snapshot of current RBAC. It cannot reconstruct a role that
was revoked earlier in the reporting period. The organization on a template is
its owning organization; the organization on an access entry is that team's
home organization.

The script supports the Controller 4.6-4.8 API layout used by AAP 2.5-2.7. It
uses Controller RBAC endpoints for Controller 4.6 and Gateway RBAC endpoints
for later supported versions.

## Git and security

`lab.env` and the default `team-resources.yaml` output are excluded by the
repository's `.gitignore`. Never commit AAP passwords or tokens. Although the
report contains no credential secrets, it does contain organization, team,
inventory, project, credential, and template names; review that operational
metadata before publishing a generated report.

## Troubleshooting

- `AAP_URL is not set`: export the Platform Gateway URL, including `https://`.
- `set AAP_USERNAME/AAP_PASSWORD or AAP_TOKEN`: configure one authentication
  method. A token takes precedence when both methods are set.
- Certificate verification errors: install the correct CA certificate. Use
  `AAP_VALIDATE_CERTS=false` only for an isolated lab.
- HTTP 401 or 403: the account is invalid or cannot read the required AAP
  Controller and RBAC endpoints.
- An empty `job_templates` list means no template has a `last_job_run` inside
  the selected period.
