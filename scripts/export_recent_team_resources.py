#!/usr/bin/env python3
"""Export recently used Job Templates and their current team access.

Output is deliberately compact:

job_templates:
  - name: Job Template
    organization: Owning Organization
    api_url: https://aap.example/api/controller/v2/job_templates/1/
    project: {name, api_url}
    inventory: {name, api_url}
    credentials: [{name, type, api_url}]
    access: [{organization, team, level, sources}]

This is a current-access report filtered by Job Template.last_job_run. It is
not a historical reconstruction of permissions that were later revoked.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any, Optional


CONTROLLER = "/api/controller/v2"
GATEWAY = "/api/gateway/v1"


class ExportError(RuntimeError):
    pass


class Client:
    def __init__(self) -> None:
        self.base_url = os.environ.get("AAP_URL", "").rstrip("/")
        token = os.environ.get("AAP_TOKEN", "")
        username = os.environ.get("AAP_USERNAME", "")
        password = os.environ.get("AAP_PASSWORD", "")
        if not self.base_url:
            raise ExportError("AAP_URL is not set")
        if token:
            self.authorization = f"Bearer {token}"
        elif username and password:
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            self.authorization = f"Basic {encoded}"
        else:
            raise ExportError("set AAP_USERNAME/AAP_PASSWORD or AAP_TOKEN")
        verify = os.environ.get("AAP_VALIDATE_CERTS", "true").lower() == "true"
        self.context = None if verify else ssl._create_unverified_context()

    def get(
        self,
        path_or_url: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if path_or_url.startswith(("http://", "https://")):
            url = path_or_url
        else:
            url = f"{self.base_url}{path_or_url}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "Authorization": self.authorization},
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise ExportError(f"GET {url} returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ExportError(f"GET {url} failed: {exc.reason}") from exc

    def list(self, path: str, **params: Any) -> list[dict[str, Any]]:
        params["page_size"] = 200
        payload = self.get(path, params)
        results = list(payload.get("results", []))
        while payload.get("next"):
            payload = self.get(payload["next"])
            results.extend(payload.get("results", []))
        return results


def relation_id(value: Any) -> Optional[int]:
    if isinstance(value, dict):
        value = value.get("id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def organization_name(item: dict[str, Any], organizations: dict[int, str]) -> str:
    summary = item.get("summary_fields", {}).get("organization", {})
    if summary.get("name"):
        return str(summary["name"])
    return organizations.get(relation_id(item.get("organization")) or -1, "Unknown Organization")


def yaml_string(value: str) -> str:
    """JSON strings are valid YAML and avoid ambiguous names such as yes/no."""
    return json.dumps(value, ensure_ascii=False)


def absolute_api_url(client: Client, value: Any, fallback: str) -> str:
    path = str(value or fallback)
    if path.startswith(("http://", "https://")):
        return path
    return f"{client.base_url}/{path.lstrip('/')}"


def ui_url(client: Client, endpoint: str, item_id: Any, kind: str = "") -> str:
    routes = {
        "job_templates": f"/execution/templates/job-template/{item_id}/details",
        "projects": f"/execution/projects/{item_id}/details",
        "credentials": f"/execution/credentials/{item_id}/details",
    }
    if endpoint == "inventories":
        inventory_type = {
            "smart": "smart-inventory",
            "constructed": "constructed-inventory",
        }.get(kind, "inventory")
        path = f"/execution/inventories/{inventory_type}/{item_id}/details"
    else:
        path = routes[endpoint]
    return f"{client.base_url}{path}"


def summarized_relation(
    client: Client,
    summary: Any,
    endpoint: str,
) -> Optional[dict[str, str]]:
    if not isinstance(summary, dict) or not summary.get("id"):
        return None
    relation = {
        "name": str(summary.get("name") or f"ID {summary['id']}"),
        "api_url": absolute_api_url(
            client,
            summary.get("url"),
            f"{CONTROLLER}/{endpoint}/{summary['id']}/",
        ),
        "ui_url": ui_url(
            client,
            endpoint,
            summary["id"],
            str(summary.get("kind") or ""),
        ),
    }
    return relation


def template_resource(
    client: Client,
    template: dict[str, Any],
    organizations: dict[int, str],
) -> dict[str, Any]:
    """Return useful non-secret metadata already exposed by the template API."""
    template_id = template["id"]
    summary = template.get("summary_fields", {})
    resource: dict[str, Any] = {
        "name": str(template["name"]),
        "organization": organization_name(template, organizations),
        "api_url": absolute_api_url(
            client,
            template.get("url"),
            f"{CONTROLLER}/job_templates/{template_id}/",
        ),
        "ui_url": ui_url(client, "job_templates", template_id),
    }
    if template.get("last_job_run"):
        resource["last_job_run"] = str(template["last_job_run"])
    if template.get("playbook"):
        resource["playbook"] = str(template["playbook"])

    project = summarized_relation(client, summary.get("project"), "projects")
    inventory = summarized_relation(client, summary.get("inventory"), "inventories")
    if project:
        resource["project"] = project
    if inventory:
        resource["inventory"] = inventory

    credentials: list[dict[str, str]] = []
    for credential in summary.get("credentials", []):
        relation = summarized_relation(client, credential, "credentials")
        if not relation:
            continue
        credential_type = credential.get("credential_type")
        if isinstance(credential_type, dict):
            credential_type = credential_type.get("name")
        credential_type = credential_type or credential.get("kind")
        if credential_type:
            relation["type"] = str(credential_type)
        credentials.append(relation)
    if credentials:
        resource["credentials"] = sorted(
            credentials, key=lambda item: item["name"].casefold()
        )
    return resource


def render_relation(lines: list[str], indent: str, relation: dict[str, str]) -> None:
    lines.append(f"{indent}name: {yaml_string(relation['name'])}")
    if relation.get("type"):
        lines.append(f"{indent}type: {yaml_string(relation['type'])}")
    lines.append(f"{indent}api_url: {yaml_string(relation['api_url'])}")


def render_yaml(report: list[dict[str, Any]]) -> str:
    if not report:
        return "job_templates: []\n"
    lines = ["job_templates:"]
    for resource in report:
        lines.append(f"  - name: {yaml_string(resource['name'])}")
        lines.append(f"    organization: {yaml_string(resource['organization'])}")
        lines.append(f"    api_url: {yaml_string(resource['api_url'])}")
        for field in ("last_job_run", "playbook"):
            if resource.get(field):
                lines.append(f"    {field}: {yaml_string(resource[field])}")
        for field in ("project", "inventory"):
            if resource.get(field):
                lines.append(f"    {field}:")
                render_relation(lines, "      ", resource[field])
        if resource.get("credentials"):
            lines.append("    credentials:")
            for credential in resource["credentials"]:
                lines.append(f"      - name: {yaml_string(credential['name'])}")
                if credential.get("type"):
                    lines.append(f"        type: {yaml_string(credential['type'])}")
                lines.append(f"        api_url: {yaml_string(credential['api_url'])}")
        if not resource["access"]:
            lines.append("    access: []")
            continue
        lines.append("    access:")
        for access in resource["access"]:
            lines.append(f"      - organization: {yaml_string(access['organization'])}")
            lines.append(f"        team: {yaml_string(access['team'])}")
            lines.append(f"        level: {yaml_string(access['level'])}")
            lines.append("        sources:")
            for source in access["sources"]:
                lines.append(f"          - {yaml_string(source)}")
    return "\n".join(lines) + "\n"


def markdown_text(value: Any) -> str:
    """Escape API-provided text for safe use in Markdown tables and prose."""
    return html.escape(str(value), quote=False).replace("|", "&#124;").replace("\n", " ")


def markdown_ui_reference(relation: dict[str, Any]) -> str:
    name = markdown_text(relation["name"])
    url = str(relation.get("ui_url") or relation["api_url"])
    url = url.replace(" ", "%20").replace(")", "%29")
    return f"{name} ([view in AAP]({url}))"


def render_markdown(report: list[dict[str, Any]], days: int, cutoff: str) -> str:
    """Render a concise human-readable companion to the YAML report."""
    organizations = {item["organization"] for item in report}
    teams = {
        (access["organization"], access["team"])
        for item in report
        for access in item["access"]
    }
    level_counts = {
        level: sum(
            access["level"] == level
            for item in report
            for access in item["access"]
        )
        for level in ("admin", "execute", "view")
    }
    without_access = sum(not item["access"] for item in report)

    lines = [
        "# AAP Job Template Access Report",
        "",
        (
            f"> Current team access to Job Templates with a last run in the past "
            f"{days} days (cutoff `{cutoff}`)."
        ),
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Recently used Job Templates | {len(report)} |",
        f"| Owning organizations | {len(organizations)} |",
        f"| Teams with access | {len(teams)} |",
        f"| Templates with no team access | {without_access} |",
        f"| Admin grants | {level_counts['admin']} |",
        f"| Execute grants | {level_counts['execute']} |",
        f"| View grants | {level_counts['view']} |",
        "",
        "## Templates",
        "",
    ]
    if not report:
        lines.extend(["No Job Templates matched the selected period.", ""])
    else:
        lines.extend(
            [
                "| Organization | Job Template | Last run | Project | Inventory | Teams |",
                "| --- | --- | --- | --- | --- | ---: |",
            ]
        )
        for resource in report:
            project = resource.get("project")
            inventory = resource.get("inventory")
            lines.append(
                "| {organization} | {template} | {last_run} | {project} | "
                "{inventory} | {teams} |".format(
                    organization=markdown_text(resource["organization"]),
                    template=markdown_ui_reference(resource),
                    last_run=markdown_text(resource.get("last_job_run", "Unknown")),
                    project=markdown_ui_reference(project) if project else "—",
                    inventory=markdown_ui_reference(inventory) if inventory else "—",
                    teams=len(resource["access"]),
                )
            )
        lines.append("")

    lines.extend(["## Details", ""])
    for resource in report:
        detail_heading = (
            f"### {markdown_text(resource['organization'])} — "
            f"{markdown_text(resource['name'])}"
        )
        lines.extend(
            [
                detail_heading,
                "",
                f"- **Job Template:** {markdown_ui_reference(resource)}",
                f"- **Last run:** `{markdown_text(resource.get('last_job_run', 'Unknown'))}`",
            ]
        )
        if resource.get("playbook"):
            lines.append(f"- **Playbook:** `{markdown_text(resource['playbook'])}`")
        for label, field in (("Project", "project"), ("Inventory", "inventory")):
            if resource.get(field):
                lines.append(
                    f"- **{label}:** {markdown_ui_reference(resource[field])}"
                )
        credentials = resource.get("credentials", [])
        if credentials:
            credential_links = []
            for credential in credentials:
                credential_type = credential.get("type")
                suffix = f" (`{markdown_text(credential_type)}`)" if credential_type else ""
                credential_links.append(
                    f"{markdown_ui_reference(credential)}{suffix}"
                )
            lines.append(f"- **Credentials:** {', '.join(credential_links)}")
        lines.append("")
        if resource["access"]:
            lines.extend(
                [
                    "| Team organization | Team | Access | Source |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for access in resource["access"]:
                sources = ", ".join(
                    source.replace("organization_role", "organization role")
                    for source in access["sources"]
                )
                lines.append(
                    f"| {markdown_text(access['organization'])} | "
                    f"{markdown_text(access['team'])} | {access['level']} | {sources} |"
                )
        else:
            lines.append("**Attention:** No current team access was found.")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            (
                "This is a snapshot of current team RBAC filtered by Job Template "
                "`last_job_run`; it is not a historical reconstruction of revoked access."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def effective_access_level(permissions: set[str]) -> Optional[str]:
    if permissions & {
        "awx.add_jobtemplate",
        "awx.change_jobtemplate",
        "awx.delete_jobtemplate",
    }:
        return "admin"
    if "awx.execute_jobtemplate" in permissions:
        return "execute"
    if "awx.view_jobtemplate" in permissions:
        return "view"
    return None


def rbac_base(client: Client) -> str:
    config = client.get(f"{CONTROLLER}/config/")
    version = str(config.get("version", ""))
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except (ValueError, TypeError) as exc:
        raise ExportError(f"could not determine Controller version from {version!r}") from exc
    # Controller 4.6 (AAP 2.5) exposes DAB role assignments through Controller.
    # Later Gateway-integrated Controller releases centralize them in Gateway.
    return CONTROLLER if (major, minor) == (4, 6) else GATEWAY


def build_report(client: Client, days: int) -> tuple[list[dict[str, Any]], str]:
    cutoff_date = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    cutoff = cutoff_date.isoformat(timespec="seconds").replace("+00:00", "Z")
    recent = client.list(
        f"{CONTROLLER}/job_templates/",
        last_job_run__gte=cutoff,
        order_by="name",
    )
    recent_by_id = {str(item["id"]): item for item in recent}
    recent_by_ansible_id = {
        str(item.get("summary_fields", {}).get("resource", {}).get("ansible_id")): item
        for item in recent
        if item.get("summary_fields", {}).get("resource", {}).get("ansible_id")
    }
    base = rbac_base(client)
    organizations_list = client.list(f"{base}/organizations/")
    organizations = {int(item["id"]): str(item["name"]) for item in organizations_list}
    templates_by_org: dict[str, list[dict[str, Any]]] = defaultdict(list)
    report_by_id: dict[str, dict[str, Any]] = {}
    access_by_template: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for template in recent:
        template_id = str(template["id"])
        resource = template_resource(client, template, organizations)
        report_by_id[template_id] = resource
        templates_by_org[resource["organization"]].append(template)

    teams = client.list(f"{base}/teams/")
    teams_by_id = {
        int(item["id"]): (
            organization_name(item, organizations),
            str(item["name"]),
        )
        for item in teams
    }
    definitions = {
        int(item["id"]): item for item in client.list(f"{base}/role_definitions/")
    }
    assignments = client.list(f"{base}/role_team_assignments/")

    level_rank = {"view": 1, "execute": 2, "admin": 3}
    source_rank = {"direct": 1, "organization_role": 2}

    def add_access(
        template: dict[str, Any],
        team_id: int,
        team_org: str,
        team_name: str,
        level: str,
        source: str,
    ) -> None:
        template_access = access_by_template[str(template["id"])]
        existing = template_access.get(team_id)
        if existing is None:
            template_access[team_id] = {
                "organization": team_org,
                "team": team_name,
                "level": level,
                "sources": {source},
            }
            return
        if level_rank[level] > level_rank[existing["level"]]:
            existing["level"] = level
        existing["sources"].add(source)

    for assignment in assignments:
        team_id = relation_id(assignment.get("team"))
        definition_id = relation_id(assignment.get("role_definition"))
        if team_id not in teams_by_id or definition_id not in definitions:
            continue
        team_org, team_name = teams_by_id[team_id]
        definition = definitions[definition_id]
        permissions = set(definition.get("permissions", []))
        level = effective_access_level(permissions)
        if level is None:
            continue
        content_type = str(
            assignment.get("content_type") or definition.get("content_type") or ""
        )

        if content_type == "awx.jobtemplate":
            template = recent_by_id.get(str(assignment.get("object_id")))
            if template is None and assignment.get("object_ansible_id"):
                template = recent_by_ansible_id.get(str(assignment["object_ansible_id"]))
            if template:
                add_access(
                    template, team_id, team_org, team_name, level, "direct"
                )
            continue

        # Organization-level roles such as Admin, Execute, or Audit can confer
        # access to every Job Template in that organization.
        if content_type == "shared.organization":
            object_org = organizations.get(relation_id(assignment.get("object_id")) or -1)
            if object_org is None:
                object_org = (
                    assignment.get("summary_fields", {})
                    .get("content_object", {})
                    .get("name")
                )
            if object_org:
                for template in templates_by_org.get(str(object_org), []):
                    add_access(
                        template,
                        team_id,
                        team_org,
                        team_name,
                        level,
                        "organization_role",
                    )

    report: list[dict[str, Any]] = []
    for template_id, resource in report_by_id.items():
        access_entries = access_by_template.get(template_id, {}).values()
        resource["access"] = sorted(
            (
                {
                    **entry,
                    "sources": sorted(
                        entry["sources"], key=lambda source: source_rank[source]
                    ),
                }
                for entry in access_entries
            ),
            key=lambda entry: (
                entry["organization"].casefold(),
                entry["team"].casefold(),
            ),
        )
        report.append(resource)
    report.sort(
        key=lambda resource: (
            resource["organization"].casefold(),
            resource["name"].casefold(),
        )
    )
    return report, cutoff


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export recently used Job Templates and their current team access."
    )
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--output", default="-", help="YAML file path; default is stdout")
    parser.add_argument(
        "--markdown-output",
        help="optional human-readable Markdown report path",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    try:
        report, cutoff = build_report(Client(), args.days)
        rendered = render_yaml(report)
        if args.output == "-":
            sys.stdout.write(rendered)
        else:
            with open(args.output, "w", encoding="utf-8") as target:
                target.write(rendered)
            print(f"Wrote {args.output} (cutoff {cutoff})", file=sys.stderr)
        if args.markdown_output:
            with open(args.markdown_output, "w", encoding="utf-8") as target:
                target.write(render_markdown(report, args.days, cutoff))
            print(f"Wrote {args.markdown_output} (cutoff {cutoff})", file=sys.stderr)
    except (ExportError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
