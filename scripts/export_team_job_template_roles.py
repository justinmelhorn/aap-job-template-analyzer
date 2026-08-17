#!/usr/bin/env python3
"""Report Controller Job Template roles assigned directly to AAP teams.

AAP 2.5 gives teams UUIDs in Platform Gateway while Controller continues to
use its original integer team IDs for legacy resource permissions.  This
report deliberately reads role assignments through each Controller team's
``roles`` relationship.  Gateway teams are used only to add the corresponding
UUID to the mapping summary; a Gateway UUID is never sent to Controller.
"""
from __future__ import annotations

import argparse
import html
import sys
import textwrap
from collections import defaultdict
from typing import Any, Optional

from export_recent_team_resources import (
    CONTROLLER,
    GATEWAY,
    Client,
    ExportError,
    relation_id,
)


def text(value: Any) -> str:
    return str(value or "").strip()


def markdown_text(value: Any) -> str:
    return html.escape(str(value), quote=False).replace("|", "&#124;").replace("\n", " ")


def normalized(value: Any) -> str:
    return text(value).casefold()


def related_id(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        value = value.get("id")
    value = text(value)
    return value or None


def organization_name(item: dict[str, Any], organizations: dict[str, str]) -> str:
    summary = item.get("summary_fields", {}).get("organization", {})
    if isinstance(summary, dict) and summary.get("name"):
        return text(summary["name"])
    organization = related_id(item.get("organization"))
    if organization:
        return organizations.get(organization, "Unknown Organization")
    return "Unknown Organization"


def team_key(organization: str, team: str) -> tuple[str, str]:
    return normalized(organization), normalized(team)


def load_gateway_teams(
    client: Client,
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """Index Gateway teams by organization/name and, as a safe fallback, name."""
    organizations = {
        text(item.get("id")): text(item.get("name"))
        for item in client.list(f"{GATEWAY}/organizations/")
    }
    exact: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for team in client.list(f"{GATEWAY}/teams/"):
        name = text(team.get("name"))
        organization = organization_name(team, organizations)
        if not name:
            continue
        exact[team_key(organization, name)].append(team)
        by_name[normalized(name)].append(team)
    return dict(exact), dict(by_name)


def match_gateway_team(
    controller_team: dict[str, Any],
    controller_organizations: dict[str, str],
    exact: dict[tuple[str, str], list[dict[str, Any]]],
    by_name: dict[str, list[dict[str, Any]]],
) -> tuple[Optional[str], str]:
    team = text(controller_team.get("name"))
    organization = organization_name(controller_team, controller_organizations)
    exact_matches = exact.get(team_key(organization, team), [])
    if len(exact_matches) == 1:
        return related_id(exact_matches[0].get("id")), "matched"
    if len(exact_matches) > 1:
        return None, "ambiguous"
    name_matches = by_name.get(normalized(team), [])
    if len(name_matches) == 1:
        return related_id(name_matches[0].get("id")), "matched_by_unique_name"
    if len(name_matches) > 1:
        return None, "ambiguous"
    return None, "not_found"


def role_resource(role: dict[str, Any]) -> dict[str, Any]:
    resource = role.get("summary_fields", {}).get("resource", {})
    return resource if isinstance(resource, dict) else {}


def is_job_template_role(role: dict[str, Any]) -> bool:
    summary = role.get("summary_fields", {})
    resource = role_resource(role)
    candidates = (
        role.get("content_type"),
        role.get("resource_type"),
        summary.get("resource_type"),
        resource.get("type"),
        resource.get("resource_type"),
    )
    normalized_candidates = {
        "".join(character for character in normalized(candidate) if character.isalnum())
        for candidate in candidates
        if candidate
    }
    return any(candidate.endswith("jobtemplate") for candidate in normalized_candidates)


def role_name(role: dict[str, Any]) -> str:
    name = text(role.get("name"))
    if name:
        return name
    field = text(role.get("role_field"))
    if field.endswith("_role"):
        field = field[:-5]
    return field.replace("_", " ").title() or "Unknown Role"


def job_template_identity(role: dict[str, Any]) -> tuple[Optional[int], str, str]:
    summary = role.get("summary_fields", {})
    resource = role_resource(role)
    template_id = relation_id(role.get("object_id")) or relation_id(resource.get("id"))
    name = text(
        resource.get("name")
        or role.get("resource_name")
        or summary.get("resource_name")
    )
    url = text(resource.get("url"))
    return template_id, name, url


def build_report(client: Client) -> dict[str, Any]:
    controller_organization_items = client.list(f"{CONTROLLER}/organizations/")
    controller_organizations = {
        text(item.get("id")): text(item.get("name"))
        for item in controller_organization_items
    }
    controller_teams = client.list(f"{CONTROLLER}/teams/")

    gateway_error: Optional[str] = None
    try:
        gateway_exact, gateway_by_name = load_gateway_teams(client)
    except ExportError as exc:
        # Gateway mapping is useful context, but Controller is the source of
        # truth for these AAP 2.5 Job Template assignments.
        gateway_exact, gateway_by_name = {}, {}
        gateway_error = str(exc)

    rows: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    template_cache: dict[int, dict[str, Any]] = {}
    teams_with_roles: set[int] = set()

    for team in controller_teams:
        controller_team_id = relation_id(team.get("id"))
        if controller_team_id is None:
            continue
        team_name = text(team.get("name")) or f"Team {controller_team_id}"
        team_organization = organization_name(team, controller_organizations)
        if gateway_error:
            gateway_team_id, mapping_status = None, "gateway_unavailable"
        else:
            gateway_team_id, mapping_status = match_gateway_team(
                team,
                controller_organizations,
                gateway_exact,
                gateway_by_name,
            )
        mappings.append(
            {
                "organization": team_organization,
                "team": team_name,
                "controller_team_id": controller_team_id,
                "gateway_team_id": gateway_team_id,
                "mapping_status": mapping_status,
            }
        )

        roles_url = text(team.get("related", {}).get("roles"))
        if not roles_url:
            roles_url = f"{CONTROLLER}/teams/{controller_team_id}/roles/"
        for role in client.list(roles_url):
            if not is_job_template_role(role):
                continue
            template_id, template_name, template_url = job_template_identity(role)
            if template_id is None:
                continue
            if not template_name:
                if template_id not in template_cache:
                    template_cache[template_id] = client.get(
                        f"{CONTROLLER}/job_templates/{template_id}/"
                    )
                template = template_cache[template_id]
                template_name = text(template.get("name")) or f"Job Template {template_id}"
                template_url = template_url or text(template.get("url"))
            rows.append(
                {
                    "organization": team_organization,
                    "team": team_name,
                    "role": role_name(role),
                    "job_template": template_name,
                    "job_template_id": template_id,
                    "job_template_api_url": (
                        template_url
                        if template_url.startswith(("http://", "https://"))
                        else f"{client.base_url}/{(template_url or f'{CONTROLLER}/job_templates/{template_id}/').lstrip('/')}"
                    ),
                    "controller_team_id": controller_team_id,
                    "gateway_team_id": gateway_team_id,
                }
            )
            teams_with_roles.add(controller_team_id)

    unique_rows = {
        (
            row["controller_team_id"],
            row["job_template_id"],
            normalized(row["role"]),
        ): row
        for row in rows
    }
    rows = sorted(
        unique_rows.values(),
        key=lambda row: (
            normalized(row["organization"]),
            normalized(row["team"]),
            normalized(row["job_template"]),
            normalized(row["role"]),
        ),
    )
    mappings.sort(key=lambda item: (normalized(item["organization"]), normalized(item["team"])))
    return {
        "teams_scanned": len(controller_teams),
        "teams_with_job_template_roles": len(teams_with_roles),
        "assignments": rows,
        "team_mappings": mappings,
        "gateway_error": gateway_error,
    }


def render_markdown(report: dict[str, Any]) -> str:
    rows = report["assignments"]
    mappings = report["team_mappings"]
    matched = sum(item["gateway_team_id"] is not None for item in mappings)
    lines = [
        "# AAP Team → Job Template Role Report",
        "",
        (
            "> Controller is the permission source of truth. Gateway UUIDs are "
            "matched automatically and are never used to query Controller roles."
        ),
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Controller teams scanned | {report['teams_scanned']} |",
        f"| Teams with direct Job Template roles | {report['teams_with_job_template_roles']} |",
        f"| Team → role → Job Template assignments | {len(rows)} |",
        f"| Teams matched to Gateway UUIDs | {matched} |",
        "",
        "## Job Template roles",
        "",
    ]
    if rows:
        lines.extend(
            [
                "| Organization | Team | Role | Job Template |",
                "| --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            template_url = str(row["job_template_api_url"]).replace(" ", "%20").replace(")", "%29")
            lines.append(
                f"| {markdown_text(row['organization'])} | {markdown_text(row['team'])} | "
                f"{markdown_text(row['role'])} | {markdown_text(row['job_template'])} "
                f"([API]({template_url})) |"
            )
    else:
        lines.append("No direct team Job Template roles were found in Controller.")
    lines.extend(["", "## Team ID mapping", ""])
    if report.get("gateway_error"):
        lines.extend(
            [
                "Gateway team mapping was unavailable. The Controller role report is still complete.",
                "",
            ]
        )
    lines.extend(
        [
            "| Organization | Team | Controller team ID | Gateway team UUID | Status |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    status_labels = {
        "matched": "Matched by organization and name",
        "matched_by_unique_name": "Matched by unique team name",
        "ambiguous": "Ambiguous",
        "not_found": "Not found in Gateway",
        "gateway_unavailable": "Gateway unavailable",
    }
    for item in mappings:
        lines.append(
            f"| {markdown_text(item['organization'])} | {markdown_text(item['team'])} | "
            f"{item['controller_team_id']} | {markdown_text(item['gateway_team_id'] or '—')} | "
            f"{status_labels[item['mapping_status']]} |"
        )
    lines.extend(
        [
            "",
            (
                "Only roles whose Controller resource type is `job_template` are included; "
                "inventory, credential, project, workflow, and other role records are filtered out."
            ),
            "",
        ]
    )
    return "\n".join(lines)


PDF_PAGE_WIDTH = 792
PDF_PAGE_HEIGHT = 612
PDF_MARGIN = 36
PDF_CONTENT_WIDTH = PDF_PAGE_WIDTH - (PDF_MARGIN * 2)


def pdf_string(value: Any) -> str:
    """Return a PDF-safe WinAnsi literal using only ASCII source bytes."""
    encoded = str(value).encode("cp1252", errors="replace")
    escaped = []
    for byte in encoded:
        if byte in (40, 41, 92):
            escaped.append("\\" + chr(byte))
        elif 32 <= byte <= 126:
            escaped.append(chr(byte))
        else:
            escaped.append(f"\\{byte:03o}")
    return "".join(escaped)


class StandardLibraryPdf:
    """Tiny PDF 1.4 writer for text-and-table reports."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = []
        self.current: list[str] = []
        self.y = PDF_PAGE_HEIGHT - PDF_MARGIN
        self.new_page()

    def new_page(self) -> None:
        if self.current:
            self.pages.append(self.current)
        self.current = []
        self.y = PDF_PAGE_HEIGHT - PDF_MARGIN

    def text(
        self,
        x: float,
        y: float,
        value: Any,
        size: float = 9,
        bold: bool = False,
    ) -> None:
        font = "F2" if bold else "F1"
        self.current.append(
            f"BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm "
            f"({pdf_string(value)}) Tj ET"
        )

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.current.append(
            f"0.70 G 0.50 w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S 0 G"
        )

    def rectangle(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        fill_gray: Optional[float] = None,
    ) -> None:
        if fill_gray is not None:
            self.current.append(
                f"{fill_gray:.2f} g {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f 0 g"
            )
        self.current.append(
            f"0.70 G 0.50 w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re S 0 G"
        )

    def finish(self) -> bytes:
        if self.current:
            self.pages.append(self.current)
            self.current = []
        page_count = len(self.pages)
        objects: list[bytes] = [b""] * (5 + page_count * 2)
        page_ids = [5 + index * 2 for index in range(page_count)]
        objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[2] = (
            f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii")
        )
        objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        objects[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

        for index, commands in enumerate(self.pages):
            page_id = page_ids[index]
            content_id = page_id + 1
            footer = (
                f"BT /F1 8.00 Tf 1 0 0 1 {PDF_PAGE_WIDTH / 2 - 22:.2f} 18.00 Tm "
                f"(Page {index + 1} of {page_count}) Tj ET"
            )
            stream = ("\n".join(commands + [footer]) + "\n").encode("ascii")
            objects[page_id] = (
                "<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {PDF_PAGE_WIDTH} {PDF_PAGE_HEIGHT}] "
                "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
            objects[content_id] = (
                f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
                + stream
                + b"endstream"
            )

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for object_id in range(1, len(objects)):
            offsets.append(len(output))
            output.extend(f"{object_id} 0 obj\n".encode("ascii"))
            output.extend(objects[object_id])
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {len(objects)}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(output)


def pdf_wrapped_lines(value: Any, width: float, font_size: float = 9) -> list[str]:
    characters = max(1, int((width - 10) / (font_size * 0.52)))
    lines: list[str] = []
    for paragraph in str(value).replace("\t", " ").splitlines() or [""]:
        lines.extend(
            textwrap.wrap(
                paragraph,
                width=characters,
                break_long_words=True,
                break_on_hyphens=True,
            )
            or [""]
        )
    return lines


def pdf_page_heading(document: StandardLibraryPdf, continuation: str = "") -> None:
    document.text(PDF_MARGIN, document.y, "AAP Team Job Template Role Report", 16, True)
    if continuation:
        document.text(PDF_MARGIN + 330, document.y + 1, continuation, 9)
    document.y -= 14
    document.line(PDF_MARGIN, document.y, PDF_PAGE_WIDTH - PDF_MARGIN, document.y)
    document.y -= 18


def pdf_table(
    document: StandardLibraryPdf,
    section_title: str,
    headers: list[str],
    rows: list[list[Any]],
    widths: list[float],
) -> None:
    row_number = 0

    def draw_header() -> None:
        x = PDF_MARGIN
        height = 24
        for header, width in zip(headers, widths):
            document.rectangle(x, document.y - height, width, height, 0.90)
            document.text(x + 5, document.y - 15, header, 8.5, True)
            x += width
        document.y -= height

    if document.y < 105:
        document.new_page()
        pdf_page_heading(document, f"{section_title} - continued")
    document.text(PDF_MARGIN, document.y, section_title, 12, True)
    document.y -= 16
    draw_header()

    if not rows:
        document.text(PDF_MARGIN + 5, document.y - 16, "No matching records were found.", 9)
        document.y -= 28
        return

    for row in rows:
        wrapped = [
            pdf_wrapped_lines(value, width, 8.5)
            for value, width in zip(row, widths)
        ]
        height = max(24, max(len(lines) for lines in wrapped) * 11 + 8)
        if document.y - height < 34:
            document.new_page()
            pdf_page_heading(document, f"{section_title} - continued")
            draw_header()
        x = PDF_MARGIN
        fill = 0.97 if row_number % 2 else None
        for lines, width in zip(wrapped, widths):
            document.rectangle(x, document.y - height, width, height, fill)
            baseline = document.y - 14
            for line in lines:
                document.text(x + 5, baseline, line, 8.5)
                baseline -= 11
            x += width
        document.y -= height
        row_number += 1
    document.y -= 12


def render_pdf(report: dict[str, Any]) -> bytes:
    document = StandardLibraryPdf()
    pdf_page_heading(document)
    subtitle = (
        "Controller is the permission source of truth. Gateway UUIDs are matched "
        "automatically and are never used to query Controller roles."
    )
    for line in pdf_wrapped_lines(subtitle, PDF_CONTENT_WIDTH, 9):
        document.text(PDF_MARGIN, document.y, line, 9)
        document.y -= 12
    document.y -= 5

    document.text(PDF_MARGIN, document.y, "Summary", 12, True)
    document.y -= 16
    summary_rows = [
        ["Controller teams scanned", report["teams_scanned"]],
        ["Teams with direct Job Template roles", report["teams_with_job_template_roles"]],
        ["Team - role - Job Template assignments", len(report["assignments"])],
        [
            "Teams matched to Gateway UUIDs",
            sum(item["gateway_team_id"] is not None for item in report["team_mappings"]),
        ],
    ]
    for label, count in summary_rows:
        document.text(PDF_MARGIN + 6, document.y, label, 9)
        document.text(PDF_MARGIN + 360, document.y, count, 9, True)
        document.y -= 14
    document.y -= 8

    assignment_rows = [
        [row["organization"], row["team"], row["role"], row["job_template"]]
        for row in report["assignments"]
    ]
    pdf_table(
        document,
        "Job Template roles",
        ["Organization", "Team", "Role", "Job Template"],
        assignment_rows,
        [130, 170, 90, 330],
    )

    status_labels = {
        "matched": "Matched by organization and name",
        "matched_by_unique_name": "Matched by unique team name",
        "ambiguous": "Ambiguous",
        "not_found": "Not found in Gateway",
        "gateway_unavailable": "Gateway unavailable",
    }
    mapping_rows = [
        [
            item["organization"],
            item["team"],
            item["controller_team_id"],
            item["gateway_team_id"] or "-",
            status_labels[item["mapping_status"]],
        ]
        for item in report["team_mappings"]
    ]
    pdf_table(
        document,
        "Team ID mapping",
        ["Organization", "Team", "Controller ID", "Gateway UUID", "Status"],
        mapping_rows,
        [110, 150, 80, 230, 150],
    )
    return document.finish()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report every Controller team role assigned directly to a Job Template."
    )
    parser.add_argument(
        "--output",
        default="-",
        help="PDF file path; default is stdout",
    )
    args = parser.parse_args()
    try:
        rendered = render_pdf(build_report(Client()))
        if args.output == "-":
            sys.stdout.buffer.write(rendered)
        else:
            with open(args.output, "wb") as target:
                target.write(rendered)
            print(f"Wrote {args.output}", file=sys.stderr)
    except (ExportError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
