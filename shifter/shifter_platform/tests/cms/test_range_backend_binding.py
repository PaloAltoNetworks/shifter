"""CMS live-fire gate returns its BackendAdmission for #1666 ownership binding.

The gate still raises on a denied backend; on an admitted GCP launch it now
returns the trusted BackendAdmission so the caller carries (backend, purpose) to
Engine persistence beside the spec (never a second env read).
"""

import os
from unittest.mock import patch

import pytest

from cms.exceptions import CMSError
from cms.services._range_create import _assert_live_fire_backend_admitted
from shared.range_instantiation_policy import InstantiationPurpose


class TestLiveFireGateReturnsAdmission:
    def test_returns_admission_on_admitted_gcp_launch(self, settings):
        settings.CLOUD_PROVIDER = "gcp"
        with patch.dict(os.environ, {"GCP_RANGE_BACKEND": "gce"}, clear=True):
            admission = _assert_live_fire_backend_admitted()
        assert admission is not None
        assert admission.admitted is True
        assert admission.backend == "gce"
        assert admission.purpose is InstantiationPurpose.LIVE_FIRE

    def test_returns_none_on_non_gcp(self, settings):
        settings.CLOUD_PROVIDER = "aws"
        assert _assert_live_fire_backend_admitted() is None

    def test_still_raises_on_denied_backend(self, settings):
        settings.CLOUD_PROVIDER = "gcp"
        with (
            patch.dict(os.environ, {"GCP_RANGE_BACKEND": "gdc"}, clear=True),
            pytest.raises(CMSError),
        ):
            _assert_live_fire_backend_admitted()
