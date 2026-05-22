import { app } from "./core.js";
import {
    escapeHtml,
    buildDedupeKey,
    formatTime,
    normalizeMessageText,
} from "./utils.js";

export async function registerPwaServiceWorker() {
    if (!("serviceWorker" in navigator)) {
        return;
    }

    try {
        const registration = await navigator.serviceWorker.register("/service-worker.js", { scope: "/" });
        registration.update().catch(() => { });
    } catch (error) {
        console.warn("[pwa] service worker registration failed", error);
    }
}

function setFeedback(element, text = "", mode = "error") {
    if (!element) {
        return;
    }
    element.textContent = text;
    element.classList.toggle("is-success", mode === "success");
}

function _buildChatRowHtml(safeRole, normalizedText, ts) {
    const meta = app.constants.CHAT_ROLE_META[safeRole];
    return `
        ${safeRole === "user" ? "" : `<div class="chat-avatar">${meta.avatar}</div>`}
        <div class="chat-bubble-wrap">
            <div class="chat-bubble">${escapeHtml(normalizedText)}</div>
            <div class="chat-meta">
                <span>${escapeHtml(meta.label)}</span>
                <span>•</span>
                <time>${escapeHtml(formatTime(ts))}</time>
            </div>
        </div>
        ${safeRole === "user" ? `<div class="chat-avatar">${meta.avatar}</div>` : ""}
    `;
}

function shouldKeepChatEntry(entry) {
    const safeRole = app.constants.CHAT_ROLE_META[entry?.role] ? entry.role : "system";
    const isError = Boolean(entry?.isError);
    return safeRole !== "system" && !isError;
}

function readPersistedChatHistory() {
    try {
        const raw = window.sessionStorage.getItem(app.constants.CHAT_HISTORY_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed.filter(shouldKeepChatEntry) : [];
    } catch (error) {
        console.warn("[chat] failed to read persisted history", error);
        return [];
    }
}

function writePersistedChatHistory(messages) {
    try {
        window.sessionStorage.setItem(
            app.constants.CHAT_HISTORY_STORAGE_KEY,
            JSON.stringify(
                Array.isArray(messages)
                    ? messages.filter(shouldKeepChatEntry).slice(-app.constants.CHAT_HISTORY_LIMIT)
                    : []
            )
        );
    } catch (error) {
        console.warn("[chat] failed to persist history", error);
    }
}

function persistChatMessage(entry) {
    const normalizedText = String(entry?.text || "").trim();
    if (!normalizedText) {
        return;
    }
    if (!shouldKeepChatEntry(entry)) {
        return;
    }

    const safeRole = app.constants.CHAT_ROLE_META[entry?.role] ? entry.role : "system";
    const ts = Number(entry?.ts) || Date.now();
    const dedupeKey = buildDedupeKey(
        safeRole,
        normalizedText,
        entry?.messageId || entry?.requestId || entry?.fingerprint || "local"
    );

    const existing = readPersistedChatHistory();
    if (existing.some((item) => String(item?.dedupeKey || "") === dedupeKey)) {
        return;
    }

    existing.push({
        role: safeRole,
        text: normalizedText,
        ts,
        isError: Boolean(entry?.isError),
        messageId: String(entry?.messageId || "").trim(),
        requestId: String(entry?.requestId || "").trim(),
        fingerprint: String(entry?.fingerprint || "").trim(),
        dedupeKey,
    });
    writePersistedChatHistory(existing);
}

function upsertPersistedChatMessage(entry) {
    const normalizedText = String(entry?.text || "").trim();
    if (!normalizedText) {
        return;
    }
    if (!shouldKeepChatEntry(entry)) {
        return;
    }

    const safeRole = app.constants.CHAT_ROLE_META[entry?.role] ? entry.role : "system";
    const ts = Number(entry?.ts) || Date.now();
    const dedupeKey = buildDedupeKey(
        safeRole,
        normalizedText,
        entry?.messageId || entry?.requestId || entry?.fingerprint || "local"
    );

    const existing = readPersistedChatHistory();
    const messageId = String(entry?.messageId || "").trim();
    const targetIndex = messageId
        ? existing.findIndex((item) => String(item?.messageId || "") === messageId)
        : existing.findIndex((item) => String(item?.dedupeKey || "") === dedupeKey);

    const nextEntry = {
        role: safeRole,
        text: normalizedText,
        ts,
        isError: Boolean(entry?.isError),
        messageId,
        requestId: String(entry?.requestId || "").trim(),
        fingerprint: String(entry?.fingerprint || "").trim(),
        dedupeKey,
    };

    if (targetIndex >= 0) {
        existing[targetIndex] = nextEntry;
    } else if (!existing.some((item) => String(item?.dedupeKey || "") === dedupeKey)) {
        existing.push(nextEntry);
    }

    writePersistedChatHistory(existing);
}

export function setAuthFeedback(text = "", mode = "error") {
    setFeedback(app.dom.authErrorEl, text, mode);
}

export function setPasswordFeedback(text = "", mode = "error") {
    setFeedback(app.dom.passwordFormStatusEl, text, mode);
}

export function setIrLearnModalFeedback(text = "", mode = "error") {
    setFeedback(app.dom.irLearnModalStatusEl, text, mode);
}

export function setAddDeviceFeedback(text = "", mode = "error") {
    setFeedback(app.dom.addDeviceModalStatusEl, text, mode);
}

export function setAddFunctionButtonFeedback(text = "", mode = "error") {
    setFeedback(app.dom.addFunctionButtonStatusEl, text, mode);
}

export function setDeviceScheduleFeedback(text = "", mode = "error") {
    setFeedback(app.dom.deviceScheduleModalStatusEl, text, mode);
}

export function setAddCameraFeedback(text = "", mode = "error") {
    setFeedback(app.dom.addCameraModalStatusEl, text, mode);
}

export function markUiReady() {
    document.body.classList.remove("app-preboot");
}

export function setAuthMode(mode = "login") {
    app.state.authMode = mode === "register" ? "register" : "login";
    const isRegisterMode = app.state.authMode === "register";

    app.dom.authLoginTabEl?.classList.toggle("is-active", !isRegisterMode);
    app.dom.authRegisterTabEl?.classList.toggle("is-active", isRegisterMode);
    app.dom.authRegisterTabEl?.classList.remove("is-hidden");
    app.dom.authLoginTabEl?.setAttribute("aria-selected", String(!isRegisterMode));
    app.dom.authRegisterTabEl?.setAttribute("aria-selected", String(isRegisterMode));
    app.dom.authJetsonFieldEl?.classList.toggle("is-hidden", !isRegisterMode);

    if (app.dom.authJetsonIdEl) {
        app.dom.authJetsonIdEl.required = isRegisterMode;
        if (!isRegisterMode) {
            app.dom.authJetsonIdEl.value = "";
        }
    }

    if (app.dom.authSubmitBtnEl) {
        app.dom.authSubmitBtnEl.textContent = isRegisterMode ? "Đăng ký tài khoản" : "Đăng nhập";
    }

    if (app.dom.authFormNoteEl) {
        app.dom.authFormNoteEl.textContent = isRegisterMode
            ? "Đăng ký tài khoản mới và nhập mã Jetson để liên kết thiết bị."
            : "Đăng nhập để mở quyền điều khiển thiết bị.";
    }

    setAuthFeedback("");
}

export function updateAuthChip(text) {
    if (app.dom.authChipTextEl) {
        app.dom.authChipTextEl.textContent = text;
    }
}

export function positionSettingsMenu() {
    if (!app.dom.settingsBtnEl || !app.dom.settingsMenuEl) {
        return;
    }
    app.dom.settingsMenuEl.style.removeProperty("width");
    app.dom.settingsMenuEl.style.removeProperty("--settings-menu-left");
    app.dom.settingsMenuEl.style.removeProperty("--settings-menu-top");
}

function updatePasswordToggle(button, input, isVisible) {
    if (!button || !input) {
        return;
    }
    input.type = isVisible ? "text" : "password";
    button.classList.toggle("is-visible", isVisible);
    button.setAttribute("aria-pressed", String(isVisible));
    button.setAttribute("aria-label", isVisible ? "Ẩn mật khẩu" : "Hiện mật khẩu");
}

export function initPasswordVisibilityToggles() {
    document.querySelectorAll("[data-password-toggle]").forEach((button) => {
        const targetId = button.getAttribute("data-password-target");
        if (!targetId) {
            return;
        }
        const input = document.getElementById(targetId);
        updatePasswordToggle(button, input, false);
        button.addEventListener("click", () => {
            updatePasswordToggle(button, input, input?.type === "password");
        });
    });
}

export function resetPasswordVisibility(scope = document) {
    scope.querySelectorAll?.("[data-password-toggle]").forEach((button) => {
        const targetId = button.getAttribute("data-password-target");
        if (!targetId) {
            return;
        }
        const input = document.getElementById(targetId);
        updatePasswordToggle(button, input, false);
    });
}

export function closeSettingsMenu() {
    app.dom.settingsMenuEl?.classList.remove("is-open");
    app.dom.settingsBtnEl?.setAttribute("aria-expanded", "false");
    app.dom.settingsMenuEl?.setAttribute("aria-hidden", "true");
}

export function openSettingsMenu() {
    if (!app.state.isAuthenticated) {
        return;
    }
    positionSettingsMenu();
    app.dom.settingsMenuEl?.classList.add("is-open");
    app.dom.settingsBtnEl?.setAttribute("aria-expanded", "true");
    app.dom.settingsMenuEl?.setAttribute("aria-hidden", "false");
}

export function toggleSettingsMenu() {
    if (app.dom.settingsMenuEl?.classList.contains("is-open")) {
        closeSettingsMenu();
        return;
    }
    openSettingsMenu();
}

export function openPasswordModal() {
    if (!app.state.isAuthenticated) {
        return;
    }
    closeSettingsMenu();
    setPasswordFeedback("");
    app.dom.passwordFormEl?.reset();
    resetPasswordVisibility(app.dom.passwordFormEl);
    app.dom.passwordModalEl?.classList.add("is-visible");
    app.dom.passwordModalEl?.setAttribute("aria-hidden", "false");
    window.setTimeout(() => app.dom.currentPasswordEl?.focus(), 0);
}

export function closePasswordModal() {
    app.dom.passwordModalEl?.classList.remove("is-visible");
    app.dom.passwordModalEl?.setAttribute("aria-hidden", "true");
    app.dom.passwordFormEl?.reset();
    resetPasswordVisibility(app.dom.passwordFormEl);
    setPasswordFeedback("");
}

export function closeDeviceMenus() {
    document.querySelectorAll("[data-device-id].is-menu-open").forEach((card) => {
        card.classList.remove("is-menu-open");
    });
    document.querySelectorAll("[data-device-menu]").forEach((menu) => {
        menu.classList.remove("is-open");
        menu.setAttribute("aria-hidden", "true");
    });
    document.querySelectorAll("[data-device-menu-btn]").forEach((button) => {
        button.setAttribute("aria-expanded", "false");
    });
}

export function toggleDeviceMenu(button) {
    const anchor = button?.closest("[data-device-menu-anchor]");
    const menu = anchor?.querySelector("[data-device-menu]");
    const card = button?.closest("[data-device-id]");
    if (!button || !menu) {
        return;
    }
    const willOpen = !menu.classList.contains("is-open");
    closeDeviceMenus();
    if (!willOpen) {
        return;
    }
    card?.classList.add("is-menu-open");
    menu.classList.add("is-open");
    menu.setAttribute("aria-hidden", "false");
    button.setAttribute("aria-expanded", "true");
}

export function setControlLockState(locked) {
    document.body.classList.toggle("auth-locked", locked);
    app.dom.appShellEl?.classList.toggle("is-locked", locked);
    app.dom.appShellEl?.setAttribute("aria-hidden", String(locked));
    app.dom.authOverlayEl?.classList.toggle("is-visible", locked);
    app.dom.authOverlayEl?.setAttribute("aria-hidden", String(!locked));

    if (app.dom.reloadBtnEl) app.dom.reloadBtnEl.disabled = locked;
    if (app.dom.micBtnEl) app.dom.micBtnEl.disabled = locked || app.state.isSendingChat;
    if (app.dom.learnCommandBtnEl) app.dom.learnCommandBtnEl.disabled = locked || app.state.isLearningIr;
    if (app.dom.addDeviceBtnEl) app.dom.addDeviceBtnEl.disabled = locked || app.state.isAddDeviceSubmitting;
    if (app.dom.deviceControlBackBtnEl) app.dom.deviceControlBackBtnEl.disabled = locked;
    if (app.dom.deviceScheduleTriggerBtnEl) app.dom.deviceScheduleTriggerBtnEl.disabled = locked || app.state.isScheduleSubmitting;
    if (app.dom.addFunctionTriggerBtnEl) app.dom.addFunctionTriggerBtnEl.disabled = locked;
    if (app.dom.irStartBtnEl) app.dom.irStartBtnEl.disabled = locked || app.state.isLearningIr;
    if (app.dom.irCancelBtnEl) app.dom.irCancelBtnEl.disabled = locked || app.state.isLearningIr;
    if (app.dom.addDeviceSubmitBtnEl) app.dom.addDeviceSubmitBtnEl.disabled = locked || app.state.isAddDeviceSubmitting;
    if (app.dom.addDeviceCancelBtnEl) app.dom.addDeviceCancelBtnEl.disabled = locked || app.state.isAddDeviceSubmitting;
    if (app.dom.addFunctionButtonSubmitBtnEl) {
        app.dom.addFunctionButtonSubmitBtnEl.disabled = locked;
    }
    if (app.dom.addFunctionButtonCancelBtnEl) {
        app.dom.addFunctionButtonCancelBtnEl.disabled = locked;
    }
    if (app.dom.deviceScheduleSubmitBtnEl) {
        app.dom.deviceScheduleSubmitBtnEl.disabled = locked || app.state.isScheduleSubmitting;
    }
    if (app.dom.deviceScheduleCancelBtnEl) {
        app.dom.deviceScheduleCancelBtnEl.disabled = locked || app.state.isScheduleSubmitting;
    }

    if (locked) {
        window.setTimeout(() => app.dom.authEmailEl?.focus(), 0);
    }
}

export function setSummaryText(text) {
    if (app.dom.summaryTextEl) {
        app.dom.summaryTextEl.textContent = text;
    }
}

export function setIrLearnStatus(text = "", mode = "error") {
    setIrLearnModalFeedback(text, mode);
}

export function setChatStatus(text, mode = "live") {
    if (app.dom.chatStatusTextEl) {
        app.dom.chatStatusTextEl.textContent = text;
    }
    if (!app.dom.chatStatusBannerEl) {
        return;
    }
    app.dom.chatStatusBannerEl.className = "chat-status-banner";
    if (mode === "error") {
        app.dom.chatStatusBannerEl.classList.add("is-error");
        return;
    }
    if (mode === "processing") {
        app.dom.chatStatusBannerEl.classList.add("is-processing");
        return;
    }
    app.dom.chatStatusBannerEl.classList.add("is-live");
}

export function setVoiceUiState({ listening = false, text = "Chạm để bắt đầu nói" } = {}) {
    app.state.isListening = listening;
    if (app.dom.voiceStatusTextEl) {
        app.dom.voiceStatusTextEl.textContent = text;
    }
    if (!app.dom.micBtnEl) {
        return;
    }
    app.dom.micBtnEl.classList.toggle("is-listening", listening);
    const iconEl = app.dom.micBtnEl.querySelector(".icon-btn-symbol");
    if (iconEl) {
        iconEl.textContent = listening ? "⏹️" : "🎙️";
    }
    app.dom.micBtnEl.setAttribute("aria-label", listening ? "Dừng ghi âm" : "Bắt đầu ghi âm");
}

export function scrollChatToBottom() {
    window.requestAnimationFrame(() => {
        app.dom.chatMessagesEl?.scrollTo({
            top: app.dom.chatMessagesEl.scrollHeight,
            behavior: "smooth",
        });
    });
}

export function ensureChatEmptyStateRemoved() {
    const emptyEl = app.dom.chatMessagesEl?.querySelector(".chat-empty");
    if (emptyEl) {
        emptyEl.remove();
    }
}

export function showChatEmptyState() {
    if (!app.dom.chatMessagesEl || app.dom.chatMessagesEl.children.length > 0) {
        return;
    }
    app.dom.chatMessagesEl.innerHTML = `
        <div class="chat-empty">
            <div>
                <h3>Smart Home AI</h3>
                <p class="section-desc">Chạm nút micro để nói lệnh. Khi nhận diện xong, hệ thống sẽ tự gửi về Jetson và hiển thị phản hồi.</p>
            </div>
        </div>
    `;
}

export function hydrateChatHistory() {
    if (!app.dom.chatMessagesEl) {
        return false;
    }

    const seenKeys = new Set();
    const history = readPersistedChatHistory().filter((entry) => {
        const dedupeKey = buildDedupeKey(
            app.constants.CHAT_ROLE_META[entry?.role] ? entry.role : "system",
            String(entry?.text || "").trim(),
            entry?.messageId || entry?.requestId || entry?.fingerprint || "local"
        );
        if (seenKeys.has(dedupeKey)) {
            return false;
        }
        seenKeys.add(dedupeKey);
        return true;
    });
    if (!history.length) {
        return false;
    }

    app.dom.chatMessagesEl.innerHTML = "";
    app.state.renderedMessageKeys.clear();

    history.forEach((entry) => {
        const dedupeKey = buildDedupeKey(
            app.constants.CHAT_ROLE_META[entry?.role] ? entry.role : "system",
            String(entry?.text || "").trim(),
            entry?.messageId || entry?.requestId || entry?.fingerprint || "local"
        );
        app.state.renderedMessageKeys.add(dedupeKey);

        const rowEl = document.createElement("div");
        const safeRole = app.constants.CHAT_ROLE_META[entry?.role] ? entry.role : "system";
        rowEl.className = `chat-row role-${safeRole}${entry?.isError ? " is-error" : ""}`;
        if (entry?.messageId) {
            rowEl.dataset.messageId = entry.messageId;
        }
        rowEl.innerHTML = _buildChatRowHtml(safeRole, String(entry?.text || "").trim(), Number(entry?.ts) || Date.now());
        app.dom.chatMessagesEl.appendChild(rowEl);
    });

    app.state.hasShownWelcomeMessage = history.some((entry) => String(entry?.fingerprint || "") === "welcome-message");
    scrollChatToBottom();
    return true;
}

export function clearPersistedChatHistory() {
    try {
        window.sessionStorage.removeItem(app.constants.CHAT_HISTORY_STORAGE_KEY);
        window.localStorage.removeItem(app.constants.CHAT_HISTORY_STORAGE_KEY);
    } catch (error) {
        console.warn("[chat] failed to clear persisted history", error);
    }
    app.state.renderedMessageKeys.clear();
    app.state.hasShownWelcomeMessage = false;
}

export function addChatMessage(role, text, ts = Date.now(), options = {}) {
    const safeRole = app.constants.CHAT_ROLE_META[role] ? role : "system";
    const normalizedText = String(text || "").trim();
    if (!normalizedText || !app.dom.chatMessagesEl) {
        return false;
    }
    if (safeRole === "system" && !options.isError && !options.forceVisible) {
        return false;
    }
    if (!shouldKeepChatEntry({ role: safeRole, isError: options.isError })) {
        return false;
    }

    const dedupeKey = buildDedupeKey(
        safeRole,
        normalizedText,
        options.messageId || options.requestId || options.fingerprint || "local"
    );

    if (app.state.renderedMessageKeys.has(dedupeKey)) {
        return false;
    }

    app.state.renderedMessageKeys.add(dedupeKey);
    ensureChatEmptyStateRemoved();

    const meta = app.constants.CHAT_ROLE_META[safeRole];
    const rowEl = document.createElement("div");
    rowEl.className = `chat-row role-${safeRole}${options.isError ? " is-error" : ""}`;
    if (options.messageId) {
        rowEl.dataset.messageId = options.messageId;
    }
    rowEl.innerHTML = _buildChatRowHtml(safeRole, normalizedText, ts);

    app.dom.chatMessagesEl.appendChild(rowEl);
    persistChatMessage({
        role: safeRole,
        text: normalizedText,
        ts,
        isError: Boolean(options.isError),
        messageId: options.messageId,
        requestId: options.requestId,
        fingerprint: options.fingerprint,
    });
    scrollChatToBottom();
    return true;
}

export function upsertChatMessage(role, text, ts = Date.now(), options = {}) {
    const safeRole = app.constants.CHAT_ROLE_META[role] ? role : "system";
    const normalizedText = String(text || "").trim();
    const messageId = String(options.messageId || "").trim();

    if (!normalizedText || !app.dom.chatMessagesEl) {
        return false;
    }
    if (safeRole === "system" && !options.isError && !options.forceVisible) {
        return false;
    }
    if (!shouldKeepChatEntry({ role: safeRole, isError: options.isError })) {
        return false;
    }

    if (messageId) {
        const rowEl = app.dom.chatMessagesEl.querySelector(`.chat-row[data-message-id="${CSS.escape(messageId)}"]`);
        if (rowEl) {
            rowEl.className = `chat-row role-${safeRole}${options.isError ? " is-error" : ""}`;
            rowEl.innerHTML = _buildChatRowHtml(safeRole, normalizedText, ts);
            upsertPersistedChatMessage({
                role: safeRole,
                text: normalizedText,
                ts,
                isError: Boolean(options.isError),
                messageId,
                requestId: options.requestId,
                fingerprint: options.fingerprint,
            });
            scrollChatToBottom();
            return true;
        }
    }

    return addChatMessage(safeRole, normalizedText, ts, options);
}

export function ensureWelcomeMessage() {
    if (app.state.hasShownWelcomeMessage) {
        return;
    }
    app.state.hasShownWelcomeMessage = addChatMessage("assistant", "Welcome SmartHome", Date.now(), {
        fingerprint: "welcome-message",
    }) || app.state.hasShownWelcomeMessage;
}

export function shouldRenderChatMessage(message, source = "", level = "") {
    const normalizedMessage = normalizeMessageText(message);
    const normalizedSource = normalizeMessageText(source);
    const normalizedLevel = normalizeMessageText(level);

    if (!normalizedMessage) return false;
    if (app.constants.BLOCKED_EVENT_SOURCES.has(normalizedSource)) return false;
    if (app.constants.BLOCKED_MESSAGE_KEYWORDS.some((keyword) => normalizedMessage.includes(keyword))) return false;
    if (normalizedLevel && ["debug", "info", "trace", "verbose", "error", "warn", "warning"].includes(normalizedLevel)) return false;
    if (app.constants.USER_VISIBLE_EVENT_SOURCES.has(normalizedSource)) return true;
    return false;
}
