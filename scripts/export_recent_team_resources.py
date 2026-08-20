#!/usr/bin/env python3
"""Export AAP Job and Workflow Templates, resources, and permissions."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any, Optional

from standard_library_pdf import (
    CONTENT_WIDTH,
    MARGIN,
    StandardLibraryPdf,
    page_heading,
    table,
    wrapped_lines,
)


CONTROLLER = "/api/controller/v2"
GATEWAY = "/api/gateway/v1"
TITLE = "AAP Template Report"
PAGE_SIZE = 50
REQUEST_DELAY = 1
RETRYABLE_HTTP_ERRORS = {429, 502, 503, 504}
RETRY_DELAYS = (60, 120)
STEP_KINDS = {
    "job": "job_template",
    "job_template": "job_template",
    "workflow_job": "workflow_job_template",
    "workflow_job_template": "workflow_job_template",
    "project_update": "project",
    "inventory_update": "inventory_source",
    "workflow_approval": "workflow_approval",
    "workflow_approval_template": "workflow_approval",
}


class ExportError(RuntimeError):
    pass


class Client:
    def __init__(self) -> None:
        self.base_url = os.environ.get("AAP_URL", "").rstrip("/")
        token = os.environ.get("AAP_TOKEN")
        username = os.environ.get("AAP_USERNAME")
        password = os.environ.get("AAP_PASSWORD")
        if not self.base_url:
            raise ExportError("AAP_URL is not set")
        if token:
            self.authorization = f"Bearer {token}"
        elif username and password:
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            self.authorization = f"Basic {encoded}"
        else:
            raise ExportError("set AAP_TOKEN or AAP_USERNAME/AAP_PASSWORD")
        verify = os.environ.get("AAP_VALIDATE_CERTS", "true").lower() == "true"
        self.context = None if verify else ssl._create_unverified_context()

    def get(
        self, path_or_url: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "Authorization": self.authorization},
        )
        delay = REQUEST_DELAY
        for attempt in range(len(RETRY_DELAYS) + 1):
            time.sleep(delay)
            try:
                with urllib.request.urlopen(
                    request, context=self.context, timeout=60
                ) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRYABLE_HTTP_ERRORS or attempt == len(RETRY_DELAYS):
                    raise ExportError(f"GET {url} returned HTTP {exc.code}") from exc
                delay = RETRY_DELAYS[attempt]
                retry_after = exc.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, int(retry_after))
                print(
                    f"GET {url} returned HTTP {exc.code}; retrying in {delay}s",
                    file=sys.stderr,
                )
            except urllib.error.URLError as exc:
                raise ExportError(f"GET {url} failed: {exc.reason}") from exc

        raise AssertionError("unreachable")

    def list(self, path: str, **params: Any) -> list[dict[str, Any]]:
        params["page_size"] = PAGE_SIZE
        page = self.get(path, params)
        results = list(page.get("results", []))
        while page.get("next"):
            page = self.get(page["next"])
            results.extend(page.get("results", []))
        return results


def key(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    return str(value or "")


def ui_url(client: Client, kind: str, item: dict[str, Any]) -> str:
    item_id = item["id"]
    if kind == "job_template":
        path = f"/execution/templates/job-template/{item_id}/details"
    elif kind == "workflow_job_template":
        path = f"/execution/templates/workflow-job-template/{item_id}/visualizer"
    elif kind == "credential":
        path = f"/execution/credentials/{item_id}/details"
    else:
        inventory_kind = {
            "smart": "smart-inventory",
            "constructed": "constructed-inventory",
        }.get(str(item.get("kind", "")), "inventory")
        path = f"/execution/inventories/{inventory_kind}/{item_id}/details"
    return client.base_url + path


def api_url(client: Client, kind: str, item: dict[str, Any]) -> str:
    endpoint = {
        "job_template": "job_templates",
        "workflow_job_template": "workflow_job_templates",
        "inventory": "inventories",
        "credential": "credentials",
    }[kind]
    path = str(item.get("url") or f"{CONTROLLER}/{endpoint}/{item['id']}/")
    if path.startswith(("http://", "https://")):
        return path
    return client.base_url + "/" + path.lstrip("/")


def resource(client: Client, kind: str, item: Any) -> Optional[dict[str, str]]:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    return {
        "name": str(item.get("name") or f"ID {item['id']}"),
        "url": api_url(client, kind, item),
        "ui_url": ui_url(client, kind, item),
    }


def permission_level(permissions: list[str]) -> Optional[str]:
    values = set(permissions)
    if values & {
        "awx.change_jobtemplate",
        "awx.delete_jobtemplate",
        "awx.change_workflowjobtemplate",
        "awx.delete_workflowjobtemplate",
    }:
        return "admin"
    if values & {
        "awx.execute_jobtemplate",
        "awx.execute_workflowjobtemplate",
    }:
        return "execute"
    if values & {"awx.view_jobtemplate", "awx.view_workflowjobtemplate"}:
        return "view"
    return None


def merge_users(
    users_by_source: dict[str, list[dict[str, Any]]],
) -> tuple[
    dict[str, tuple[str, str]],
    dict[tuple[str, str], str],
    dict[str, list[dict[str, Any]]],
]:
    """Merge Gateway and Controller identities without comparing their IDs."""
    stable_by_username: dict[str, set[str]] = defaultdict(set)
    for users in users_by_source.values():
        for user in users:
            username = str(user.get("username") or "").casefold()
            if username and user.get("ansible_id"):
                stable_by_username[username].add(key(user["ansible_id"]))

    principals: dict[str, tuple[str, str]] = {}
    source_ids: dict[tuple[str, str], str] = {}
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source, users in users_by_source.items():
        for user in users:
            username = str(user.get("username") or user.get("name") or user["id"])
            normalized_username = username.casefold()
            stable = key(user.get("ansible_id"))
            if not stable and len(stable_by_username[normalized_username]) == 1:
                stable = next(iter(stable_by_username[normalized_username]))
            identity = f"ansible:{stable}" if stable else f"username:{normalized_username}"
            principals.setdefault(identity, (username, ""))
            source_ids[(source, key(user["id"]))] = identity
            records[identity].append(user)
    return principals, source_ids, records


def rbac_base(client: Client) -> str:
    version = str(client.get(f"{CONTROLLER}/config/").get("version", ""))
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except (TypeError, ValueError) as exc:
        raise ExportError(f"could not read Controller version {version!r}") from exc
    return CONTROLLER if (major, minor) == (4, 6) else GATEWAY


def ran_recently(template: dict[str, Any], cutoff: str) -> bool:
    last_run = template.get("last_job_run")
    return bool(last_run and str(last_run) >= cutoff)


def node_link(node: dict[str, Any]) -> tuple[str, str]:
    summary = node.get("summary_fields", {}).get("unified_job_template", {})
    if not isinstance(summary, dict):
        summary = {}
    raw_kind = str(summary.get("type") or summary.get("unified_job_type") or "")
    kind = STEP_KINDS.get(raw_kind, raw_kind)
    if not kind:
        path = str(node.get("related", {}).get("unified_job_template") or "")
        for endpoint, endpoint_kind in (
            ("/workflow_job_templates/", "workflow_job_template"),
            ("/job_templates/", "job_template"),
            ("/projects/", "project"),
            ("/inventory_sources/", "inventory_source"),
            ("/workflow_approval_templates/", "workflow_approval"),
        ):
            if endpoint in path:
                kind = endpoint_kind
                break
    return kind or "unknown", key(
        node.get("unified_job_template") or summary.get("id")
    )


def used_template_ids(
    jobs: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    cutoff: str,
) -> tuple[set[str], set[str]]:
    used_jobs = {
        key(item["id"]) for item in jobs if ran_recently(item, cutoff)
    }
    used_workflows = {
        key(item["id"]) for item in workflows if ran_recently(item, cutoff)
    }
    nodes_by_workflow: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        nodes_by_workflow[key(node.get("workflow_job_template"))].append(node)

    pending = list(used_workflows)
    visited: set[str] = set()
    while pending:
        workflow_id = pending.pop()
        if workflow_id in visited:
            continue
        visited.add(workflow_id)
        for node in nodes_by_workflow.get(workflow_id, []):
            kind, template_id = node_link(node)
            if kind == "job_template" and template_id:
                used_jobs.add(template_id)
            elif kind == "workflow_job_template" and template_id:
                if template_id not in used_workflows:
                    used_workflows.add(template_id)
                pending.append(template_id)
    return used_jobs, used_workflows


def job_entries(
    client: Client,
    templates: list[dict[str, Any]],
    access: Optional[
        dict[tuple[str, str], dict[tuple[str, str], dict[str, str]]]
    ] = None,
) -> list[dict[str, Any]]:
    report = []
    for template in templates:
        summary = template.get("summary_fields", {})
        inventory = resource(client, "inventory", summary.get("inventory"))
        credentials = []
        for item in summary.get("credentials", []):
            credential = resource(client, "credential", item)
            if credential:
                credentials.append(credential)
        entry: dict[str, Any] = {
            "kind": "job_template",
            "pdf_anchor": f"job-template-{template['id']}",
            "name": str(template["name"]),
            "url": api_url(client, "job_template", template),
            "ui_url": ui_url(client, "job_template", template),
            "last_run": (
                str(template["last_job_run"])
                if template.get("last_job_run")
                else None
            ),
            "inventory": inventory,
            "credentials": sorted(
                credentials, key=lambda item: item["name"].casefold()
            ),
            "permissions_checked": access is not None,
        }
        if access is not None:
            entry["permissions"] = sorted(
                access[("job_template", key(template["id"]))].values(),
                key=lambda item: (item["type"], item["name"].casefold()),
            )
        report.append(entry)
    return sorted(report, key=lambda item: item["name"].casefold())


def workflow_entries(
    client: Client,
    workflows: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    access: Optional[
        dict[tuple[str, str], dict[tuple[str, str], dict[str, str]]]
    ] = None,
) -> list[dict[str, Any]]:
    nodes_by_workflow: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        nodes_by_workflow[key(node.get("workflow_job_template"))].append(node)

    report = []
    for workflow in workflows:
        workflow_nodes = nodes_by_workflow.get(key(workflow["id"]), [])
        identifiers = {
            key(node["id"]): str(node.get("identifier") or f"Node {node['id']}")
            for node in workflow_nodes
        }
        steps = []
        for node in workflow_nodes:
            summary = node.get("summary_fields", {}).get("unified_job_template", {})
            if not isinstance(summary, dict):
                summary = {}
            kind, template_id = node_link(node)
            path = node.get("related", {}).get("unified_job_template") or summary.get(
                "url"
            )
            url = None
            if path:
                url = (
                    str(path)
                    if str(path).startswith(("http://", "https://"))
                    else client.base_url + "/" + str(path).lstrip("/")
                )
            elif template_id and kind in {"job_template", "workflow_job_template"}:
                url = api_url(client, kind, {"id": template_id})
            ui = url
            if template_id and kind in {"job_template", "workflow_job_template"}:
                ui = ui_url(client, kind, {"id": template_id})

            def branches(name: str) -> list[str]:
                return [
                    identifiers.get(key(item), key(item))
                    for item in node.get(name, [])
                ]

            steps.append(
                {
                    "identifier": str(
                        node.get("identifier") or f"Node {node['id']}"
                    ),
                    "name": str(
                        summary.get("name")
                        or node.get("identifier")
                        or f"Node {node['id']}"
                    ),
                    "type": kind,
                    "url": url,
                    "ui_url": ui,
                    "success": branches("success_nodes"),
                    "failure": branches("failure_nodes"),
                    "always": branches("always_nodes"),
                }
            )

        summary = workflow.get("summary_fields", {})
        entry: dict[str, Any] = {
            "kind": "workflow_job_template",
            "pdf_anchor": f"workflow-template-{workflow['id']}",
            "name": str(workflow["name"]),
            "url": api_url(client, "workflow_job_template", workflow),
            "ui_url": ui_url(client, "workflow_job_template", workflow),
            "last_run": (
                str(workflow["last_job_run"])
                if workflow.get("last_job_run")
                else None
            ),
            "inventory": resource(client, "inventory", summary.get("inventory")),
            "credentials": [],
            "steps": steps,
            "permissions_checked": access is not None,
        }
        if access is not None:
            entry["permissions"] = sorted(
                access[("workflow_job_template", key(workflow["id"]))].values(),
                key=lambda item: (item["type"], item["name"].casefold()),
            )
        report.append(entry)
    return sorted(report, key=lambda item: item["name"].casefold())


def build_report(
    client: Client,
    days: int = 365,
    mode: str = "recent",
    check_rbac: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    all_jobs = client.list(f"{CONTROLLER}/job_templates/", order_by="name")
    all_workflows = client.list(
        f"{CONTROLLER}/workflow_job_templates/", order_by="name"
    )
    all_nodes = (
        client.list(f"{CONTROLLER}/workflow_job_template_nodes/", order_by="id")
        if all_workflows
        else []
    )
    used_jobs, used_workflows = used_template_ids(
        all_jobs, all_workflows, all_nodes, cutoff
    )

    def included(kind: str, item: dict[str, Any]) -> bool:
        if mode == "all":
            return True
        used_ids = used_jobs if kind == "job_template" else used_workflows
        is_used = key(item["id"]) in used_ids
        return is_used if mode == "recent" else not is_used

    jobs = [item for item in all_jobs if included("job_template", item)]
    workflows = [
        item for item in all_workflows if included("workflow_job_template", item)
    ]
    workflow_ids = {key(item["id"]) for item in workflows}
    nodes = [
        item
        for item in all_nodes
        if key(item.get("workflow_job_template")) in workflow_ids
    ]

    def entries(
        access: Optional[
            dict[tuple[str, str], dict[tuple[str, str], dict[str, str]]]
        ] = None,
    ) -> list[dict[str, Any]]:
        return sorted(
            job_entries(client, jobs, access)
            + workflow_entries(client, workflows, nodes, access),
            key=lambda item: (item["name"].casefold(), item["kind"]),
        )

    if not check_rbac:
        return entries(), cutoff

    templates = {
        "job_template": jobs,
        "workflow_job_template": workflows,
    }
    templates_by_id = {
        kind: {key(item["id"]): item for item in items}
        for kind, items in templates.items()
    }
    templates_by_ansible_id = {
        kind: {
            key(
                item.get("ansible_id")
                or item.get("summary_fields", {})
                .get("resource", {})
                .get("ansible_id")
            ): item
            for item in items
            if item.get("ansible_id")
            or item.get("summary_fields", {})
            .get("resource", {})
            .get("ansible_id")
        }
        for kind, items in templates.items()
    }

    base = rbac_base(client)
    organizations = {
        key(item["id"]): str(item["name"])
        for item in client.list(f"{base}/organizations/")
    }
    teams = client.list(f"{base}/teams/")
    users_by_source = {base: client.list(f"{base}/users/")}
    if base != CONTROLLER:
        users_by_source[CONTROLLER] = client.list(f"{CONTROLLER}/users/")
    user_principals, user_source_ids, user_records = merge_users(users_by_source)
    principals: dict[str, dict[str, tuple[str, str]]] = {
        "team": {
            key(item["id"]): (
                str(item["name"]),
                organizations.get(key(item.get("organization")), ""),
            )
            for item in teams
        },
        "user": user_principals,
    }
    definitions = {
        key(item["id"]): item for item in client.list(f"{base}/role_definitions/")
    }

    templates_by_org: dict[
        str, list[tuple[str, dict[str, Any]]]
    ] = defaultdict(list)
    for kind, items in templates.items():
        for template in items:
            organization = template.get("summary_fields", {}).get(
                "organization", {}
            )
            organization_name = organization.get("name")
            if not organization_name:
                organization_name = organizations.get(
                    key(template.get("organization"))
                )
            if organization_name:
                templates_by_org[str(organization_name)].append((kind, template))

    rank = {"view": 1, "execute": 2, "admin": 3}
    access: dict[
        tuple[str, str], dict[tuple[str, str], dict[str, str]]
    ] = defaultdict(dict)

    def add(
        kind: str,
        template: dict[str, Any],
        principal_type: str,
        principal_id: str,
        level: str,
    ) -> None:
        principal = principals[principal_type].get(principal_id)
        if not principal:
            return
        name, organization = principal
        entry = {"type": principal_type, "name": name, "level": level}
        if principal_type == "team" and organization:
            entry["organization"] = organization
        identity = (principal_type, principal_id)
        template_identity = (kind, key(template["id"]))
        current = access[template_identity].get(identity)
        if current is None or rank[level] > rank[current["level"]]:
            access[template_identity][identity] = entry

    for identity, records in user_records.items():
        if any(
            user.get("is_superuser") or user.get("is_platform_superuser")
            for user in records
        ):
            level = "admin"
        elif any(
            user.get("is_system_auditor") or user.get("is_platform_auditor")
            for user in records
        ):
            level = "view"
        else:
            continue
        for kind, items in templates.items():
            for template in items:
                add(kind, template, "user", identity, level)

    content_types = {
        "awx.jobtemplate": "job_template",
        "awx.workflowjobtemplate": "workflow_job_template",
    }
    for principal_type in ("team", "user"):
        assignments = client.list(f"{base}/role_{principal_type}_assignments/")
        for assignment in assignments:
            principal_id = key(assignment.get(principal_type))
            if principal_type == "user":
                principal_id = user_source_ids.get(
                    (base, principal_id), principal_id
                )
            definition = definitions.get(key(assignment.get("role_definition")), {})
            level = permission_level(definition.get("permissions", []))
            if not level:
                continue
            content_type = str(
                assignment.get("content_type")
                or definition.get("content_type")
                or ""
            )
            kind = content_types.get(content_type)
            if kind:
                template = templates_by_id[kind].get(
                    key(assignment.get("object_id"))
                )
                template = template or templates_by_ansible_id[kind].get(
                    key(assignment.get("object_ansible_id"))
                )
                if template:
                    add(kind, template, principal_type, principal_id, level)
            elif content_type == "shared.organization":
                organization_name = organizations.get(key(assignment.get("object_id")))
                if not organization_name:
                    organization_name = (
                        assignment.get("summary_fields", {})
                        .get("content_object", {})
                        .get("name")
                    )
                for kind, template in templates_by_org.get(
                    str(organization_name), []
                ):
                    add(kind, template, principal_type, principal_id, level)

    return entries(access), cutoff


def scalar(value: Optional[str]) -> str:
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


def render_yaml(report: list[dict[str, Any]]) -> str:
    lines = ["summary:" + ("" if report else " []")]
    for template in report:
        lines.extend(
            [
                f"  - name: {scalar(template['name'])}",
                f"    url: {scalar(template['url'])}",
            ]
        )

    def add_inventory(template: dict[str, Any]) -> None:
        if template["inventory"]:
            lines.extend(
                [
                    "    inventory:",
                    f"      name: {scalar(template['inventory']['name'])}",
                    f"      url: {scalar(template['inventory']['url'])}",
                ]
            )
        else:
            lines.append("    inventory: null")

    def add_permissions(template: dict[str, Any]) -> None:
        if not template["permissions_checked"]:
            lines.append("    permissions_checked: false")
            return
        lines.append(
            "    permissions:" + ("" if template["permissions"] else " []")
        )
        for permission in template["permissions"]:
            lines.extend(
                [
                    f"      - type: {scalar(permission['type'])}",
                    f"        name: {scalar(permission['name'])}",
                ]
            )
            if permission.get("organization"):
                lines.append(
                    f"        organization: {scalar(permission['organization'])}"
                )
            lines.append(f"        level: {scalar(permission['level'])}")

    jobs = [item for item in report if item["kind"] == "job_template"]
    workflows = [
        item for item in report if item["kind"] == "workflow_job_template"
    ]
    lines.append("job_templates:" + ("" if jobs else " []"))
    for job in jobs:
        lines.extend(
            [
                f"  - name: {scalar(job['name'])}",
                f"    url: {scalar(job['url'])}",
                f"    last_run: {scalar(job['last_run'])}",
            ]
        )
        add_inventory(job)
        lines.append("    credentials:" + ("" if job["credentials"] else " []"))
        for credential in job["credentials"]:
            lines.extend(
                [
                    f"      - name: {scalar(credential['name'])}",
                    f"        url: {scalar(credential['url'])}",
                ]
            )
        add_permissions(job)

    lines.append("workflow_job_templates:" + ("" if workflows else " []"))
    for workflow in workflows:
        lines.extend(
            [
                f"  - name: {scalar(workflow['name'])}",
                f"    url: {scalar(workflow['url'])}",
                f"    last_run: {scalar(workflow['last_run'])}",
            ]
        )
        add_inventory(workflow)
        lines.append("    steps:" + ("" if workflow["steps"] else " []"))
        for step in workflow["steps"]:
            lines.extend(
                [
                    f"      - identifier: {scalar(step['identifier'])}",
                    f"        name: {scalar(step['name'])}",
                    f"        type: {scalar(step['type'])}",
                    f"        url: {scalar(step['url'])}",
                ]
            )
            for branch in ("success", "failure", "always"):
                targets = step[branch]
                lines.append(f"        {branch}:" + ("" if targets else " []"))
                for target in targets:
                    lines.append(f"          - {scalar(target)}")
        add_permissions(workflow)
    return "\n".join(lines) + "\n"


def add_text(document: StandardLibraryPdf, value: str, bold: bool = False) -> None:
    for line in wrapped_lines(value, CONTENT_WIDTH, 9):
        if document.y < 42:
            document.new_page()
            page_heading(document, TITLE, "Details - continued")
        document.text(MARGIN, document.y, line, 9, bold)
        document.y -= 12


def unique_resource_counts(report: list[dict[str, Any]]) -> tuple[int, int]:
    inventories = {
        job["inventory"]["url"] for job in report if job.get("inventory")
    }
    credentials = {
        credential["url"]
        for job in report
        for credential in job.get("credentials", [])
    }
    return len(inventories), len(credentials)


def render_pdf(
    report: list[dict[str, Any]],
    days: int,
    cutoff: str,
    mode: str,
    rbac_checked: bool,
) -> bytes:
    document = StandardLibraryPdf()
    page_heading(document, TITLE)
    scope = {
        "recent": f"Used directly or by a workflow within the last {days} days",
        "unused": f"Not used directly or by a workflow within the last {days} days",
        "all": "All templates; no date filter",
    }[mode]
    inventory_count, credential_count = unique_resource_counts(report)
    jobs = [item for item in report if item["kind"] == "job_template"]
    workflows = [
        item for item in report if item["kind"] == "workflow_job_template"
    ]
    overview = [
        ["Scope", scope],
        ["Cutoff", cutoff if mode != "all" else "Not applied"],
        ["Job Templates", len(jobs)],
        ["Workflow Templates", len(workflows)],
        ["Workflow Steps", sum(len(item["steps"]) for item in workflows)],
        ["Unique inventories", inventory_count],
        ["Unique credentials", credential_count],
        ["RBAC permissions", "Checked" if rbac_checked else "Not checked"],
    ]
    table(
        document,
        TITLE,
        "Overview",
        ["Item", "Value"],
        overview,
        [250, 470],
    )
    table(
        document,
        TITLE,
        "Summary",
        ["Template (click for details)", "URL"],
        [[template["name"], template["ui_url"]] for template in report],
        [250, 470],
        row_links=[template["pdf_anchor"] for template in report],
    )

    for template in report:
        if document.y < 150:
            document.new_page()
            page_heading(document, TITLE, "Details - continued")
        document.destination(template["pdf_anchor"])
        kind = (
            "Workflow Template"
            if template["kind"] == "workflow_job_template"
            else "Job Template"
        )
        add_text(document, template["name"], True)
        add_text(document, f"Type: {kind}")
        add_text(document, f"URL: {template['ui_url']}")
        add_text(document, f"Last run: {template['last_run'] or 'Never'}")
        inventory = template["inventory"]
        add_text(
            document,
            "Inventory: none"
            if not inventory
            else f"Inventory: {inventory['name']} - {inventory['ui_url']}",
        )
        if template["kind"] == "job_template":
            credentials = template["credentials"]
            add_text(
                document,
                "Credentials: none"
                if not credentials
                else "Credentials: "
                + "; ".join(
                    f"{item['name']} - {item['ui_url']}" for item in credentials
                ),
            )
        else:
            step_rows = []
            for step in template["steps"]:
                paths = []
                for branch in ("success", "failure", "always"):
                    if step[branch]:
                        paths.append(f"{branch}: {', '.join(step[branch])}")
                step_rows.append(
                    [
                        f"{step['identifier']}: {step['name']}",
                        step["type"].replace("_", " ").title(),
                        step["ui_url"] or "",
                        "; ".join(paths) or "End",
                    ]
                )
            table(
                document,
                TITLE,
                "Steps",
                ["Step", "Type", "URL", "Next"],
                step_rows,
                [180, 110, 280, 150],
            )
        if not template["permissions_checked"]:
            add_text(document, "Permissions: not checked")
            document.y -= 12
            continue
        permission_rows = []
        for permission in template["permissions"]:
            name = permission["name"]
            if permission.get("organization"):
                name += f" ({permission['organization']})"
            permission_rows.append(
                [permission["type"].title(), name, permission["level"]]
            )
        table(
            document,
            TITLE,
            "Permissions",
            ["Type", "Name", "Level"],
            permission_rows,
            [90, 480, 150],
        )
    return document.finish()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365, help="cutoff; default: 365")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--unused", action="store_true", help="not run within --days")
    mode.add_argument("--all", action="store_true", help="no date filter")
    parser.add_argument("--no-rbac", action="store_true", help="skip permission checks")
    parser.add_argument("--output", default="-", help="YAML path; default: stdout")
    parser.add_argument("--pdf-output", help="optional PDF path")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    report_mode = "all" if args.all else "unused" if args.unused else "recent"
    try:
        report, cutoff = build_report(
            Client(), args.days, report_mode, check_rbac=not args.no_rbac
        )
        output = render_yaml(report)
        if args.output == "-":
            sys.stdout.write(output)
        else:
            with open(args.output, "w", encoding="utf-8") as target:
                target.write(output)
            print(f"Wrote {args.output}", file=sys.stderr)
        if args.pdf_output:
            with open(args.pdf_output, "wb") as target:
                target.write(
                    render_pdf(
                        report,
                        args.days,
                        cutoff,
                        report_mode,
                        rbac_checked=not args.no_rbac,
                    )
                )
            print(f"Wrote {args.pdf_output}", file=sys.stderr)
    except (ExportError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
