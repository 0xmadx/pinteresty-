// Listen for changes to cookies
chrome.cookies.onChanged.addListener((changeInfo) => {
    const { cookie, removed } = changeInfo;
    
    // Only care about datadome cookie on etsy.com and when it is added/updated
    if (!removed && cookie.domain.includes('etsy.com') && cookie.name === 'datadome') {
        console.log("Detected new DataDome cookie! Syncing to backend...");
        
        syncCookieToBackend(cookie.value);
    }
});

// Function to send the cookie to the local FastAPI server
async function syncCookieToBackend(cookieValue) {
    try {
        const response = await fetch('http://localhost:8000/update-cookie', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ cookie: cookieValue })
        });
        
        if (response.ok) {
            console.log("Successfully synced DataDome cookie to local backend.");
        } else {
            console.error("Failed to sync cookie. Server responded with:", response.status);
        }
    } catch (error) {
        console.error("Failed to sync cookie. Is the local FastAPI server running? Error:", error);
    }
}
