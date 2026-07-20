"""Tests for the shared Polaris AWS operator helpers (issue #691).

Run from this directory:
    python3 -m unittest test_common -v

The scripts import sibling modules by bare name, so the directory must be on
sys.path; running with ``-m unittest`` from here satisfies that.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from common import (
    PORTAL_INSTANCE_TAG_NAME,
    PolarisAwsContext,
    PortalShellTransport,
    SsmExecutor,
    SsmResult,
    SsmTimeout,
    find_portal_instance,
    mask_sensitive_output,
    parse_json_envelope,
)


# -----------------------------------------------------------------------------
# parse_json_envelope
# -----------------------------------------------------------------------------


class ParseJsonEnvelopeTests(unittest.TestCase):
    def test_returns_parsed_object_between_default_markers(self) -> None:
        stdout = 'noise\n__JSON_START__{"a": 1, "b": [2, 3]}__JSON_END__\nmore noise'

        self.assertEqual(parse_json_envelope(stdout), {"a": 1, "b": [2, 3]})

    def test_tolerates_whitespace_inside_envelope(self) -> None:
        stdout = "x\n__JSON_START__\n   {\"k\": \"v\"}   \n__JSON_END__\n"

        self.assertEqual(parse_json_envelope(stdout), {"k": "v"})

    def test_raises_when_markers_missing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "JSON markers missing"):
            parse_json_envelope("no markers here")

    def test_raises_when_only_one_marker_present(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "JSON markers missing"):
            parse_json_envelope("__JSON_START__{}")

    def test_raises_on_malformed_json(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "bad JSON"):
            parse_json_envelope("__JSON_START__{not json}__JSON_END__")

    def test_supports_custom_markers(self) -> None:
        stdout = "__RECORD__[1,2,3]__END__"

        self.assertEqual(
            parse_json_envelope(stdout, start="__RECORD__", end="__END__"),
            [1, 2, 3],
        )


# -----------------------------------------------------------------------------
# mask_sensitive_output
# -----------------------------------------------------------------------------


class MaskSensitiveOutputTests(unittest.TestCase):
    def test_redacts_known_secret(self) -> None:
        masked = mask_sensitive_output("token=super-secret abc", ["super-secret"])

        self.assertEqual(masked, "token=***REDACTED*** abc")

    def test_redacts_multiple_secrets(self) -> None:
        masked = mask_sensitive_output(
            "AWS_SECRET=abc CTFD_TOKEN=def",
            ["abc", "def"],
        )

        self.assertEqual(masked, "AWS_SECRET=***REDACTED*** CTFD_TOKEN=***REDACTED***")

    def test_no_secrets_returns_input_unchanged(self) -> None:
        self.assertEqual(mask_sensitive_output("hello world", []), "hello world")

    def test_empty_secret_is_ignored(self) -> None:
        # An empty string would match everywhere; never substitute it.
        self.assertEqual(
            mask_sensitive_output("hello", ["", "world"]),
            "hello",
        )

    def test_handles_none_in_iterable(self) -> None:
        self.assertEqual(
            mask_sensitive_output("hello secret", [None, "secret"]),  # type: ignore[list-item]
            "hello ***REDACTED***",
        )


# -----------------------------------------------------------------------------
# find_portal_instance
# -----------------------------------------------------------------------------


class FindPortalInstanceTests(unittest.TestCase):
    def test_returns_first_running_instance_id(self) -> None:
        ec2 = MagicMock()
        ec2.describe_instances.return_value = {
            "Reservations": [
                {"Instances": [{"InstanceId": "i-aaa"}, {"InstanceId": "i-bbb"}]},
            ],
        }

        self.assertEqual(find_portal_instance(ec2), "i-aaa")
        ec2.describe_instances.assert_called_once()
        kwargs = ec2.describe_instances.call_args.kwargs
        # Confirms the filter pins on Name tag + running state.
        filters = {f["Name"]: f["Values"] for f in kwargs["Filters"]}
        self.assertEqual(filters["tag:Name"], [PORTAL_INSTANCE_TAG_NAME])
        self.assertEqual(filters["instance-state-name"], ["running"])

    def test_raises_when_no_instances(self) -> None:
        ec2 = MagicMock()
        ec2.describe_instances.return_value = {"Reservations": []}

        with self.assertRaisesRegex(RuntimeError, "no running instance"):
            find_portal_instance(ec2)

    def test_supports_custom_tag(self) -> None:
        ec2 = MagicMock()
        ec2.describe_instances.return_value = {
            "Reservations": [{"Instances": [{"InstanceId": "i-xyz"}]}],
        }

        self.assertEqual(find_portal_instance(ec2, name_tag="my-portal"), "i-xyz")
        filters = {f["Name"]: f["Values"] for f in ec2.describe_instances.call_args.kwargs["Filters"]}
        self.assertEqual(filters["tag:Name"], ["my-portal"])


# -----------------------------------------------------------------------------
# SsmExecutor
# -----------------------------------------------------------------------------


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetCommandInvocation")


class SsmExecutorTests(unittest.TestCase):
    def test_run_bash_round_trip_success(self) -> None:
        ssm = MagicMock()
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
        ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "ok-out",
            "StandardErrorContent": "",
        }
        executor = SsmExecutor(ssm, poll_interval_s=0)

        result = executor.run_bash("i-1", "echo hi", timeout_s=30)

        self.assertIsInstance(result, SsmResult)
        self.assertEqual(result.command_id, "cmd-1")
        self.assertEqual(result.instance_id, "i-1")
        self.assertEqual(result.status, "Success")
        self.assertEqual(result.stdout, "ok-out")
        self.assertEqual(result.stderr, "")
        ssm.send_command.assert_called_once()

    def test_run_bash_raises_on_terminal_failure(self) -> None:
        ssm = MagicMock()
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-2"}}
        ssm.get_command_invocation.return_value = {
            "Status": "Failed",
            "StandardOutputContent": "out",
            "StandardErrorContent": "err",
        }
        executor = SsmExecutor(ssm, poll_interval_s=0)

        with self.assertRaisesRegex(RuntimeError, "SSM command failed .Failed."):
            executor.run_bash("i-1", "false", timeout_s=10)

    def test_poll_invocation_retries_on_invocation_not_yet_visible(self) -> None:
        ssm = MagicMock()
        ssm.get_command_invocation.side_effect = [
            _client_error("InvocationDoesNotExist"),
            {
                "Status": "Success",
                "StandardOutputContent": "done",
                "StandardErrorContent": "",
            },
        ]
        executor = SsmExecutor(ssm, poll_interval_s=0)

        result = executor.poll_invocation("cmd-3", "i-2", timeout_s=10)

        self.assertEqual(result.status, "Success")
        self.assertEqual(result.stdout, "done")
        self.assertEqual(ssm.get_command_invocation.call_count, 2)

    def test_poll_invocation_re_raises_unknown_client_error(self) -> None:
        ssm = MagicMock()
        ssm.get_command_invocation.side_effect = _client_error("InternalServerError")
        executor = SsmExecutor(ssm, poll_interval_s=0)

        with self.assertRaises(ClientError):
            executor.poll_invocation("cmd-4", "i-3", timeout_s=5)

    def test_poll_invocation_raises_timeout_when_deadline_exceeded(self) -> None:
        ssm = MagicMock()
        ssm.get_command_invocation.return_value = {
            "Status": "InProgress",
            "StandardOutputContent": "",
            "StandardErrorContent": "",
        }
        # grace=0 keeps the test fast; production callers leave the default 30s.
        executor = SsmExecutor(ssm, poll_interval_s=0, poll_grace_s=0)

        with self.assertRaises(SsmTimeout):
            executor.poll_invocation("cmd-5", "i-4", timeout_s=0)

    def test_run_bash_batch_returns_per_instance_results(self) -> None:
        ssm = MagicMock()
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-6"}}
        ssm.get_paginator.return_value.paginate.return_value = [
            {
                "CommandInvocations": [
                    {
                        "InstanceId": "i-1",
                        "Status": "Success",
                        "CommandPlugins": [
                            {"Output": "out-1", "StandardErrorContent": ""},
                        ],
                    },
                    {
                        "InstanceId": "i-2",
                        "Status": "Success",
                        "CommandPlugins": [
                            {"Output": "out-2", "StandardErrorContent": "warn"},
                        ],
                    },
                ],
            },
        ]
        executor = SsmExecutor(ssm, poll_interval_s=0)

        results = executor.run_bash_batch(["i-1", "i-2"], "echo hi", timeout_s=30)

        self.assertEqual(set(results), {"i-1", "i-2"})
        self.assertEqual(results["i-1"].stdout, "out-1")
        self.assertEqual(results["i-2"].stderr, "warn")
        self.assertEqual(results["i-1"].status, "Success")

    def test_run_bash_batch_keeps_polling_until_all_requested_ids_report(self) -> None:
        # First poll only returns i-1 (Success); list_command_invocations can be
        # eventually consistent. The batch must NOT return early — it must wait
        # for i-2 to also appear with a terminal status.
        ssm = MagicMock()
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-7"}}
        ssm.get_paginator.return_value.paginate.side_effect = [
            [
                {
                    "CommandInvocations": [
                        {
                            "InstanceId": "i-1",
                            "Status": "Success",
                            "CommandPlugins": [
                                {"Output": "out-1", "StandardErrorContent": ""},
                            ],
                        },
                    ],
                },
            ],
            [
                {
                    "CommandInvocations": [
                        {
                            "InstanceId": "i-1",
                            "Status": "Success",
                            "CommandPlugins": [
                                {"Output": "out-1", "StandardErrorContent": ""},
                            ],
                        },
                        {
                            "InstanceId": "i-2",
                            "Status": "Success",
                            "CommandPlugins": [
                                {"Output": "out-2", "StandardErrorContent": ""},
                            ],
                        },
                    ],
                },
            ],
        ]
        executor = SsmExecutor(ssm, poll_interval_s=0)

        results = executor.run_bash_batch(["i-1", "i-2"], "echo hi", timeout_s=30)

        self.assertEqual(set(results), {"i-1", "i-2"})
        self.assertEqual(results["i-2"].stdout, "out-2")
        self.assertEqual(ssm.get_paginator.return_value.paginate.call_count, 2)

    def test_run_bash_batch_times_out_when_requested_id_never_reports(self) -> None:
        ssm = MagicMock()
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-8"}}
        ssm.get_paginator.return_value.paginate.return_value = [
            {
                "CommandInvocations": [
                    {
                        "InstanceId": "i-1",
                        "Status": "Success",
                        "CommandPlugins": [
                            {"Output": "out-1", "StandardErrorContent": ""},
                        ],
                    },
                ],
            },
        ]
        executor = SsmExecutor(ssm, poll_interval_s=0, poll_grace_s=0)

        with self.assertRaises(SsmTimeout):
            executor.run_bash_batch(["i-1", "i-missing"], "echo hi", timeout_s=0)


# -----------------------------------------------------------------------------
# PortalShellTransport
# -----------------------------------------------------------------------------


class PortalShellTransportTests(unittest.TestCase):
    def test_run_django_wraps_payload_and_returns_parsed_envelope(self) -> None:
        ssm = MagicMock()
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
        ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "StandardOutputContent": "__JSON_START__{\"hello\": \"world\"}__JSON_END__",
            "StandardErrorContent": "",
        }
        transport = PortalShellTransport(SsmExecutor(ssm, poll_interval_s=0), "i-portal")

        parsed = transport.run_django("print('hello')", timeout_s=30)

        self.assertEqual(parsed, {"hello": "world"})
        # Confirm the inner script went over via base64 in send_command parameters.
        kwargs = ssm.send_command.call_args.kwargs
        commands = kwargs["Parameters"]["commands"]
        # one command string, includes base64 indirection sentinel.
        self.assertEqual(len(commands), 1)
        self.assertIn("base64 -d", commands[0])
        self.assertIn("docker exec portal", commands[0])

    def test_run_django_propagates_failure(self) -> None:
        ssm = MagicMock()
        ssm.send_command.return_value = {"Command": {"CommandId": "cmd-2"}}
        ssm.get_command_invocation.return_value = {
            "Status": "Failed",
            "StandardOutputContent": "",
            "StandardErrorContent": "broken",
        }
        transport = PortalShellTransport(SsmExecutor(ssm, poll_interval_s=0), "i-portal")

        with self.assertRaises(RuntimeError):
            transport.run_django("raise Exception", timeout_s=10)


# -----------------------------------------------------------------------------
# PolarisAwsContext
# -----------------------------------------------------------------------------


class PolarisAwsContextTests(unittest.TestCase):
    def test_clients_are_cached_per_service(self) -> None:
        fake_session = MagicMock()
        fake_session.client.side_effect = lambda service: MagicMock(name=service)
        ctx = PolarisAwsContext(profile=None, region="us-east-2", _session=fake_session)

        ec2_a = ctx.ec2()
        ec2_b = ctx.ec2()
        ssm_a = ctx.ssm()
        ssm_b = ctx.ssm()

        self.assertIs(ec2_a, ec2_b)
        self.assertIs(ssm_a, ssm_b)
        # 2 distinct services, each created once.
        self.assertEqual(fake_session.client.call_count, 2)

    def test_session_factory_uses_profile_and_region(self) -> None:
        recorded: dict[str, object] = {}

        def fake_session_factory(**kwargs):
            recorded.update(kwargs)
            return MagicMock()

        ctx = PolarisAwsContext(
            profile="my-profile",
            region="us-west-1",
            _session_factory=fake_session_factory,
        )
        ctx.session()

        self.assertEqual(recorded, {"profile_name": "my-profile", "region_name": "us-west-1"})


if __name__ == "__main__":
    unittest.main()
