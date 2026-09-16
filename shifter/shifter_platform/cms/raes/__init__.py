"""CMS-side RAES boundary implementations (issue #1262).

This package holds the concrete, ``cms``-owned implementations of ports
declared in :mod:`shared.raes`. It never imports an ``raes_*`` SDL package --
that stays confined to :mod:`shared.raes.manifest` and
:mod:`shared.raes.runtime_target` (ADR-024). Modules here only import
``shared``/``cms``/``engine``.
"""
