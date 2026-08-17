#!/usr/bin/env python3
"""Audit Job Template access across AAP Gateway and Controller identity stores."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from typing import Any, Optional

from export_recent_team_resources import CONTROLLER, GATEWAY, Client, ExportError
from standard_library_pdf import (
    CONTENT_WIDTH,
    MARGIN,
    StandardLibraryPdf,
    page_heading,
    table,
    wrapped_lines,
)


REPORT_TITLE = "AAP Job Template Identity Access Audit"
SOURCES = (("gateway", GATEWAY), ("controller", CONTROLLER))
LEVEL_RANK = {"view": 1, "execute": 2, "admin": 3}


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalized(value: Any) -> str:
    return clean(value).casefold()


def relation_value(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        value = value.get("id") or value.get("ansible_id")
    result = clean(value)
    return result or None


def ansible_id(item: dict[str, Any]) -> str:
    summary = item.get("summary_fields", {})
    resource = summary.get("resource", {}) if isinstance(summary, dict) else {}
    return clean(item.get("ansible_id") or resource.get("ansible_id"))


def organization_label(item: dict[str, Any], organizations: dict[str, str]) -> str:
    summary = item.get("summary_fields", {})
    organization = summary.get("organization", {}) if isinstance(summary, dict) else {}
    if isinstance(organization, dict) and organization.get("name"):
        return clean(organization["name"])
    organization_id = relation_value(item.get("organization"))
    return organizations.get(organization_id or "", "Unknown Organization")


def user_display_name(item: dict[str, Any]) -> str:
    explicit = clean(item.get("name") or item.get("full_name"))
    if explicit:
        return explicit
    return " ".join(
        part for part in (clean(item.get("first_name")), clean(item.get("last_name"))) if part
    )


def content_slug(value: Any) -> str:
    return "".join(character for character in normalized(value) if character.isalnum())


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [prefix + "{}"]
        lines: list[str] = []
        for key, child in value.items():
            if isinstance(child, (dict, list)) and child:
                lines.append(f"{prefix}{key}:")
                lines.extend(yaml_lines(child, indent + 2))
            elif isinstance(child, dict):
                lines.append(f"{prefix}{key}: {{}}")
            elif isinstance(child, list):
                lines.append(f"{prefix}{key}: []")
            else:
                lines.append(f"{prefix}{key}: {yaml_scalar(child)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [prefix + "[]"]
        lines = []
        for child in value:
            if isinstance(child, dict):
                if not child:
                    lines.append(prefix + "- {}")
                    continue
                first_key = next(iter(child))
                first_value = child[first_key]
                if isinstance(first_value, (dict, list)):
                    lines.append(f"{prefix}- {first_key}:")
                    lines.extend(yaml_lines(first_value, indent + 4))
                else:
                    lines.append(f"{prefix}- {first_key}: {yaml_scalar(first_value)}")
                remainder = {key: item for key, item in child.items() if key != first_key}
                if remainder:
                    lines.extend(yaml_lines(remainder, indent + 2))
            elif isinstance(child, list):
                lines.append(prefix + "-")
                lines.extend(yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}- {yaml_scalar(child)}")
        return lines
    return [prefix + yaml_scalar(value)]


def render_yaml(report: dict[str, Any]) -> str:
    return "\n".join(yaml_lines(report)) + "\n"


class AuditCollector:
    def __init__(self, client: Client) -> None:
        self.client = client
        self.coverage: dict[str, dict[str, Any]] = {}
        self.errors: list[dict[str, str]] = []
        self.optional_errors: dict[tuple[str, str, str], str] = {}

    def _coverage(self, source: str, category: str) -> dict[str, Any]:
        key = f"{source}.{category}"
        return self.coverage.setdefault(
            key,
            {"source": source, "endpoint": category, "status": "complete", "calls": 0, "records": 0},
        )

    def list(
        self,
        source: str,
        category: str,
        path: str,
        required: bool = True,
    ) -> list[dict[str, Any]]:
        coverage = self._coverage(source, category)
        coverage["calls"] += 1
        try:
            results = self.client.list(path)
            coverage["records"] += len(results)
            return results
        except ExportError as exc:
            if required:
                coverage["status"] = "incomplete"
                message = str(exc)
                coverage.setdefault("errors", []).append(message)
                self.errors.append(
                    {"source": source, "endpoint": path, "error": message}
                )
            else:
                self.optional_errors[(source, category, path)] = str(exc)
            return []

    def resolve_optional(
        self,
        source: str,
        category: str,
        path: str,
        recovered: bool,
    ) -> None:
        message = self.optional_errors.pop((source, category, path), None)
        if message is None:
            return
        coverage = self._coverage(source, category)
        if recovered:
            if coverage["status"] == "complete":
                coverage["status"] = "derived"
            coverage.setdefault("notes", []).append(
                f"{path}: membership derived from Team Member/Admin role assignments"
            )
            return
        coverage["status"] = "incomplete"
        coverage.setdefault("errors", []).append(message)
        self.errors.append({"source": source, "endpoint": path, "error": message})

    def report(self) -> dict[str, Any]:
        raw: dict[str, dict[str, Any]] = {}
        for source, base in SOURCES:
            organizations = self.list(source, "organizations", f"{base}/organizations/")
            users = self.list(source, "users", f"{base}/users/")
            teams = self.list(source, "teams", f"{base}/teams/")
            definitions = self.list(source, "role_definitions", f"{base}/role_definitions/")
            user_assignments = self.list(
                source, "role_user_assignments", f"{base}/role_user_assignments/"
            )
            team_assignments = self.list(
                source, "role_team_assignments", f"{base}/role_team_assignments/"
            )
            raw[source] = {
                "base": base,
                "organizations": organizations,
                "users": users,
                "teams": teams,
                "definitions": definitions,
                "user_assignments": user_assignments,
                "team_assignments": team_assignments,
            }

        templates = self.list(
            "controller", "job_templates", f"{CONTROLLER}/job_templates/"
        )
        model = build_model(self, raw, templates)
        coverage = sorted(self.coverage.values(), key=lambda item: (item["source"], item["endpoint"]))
        complete = not self.errors
        return {
            "metadata": {
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "aap_url": self.client.base_url,
                "complete": complete,
                "endpoint_coverage": coverage,
            },
            "job_templates": model["job_templates"],
            "global_access": model["global_access"],
            "membership_drift": model["membership_drift"],
            "unresolved_principals": model["unresolved_principals"],
            "collection_errors": self.errors,
        }


def principal_records(
    raw: dict[str, dict[str, Any]], kind: str
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], str], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    for source, source_data in raw.items():
        organizations = {
            clean(item.get("id")): clean(item.get("name"))
            for item in source_data["organizations"]
        }
        for item in source_data[f"{kind}s"]:
            source_id = clean(item.get("id"))
            stable = ansible_id(item)
            if kind == "user":
                natural = normalized(item.get("username"))
                label = clean(item.get("username")) or f"User {source_id}"
            else:
                organization = organization_label(item, organizations)
                natural = f"{normalized(organization)}|{normalized(item.get('name'))}"
                label = clean(item.get("name")) or f"Team {source_id}"
            records.append(
                {
                    "source": source,
                    "source_id": source_id,
                    "stable": stable,
                    "natural": natural,
                    "label": label,
                    "organization": organization_label(item, organizations) if kind == "team" else "",
                    "raw": item,
                }
            )

    by_natural: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_stable: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_natural[record["natural"]].append(record)
        if record["stable"]:
            by_stable[record["stable"]].append(record)

    ambiguous_naturals = {
        natural
        for natural, group in by_natural.items()
        if len({record["stable"] for record in group if record["stable"]}) > 1
        or any(
            sum(record["source"] == source for record in group) > 1
            for source in {record["source"] for record in group}
        )
    }
    ambiguous_stable = {
        stable
        for stable, group in by_stable.items()
        if any(
            sum(record["source"] == source for record in group) > 1
            for source in {record["source"] for record in group}
        )
    }

    merged: dict[str, dict[str, Any]] = {}
    source_map: dict[tuple[str, str], str] = {}
    for record in records:
        natural_group = by_natural[record["natural"]]
        natural_stable_ids = {
            item["stable"] for item in natural_group if item["stable"]
        }
        ambiguous = (
            record["natural"] in ambiguous_naturals
            or record["stable"] in ambiguous_stable
        )
        if record["stable"] and record["stable"] not in ambiguous_stable:
            # AAP's cross-service identity is authoritative even if a username or
            # team name changed between the two API surfaces.
            key = f"{kind}:{record['stable']}"
        elif not ambiguous and len(natural_stable_ids) == 1:
            key = f"{kind}:{next(iter(natural_stable_ids))}"
        elif not ambiguous:
            key = f"{kind}:{record['natural']}"
        else:
            key = f"{kind}:source:{record['source']}:{record['source_id']}"
        if ambiguous:
            unresolved.append(
                {
                    "principal_type": kind,
                    "principal": record["label"],
                    "source": record["source"],
                    "reason": "ambiguous natural identity or conflicting ansible_id",
                }
            )
        source_map[(record["source"], record["source_id"])] = key
        principal = merged.setdefault(
            key,
            {
                "key": key,
                "type": kind,
                "name": record["label"],
                "organization": record["organization"],
                "sources": set(),
                "source_ids": {},
                "raw_by_source": {},
            },
        )
        principal["sources"].add(record["source"])
        principal["source_ids"][record["source"]] = record["source_id"]
        principal["raw_by_source"][record["source"]] = record["raw"]
        if kind == "user":
            display = user_display_name(record["raw"])
            if display:
                principal["display_name"] = display
    return merged, source_map, unresolved


def definition_maps(raw: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        source: {clean(item.get("id")): item for item in data["definitions"]}
        for source, data in raw.items()
    }


def assignment_fact(
    assignment: dict[str, Any],
    source: str,
    principal_type: str,
    definitions: dict[str, dict[str, dict[str, Any]]],
    principal_map: dict[tuple[str, str], str],
    principal_by_stable: dict[str, str],
    evidence: str,
    forced_principal: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    definition_id = relation_value(assignment.get("role_definition")) or ""
    definition = definitions[source].get(definition_id, {})
    summary = assignment.get("summary_fields", {})
    summary_definition = summary.get("role_definition", {}) if isinstance(summary, dict) else {}
    principal_id = relation_value(assignment.get(principal_type))
    stable = clean(assignment.get(f"{principal_type}_ansible_id"))
    principal = forced_principal
    if not principal and principal_id:
        principal = principal_map.get((source, principal_id))
    if not principal and stable:
        principal = principal_by_stable.get(stable)
    if not principal:
        return None
    role = clean(
        definition.get("name")
        or summary_definition.get("name")
        or assignment.get("name")
        or assignment.get("role_field")
        or "Unknown Role"
    )
    content_type = clean(
        assignment.get("content_type")
        or definition.get("content_type")
        or assignment.get("resource_type")
        or summary.get("resource_type")
    )
    content_object = summary.get("content_object", {}) if isinstance(summary, dict) else {}
    resource = summary.get("resource", {}) if isinstance(summary, dict) else {}
    object_id = relation_value(assignment.get("object_id")) or relation_value(resource)
    object_stable = clean(assignment.get("object_ansible_id") or resource.get("ansible_id"))
    object_name = clean(
        assignment.get("resource_name")
        or content_object.get("name")
        or resource.get("name")
        or summary.get("resource_name")
    )
    permissions = sorted(clean(item) for item in definition.get("permissions", []) if clean(item))
    return {
        "principal_type": principal_type,
        "principal": principal,
        "role": role,
        "content_type": content_type,
        "object_id": object_id,
        "object_ansible_id": object_stable,
        "object_name": object_name,
        "permissions": permissions,
        "evidence": evidence,
    }


def legacy_role_fact(
    role: dict[str, Any],
    source: str,
    principal_type: str,
    principal: str,
    evidence: str,
) -> dict[str, Any]:
    summary = role.get("summary_fields", {})
    resource = summary.get("resource", {}) if isinstance(summary, dict) else {}
    return {
        "principal_type": principal_type,
        "principal": principal,
        "role": clean(role.get("name") or role.get("role_field") or "Unknown Role"),
        "content_type": clean(
            role.get("content_type")
            or role.get("resource_type")
            or summary.get("resource_type")
            or resource.get("type")
        ),
        "object_id": relation_value(role.get("object_id")) or relation_value(resource.get("id")),
        "object_ansible_id": clean(role.get("object_ansible_id") or resource.get("ansible_id")),
        "object_name": clean(role.get("resource_name") or summary.get("resource_name") or resource.get("name")),
        "permissions": sorted(clean(item) for item in role.get("permissions", []) if clean(item)),
        "evidence": evidence,
    }


def access_level(fact: dict[str, Any]) -> Optional[str]:
    permissions = set(fact["permissions"])
    if permissions & {"awx.change_jobtemplate", "awx.delete_jobtemplate"}:
        return "admin"
    if "awx.execute_jobtemplate" in permissions:
        return "execute"
    if "awx.view_jobtemplate" in permissions:
        return "view"
    role = normalized(fact["role"])
    if "admin" in role:
        return "admin"
    if "execute" in role:
        return "execute"
    if any(word in role for word in ("audit", "view", "read")):
        return "view"
    return None


def build_model(
    collector: AuditCollector,
    raw: dict[str, dict[str, Any]],
    templates: list[dict[str, Any]],
) -> dict[str, Any]:
    users, user_map, unresolved_users = principal_records(raw, "user")
    teams, team_map, unresolved_teams = principal_records(raw, "team")
    unresolved = unresolved_users + unresolved_teams
    definitions = definition_maps(raw)
    user_by_stable = {
        ansible_id(item): user_map[(source, clean(item.get("id")))]
        for source, data in raw.items()
        for item in data["users"]
        if ansible_id(item) and (source, clean(item.get("id"))) in user_map
    }
    team_by_stable = {
        ansible_id(item): team_map[(source, clean(item.get("id")))]
        for source, data in raw.items()
        for item in data["teams"]
        if ansible_id(item) and (source, clean(item.get("id"))) in team_map
    }

    memberships: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"gateway": set(), "controller": set()}
    )
    membership_checks: list[tuple[str, str, str]] = []
    facts: list[dict[str, Any]] = []

    for source, data in raw.items():
        for assignment in data["user_assignments"]:
            fact = assignment_fact(
                assignment,
                source,
                "user",
                definitions,
                user_map,
                user_by_stable,
                f"{source}:role_user_assignments",
            )
            if fact:
                facts.append(fact)
        for assignment in data["team_assignments"]:
            fact = assignment_fact(
                assignment,
                source,
                "team",
                definitions,
                team_map,
                team_by_stable,
                f"{source}:role_team_assignments",
            )
            if fact:
                facts.append(fact)

        for item in data["users"]:
            source_id = clean(item.get("id"))
            principal = user_map.get((source, source_id))
            related = item.get("related", {}) if isinstance(item.get("related"), dict) else {}
            roles_path = clean(related.get("roles"))
            if principal and roles_path:
                roles = collector.list(source, "legacy_user_roles", roles_path)
                facts.extend(
                    legacy_role_fact(role, source, "user", principal, f"{source}:legacy_user_roles")
                    for role in roles
                )

        for item in data["teams"]:
            source_id = clean(item.get("id"))
            principal = team_map.get((source, source_id))
            related = item.get("related", {}) if isinstance(item.get("related"), dict) else {}
            roles_path = clean(related.get("roles"))
            if principal and roles_path:
                roles = collector.list(source, "legacy_team_roles", roles_path)
                facts.extend(
                    legacy_role_fact(role, source, "team", principal, f"{source}:legacy_team_roles")
                    for role in roles
                )
            users_path = clean(related.get("users")) or f"{data['base']}/teams/{source_id}/users/"
            if principal:
                members = collector.list(
                    source, "team_memberships", users_path, required=False
                )
                membership_checks.append((source, principal, users_path))
                for member in members:
                    member_id = clean(member.get("id"))
                    member_key = user_map.get((source, member_id))
                    if not member_key and ansible_id(member):
                        member_key = user_by_stable.get(ansible_id(member))
                    if not member_key and member.get("username"):
                        candidate = f"user:{normalized(member['username'])}"
                        if candidate in users:
                            member_key = candidate
                    if member_key:
                        memberships[principal][source].add(member_key)

    # Team membership can also be represented as a user role on a team object.
    for fact in facts:
        if fact["principal_type"] != "user":
            continue
        if not content_slug(fact["content_type"]).endswith("team"):
            continue
        if not any(word in normalized(fact["role"]) for word in ("member", "admin")):
            continue
        source = fact["evidence"].split(":", 1)[0]
        team_key = team_map.get((source, clean(fact["object_id"])))
        if team_key:
            memberships[team_key][source].add(fact["principal"])

    for source, principal, users_path in membership_checks:
        collector.resolve_optional(
            source,
            "team_memberships",
            users_path,
            recovered=bool(memberships[principal][source]),
        )

    controller_orgs = {
        clean(item.get("id")): clean(item.get("name"))
        for item in raw["controller"]["organizations"]
    }
    template_models: list[dict[str, Any]] = []
    template_by_id: dict[str, dict[str, Any]] = {}
    template_by_stable: dict[str, dict[str, Any]] = {}
    templates_by_org: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for template in templates:
        template_id = clean(template.get("id"))
        owner = organization_label(template, controller_orgs)
        model = {
            "name": clean(template.get("name")) or f"Job Template {template_id}",
            "owning_organization": owner,
            "api_url": (
                clean(template.get("url"))
                if clean(template.get("url")).startswith(("http://", "https://"))
                else f"{collector.client.base_url}/{(clean(template.get('url')) or f'{CONTROLLER}/job_templates/{template_id}/').lstrip('/')}"
            ),
            "team_access": [],
            "direct_user_access": [],
        }
        template_models.append(model)
        template_by_id[template_id] = model
        stable = ansible_id(template)
        if stable:
            template_by_stable[stable] = model
        templates_by_org[normalized(owner)].append(model)

    grant_groups: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    global_groups: dict[tuple[str, str], dict[str, Any]] = {}
    source_orgs = {
        source: {
            clean(item.get("id")): clean(item.get("name"))
            for item in data["organizations"]
        }
        for source, data in raw.items()
    }

    def add_grant(template: dict[str, Any], fact: dict[str, Any], scope: str) -> None:
        level = access_level(fact)
        if level is None:
            return
        key = (id(template), fact["principal_type"], fact["principal"], scope)
        grant = grant_groups.setdefault(
            key,
            {
                "template": template,
                "principal_type": fact["principal_type"],
                "principal": fact["principal"],
                "scope": scope,
                "roles": set(),
                "levels": set(),
                "evidence_sources": set(),
            },
        )
        grant["roles"].add(fact["role"])
        grant["levels"].add(level)
        grant["evidence_sources"].add(fact["evidence"])

    for fact in facts:
        slug = content_slug(fact["content_type"])
        level = access_level(fact)
        if "jobtemplate" in slug:
            template = template_by_id.get(clean(fact["object_id"]))
            if not template and fact["object_ansible_id"]:
                template = template_by_stable.get(fact["object_ansible_id"])
            if not template and fact["object_name"]:
                candidates = [item for item in template_models if item["name"] == fact["object_name"]]
                template = candidates[0] if len(candidates) == 1 else None
            if template:
                add_grant(template, fact, "direct")
            continue
        if slug.endswith("organization") and level:
            source = fact["evidence"].split(":", 1)[0]
            organization = source_orgs[source].get(clean(fact["object_id"])) or fact["object_name"]
            for template in templates_by_org.get(normalized(organization), []):
                add_grant(template, fact, "organization_inherited")
            continue
        if level and (slug.endswith("global") or not fact["object_id"]):
            key = (fact["principal"], fact["principal_type"])
            global_grant = global_groups.setdefault(
                key,
                {
                    "principal": fact["principal"],
                    "principal_type": fact["principal_type"],
                    "roles": set(),
                    "evidence_sources": set(),
                },
            )
            global_grant["roles"].add(fact["role"])
            global_grant["evidence_sources"].add(fact["evidence"])

    # Explicit administrator/auditor flags are global evidence too.
    for key, user in users.items():
        for source, item in user["raw_by_source"].items():
            roles = []
            if item.get("is_superuser"):
                roles.append("System Administrator")
            if item.get("is_platform_auditor") or item.get("is_system_auditor"):
                roles.append("Platform Auditor")
            if not roles:
                continue
            global_grant = global_groups.setdefault(
                (key, "user"),
                {"principal": key, "principal_type": "user", "roles": set(), "evidence_sources": set()},
            )
            global_grant["roles"].update(roles)
            global_grant["evidence_sources"].add(f"{source}:user_flags")

    def public_user(key: str) -> dict[str, Any]:
        user = users.get(key, {"name": "Unknown User", "display_name": ""})
        active_by_source = {
            source: bool(item.get("is_active", True))
            for source, item in user.get("raw_by_source", {}).items()
        }
        return {
            "username": user.get("name", "Unknown User"),
            "display_name": user.get("display_name", ""),
            "active": all(active_by_source.values()) if active_by_source else True,
            "seen_in": sorted(user.get("sources", [])),
        }

    drift: list[dict[str, Any]] = []
    for team_key, team in teams.items():
        gateway_members = memberships[team_key]["gateway"]
        controller_members = memberships[team_key]["controller"]
        if gateway_members == controller_members:
            continue
        drift.append(
            {
                "team": team["name"],
                "team_organization": team.get("organization", "Unknown Organization"),
                "gateway_only": [public_user(key) for key in sorted(gateway_members - controller_members)],
                "controller_only": [public_user(key) for key in sorted(controller_members - gateway_members)],
            }
        )

    for grant in grant_groups.values():
        template = grant["template"]
        level = max(grant["levels"], key=lambda item: LEVEL_RANK[item])
        base = {
            "roles": sorted(grant["roles"], key=str.casefold),
            "effective_level": level,
            "scope": grant["scope"],
            "evidence_sources": sorted(grant["evidence_sources"]),
        }
        if grant["principal_type"] == "team":
            team = teams.get(grant["principal"], {"name": "Unknown Team", "organization": "Unknown Organization"})
            gateway_members = memberships[grant["principal"]]["gateway"]
            controller_members = memberships[grant["principal"]]["controller"]
            template["team_access"].append(
                {
                    "team": team["name"],
                    "team_organization": team.get("organization", "Unknown Organization"),
                    **base,
                    "members": {
                        "gateway": [public_user(key) for key in sorted(gateway_members)],
                        "controller": [public_user(key) for key in sorted(controller_members)],
                    },
                    "membership_drift": gateway_members != controller_members,
                }
            )
        else:
            template["direct_user_access"].append({**public_user(grant["principal"]), **base})

    for template in template_models:
        template["team_access"].sort(key=lambda item: (normalized(item["team_organization"]), normalized(item["team"])))
        template["direct_user_access"].sort(key=lambda item: normalized(item["username"]))
    template_models.sort(key=lambda item: (normalized(item["owning_organization"]), normalized(item["name"])))

    global_access = []
    for grant in global_groups.values():
        if grant["principal_type"] == "user":
            entry = public_user(grant["principal"])
        else:
            team = teams.get(grant["principal"], {"name": "Unknown Team", "organization": "Unknown Organization"})
            entry = {"team": team["name"], "team_organization": team.get("organization", "Unknown Organization")}
        entry.update(
            {
                "principal_type": grant["principal_type"],
                "roles": sorted(grant["roles"], key=str.casefold),
                "evidence_sources": sorted(grant["evidence_sources"]),
            }
        )
        global_access.append(entry)
    global_access.sort(key=lambda item: (item["principal_type"], normalized(item.get("username") or item.get("team"))))
    drift.sort(key=lambda item: (normalized(item["team_organization"]), normalized(item["team"])))
    return {
        "job_templates": template_models,
        "global_access": global_access,
        "membership_drift": drift,
        "unresolved_principals": unresolved,
    }


def add_wrapped(document: StandardLibraryPdf, value: Any, size: float = 9, bold: bool = False) -> None:
    for line in wrapped_lines(value, CONTENT_WIDTH, size):
        document.text(MARGIN, document.y, line, size, bold)
        document.y -= size + 3


def ensure_page(document: StandardLibraryPdf, height: float, continuation: str) -> None:
    if document.y - height < 34:
        document.new_page()
        page_heading(document, REPORT_TITLE, continuation)


def render_pdf(report: dict[str, Any]) -> bytes:
    document = StandardLibraryPdf()
    page_heading(document, REPORT_TITLE)
    status = "COMPLETE" if report["metadata"]["complete"] else "PARTIAL - review collection errors"
    add_wrapped(document, f"Coverage status: {status}", 10, True)
    add_wrapped(document, f"Generated: {report['metadata']['generated_at']}")
    document.y -= 6

    table(
        document,
        REPORT_TITLE,
        "Summary",
        ["Metric", "Count"],
        [
            ["Job Templates audited", len(report["job_templates"])],
            ["Team access entries", sum(len(item["team_access"]) for item in report["job_templates"])],
            ["Direct user access entries", sum(len(item["direct_user_access"]) for item in report["job_templates"])],
            ["Membership drift entries", len(report["membership_drift"])],
            ["Global access principals", len(report["global_access"])],
            ["Collection errors", len(report["collection_errors"])],
        ],
        [600, 120],
    )
    table(
        document,
        REPORT_TITLE,
        "Endpoint coverage",
        ["Source", "Endpoint", "Status", "Calls", "Records"],
        [
            [item["source"], item["endpoint"], item["status"], item["calls"], item["records"]]
            for item in report["metadata"]["endpoint_coverage"]
        ],
        [100, 300, 120, 90, 110],
    )

    for template_item in report["job_templates"]:
        ensure_page(document, 160, "Job Template details - continued")
        add_wrapped(
            document,
            f"{template_item['owning_organization']} - {template_item['name']}",
            12,
            True,
        )
        add_wrapped(document, f"API: {template_item['api_url']}", 8.5)
        document.y -= 4
        table(
            document,
            REPORT_TITLE,
            "Team access",
            ["Team", "Organization", "Role", "Scope", "Members G/C", "Drift", "Evidence"],
            [
                [
                    item["team"],
                    item["team_organization"],
                    f"{item['effective_level']} ({', '.join(item['roles'])})",
                    item["scope"],
                    f"{len(item['members']['gateway'])}/{len(item['members']['controller'])}",
                    "yes" if item["membership_drift"] else "no",
                    ", ".join(item["evidence_sources"]),
                ]
                for item in template_item["team_access"]
            ],
            [120, 100, 125, 100, 75, 50, 150],
        )
        for team_access in template_item["team_access"]:
            member_rows = []
            member_sources: dict[str, set[str]] = defaultdict(set)
            member_data: dict[str, dict[str, Any]] = {}
            for source in ("gateway", "controller"):
                for member in team_access["members"][source]:
                    member_sources[member["username"]].add(source)
                    member_data[member["username"]] = member
            for username in sorted(member_data, key=str.casefold):
                member = member_data[username]
                member_rows.append(
                    [username, member["display_name"] or "-", "yes" if member["active"] else "no", ", ".join(sorted(member_sources[username]))]
                )
            table(
                document,
                REPORT_TITLE,
                f"Members - {team_access['team']}",
                ["Username", "Display name", "Active", "Membership evidence"],
                member_rows,
                [190, 250, 80, 200],
            )
        table(
            document,
            REPORT_TITLE,
            "Direct user access",
            ["Username", "Display name", "Active", "Role", "Scope", "Evidence"],
            [
                [
                    item["username"],
                    item["display_name"] or "-",
                    "yes" if item["active"] else "no",
                    f"{item['effective_level']} ({', '.join(item['roles'])})",
                    item["scope"],
                    ", ".join(item["evidence_sources"]),
                ]
                for item in template_item["direct_user_access"]
            ],
            [125, 150, 60, 135, 110, 140],
        )

    table(
        document,
        REPORT_TITLE,
        "Global access",
        ["Type", "Principal", "Active", "Roles", "Evidence"],
        [
            [
                item["principal_type"],
                item.get("username") or item.get("team") or "Unknown",
                "yes" if item.get("active", True) else "no",
                ", ".join(item["roles"]),
                ", ".join(item["evidence_sources"]),
            ]
            for item in report["global_access"]
        ],
        [80, 170, 70, 190, 210],
    )
    table(
        document,
        REPORT_TITLE,
        "Membership drift",
        ["Team", "Organization", "Gateway only", "Controller only"],
        [
            [
                item["team"],
                item["team_organization"],
                ", ".join(user["username"] for user in item["gateway_only"]) or "-",
                ", ".join(user["username"] for user in item["controller_only"]) or "-",
            ]
            for item in report["membership_drift"]
        ],
        [160, 130, 215, 215],
    )
    table(
        document,
        REPORT_TITLE,
        "Unresolved principals",
        ["Type", "Principal", "Source", "Reason"],
        [
            [item["principal_type"], item["principal"], item["source"], item["reason"]]
            for item in report["unresolved_principals"]
        ],
        [90, 190, 100, 340],
    )
    table(
        document,
        REPORT_TITLE,
        "Collection errors",
        ["Source", "Endpoint", "Error"],
        [[item["source"], item["endpoint"], item["error"]] for item in report["collection_errors"]],
        [90, 300, 330],
    )
    return document.finish()


def write_reports(report: dict[str, Any], yaml_output: str, pdf_output: str) -> None:
    with open(yaml_output, "w", encoding="utf-8") as target:
        target.write(render_yaml(report))
    with open(pdf_output, "wb") as target:
        target.write(render_pdf(report))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit user and team access to every AAP Controller Job Template."
    )
    parser.add_argument("--yaml-output", default="job-template-identity-access.yaml")
    parser.add_argument("--pdf-output", default="job-template-identity-access.pdf")
    args = parser.parse_args()
    try:
        report = AuditCollector(Client()).report()
        write_reports(report, args.yaml_output, args.pdf_output)
        print(f"Wrote {args.yaml_output}", file=sys.stderr)
        print(f"Wrote {args.pdf_output}", file=sys.stderr)
        return 0 if report["metadata"]["complete"] else 2
    except (ExportError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
