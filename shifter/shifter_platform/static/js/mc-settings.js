// Mission Control settings page: delete-account confirmation modal.
//
// Extracted from the inline <script> block in
// templates/mission_control/settings.html so the template stays within
// Sonar's Web:LongJavaScriptCheck limit.

// Delete account modal logic
const deleteBtn = document.getElementById('delete-account-btn');
const deleteModal = document.getElementById('delete-modal');
const cancelBtn = document.getElementById('cancel-delete-btn');
const confirmInput = document.getElementById('delete-confirm-input');
const confirmBtn = document.getElementById('confirm-delete-btn');

deleteBtn.addEventListener('click', () => {
    deleteModal.style.display = 'flex';
});

cancelBtn.addEventListener('click', () => {
    deleteModal.style.display = 'none';
    confirmInput.value = '';
    confirmBtn.disabled = true;
});

confirmInput.addEventListener('input', () => {
    confirmBtn.disabled = confirmInput.value !== 'DELETE';
});
