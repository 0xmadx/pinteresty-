// ==========================================
// GHOST USER: Behavioral Biometrics Spoofing
// ==========================================

console.log("[Ghost User] Autonomous behavior script injected and active.");

// --- 1. GHOST MOUSE ---
// Randomly fires mousemove events across the page to simulate a human looking around.
function fireRandomMouseMove() {
    const x = Math.floor(Math.random() * window.innerWidth);
    const y = Math.floor(Math.random() * window.innerHeight);

    const event = new MouseEvent('mousemove', {
        view: window,
        bubbles: true,
        cancelable: true,
        clientX: x,
        clientY: y,
        screenX: x + window.screenX,
        screenY: y + window.screenY
    });

    document.dispatchEvent(event);
    
    // Schedule the next mouse movement randomly between 2s and 8s
    const nextMove = 2000 + Math.random() * 6000;
    setTimeout(fireRandomMouseMove, nextMove);
}

// --- 2. GHOST SCROLL ---
// Randomly scrolls the page up and down by small amounts.
function fireRandomScroll() {
    // 70% chance to scroll down, 30% to scroll up
    const direction = Math.random() > 0.3 ? 1 : -1;
    
    // Scroll distance between 50px and 300px
    const distance = Math.floor(50 + Math.random() * 250) * direction;
    
    window.scrollBy({
        top: distance,
        left: 0,
        behavior: 'smooth'
    });
    
    // Schedule the next scroll randomly between 10s and 30s
    const nextScroll = 10000 + Math.random() * 20000;
    setTimeout(fireRandomScroll, nextScroll);
}

// Start the autonomous behaviors
setTimeout(fireRandomMouseMove, 3000);
setTimeout(fireRandomScroll, 5000);

// --- 3. HUMAN REFRESH RECEIVER ---
// Listens for the signal from background.js to softly refresh the page
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "human_refresh") {
        console.log("[Ghost User] Received human refresh signal! Simulating natural reload...");
        
        // Step 1: Scroll to the very top smoothly
        window.scrollTo({
            top: 0,
            left: 0,
            behavior: 'smooth'
        });

        // Step 2: Wait for scroll to finish (approx 1-2s), then simulate a soft click on the logo or just reload
        setTimeout(() => {
            // Soft reload bypasses hard cache resets and looks more like a natural navigation
            window.location.reload();
        }, 1500 + Math.random() * 1000);
        
        sendResponse({status: "refreshing"});
    }
});
