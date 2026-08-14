document.addEventListener('DOMContentLoaded', () => {
    const profileNameInput = document.getElementById('profileName');
    const profileRoleSelect = document.getElementById('profileRole');
    const saveBtn = document.getElementById('saveBtn');
    const statusDiv = document.getElementById('status');

    // Load existing profile name and role
    chrome.storage.local.get(['profile_id', 'profile_role'], (result) => {
        if (result.profile_id) {
            profileNameInput.value = result.profile_id;
        } else {
            // Default generated ID if none exists yet
            profileNameInput.value = "profile_" + Math.random().toString(36).substr(2, 9);
        }

        if (result.profile_role) {
            profileRoleSelect.value = result.profile_role;
        }
    });

    // Save profile name and role
    saveBtn.addEventListener('click', () => {
        const newName = profileNameInput.value.trim();
        const newRole = profileRoleSelect.value;
        
        // A role is required. Saving without one used to store "auto", which routed
        // cookies and seller tokens to different pools and could file a seller session
        // into the public scraping pool (S-1 / D-29).
        if (newName && !newRole) {
            statusDiv.textContent = "Pick an account role first.";
            statusDiv.style.color = "red";
            setTimeout(() => {
                statusDiv.textContent = "";
                statusDiv.style.color = "green";
            }, 3000);
            return;
        }

        if (newName) {
            chrome.storage.local.set({
                profile_id: newName,
                profile_role: newRole
            }, () => {
                // Force a sync immediately so we don't have to wait for a cookie to change
                chrome.runtime.sendMessage({ action: "force_sync", profile_id: newName, profile_role: newRole });
                statusDiv.textContent = "Saved! Refresh Etsy tab to sync.";
                setTimeout(() => {
                    statusDiv.textContent = "";
                }, 3000);
            });
        } else {
            statusDiv.textContent = "Name cannot be empty.";
            statusDiv.style.color = "red";
            setTimeout(() => {
                statusDiv.textContent = "";
                statusDiv.style.color = "green";
            }, 3000);
        }
    });
});
