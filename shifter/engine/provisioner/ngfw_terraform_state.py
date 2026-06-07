"""State and Terraform variable helpers for NGFW Terraform operations."""

import os
from typing import Any


def _build_provider_state(output_data: dict[str, Any]) -> dict[str, Any]:
    """Build provider-neutral NGFW state fields for the Terraform outputs."""
    cloud_provider = output_data.get("cloud_provider") or os.environ.get("CLOUD_PROVIDER", "aws")
    management_ip = output_data.get("management_ip", "")
    dataplane_ip = output_data.get("dataplane_ip", "")
    data_attachment_id = output_data.get("data_eni_id", "")
    ssh_key_secret_arn = output_data.get("ssh_key_secret_arn", "")
    if cloud_provider == "gcp":
        data_attachment_id = output_data.get("data_attachment_id", "")
        return {
            "cloud_provider": "gcp",
            "route_next_hop_ip": output_data.get("route_next_hop_ip", ""),
            "attachment_mode": output_data.get("attachment_mode", "gdc-vmruntime-palo-alto-vmseries"),
            "data_attachment_id": data_attachment_id,
            "attached_ranges": [],
            "provider_metadata": output_data.get("provider_metadata", {}),
        }

    provider_state = {
        "management_ip": management_ip,
        "dataplane_ip": dataplane_ip,
        "route_next_hop_ip": dataplane_ip,
        "attachment_mode": "aws-route-table-eni" if cloud_provider == "aws" else "",
        "data_attachment_id": data_attachment_id,
        "data_eni_id": data_attachment_id,
        "ssh_key_secret_arn": ssh_key_secret_arn,
    }
    return {
        "cloud_provider": cloud_provider,
        "route_next_hop_ip": dataplane_ip,
        "attachment_mode": provider_state["attachment_mode"],
        "data_attachment_id": data_attachment_id,
        "attached_ranges": [],
        "provider_metadata": {
            cloud_provider: provider_state,
        },
    }


def _build_tf_variables(
    request_id: str,
    instance_id: str,
    app_spec: dict[str, Any],
) -> dict[str, Any]:
    """Build Terraform variables from environment and app_spec."""
    user_id = app_spec.get("user_id", 0)
    return {
        "name_prefix": f"ngfw-user-{user_id}",
        "user_id": user_id,
        "instance_uuid": instance_id,
        "request_uuid": request_id,
        "environment": os.environ.get("ENVIRONMENT", "dev"),
        "secrets_kms_key_arn": os.environ["SECRETS_KMS_KEY_ARN"],
        "subnet_id": os.environ.get("NGFW_SUBNET_ID", ""),
        "mgmt_security_group_id": os.environ.get("NGFW_MGMT_SECURITY_GROUP_ID", ""),
        "data_security_group_id": os.environ.get("NGFW_DATA_SECURITY_GROUP_ID", ""),
        "ami_id": os.environ.get("NGFW_AMI_ID", ""),
        "bootstrap_bucket": os.environ.get("NGFW_BOOTSTRAP_BUCKET", ""),
        "instance_type": os.environ.get("NGFW_INSTANCE_TYPE", "m5.xlarge"),
        "instance_profile_name": os.environ.get("NGFW_INSTANCE_PROFILE_NAME") or None,
        "scm_pin_id": app_spec.get("scm_pin_id", ""),
        "scm_pin_value": app_spec.get("scm_pin_value", ""),
        "scm_folder_name": app_spec.get("scm_folder_name", ""),
        "authcode": app_spec.get("authcode", ""),
    }
