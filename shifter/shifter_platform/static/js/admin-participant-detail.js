/* global initScoreTimeline */
// Admin participant-detail page actions: resend invite, disqualify.
// Extracted from the inline `<script>` block in
// templates/ctf/admin/participant_detail.html so the template stays
// within Sonar Web:LongJavaScriptCheck limits.

function resendInvite(participantId, csrfToken) {
    if (!confirm('Resend invitation email to this participant?')) return;

    fetch('/ctf/api/participants/' + participantId + '/resend-invite/', {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
            'Content-Type': 'application/json'
        }
    })
    .then(function(response) { return response.json(); })
    .then(function(data) {
        if (data.success) {
            alert('Invitation resent successfully.');
            location.reload();
        } else {
            alert('Error: ' + (data.error || 'Failed to resend invite'));
        }
    })
    .catch(function(err) {
        alert('Error resending invite: ' + err.message);
    });
}

function disqualifyParticipant(_participantId) {
    if (!confirm('Are you sure you want to disqualify this participant? This action cannot be undone.')) return;
    // Disqualify API endpoint not yet implemented.
    alert('Disqualify functionality not yet implemented via API.');
}

function initParticipantTimeline(participantId) {
    initScoreTimeline('score-timeline-chart', '/ctf/api/participants/' + participantId + '/score-timeline/');
}

window.resendInvite = resendInvite;
window.disqualifyParticipant = disqualifyParticipant;
window.initParticipantTimeline = initParticipantTimeline;
