"""Tests for cyberscript.schemas.ctf.

Covers:
- Each schema module's basic validation rules
- CTFRangeSpec cross-reference integrity
- AnyRangeSpec discriminated union
- ScenarioOverlaySpec validation (dep cycles, safety override)
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError


def _minimal_range_kwargs(**overrides):
    """Produce the minimum keyword args to construct a CTFRangeSpec."""
    from cyberscript.schemas.ctf import (
        AssetNetworkAttachment,
        AssetSpec,
        GDCNetworkBinding,
        NetworkSpec,
        ParticipantAccessSpec,
        ZoneSpec,
    )

    zones = [ZoneSpec(name="z-a", kind="admin")]
    nets = [
        NetworkSpec(
            name="net-a",
            zone="z-a",
            gdc=GDCNetworkBinding(nad_name="nad-a", cidr="10.0.0.0/24"),
        )
    ]
    assets = [
        AssetSpec(
            name="a-one",
            asset_type="scenario_pod",
            role="victim",
            os_type="alpine",
            zone="z-a",
            networks=[AssetNetworkAttachment(network="net-a", primary=True)],
            image="busybox:1.36",
        )
    ]
    pa = ParticipantAccessSpec(kali_networks=["net-a"])

    kwargs = dict(
        scenario_id="test-scenario",
        user_id=1,
        subnets=[],
        zones=zones,
        networks=nets,
        assets=assets,
        participant_access=pa,
    )
    kwargs.update(overrides)
    return kwargs


class TestZoneAndNetwork:
    def test_network_rejects_bad_cidr(self):
        from cyberscript.schemas.ctf import GDCNetworkBinding

        with pytest.raises(ValidationError, match="invalid CIDR"):
            GDCNetworkBinding(nad_name="x", cidr="not-a-cidr")

    def test_network_rejects_vlan_out_of_range(self):
        from cyberscript.schemas.ctf import GDCNetworkBinding

        with pytest.raises(ValidationError, match="vlan_id must be in"):
            GDCNetworkBinding(nad_name="x", cidr="10.0.0.0/24", vlan_id=5000)

    def test_zone_rejects_empty_name(self):
        from cyberscript.schemas.ctf import ZoneSpec

        with pytest.raises(ValidationError, match="empty"):
            ZoneSpec(name="   ", kind="admin")


class TestAsset:
    def test_dc_vm_requires_dc_role(self):
        from cyberscript.schemas.ctf import AssetSpec, DCConfigExt

        with pytest.raises(ValidationError, match="dc_vm asset_type requires role='dc'"):
            AssetSpec(
                name="bad-dc",
                asset_type="dc_vm",
                role="victim",
                os_type="windows",
                zone="z",
                dc_config=DCConfigExt(domain_name="x.local", netbios_name="X"),
            )

    def test_dc_vm_requires_dc_config(self):
        from cyberscript.schemas.ctf import AssetSpec

        with pytest.raises(ValidationError, match="requires dc_config"):
            AssetSpec(
                name="bad-dc",
                asset_type="dc_vm",
                role="dc",
                os_type="windows",
                zone="z",
            )

    def test_ot_role_requires_safety_envelope(self):
        from cyberscript.schemas.ctf import AssetSpec

        with pytest.raises(ValidationError, match="must declare safety_envelope"):
            AssetSpec(
                name="bad-ot",
                asset_type="ot_plc_pod",
                role="ot",
                os_type="alpine",
                zone="z",
            )

    def test_ngfw_asset_type_requires_ngfw_role(self):
        from cyberscript.schemas.ctf import AssetSpec

        with pytest.raises(ValidationError, match="requires role='ngfw'"):
            AssetSpec(
                name="bad-ngfw",
                asset_type="ngfw",
                role="victim",
                os_type="panos",
                zone="z",
            )

    def test_primary_network_unique(self):
        from cyberscript.schemas.ctf import AssetNetworkAttachment, AssetSpec

        with pytest.raises(ValidationError, match="at most one primary"):
            AssetSpec(
                name="multi-primary",
                asset_type="scenario_pod",
                role="victim",
                os_type="alpine",
                zone="z",
                networks=[
                    AssetNetworkAttachment(network="n1", primary=True),
                    AssetNetworkAttachment(network="n2", primary=True),
                ],
            )


class TestFlag:
    def test_flag_id_must_be_non_empty(self):
        from cyberscript.schemas.ctf import FlagSpec

        with pytest.raises(ValidationError, match="empty"):
            FlagSpec(
                id="",
                display_name="x",
                points=100,
                difficulty="easy",
                zone="z",
                asset="a",
            )

    def test_unlock_day_must_be_positive(self):
        from cyberscript.schemas.ctf import FlagSpec

        with pytest.raises(ValidationError, match="unlock_day must be >= 1"):
            FlagSpec(
                id="f1",
                display_name="x",
                points=100,
                difficulty="easy",
                zone="z",
                asset="a",
                unlock_day=0,
            )


class TestForest:
    def test_domain_requires_fqdn(self):
        from cyberscript.schemas.ctf import DomainSpec

        with pytest.raises(ValidationError, match="must be a FQDN"):
            DomainSpec(
                domain_name="notfqdn",
                netbios_name="NS",
                dc_asset_names=["dc1"],
            )

    def test_netbios_uppercased_and_length_checked(self):
        from cyberscript.schemas.ctf import DomainSpec

        d = DomainSpec(
            domain_name="example.com",
            netbios_name="example",
            dc_asset_names=["dc1"],
        )
        assert d.netbios_name == "EXAMPLE"

        with pytest.raises(ValidationError, match="<= 15 characters"):
            DomainSpec(
                domain_name="example.com",
                netbios_name="X" * 16,
                dc_asset_names=["dc1"],
            )

    def test_forest_rejects_self_trust(self):
        from cyberscript.schemas.ctf import DomainSpec, ForestSpec, ForestTrustSpec

        with pytest.raises(ValidationError, match="trust to itself"):
            ForestSpec(
                name="f",
                root_domain=DomainSpec(
                    domain_name="f.local",
                    netbios_name="F",
                    dc_asset_names=["dc1"],
                ),
                trusts=[ForestTrustSpec(target_forest="f", kind="two_way")],
            )


class TestCTFRangeSpec:
    def test_minimal_range_validates(self):
        from cyberscript.schemas.ctf import CTFRangeSpec

        r = CTFRangeSpec(**_minimal_range_kwargs())
        assert r.range_type == "ctf"
        assert r.cyberscript_version == "v1"
        assert len(r.assets) == 1

    def test_rejects_empty_zones(self):
        from cyberscript.schemas.ctf import CTFRangeSpec

        with pytest.raises(ValidationError, match="at least one zone"):
            CTFRangeSpec(**_minimal_range_kwargs(zones=[]))

    def test_rejects_unknown_zone_ref_on_network(self):
        from cyberscript.schemas.ctf import (
            CTFRangeSpec,
            GDCNetworkBinding,
            NetworkSpec,
            ZoneSpec,
        )

        kwargs = _minimal_range_kwargs(
            networks=[
                NetworkSpec(
                    name="net-a",
                    zone="zone-does-not-exist",
                    gdc=GDCNetworkBinding(nad_name="x", cidr="10.1.0.0/24"),
                )
            ],
            zones=[ZoneSpec(name="z-a", kind="admin")],
        )
        with pytest.raises(ValidationError, match="unknown zone"):
            CTFRangeSpec(**kwargs)

    def test_rejects_unknown_asset_service_ref(self):
        from cyberscript.schemas.ctf import (
            AssetNetworkAttachment,
            AssetSpec,
            CTFRangeSpec,
        )

        assets = [
            AssetSpec(
                name="a-one",
                asset_type="scenario_pod",
                role="victim",
                os_type="alpine",
                zone="z-a",
                networks=[AssetNetworkAttachment(network="net-a", primary=True)],
                services=["ghost-service"],
                image="busybox:1.36",
            )
        ]
        kwargs = _minimal_range_kwargs(assets=assets)
        with pytest.raises(ValidationError, match="unknown service 'ghost-service'"):
            CTFRangeSpec(**kwargs)

    def test_rejects_duplicate_asset_names(self):
        from cyberscript.schemas.ctf import (
            AssetNetworkAttachment,
            AssetSpec,
            CTFRangeSpec,
        )

        dup = [
            AssetSpec(
                name="dup",
                asset_type="scenario_pod",
                role="victim",
                os_type="alpine",
                zone="z-a",
                networks=[AssetNetworkAttachment(network="net-a", primary=True)],
                image="busybox:1.36",
            ),
            AssetSpec(
                name="dup",
                asset_type="scenario_pod",
                role="victim",
                os_type="alpine",
                zone="z-a",
                networks=[AssetNetworkAttachment(network="net-a")],
                image="busybox:1.36",
            ),
        ]
        with pytest.raises(ValidationError, match="duplicate asset name 'dup'"):
            CTFRangeSpec(**_minimal_range_kwargs(assets=dup))

    def test_rejects_duplicate_flag_ids(self):
        from cyberscript.schemas.ctf import CTFRangeSpec, FlagSpec

        flags = [
            FlagSpec(
                id="same",
                display_name="x",
                points=100,
                difficulty="easy",
                zone="z-a",
                asset="a-one",
            ),
            FlagSpec(
                id="same",
                display_name="y",
                points=100,
                difficulty="easy",
                zone="z-a",
                asset="a-one",
            ),
        ]
        with pytest.raises(ValidationError, match="duplicate flag id 'same'"):
            CTFRangeSpec(**_minimal_range_kwargs(flags=flags))


class TestAnyRangeSpecDiscriminator:
    def test_demo_range_discriminates(self):
        from cyberscript.schemas import AnyRangeSpec, InstanceSpec

        # Demo range payload
        payload = {
            "scenario_id": "basic",
            "user_id": 1,
            "subnets": [
                {
                    "name": "subnet-a",
                    "instances": [
                        {
                            "name": "i1",
                            "role": "attacker",
                            "os_type": "kali",
                        }
                    ],
                }
            ],
            "range_type": "demo",
        }
        r = TypeAdapter(AnyRangeSpec).validate_python(payload)
        assert r.range_type == "demo"
        assert isinstance(r.subnets[0].instances[0], InstanceSpec)

    def test_ctf_range_discriminates(self):
        from cyberscript.schemas import AnyRangeSpec, CTFRangeSpec

        # Build via the helper
        ctf_kwargs = _minimal_range_kwargs()
        ctf_kwargs["range_type"] = "ctf"

        # Serialize to dict then re-parse via discriminator
        ctf = CTFRangeSpec(**ctf_kwargs)
        as_dict = ctf.model_dump(mode="python")
        r = TypeAdapter(AnyRangeSpec).validate_python(as_dict)
        assert r.range_type == "ctf"


class TestScenarioOverlay:
    def test_safety_override_demands_review(self):
        from cyberscript.schemas.ctf import (
            InjectVulnOperation,
            ScenarioOverlayMetadata,
            ScenarioOverlaySpec,
        )

        op = InjectVulnOperation(
            op_id="op-inject-safety",
            target="OBS-01",
            vuln_id="hvac-bad-write",
            override_safety_envelope=True,
        )
        meta = ScenarioOverlayMetadata(
            title="x", summary="x", duration_days=5
        )
        with pytest.raises(ValidationError, match="must include safety_review"):
            ScenarioOverlaySpec(
                scenario_id="s",
                baseline_fingerprint="sha256:abc",
                operations=[op],
                metadata=meta,
            )

    def test_dep_cycle_detection(self):
        from cyberscript.schemas.ctf import (
            ScenarioOverlayMetadata,
            ScenarioOverlaySpec,
            TagOperation,
        )

        a = TagOperation(op_id="a", target="X", tags={}, depends_on=["b"])
        b = TagOperation(op_id="b", target="X", tags={}, depends_on=["a"])
        meta = ScenarioOverlayMetadata(title="x", summary="x", duration_days=3)
        with pytest.raises(ValidationError, match="dependency cycle"):
            ScenarioOverlaySpec(
                scenario_id="s",
                baseline_fingerprint="sha256:abc",
                operations=[a, b],
                metadata=meta,
            )

    def test_unique_op_ids(self):
        from cyberscript.schemas.ctf import (
            ScenarioOverlayMetadata,
            ScenarioOverlaySpec,
            TagOperation,
        )

        a = TagOperation(op_id="same", target="X", tags={})
        b = TagOperation(op_id="same", target="Y", tags={})
        meta = ScenarioOverlayMetadata(title="x", summary="x", duration_days=3)
        with pytest.raises(ValidationError, match="duplicate op_id"):
            ScenarioOverlaySpec(
                scenario_id="s",
                baseline_fingerprint="sha256:abc",
                operations=[a, b],
                metadata=meta,
            )

    def test_depends_on_unknown_op(self):
        from cyberscript.schemas.ctf import (
            ScenarioOverlayMetadata,
            ScenarioOverlaySpec,
            TagOperation,
        )

        a = TagOperation(op_id="a", target="X", tags={}, depends_on=["ghost"])
        meta = ScenarioOverlayMetadata(title="x", summary="x", duration_days=3)
        with pytest.raises(ValidationError, match="unknown op 'ghost'"):
            ScenarioOverlaySpec(
                scenario_id="s",
                baseline_fingerprint="sha256:abc",
                operations=[a],
                metadata=meta,
            )
