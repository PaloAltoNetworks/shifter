"""Base class for GCP cloud adapters.

Provides shared Google Cloud project resolution used by all GCP adapters.
"""

from __future__ import annotations

import os


class BaseGCPAdapter:
    """Base class providing shared GCP project resolution.

    Subclasses use google-cloud-* libraries for their specific services.
    """

    def _get_project(self) -> str:
        """Get the GCP project ID from environment."""
        project = os.environ.get("GCP_PROJECT_ID", "")
        if not project:
            raise ValueError("GCP_PROJECT_ID environment variable is required")
        return project
