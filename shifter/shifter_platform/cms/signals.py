"""CMS signals for cross-domain event propagation.

Signals defined here may be received by any layer that depends on CMS.
"""

from django.dispatch import Signal

# Fired after updating RangeInstance.status in cms/handlers.py.
# Kwargs: range_instance_id (int), new_status (str), previous_status (str)
range_status_changed = Signal()
