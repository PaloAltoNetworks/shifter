"""Scenario-layer services for CTF ranges.

A service is a logical grouping of one or more assets that together
deliver a capability (EHR, PACS, LIMS, HL7 engine, WAF, SIEM, etc.).
Services name the intent; assets implement it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

from ..base import SpecBase

ServiceType = Literal[
    "ehr",
    "pacs",
    "ris",
    "lims",
    "hl7_engine",
    "fhir_server",
    "pharmacy",
    "trial_mgmt",
    "patient_portal",
    "waf",
    "siem",
    "ids",
    "soar",
    "case_mgmt",
    "threat_intel",
    "genomics",
    "ml_serving",
    "ai_agent",
    "voip",
    "idp",
    "vms",
    "bas",
    "mail",
    "file_share",
    "source_repo",
    "helpdesk",
    "dns",
    "ntp",
    "dhcp",
    "hie_gateway",
    "telemed_api",
    "rpm",
    "video_consult",
    "remote_support",
    "asset_mgmt",
    "patch_mgmt",
    "billing",
    "procurement",
    "vendor_mgmt",
    "cmdb",
    "radius",
    "vpn",
]


ProtoLiteral = Literal[
    "http",
    "https",
    "dicom",
    "dicom_tls",
    "hl7_mllp",
    "hl7_mllp_tls",
    "modbus_tcp",
    "bacnet",
    "ssh",
    "rdp",
    "smb",
    "ftp",
    "sftp",
    "mqtt",
    "ldap",
    "ldaps",
    "snmp",
    "rtsp",
    "sip",
    "sip_tls",
    "ike",
    "wireguard",
    "tftp",
    "radius",
    "kerberos",
    "websocket",
    "webrtc",
]


class WeakWAFConfig(BaseModel):
    """Configuration block used by `service_type='waf'`.

    Baseline hospitals ship WAF in blocking mode; scenarios may weaken
    via config_patch. This block captures the final scenario-time
    posture for documentation + validation.

    Attributes:
        mode: SecRuleEngine mode.
        paranoia: CRS paranoia level.
        bypass_patterns: human-readable list of intentional bypass vectors.
        admin_allow_cidrs: CIDR allow-list for admin endpoints.
    """

    mode: Literal["On", "DetectionOnly"] = "On"
    paranoia: Literal[1, 2, 3, 4] = 1
    bypass_patterns: list[str] = []
    admin_allow_cidrs: list[str] = []


class ServiceEndpointSpec(BaseModel):
    """An exposed protocol/port on a service.

    Attributes:
        name: short descriptive label (e.g. "dicomweb").
        proto: protocol literal.
        port: TCP/UDP port.
        path: optional URL path for HTTP-family protocols.
        intentional_vulns: short identifiers overlays may target.
    """

    name: str
    proto: ProtoLiteral
    port: int
    path: str | None = None
    intentional_vulns: list[str] = []

    @field_validator("port")
    @classmethod
    def port_range(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("port must be in [1, 65535]")
        return v


class ServiceSpec(SpecBase):
    """A scenario-layer service.

    Attributes:
        name: unique service identifier.
        service_type: category from ServiceType.
        primary_asset: AssetSpec.name carrying the primary responsibility.
        component_assets: additional AssetSpec.name refs involved.
        exposed_endpoints: ServiceEndpointSpec list.
        waf: optional config block when service_type=='waf'.
    """

    name: str
    service_type: ServiceType
    primary_asset: str
    component_assets: list[str] = []
    exposed_endpoints: list[ServiceEndpointSpec] = []
    waf: WeakWAFConfig | None = None

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("service name must be non-empty")
        return v.strip()
