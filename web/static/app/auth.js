import { app } from "./core.js";
import { fetchJson, setUnauthorizedHandler } from "./api.js";
import { clearVoiceSendTimer, refreshMicrophonePermissionStatus, resetVoiceState, stopMic } from "./chat.js";
import { closeAddDeviceModal, closeAddFunctionButtonModal, closeDeviceControlPage, closeDeviceScheduleModal, hydrateCachedDevices, loadDevices, loadIrTemplateOptions, closeIrLearnModal } from "./devices.js";
import { initializeApp, pollEvents, prepareLockedShell, setupRealtime, stopRealtimeAndPolling } from "./realtime.js";
import {
    clearPersistedChatHistory,
    closePasswordModal,
    closeSettingsMenu,
    setAuthFeedback,
    setAuthMode,
    setChatStatus,
    setControlLockState,
    setIrLearnStatus,
    setPasswordFeedback,
    setVoiceUiState,
    updateAuthChip,
    markUiReady,
} from "./ui.js";

function getBootstrapSessionData() {
    const payload = window.__SMART_HOME_BOOTSTRAP__;
    if (!payload || payload.authenticated !== true) {
        return null;
    }
    return {
        authenticated: true,
        jetson_id: String(payload.jetson_id || "").trim(),
    };
}

function clearAuthFields() {
    app.dom.authFormEl?.reset();

    if (app.dom.authEmailEl) {
        app.dom.authEmailEl.value = "";
    }
    if (app.dom.authPasswordEl) {
        app.dom.authPasswordEl.value = "";
    }
    if (app.dom.authJetsonIdEl) {
        app.dom.authJetsonIdEl.value = "";
    }
}

export function lockControlUi(message = "Vui lòng đăng nhập") {
    app.state.isAuthenticated = false;
    app.state.appInitialized = false;
    stopRealtimeAndPolling();
    clearVoiceSendTimer();
    clearPersistedChatHistory();

    stopMic({ force: true, updateUi: false });

    resetVoiceState();
    closeSettingsMenu();
    closePasswordModal();
    closeAddDeviceModal();
    closeAddFunctionButtonModal();
    closeDeviceScheduleModal();
    closeDeviceControlPage({ navigate: false });
    closeIrLearnModal({ force: true });
    clearAuthFields();
    setAuthFeedback(message, "error");
    updateAuthChip("Đăng nhập để mở quyền điều khiển");
    setControlLockState(true);
    setChatStatus("Vui lòng đăng nhập để sử dụng điều khiển thiết bị", "error");
    setVoiceUiState({
        listening: false,
        text: "Đăng nhập để dùng micro",
        transcript: "Toàn bộ lệnh điều khiển đang bị khóa cho đến khi đăng nhập thành công.",
    });
    setIrLearnStatus("Vui lòng đăng nhập để học lệnh và điều khiển thiết bị.", "error");
    markUiReady();
}

export async function handleLogout() {
    closeSettingsMenu();
    try {
        await fetchJson("/api/auth/logout", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
    } catch (error) {
        // Ignore logout transport errors, local UI still needs to lock.
    }
    lockControlUi("Vui lòng đăng nhập");
}

export async function unlockControlUi(sessionData = {}) {
    app.state.isAuthenticated = true;
    setAuthFeedback("", "success");
    updateAuthChip(sessionData.jetson_id ? `Jetson ${sessionData.jetson_id}` : "Đăng nhập thành công");
    setControlLockState(false);
    setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
    setVoiceUiState({
        listening: false,
        text: app.constants.SpeechRecognitionApi ? "Chạm để bắt đầu nói" : "Trình duyệt chưa hỗ trợ micro",
        transcript: app.constants.SpeechRecognitionApi
            ? "Không có ô nhập tay, sau khi nhận diện xong hệ thống sẽ tự gửi lên Jetson."
            : "Hãy mở bằng Chrome hoặc Edge để dùng điều khiển giọng nói.",
    });
    setIrLearnStatus("Sẵn sàng học lệnh. Hãy chọn IR hoặc RF trước khi bắt đầu.", "idle");
    initializeApp();
    setupRealtime();
    hydrateCachedDevices();
    markUiReady();
    await refreshMicrophonePermissionStatus();
    await loadIrTemplateOptions();
    await loadDevices();
    await pollEvents();
}

export async function submitLogin(event) {
    event.preventDefault();
    if (app.state.isAuthSubmitting || !app.dom.authFormEl?.reportValidity()) {
        return;
    }

    const formData = new FormData(app.dom.authFormEl);
    const email = String(formData.get("email") || "").trim();
    const password = String(formData.get("password") || "");
    const jetsonId = String(formData.get("jetson_id") || "").trim();
    const endpoint = app.state.authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const successChipText = app.state.authMode === "register"
        ? "Đang tạo tài khoản..."
        : "Đang xác thực...";

    app.state.isAuthSubmitting = true;
    if (app.dom.authSubmitBtnEl) {
        app.dom.authSubmitBtnEl.disabled = true;
    }
    setAuthFeedback("");
    updateAuthChip(successChipText);

    try {
        const { result } = await fetchJson(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password, jetson_id: jetsonId }),
        });

        app.dom.authFormEl?.reset();
        setAuthMode("login");
        await unlockControlUi(result);
    } catch (error) {
        setControlLockState(true);
        setAuthFeedback(error.message || (app.state.authMode === "register" ? "Đăng ký thất bại." : "Đăng nhập thất bại."));
        updateAuthChip(app.state.authMode === "register" ? "Nhập thông tin để tạo tài khoản" : "Đăng nhập để mở quyền điều khiển");
        (app.state.authMode === "register" ? app.dom.authJetsonIdEl : app.dom.authPasswordEl)?.focus();
    } finally {
        app.state.isAuthSubmitting = false;
        if (app.dom.authSubmitBtnEl) {
            app.dom.authSubmitBtnEl.disabled = false;
        }
    }
}

export async function submitPasswordChange(event) {
    event.preventDefault();
    if (!app.state.isAuthenticated || app.state.isPasswordSubmitting || !app.dom.passwordFormEl?.reportValidity()) {
        return;
    }

    const formData = new FormData(app.dom.passwordFormEl);
    const currentPassword = String(formData.get("current_password") || "");
    const newPassword = String(formData.get("new_password") || "");

    app.state.isPasswordSubmitting = true;
    if (app.dom.passwordSubmitBtnEl) {
        app.dom.passwordSubmitBtnEl.disabled = true;
    }
    setPasswordFeedback("");

    try {
        const { result } = await fetchJson("/api/auth/change-password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword,
            }),
        });
        setPasswordFeedback(result.message || "Đổi mật khẩu thành công.", "success");
        app.dom.passwordFormEl?.reset();
        window.setTimeout(() => closePasswordModal(), 700);
    } catch (error) {
        setPasswordFeedback(error.message || "Đổi mật khẩu thất bại.");
        app.dom.currentPasswordEl?.focus();
    } finally {
        app.state.isPasswordSubmitting = false;
        if (app.dom.passwordSubmitBtnEl) {
            app.dom.passwordSubmitBtnEl.disabled = false;
        }
    }
}

export async function bootstrapAuthentication() {
    const bootstrapSession = getBootstrapSessionData();
    if (bootstrapSession) {
        app.state.isAuthenticated = true;
        setControlLockState(false);
        updateAuthChip(bootstrapSession.jetson_id ? `Jetson ${bootstrapSession.jetson_id}` : "Đăng nhập thành công");
        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
        setVoiceUiState({
            listening: false,
            text: app.constants.SpeechRecognitionApi ? "Chạm để bắt đầu nói" : "Trình duyệt chưa hỗ trợ micro",
        });
        setIrLearnStatus("Sẵn sàng học lệnh. Hãy chọn IR hoặc RF trước khi bắt đầu.", "idle");
        initializeApp();
        hydrateCachedDevices();
        markUiReady();
        await refreshMicrophonePermissionStatus();
        await loadIrTemplateOptions();
        await loadDevices();
    } else {
        setControlLockState(true);
        prepareLockedShell();
        setIrLearnStatus("Vui lòng đăng nhập để học lệnh và điều khiển thiết bị.", "error");
        updateAuthChip("Kiểm tra phiên đăng nhập...");
    }

    try {
        const { result } = await fetchJson("/api/auth/status", { allowResultError: true });
        if (result.authenticated) {
            if (!bootstrapSession) {
                await unlockControlUi(result);
            } else {
                markUiReady();
            }
            return;
        }
        lockControlUi("");
    } catch (error) {
        lockControlUi(error.message || "Không kiểm tra được trạng thái đăng nhập.");
    }
}

setUnauthorizedHandler(lockControlUi);
