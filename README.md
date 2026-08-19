# AAP Job Template Report

A small, read-only Python script that reports:

- Job Templates and their AAP URLs
- attached inventories and credentials (names and URLs only)
- teams and users with current view, execute, or admin permission
- recently used, unused, or all Job Templates

It writes simple YAML and, optionally, a dependency-free PDF. It never exports
credential inputs or changes AAP.

## Setup

Python 3.9 or newer is required. Set the Platform Gateway URL and either a token:

```bash
export AAP_URL=https://aap.example.com
export AAP_TOKEN='your-token'
```

or a username and password:

```bash
export AAP_URL=https://aap.example.com
export AAP_USERNAME=admin
export AAP_PASSWORD='your-password'
```

TLS certificates are validated by default. For an isolated lab with a self-signed
certificate, set `AAP_VALIDATE_CERTS=false`.

## Run

Job Templates run in the last year (the default):

```bash
python3 scripts/export_recent_team_resources.py \
  --output job-templates.yaml \
  --pdf-output job-templates.pdf
```

Job Templates that have **not** run in the last year, including never-run jobs:

```bash
python3 scripts/export_recent_team_resources.py \
  --unused \
  --output unused-job-templates.yaml \
  --pdf-output unused-job-templates.pdf
```

Use `--days 90` to change the cutoff or `--all` to remove the date filter.
Omit `--output` to write YAML to stdout. The guided `./run-report.sh` wrapper
prompts for the same settings.

## Output

The summary is deliberately first and contains only each matching name and URL:

```yaml
summary:
  - name: "Deploy Payments"
    url: "https://aap.example.com/execution/templates/job-template/24/details"

job_templates:
  - name: "Deploy Payments"
    url: "https://aap.example.com/execution/templates/job-template/24/details"
    last_run: "2026-08-12T15:20:12Z"
    inventory:
      name: "Payments Production"
      url: "https://aap.example.com/execution/inventories/inventory/2/details"
    credentials:
      - name: "Payments SSH"
        url: "https://aap.example.com/execution/credentials/3/details"
    permissions:
      - type: "team"
        name: "Payments Operators"
        organization: "Payments"
        level: "execute"
      - type: "user"
        name: "alice"
        level: "admin"
```

The report uses `last_job_run`; it does not depend on retained job history.
Permissions are the current direct or owning-organization grants reported by
AAP, not a reconstruction of permissions that were revoked in the past.

The script supports the Controller 4.6-4.8 API layouts used by AAP 2.5-2.7.
Controller 4.6 RBAC is read from Controller; later versions use Gateway RBAC.

## Test

```bash
python3 -m unittest discover -s tests -v
```
