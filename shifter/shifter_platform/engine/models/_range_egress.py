"""Range egress-mode field vocabulary (PLAT-238).

Kept out of ``_range.py`` so that module stays within the file-length budget.
``RANGE_EGRESS_MODE_CHOICES`` is the Django ``choices`` for the pinned effective
range egress mode, built from the canonical
``installation.range_egress.RangeEgressMode`` StrEnum (which is not a Django
``TextChoices`` and so exposes no ``.choices``). Kept in lockstep with the enum
so a new canonical mode is a one-line update here.
"""

from installation.range_egress import RangeEgressMode

RANGE_EGRESS_MODE_CHOICES = tuple((mode.value, mode.value) for mode in RangeEgressMode)
#: Compatibility default: inherit the deployment baseline.
RANGE_EGRESS_DEFAULT = RangeEgressMode.STATUS_QUO.value
