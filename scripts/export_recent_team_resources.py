#!/usr/bin/env python3
"""Export AAP Job Templates, tied resources, and current permissions."""
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
TITLE = "AAP Job Template Report"
RETRYABLE_HTTP_ERRORS = {429, 502, 503, 504}
RETRY_DELAYS = (1, 2, 4)


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
        for attempt in range(len(RETRY_DELAYS) + 1):
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
                time.sleep(delay)
            except urllib.error.URLError as exc:
                raise ExportError(f"GET {url} failed: {exc.reason}") from exc

        raise AssertionError("unreachable")

    def list(self, path: str, **params: Any) -> list[dict[str, Any]]:
        params["page_size"] = 200
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
    if values & {"awx.change_jobtemplate", "awx.delete_jobtemplate"}:
        return "admin"
    if "awx.execute_jobtemplate" in values:
        return "execute"
    if "awx.view_jobtemplate" in values:
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


def selected(template: dict[str, Any], cutoff: str, mode: str) -> bool:
    last_run = template.get("last_job_run")
    if mode == "all":
        return True
    if mode == "unused":
        return not last_run or str(last_run) < cutoff
    return bool(last_run and str(last_run) >= cutoff)


def job_entries(
    client: Client,
    templates: list[dict[str, Any]],
    access: Optional[dict[str, dict[tuple[str, str], dict[str, str]]]] = None,
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
                access[key(template["id"])].values(),
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
    templates = [
        item
        for item in client.list(f"{CONTROLLER}/job_templates/", order_by="name")
        if selected(item, cutoff, mode)
    ]
    if not check_rbac:
        return job_entries(client, templates), cutoff

    templates_by_id = {key(item["id"]): item for item in templates}
    templates_by_ansible_id = {
        key(
            item.get("ansible_id")
            or item.get("summary_fields", {}).get("resource", {}).get("ansible_id")
        ): item
        for item in templates
        if item.get("ansible_id")
        or item.get("summary_fields", {}).get("resource", {}).get("ansible_id")
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

    templates_by_org: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for template in templates:
        organization = template.get("summary_fields", {}).get("organization", {})
        organization_name = organization.get("name")
        if not organization_name:
            organization_name = organizations.get(key(template.get("organization")))
        if organization_name:
            templates_by_org[str(organization_name)].append(template)

    rank = {"view": 1, "execute": 2, "admin": 3}
    access: dict[str, dict[tuple[str, str], dict[str, str]]] = defaultdict(dict)

    def add(
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
        current = access[key(template["id"])].get(identity)
        if current is None or rank[level] > rank[current["level"]]:
            access[key(template["id"])][identity] = entry

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
        for template in templates:
            add(template, "user", identity, level)

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
            if content_type == "awx.jobtemplate":
                template = templates_by_id.get(key(assignment.get("object_id")))
                template = template or templates_by_ansible_id.get(
                    key(assignment.get("object_ansible_id"))
                )
                if template:
                    add(template, principal_type, principal_id, level)
            elif content_type == "shared.organization":
                organization_name = organizations.get(key(assignment.get("object_id")))
                if not organization_name:
                    organization_name = (
                        assignment.get("summary_fields", {})
                        .get("content_object", {})
                        .get("name")
                    )
                for template in templates_by_org.get(str(organization_name), []):
                    add(template, principal_type, principal_id, level)

    return job_entries(client, templates, access), cutoff


def scalar(value: Optional[str]) -> str:
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


def render_yaml(report: list[dict[str, Any]]) -> str:
    lines = ["summary:" + ("" if report else " []")]
    for job in report:
        lines.extend(
            [f"  - name: {scalar(job['name'])}", f"    url: {scalar(job['url'])}"]
        )

    lines.append("job_templates:" + ("" if report else " []"))
    for job in report:
        lines.extend(
            [
                f"  - name: {scalar(job['name'])}",
                f"    url: {scalar(job['url'])}",
                f"    last_run: {scalar(job['last_run'])}",
            ]
        )
        if job["inventory"]:
            lines.extend(
                [
                    "    inventory:",
                    f"      name: {scalar(job['inventory']['name'])}",
                    f"      url: {scalar(job['inventory']['url'])}",
                ]
            )
        else:
            lines.append("    inventory: null")
        lines.append("    credentials:" + ("" if job["credentials"] else " []"))
        for credential in job["credentials"]:
            lines.extend(
                [
                    f"      - name: {scalar(credential['name'])}",
                    f"        url: {scalar(credential['url'])}",
                ]
            )
        if not job["permissions_checked"]:
            lines.append("    permissions_checked: false")
            continue
        lines.append("    permissions:" + ("" if job["permissions"] else " []"))
        for permission in job["permissions"]:
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
        "recent": f"Run within the last {days} days",
        "unused": f"Not run within the last {days} days; never-run jobs included",
        "all": "All Job Templates; no date filter",
    }[mode]
    inventory_count, credential_count = unique_resource_counts(report)
    overview = [
        ["Scope", scope],
        ["Cutoff", cutoff if mode != "all" else "Not applied"],
        ["Job Templates", len(report)],
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
        ["Job Template", "URL"],
        [[job["name"], job["ui_url"]] for job in report],
        [250, 470],
    )

    for job in report:
        if document.y < 150:
            document.new_page()
            page_heading(document, TITLE, "Details - continued")
        add_text(document, job["name"], True)
        add_text(document, f"URL: {job['ui_url']}")
        add_text(document, f"Last run: {job['last_run'] or 'Never'}")
        inventory = job["inventory"]
        add_text(
            document,
            "Inventory: none"
            if not inventory
            else f"Inventory: {inventory['name']} - {inventory['ui_url']}",
        )
        credentials = job["credentials"]
        add_text(
            document,
            "Credentials: none"
            if not credentials
            else "Credentials: "
            + "; ".join(
                f"{item['name']} - {item['ui_url']}" for item in credentials
            ),
        )
        if not job["permissions_checked"]:
            add_text(document, "Permissions: not checked")
            document.y -= 12
            continue
        permission_rows = []
        for permission in job["permissions"]:
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
