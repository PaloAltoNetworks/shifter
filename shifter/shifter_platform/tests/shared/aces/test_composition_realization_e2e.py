"""End-to-end: an authored ACES scenario with composition realizes real bootstrap.

This is the cross-boundary proof that composition realization is genuine (ADR-032,
issues #1477 and #1560). It compiles a real ACES SDL (a directory content placement
and password/public-key accounts) through the upstream compiler, serializes the plan exactly as the platform
persists it, then parses and realizes it with the **provisioner-side** modules
loaded standalone (in production the provisioner ships no aces_* and reads the
serialized plan as plain data) -- asserting the scenario's directory content,
accounts, and credential intent survive into the realizer. If the compiler's payload
convention shifts, or the provisioner reader/realizer drifts, this fails.

It exercises ``directory`` content and account placements through the full
compile -> serialize -> parse -> realize pipeline. ``file`` and ``directory`` are
both declared manifest capabilities again as of #1564 (every admitted shape --
inline text, empty directory, and genuinely-delivered source-backed file/directory
-- has a real, digest-verified guest effect). Inline-file bootstrap rendering is
covered by ``test_aces_gcp_composition.py``; genuine source-backed content
delivery (materialize -> promote -> transport -> in-guest digest readback) is
covered by the CMS delivery-prep tests and the provisioner delivery tests.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from aces_runtime.manager import RuntimeManager
from aces_sdl.parser import parse_sdl

from shared.aces.dispatch_port import ShifterDispatchResult
from shared.aces.runtime_target import create_shifter_backend_target, serialize_provisioning_plan

_PROVISIONER_DIR = Path(__file__).resolve().parents[4] / "engine" / "provisioner"

# Content + account exercise the full compile -> serialize -> parse -> realize
# pipeline through the real compiler. Feature-binding realization (which needs SDL
# role/entity definitions) is covered by the provisioner composition unit tests
# and the platform envelope tests.
_SDL = """name: e2e-composition
version: "1.0.0"
nodes:
  web:
    type: vm
    os: linux
    source: base-linux
content:
  seed:
    type: directory
    target: web
    destination: /srv/data
accounts:
  alice:
    username: alice
    node: web
    groups: [ops]
  bob:
    username: bob
    node: web
    auth_method: publickey
    password_strength: strong
"""


@dataclass
class _Port:
    """Minimal dispatch port; plan() does not dispatch, so realize() is unused here."""

    request_id: str = "req-e2e"

    def realize(self, compiled_plan: dict) -> ShifterDispatchResult:
        return ShifterDispatchResult(request_id=self.request_id, accepted=True, status="accepted", range_id="r1")


def _load_provisioner_module(name: str):
    # Provisioner modules import their siblings (e.g. aces_plan -> aces_composition),
    # so the provisioner dir must be importable when they are loaded standalone.
    if str(_PROVISIONER_DIR) not in sys.path:
        sys.path.insert(0, str(_PROVISIONER_DIR))
    spec = importlib.util.spec_from_file_location(name, _PROVISIONER_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # so sibling `from aces_plan import ...` resolves
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def provisioner():
    aces_plan = _load_provisioner_module("aces_plan")
    composition = _load_provisioner_module("aces_gcp_composition")
    return aces_plan, composition


def test_authored_scenario_realizes_genuine_bootstrap(provisioner):
    aces_plan, composition = provisioner

    # Upstream compile -> serialize (exactly what the platform persists).
    scenario = parse_sdl(_SDL)
    plan = RuntimeManager(create_shifter_backend_target(port=_Port())).plan(scenario).provisioning
    serialized = serialize_provisioning_plan(plan)

    # Provisioner-side parse + realize (no aces_* imports).
    parsed = aces_plan.parse_plan(serialized)
    web = next(node for node in parsed.nodes if node.address.rsplit(".", 1)[-1] == "web")
    script = composition.node_bootstrap_script(web, parsed)

    # The scenario's directory content and account are genuinely realized in the guest bootstrap.
    assert "mkdir -p /srv/data" in script  # directory content (a retained, declared term)
    assert "useradd -m alice" in script  # account
    assert "usermod -aG ops alice" in script  # group membership
    assert "useradd -m bob" in script
    accounts = {account.username: account for account in parsed.accounts}
    assert accounts["alice"].auth_method == "password"  # upstream default still gets a credential
    assert accounts["alice"].password_strength == "medium"
    assert accounts["bob"].auth_method == "publickey"
    assert accounts["bob"].password_strength == "strong"
