"""Scripted event-load harness for the Shifter portal (#926).

A standalone client that drives a *deployed* Shifter portal over its real
HTTP/websocket contracts, measures client-side latency/error/drop evidence, and
renders a sanitized concurrency-envelope report. The load-generation and
client-measured-evidence core is platform-agnostic; provider-metrics collection
is an optional, swappable adapter (see ``event_load_harness.metrics``).

This package intentionally does NOT import the Shifter Django application: it
runs as an external client against a deployed target, so it stays runnable
without the app installed and portable across deployment platforms.
"""

__version__ = "0.1.0"
