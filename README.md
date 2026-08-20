# AAP Job and Workflow Template Report

A small, read-only Python script that reports:

- Job and Workflow Templates and their AAP URLs
- attached inventories and credentials (names and URLs only)
- configured workflow steps and their success, failure, and always paths
- teams and users with current view, execute, or admin permission
- recently used, unused, or all templates

It writes simple YAML and, optionally, a dependency-free PDF. The PDF starts
with an overview and the consolidated name/URL summary. It never exports
credential inputs or changes AAP.

## Setup

Python 3.9 or newer is required. The shell wrapper checks aliases first and then
executables named `python3`, `python`, and `py`, using the first supported
launcher it finds. Set the Platform Gateway URL and either a token:

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

# These settings make the entire two-report run non-interactive.
AAP_REPORT_DAYS=365
AAP_OUTPUT_ROOT=output
AAP_USED_CHECK_RBAC=true
AAP_UNUSED_CHECK_RBAC=false
```

Run `./run-report.sh` after saving the file. Set `AAP_ENV_FILE=/path/to/file`
to load a different file. Environment files use normal shell assignment syntax.

## Run

The shell wrapper automatically generates both reports for the same period:

```bash
./run-report.sh
```

With a 365-day period, it creates:

```text
output/
  2026-08-20_14-30-00-used-and-unused-365-day-report/
    used/
      used-job-templates.yaml
      used-job-templates.pdf
    unused/
      unused-job-templates.yaml
      unused-job-templates.pdf
```

The used report checks RBAC by default. The unused report skips RBAC by default.
Set `AAP_USED_CHECK_RBAC` or `AAP_UNUSED_CHECK_RBAC` to override either choice.
The direct Python command remains available for individual reports; run it with
`--help` for its options.

API requests are deliberately low-impact: collections use pages of 50 and every
request is delayed by one second. Temporary HTTP failures are retried only twice,
after at least 60 and 120 seconds. RBAC reports can therefore take several minutes
in large environments; protecting AAP is prioritized over report speed.

## Output

The PDF overview counts unique inventories and credentials, even when several
templates use the same resource. Names in the PDF summary link to their detail
sections later in the report. YAML URLs are Controller API endpoints; the PDF
keeps human-facing AAP UI URLs. The YAML summary is deliberately first and
contains only each matching name and URL:

```yaml
summary:
  - name: "Deploy Payments"
    url: "https://aap.example.com/api/controller/v2/job_templates/24/"
  - name: "Release Payments"
    url: "https://aap.example.com/api/controller/v2/workflow_job_templates/8/"

job_templates:
  - name: "Deploy Payments"
    url: "https://aap.example.com/api/controller/v2/job_templates/24/"
    last_run: "2026-08-12T15:20:12Z"
    inventory:
      name: "Payments Production"
      url: "https://aap.example.com/api/controller/v2/inventories/2/"
    credentials:
      - name: "Payments SSH"
        url: "https://aap.example.com/api/controller/v2/credentials/3/"
    permissions:
      - type: "team"
        name: "Payments Operators"
        organization: "Payments"
        level: "execute"
      - type: "user"
        name: "alice"
        level: "admin"

workflow_job_templates:
  - name: "Release Payments"
    url: "https://aap.example.com/api/controller/v2/workflow_job_templates/8/"
    last_run: "2026-08-12T15:21:00Z"
    inventory: null
    steps:
      - identifier: "deploy"
        name: "Deploy Payments"
        type: "job_template"
        url: "https://aap.example.com/api/controller/v2/job_templates/24/"
        success: []
        failure: []
        always: []
```

The report uses `last_job_run`; it does not depend on retained job history. A
workflow used during the report period makes every configured child Job Template
used, even when that branch did not run or the child has no `last_job_run` value.
Nested workflows and their children are followed recursively. Those children are
therefore included in the used report and excluded from the unused report.
Permissions are the current direct or owning-organization grants reported by
AAP, not a reconstruction of permissions that were revoked in the past. On
Gateway-based versions, users are cross-referenced with Controller users by
`ansible_id` and then username so legacy Controller identities are retained.

The script supports the Controller 4.6-4.8 API layouts used by AAP 2.5-2.7.
Controller 4.6 RBAC is read from Controller; later versions use Gateway RBAC.

## Test

```bash
python3 -m unittest discover -s tests -v
```
