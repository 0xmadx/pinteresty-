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
        
        // An empty tier is a legitimate answer — it means "this browser is not signed
        // in to Etsy", and Pinterest still syncs. What is NOT allowed is guessing,
        // which is what the old "auto" default did (S-1 / D-29).
        if (newName) {
            chrome.storage.local.set({
                profile_id: newName,
                profile_role: newRole
            }, () => {
                // Force a sync immediately so we don't have to wait for a cookie to change
                chrome.runtime.sendMessage({ action: "force_sync", profile_id: newName, profile_role: newRole });
                statusDiv.textContent = newRole
                    ? "Saved — syncing Etsy + Pinterest."
                    : "Saved — Pinterest only (no Etsy account set).";
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
