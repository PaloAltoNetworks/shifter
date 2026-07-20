"""Production-path quality-ownership contract package (#1530, GEN-002).

Single source of truth for ``.github/quality-path-filters.yaml``. Consumed by
``scripts/quality_ownership/classify_paths.py`` (the ``_quality.yml`` ``paths``
job) and by ``scripts/adr_guard/adr_guard.py`` (the ci-level conformance
check). There is no second implementation of the schema.
"""
