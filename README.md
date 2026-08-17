# AAP Job Template Access Report

This read-only Python utility exports one YAML record for every Ansible
Automation Platform Job Template run during a selected period. Each record
contains the template's related resources and the teams that can currently
access it. When a template prompts for inventory or credentials at launch, the
report also provides a conservative team-derived readiness assessment.

## Requirements

- Python 3.9 or newer
- Network access to the AAP Platform Gateway
- An AAP account allowed to read Controller resources and RBAC assignments

The interactive shell wrapper checks `python3`, `python`, and `py` in that
order and uses the first launcher that reports Python 3.9 or newer.

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

### Interactive setup

The easiest option is the guided shell wrapper. It first offers two reports,
then prompts for the connection, authentication, certificate validation, and
relevant output settings, so you do not need to export environment variables:

```bash
./run-report.sh
```

Password and token input is hidden and is used only by the analyzer process;
the wrapper does not write credentials to disk.

Choose report 1 for the existing recently-used template analysis. Choose
report 2 for the AAP 2.5 Controller team-role report described below. Choose
report 3 to run both sequentially with the same connection and authentication,
producing the YAML, Markdown, and PDF outputs in one run.

### AAP 2.5 team → role → Job Template report

AAP 2.5 gives a team a UUID in Platform Gateway while Controller retains the
team's older integer ID for Job Template permissions. The dedicated report
handles that split automatically:

- It scans teams from `/api/controller/v2/teams/`.
- It follows each Controller team's `roles` relationship using the integer
  Controller ID.
- It retains only roles whose resource is a Job Template.
- It matches the same team in Gateway by organization name and team name, with
  a unique-name fallback, and records the Gateway UUID for traceability.
- It never passes a Controller integer ID to Gateway or a Gateway UUID to
  Controller.

Run it from the interactive wrapper by selecting option 2, or directly after
setting the connection environment variables:

```bash
python3 scripts/export_team_job_template_roles.py \
  --output team-job-template-roles.pdf
```

The PDF is generated directly with Python's standard library; it does not use
ReportLab, PyPDF, or another installed package. It contains a clean
`Organization → Team → Role → Job Template` table and a separate
Controller-ID-to-Gateway-UUID mapping table, with automatic text wrapping,
repeated table headers, pagination, and page numbers.
If Gateway team listing is unavailable, Controller permissions are still
reported because Controller is the source of truth for these assignments.
Only direct Job Template role records are included; roles attached to
inventories, credentials, projects, workflows, or other resource types are
filtered out.

### Environment-variable setup

For automation or non-interactive use, configure the environment as described
above and run from the repository root:

```bash
python3 scripts/export_recent_team_resources.py \
  --days 365 \
  --output team-resources.yaml \
  --markdown-output team-resources.md
```

The YAML is the machine-readable source. The optional Markdown companion adds
a summary, a compact template table, friendly `([view in AAP](...))` UI links,
and detailed team-access tables for easy review in GitHub or any Markdown
viewer. YAML continues to expose stable API URLs for automation.

Omit `--output` to write YAML to standard output. Omit `--markdown-output` if
you only need YAML. `--days` must be at least 1 and defaults to 365.

The command only sends HTTP `GET` requests. It does not launch jobs, modify
RBAC, change templates, or clean up AAP data.

## Output

### YAML

```yaml
job_templates:
  - name: "Payments | Deploy Development"
    owning_organization: "Payments"
    ui_url: "https://aap.example.com/execution/templates/job-template/24/details"
    api_url: "https://aap.example.com/api/controller/v2/job_templates/24/"
    last_job_run: "2026-08-12T15:20:12Z"
    playbook: "payments/playbooks/deploy.yml"
    project:
      name: "Payments Automation"
      ui_url: "https://aap.example.com/execution/projects/8/details"
      api_url: "https://aap.example.com/api/controller/v2/projects/8/"
    inventory:
      name: "Payments Development"
      ui_url: "https://aap.example.com/execution/inventories/inventory/2/details"
      api_url: "https://aap.example.com/api/controller/v2/inventories/2/"
    credentials:
      - name: "Payments Target SSH"
        type: "ssh"
        ui_url: "https://aap.example.com/execution/credentials/3/details"
        api_url: "https://aap.example.com/api/controller/v2/credentials/3/"
    launch_prompts:
      inventory:
        enabled: true
        required: true
        default: null
      credentials:
        enabled: true
        required: false
        defaults:
          - name: "Payments Target SSH"
            type: "ssh"
            ui_url: "https://aap.example.com/execution/credentials/3/details"
            api_url: "https://aap.example.com/api/controller/v2/credentials/3/"
    access:
      - team_organization: "Payments"
        team: "Payments Developers"
        level: "execute"
        can_execute: true
        sources:
          - "job_template_assignment"
        launch_readiness:
          status: "attention"
          inventory: "team_access_not_evidenced"
          credentials: "default_prompt"
```

### Markdown summary

```markdown
# AAP Job Template Access Report

## Summary

| Metric | Count |
| --- | ---: |
| Recently used Job Templates | 1 |
| Owning organizations | 1 |
| Teams with access | 4 |
| Templates with no team access | 0 |
| Templates with launch prompts | 1 |
| Required selections without defaults | 1 |
| Cross-organization team grants | 1 |
| Team readiness entries needing review | 1 |

## Templates

| Organization | Job Template | Last run | Project | Inventory | Teams |
| --- | --- | --- | --- | --- | ---: |
| Payments | Payments \| Deploy Development ([view in AAP](https://aap.example.com/execution/templates/job-template/24/details)) | 2026-08-12T15:20:12Z | Payments Automation ([view in AAP](https://aap.example.com/execution/projects/8/details)) | Payments Development ([view in AAP](https://aap.example.com/execution/inventories/inventory/2/details)) | 4 |
```

The Markdown summary also counts effective admin, execute, and view grants.
Each detailed section lists credentials and groups teams by their home
organization. Each group is marked as either the same as the template owner or
cross-organization access. The table shows effective access, grant path, and
launch readiness. Templates without team access are called out for attention.

Markdown links target the unified Platform Gateway UI under `/execution/`, not
the JSON API. Configure `AAP_URL` with the Gateway URL so these links open the
correct AAP 2.5-2.7 interface.

Access levels are reduced to `view`, `execute`, or `admin`. `can_execute` is
retained separately: a custom change-only role can display as `admin` without
being misrepresented as executable. Sources are `job_template_assignment`,
`owning_organization_assignment`, or both. A recently used template with no
current team assignment is retained with `access: []`.

### Launch prompts and readiness

For a recent template with inventory or credential prompting enabled, the
report sends a read-only `GET` to that template's `/launch/` endpoint. It
distinguishes fixed configuration, prompted defaults, required selection
without a default, and optional credentials.

Readiness is intentionally team-only and conservative:

- `fixed`: prompting is disabled and the template configuration applies.
- `default_prompt`: a launcher may accept the configured default.
- `team_selection`: a matching team `use` grant was found, directly or through
  an applicable organization role.
- `optional`: no credential selection is required.
- `team_access_not_evidenced`: a required team-provided selection was not
  found.
- `not_applicable`: the team does not have Job Template execute permission.

The overall status is `ready`, `attention`, or `not_applicable`. `attention`
is not a definitive denial: a user's direct roles may provide additional
inventory or credential access that the team-only report intentionally does
not enumerate. The reporter does not attempt to prove credential-type
compatibility or enumerate users.

Every template and related resource includes both a human-facing `ui_url` and
a stable machine-facing `api_url`. This makes the YAML useful in review emails
while preserving the API reference for automation.

The credential entries contain only names, types, UI URLs, and API URLs. The
reporter does not request or export passwords, tokens, private keys, or
credential inputs.

## What the report means

The time filter uses the Job Template's `last_job_run` field rather than
retained job records. Normal job cleanup can delete job records without
preventing the template from appearing, provided AAP retains that timestamp.

Team access is a snapshot of current RBAC. It cannot reconstruct a role that
was revoked earlier in the reporting period. `owning_organization` is the
template owner; `team_organization` is the team's home organization.

The script supports the Controller 4.6-4.8 API layout used by AAP 2.5-2.7. It
uses Controller RBAC endpoints for Controller 4.6 and Gateway RBAC endpoints
for later supported versions.

## Git and security

`lab.env`, `team-resources.yaml`, `team-resources.md`, and
`team-job-template-roles.pdf` are excluded by the repository's `.gitignore`.
Never commit AAP passwords or tokens. Although the reports contain no
credential secrets, they do contain organization, team, inventory, project,
credential, and template names; review that operational metadata before
publishing a generated report.

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
