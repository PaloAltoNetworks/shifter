"""Django signals for engine events.

These signals replace SNS/SQS fan-out for cross-app event notification.
Signal receivers in cms and mission_control handle their respective concerns.

Signal kwargs:
    range_status_changed:
        request_id (str), range_id (int), user_id (int),
        new_status (str), previous_status (str), error_message (str|None)

    range_provisioned:
        request_id (str), range_id (int), user_id (int)

    ngfw_status_changed:
        request_id (str), instance_id (str), app_id (str),
        status (str|None), serial_number (str|None), state (dict|None)
"""

import django.dispatch

range_status_changed = django.dispatch.Signal()
range_provisioned = django.dispatch.Signal()
ngfw_status_changed = django.dispatch.Signal()
