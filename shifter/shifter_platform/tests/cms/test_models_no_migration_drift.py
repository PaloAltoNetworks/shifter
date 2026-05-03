"""Migration safety net for the cms.models package refactor.

Splitting ``cms/models.py`` into a package must produce zero new migrations.
Django identifies a model by ``app_label`` + class name + ``db_table`` (not
``__module__``), so re-exports plus unchanged Meta should be enough — but the
only reliable proof is to run ``makemigrations --check --dry-run`` itself.

This test runs continuously throughout the #1067 refactor (and protects every
future PR that touches CMS models) by failing if any pending model change has
not been captured in a concrete migration file.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_cms_models_have_no_pending_migrations():
    """``manage.py makemigrations cms --check --dry-run`` must exit cleanly.

    Django's ``--check`` flag makes the command exit non-zero when changes
    would have been written; ``--dry-run`` keeps it from actually writing
    files. Combined, they assert "the model graph matches the on-disk
    migration history."

    A failure means one of:
      * a field/Meta/constraint changed silently during the refactor;
      * ``db_table`` drifted because Django's auto-naming key changed;
      * a class moved to a new app_label by mistake.

    The fix is never to run ``makemigrations`` and commit the diff — the
    refactor is structural-only by contract. Find what changed and revert
    that piece.
    """
    stdout = StringIO()
    stderr = StringIO()
    try:
        call_command(
            "makemigrations",
            "cms",
            "--check",
            "--dry-run",
            stdout=stdout,
            stderr=stderr,
        )
    except SystemExit as exc:
        pytest.fail(
            "makemigrations --check detected pending changes for the cms app:\n"
            f"  exit code: {exc.code}\n"
            f"  stdout: {stdout.getvalue() or '(empty)'}\n"
            f"  stderr: {stderr.getvalue() or '(empty)'}\n"
            "The cms.models package refactor must produce zero migration diff."
        )
