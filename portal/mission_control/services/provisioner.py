"""Stub provisioner for range infrastructure.

This module provides a stub implementation of the provisioning service
that simulates infrastructure deployment. In production, this will be
replaced by AWS Step Functions that orchestrate Terraform.

For now, it uses threading to simulate async provisioning and calls
back to the Portal API after a short delay.
"""

import hashlib
import hmac
import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Stub provisioning delay in seconds
STUB_PROVISIONING_DELAY = 3

# Stub teardown delay in seconds
STUB_TEARDOWN_DELAY = 2


def _generate_callback_token(range_id: int) -> str:
    """Generate HMAC-signed callback token for a range."""
    message = f"range_callback:{range_id}"
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return signature


def verify_callback_token(range_id: int, token: str) -> bool:
    """Verify callback token for a range."""
    expected = _generate_callback_token(range_id)
    return hmac.compare_digest(expected, token)


def _get_callback_url() -> str:
    """Get the URL for the range callback endpoint.

    Raises:
        ValueError: If SITE_URL is not configured in settings.
    """
    base_url = getattr(settings, "SITE_URL", None)
    if not base_url:
        raise ValueError(
            "SITE_URL must be configured in settings. "
            "Set SITE_URL environment variable (e.g., http://localhost:8000 for local dev, "
            "https://your-domain.com for production)."
        )
    return f"{base_url}/mission-control/api/range/callback/"


def _do_stub_provisioning(range_id: int):
    """Simulate provisioning and call back when done.

    This runs in a background thread to simulate async provisioning.
    In production, Step Functions would handle this.
    """
    logger.info(f"[STUB] Starting provisioning for range_id={range_id}")

    # Simulate provisioning delay
    time.sleep(STUB_PROVISIONING_DELAY)

    # Generate stub data
    # In production, these would come from Terraform outputs
    stub_victim_ip = "10.0.1.100"
    stub_chat_url = f"http://localhost:3000/chat/range-{range_id}"

    callback_token = _generate_callback_token(range_id)
    callback_url = _get_callback_url()

    payload = {
        "range_id": range_id,
        "status": "ready",
        "callback_token": callback_token,
        "victim_ip": stub_victim_ip,
        "chat_url": stub_chat_url,
    }

    try:
        response = requests.post(callback_url, json=payload, timeout=10)
        if response.ok:
            logger.info(f"[STUB] Provisioning callback successful for range_id={range_id}")
        else:
            logger.error(
                f"[STUB] Provisioning callback failed for range_id={range_id}: "
                f"status={response.status_code} body={response.text}"
            )
    except requests.RequestException as e:
        logger.error(f"[STUB] Provisioning callback error for range_id={range_id}: {e}")


def _do_stub_teardown(range_id: int):
    """Simulate teardown and call back when done.

    This runs in a background thread to simulate async teardown.
    In production, Step Functions would handle this.
    """
    logger.info(f"[STUB] Starting teardown for range_id={range_id}")

    # Simulate teardown delay
    time.sleep(STUB_TEARDOWN_DELAY)

    callback_token = _generate_callback_token(range_id)
    callback_url = _get_callback_url()

    payload = {
        "range_id": range_id,
        "status": "destroyed",
        "callback_token": callback_token,
    }

    try:
        response = requests.post(callback_url, json=payload, timeout=10)
        if response.ok:
            logger.info(f"[STUB] Teardown callback successful for range_id={range_id}")
        else:
            logger.error(
                f"[STUB] Teardown callback failed for range_id={range_id}: "
                f"status={response.status_code} body={response.text}"
            )
    except requests.RequestException as e:
        logger.error(f"[STUB] Teardown callback error for range_id={range_id}: {e}")


def start_provisioning(range_id: int):
    """Start provisioning a range.

    In production, this would:
    1. Start a Step Function execution
    2. Pass the range_id and callback URL
    3. Step Function orchestrates CodeBuild/Terraform

    For now, it starts a background thread that simulates the process.
    """
    logger.info(f"Starting provisioning for range_id={range_id}")

    thread = threading.Thread(
        target=_do_stub_provisioning,
        args=(range_id,),
        daemon=True,
    )
    thread.start()


def start_teardown(range_id: int):
    """Start teardown of a range.

    In production, this would:
    1. Start a Step Function execution for teardown
    2. Step Function orchestrates terraform destroy

    For now, it starts a background thread that simulates the process.
    """
    logger.info(f"Starting teardown for range_id={range_id}")

    thread = threading.Thread(
        target=_do_stub_teardown,
        args=(range_id,),
        daemon=True,
    )
    thread.start()
