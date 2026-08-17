# AAP Job Template Access Report

These read-only Python utilities provide two views of Ansible Automation
Platform Job Templates: a recent-use resource/readiness report and a complete
Gateway-plus-Controller identity-access audit. Both produce YAML and a
dependency-free PDF, and neither changes AAP data.

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

The easiest option is the guided shell wrapper. It lets you run either report
or both, then prompts for the connection, authentication, certificate
validation, and relevant output settings, so you do not need to export
environment variables:

```bash
./run-report.sh
```

Password and token input is hidden and is used only by the analyzer process;
the wrapper does not write credentials to disk.

While a report is running, the wrapper prints its current report name and an
elapsed-time heartbeat every 15 seconds, followed by an explicit finished or
failed status. Set `AAP_STATUS_INTERVAL` to a positive number of seconds to
change the heartbeat interval.

Choose report 1 for the recently-used template analysis. Choose report 2 for
the complete Job Template identity-access audit described below. Choose report
3 to run both sequentially with one connection and authentication session,
producing two YAML files and two PDF reports.

### AAP 2.4 → 2.5 Job Template identity-access audit

AAP 2.5 separates platform identities and platform roles in Gateway from
Controller-owned automation resources and permissions. The identity audit
reads both API surfaces and correlates the evidence into effective Job
Template access:

- It audits organizations, teams, users, role definitions, team role
  assignments, and user role assignments under both `/api/gateway/v1/` and
  `/api/controller/v2/`.
- It scans every Controller Job Template; the recent-run filter does not apply.
- It always follows advertised legacy `related.roles` links for users and
  teams, preserving evidence that may not have migrated cleanly from 2.4.
- It records direct team and user grants plus organization-inherited grants
  that confer access to an owning organization's Job Templates.
- It collects team membership independently from Gateway and Controller,
  derives it from Team Member/Admin assignments when needed, and reports
  disagreement as membership drift.
- It summarizes platform and Controller administrators and auditors separately
  instead of expanding global access onto every template.
- It correlates identities with `ansible_id` first, then username for users and
  organization/name for teams. Ambiguous matches remain separate and appear in
  diagnostics.

Run it from the interactive wrapper by selecting option 2, or directly after
setting the connection environment variables:

```bash
python3 scripts/export_job_template_identity_access.py \
  --yaml-output job-template-identity-access.yaml \
  --pdf-output job-template-identity-access.pdf
```

`scripts/export_team_job_template_roles.py` remains as a compatibility launcher
and accepts the same arguments. Both output formats use only Python's standard
library. The YAML contains endpoint coverage, per-template team and direct-user
grants, global access, membership drift, unresolved identities, and collection
errors. The PDF presents the same audit in coverage, template, and diagnostic
sections with wrapping, repeated headers, pagination, and page numbers.

The report never emits a Gateway-to-Controller ID mapping table, raw UUID
comparison table, email address, authentication identifier, or credential
data. If a required endpoint cannot be read, both artifacts are still written
and visibly marked partial; the command then exits with status 2.

### Environment-variable setup

For automation or non-interactive use, configure the environment as described
above and run from the repository root:

```bash
python3 scripts/export_recent_team_resources.py \
  --days 365 \
  --output team-resources.yaml \
  --pdf-output team-resources.pdf
```

The YAML is the machine-readable source. The PDF companion adds a summary, a
compact template table, and detailed team-access tables with automatic text
wrapping, repeated table headers, and pagination. YAML continues to expose
stable API and UI URLs for automation.

Omit `--output` to write YAML to standard output. Omit `--pdf-output` if
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

### PDF report

The PDF begins with summary counts and a compact recently-used template table.
Each detailed section lists the template metadata, credentials, effective team
access, grant path, and launch readiness. Templates without team access are
called out with an empty access table. The PDF is generated using only Python's
standard library; no PDF package is required.

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

`lab.env`, `team-resources.yaml`, `team-resources.md`, `team-resources.pdf`,
`job-template-identity-access.yaml`, `job-template-identity-access.pdf`, and
the legacy `team-job-template-roles.pdf` name are excluded by the repository's
`.gitignore`. Never commit AAP passwords or tokens. Although the reports contain
no credential secrets or email addresses, they do contain usernames plus
organization, team, inventory, project, credential, and template names; review
that operational metadata before publishing a generated report.

## Troubleshooting

- `AAP_URL is not set`: export the Platform Gateway URL, including `https://`.
- `set AAP_USERNAME/AAP_PASSWORD or AAP_TOKEN`: configure one authentication
  method. A token takes precedence when both methods are set.
- Certificate verification errors: install the correct CA certificate. Use
  `AAP_VALIDATE_CERTS=false` only for an isolated lab.
- HTTP 401 or 403: the account is invalid or cannot read one or more required
  Gateway, Controller, or RBAC endpoints. The identity audit writes partial
  artifacts with endpoint-specific errors and exits nonzero.
- An empty `job_templates` list means no template has a `last_job_run` inside
  the selected period in report 1. Report 2 audits every Job Template.
