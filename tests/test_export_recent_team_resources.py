from __future__ import annotations

import io
import importlib.util
import sys
import tempfile
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
                {
                    "id": 200,
                    "username": "alice",
                    "summary_fields": {"resource": {"ansible_id": "user-alice"}},
                },
                {
                    "id": 201,
                    "username": "platform-admin",
                    "is_superuser": True,
                    "summary_fields": {"resource": {"ansible_id": "user-admin"}},
                },
                {
                    "id": 202,
                    "username": "ldap-admin",
                    "is_superuser": True,
                    "ldap_dn": "uid=ldap-admin,ou=people,dc=example,dc=com",
                    "summary_fields": {"resource": {"ansible_id": "user-ldap"}},
                },
            ],
            "/api/gateway/v1/users/": [
                {
                    "id": 900,
                    "username": "alice",
                    "summary_fields": {"resource": {"ansible_id": "user-alice"}},
                },
                {
                    "id": 901,
                    "username": "platform-admin",
                    "is_superuser": True,
                    "summary_fields": {"resource": {"ansible_id": "user-admin"}},
                },
                {
                    "id": 902,
                    "username": "ldap-admin",
                    "is_superuser": True,
                    "summary_fields": {"resource": {"ansible_id": "user-ldap"}},
                },
            ],
            "/api/gateway/v1/authenticators/": [
                {
                    "id": 1,
                    "slug": "local-provider",
                    "type": "ansible_base.authentication.authenticator_plugins.local",
                },
                {
                    "id": 5,
                    "slug": "2b003d7d-1012-49d1-8f4f-2f7f04bb35b2",
                    "type": "ansible_base.authentication.authenticator_plugins.ldap",
                },
            ],
            "/api/gateway/v1/authenticator_users/": [
                {
                    "user": 900,
                    "provider": "local-provider",
                    "related": {
                        "provider": "/api/gateway/v1/authenticators/1/",
                        "user": "/api/gateway/v1/users/900/",
                    },
                    "summary_fields": {"provider": {"id": 1}, "user": {"id": 900}},
                },
                {
                    "user": 901,
                    "provider": "local-provider",
                    "related": {
                        "provider": "/api/gateway/v1/authenticators/1/",
                        "user": "/api/gateway/v1/users/901/",
                    },
                    "summary_fields": {"provider": {"id": 1}, "user": {"id": 901}},
                },
                {
                    "id": 995,
                    "user": 902,
                    "provider": "2b003d7d-1012-49d1-8f4f-2f7f04bb35b2",
                    "related": {
                        "provider": "/api/gateway/v1/authenticators/5/",
                        "user": "/api/gateway/v1/users/902/",
                    },
                    "summary_fields": {
                        "provider": {"id": 5, "name": "LDAP QA"},
                        "user": {"id": 902, "username": "ldap-admin"},
                    },
                },
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
                    "id": 10,
                    "username": "alice",
                    "summary_fields": {"resource": {"ansible_id": "user-alice"}},
                },
                {
                    "id": 11,
                    "username": "ldap-admin",
                    "is_superuser": True,
                    "summary_fields": {"resource": {"ansible_id": "user-ldap"}},
                },
                {
                    "id": 12,
                    "username": "mixed-admin",
                    "is_superuser": True,
                },
            ],
            "/api/controller/v2/users/": [
                {
                    "id": 200,
                    "username": "alice-old-name",
                    "summary_fields": {"resource": {"ansible_id": "user-alice"}},
                },
                {
                    "id": 300,
                    "username": "legacy-admin",
                    "is_superuser": True,
                },
                {
                    "id": 301,
                    "username": "ldap-admin",
                    "is_superuser": True,
                    "summary_fields": {"resource": {"ansible_id": "user-ldap"}},
                },
            ],
            "/api/gateway/v1/authenticators/": [
                {
                    "id": 1,
                    "slug": "local-provider",
                    "type": "ansible_base.authentication.authenticator_plugins.local",
                },
                {
                    "id": 5,
                    "slug": "ldap-provider",
                    "type": "ansible_base.authentication.authenticator_plugins.ldap",
                },
            ],
            "/api/gateway/v1/authenticator_users/": [
                {
                    "user": 10,
                    "provider": "local-provider",
                    "related": {"provider": "/api/gateway/v1/authenticators/1/"},
                    "summary_fields": {"provider": {"id": 1}, "user": {"id": 10}},
                },
                {
                    "user": 11,
                    "provider": "ldap-provider",
                    "related": {"provider": "/api/gateway/v1/authenticators/5/"},
                    "summary_fields": {"provider": {"id": 5}, "user": {"id": 11}},
                },
                {
                    "user": 12,
                    "provider": "local-provider",
                    "summary_fields": {"provider": {"id": 1}, "user": {"id": 12}},
                },
                {
                    "user": 12,
                    "provider": "ldap-provider",
                    "summary_fields": {"provider": {"id": 5}, "user": {"id": 12}},
                },
            ],
            "/api/gateway/v1/role_definitions/": [
                {"id": "execute", "permissions": ["awx.execute_jobtemplate"]}
            ],
            "/api/gateway/v1/role_team_assignments/": [],
            "/api/gateway/v1/role_user_assignments/": [
                {
                    "user": 10,
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
            "?page=2&page_size=100"
        )
        client.get = mock.Mock(
            side_effect=[
                {"count": 2, "results": [{"id": 1}], "next": next_url},
                {"results": [{"id": 2}], "next": None},
            ]
        )

        stderr = io.StringIO()
        with mock.patch.object(MODULE.sys, "stderr", new=stderr):
            self.assertEqual([{"id": 1}, {"id": 2}], client.list("/users/"))
        self.assertEqual(
            [mock.call("/users/", {"page_size": 100}), mock.call(next_url)],
            client.get.call_args_list,
        )
        self.assertEqual("Users: 1/2\nUsers: 2/2\n", stderr.getvalue())

    def test_client_reports_authentication_failure_separately(self):
        client = self.api_client()

        with mock.patch.object(
            MODULE.urllib.request, "urlopen", side_effect=self.http_error(401)
        ) as urlopen, mock.patch.object(MODULE.time, "sleep") as sleep:
            with self.assertRaises(MODULE.AuthenticationError):
                client.get("/api/gateway/v1/me/")

        self.assertEqual(1, urlopen.call_count)
        self.assertEqual([mock.call(0.25)], sleep.call_args_list)

    def test_local_gateway_users_excludes_any_external_association(self):
        users = [
            {"id": "direct", "username": "direct"},
            {"id": "local", "username": "local"},
            {"id": "ldap", "username": "ldap"},
            {"id": "mixed", "username": "mixed"},
            {"id": "legacy", "username": "legacy"},
            {"id": "legacy-external", "username": "legacy-external"},
        ]
        authenticators = [
            {
                "id": 1,
                "type": "ansible_base.authentication.authenticator_plugins.local",
            },
            {
                "id": 2,
                "type": "ansible_base.authentication.authenticator_plugins.ldap",
            },
            {
                "id": 3,
                "type": "ansible_base.authentication.authenticator_plugins.legacy_password",
            },
            {
                "id": 4,
                "type": "ansible_base.authentication.authenticator_plugins.legacy_external_password",
            },
        ]

        associations = [
            {
                "user": "local",
                "provider": "local-provider",
                "summary_fields": {"provider": {"id": 1}},
            },
            {
                "user": "/api/gateway/v1/users/ldap/",
                "provider": "ldap-provider",
                "summary_fields": {"provider": {"id": 2}},
            },
            {"user": "mixed", "summary_fields": {"provider": {"id": 1}}},
            {"user": "mixed", "summary_fields": {"provider": {"id": 2}}},
            {"user": "legacy", "summary_fields": {"provider": {"id": 3}}},
            {
                "user": "legacy-external",
                "summary_fields": {"provider": {"id": 4}},
            },
        ]

        local, external, unknown = MODULE.local_gateway_users(
            users, authenticators, associations
        )

        self.assertEqual(["local", "legacy"], [user["username"] for user in local])
        self.assertEqual(
            ["ldap", "mixed", "legacy-external"],
            [user["username"] for user in external],
        )
        self.assertEqual(["direct"], [user["username"] for user in unknown])

    def test_local_gateway_users_rejects_unmatched_associations(self):
        with self.assertRaises(MODULE.ExportError):
            MODULE.local_gateway_users(
                [{"id": "local", "username": "local"}],
                [{"id": 1, "type": "ansible_base.authentication.authenticator_plugins.local"}],
                [{"user": "missing", "provider": 1}],
            )

    def test_local_gateway_users_accepts_provider_slug_without_summary_fields(self):
        local, external, unknown = MODULE.local_gateway_users(
            [{"id": 10, "username": "local"}],
            [
                {
                    "id": 1,
                    "slug": "local-provider",
                    "type": "ansible_base.authentication.authenticator_plugins.local",
                }
            ],
            [{"user": 10, "provider": "local-provider"}],
        )
        self.assertEqual(["local"], [user["username"] for user in local])
        self.assertEqual([], external)
        self.assertEqual([], unknown)

    def test_check_auth_mode_calls_gateway_me(self):
        client = mock.Mock()
        with mock.patch.object(MODULE, "Client", return_value=client), mock.patch.object(
            MODULE.sys, "argv", ["report", "--check-auth"]
        ), mock.patch.object(MODULE.sys, "stderr", new=io.StringIO()):
            self.assertEqual(0, MODULE.main())

        client.get.assert_called_once_with("/api/gateway/v1/me/")

    def test_check_auth_mode_returns_distinct_status_for_401(self):
        client = mock.Mock()
        client.get.side_effect = MODULE.AuthenticationError("HTTP 401")
        with mock.patch.object(MODULE, "Client", return_value=client), mock.patch.object(
            MODULE.sys, "argv", ["report", "--check-auth"]
        ), mock.patch.object(MODULE.sys, "stderr", new=io.StringIO()):
            self.assertEqual(MODULE.AUTH_FAILURE_EXIT, MODULE.main())

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
            [mock.call(0.25), mock.call(60), mock.call(120)], sleep.call_args_list
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

        self.assertEqual([mock.call(0.25), mock.call(180)], sleep.call_args_list)

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
            [mock.call(0.25), mock.call(60), mock.call(120)], sleep.call_args_list
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
        self.assertEqual([mock.call(0.25)], sleep.call_args_list)

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
        self.assertEqual([mock.call(0.25)], sleep.call_args_list)

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
        self.assertNotIn("ldap-admin", output)

        pdf = MODULE.render_pdf(
            report, 365, "2025-08-19T00:00:00Z", "recent", rbac_checked=True
        )
        self.assertIn(b"/execution/templates/job-template/10/details", pdf)
        self.assertEqual(1, pdf.count(b"/Subtype /Link"))
        self.assertEqual(1, pdf.count(b"/Dest ["))
        self.assertNotIn(b"ldap-admin", pdf)

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

    def test_combined_reports_collect_every_endpoint_once(self):
        client = WorkflowClient()

        reports, _ = MODULE.build_reports(
            client, 365, {"recent": True, "unused": True}
        )

        for path in (
            "/api/controller/v2/job_templates/",
            "/api/controller/v2/workflow_job_templates/",
            "/api/controller/v2/workflow_job_template_nodes/",
            "/api/controller/v2/organizations/",
            "/api/controller/v2/teams/",
            "/api/controller/v2/users/",
            "/api/controller/v2/role_definitions/",
            "/api/controller/v2/role_team_assignments/",
            "/api/controller/v2/role_user_assignments/",
            "/api/gateway/v1/users/",
            "/api/gateway/v1/authenticators/",
            "/api/gateway/v1/authenticator_users/",
        ):
            self.assertEqual(1, client.paths.count(path), path)
        self.assertEqual(
            {"Deploy", "Never Run", "Old Audit", "Nested Workflow", "Release Workflow"},
            {item["name"] for item in reports["recent"]},
        )
        self.assertEqual(
            {"Truly Unused", "Dormant Workflow"},
            {item["name"] for item in reports["unused"]},
        )
        self.assertTrue(
            all(item["permissions_checked"] for report in reports.values() for item in report)
        )

    def test_combined_cli_writes_used_and_unused_yaml_and_pdf(self):
        client = WorkflowClient()
        with tempfile.TemporaryDirectory() as output_root, mock.patch.object(
            MODULE, "Client", return_value=client
        ), mock.patch.object(
            MODULE.sys,
            "argv",
            ["report", "--both-output-root", output_root],
        ), mock.patch.object(MODULE.sys, "stderr", new=io.StringIO()):
            self.assertEqual(0, MODULE.main())

            used_yaml = Path(output_root) / "used" / "used-job-templates.yaml"
            unused_yaml = Path(output_root) / "unused" / "unused-job-templates.yaml"
            self.assertIn('name: "Deploy"', used_yaml.read_text())
            unused_text = unused_yaml.read_text()
            self.assertIn('name: "Truly Unused"', unused_text)
            self.assertIn("permissions_checked: false", unused_text)
            self.assertTrue(
                (Path(output_root) / "used" / "used-job-templates.pdf")
                .read_bytes()
                .startswith(b"%PDF-1.4")
            )
            self.assertTrue(
                (Path(output_root) / "unused" / "unused-job-templates.pdf")
                .read_bytes()
                .startswith(b"%PDF-1.4")
            )

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
        self.assertEqual(1, client.paths.count("/api/gateway/v1/authenticators/"))
        self.assertEqual(
            1, client.paths.count("/api/gateway/v1/authenticator_users/")
        )
        self.assertIn("/api/controller/v2/users/", client.paths)
        self.assertEqual(
            [{"type": "user", "name": "alice", "level": "execute"}],
            permissions,
        )
        self.assertNotIn("legacy-admin", [item["name"] for item in permissions])
        self.assertNotIn("ldap-admin", [item["name"] for item in permissions])
        pdf = MODULE.render_pdf(
            report, 365, "2025-08-19T00:00:00Z", "recent", rbac_checked=True
        )
        self.assertNotIn(b"mixed-admin", pdf)
        self.assertNotIn(b"ldap-admin", pdf)

    def test_unknown_gateway_users_are_excluded_with_a_warning(self):
        class UnknownUserClient(GatewayUserClient):
            def list(self, path, **params):
                users = super().list(path, **params)
                if path == "/api/gateway/v1/users/":
                    return users + [{"id": 99, "username": "never-logged-in"}]
                return users

        with mock.patch.object(MODULE.sys, "stderr", new=io.StringIO()) as stderr:
            report, _ = MODULE.build_report(UnknownUserClient(), 365, "recent")

        self.assertNotIn("never-logged-in", str(report))
        self.assertIn("excluded 1 Gateway user", stderr.getvalue())

    def test_role_assignment_uses_user_ansible_id_when_user_is_missing(self):
        class AnsibleIdAssignmentClient(GatewayUserClient):
            def list(self, path, **params):
                if path == "/api/gateway/v1/role_user_assignments/":
                    return [
                        {
                            "user": None,
                            "user_ansible_id": "user-alice",
                            "role_definition": "execute",
                            "object_id": 10,
                            "content_type": "awx.jobtemplate",
                        }
                    ]
                return super().list(path, **params)

        report, _ = MODULE.build_report(AnsibleIdAssignmentClient(), 365, "recent")
        self.assertEqual(
            [{"type": "user", "name": "alice", "level": "execute"}],
            report[0]["permissions"],
        )

    def test_no_users_skips_user_collections_and_permissions(self):
        client = GatewayUserClient()

        report, _ = MODULE.build_report(
            client, 365, "recent", check_users=False
        )

        self.assertEqual([], report[0]["permissions"])
        for path in (
            "/api/gateway/v1/users/",
            "/api/gateway/v1/authenticators/",
            "/api/gateway/v1/authenticator_users/",
            "/api/controller/v2/users/",
            "/api/gateway/v1/role_user_assignments/",
        ):
            self.assertNotIn(path, client.paths)

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
