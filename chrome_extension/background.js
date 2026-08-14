// ==========================================
// DYNAMIC PROFILE IDENTIFIER & ROLE
// ==========================================
let PROFILE_ID = "pending_uuid";
let PROFILE_ROLE = "auto";

// Generate or load a unique ID for this specific Chrome profile
chrome.storage.local.get(['profile_id', 'profile_role'], (result) => {
    if (result.profile_id) {
        PROFILE_ID = result.profile_id;
        console.log(`Loaded existing Profile ID: ${PROFILE_ID}`);
    } else {
        // Generate a random ID (e.g. "profile_8a3f91")
        PROFILE_ID = "profile_" + Math.random().toString(36).substr(2, 9);
        chrome.storage.local.set({ profile_id: PROFILE_ID }, () => {
            console.log(`Generated and saved new Profile ID: ${PROFILE_ID}`);
        });
    }
    
    if (result.profile_role) {
        PROFILE_ROLE = result.profile_role;
        console.log(`Loaded existing Profile Role: ${PROFILE_ROLE}`);
    }
});

// Listen for updates from the popup UI
chrome.storage.onChanged.addListener((changes, namespace) => {
    if (namespace === 'local') {
        if (changes.profile_id) {
            PROFILE_ID = changes.profile_id.newValue;
            console.log(`Profile ID updated via UI to: ${PROFILE_ID}`);
        }
        if (changes.profile_role) {
            PROFILE_ROLE = changes.profile_role.newValue;
            console.log(`Profile Role updated via UI to: ${PROFILE_ROLE}`);
        }
    }
});

// Force sync when popup hits Save
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "force_sync") {
        console.log("Forced sync requested via UI.");
        
        let explicitRole = request.profile_role || PROFILE_ROLE;
        let explicitId = request.profile_id || PROFILE_ID;
        let targetDomain = explicitRole === 'pinterest' ? 'pinterest.com' : 'etsy.com';
        
        chrome.cookies.getAll({ domain: targetDomain }, (cookies) => {
            if (cookies && cookies.length > 0) {
                let cookieJson = {};
                cookies.forEach(c => {
                    cookieJson[c.name] = c.value;
                });
                
                let targetPlatform = 'etsy';
                if (explicitRole === 'etsy_private') {
                    targetPlatform = 'etsy_private';
                } else if (explicitRole === 'etsy_public') {
                    targetPlatform = 'etsy';
                } else if (explicitRole === 'pinterest') {
                    targetPlatform = 'pinterest';
                }

                syncCookieToBackend({
                    profile_id: explicitId,
                    cookie: "", 
                    cookie_json: JSON.stringify(cookieJson),
                    platform: targetPlatform,
                    cookie_name: 'all_cookies'
                });
            }
        });
    }
});

// Listen for changes to cookies
chrome.cookies.onChanged.addListener(async (changeInfo) => {
    const { cookie, removed } = changeInfo;

    // --- ETSY COOKIES ---
    if (!removed && cookie.domain.includes('etsy.com')) {
        if (PROFILE_ROLE === 'pinterest') return; // Strict isolation

        const cookies = await chrome.cookies.getAll({ domain: 'etsy.com' });
        const cookieJson = {};
        let dataDomeValue = "";

        cookies.forEach(c => {
            cookieJson[c.name] = c.value;
            if (c.name === 'datadome') dataDomeValue = c.value;
        });

        // Determine destination based on manual role
        let targetPlatform = 'etsy';
        if (PROFILE_ROLE === 'etsy_private') {
            targetPlatform = 'etsy_private';
        } else if (PROFILE_ROLE === 'etsy_public') {
            targetPlatform = 'etsy';
        }

        syncCookieToBackend({
            cookie: dataDomeValue, // Legacy fallback
            cookie_json: cookieJson,
            platform: targetPlatform,
            cookie_name: 'all_cookies'
        });
    }

    // --- PINTEREST COOKIES ---
    if (!removed && cookie.domain.includes('pinterest.com')) {
        if (PROFILE_ROLE === 'etsy_public' || PROFILE_ROLE === 'etsy_private') return; // Strict isolation

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

// Intercept requests to grab x-csrf-token and shop_id
chrome.webRequest.onBeforeSendHeaders.addListener(
    function (details) {
        if (PROFILE_ROLE === 'pinterest' || PROFILE_ROLE === 'etsy_public') return { requestHeaders: details.requestHeaders };

        let csrfToken = null;
        let shopId = null;

        // Find Shop ID in any URL (e.g. /shop/56057851/)
        const match = details.url.match(/\/shop\/(\d+)/);
        if (match) {
            shopId = match[1];
        }

        // Find CSRF token in any request header
        if (details.requestHeaders) {
            for (let i = 0; i < details.requestHeaders.length; ++i) {
                if (details.requestHeaders[i].name.toLowerCase() === 'x-csrf-token') {
                    csrfToken = details.requestHeaders[i].value;
                    break;
                }
            }
        }

        // If we found either of them, sync immediately!
        if (csrfToken || shopId) {
            syncCookieToBackend({
                platform: 'etsy_private',
                shop_id: shopId,
                csrf_token: csrfToken
            });
        }
        return { requestHeaders: details.requestHeaders };
    },
    { urls: ["*://*.etsy.com/*"] },
    ["requestHeaders", "extraHeaders"]
);

// Function to send the payload to the local FastAPI server
async function syncCookieToBackend(payload) {
    payload.user_agent = navigator.userAgent;
    payload.profile_id = PROFILE_ID; // Attach dynamic profile ID

    try {
        const response = await fetch('http://localhost:8000/update-cookie', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer super_secret_key_123'
            },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            console.log(`Successfully synced ${payload.platform} cookies to local backend for ${PROFILE_ID}.`);
        } else {
            console.error("Failed to sync cookies. Server responded with:", response.status);
        }
    } catch (error) {
        console.error("Failed to sync cookies. Is the local FastAPI server running? Error:", error);
    }
}

// ==========================================
// HUMAN-LIKE KEEP-ALIVE SYSTEM
// ==========================================

function scheduleNextRefresh() {
    // Randomize the next refresh between 2.5 and 4.5 minutes
    const randomMinutes = 2.5 + Math.random() * 2.0;
    console.log(`[Keep-Alive] Next refresh scheduled in ${randomMinutes.toFixed(2)} minutes.`);
    chrome.alarms.create("autoRefresh", { delayInMinutes: randomMinutes });
}

// Start the first alarm
scheduleNextRefresh();

chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "autoRefresh") {
        console.log("[Keep-Alive] Alarm triggered! Sending soft-refresh signal to tabs...");

        chrome.tabs.query({ url: ["*://*.etsy.com/*", "*://*.pinterest.com/*"] }, (tabs) => {
            if (tabs.length === 0) {
                console.log("[Keep-Alive] No Etsy or Pinterest tabs open to refresh.");
            } else {
                tabs.forEach((tab) => {
                    console.log(`[Keep-Alive] Requesting human refresh for tab: ${tab.url}`);
                    // Send message to content.js to perform a soft, human-like reload
                    chrome.tabs.sendMessage(tab.id, { action: "human_refresh" }).catch(() => {
                        // Fallback if content script isn't loaded
                        console.log(`[Keep-Alive] Content script not responding on ${tab.url}, falling back to standard reload.`);
                        chrome.tabs.reload(tab.id);
                    });
                });
            }
            
            // Schedule the next randomized refresh
            scheduleNextRefresh();
        });
    }
});
