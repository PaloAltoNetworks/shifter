"""Root pytest hooks — must set env before Django settings import (#948)."""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")
