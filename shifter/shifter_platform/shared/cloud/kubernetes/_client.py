"""Lazy Kubernetes client loading for the neutral task runner.

The Kubernetes Python client is an optional runtime dependency for
Kubernetes-backed flows and must not be imported at module import time so
non-Kubernetes processes never pay for it (#1824).
"""

from __future__ import annotations

import importlib
import os

from shared.cloud.exceptions import CloudTaskError


def load_kubernetes_api() -> tuple[object, object, object, type[Exception]]:
    """Return ``(BatchV1Api, CoreV1Api, client module, ApiException)``.

    Loads in-cluster configuration when running inside a Pod and falls back to
    the local kubeconfig otherwise. Any failure is normalized to
    ``CloudTaskError`` without leaking provider diagnostics.
    """
    try:
        kubernetes = importlib.import_module("kubernetes")
    except ImportError as e:
        raise CloudTaskError("Kubernetes task runner support requires kubernetes") from e

    config = kubernetes.config
    config_exception = getattr(getattr(config, "config_exception", None), "ConfigException", Exception)

    try:
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            try:
                config.load_incluster_config()
            except config_exception:
                config.load_kube_config()
        else:
            config.load_kube_config()
    except Exception as e:
        raise CloudTaskError(f"Failed to load Kubernetes client configuration ({type(e).__name__})") from e

    client = kubernetes.client
    api_exception = getattr(getattr(client, "exceptions", None), "ApiException", Exception)
    return client.BatchV1Api(), client.CoreV1Api(), client, api_exception
