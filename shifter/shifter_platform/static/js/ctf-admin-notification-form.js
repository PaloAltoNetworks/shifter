// CTF admin notification compose form: toggle the schedule field and inject
// the "schedule" action when the form is submitted with a scheduled time.
//
// Extracted from the inline <script> block in
// templates/ctf/admin/notification_form.html so the template stays within
// Sonar's Web:LongJavaScriptCheck limit.

document.getElementById('btn-toggle-schedule').addEventListener('click', function () {
    const group = document.getElementById('schedule-group');
    if (group.classList.contains('d-none')) {
        group.classList.remove('d-none');
        this.textContent = 'Cancel Schedule';
    } else {
        group.classList.add('d-none');
        this.textContent = 'Schedule';
    }
});

document.querySelector('form').addEventListener('submit', function (e) {
    const scheduleGroup = document.getElementById('schedule-group');
    if (!scheduleGroup.classList.contains('d-none')) {
        const actionInput = document.querySelector('button[name="action"][value="send_now"]');
        if (e.submitter === actionInput) return;
        const hiddenInput = document.createElement('input');
        hiddenInput.type = 'hidden';
        hiddenInput.name = 'action';
        hiddenInput.value = 'schedule';
        this.appendChild(hiddenInput);
    }
});
