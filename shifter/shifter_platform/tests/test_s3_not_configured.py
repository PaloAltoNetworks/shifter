"""Verify S3 helpers fail closed when AWS_S3_BUCKET_NAME is unset (issue #779 burndown)."""

import pytest
from django.test import override_settings

from cms.assets import s3 as assets_s3
from ctf import s3 as ctf_s3
from ctf.s3 import CTFFileError

pytestmark = pytest.mark.django_db


# (module, callable returning the result of invoking the function with dummy args)
CASES = [
    lambda: ctf_s3.delete_challenge_file("ctf/x"),
    lambda: ctf_s3.generate_download_url("ctf/x", "x.txt"),
    lambda: assets_s3.verify_s3_object_exists("agents/x"),
    lambda: assets_s3.read_agent_header("agents/x", 16),
    lambda: assets_s3.tag_s3_object("agents/x", {"k": "v"}),
    lambda: assets_s3.delete_agent("agents/x"),
]


@override_settings(AWS_S3_BUCKET_NAME="")
@pytest.mark.parametrize("invoke", CASES)
def test_raises_when_bucket_unset(invoke):
    with pytest.raises((assets_s3.S3Error, CTFFileError)):
        invoke()
