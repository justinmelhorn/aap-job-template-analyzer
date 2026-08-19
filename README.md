# AAP Job Template Report

A small, read-only Python script that reports:

- Job Templates and their AAP URLs
- attached inventories and credentials (names and URLs only)
- teams and users with current view, execute, or admin permission
- recently used, unused, or all Job Templates

It writes simple YAML and, optionally, a dependency-free PDF. The PDF starts
with an overview and the consolidated name/URL summary. It never exports
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

### Environment file

`./run-report.sh` automatically loads `.env`, or `lab.env` when `.env` is not
present. Authentication prompts are skipped when the file contains a complete
token or username/password configuration.

```bash
AAP_URL=https://aap.example.com
AAP_TOKEN='your-token'
AAP_VALIDATE_CERTS=true

# These five settings make the entire run non-interactive.
AAP_REPORT_MODE=unused
AAP_REPORT_DAYS=365
AAP_CHECK_RBAC=false
AAP_YAML_OUTPUT=unused-job-templates.yaml
AAP_PDF_OUTPUT=unused-job-templates.pdf
```

Run `./run-report.sh` after saving the file. Set `AAP_ENV_FILE=/path/to/file`
to load a different file. Environment files use normal shell assignment syntax.

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
  --no-rbac \
  --output unused-job-templates.yaml \
  --pdf-output unused-job-templates.pdf
```

Use `--no-rbac` to skip all permission API calls. The shell wrapper defaults to
skipping RBAC for `unused` reports and checking it for `recent` or `all` reports.
Use `--days 90` to change the cutoff or `--all` to remove the date filter.
Omit `--output` to write YAML to stdout. The guided `./run-report.sh` wrapper
loads saved settings and prompts only for values that are missing.

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
