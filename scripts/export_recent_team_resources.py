#!/usr/bin/env python3
"""Export recently used Job Templates and their current team access.

Output is deliberately compact:

job_templates:
  - name: Job Template
    owning_organization: Owning Organization
    api_url: https://aap.example/api/controller/v2/job_templates/1/
    project: {name, api_url}
    inventory: {name, api_url}
    credentials: [{name, type, api_url}]
    access: [{team_organization, team, level, can_execute, sources, launch_readiness}]

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

from standard_library_pdf import (
    CONTENT_WIDTH as PDF_CONTENT_WIDTH,
    MARGIN as PDF_MARGIN,
    StandardLibraryPdf,
    page_heading as pdf_page_heading,
    table as pdf_table,
    wrapped_lines as pdf_wrapped_lines,
)


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
    launch: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return useful non-secret metadata already exposed by the template API."""
    template_id = template["id"]
    summary = template.get("summary_fields", {})
    resource: dict[str, Any] = {
        "name": str(template["name"]),
        "owning_organization": organization_name(template, organizations),
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
    launch = launch or {}
    resource["launch_prompts"] = {
        "inventory": {
            "enabled": bool(template.get("ask_inventory_on_launch")),
            "required": bool(launch.get("inventory_needed_to_start")),
            "default": inventory,
        },
        "credentials": {
            "enabled": bool(template.get("ask_credential_on_launch")),
            "required": bool(launch.get("credential_needed_to_start")),
            "defaults": resource.get("credentials", []),
        },
    }
    return resource


def render_relation(lines: list[str], indent: str, relation: dict[str, str]) -> None:
    lines.append(f"{indent}name: {yaml_string(relation['name'])}")
    if relation.get("type"):
        lines.append(f"{indent}type: {yaml_string(relation['type'])}")
    lines.append(f"{indent}ui_url: {yaml_string(relation['ui_url'])}")
    lines.append(f"{indent}api_url: {yaml_string(relation['api_url'])}")


def yaml_bool(value: bool) -> str:
    return "true" if value else "false"


def render_prompt_relation(
    lines: list[str],
    indent: str,
    field: str,
    relation: Optional[dict[str, str]],
) -> None:
    if relation is None:
        lines.append(f"{indent}{field}: null")
        return
    lines.append(f"{indent}{field}:")
    render_relation(lines, f"{indent}  ", relation)


def render_yaml(report: list[dict[str, Any]]) -> str:
    if not report:
        return "job_templates: []\n"
    lines = ["job_templates:"]
    for resource in report:
        lines.append(f"  - name: {yaml_string(resource['name'])}")
        lines.append(
            "    owning_organization: "
            f"{yaml_string(resource['owning_organization'])}"
        )
        lines.append(f"    ui_url: {yaml_string(resource['ui_url'])}")
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
                lines.append(f"        ui_url: {yaml_string(credential['ui_url'])}")
                lines.append(f"        api_url: {yaml_string(credential['api_url'])}")
        prompts = resource["launch_prompts"]
        inventory_prompt = prompts["inventory"]
        credential_prompt = prompts["credentials"]
        lines.append("    launch_prompts:")
        lines.append("      inventory:")
        lines.append(
            f"        enabled: {yaml_bool(inventory_prompt['enabled'])}"
        )
        lines.append(
            f"        required: {yaml_bool(inventory_prompt['required'])}"
        )
        render_prompt_relation(
            lines, "        ", "default", inventory_prompt["default"]
        )
        lines.append("      credentials:")
        lines.append(
            f"        enabled: {yaml_bool(credential_prompt['enabled'])}"
        )
        lines.append(
            f"        required: {yaml_bool(credential_prompt['required'])}"
        )
        defaults = credential_prompt["defaults"]
        if defaults:
            lines.append("        defaults:")
            for credential in defaults:
                lines.append(f"          - name: {yaml_string(credential['name'])}")
                if credential.get("type"):
                    lines.append(f"            type: {yaml_string(credential['type'])}")
                lines.append(
                    f"            ui_url: {yaml_string(credential['ui_url'])}"
                )
                lines.append(
                    f"            api_url: {yaml_string(credential['api_url'])}"
                )
        else:
            lines.append("        defaults: []")
        if not resource["access"]:
            lines.append("    access: []")
            continue
        lines.append("    access:")
        for access in resource["access"]:
            lines.append(
                "      - team_organization: "
                f"{yaml_string(access['team_organization'])}"
            )
            lines.append(f"        team: {yaml_string(access['team'])}")
            lines.append(f"        level: {yaml_string(access['level'])}")
            lines.append(
                f"        can_execute: {yaml_bool(access['can_execute'])}"
            )
            lines.append("        sources:")
            for source in access["sources"]:
                lines.append(f"          - {yaml_string(source)}")
            readiness = access["launch_readiness"]
            lines.append("        launch_readiness:")
            for field in ("status", "inventory", "credentials"):
                lines.append(
                    f"          {field}: {yaml_string(readiness[field])}"
                )
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
    organizations = {item["owning_organization"] for item in report}
    teams = {
        (access["team_organization"], access["team"])
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
    prompted_templates = sum(
        any(prompt["enabled"] for prompt in item["launch_prompts"].values())
        for item in report
    )
    required_selections = sum(
        prompt["enabled"]
        and prompt["required"]
        and not (prompt.get("default") or prompt.get("defaults"))
        for item in report
        for prompt in item["launch_prompts"].values()
    )
    cross_organization = sum(
        access["team_organization"] != item["owning_organization"]
        for item in report
        for access in item["access"]
    )
    readiness_attention = sum(
        access["launch_readiness"]["status"] == "attention"
        for item in report
        for access in item["access"]
    )

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
        f"| Templates with launch prompts | {prompted_templates} |",
        f"| Required selections without defaults | {required_selections} |",
        f"| Cross-organization team grants | {cross_organization} |",
        f"| Team readiness entries needing review | {readiness_attention} |",
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
                    organization=markdown_text(resource["owning_organization"]),
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
            f"### {markdown_text(resource['owning_organization'])} — "
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
        if resource.get("project"):
            lines.append(
                f"- **Project:** {markdown_ui_reference(resource['project'])}"
            )
        inventory_prompt = resource["launch_prompts"]["inventory"]
        inventory = inventory_prompt["default"]
        if inventory_prompt["enabled"]:
            if inventory:
                inventory_text = (
                    "Prompted at launch; default: "
                    f"{markdown_ui_reference(inventory)}"
                )
            elif inventory_prompt["required"]:
                inventory_text = "Prompted at launch; selection required; no default"
            else:
                inventory_text = "Prompted at launch; no default"
        else:
            inventory_text = (
                f"Fixed: {markdown_ui_reference(inventory)}"
                if inventory
                else "Fixed; none configured"
            )
        lines.append(f"- **Inventory:** {inventory_text}")

        credential_prompt = resource["launch_prompts"]["credentials"]
        credentials = credential_prompt["defaults"]
        credential_links = []
        for credential in credentials:
            credential_type = credential.get("type")
            suffix = f" (`{markdown_text(credential_type)}`)" if credential_type else ""
            credential_links.append(f"{markdown_ui_reference(credential)}{suffix}")
        credential_defaults = ", ".join(credential_links)
        if credential_prompt["enabled"]:
            if credential_defaults:
                credential_text = (
                    "Prompted at launch; defaults: " + credential_defaults
                )
            elif credential_prompt["required"]:
                credential_text = "Prompted at launch; selection required; no default"
            else:
                credential_text = "Prompted at launch; optional; no default"
        else:
            credential_text = (
                "Fixed: " + credential_defaults
                if credential_defaults
                else "Fixed; none configured"
            )
        lines.append(f"- **Credentials:** {credential_text}")
        lines.append("")
        if resource["access"]:
            access_by_organization: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for access in resource["access"]:
                access_by_organization[access["team_organization"]].append(access)
            for team_organization in sorted(
                access_by_organization, key=str.casefold
            ):
                relationship = (
                    "same as template owner"
                    if team_organization == resource["owning_organization"]
                    else "cross-organization access"
                )
                lines.extend(
                    [
                        f"#### Teams from {markdown_text(team_organization)} — {relationship}",
                        "",
                        "| Team | Effective access | Grant path | Launch readiness |",
                        "| --- | --- | --- | --- |",
                    ]
                )
                for access in access_by_organization[team_organization]:
                    source_labels = {
                        "job_template_assignment": "Job Template assignment",
                        "owning_organization_assignment": (
                            "Owning Organization assignment"
                        ),
                    }
                    sources = ", ".join(
                        source_labels[source] for source in access["sources"]
                    )
                    readiness = access["launch_readiness"]
                    readiness_labels = {
                        "ready": "Ready",
                        "attention": "Attention",
                        "not_applicable": "Not applicable",
                        "fixed": "fixed",
                        "default_prompt": "prompted default",
                        "team_selection": "team selection",
                        "optional": "optional",
                        "team_access_not_evidenced": "team access not evidenced",
                    }
                    readiness_text = readiness_labels[readiness["status"]]
                    if readiness["status"] != "not_applicable":
                        readiness_text += (
                            f" — inventory: {readiness_labels[readiness['inventory']]}; "
                            "credentials: "
                            f"{readiness_labels[readiness['credentials']]}"
                        )
                    lines.append(
                        f"| {markdown_text(access['team'])} | "
                        f"{access['level']} | {sources} | {readiness_text} |"
                    )
                lines.append("")
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
            (
                "Launch readiness is derived only from team assignments. Direct user "
                "roles can add access, so an attention result is not a definitive denial."
            ),
            "",
        ]
    )
    return "\n".join(lines)


PDF_REPORT_TITLE = "AAP Job Template Access Report"


def pdf_add_wrapped(
    document: StandardLibraryPdf,
    value: Any,
    width: float = PDF_CONTENT_WIDTH,
    size: float = 9,
    bold: bool = False,
    indent: float = 0,
) -> None:
    for line in pdf_wrapped_lines(value, width - indent, size):
        document.text(PDF_MARGIN + indent, document.y, line, size, bold)
        document.y -= size + 3


def pdf_ensure_space(
    document: StandardLibraryPdf,
    height: float,
    continuation: str,
) -> None:
    if document.y - height < 34:
        document.new_page()
        pdf_page_heading(document, PDF_REPORT_TITLE, continuation)


def render_pdf(report: list[dict[str, Any]], days: int, cutoff: str) -> bytes:
    """Render the recently-used access report with no third-party packages."""
    organizations = {item["owning_organization"] for item in report}
    teams = {
        (access["team_organization"], access["team"])
        for item in report
        for access in item["access"]
    }
    without_access = sum(not item["access"] for item in report)
    prompted_templates = sum(
        any(prompt["enabled"] for prompt in item["launch_prompts"].values())
        for item in report
    )
    cross_organization = sum(
        access["team_organization"] != item["owning_organization"]
        for item in report
        for access in item["access"]
    )
    readiness_attention = sum(
        access["launch_readiness"]["status"] == "attention"
        for item in report
        for access in item["access"]
    )

    document = StandardLibraryPdf()
    pdf_page_heading(document, PDF_REPORT_TITLE)
    pdf_add_wrapped(
        document,
        f"Current team access to Job Templates with a last run in the past "
        f"{days} days. Cutoff: {cutoff}",
    )
    document.y -= 6

    pdf_table(
        document,
        PDF_REPORT_TITLE,
        "Summary",
        ["Metric", "Count"],
        [
            ["Recently used Job Templates", len(report)],
            ["Owning organizations", len(organizations)],
            ["Teams with access", len(teams)],
            ["Templates with no team access", without_access],
            ["Templates with launch prompts", prompted_templates],
            ["Cross-organization team grants", cross_organization],
            ["Team readiness entries needing review", readiness_attention],
        ],
        [600, 120],
    )

    template_rows = [
        [
            resource["owning_organization"],
            resource["name"],
            resource.get("last_job_run", "Unknown"),
            resource.get("project", {}).get("name", "-"),
            resource.get("inventory", {}).get("name", "-"),
            len(resource["access"]),
        ]
        for resource in report
    ]
    pdf_table(
        document,
        PDF_REPORT_TITLE,
        "Templates",
        ["Organization", "Job Template", "Last run", "Project", "Inventory", "Teams"],
        template_rows,
        [105, 205, 105, 115, 120, 70],
    )

    for resource in report:
        pdf_ensure_space(document, 150, "Details - continued")
        pdf_add_wrapped(
            document,
            f"{resource['owning_organization']} - {resource['name']}",
            size=12,
            bold=True,
        )
        document.y -= 2
        detail_lines = [
            f"Last run: {resource.get('last_job_run', 'Unknown')}",
            f"API: {resource['api_url']}",
        ]
        if resource.get("playbook"):
            detail_lines.append(f"Playbook: {resource['playbook']}")
        if resource.get("project"):
            detail_lines.append(f"Project: {resource['project']['name']}")
        if resource.get("inventory"):
            detail_lines.append(f"Inventory: {resource['inventory']['name']}")
        credentials = resource.get("credentials", [])
        detail_lines.append(
            "Credentials: " + ", ".join(item["name"] for item in credentials)
            if credentials
            else "Credentials: none configured"
        )
        for detail in detail_lines:
            pdf_add_wrapped(document, detail, size=8.5, indent=6)
        document.y -= 3

        access_rows = []
        for access in resource["access"]:
            readiness = access["launch_readiness"]
            access_rows.append(
                [
                    access["team_organization"],
                    access["team"],
                    access["level"],
                    ", ".join(source.replace("_", " ") for source in access["sources"]),
                    (
                        f"{readiness['status']}; inventory: {readiness['inventory']}; "
                        f"credentials: {readiness['credentials']}"
                    ),
                ]
            )
        pdf_table(
            document,
            PDF_REPORT_TITLE,
            "Team access",
            ["Team organization", "Team", "Level", "Grant path", "Launch readiness"],
            access_rows,
            [120, 150, 65, 165, 220],
        )
    return document.finish()


def effective_access_level(permissions: set[str]) -> Optional[str]:
    if permissions & {
        "awx.change_jobtemplate",
        "awx.delete_jobtemplate",
    }:
        return "admin"
    if "awx.execute_jobtemplate" in permissions:
        return "execute"
    if "awx.view_jobtemplate" in permissions:
        return "view"
    return None


def prompt_readiness(
    resource: dict[str, Any],
    can_execute: bool,
    has_inventory_selection: bool,
    has_credential_selection: bool,
) -> dict[str, str]:
    if not can_execute:
        return {
            "status": "not_applicable",
            "inventory": "not_applicable",
            "credentials": "not_applicable",
        }

    prompts = resource["launch_prompts"]
    inventory = prompts["inventory"]
    credentials = prompts["credentials"]
    if not inventory["enabled"]:
        inventory_status = "fixed"
    elif inventory["default"]:
        inventory_status = "default_prompt"
    elif has_inventory_selection:
        inventory_status = "team_selection"
    else:
        inventory_status = "team_access_not_evidenced"

    if not credentials["enabled"]:
        credential_status = "fixed"
    elif credentials["defaults"]:
        credential_status = "default_prompt"
    elif not credentials["required"]:
        credential_status = "optional"
    elif has_credential_selection:
        credential_status = "team_selection"
    else:
        credential_status = "team_access_not_evidenced"

    needs_attention = (
        inventory["required"]
        and inventory_status == "team_access_not_evidenced"
    ) or (
        credentials["required"]
        and credential_status == "team_access_not_evidenced"
    )
    return {
        "status": "attention" if needs_attention else "ready",
        "inventory": inventory_status,
        "credentials": credential_status,
    }


def organization_has_resource(
    client: Client,
    endpoint: str,
    organization_name_value: str,
    cache: dict[tuple[str, str], bool],
    controller_organization_cache: dict[str, Optional[int]],
) -> bool:
    key = (endpoint, organization_name_value)
    if key not in cache:
        if organization_name_value not in controller_organization_cache:
            organizations = client.get(
                f"{CONTROLLER}/organizations/",
                {"name": organization_name_value, "page_size": 1},
            ).get("results", [])
            controller_organization_cache[organization_name_value] = (
                int(organizations[0]["id"]) if organizations else None
            )
        organization_id = controller_organization_cache[organization_name_value]
        if organization_id is None:
            cache[key] = False
            return False
        payload = client.get(
            f"{CONTROLLER}/{endpoint}/",
            {"organization": organization_id, "page_size": 1},
        )
        cache[key] = bool(payload.get("count") or payload.get("results"))
    return cache[key]


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
        prompted = bool(
            template.get("ask_inventory_on_launch")
            or template.get("ask_credential_on_launch")
        )
        launch = (
            client.get(f"{CONTROLLER}/job_templates/{template_id}/launch/")
            if prompted
            else None
        )
        resource = template_resource(client, template, organizations, launch)
        report_by_id[template_id] = resource
        templates_by_org[resource["owning_organization"]].append(template)

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

    source_rank = {
        "job_template_assignment": 1,
        "owning_organization_assignment": 2,
    }
    team_use: dict[int, dict[str, set[Any]]] = defaultdict(
        lambda: {
            "inventory_objects": set(),
            "credential_objects": set(),
            "inventory_organizations": set(),
            "credential_organizations": set(),
        }
    )

    def add_access(
        template: dict[str, Any],
        team_id: int,
        team_org: str,
        team_name: str,
        permissions: set[str],
        source: str,
    ) -> None:
        template_access = access_by_template[str(template["id"])]
        existing = template_access.get(team_id)
        if existing is None:
            template_access[team_id] = {
                "team_organization": team_org,
                "team": team_name,
                "_team_id": team_id,
                "_permissions": set(permissions),
                "level": effective_access_level(permissions),
                "sources": {source},
            }
            return
        existing["_permissions"].update(permissions)
        existing["level"] = effective_access_level(existing["_permissions"])
        existing["sources"].add(source)

    for assignment in assignments:
        team_id = relation_id(assignment.get("team"))
        definition_id = relation_id(assignment.get("role_definition"))
        if team_id not in teams_by_id or definition_id not in definitions:
            continue
        team_org, team_name = teams_by_id[team_id]
        definition = definitions[definition_id]
        permissions = set(definition.get("permissions", []))
        content_type = str(
            assignment.get("content_type") or definition.get("content_type") or ""
        )
        object_reference = assignment.get("object_id") or assignment.get(
            "object_ansible_id"
        )

        if content_type == "awx.inventory" and "awx.use_inventory" in permissions:
            if object_reference is not None:
                team_use[team_id]["inventory_objects"].add(str(object_reference))
            continue

        if content_type == "awx.credential" and "awx.use_credential" in permissions:
            if object_reference is not None:
                team_use[team_id]["credential_objects"].add(str(object_reference))
            continue

        if content_type == "awx.jobtemplate":
            if effective_access_level(permissions) is None:
                continue
            template = recent_by_id.get(str(assignment.get("object_id")))
            if template is None and assignment.get("object_ansible_id"):
                template = recent_by_ansible_id.get(str(assignment["object_ansible_id"]))
            if template:
                add_access(
                    template,
                    team_id,
                    team_org,
                    team_name,
                    permissions,
                    "job_template_assignment",
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
                object_org = str(object_org)
                if "awx.use_inventory" in permissions:
                    team_use[team_id]["inventory_organizations"].add(object_org)
                if "awx.use_credential" in permissions:
                    team_use[team_id]["credential_organizations"].add(object_org)
                if effective_access_level(permissions) is not None:
                    for template in templates_by_org.get(object_org, []):
                        add_access(
                            template,
                            team_id,
                            team_org,
                            team_name,
                            permissions,
                            "owning_organization_assignment",
                        )

    report: list[dict[str, Any]] = []
    organization_resource_cache: dict[tuple[str, str], bool] = {}
    controller_organization_cache: dict[str, Optional[int]] = {}

    def has_team_selection(team_id: int, resource_type: str) -> bool:
        access = team_use[team_id]
        if access[f"{resource_type}_objects"]:
            return True
        endpoint = "inventories" if resource_type == "inventory" else "credentials"
        return any(
            organization_has_resource(
                client,
                endpoint,
                organization,
                organization_resource_cache,
                controller_organization_cache,
            )
            for organization in access[f"{resource_type}_organizations"]
        )

    for template_id, resource in report_by_id.items():
        access_entries = access_by_template.get(template_id, {}).values()
        rendered_access = []
        for entry in access_entries:
            permissions = entry.pop("_permissions")
            team_id = entry.pop("_team_id")
            entry["can_execute"] = "awx.execute_jobtemplate" in permissions
            entry["sources"] = sorted(
                entry["sources"], key=lambda source: source_rank[source]
            )
            prompts = resource["launch_prompts"]
            needs_inventory_selection = (
                prompts["inventory"]["enabled"]
                and not prompts["inventory"]["default"]
            )
            needs_credential_selection = (
                prompts["credentials"]["enabled"]
                and prompts["credentials"]["required"]
                and not prompts["credentials"]["defaults"]
            )
            entry["launch_readiness"] = prompt_readiness(
                resource,
                entry["can_execute"],
                has_team_selection(team_id, "inventory")
                if needs_inventory_selection
                else False,
                has_team_selection(team_id, "credential")
                if needs_credential_selection
                else False,
            )
            rendered_access.append(entry)
        resource["access"] = sorted(
            rendered_access,
            key=lambda entry: (
                entry["team_organization"].casefold(),
                entry["team"].casefold(),
            ),
        )
        report.append(resource)
    report.sort(
        key=lambda resource: (
            resource["owning_organization"].casefold(),
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
    parser.add_argument(
        "--pdf-output",
        help="optional dependency-free PDF report path",
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
        if args.pdf_output:
            with open(args.pdf_output, "wb") as target:
                target.write(render_pdf(report, args.days, cutoff))
            print(f"Wrote {args.pdf_output} (cutoff {cutoff})", file=sys.stderr)
    except (ExportError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
