"""Template-level tests for mission_control/terminal.html.

Verifies the issue #370 surface:
- Range number is appended after the scenario name when range_id is present.
- Range suffix is hidden when range_id is None.
- Per-instance data is embedded via Django's json_script tag (not inline JS interpolation),
  and the payload exposes uuid/role/osType/name/privateIp.
- Per-instance subtitle shows the IP when present.
"""

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from shared.enums import ResourceStatus
from shared.schemas import InstanceContext, RangeContext


def _range(range_id, instances):
    return RangeContext(
        request_id=uuid4(),
        range_id=range_id,
        user_id=42,
        scenario_id="ctf-basic",
        status=ResourceStatus.READY,
        instances=instances,
        agent_name="Agent",
    )


def _request():
    request = RequestFactory().get("/terminal/")
    user = MagicMock()
    user.is_authenticated = True
    user.is_active = True
    user.is_staff = False
    user.id = 42
    user.username = "test@example.com"
    user.email = "test@example.com"
    request.user = user
    return request


def _render(context):
    base_context = {
        "page_title": "Terminal",
        "active_nav": "terminal",
        "csrf_token": "test-csrf",
    }
    base_context.update(context)
    return render_to_string(
        "mission_control/terminal.html",
        base_context,
        request=_request(),
    )


class TestTerminalTemplateRangeSuffix:
    def test_appends_range_number_when_present(self):
        range_ctx = _range(42, [])
        html = _render(
            {
                "has_active_range": True,
                "active_range": range_ctx,
                "connection_urls": [],
                "scenario_name": "Capture The Flag",
                "terminal_instances": [],
            }
        )
        assert "Range 42" in html

    def test_omits_range_number_when_none(self):
        range_ctx = _range(None, [])
        html = _render(
            {
                "has_active_range": True,
                "active_range": range_ctx,
                "connection_urls": [],
                "scenario_name": "Capture The Flag",
                "terminal_instances": [],
            }
        )
        assert "Range " not in html
        assert "Capture The Flag" in html


class TestTerminalTemplateJsonScriptPayload:
    def _payload(self, html, element_id):
        marker = f'id="{element_id}"'
        assert marker in html, f"Expected json_script element id={element_id}"
        start = html.index(marker)
        gt = html.index(">", start) + 1
        end = html.index("</script>", gt)
        return json.loads(html[gt:end])

    def test_instances_payload_emitted_via_json_script(self):
        instance = InstanceContext(
            uuid="att-1",
            name="AttackerKali",
            role="attacker",
            os_type="kali",
            private_ip="10.0.1.5",
        )
        range_ctx = _range(7, [instance])
        terminal_instances = [
            {
                "uuid": "att-1",
                "role": "attacker",
                "osType": "kali",
                "name": "AttackerKali",
                "privateIp": "10.0.1.5",
            }
        ]
        html = _render(
            {
                "has_active_range": True,
                "active_range": range_ctx,
                "connection_urls": [{"uuid": "att-1", "terminal_url": "/ws/term/att-1"}],
                "scenario_name": "CTF",
                "terminal_instances": terminal_instances,
            }
        )

        payload = self._payload(html, "terminal-instances-data")
        assert payload == terminal_instances

    def test_pane_subtitle_shows_ip_when_present(self):
        instance = InstanceContext(
            uuid="att-1",
            name="AttackerKali",
            role="attacker",
            os_type="kali",
            private_ip="10.0.1.5",
        )
        range_ctx = _range(7, [instance])
        html = _render(
            {
                "has_active_range": True,
                "active_range": range_ctx,
                "connection_urls": [],
                "scenario_name": "CTF",
                "terminal_instances": [],
            }
        )
        assert "10.0.1.5" in html

    def test_pane_subtitle_omits_ip_when_missing(self):
        instance = InstanceContext(
            uuid="att-1",
            name="AttackerKali",
            role="attacker",
            os_type="kali",
        )
        range_ctx = _range(7, [instance])
        html = _render(
            {
                "has_active_range": True,
                "active_range": range_ctx,
                "connection_urls": [],
                "scenario_name": "CTF",
                "terminal_instances": [],
            }
        )
        # subtitle still has os_type
        assert "kali" in html
        # No IP smuggled in
        assert "10.0.1" not in html

    def test_no_inline_interpolation_of_instance_uuid(self):
        """Old inline JS pattern ('uuid: "att-1"') must be gone — payload now uses json_script."""
        instance = InstanceContext(
            uuid="att-1",
            name="AttackerKali",
            role="attacker",
            os_type="kali",
            private_ip="10.0.1.5",
        )
        range_ctx = _range(7, [instance])
        html = _render(
            {
                "has_active_range": True,
                "active_range": range_ctx,
                "connection_urls": [{"uuid": "att-1", "terminal_url": "/ws/term/att-1"}],
                "scenario_name": "CTF",
                "terminal_instances": [
                    {
                        "uuid": "att-1",
                        "role": "attacker",
                        "osType": "kali",
                        "name": "AttackerKali",
                        "privateIp": "10.0.1.5",
                    }
                ],
            }
        )
        assert 'uuid: "att-1"' not in html
        assert 'terminalUrl: "/ws/term/att-1"' not in html


@pytest.mark.parametrize("range_id,expected", [(1, "Range 1"), (99, "Range 99")])
def test_range_suffix_value(range_id, expected):
    range_ctx = _range(range_id, [])
    html = _render(
        {
            "has_active_range": True,
            "active_range": range_ctx,
            "connection_urls": [],
            "scenario_name": "Scenario",
            "terminal_instances": [],
        }
    )
    assert expected in html
