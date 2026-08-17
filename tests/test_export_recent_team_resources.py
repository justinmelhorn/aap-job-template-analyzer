#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "export_recent_team_resources.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("export_recent_team_resources", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeClient:
    base_url = "https://aap.example.com"

    def get(self, path, params=None):
        if path.endswith("/config/"):
            return {"version": "4.6.30"}
        raise AssertionError(path)

    def list(self, path, **params):
        if path.endswith("/job_templates/"):
            self.job_template_params = params
            candidates = [
                {
                    "id": 10,
                    "name": "Payments | Health Check",
                    "url": "/api/controller/v2/job_templates/10/",
                    "last_job_run": "2026-08-01T12:00:00Z",
                    "playbook": "health_check.yml",
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"},
                        "project": {"id": 11, "name": "Payments Automation"},
                        "inventory": {"id": 12, "name": "Payments Production"},
                        "credentials": [
                            {
                                "id": 13,
                                "name": "Payments SSH",
                                "kind": "ssh",
                                "inputs": {"password": "must-not-be-exported"},
                            }
                        ],
                    },
                },
                {
                    "id": 20,
                    "name": "Network | Health Check",
                    "last_job_run": "2026-07-01T12:00:00Z",
                    "summary_fields": {"organization": {"id": 2, "name": "Network"}},
                },
                {
                    "id": 30,
                    "name": "Shared | Unassigned Recent Template",
                    "last_job_run": "2026-06-01T12:00:00Z",
                    "summary_fields": {"organization": {"id": 3, "name": "Shared"}},
                },
                {
                    "id": 40,
                    "name": "Payments | Stale Template",
                    "last_job_run": "2020-01-01T12:00:00Z",
                    "summary_fields": {"organization": {"id": 1, "name": "Payments"}},
                },
                {
                    "id": 50,
                    "name": "Payments | Never Run",
                    "last_job_run": None,
                    "summary_fields": {"organization": {"id": 1, "name": "Payments"}},
                },
            ]
            cutoff = params["last_job_run__gte"]
            return [
                item
                for item in candidates
                if item.get("last_job_run") and item["last_job_run"] >= cutoff
            ]
        if path.endswith("/organizations/"):
            return [
                {"id": 1, "name": "Payments"},
                {"id": 2, "name": "Network"},
                {"id": 3, "name": "Shared"},
            ]
        if path.endswith("/teams/"):
            return [
                {
                    "id": 100,
                    "name": "Payments Developers",
                    "organization": 1,
                    "summary_fields": {"organization": {"id": 1, "name": "Payments"}},
                },
                {
                    "id": 200,
                    "name": "Network Admins",
                    "organization": 2,
                    "summary_fields": {"organization": {"id": 2, "name": "Network"}},
                },
                {
                    "id": 300,
                    "name": "Payments Auditors",
                    "organization": 1,
                    "summary_fields": {"organization": {"id": 1, "name": "Payments"}},
                },
            ]
        if path.endswith("/role_definitions/"):
            return [
                {
                    "id": 1,
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.execute_jobtemplate", "awx.view_jobtemplate"],
                },
                {
                    "id": 2,
                    "content_type": "shared.organization",
                    "permissions": ["awx.change_jobtemplate", "awx.view_jobtemplate"],
                },
                {
                    "id": 3,
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.view_jobtemplate"],
                },
            ]
        if path.endswith("/role_team_assignments/"):
            return [
                {
                    "team": 100,
                    "role_definition": 1,
                    "content_type": "awx.jobtemplate",
                    "object_id": "10",
                },
                {
                    "team": 200,
                    "role_definition": 2,
                    "content_type": "shared.organization",
                    "object_id": "2",
                },
                {
                    "team": 100,
                    "role_definition": 2,
                    "content_type": "shared.organization",
                    "object_id": "1",
                },
                {
                    "team": 300,
                    "role_definition": 3,
                    "content_type": "awx.jobtemplate",
                    "object_id": "10",
                },
            ]
        raise AssertionError(path)


class PromptFakeClient(FakeClient):
    def get(self, path, params=None):
        if path.endswith("/config/"):
            return {"version": "4.6.30"}
        if path.endswith("/job_templates/60/launch/"):
            return {
                "inventory_needed_to_start": True,
                "credential_needed_to_start": True,
                "can_start_without_user_input": False,
                "defaults": {"inventory": {}, "credentials": []},
            }
        if path.endswith("/organizations/") and params:
            organization_id = 1 if params.get("name") == "Payments" else 2
            return {"count": 1, "results": [{"id": organization_id}]}
        if path.endswith(("/inventories/", "/credentials/")) and params:
            return {"count": 1, "results": [{"id": 900}]}
        raise AssertionError((path, params))

    def list(self, path, **params):
        if path.endswith("/job_templates/"):
            self.job_template_params = params
            return [
                {
                    "id": 60,
                    "name": "Payments | Prompted Deployment",
                    "last_job_run": "2026-08-01T12:00:00Z",
                    "ask_inventory_on_launch": True,
                    "ask_credential_on_launch": True,
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"}
                    },
                }
            ]
        if path.endswith("/organizations/"):
            return [{"id": 1, "name": "Payments"}, {"id": 2, "name": "Shared"}]
        if path.endswith("/teams/"):
            return [
                {
                    "id": 500,
                    "name": "Payments Launchers",
                    "organization": 1,
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"}
                    },
                },
                {
                    "id": 600,
                    "name": "Shared Operators",
                    "organization": 2,
                    "summary_fields": {
                        "organization": {"id": 2, "name": "Shared"}
                    },
                },
                {
                    "id": 700,
                    "name": "Payments Editors",
                    "organization": 1,
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"}
                    },
                },
            ]
        if path.endswith("/role_definitions/"):
            return [
                {
                    "id": 10,
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.execute_jobtemplate", "awx.view_jobtemplate"],
                },
                {
                    "id": 11,
                    "content_type": "awx.inventory",
                    "permissions": ["awx.use_inventory", "awx.view_inventory"],
                },
                {
                    "id": 12,
                    "content_type": "shared.organization",
                    "permissions": [
                        "awx.execute_jobtemplate",
                        "awx.view_jobtemplate",
                        "awx.use_inventory",
                        "awx.use_credential",
                    ],
                },
                {
                    "id": 13,
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.change_jobtemplate", "awx.view_jobtemplate"],
                },
            ]
        if path.endswith("/role_team_assignments/"):
            return [
                {
                    "team": 500,
                    "role_definition": 10,
                    "content_type": "awx.jobtemplate",
                    "object_id": "60",
                },
                {
                    "team": 500,
                    "role_definition": 11,
                    "content_type": "awx.inventory",
                    "object_id": "901",
                },
                {
                    "team": 600,
                    "role_definition": 12,
                    "content_type": "shared.organization",
                    "object_id": "1",
                },
                {
                    "team": 700,
                    "role_definition": 13,
                    "content_type": "awx.jobtemplate",
                    "object_id": "60",
                },
            ]
        raise AssertionError(path)


class ExportTests(unittest.TestCase):
    def test_access_is_inverted_merged_and_ranked(self):
        client = FakeClient()
        report, _ = MODULE.build_report(client, 365)
        by_name = {item["name"]: item for item in report}
        payments = by_name["Payments | Health Check"]
        self.assertEqual(
            "Payments Automation",
            payments["project"]["name"],
        )
        self.assertEqual(
            [
                {
                    "team_organization": "Payments",
                    "team": "Payments Auditors",
                    "level": "view",
                    "sources": ["job_template_assignment"],
                    "can_execute": False,
                    "launch_readiness": {
                        "status": "not_applicable",
                        "inventory": "not_applicable",
                        "credentials": "not_applicable",
                    },
                },
                {
                    "team_organization": "Payments",
                    "team": "Payments Developers",
                    "level": "admin",
                    "sources": [
                        "job_template_assignment",
                        "owning_organization_assignment",
                    ],
                    "can_execute": True,
                    "launch_readiness": {
                        "status": "ready",
                        "inventory": "fixed",
                        "credentials": "fixed",
                    },
                },
            ],
            payments["access"],
        )
        self.assertEqual(
            {
                "team_organization": "Network",
                "team": "Network Admins",
                "level": "admin",
                "sources": ["owning_organization_assignment"],
                "can_execute": False,
                "launch_readiness": {
                    "status": "not_applicable",
                    "inventory": "not_applicable",
                    "credentials": "not_applicable",
                },
            },
            by_name["Network | Health Check"]["access"][0],
        )
        self.assertIn("last_job_run__gte", client.job_template_params)

    def test_recent_unassigned_is_included_and_stale_or_never_run_are_excluded(self):
        report, _ = MODULE.build_report(FakeClient(), 365)
        by_name = {item["name"]: item for item in report}
        self.assertEqual([], by_name["Shared | Unassigned Recent Template"]["access"])
        self.assertNotIn("Payments | Stale Template", by_name)
        self.assertNotIn("Payments | Never Run", by_name)

    def test_resource_yaml_is_compact_and_never_exports_credential_inputs(self):
        report, _ = MODULE.build_report(FakeClient(), 365)
        payments = next(
            item for item in report if item["name"] == "Payments | Health Check"
        )
        rendered = MODULE.render_yaml([payments])
        self.assertIn('    owning_organization: "Payments"', rendered)
        self.assertIn(
            '    ui_url: "https://aap.example.com/execution/templates/'
            'job-template/10/details"',
            rendered,
        )
        self.assertIn(
            '      ui_url: "https://aap.example.com/execution/projects/11/details"',
            rendered,
        )
        self.assertIn(
            '      ui_url: "https://aap.example.com/execution/inventories/'
            'inventory/12/details"',
            rendered,
        )
        self.assertIn(
            '        ui_url: "https://aap.example.com/execution/credentials/'
            '13/details"',
            rendered,
        )
        self.assertIn("    launch_prompts:\n      inventory:", rendered)
        self.assertIn("        enabled: false\n        required: false", rendered)
        self.assertIn('      - team_organization: "Payments"', rendered)
        self.assertIn("        can_execute: true", rendered)
        self.assertIn('          - "job_template_assignment"', rendered)
        self.assertIn('          status: "ready"', rendered)
        self.assertIn('          inventory: "fixed"', rendered)
        self.assertNotIn("\n    organization:", rendered)
        self.assertNotIn("\n      - organization:", rendered)
        self.assertNotIn("must-not-be-exported", rendered)
        self.assertNotIn("inputs", rendered)

    def test_prompted_launch_readiness_uses_direct_and_org_team_grants(self):
        report, _ = MODULE.build_report(PromptFakeClient(), 365)
        resource = report[0]
        self.assertEqual("Payments", resource["owning_organization"])
        self.assertEqual(
            {
                "enabled": True,
                "required": True,
                "default": None,
            },
            resource["launch_prompts"]["inventory"],
        )
        self.assertEqual([], resource["launch_prompts"]["credentials"]["defaults"])
        by_team = {entry["team"]: entry for entry in resource["access"]}

        direct = by_team["Payments Launchers"]
        self.assertTrue(direct["can_execute"])
        self.assertEqual("team_selection", direct["launch_readiness"]["inventory"])
        self.assertEqual(
            "team_access_not_evidenced",
            direct["launch_readiness"]["credentials"],
        )
        self.assertEqual("attention", direct["launch_readiness"]["status"])

        organization = by_team["Shared Operators"]
        self.assertEqual("Shared", organization["team_organization"])
        self.assertEqual(
            ["owning_organization_assignment"], organization["sources"]
        )
        self.assertEqual("ready", organization["launch_readiness"]["status"])
        self.assertEqual(
            "team_selection", organization["launch_readiness"]["inventory"]
        )
        self.assertEqual(
            "team_selection", organization["launch_readiness"]["credentials"]
        )

        editor = by_team["Payments Editors"]
        self.assertEqual("admin", editor["level"])
        self.assertFalse(editor["can_execute"])
        self.assertEqual("not_applicable", editor["launch_readiness"]["status"])

    def test_prompt_readiness_defaults_and_optional_credentials(self):
        resource = {
            "launch_prompts": {
                "inventory": {
                    "enabled": True,
                    "required": True,
                    "default": {"name": "Default Inventory"},
                },
                "credentials": {
                    "enabled": True,
                    "required": False,
                    "defaults": [],
                },
            }
        }
        readiness = MODULE.prompt_readiness(resource, True, False, False)
        self.assertEqual(
            {
                "status": "ready",
                "inventory": "default_prompt",
                "credentials": "optional",
            },
            readiness,
        )

    def test_empty_report_yaml(self):
        self.assertEqual("job_templates: []\n", MODULE.render_yaml([]))

    def test_markdown_has_summary_links_details_and_access(self):
        report, _ = MODULE.build_report(FakeClient(), 365)
        rendered = MODULE.render_markdown(report, 365, "2025-08-12T00:00:00Z")
        self.assertIn("# AAP Job Template Access Report", rendered)
        self.assertIn("| Recently used Job Templates | 3 |", rendered)
        self.assertIn("| Owning organizations | 3 |", rendered)
        self.assertIn("| Teams with access | 3 |", rendered)
        self.assertIn("| Templates with no team access | 1 |", rendered)
        self.assertIn("| Admin grants | 2 |", rendered)
        self.assertIn(
            "Payments &#124; Health Check "
            "([view in AAP](https://aap.example.com/execution/templates/"
            "job-template/10/details))",
            rendered,
        )
        self.assertIn(
            "Payments Automation "
            "([view in AAP](https://aap.example.com/execution/projects/11/details))",
            rendered,
        )
        self.assertIn(
            "Payments Production "
            "([view in AAP](https://aap.example.com/execution/inventories/"
            "inventory/12/details))",
            rendered,
        )
        self.assertIn(
            "Payments SSH "
            "([view in AAP](https://aap.example.com/execution/credentials/13/details))",
            rendered,
        )
        self.assertIn(
            "Payments Developers | admin | Job Template assignment, "
            "Owning Organization assignment | Ready",
            rendered,
        )
        self.assertIn(
            "#### Teams from Payments — same as template owner", rendered
        )
        self.assertIn("**Attention:** No current team access was found.", rendered)
        self.assertNotIn("must-not-be-exported", rendered)
        self.assertNotIn("inputs", rendered)

    def test_markdown_groups_cross_org_access_and_summarizes_prompts(self):
        report, _ = MODULE.build_report(PromptFakeClient(), 365)
        rendered = MODULE.render_markdown(report, 365, "2025-08-12T00:00:00Z")
        self.assertIn("| Templates with launch prompts | 1 |", rendered)
        self.assertIn("| Required selections without defaults | 2 |", rendered)
        self.assertIn("| Cross-organization team grants | 1 |", rendered)
        self.assertIn("| Team readiness entries needing review | 1 |", rendered)
        self.assertIn(
            "#### Teams from Payments — same as template owner", rendered
        )
        self.assertIn(
            "#### Teams from Shared — cross-organization access", rendered
        )
        self.assertIn(
            "Payments Launchers | execute | Job Template assignment | "
            "Attention — inventory: team selection; credentials: team access not evidenced",
            rendered,
        )
        self.assertIn(
            "Launch readiness is derived only from team assignments", rendered
        )

    def test_empty_markdown_report(self):
        rendered = MODULE.render_markdown([], 30, "2026-07-13T00:00:00Z")
        self.assertIn("| Recently used Job Templates | 0 |", rendered)
        self.assertIn("No Job Templates matched the selected period.", rendered)

    def test_pdf_contains_summary_templates_and_team_access(self):
        report, _ = MODULE.build_report(FakeClient(), 365)
        rendered = MODULE.render_pdf(report, 365, "2025-08-17T00:00:00Z")
        self.assertTrue(rendered.startswith(b"%PDF-1.4"))
        self.assertTrue(rendered.endswith(b"%%EOF\n"))
        self.assertIn(b"AAP Job Template Access Report", rendered)
        self.assertIn(b"Payments | Health Check", rendered)
        self.assertIn(b"Payments Developers", rendered)
        self.assertIn(b"Team access", rendered)

    def test_pdf_paginates_large_reports(self):
        report, _ = MODULE.build_report(FakeClient(), 365)
        seed = report[0]
        expanded = [
            {
                **seed,
                "name": f"Payments | Long Running Deployment Template {index:02d}",
            }
            for index in range(30)
        ]
        rendered = MODULE.render_pdf(expanded, 365, "2025-08-17T00:00:00Z")
        self.assertGreaterEqual(rendered.count(b"/Type /Page "), 5)
        self.assertGreaterEqual(rendered.count(b"(Organization) Tj"), 2)
        self.assertIn(b"- continued", rendered)


if __name__ == "__main__":
    unittest.main()
