// Listen for changes to cookies
chrome.cookies.onChanged.addListener(async (changeInfo) => {
    const { cookie, removed } = changeInfo;
    
    // Etsy: DataDome cookie
    if (!removed && cookie.domain.includes('etsy.com') && cookie.name === 'datadome') {
        console.log("Detected new DataDome cookie for Etsy! Syncing to backend...");
        syncCookieToBackend({ cookie: cookie.value, platform: 'etsy', cookie_name: 'datadome' });
    }
    
    // Pinterest: Sync all cookies
    if (!removed && cookie.domain.includes('pinterest.com')) {
        console.log(`Detected new cookie for Pinterest: ${cookie.name}! Syncing all Pinterest cookies to backend...`);
        // Fetch all cookies for pinterest.com
        const cookies = await chrome.cookies.getAll({ domain: 'pinterest.com' });
        const cookieString = cookies.map(c => `${c.name}=${c.value}`).join('; ');
        
        // Also build a JSON object for direct usage if needed
        const cookieJson = {};
        cookies.forEach(c => { cookieJson[c.name] = c.value });
        
        syncCookieToBackend({ 
            cookie: cookieString, 
            cookie_json: cookieJson,
            platform: 'pinterest', 
            cookie_name: 'all_cookies' 
        });
    }
});

// Function to send the payload to the local FastAPI server
async function syncCookieToBackend(payload) {
    try {
        const response = await fetch('http://localhost:8000/update-cookie', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });
        
        if (response.ok) {
            console.log(`Successfully synced ${payload.platform} cookies to local backend.`);
        } else {
            console.error("Failed to sync cookies. Server responded with:", response.status);
        }
    } catch (error) {
        console.error("Failed to sync cookies. Is the local FastAPI server running? Error:", error);
    }
}

// ==========================================
// AUTO-REFRESH "KEEP-ALIVE" SYSTEM
// ==========================================
// DataDome cookies expire quickly. This alarm fires every 4 minutes.
chrome.alarms.create("autoRefresh", {
    periodInMinutes: 4.0
});

chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "autoRefresh") {
        console.log("[Keep-Alive] Alarm triggered! Searching for Etsy and Pinterest tabs to refresh...");
        
        // Find all open tabs for Etsy and Pinterest
        chrome.tabs.query({ url: ["*://*.etsy.com/*", "*://*.pinterest.com/*"] }, (tabs) => {
            if (tabs.length === 0) {
                console.log("[Keep-Alive] No Etsy or Pinterest tabs open to refresh.");
                return;
            }
            
            // Reload each tab to trick DataDome into issuing a fresh cookie
            tabs.forEach((tab) => {
                console.log(`[Keep-Alive] Auto-refreshing tab: ${tab.url}`);
                chrome.tabs.reload(tab.id);
            });
        });
    }
});
