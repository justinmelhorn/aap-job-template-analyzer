#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "export_recent_team_resources.py"
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
                    "organization": "Payments",
                    "team": "Payments Auditors",
                    "level": "view",
                    "sources": ["direct"],
                },
                {
                    "organization": "Payments",
                    "team": "Payments Developers",
                    "level": "admin",
                    "sources": ["direct", "organization_role"],
                },
            ],
            payments["access"],
        )
        self.assertEqual(
            {
                "organization": "Network",
                "team": "Network Admins",
                "level": "admin",
                "sources": ["organization_role"],
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
        self.assertEqual(
            "job_templates:\n"
            '  - name: "Payments | Health Check"\n'
            '    organization: "Payments"\n'
            '    api_url: "https://aap.example.com/api/controller/v2/job_templates/10/"\n'
            '    last_job_run: "2026-08-01T12:00:00Z"\n'
            '    playbook: "health_check.yml"\n'
            '    project:\n'
            '      name: "Payments Automation"\n'
            '      api_url: "https://aap.example.com/api/controller/v2/projects/11/"\n'
            '    inventory:\n'
            '      name: "Payments Production"\n'
            '      api_url: "https://aap.example.com/api/controller/v2/inventories/12/"\n'
            '    credentials:\n'
            '      - name: "Payments SSH"\n'
            '        type: "ssh"\n'
            '        api_url: "https://aap.example.com/api/controller/v2/credentials/13/"\n'
            '    access:\n'
            '      - organization: "Payments"\n'
            '        team: "Payments Auditors"\n'
            '        level: "view"\n'
            '        sources:\n'
            '          - "direct"\n'
            '      - organization: "Payments"\n'
            '        team: "Payments Developers"\n'
            '        level: "admin"\n'
            '        sources:\n'
            '          - "direct"\n'
            '          - "organization_role"\n',
            rendered,
        )
        self.assertNotIn("must-not-be-exported", rendered)
        self.assertNotIn("inputs", rendered)

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
        self.assertIn("Payments Developers | admin | direct, organization role", rendered)
        self.assertIn("**Attention:** No current team access was found.", rendered)
        self.assertNotIn("must-not-be-exported", rendered)
        self.assertNotIn("inputs", rendered)

    def test_empty_markdown_report(self):
        rendered = MODULE.render_markdown([], 30, "2026-07-13T00:00:00Z")
        self.assertIn("| Recently used Job Templates | 0 |", rendered)
        self.assertIn("No Job Templates matched the selected period.", rendered)


if __name__ == "__main__":
    unittest.main()
