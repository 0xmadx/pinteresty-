// ==========================================
// DYNAMIC PROFILE IDENTIFIER & ROLE
// ==========================================
let PROFILE_ID = "pending_uuid";
let PROFILE_ROLE = null;

// The role answers ONE question: what is this browser's Etsy login — a buyer or the
// seller? That is the only genuinely ambiguous thing, because both produce cookies on
// etsy.com and only the operator knows which account is signed in.
//
// It deliberately does NOT decide which sites may sync. Etsy and Pinterest are
// different domains with separate cookie jars; a browser with both open has no
// ambiguity to resolve, so Pinterest always syncs. The old model made the role a
// global gate, which meant one browser could feed only one platform — the operator
// hit this immediately with Etsy and Pinterest open side by side.
//
// What the old "auto" default did, and why it is gone rather than re-routed:
// it matched no branch, so cookies filed under `etsy` while the seller's csrf/shop_id
// filed under `etsy_private` — splitting one identity so neither half could
// authenticate. And a browser signed in AS THE SELLER had its seller cookies filed
// into the PUBLIC pool and drawn for competitor scraping: D-29 inverted, with the one
// irreplaceable account doing the risky work. An undeclared Etsy login is not
// guessable, so it is refused.
const ETSY_TIERS = ["etsy_public", "etsy_private"];

/** The declared Etsy tier, or null if the operator has not said. */
function etsyTier() {
    return ETSY_TIERS.includes(PROFILE_ROLE) ? PROFILE_ROLE : null;
}

/** Redis platform for a declared tier. Total over ETSY_TIERS — no fall-through. */
function etsyPlatform(tier) {
    return tier === 'etsy_private' ? 'etsy_private' : 'etsy';
}

function warnTierUnset() {
    console.warn(
        `[Scraper] Not syncing Etsy cookies: this profile's Etsy account type is ` +
        `"${PROFILE_ROLE}". Open the extension popup and say whether it is signed in ` +
        `as a buyer or as your seller account. Guessing could file your seller ` +
        `session into the public scraping pool (D-29). Pinterest is unaffected and ` +
        `syncs normally.`
    );
}

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
        
        const explicitRole = request.profile_role || PROFILE_ROLE;
        const explicitId = request.profile_id || PROFILE_ID;
        const tier = ETSY_TIERS.includes(explicitRole) ? explicitRole : null;

        // Sync every domain this browser can speak for, not just one. Picking a single
        // target is what forced the operator to choose between Etsy and Pinterest.
        const jobs = [{ domain: 'pinterest.com', platform: 'pinterest' }];
        if (tier) {
            jobs.push({ domain: 'etsy.com', platform: etsyPlatform(tier) });
        } else {
            warnTierUnset();
        }

        jobs.forEach(({ domain, platform }) => {
            chrome.cookies.getAll({ domain }, (cookies) => {
                if (!cookies || cookies.length === 0) return;   // not signed in here
                const cookieJson = {};
                cookies.forEach(c => { cookieJson[c.name] = c.value; });

                syncCookieToBackend({
                    profile_id: explicitId,
                    cookie: "",
                    // The OBJECT, not JSON.stringify(...). The Go server re-marshals
                    // whatever it receives, so a string here arrives in Redis as a
                    // quoted JSON string; Python then json.loads() it into a str, the
                    // isinstance(dict) check fails, and ZERO cookies get injected with
                    // no error anywhere. That made this Save button produce profiles
                    // that looked valid and could never authenticate (S-3).
                    cookie_json: cookieJson,
                    platform: platform,
                    cookie_name: 'all_cookies'
                });
            });
        });
    }
});

// Listen for changes to cookies
chrome.cookies.onChanged.addListener(async (changeInfo) => {
    const { cookie, removed } = changeInfo;

    // --- ETSY COOKIES ---
    if (!removed && cookie.domain.includes('etsy.com')) {
        const tier = etsyTier();
        if (!tier) { warnTierUnset(); return; }

        const cookies = await chrome.cookies.getAll({ domain: 'etsy.com' });
        const cookieJson = {};
        let dataDomeValue = "";

        cookies.forEach(c => {
            cookieJson[c.name] = c.value;
            if (c.name === 'datadome') dataDomeValue = c.value;
        });

        const targetPlatform = etsyPlatform(tier);

        syncCookieToBackend({
            cookie: dataDomeValue, // Legacy fallback
            cookie_json: cookieJson,
            platform: targetPlatform,
            cookie_name: 'all_cookies'
        });
    }

    // --- PINTEREST COOKIES ---
    if (!removed && cookie.domain.includes('pinterest.com')) {
        // No tier check and no isolation guard: pinterest.com cookies can only ever be
        // Pinterest cookies. The old guard blocked this whenever an Etsy tier was set,
        // which is why one browser could not serve both sites.
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
        // Only a declared seller profile may emit seller tokens. Previously this
        // early-returned for two named roles and therefore RAN under the unset "auto"
        // default — sending csrf/shop_id to `etsy_private` while that same profile's
        // cookies went to `etsy`. Positive test, not a blocklist: anything that is not
        // explicitly the seller is excluded by construction.
        if (etsyTier() !== 'etsy_private') return { requestHeaders: details.requestHeaders };

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
