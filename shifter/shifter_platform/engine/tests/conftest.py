"""Engine integration test environment defaults."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "engine-tests-secret-key")
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("SITE_URL", "http://localhost")
