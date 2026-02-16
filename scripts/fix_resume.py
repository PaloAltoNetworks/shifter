"""One-shot script to fix resume_range and resume_range_by_request_id status updates."""
import sys

path = '/home/atomik/src/shifter/shifter/shifter_platform/cms/services.py'
with open(path, 'r') as f:
    content = f.read()

# First replacement: resume_range()
old1 = (
    '        # Call engine - it will update DB status and trigger ECS task\n'
    '        if not engine_resume_range(request_id):\n'
    '            logger.warning(\n'
    '                "resume_range: engine returned False for range_id=%s",\n'
    '                range_id,\n'
    '            )\n'
    '            raise CMSError("Range cannot be resumed in current state")'
)

new1 = (
    '        # Update CMS status to RESUMING before calling engine (keeps models in sync)\n'
    '        instance.status = ResourceStatus.RESUMING.value\n'
    '        instance.save(update_fields=["status"])\n'
    '\n'
    '        # Call engine - it will update Engine Range status and trigger ECS task\n'
    '        if not engine_resume_range(request_id):\n'
    '            # Revert CMS status on failure\n'
    '            instance.status = ResourceStatus.PAUSED.value\n'
    '            instance.save(update_fields=["status"])\n'
    '            logger.warning(\n'
    '                "resume_range: engine returned False for range_id=%s",\n'
    '                range_id,\n'
    '            )\n'
    '            raise CMSError("Range cannot be resumed in current state")'
)

if old1 not in content:
    print('ERROR: First pattern not found!')
    sys.exit(1)
content = content.replace(old1, new1, 1)
print('First replacement applied (resume_range)')

# Second replacement: resume_range_by_request_id()
old2 = (
    '    try:\n'
    '        # Call engine - it will update DB status and trigger ECS task\n'
    '        if not engine_resume_range(instance.request.request_id):\n'
    '            logger.warning(\n'
    '                "resume_range_by_request_id: engine returned False for request_id=%s",\n'
    '                request_id,\n'
    '            )\n'
    '            raise CMSError("Range cannot be resumed in current state")'
)

new2 = (
    '    try:\n'
    '        # Update CMS status to RESUMING before calling engine (keeps models in sync)\n'
    '        instance.status = ResourceStatus.RESUMING.value\n'
    '        instance.save(update_fields=["status"])\n'
    '\n'
    '        # Call engine - it will update Engine Range status and trigger ECS task\n'
    '        if not engine_resume_range(instance.request.request_id):\n'
    '            # Revert CMS status on failure\n'
    '            instance.status = ResourceStatus.PAUSED.value\n'
    '            instance.save(update_fields=["status"])\n'
    '            logger.warning(\n'
    '                "resume_range_by_request_id: engine returned False for request_id=%s",\n'
    '                request_id,\n'
    '            )\n'
    '            raise CMSError("Range cannot be resumed in current state")'
)

if old2 not in content:
    print('ERROR: Second pattern not found!')
    sys.exit(1)
content = content.replace(old2, new2, 1)
print('Second replacement applied (resume_range_by_request_id)')

with open(path, 'w') as f:
    f.write(content)

print('OK - file written successfully')
