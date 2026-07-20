"""Scenario-neutral live-fire escape-validation suite for GCP ranges (issue #1347).

The suite proves, from participant-controlled context inside a live range cell,
that the outer boundary fails closed before the range is trusted for live fire
(ADR-030-R5). The closed machine-readable report contract lives in
:mod:`shared.range_escape`; this package owns the orchestration: the boundary
target inventory, the probe-launch adapter seam, and the runner that aggregates
one-range and multi-range results into the report.
"""
