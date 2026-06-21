/**
 * Initializes full screen mode for the application.
 * Attempts to enter fullscreen immediately on load.
 * If rejected due to browser security policies (requiring a user gesture),
 * it registers one-time capture listeners for click, keydown, and touchstart to enter fullscreen
 * on the very first user interaction.
 */
export function initFullscreen() {
    const docEl = document.documentElement;
    const requestFS = docEl.requestFullscreen || 
                      docEl.webkitRequestFullscreen || 
                      docEl.mozRequestFullScreen || 
                      docEl.msRequestFullscreen;

    if (!requestFS) {
        console.warn("Fullscreen API is not supported in this browser.");
        return;
    }

    const enterFullscreen = () => {
        const isCurrentlyFullscreen = document.fullscreenElement || 
                                      document.webkitFullscreenElement || 
                                      document.mozFullScreenElement || 
                                      document.msFullscreenElement;

        if (!isCurrentlyFullscreen) {
            requestFS.call(docEl)
                .then(() => {
                    removeListeners();
                })
                .catch(err => {
                    console.warn("Failed to enter fullscreen via interaction:", err);
                    removeListeners();
                });
        } else {
            removeListeners();
        }
    };

    const removeListeners = () => {
        document.removeEventListener("click", enterFullscreen, true);
        document.removeEventListener("keydown", enterFullscreen, true);
        document.removeEventListener("touchstart", enterFullscreen, true);
    };

    // Try immediately (in case the browser config/kiosk mode allows it)
    requestFS.call(docEl)
        .then(() => {
            console.log("Entered fullscreen immediately on load.");
        })
        .catch(() => {
            // Register interaction listeners for fallback using capture phase (true)
            // to bypass any stopPropagation() calls on child elements.
            document.addEventListener("click", enterFullscreen, true);
            document.addEventListener("keydown", enterFullscreen, true);
            document.addEventListener("touchstart", enterFullscreen, true);
        });
}
