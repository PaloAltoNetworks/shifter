"""Shifter RAES contract surface.

This package holds Shifter's RAES (Adversarial Cyber Exercise System) contract
artifacts. The first artifact (issue #1261) is the ``provisioning-only`` backend
manifest published in :mod:`shared.raes.manifest`; runtime-safe profile and
operation-sidecar constants live in :mod:`shared.raes.contracts`.

Nothing is imported eagerly here on purpose. The manifest builder
(:mod:`shared.raes.manifest`) and the RuntimeTarget adapter
(:mod:`shared.raes.runtime_target`, #1262) import the ``raes`` tooling,
which is a ``[project]`` runtime dependency since #1262; keeping
``import shared.raes`` inert means other ``shared.raes`` submodules (status
projection, participant-runtime sidecar persistence, ...) never pull that
tooling in just because they live in the same package.
"""
