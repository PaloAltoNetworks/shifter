"""Range-dependent functional smoke for the participant journey (#987).

Drives the two flows that a TCP-reachability probe cannot prove — an interactive
terminal that exchanges real data with a range host, and a Guacamole session that
reaches a client-level connection — against a positively selected, known-up
example range on a deployed tenant.

On demand only: nothing here is wired into deploy gating.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
