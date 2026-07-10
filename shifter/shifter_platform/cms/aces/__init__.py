"""CMS-side ACES boundary implementations (issue #1262).

This package holds the concrete, ``cms``-owned implementations of ports
declared in :mod:`shared.aces`. It never imports an ``aces_*`` SDL package --
that stays confined to :mod:`shared.aces.manifest` and
:mod:`shared.aces.runtime_target` (ADR-024). Modules here only import
``shared``/``cms``/``engine``.
"""
