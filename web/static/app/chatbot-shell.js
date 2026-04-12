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

    const syncFabState = () => {
        const isHidden = popup.classList.contains("is-hidden");
        popup.setAttribute("aria-hidden", String(isHidden));
        fab.setAttribute("aria-expanded", String(!isHidden));
        fab.setAttribute("aria-label", isHidden ? "Mở chatbot" : "Ẩn chatbot");
        writeOpenState(!isHidden);
    };

    fab.addEventListener("click", () => {
        popup.classList.toggle("is-hidden");
        syncFabState();
    });

    popup.classList.toggle("is-hidden", !readOpenState());
    syncFabState();
}
