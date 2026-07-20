"""Shifter ACES contract surface.

This package holds Shifter's ACES (Adversarial Cyber Exercise System) contract
artifacts. The first artifact (issue #1261) is the ``provisioning-only`` backend
manifest published in :mod:`shared.aces.manifest`; runtime-safe profile and
operation-sidecar constants live in :mod:`shared.aces.contracts`.

Nothing is imported eagerly here on purpose. The manifest builder
(:mod:`shared.aces.manifest`) and the RuntimeTarget adapter
(:mod:`shared.aces.runtime_target`, #1262) import the ``aces-sdl`` tooling,
which is a ``[project]`` runtime dependency since #1262; keeping
``import shared.aces`` inert means other ``shared.aces`` submodules (status
projection, participant-runtime sidecar persistence, ...) never pull that
tooling in just because they live in the same package.
"""
