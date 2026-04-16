let activeMicrophoneStream = null;

function isLocalhostHost(hostname = "") {
    return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function normalizePermissionState(value) {
    const normalized = String(value || "").trim().toLowerCase();
    return ["granted", "denied", "prompt"].includes(normalized) ? normalized : "unknown";
}

function clearStoredStream(referenceStream = null) {
    if (!referenceStream || referenceStream === activeMicrophoneStream) {
        activeMicrophoneStream = null;
    }
}

function bindStreamLifecycle(stream) {
    stream?.getTracks?.().forEach((track) => {
        track.addEventListener("ended", () => {
            const hasLiveTrack = stream.getTracks().some((item) => item.readyState === "live");
            if (!hasLiveTrack) {
                clearStoredStream(stream);
            }
        });
    });
}

export function getActiveMicrophoneStream() {
    if (!activeMicrophoneStream) {
        return null;
    }
    const hasLiveTrack = activeMicrophoneStream.getTracks().some((track) => track.readyState === "live");
    if (!hasLiveTrack) {
        activeMicrophoneStream = null;
        return null;
    }
    return activeMicrophoneStream;
}

export function stopMicrophoneTracks(stream = null) {
    const targetStream = stream || getActiveMicrophoneStream();
    if (!targetStream) {
        return {
            ok: true,
            stopped: false,
        };
    }

    targetStream.getTracks().forEach((track) => track.stop());
    clearStoredStream(targetStream);
    return {
        ok: true,
        stopped: true,
    };
}

export function checkMicrophoneSupport() {
    const hostname = window.location.hostname;
    const secureContext = window.isSecureContext || isLocalhostHost(hostname);
    const hasMediaDevices = typeof navigator !== "undefined" && !!navigator.mediaDevices;
    const hasGetUserMedia = typeof navigator !== "undefined" && typeof navigator.mediaDevices?.getUserMedia === "function";
    const supported = secureContext && hasMediaDevices && hasGetUserMedia;

    let code = "ok";
    let message = "";

    if (!secureContext) {
        code = "https_required";
        message = "Microphone requires HTTPS, except on localhost.";
    } else if (!hasMediaDevices || !hasGetUserMedia) {
        code = "unsupported_browser";
        message = "This browser does not support microphone access.";
    }

    return {
        ok: supported,
        supported,
        secureContext,
        hasMediaDevices,
        hasGetUserMedia,
        code,
        message,
    };
}

export async function checkMicrophonePermissionState() {
    const support = checkMicrophoneSupport();
    if (!support.supported) {
        return {
            ok: false,
            supported: false,
            canQuery: false,
            state: "unknown",
            code: support.code,
            message: support.message,
        };
    }

    if (typeof navigator === "undefined" || typeof navigator.permissions?.query !== "function") {
        return {
            ok: true,
            supported: true,
            canQuery: false,
            state: getActiveMicrophoneStream() ? "granted" : "unknown",
            code: "permissions_api_unavailable",
            message: "Permissions API is unavailable in this browser.",
        };
    }

    try {
        const permissionStatus = await navigator.permissions.query({ name: "microphone" });
        return {
            ok: true,
            supported: true,
            canQuery: true,
            state: normalizePermissionState(permissionStatus?.state),
            code: "ok",
            message: "",
            permissionStatus,
        };
    } catch (error) {
        return {
            ok: true,
            supported: true,
            canQuery: false,
            state: getActiveMicrophoneStream() ? "granted" : "unknown",
            code: "permissions_query_failed",
            message: error?.message || "Unable to query microphone permission.",
            error,
        };
    }
}

export async function requestMicrophoneAccess() {
    const support = checkMicrophoneSupport();
    if (!support.supported) {
        return {
            ok: false,
            state: "unknown",
            stream: null,
            reused: false,
            code: support.code,
            message: support.message,
        };
    }

    const liveStream = getActiveMicrophoneStream();
    if (liveStream) {
        return {
            ok: true,
            state: "granted",
            stream: liveStream,
            reused: true,
            code: "ok",
            message: "",
        };
    }

    const permission = await checkMicrophonePermissionState();
    if (permission.state === "denied") {
        return {
            ok: false,
            state: "denied",
            stream: null,
            reused: false,
            code: "microphone_blocked",
            message: "Microphone permission is blocked in browser settings.",
        };
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        activeMicrophoneStream = stream;
        bindStreamLifecycle(stream);
        return {
            ok: true,
            state: "granted",
            stream,
            reused: false,
            code: "ok",
            message: "",
        };
    } catch (error) {
        const errorName = String(error?.name || "").trim();
        if (errorName === "NotAllowedError" || errorName === "SecurityError") {
            return {
                ok: false,
                state: "denied",
                stream: null,
                reused: false,
                code: "microphone_blocked",
                message: "Microphone permission was denied.",
                error,
            };
        }
        if (errorName === "NotFoundError" || errorName === "DevicesNotFoundError") {
            return {
                ok: false,
                state: "unknown",
                stream: null,
                reused: false,
                code: "microphone_missing",
                message: "No microphone device was found.",
                error,
            };
        }
        if (errorName === "NotReadableError" || errorName === "TrackStartError") {
            return {
                ok: false,
                state: "unknown",
                stream: null,
                reused: false,
                code: "microphone_busy",
                message: "Microphone is busy or unavailable right now.",
                error,
            };
        }
        return {
            ok: false,
            state: "unknown",
            stream: null,
            reused: false,
            code: "microphone_failed",
            message: error?.message || "Unable to access microphone.",
            error,
        };
    }
}
