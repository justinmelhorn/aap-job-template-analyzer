#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "export_team_job_template_roles.py"
SPEC = importlib.util.spec_from_file_location("export_team_job_template_roles", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeClient:
    base_url = "https://aap.example.com"

    def __init__(self):
        self.role_paths = []

    def list(self, path, **params):
        if path == "/api/controller/v2/organizations/":
            return [
                {"id": 1, "name": "Payments"},
                {"id": 2, "name": "Network"},
            ]
        if path == "/api/controller/v2/teams/":
            return [
                {
                    "id": 5,
                    "name": "Payments Operators",
                    "organization": 1,
                    "related": {"roles": "/api/controller/v2/teams/5/roles/"},
                },
                {
                    "id": 7,
                    "name": "Network Admins",
                    "summary_fields": {
                        "organization": {"id": 2, "name": "Network"}
                    },
                },
            ]
        if path == "/api/gateway/v1/organizations/":
            return [
                {"id": "org-payments", "name": "Payments"},
                {"id": "org-network", "name": "Network"},
            ]
        if path == "/api/gateway/v1/teams/":
            return [
                {
                    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "name": "Payments Operators",
                    "organization": "org-payments",
                },
                {
                    "id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                    "name": "Network Admins",
                    "organization": "org-network",
                },
            ]
        if path == "/api/controller/v2/teams/5/roles/":
            self.role_paths.append(path)
            return [
                {
                    "id": 101,
                    "name": "Execute",
                    "object_id": 42,
                    "summary_fields": {
                        "resource_type": "job_template",
                        "resource_name": "Deploy Payments",
                        "resource": {
                            "id": 42,
                            "type": "job_template",
                            "url": "/api/controller/v2/job_templates/42/",
                        }
                    },
                },
                {
                    "id": 102,
                    "name": "Use",
                    "content_type": "inventory",
                    "object_id": 9,
                },
            ]
        if path == "/api/controller/v2/teams/7/roles/":
            self.role_paths.append(path)
            return [
                {
                    "id": 103,
                    "role_field": "admin_role",
                    "content_type": "awx.jobtemplate",
                    "object_id": 99,
                }
            ]
        raise AssertionError(path)

    def get(self, path, params=None):
        if path == "/api/controller/v2/job_templates/99/":
            return {
                "id": 99,
                "name": "Configure Network",
                "url": "/api/controller/v2/job_templates/99/",
            }
        raise AssertionError((path, params))


class GatewayUnavailableClient(FakeClient):
    def list(self, path, **params):
        if path == "/api/gateway/v1/organizations/":
            raise MODULE.ExportError("GET gateway returned HTTP 403")
        return super().list(path, **params)


class TeamRoleReportTests(unittest.TestCase):
    def test_uses_controller_team_ids_filters_roles_and_maps_gateway_uuids(self):
        client = FakeClient()
        report = MODULE.build_report(client)

        self.assertEqual(2, report["teams_scanned"])
        self.assertEqual(2, report["teams_with_job_template_roles"])
        self.assertEqual(
            [
                "/api/controller/v2/teams/5/roles/",
                "/api/controller/v2/teams/7/roles/",
            ],
            client.role_paths,
        )
        self.assertEqual(2, len(report["assignments"]))
        by_team = {row["team"]: row for row in report["assignments"]}
        self.assertEqual("Execute", by_team["Payments Operators"]["role"])
        self.assertEqual(
            "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            by_team["Payments Operators"]["gateway_team_id"],
        )
        self.assertEqual("Admin", by_team["Network Admins"]["role"])
        self.assertEqual("Configure Network", by_team["Network Admins"]["job_template"])
        self.assertFalse(any(row["role"] == "Use" for row in report["assignments"]))

    def test_markdown_is_a_clean_team_role_template_report(self):
        rendered = MODULE.render_markdown(MODULE.build_report(FakeClient()))
        self.assertIn("# AAP Team → Job Template Role Report", rendered)
        self.assertIn("| Controller teams scanned | 2 |", rendered)
        self.assertIn(
            "| Payments | Payments Operators | Execute | Deploy Payments ", rendered
        )
        self.assertIn("## Team ID mapping", rendered)
        self.assertIn("3fa85f64-5717-4562-b3fc-2c963f66afa6", rendered)
        self.assertNotIn("| Use |", rendered)

    def test_pdf_uses_only_builtin_writer_and_contains_report_content(self):
        rendered = MODULE.render_pdf(MODULE.build_report(FakeClient()))
        self.assertTrue(rendered.startswith(b"%PDF-1.4"))
        self.assertTrue(rendered.endswith(b"%%EOF\n"))
        self.assertIn(b"AAP Team Job Template Role Report", rendered)
        self.assertIn(b"Payments Operators", rendered)
        self.assertIn(b"Deploy Payments", rendered)
        self.assertIn(b"3fa85f64-5717-4562-b3fc-2c963f66afa6", rendered)
        self.assertIn(b"xref", rendered)

    def test_pdf_paginates_and_repeats_table_headers(self):
        report = MODULE.build_report(FakeClient())
        assignment = report["assignments"][0]
        mapping = report["team_mappings"][0]
        report["assignments"] = [
            {
                **assignment,
                "team": f"Payments Automation Operators Group {index:02d}",
                "job_template": (
                    "Deploy Payments Application and Validate Production "
                    f"Readiness {index:02d}"
                ),
            }
            for index in range(45)
        ]
        report["team_mappings"] = [
            {
                **mapping,
                "team": f"Payments Automation Operators Group {index:02d}",
                "controller_team_id": index + 1,
            }
            for index in range(45)
        ]
        rendered = MODULE.render_pdf(report)
        self.assertGreaterEqual(rendered.count(b"/Type /Page "), 5)
        self.assertGreaterEqual(rendered.count(b"(Organization) Tj"), 5)
        self.assertIn(b"- continued", rendered)

    def test_gateway_mapping_failure_does_not_hide_controller_permissions(self):
        report = MODULE.build_report(GatewayUnavailableClient())
        self.assertEqual(2, len(report["assignments"]))
        self.assertIsNotNone(report["gateway_error"])
        self.assertTrue(
            all(
                mapping["mapping_status"] == "gateway_unavailable"
                for mapping in report["team_mappings"]
            )
        )
        rendered = MODULE.render_markdown(report)
        self.assertIn("Controller role report is still complete", rendered)


if __name__ == "__main__":
    unittest.main()
