from __future__ import annotations

import io
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "export_recent_team_resources", SCRIPTS / "export_recent_team_resources.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeClient:
    base_url = "https://aap.example.com"

    def get(self, path, params=None):
        if path.endswith("/config/"):
            return {"version": "4.6.30"}
        raise AssertionError((path, params))

    def list(self, path, **params):
        data = {
            "/api/controller/v2/job_templates/": [
                {
                    "id": 10,
                    "ansible_id": "deploy-id",
                    "name": "Deploy",
                    "last_job_run": "2026-08-01T12:00:00Z",
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"},
                        "inventory": {"id": 20, "name": "Production"},
                        "credentials": [
                            {
                                "id": 30,
                                "name": "SSH Key",
                                "inputs": {"password": "must-not-appear"},
                            }
                        ],
                    },
                },
                {
                    "id": 11,
                    "name": "Old Audit",
                    "last_job_run": "2020-01-01T12:00:00Z",
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"}
                    },
                },
                {
                    "id": 12,
                    "name": "Never Run",
                    "last_job_run": None,
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"}
                    },
                },
            ],
            "/api/controller/v2/workflow_job_templates/": [],
            "/api/controller/v2/organizations/": [{"id": 1, "name": "Payments"}],
            "/api/controller/v2/teams/": [
                {"id": 100, "name": "Operators", "organization": 1}
            ],
            "/api/controller/v2/users/": [
                {"id": 200, "username": "alice"},
                {"id": 201, "username": "platform-admin", "is_superuser": True},
            ],
            "/api/controller/v2/role_definitions/": [
                {
                    "id": 1,
                    "content_type": "awx.jobtemplate",
                    "permissions": ["awx.execute_jobtemplate"],
                },
                {
                    "id": 2,
                    "content_type": "shared.organization",
                    "permissions": ["awx.change_jobtemplate"],
                },
            ],
            "/api/controller/v2/role_team_assignments/": [
                {
                    "team": 100,
                    "role_definition": 1,
                    "object_id": 10,
                    "content_type": "awx.jobtemplate",
                }
            ],
            "/api/controller/v2/role_user_assignments/": [
                {
                    "user": 200,
                    "role_definition": 2,
                    "object_id": 1,
                    "content_type": "shared.organization",
                }
            ],
        }
        if path not in data:
            raise AssertionError((path, params))
        return data[path]


class GatewayUserClient(FakeClient):
    def __init__(self):
        self.paths = []

    def get(self, path, params=None):
        if path.endswith("/config/"):
            return {"version": "4.7.0"}
        return super().get(path, params)

    def list(self, path, **params):
        self.paths.append(path)
        gateway = {
            "/api/gateway/v1/organizations/": [{"id": "g-org", "name": "Payments"}],
            "/api/gateway/v1/teams/": [],
            "/api/gateway/v1/users/": [
                {
                    "id": "g-alice",
                    "ansible_id": "user-alice",
                    "username": "alice",
                }
            ],
            "/api/controller/v2/users/": [
                {
                    "id": 200,
                    "ansible_id": "user-alice",
                    "username": "alice-old-name",
                },
                {"id": 300, "username": "legacy-admin", "is_superuser": True},
            ],
            "/api/gateway/v1/role_definitions/": [
                {"id": "execute", "permissions": ["awx.execute_jobtemplate"]}
            ],
            "/api/gateway/v1/role_team_assignments/": [],
            "/api/gateway/v1/role_user_assignments/": [
                {
                    "user": "g-alice",
                    "role_definition": "execute",
                    "object_id": 10,
                    "content_type": "awx.jobtemplate",
                }
            ],
        }
        if path in gateway:
            return gateway[path]
        return super().list(path, **params)


class WorkflowClient(FakeClient):
    def __init__(self):
        self.paths = []

    def list(self, path, **params):
        self.paths.append(path)
        if path == "/api/controller/v2/job_templates/":
            return super().list(path, **params) + [
                {
                    "id": 13,
                    "name": "Truly Unused",
                    "last_job_run": "2020-01-01T12:00:00Z",
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"}
                    },
                }
            ]
        if path == "/api/controller/v2/workflow_job_templates/":
            return [
                {
                    "id": 40,
                    "name": "Release Workflow",
                    "last_job_run": "2026-08-02T12:00:00Z",
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"},
                        "inventory": {"id": 20, "name": "Production"},
                    },
                },
                {
                    "id": 41,
                    "name": "Nested Workflow",
                    "last_job_run": None,
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"}
                    },
                },
                {
                    "id": 42,
                    "name": "Dormant Workflow",
                    "last_job_run": "2020-01-01T12:00:00Z",
                    "summary_fields": {
                        "organization": {"id": 1, "name": "Payments"}
                    },
                },
            ]
        if path == "/api/controller/v2/workflow_job_template_nodes/":
            return [
                {
                    "id": 50,
                    "identifier": "never-run-branch",
                    "workflow_job_template": 40,
                    "unified_job_template": 12,
                    "success_nodes": [51],
                    "failure_nodes": [],
                    "always_nodes": [],
                    "related": {
                        "unified_job_template": "/api/controller/v2/job_templates/12/"
                    },
                    "summary_fields": {
                        "unified_job_template": {
                            "id": 12,
                            "name": "Never Run",
                        }
                    },
                },
                {
                    "id": 51,
                    "identifier": "nested-workflow",
                    "workflow_job_template": 40,
                    "unified_job_template": 41,
                    "success_nodes": [],
                    "failure_nodes": [54],
                    "always_nodes": [],
                    "related": {
                        "unified_job_template": "/api/controller/v2/workflow_job_templates/41/"
                    },
                    "summary_fields": {
                        "unified_job_template": {
                            "id": 41,
                            "name": "Nested Workflow",
                            "unified_job_type": "workflow_job",
                        }
                    },
                },
                {
                    "id": 52,
                    "identifier": "old-audit",
                    "workflow_job_template": 41,
                    "unified_job_template": 11,
                    "success_nodes": [],
                    "failure_nodes": [],
                    "always_nodes": [],
                    "related": {
                        "unified_job_template": "/api/controller/v2/job_templates/11/"
                    },
                    "summary_fields": {
                        "unified_job_template": {
                            "id": 11,
                            "name": "Old Audit",
                            "unified_job_type": "job",
                        }
                    },
                },
                {
                    "id": 53,
                    "identifier": "dormant-step",
                    "workflow_job_template": 42,
                    "unified_job_template": 13,
                    "success_nodes": [],
                    "failure_nodes": [],
                    "always_nodes": [],
                    "related": {
                        "unified_job_template": "/api/controller/v2/job_templates/13/"
                    },
                    "summary_fields": {
                        "unified_job_template": {
                            "id": 13,
                            "name": "Truly Unused",
                            "unified_job_type": "job",
                        }
                    },
                },
                {
                    "id": 54,
                    "identifier": "approval",
                    "workflow_job_template": 40,
                    "unified_job_template": 60,
                    "success_nodes": [],
                    "failure_nodes": [],
                    "always_nodes": [],
                    "related": {
                        "unified_job_template": "/api/controller/v2/workflow_approval_templates/60/"
                    },
                    "summary_fields": {
                        "unified_job_template": {
                            "id": 60,
                            "name": "Approve Release",
                            "unified_job_type": "workflow_approval",
                        }
                    },
                },
            ]
        if path == "/api/controller/v2/role_definitions/":
            return super().list(path, **params) + [
                {
                    "id": 3,
                    "content_type": "awx.workflowjobtemplate",
                    "permissions": ["awx.execute_workflowjobtemplate"],
                }
            ]
        if path == "/api/controller/v2/role_team_assignments/":
            return super().list(path, **params) + [
                {
                    "team": 100,
                    "role_definition": 3,
                    "object_id": 40,
                    "content_type": "awx.workflowjobtemplate",
                }
            ]
        return super().list(path, **params)


class ExportTests(unittest.TestCase):
    def api_client(self):
        client = MODULE.Client.__new__(MODULE.Client)
        client.base_url = "https://aap.example.com"
        client.authorization = "Bearer test"
        client.context = None
        return client

    def http_error(self, status, headers=None):
        error = MODULE.urllib.error.HTTPError(
            "https://aap.example.com/api/controller/v2/users/",
            status,
            "API error",
            headers or {},
            io.BytesIO(),
        )
        self.addCleanup(error.close)
        return error

    def test_client_uses_small_pages_and_follows_next(self):
        client = self.api_client()
        next_url = (
            "https://aap.example.com/api/controller/v2/users/"
            "?page=2&page_size=50"
        )
        client.get = mock.Mock(
            side_effect=[
                {"results": [{"id": 1}], "next": next_url},
                {"results": [{"id": 2}], "next": None},
            ]
        )

        self.assertEqual([{"id": 1}, {"id": 2}], client.list("/users/"))
        self.assertEqual(
            [mock.call("/users/", {"page_size": 50}), mock.call(next_url)],
            client.get.call_args_list,
        )

    def test_client_retries_temporary_errors_slowly(self):
        client = self.api_client()
        unavailable = self.http_error(503)

        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=[unavailable, unavailable, io.BytesIO(b'{"results": []}')],
        ) as urlopen, mock.patch.object(
            MODULE.time, "sleep"
        ) as sleep, mock.patch.object(
            MODULE.sys, "stderr", new=io.StringIO()
        ):
            response = client.get("/api/controller/v2/users/")

        self.assertEqual({"results": []}, response)
        self.assertEqual(3, urlopen.call_count)
        self.assertEqual(
            [mock.call(1), mock.call(60), mock.call(120)], sleep.call_args_list
        )

    def test_client_honors_a_longer_retry_after(self):
        client = self.api_client()
        unavailable = self.http_error(503, {"Retry-After": "180"})

        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=[unavailable, io.BytesIO(b'{"results": []}')],
        ), mock.patch.object(MODULE.time, "sleep") as sleep, mock.patch.object(
            MODULE.sys, "stderr", new=io.StringIO()
        ):
            client.get("/api/controller/v2/users/")

        self.assertEqual([mock.call(1), mock.call(180)], sleep.call_args_list)

    def test_client_stops_after_two_temporary_retries(self):
        client = self.api_client()
        unavailable = self.http_error(503)

        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=[unavailable, unavailable, unavailable],
        ) as urlopen, mock.patch.object(
            MODULE.time, "sleep"
        ) as sleep, mock.patch.object(
            MODULE.sys, "stderr", new=io.StringIO()
        ):
            with self.assertRaises(MODULE.ExportError):
                client.get("/api/controller/v2/users/")

        self.assertEqual(3, urlopen.call_count)
        self.assertEqual(
            [mock.call(1), mock.call(60), mock.call(120)], sleep.call_args_list
        )

    def test_client_does_not_retry_permanent_http_errors(self):
        client = self.api_client()

        with mock.patch.object(
            MODULE.urllib.request, "urlopen", side_effect=self.http_error(403)
        ) as urlopen, mock.patch.object(
            MODULE.time, "sleep"
        ) as sleep:
            with self.assertRaises(MODULE.ExportError):
                client.get("/api/controller/v2/users/")

        self.assertEqual(1, urlopen.call_count)
        self.assertEqual([mock.call(1)], sleep.call_args_list)

    def test_client_does_not_retry_connection_failures(self):
        client = self.api_client()

        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=MODULE.urllib.error.URLError("connection failed"),
        ) as urlopen, mock.patch.object(MODULE.time, "sleep") as sleep:
            with self.assertRaises(MODULE.ExportError):
                client.get("/api/controller/v2/users/")

        self.assertEqual(1, urlopen.call_count)
        self.assertEqual([mock.call(1)], sleep.call_args_list)

    def test_recent_report_has_resources_teams_users_and_summary(self):
        report, _ = MODULE.build_report(FakeClient(), 365, "recent")
        self.assertEqual(["Deploy"], [item["name"] for item in report])
        job = report[0]
        self.assertEqual(
            "https://aap.example.com/api/controller/v2/job_templates/10/",
            job["url"],
        )
        self.assertEqual("Production", job["inventory"]["name"])
        self.assertEqual(
            "https://aap.example.com/api/controller/v2/inventories/20/",
            job["inventory"]["url"],
        )
        self.assertEqual(["SSH Key"], [item["name"] for item in job["credentials"]])
        self.assertEqual(
            "https://aap.example.com/api/controller/v2/credentials/30/",
            job["credentials"][0]["url"],
        )
        self.assertEqual(
            [
                {
                    "type": "team",
                    "name": "Operators",
                    "organization": "Payments",
                    "level": "execute",
                },
                {"type": "user", "name": "alice", "level": "admin"},
                {"type": "user", "name": "platform-admin", "level": "admin"},
            ],
            job["permissions"],
        )

        output = MODULE.render_yaml(report)
        self.assertTrue(output.startswith("summary:\n  - name: \"Deploy\"\n    url:"))
        self.assertIn('url: "https://aap.example.com/api/controller/v2/job_templates/10/"', output)
        self.assertNotIn("\n    url: \"https://aap.example.com/execution/", output)
        self.assertIn("\njob_templates:\n", output)
        self.assertNotIn("must-not-appear", output)
        self.assertNotIn("inputs", output)

        pdf = MODULE.render_pdf(
            report, 365, "2025-08-19T00:00:00Z", "recent", rbac_checked=True
        )
        self.assertIn(b"/execution/templates/job-template/10/details", pdf)
        self.assertEqual(1, pdf.count(b"/Subtype /Link"))
        self.assertEqual(1, pdf.count(b"/Dest ["))

    def test_recent_workflow_marks_all_nested_children_used(self):
        client = WorkflowClient()
        report, _ = MODULE.build_report(client, 365, "recent")
        jobs = {
            item["name"]: item
            for item in report
            if item["kind"] == "job_template"
        }
        workflows = {
            item["name"]: item
            for item in report
            if item["kind"] == "workflow_job_template"
        }

        self.assertEqual({"Deploy", "Never Run", "Old Audit"}, set(jobs))
        self.assertIsNone(jobs["Never Run"]["last_run"])
        self.assertEqual(
            {"Nested Workflow", "Release Workflow"}, set(workflows)
        )
        self.assertIsNone(workflows["Nested Workflow"]["last_run"])
        release_steps = {
            item["identifier"]: item for item in workflows["Release Workflow"]["steps"]
        }
        self.assertEqual("Never Run", release_steps["never-run-branch"]["name"])
        self.assertEqual(
            ["nested-workflow"], release_steps["never-run-branch"]["success"]
        )
        self.assertEqual("workflow_approval", release_steps["approval"]["type"])
        self.assertIn(
            {
                "type": "team",
                "name": "Operators",
                "organization": "Payments",
                "level": "execute",
            },
            workflows["Release Workflow"]["permissions"],
        )
        self.assertEqual(
            1,
            client.paths.count(
                "/api/controller/v2/workflow_job_template_nodes/"
            ),
        )
        self.assertFalse(
            any("/workflow_nodes/" in path for path in client.paths),
            client.paths,
        )

        output = MODULE.render_yaml(report)
        self.assertIn("\nworkflow_job_templates:\n", output)
        self.assertIn('identifier: "never-run-branch"', output)
        self.assertIn('name: "Approve Release"', output)
        pdf = MODULE.render_pdf(
            report, 365, "2025-08-19T00:00:00Z", "recent", rbac_checked=True
        )
        self.assertIn(b"Workflow Templates", pdf)
        self.assertIn(b"Never Run", pdf)
        self.assertEqual(len(report), pdf.count(b"/Subtype /Link"))
        self.assertEqual(len(report), pdf.count(b"/Dest ["))

    def test_unused_excludes_children_of_used_workflows(self):
        report, _ = MODULE.build_report(
            WorkflowClient(), 365, "unused", check_rbac=False
        )
        jobs = {
            item["name"] for item in report if item["kind"] == "job_template"
        }
        workflows = {
            item["name"]
            for item in report
            if item["kind"] == "workflow_job_template"
        }
        self.assertEqual({"Truly Unused"}, jobs)
        self.assertEqual({"Dormant Workflow"}, workflows)

    def test_unused_includes_old_and_never_run_jobs(self):
        report, _ = MODULE.build_report(FakeClient(), 365, "unused")
        self.assertEqual(["Never Run", "Old Audit"], [item["name"] for item in report])
        self.assertIsNone(report[0]["last_run"])

    def test_no_rbac_skips_permission_calls_and_marks_output(self):
        client = FakeClient()
        report, _ = MODULE.build_report(client, 365, "unused", check_rbac=False)
        self.assertFalse(report[0]["permissions_checked"])
        self.assertNotIn("permissions", report[0])

        output = MODULE.render_yaml(report)
        self.assertIn("    permissions_checked: false", output)
        self.assertNotIn("\n    permissions:", output)

        pdf = MODULE.render_pdf(
            report, 365, "2025-08-19T00:00:00Z", "unused", rbac_checked=False
        )
        self.assertIn(b"Overview", pdf)
        self.assertIn(b"Permissions: not checked", pdf)

    def test_all_has_no_date_filter(self):
        report, _ = MODULE.build_report(FakeClient(), 365, "all")
        self.assertEqual(3, len(report))

    def test_overview_resource_counts_are_unique(self):
        report, _ = MODULE.build_report(FakeClient(), 365, "recent")
        duplicate = dict(report[0])
        duplicate["name"] = "Another template using the same resources"
        self.assertEqual((1, 1), MODULE.unique_resource_counts([report[0], duplicate]))

    def test_gateway_users_are_cross_referenced_with_controller_users(self):
        client = GatewayUserClient()
        report, _ = MODULE.build_report(client, 365, "recent")
        permissions = report[0]["permissions"]
        self.assertEqual(1, client.paths.count("/api/gateway/v1/teams/"))
        self.assertIn("/api/controller/v2/users/", client.paths)
        self.assertEqual(
            [
                {"type": "user", "name": "alice", "level": "execute"},
                {"type": "user", "name": "legacy-admin", "level": "admin"},
            ],
            permissions,
        )

    def test_empty_yaml_and_pdf(self):
        self.assertEqual(
            "summary: []\njob_templates: []\nworkflow_job_templates: []\n",
            MODULE.render_yaml([]),
        )
        pdf = MODULE.render_pdf(
            [], 365, "2025-08-19T00:00:00Z", "unused", rbac_checked=True
        )
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"Overview", pdf)
        self.assertIn(b"Summary", pdf)


if __name__ == "__main__":
    unittest.main()
