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
        const streamingEnabled = Boolean(result.tts_streaming);

        if (result.reply_text) {
            if (!streamingEnabled) {
                rememberRecentMessage(app.state.pendingAssistantTexts, result.reply_text);
                addChatMessage("assistant", result.reply_text, Date.now(), { requestId, messageId: `${requestId}-assistant` });
            } else {
                window.setTimeout(() => {
                    if (app.state.assistantStreamRequestIds.has(requestId)) {
                        return;
                    }
                    rememberRecentMessage(app.state.pendingAssistantTexts, result.reply_text);
                    addChatMessage("assistant", result.reply_text, Date.now(), { requestId, messageId: `${requestId}-assistant` });
                }, 1200);
            }
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

        setChatStatus(streamingEnabled ? "Trợ lý đang phản hồi bằng giọng nói..." : "Sẵn sàng nhận lệnh bằng giọng nói", streamingEnabled ? "processing" : "live");
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

export function stopVoiceRecognition() {
    if (!app.state.recognition || !app.state.isListening) {
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

export function startVoiceRecognition() {
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

    if (!app.state.recognition) {
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
    }

    if (app.state.isListening) {
        stopVoiceRecognition();
        return;
    }

    app.state.currentVoiceSessionId = createMessageId("voice");
    app.state.recognition.start();
}

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
