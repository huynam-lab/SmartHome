import { app } from "./core.js";
import { fetchJson } from "./api.js";
import { createMessageId, hasRecentMessage, normalizeMessageText, rememberRecentMessage } from "./utils.js";
import {
    addChatMessage,
    setChatStatus,
    setVoiceUiState,
    shouldRenderChatMessage,
    upsertChatMessage,
} from "./ui.js";
import { mergeDeviceState } from "./devices.js";

let microphonePermissionStatus = null;
let microphonePermissionRequest = null;

const MIC_PERMISSION_CACHE_KEY = "smarthome.microphone.permission.v2";

function _normalizePermissionState(permissionState) {
    const normalizedState = String(permissionState || "").trim();
    return ["granted", "denied", "prompt"].includes(normalizedState) ? normalizedState : "";
}

function getCurrentMicOriginContext() {
    const { protocol, hostname, port, origin, pathname } = window.location;
    const normalizedPort = port || (protocol === "https:" ? "443" : "80");
    return {
        protocol,
        domain: hostname,
        port: normalizedPort,
        origin,
        path: pathname,
    };
}

function _supportsPermissionsApi() {
    return typeof navigator !== "undefined" && !!navigator.permissions?.query;
}

function _supportsGetUserMedia() {
    return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

function readCachedMicrophonePermission() {
    try {
        const rawValue = window.localStorage.getItem(MIC_PERMISSION_CACHE_KEY);
        if (!rawValue) {
            return { state: "", context: null };
        }
        if (!rawValue.startsWith("{")) {
            return { state: _normalizePermissionState(rawValue), context: null };
        }
        const parsedValue = JSON.parse(rawValue);
        return {
            state: _normalizePermissionState(parsedValue?.state),
            context: parsedValue?.context || null,
        };
    } catch (error) {
        console.warn("[voice-chat] failed to read cached microphone permission", error);
        return { state: "", context: null };
    }
}

function getCachedMicrophonePermissionState() {
    const cachedPermission = readCachedMicrophonePermission();
    if (!cachedPermission.state) {
        return "";
    }
    if (cachedPermission.context?.origin && cachedPermission.context.origin !== window.location.origin) {
        return "";
    }
    return cachedPermission.state;
}

function writeCachedMicrophonePermission(permissionState) {
    const normalizedState = _normalizePermissionState(permissionState);
    if (!normalizedState) {
        return;
    }
    try {
        window.localStorage.setItem(MIC_PERMISSION_CACHE_KEY, JSON.stringify({
            state: normalizedState,
            context: getCurrentMicOriginContext(),
            updatedAt: Date.now(),
        }));
    } catch (error) {
        console.warn("[voice-chat] failed to persist microphone permission", error);
    }
}

function getKnownMicrophonePermissionState() {
    if (microphonePermissionStatus?.state) {
        return _normalizePermissionState(microphonePermissionStatus.state);
    }
    return getCachedMicrophonePermissionState();
}

function _buildPermissionUi(permissionState) {
    if (permissionState === "granted") {
        return {
            text: "Micro đã được cho phép",
            transcript: "Trình duyệt đang nhớ quyền micro cho website này.",
            statusText: "Micro đã sẵn sàng, không cần xin lại nếu browser vẫn giữ quyền.",
            statusMode: "live",
        };
    }
    if (permissionState === "denied") {
        return {
            text: "Micro đang bị chặn",
            transcript: "Trình duyệt đang chặn quyền micro. Hãy mở cài đặt quyền của website và chuyển sang Allow.",
            statusText: "Quyền micro đang bị chặn ở phía trình duyệt",
            statusMode: "error",
        };
    }
    return {
        text: "Micro cần cấp quyền",
        transcript: "Trình duyệt vẫn đang ở trạng thái hỏi quyền micro. Nếu muốn khỏi hỏi lại, hãy đổi quyền site sang Allow.",
        statusText: "Website chưa được browser nhớ quyền micro lâu dài",
        statusMode: "processing",
    };
}

function applyMicrophonePermissionUi(permissionState, { preserveListening = true } = {}) {
    const nextState = _buildPermissionUi(permissionState);
    setVoiceUiState({
        listening: preserveListening ? app.state.isListening : false,
        text: nextState.text,
        transcript: nextState.transcript,
    });
    if (!app.state.isListening && !app.state.isSendingChat && !app.state.isSendingVoice) {
        setChatStatus(nextState.statusText, nextState.statusMode);
    }
}

function showMicPermissionMessage(message, options = {}) {
    const normalizedMessage = String(message || "").trim();
    if (!normalizedMessage) {
        return;
    }
    addChatMessage("system", normalizedMessage, Date.now(), {
        fingerprint: options.fingerprint || `mic-permission-${normalizedMessage}`,
        isError: options.isError === true,
    });
}

export async function refreshMicrophonePermissionStatus() {
    const cachedPermissionState = getCachedMicrophonePermissionState();
    if (cachedPermissionState && !_supportsPermissionsApi()) {
        applyMicrophonePermissionUi(cachedPermissionState);
        return cachedPermissionState;
    }
    if (!_supportsPermissionsApi()) {
        return "";
    }
    try {
        if (!microphonePermissionStatus) {
            microphonePermissionStatus = await navigator.permissions.query({ name: "microphone" });
            microphonePermissionStatus.onchange = () => {
                const nextState = String(microphonePermissionStatus?.state || "prompt");
                writeCachedMicrophonePermission(nextState);
                applyMicrophonePermissionUi(nextState);
            };
        }
        const permissionState = String(microphonePermissionStatus.state || "prompt");
        writeCachedMicrophonePermission(permissionState);
        applyMicrophonePermissionUi(permissionState);
        return permissionState;
    } catch (error) {
        console.warn("[voice-chat] permissions.query(microphone) failed", error);
        if (cachedPermissionState) {
            applyMicrophonePermissionUi(cachedPermissionState);
            return cachedPermissionState;
        }
        return "";
    }
}

export async function checkMicPermission() {
    return refreshMicrophonePermissionStatus();
}

export async function requestMicPermission() {
    const currentPermissionState = _normalizePermissionState(await checkMicPermission());
    if (currentPermissionState === "granted") {
        return "granted";
    }
    if (currentPermissionState === "denied") {
        showMicPermissionMessage(
            "Micro đang bị chặn. Trên điện thoại hãy mở cài đặt quyền của trình duyệt cho website này và chuyển Microphone sang Allow.",
            { fingerprint: "mic-permission-denied-guide", isError: true }
        );
        return "denied";
    }
    if (!_supportsGetUserMedia()) {
        return currentPermissionState || "";
    }

    if (!microphonePermissionRequest) {
        microphonePermissionRequest = (async () => {
            let tempStream = null;
            try {
                setChatStatus("Trình duyệt đang xin quyền micro, hãy bấm Allow", "processing");
                setVoiceUiState({
                    listening: false,
                    text: "Đang xin quyền micro",
                    transcript: "Nếu điện thoại hiện popup quyền, hãy chọn Allow để bắt đầu nói.",
                });
                showMicPermissionMessage(
                    "Trình duyệt đang xin quyền micro. Nếu điện thoại hiện popup, hãy bấm Allow.",
                    { fingerprint: "mic-permission-requesting" }
                );

                // Chỉ dùng getUserMedia khi thật sự cần xin quyền từ user gesture.
                // Stream này không thể được giữ qua navigation/reload giữa 2 page.
                // Browser chỉ có thể nhớ quyền nếu vẫn coi đây là cùng origin/site context.
                tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                writeCachedMicrophonePermission("granted");
                applyMicrophonePermissionUi("granted");
                showMicPermissionMessage(
                    "Đã cấp quyền micro cho website này. Chrome Android sẽ ổn định hơn nếu bạn tiếp tục ở cùng origin và cùng app context.",
                    { fingerprint: "mic-permission-granted" }
                );
                return "granted";
            } catch (error) {
                const permissionState = error?.name === "NotAllowedError" || error?.name === "SecurityError"
                    ? "denied"
                    : "prompt";
                writeCachedMicrophonePermission(permissionState);
                applyMicrophonePermissionUi(permissionState);
                if (permissionState === "denied") {
                    showMicPermissionMessage(
                        "Bạn đã từ chối quyền micro. Trên điện thoại hãy bấm biểu tượng ổ khóa hoặc cài đặt site của trình duyệt, rồi chuyển Microphone sang Allow.",
                        { fingerprint: "mic-permission-denied", isError: true }
                    );
                } else {
                    showMicPermissionMessage(
                        "Chưa lấy được quyền micro. Hãy thử bấm nút mic lại và chấp nhận popup quyền của trình duyệt.",
                        { fingerprint: "mic-permission-prompt", isError: true }
                    );
                }
                console.warn("[voice-chat] getUserMedia() microphone permission failed", error);
                return permissionState;
            } finally {
                tempStream?.getTracks?.().forEach((track) => track.stop());
                microphonePermissionRequest = null;
            }
        })();
    }

    return microphonePermissionRequest;
}

function showDeniedMicrophoneState() {
    setChatStatus("Quyền micro đang bị chặn ở phía trình duyệt", "error");
    setVoiceUiState({
        listening: false,
        text: "Micro đang bị chặn",
        transcript: "Hãy mở Site settings của trình duyệt và chuyển Microphone sang Allow.",
    });
    showMicPermissionMessage(
        "Micro đang bị chặn. Trên điện thoại: mở menu trình duyệt hoặc biểu tượng ổ khóa của website, vào Site settings và bật Microphone = Allow.",
        { fingerprint: "mic-permission-start-denied", isError: true }
    );
}

function startRecognitionSession(permissionState = "") {
    const recognition = ensureRecognitionInstance();
    const normalizedPermissionState = _normalizePermissionState(permissionState);

    app.state.currentVoiceSessionId = createMessageId("voice");
    setChatStatus(
        normalizedPermissionState === "granted"
            ? "Đang bật micro..."
            : "Đang bật micro, nếu trình duyệt hỏi quyền hãy bấm Allow",
        "processing"
    );
    setVoiceUiState({
        listening: false,
        text: "Đang bật micro",
        transcript: normalizedPermissionState === "granted"
            ? "Micro đã sẵn sàng, hệ thống đang chuẩn bị nghe lệnh."
            : "Nếu điện thoại hiện hộp quyền, hãy chọn Allow để tiếp tục.",
    });

    try {
        // Khởi động recognition trực tiếp từ cú chạm hiện tại để tránh mất
        // user activation trên mobile sau nhiều await không cần thiết.
        recognition.start();
        refreshMicrophonePermissionStatus().catch(() => { });
        return true;
    } catch (error) {
        if (error?.name === "InvalidStateError") {
            return true;
        }
        console.warn("[voice-chat] recognition.start() failed", error);
        return false;
    }
}

export function clearVoiceSendTimer() {
    if (!app.state.voiceSendTimer) {
        return;
    }
    window.clearTimeout(app.state.voiceSendTimer);
    app.state.voiceSendTimer = null;
}

export function resetVoiceState({ keepTranscript = false } = {}) {
    clearVoiceSendTimer();
    app.state.currentVoiceSessionId = null;
    app.state.isSendingVoice = false;
    if (!keepTranscript) {
        app.state.latestTranscript = "";
    }
}

function hasMeaningfulVoiceTranscript(transcript) {
    return String(transcript || "").trim().length >= app.constants.MIN_VOICE_TRANSCRIPT_LENGTH;
}

function updatePendingVoiceTranscript(transcript) {
    const normalizedTranscript = String(transcript || "").trim();
    app.state.latestTranscript = normalizedTranscript;
    setVoiceUiState({
        listening: true,
        text: "Đang chờ bạn nói xong...",
        transcript: normalizedTranscript ? `“${normalizedTranscript}”` : "Hãy tiếp tục nói để hoàn thành câu lệnh.",
    });
    setChatStatus("Đang chờ bạn nói xong...", "processing");
}

async function flushVoiceTranscript(options = {}) {
    const normalizedTranscript = String(options.transcript ?? app.state.latestTranscript ?? "").trim();
    const shouldStopRecognition = options.stopRecognition !== false;
    const isManualStop = options.isManualStop === true;

    clearVoiceSendTimer();

    if (!normalizedTranscript) {
        resetVoiceState();
        setVoiceUiState({ listening: false, text: "Chạm để bắt đầu nói", transcript: "Không nhận được câu hoàn chỉnh, hãy thử nói lại." });
        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
        return;
    }
    if (!hasMeaningfulVoiceTranscript(normalizedTranscript)) {
        resetVoiceState();
        setVoiceUiState({
            listening: false,
            text: isManualStop ? "Câu nói quá ngắn" : "Thử lại bằng giọng nói",
            transcript: "Câu lệnh quá ngắn, vui lòng nói rõ hơn để hệ thống xử lý.",
        });
        setChatStatus("Câu lệnh quá ngắn, chưa gửi lên Jetson", "error");
        return;
    }
    if (app.state.isSendingVoice || app.state.isSendingChat || hasRecentMessage(app.state.pendingUserTexts, normalizedTranscript)) {
        resetVoiceState({ keepTranscript: true });
        setVoiceUiState({ listening: false, text: "Đã nhận giọng nói", transcript: `“${normalizedTranscript}” đã được gửi trước đó.` });
        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
        return;
    }

    const requestId = app.state.currentVoiceSessionId || createMessageId("voice");
    app.state.isSendingVoice = true;
    app.state.currentVoiceSessionId = requestId;

    if (shouldStopRecognition && app.state.recognition) {
        try {
            app.state.recognition.stop();
        } catch (stopError) {
            console.warn("[voice-chat] recognition.stop() failed", stopError);
        }
    }

    setVoiceUiState({ listening: false, text: "Đang gửi...", transcript: `“${normalizedTranscript}”` });
    setChatStatus("Đang gửi lệnh lên Jetson...", "processing");
    addChatMessage("user", normalizedTranscript, Date.now(), { requestId, messageId: `${requestId}-user` });

    try {
        await sendChatText(normalizedTranscript, { requestId, skipUserBubble: true });
    } finally {
        resetVoiceState();
    }
}

function scheduleVoiceSend(transcript) {
    const normalizedTranscript = String(transcript || "").trim();
    if (!normalizedTranscript) {
        return;
    }
    app.state.latestTranscript = normalizedTranscript;
    clearVoiceSendTimer();
    app.state.voiceSendTimer = window.setTimeout(() => {
        flushVoiceTranscript({ transcript: app.state.latestTranscript, stopRecognition: true }).catch((error) => {
            console.error("[voice-chat] flushVoiceTranscript() failed", error);
        });
    }, app.constants.VOICE_SEND_DEBOUNCE_MS);
}

export async function sendChatText(text, options = {}) {
    const normalizedText = String(text || "").trim();
    if (!normalizedText || app.state.isSendingChat) {
        return;
    }
    if (!app.state.isAuthenticated) {
        return;
    }

    const requestId = options.requestId || createMessageId("voice-request");
    app.state.activeChatRequestId = requestId;
    app.state.isSendingChat = true;
    rememberRecentMessage(app.state.pendingUserTexts, normalizedText);

    if (!options.skipUserBubble) {
        addChatMessage("user", normalizedText, Date.now(), { requestId, messageId: `${requestId}-user` });
    }

    setChatStatus("Đang gửi lệnh lên Jetson...", "processing");
    setVoiceUiState({ listening: false, text: "Đã nhận câu lệnh", transcript: `“${normalizedText}” đang được xử lý...` });
    if (app.dom.micBtnEl) {
        app.dom.micBtnEl.disabled = true;
    }

    try {
        const { result } = await fetchJson("/api/chat/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: normalizedText, request_id: requestId }),
        });
        if (result.reply_text) {
            rememberRecentMessage(app.state.pendingAssistantTexts, result.reply_text);
            addChatMessage("assistant", result.reply_text, Date.now(), { requestId, messageId: `${requestId}-assistant` });
        }

        if (result.intent?.device && result.intent?.action) {
            mergeDeviceState(result.intent.device, {
                state: result.state || result.intent.action || "unknown",
                state_verified: result.state_verified,
                last_command: result.last_command || result.intent.action,
                last_command_at: result.last_command_at,
                last_command_status: result.last_command_status,
                last_command_message: result.last_command_message,
            });
        }

        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
        setVoiceUiState({ listening: false, text: "Chạm để bắt đầu nói", transcript: `Đã gửi: “${normalizedText}”` });
    } catch (error) {
        if (!error.isAuth) {
            addChatMessage("system", error.message || "Có lỗi xảy ra khi gửi lệnh lên Jetson", Date.now(), {
                isError: true,
                requestId,
                messageId: `${requestId}-error`,
            });
            setChatStatus("Có lỗi khi xử lý yêu cầu", "error");
            setVoiceUiState({ listening: false, text: "Thử lại bằng giọng nói", transcript: "Jetson chưa phản hồi đúng, hãy nói lại một lần nữa." });
        }
    } finally {
        app.state.isSendingChat = false;
        app.state.activeChatRequestId = null;
        if (app.dom.micBtnEl) {
            app.dom.micBtnEl.disabled = false;
        }
    }
}

function ensureRecognitionInstance() {
    if (app.state.recognition) {
        return app.state.recognition;
    }

    app.state.recognition = new app.constants.SpeechRecognitionApi();
    app.state.recognition.lang = "vi-VN";
    app.state.recognition.interimResults = true;
    app.state.recognition.maxAlternatives = 1;
    app.state.recognition.continuous = false;

    app.state.recognition.onstart = () => {
        resetVoiceState();
        setVoiceUiState({ listening: true, text: "Đang nghe...", transcript: "Hãy nói lệnh của bạn. Hệ thống sẽ đợi bạn nói xong rồi mới gửi." });
        setChatStatus("Đang nghe giọng nói của bạn...", "processing");
    };

    app.state.recognition.onresult = (event) => {
        const transcript = Array.from(event.results || [])
            .map((result) => result?.[0]?.transcript || "")
            .join(" ")
            .trim();
        if (!transcript) {
            return;
        }
        updatePendingVoiceTranscript(transcript);
        scheduleVoiceSend(transcript);
    };

    app.state.recognition.onerror = (event) => {
        resetVoiceState();
        const errorMap = {
            not_allowed: "Bạn chưa cấp quyền micro cho trình duyệt.",
            no_speech: "Không nghe thấy giọng nói, vui lòng thử lại.",
            audio_capture: "Không truy cập được microphone.",
            aborted: "Ghi âm đã được dừng.",
        };
        const message = errorMap[event.error] || "Không thể nhận diện giọng nói lúc này.";
        if (event.error === "not_allowed") {
            writeCachedMicrophonePermission("denied");
        }
        setChatStatus(event.error !== "aborted" ? message : "Đã dừng ghi âm", event.error !== "aborted" ? "error" : "live");
        setVoiceUiState({
            listening: false,
            text: event.error === "aborted" ? "Đã dừng ghi âm" : "Micro gặp lỗi",
            transcript: message,
        });
    };

    app.state.recognition.onend = () => {
        if (app.state.voiceSendTimer || app.state.isSendingVoice || app.state.isSendingChat) {
            return;
        }
        if (app.state.isListening && hasMeaningfulVoiceTranscript(app.state.latestTranscript)) {
            flushVoiceTranscript({ transcript: app.state.latestTranscript, stopRecognition: false }).catch((error) => {
                console.error("[voice-chat] onend flush failed", error);
            });
            return;
        }
        if (app.state.isListening) {
            resetVoiceState();
            setVoiceUiState({ listening: false, text: "Chạm để bắt đầu nói", transcript: "Không nhận được câu hoàn chỉnh, hãy thử nói lại." });
            setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
        }
    };

    return app.state.recognition;
}

export function stopMic(options = {}) {
    const force = options.force === true;
    const updateUi = options.updateUi !== false;

    if (!app.state.recognition) {
        return;
    }

    if (force) {
        clearVoiceSendTimer();
        resetVoiceState();
        try {
            app.state.recognition.stop();
        } catch (stopError) {
            console.warn("[voice-chat] recognition.stop() failed", stopError);
        }
        if (updateUi) {
            setVoiceUiState({
                listening: false,
                text: "Đã dừng ghi âm",
                transcript: "Bạn có thể chạm lại để nói một lệnh mới.",
            });
            setChatStatus("Đã dừng ghi âm", "live");
        }
        return;
    }

    if (!app.state.isListening) {
        return;
    }

    const transcriptToFlush = app.state.latestTranscript;
    clearVoiceSendTimer();

    if (hasMeaningfulVoiceTranscript(transcriptToFlush)) {
        flushVoiceTranscript({ transcript: transcriptToFlush, stopRecognition: true, isManualStop: true }).catch((error) => {
            console.error("[voice-chat] manual flush failed", error);
        });
        return;
    }

    resetVoiceState();
    try {
        app.state.recognition.stop();
    } catch (stopError) {
        console.warn("[voice-chat] recognition.stop() failed", stopError);
    }

    setVoiceUiState({
        listening: false,
        text: transcriptToFlush ? "Câu nói quá ngắn" : "Đã dừng ghi âm",
        transcript: transcriptToFlush
            ? "Câu lệnh quá ngắn, chưa gửi lên Jetson. Hãy nói dài hơn một chút."
            : "Bạn có thể chạm lại để nói một lệnh mới.",
    });
    setChatStatus(transcriptToFlush ? "Câu lệnh quá ngắn, chưa gửi" : "Đã dừng ghi âm", transcriptToFlush ? "error" : "live");
}

export async function startMic() {
    if (!app.constants.SpeechRecognitionApi) {
        addChatMessage("system", "Trình duyệt này chưa hỗ trợ nhận diện giọng nói. Hãy dùng Chrome hoặc Edge mới để dùng micro.", Date.now(), {
            isError: true,
            fingerprint: "speech-not-supported",
        });
        setChatStatus("Thiết bị không hỗ trợ SpeechRecognition", "error");
        setVoiceUiState({ listening: false, text: "Trình duyệt chưa hỗ trợ micro", transcript: "Hãy mở bằng Chrome hoặc Edge để dùng điều khiển giọng nói." });
        return;
    }

    if (app.state.isSendingChat) {
        return;
    }

    if (app.state.isListening) {
        stopMic();
        return;
    }

    const knownPermissionState = getKnownMicrophonePermissionState();
    if (knownPermissionState === "denied") {
        const confirmedPermissionState = await checkMicPermission();
        if (confirmedPermissionState === "denied") {
            showDeniedMicrophoneState();
            return;
        }
    }

    if (startRecognitionSession(knownPermissionState)) {
        return;
    }

    const permissionState = await checkMicPermission();
    if (permissionState === "denied") {
        showDeniedMicrophoneState();
        return;
    }

    const grantedState = await requestMicPermission();
    if (grantedState !== "granted") {
        setChatStatus("Micro chưa được cấp quyền ổn định", "error");
        return;
    }

    if (!startRecognitionSession("granted")) {
        setChatStatus("Không thể khởi động micro lúc này", "error");
    }
}

export const startVoiceRecognition = startMic;
export const stopVoiceRecognition = stopMic;

export function renderEventAsChat(event) {
    if (!event || app.state.renderedEventIds.has(event.id)) {
        return;
    }
    app.state.renderedEventIds.add(event.id);

    const message = event?.message || event?.payload?.reply_text || "";
    const source = event?.source || event?.payload?.source || "";
    const level = event?.level || event?.payload?.level || "";
    if (!shouldRenderChatMessage(message, source, level)) {
        return;
    }
    addChatMessage("system", message, event.ts || Date.now(), { fingerprint: `event-${event.id}` });
}

export function handleAssistantTtsChunk(payload) {
    const requestId = String(payload?.request_id || "").trim();
    const accumulatedText = String(payload?.accumulated_text || "").trim();
    if (!requestId || !accumulatedText) {
        return;
    }

    app.state.assistantStreamRequestIds.add(requestId);
    rememberRecentMessage(app.state.pendingAssistantTexts, accumulatedText);
    upsertChatMessage("assistant", accumulatedText, payload?.ts || Date.now(), {
        requestId,
        messageId: `${requestId}-assistant`,
    });

    if (payload?.is_final) {
        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
    } else {
        setChatStatus("Trợ lý đang phản hồi bằng giọng nói...", "processing");
    }
}

export function shouldSkipSocketMessage(message) {
    const normalizedMessage = normalizeMessageText(message);
    return hasRecentMessage(app.state.pendingAssistantTexts, normalizedMessage)
        || hasRecentMessage(app.state.pendingUserTexts, normalizedMessage);
}
