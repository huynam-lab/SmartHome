const CHATBOT_OPEN_STATE_KEY = "smarthome.chatbotOpen.v1";

export function initializeChatbotShell() {
    const fab = document.getElementById("chatbot-fab");
    const popup = document.getElementById("chatbot-popup");

    if (!fab || !popup) {
        return;
    }

    const readOpenState = () => {
        try {
            return window.sessionStorage.getItem(CHATBOT_OPEN_STATE_KEY) === "1";
        } catch (error) {
            return false;
        }
    };

    const writeOpenState = (isOpen) => {
        try {
            window.sessionStorage.setItem(CHATBOT_OPEN_STATE_KEY, isOpen ? "1" : "0");
        } catch (error) {
            // Ignore storage failures; shell still works.
        }
    };

    const isLocked = () => document.body.classList.contains("auth-locked");

    const syncFabState = () => {
        if (isLocked()) {
            popup.classList.add("is-hidden");
            popup.setAttribute("aria-hidden", "true");
            popup.hidden = true;
            fab.hidden = true;
            fab.setAttribute("aria-expanded", "false");
            fab.setAttribute("aria-label", "Mở chatbot");
            writeOpenState(false);
            return;
        }

        popup.hidden = false;
        fab.hidden = false;
        const isHidden = popup.classList.contains("is-hidden");
        popup.setAttribute("aria-hidden", String(isHidden));
        fab.setAttribute("aria-expanded", String(!isHidden));
        fab.setAttribute("aria-label", isHidden ? "Mở chatbot" : "Ẩn chatbot");
        writeOpenState(!isHidden);
    };

    fab.addEventListener("click", () => {
        if (isLocked()) {
            return;
        }
        popup.classList.toggle("is-hidden");
        syncFabState();
    });

    popup.classList.toggle("is-hidden", !readOpenState());
    syncFabState();

    const observer = new MutationObserver(() => syncFabState());
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
}
