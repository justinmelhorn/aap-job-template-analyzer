#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "export_job_template_identity_access.py"
SPEC = importlib.util.spec_from_file_location("export_job_template_identity_access", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeClient:
    base_url = "https://aap.example.com"

    def list(self, path, **params):
        data = {
            "/api/gateway/v1/organizations/": [
                {"id": "g-org", "name": "Payments"}
            ],
            "/api/controller/v2/organizations/": [
                {"id": 1, "name": "Payments"}
            ],
            "/api/gateway/v1/users/": [
                {
                    "id": "g-alice",
                    "ansible_id": "user-alice",
                    "username": "alice",
                    "first_name": "Alice",
                    "last_name": "Adams",
                    "email": "must-not-appear@example.com",
                    "is_active": True,
                    "related": {"roles": "/gateway/users/alice/roles/"},
                },
                {
                    "id": "g-bob",
                    "ansible_id": "user-bob",
                    "username": "bob",
                    "first_name": "Bob",
                    "last_name": "Brown",
                    "is_active": True,
                    "related": {"roles": "/gateway/users/bob/roles/"},
                },
                {
                    "id": "g-carol",
                    "ansible_id": "user-carol",
                    "username": "carol",
                    "first_name": "Carol",
                    "last_name": "Clark",
                    "is_active": False,
                    "is_platform_auditor": True,
                    "related": {"roles": "/gateway/users/carol/roles/"},
                },
            ],
            "/api/controller/v2/users/": [
                {
                    "id": 1,
                    "ansible_id": "user-alice",
                    "username": "alice",
                    "first_name": "Alice",
                    "last_name": "Adams",
                    "is_active": True,
                    "related": {"roles": "/controller/users/1/roles/"},
                },
                {
                    "id": 2,
                    "ansible_id": "user-bob",
                    "username": "bob",
                    "first_name": "Bob",
                    "last_name": "Brown",
                    "is_active": True,
                    "related": {"roles": "/controller/users/2/roles/"},
                },
                {
                    "id": 3,
                    "ansible_id": "user-dave",
                    "username": "dave",
                    "first_name": "Dave",
                    "last_name": "Dunn",
                    "is_active": True,
                    "related": {"roles": "/controller/users/3/roles/"},
                },
                {
                    "id": 4,
                    "ansible_id": "user-carol",
                    "username": "carol",
                    "is_active": False,
                    "related": {"roles": "/controller/users/4/roles/"},
                },
            ],
            "/api/gateway/v1/teams/": [
                {
                    "id": "g-ops",
                    "ansible_id": "team-ops",
                    "name": "Payments Operators",
                    "organization": "g-org",
                    "related": {
                        "roles": "/gateway/teams/ops/roles/",
                        "users": "/gateway/teams/ops/users/",
                    },
                },
                {
                    "id": "g-legacy",
                    "ansible_id": "team-legacy",
                    "name": "Payments Legacy",
                    "organization": "g-org",
                    "related": {
                        "roles": "/gateway/teams/legacy/roles/",
                        "users": "/gateway/teams/legacy/users/",
                    },
                },
            ],
            "/api/controller/v2/teams/": [
                {
                    "id": 10,
                    "ansible_id": "team-ops",
                    "name": "Payments Operators",
                    "organization": 1,
                    "related": {
                        "roles": "/controller/teams/10/roles/",
                        "users": "/controller/teams/10/users/",
                    },
                },
                {
                    "id": 20,
                    "ansible_id": "team-legacy",
                    "name": "Payments Legacy",
                    "organization": 1,
                    "related": {
                        "roles": "/controller/teams/20/roles/",
                        "users": "/controller/teams/20/users/",
                    },
                },
            ],
            "/api/gateway/v1/role_definitions/": [
                {
                    "id": "g-execute",
                    "name": "Execute",
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.execute_jobtemplate", "awx.view_jobtemplate"],
                },
                {
                    "id": "g-view",
                    "name": "View",
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.view_jobtemplate"],
                },
                {
                    "id": "g-member",
                    "name": "Team Member",
                    "content_type": "shared.team",
                    "permissions": [],
                },
            ],
            "/api/controller/v2/role_definitions/": [
                {
                    "id": 11,
                    "name": "Execute",
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.execute_jobtemplate", "awx.view_jobtemplate"],
                },
                {
                    "id": 12,
                    "name": "View",
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.view_jobtemplate"],
                },
                {
                    "id": 13,
                    "name": "Organization Admin",
                    "content_type": "shared.organization",
                    "permissions": ["awx.change_jobtemplate", "awx.execute_jobtemplate"],
                },
                {
                    "id": 14,
                    "name": "Admin",
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.change_jobtemplate", "awx.execute_jobtemplate"],
                },
            ],
            "/api/gateway/v1/role_team_assignments/": [
                {
                    "team": "g-ops",
                    "role_definition": "g-execute",
                    "content_type": "awx.jobtemplate",
                    "object_id": "100",
                    "object_ansible_id": "jt-deploy",
                }
            ],
            "/api/controller/v2/role_team_assignments/": [
                {
                    "team": 10,
                    "role_definition": 11,
                    "content_type": "awx.jobtemplate",
                    "object_id": "100",
                    "object_ansible_id": "jt-deploy",
                },
                {
                    "team": 20,
                    "role_definition": 13,
                    "content_type": "shared.organization",
                    "object_id": "1",
                    "summary_fields": {"content_object": {"name": "Payments"}},
                },
            ],
            "/api/gateway/v1/role_user_assignments/": [
                {
                    "user": "g-alice",
                    "role_definition": "g-view",
                    "content_type": "awx.jobtemplate",
                    "object_id": "100",
                    "object_ansible_id": "jt-deploy",
                },
                {
                    "user": "g-bob",
                    "role_definition": "g-member",
                    "content_type": "shared.team",
                    "object_id": "g-ops",
                },
            ],
            "/api/controller/v2/role_user_assignments/": [
                {
                    "user": 1,
                    "role_definition": 12,
                    "content_type": "awx.jobtemplate",
                    "object_id": "100",
                    "object_ansible_id": "jt-deploy",
                },
                {
                    "user": 3,
                    "role_definition": 14,
                    "content_type": "awx.jobtemplate",
                    "object_id": "100",
                    "object_ansible_id": "jt-deploy",
                },
            ],
            "/api/controller/v2/job_templates/": [
                {
                    "id": 100,
                    "ansible_id": "jt-deploy",
                    "name": "Deploy Payments",
                    "url": "/api/controller/v2/job_templates/100/",
                    "summary_fields": {"organization": {"id": 1, "name": "Payments"}},
                },
                {
                    "id": 200,
                    "ansible_id": "jt-audit",
                    "name": "Audit Payments",
                    "url": "/api/controller/v2/job_templates/200/",
                    "summary_fields": {"organization": {"id": 1, "name": "Payments"}},
                },
            ],
            "/gateway/users/alice/roles/": [
                {
                    "name": "View",
                    "content_type": "jobtemplate",
                    "object_id": 100,
                    "summary_fields": {"resource": {"id": 100, "name": "Deploy Payments"}},
                }
            ],
            "/gateway/users/bob/roles/": [],
            "/gateway/users/carol/roles/": [],
            "/controller/users/1/roles/": [],
            "/controller/users/2/roles/": [],
            "/controller/users/3/roles/": [
                {
                    "name": "Admin",
                    "content_type": "jobtemplate",
                    "object_id": 100,
                    "summary_fields": {"resource": {"id": 100, "name": "Deploy Payments"}},
                }
            ],
            "/controller/users/4/roles/": [],
            "/gateway/teams/ops/roles/": [],
            "/gateway/teams/legacy/roles/": [],
            "/controller/teams/10/roles/": [],
            "/controller/teams/20/roles/": [
                {
                    "name": "View",
                    "content_type": "jobtemplate",
                    "object_id": 200,
                    "summary_fields": {"resource": {"id": 200, "name": "Audit Payments"}},
                }
            ],
            "/gateway/teams/ops/users/": [
                {"id": "g-alice", "ansible_id": "user-alice", "username": "alice"},
                {"id": "g-bob", "ansible_id": "user-bob", "username": "bob"},
            ],
            "/controller/teams/10/users/": [
                {"id": 1, "ansible_id": "user-alice", "username": "alice"},
                {"id": 3, "ansible_id": "user-dave", "username": "dave"},
            ],
            "/gateway/teams/legacy/users/": [{"id": "g-bob", "username": "bob"}],
            "/controller/teams/20/users/": [{"id": 2, "username": "bob"}],
        }
        if path not in data:
            raise AssertionError(path)
        return data[path]


class PartialClient(FakeClient):
    def list(self, path, **params):
        if path == "/api/gateway/v1/role_user_assignments/":
            raise MODULE.ExportError("GET gateway role users returned HTTP 403")
        return super().list(path, **params)


class MembershipFallbackClient(FakeClient):
    def list(self, path, **params):
        if path == "/gateway/teams/ops/users/":
            raise MODULE.ExportError("GET Gateway team users returned HTTP 404")
        return super().list(path, **params)


class AmbiguousClient(FakeClient):
    def list(self, path, **params):
        if path == "/gateway/users/alice-duplicate/roles/":
            return []
        records = super().list(path, **params)
        if path == "/api/gateway/v1/users/":
            return records + [
                {
                    "id": "g-alice-duplicate",
                    "ansible_id": "user-alice-conflict",
                    "username": "alice",
                    "is_active": True,
                    "related": {"roles": "/gateway/users/alice-duplicate/roles/"},
                }
            ]
        return records


class RenamedUserClient(FakeClient):
    def list(self, path, **params):
        records = copy.deepcopy(super().list(path, **params))
        if path == "/api/controller/v2/users/":
            next(item for item in records if item["ansible_id"] == "user-alice")[
                "username"
            ] = "alice-renamed"
        if path == "/controller/teams/10/users/":
            records[0]["username"] = "alice-renamed"
        return records


class IdentityAuditTests(unittest.TestCase):
    def setUp(self):
        self.report = MODULE.AuditCollector(FakeClient()).report()
        self.templates = {item["name"]: item for item in self.report["job_templates"]}

    def test_collects_both_surfaces_and_all_templates(self):
        self.assertTrue(self.report["metadata"]["complete"])
        self.assertEqual({"Deploy Payments", "Audit Payments"}, set(self.templates))
        coverage = {
            (item["source"], item["endpoint"]): item
            for item in self.report["metadata"]["endpoint_coverage"]
        }
        for source in ("gateway", "controller"):
            self.assertIn((source, "role_user_assignments"), coverage)
            self.assertIn((source, "role_team_assignments"), coverage)
            self.assertIn((source, "legacy_user_roles"), coverage)
            self.assertIn((source, "legacy_team_roles"), coverage)
            self.assertIn((source, "team_memberships"), coverage)

    def test_dedupes_direct_grants_but_retains_evidence(self):
        deploy = self.templates["Deploy Payments"]
        operators = next(item for item in deploy["team_access"] if item["team"] == "Payments Operators")
        self.assertEqual("execute", operators["effective_level"])
        self.assertEqual("direct", operators["scope"])
        self.assertIn("gateway:role_team_assignments", operators["evidence_sources"])
        self.assertIn("controller:role_team_assignments", operators["evidence_sources"])

        alice = next(item for item in deploy["direct_user_access"] if item["username"] == "alice")
        self.assertEqual("view", alice["effective_level"])
        self.assertIn("gateway:legacy_user_roles", alice["evidence_sources"])
        self.assertIn("gateway:role_user_assignments", alice["evidence_sources"])
        self.assertIn("controller:role_user_assignments", alice["evidence_sources"])

    def test_organization_and_legacy_grants_are_included(self):
        for template in self.templates.values():
            legacy = next(item for item in template["team_access"] if item["team"] == "Payments Legacy")
            if template["name"] == "Deploy Payments":
                self.assertEqual("organization_inherited", legacy["scope"])
                self.assertEqual("admin", legacy["effective_level"])
            else:
                scopes = {item["scope"] for item in template["team_access"] if item["team"] == "Payments Legacy"}
                self.assertEqual({"direct", "organization_inherited"}, scopes)

    def test_membership_drift_is_explicit_and_members_are_source_specific(self):
        deploy = self.templates["Deploy Payments"]
        operators = next(item for item in deploy["team_access"] if item["team"] == "Payments Operators")
        self.assertTrue(operators["membership_drift"])
        self.assertEqual(
            {"alice", "bob"},
            {item["username"] for item in operators["members"]["gateway"]},
        )
        self.assertEqual(
            {"alice", "dave"},
            {item["username"] for item in operators["members"]["controller"]},
        )
        drift = next(item for item in self.report["membership_drift"] if item["team"] == "Payments Operators")
        self.assertEqual(["bob"], [item["username"] for item in drift["gateway_only"]])
        self.assertEqual(["dave"], [item["username"] for item in drift["controller_only"]])

    def test_direct_users_inactive_globals_and_privacy(self):
        deploy = self.templates["Deploy Payments"]
        self.assertIn("dave", {item["username"] for item in deploy["direct_user_access"]})
        carol = next(item for item in self.report["global_access"] if item.get("username") == "carol")
        self.assertFalse(carol["active"])
        self.assertIn("Platform Auditor", carol["roles"])
        rendered = MODULE.render_yaml(self.report)
        self.assertNotIn("must-not-appear@example.com", rendered)
        self.assertNotIn("team_mappings", rendered)
        self.assertNotIn("Gateway team UUID", rendered)

    def test_pdf_contains_access_and_not_id_mapping(self):
        rendered = MODULE.render_pdf(self.report)
        self.assertTrue(rendered.startswith(b"%PDF-1.4"))
        self.assertIn(b"AAP Job Template Identity Access Audit", rendered)
        self.assertIn(b"Payments Operators", rendered)
        self.assertIn(b"Direct user access", rendered)
        self.assertIn(b"Membership drift", rendered)
        self.assertNotIn(b"Team ID mapping", rendered)
        self.assertNotIn(b"Gateway UUID", rendered)

    def test_partial_scan_writes_artifacts_and_is_marked_incomplete(self):
        report = MODULE.AuditCollector(PartialClient()).report()
        self.assertFalse(report["metadata"]["complete"])
        self.assertEqual(1, len(report["collection_errors"]))
        with tempfile.TemporaryDirectory() as directory:
            yaml_path = str(Path(directory) / "audit.yaml")
            pdf_path = str(Path(directory) / "audit.pdf")
            MODULE.write_reports(report, yaml_path, pdf_path)
            self.assertIn('complete: false', Path(yaml_path).read_text())
            self.assertTrue(Path(pdf_path).read_bytes().startswith(b"%PDF-1.4"))

    def test_partial_cli_writes_both_artifacts_and_exits_two(self):
        with tempfile.TemporaryDirectory() as directory:
            yaml_path = str(Path(directory) / "audit.yaml")
            pdf_path = str(Path(directory) / "audit.pdf")
            argv = [
                str(MODULE_PATH),
                "--yaml-output",
                yaml_path,
                "--pdf-output",
                pdf_path,
            ]
            with mock.patch.object(MODULE, "Client", PartialClient), mock.patch.object(
                sys, "argv", argv
            ):
                self.assertEqual(2, MODULE.main())
            self.assertTrue(Path(yaml_path).exists())
            self.assertTrue(Path(pdf_path).exists())

    def test_unavailable_membership_endpoint_can_be_derived_from_role_assignments(self):
        report = MODULE.AuditCollector(MembershipFallbackClient()).report()
        self.assertTrue(report["metadata"]["complete"])
        coverage = next(
            item
            for item in report["metadata"]["endpoint_coverage"]
            if item["source"] == "gateway" and item["endpoint"] == "team_memberships"
        )
        self.assertEqual("derived", coverage["status"])
        deploy = next(item for item in report["job_templates"] if item["name"] == "Deploy Payments")
        operators = next(item for item in deploy["team_access"] if item["team"] == "Payments Operators")
        self.assertEqual(["bob"], [item["username"] for item in operators["members"]["gateway"]])

    def test_ambiguous_identity_is_not_silently_merged(self):
        report = MODULE.AuditCollector(AmbiguousClient()).report()
        unresolved = [
            item
            for item in report["unresolved_principals"]
            if item["principal_type"] == "user" and item["principal"] == "alice"
        ]
        self.assertGreaterEqual(len(unresolved), 2)
        self.assertTrue(all("ambiguous" in item["reason"] for item in unresolved))

    def test_ansible_id_correlates_a_renamed_user_before_username(self):
        report = MODULE.AuditCollector(RenamedUserClient()).report()
        deploy = next(item for item in report["job_templates"] if item["name"] == "Deploy Payments")
        direct = [item for item in deploy["direct_user_access"] if item["username"] == "alice"]
        self.assertEqual(1, len(direct))
        self.assertEqual(["controller", "gateway"], direct[0]["seen_in"])
        self.assertNotIn(
            "alice-renamed",
            {item["username"] for item in deploy["direct_user_access"]},
        )

    def test_identity_pdf_paginates_large_reports(self):
        report = copy.deepcopy(self.report)
        template = copy.deepcopy(report["job_templates"][0])
        report["job_templates"] = []
        for index in range(28):
            item = copy.deepcopy(template)
            item["name"] = f"Deploy Payments {index + 1:02d}"
            report["job_templates"].append(item)
        rendered = MODULE.render_pdf(report)
        self.assertGreater(rendered.count(b"/Type /Page "), 3)
        self.assertIn(b"continued", rendered)


if __name__ == "__main__":
    unittest.main()
