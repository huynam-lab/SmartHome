import { app } from "./core.js";

export function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

export function createMessageId(prefix = "msg") {
    const randomText = Math.random().toString(36).slice(2, 10);
    return `${prefix}-${Date.now()}-${randomText}`;
}

export function normalizeMessageText(text) {
    return String(text || "").trim().replaceAll(/\s+/g, " ").toLowerCase();
}

export function buildDedupeKey(role, text, fingerprint = "") {
    return `${role}::${normalizeMessageText(text)}::${fingerprint}`;
}

export function rememberRecentMessage(setMap, text, ttl = 12000) {
    const key = normalizeMessageText(text);
    setMap.set(key, Date.now() + ttl);

    window.setTimeout(() => {
        const expiresAt = setMap.get(key);
        if (expiresAt && expiresAt <= Date.now()) {
            setMap.delete(key);
        }
    }, ttl + 100);
}

export function hasRecentMessage(setMap, text) {
    const key = normalizeMessageText(text);
    const expiresAt = setMap.get(key);
    if (!expiresAt) {
        return false;
    }
    if (expiresAt <= Date.now()) {
        setMap.delete(key);
        return false;
    }
    return true;
}

export function formatTime(ts) {
    return new Date(ts || Date.now()).toLocaleTimeString("vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
    });
}

export function formatActionLabel(action) {
    const labels = {
        on: "Bật",
        off: "Tắt",
        turn_on: "Bật",
        turn_off: "Tắt",
        "power.on": "Bật",
        "power.off": "Tắt",
    };
    return labels[action] || String(action || "").replaceAll("_", " ");
}

export function formatState(state) {
    const labels = {
        on: "Đang bật",
        off: "Đang tắt",
        unknown: "Chưa rõ",
    };
    return labels[state] || state || "Chưa rõ";
}

export function getEffectiveDeviceState(device) {
    if (!device) {
        return "unknown";
    }
    if (device.state && typeof device.state === "object" && (device.state.power === "on" || device.state.power === "off")) {
        return device.state.power;
    }
    if (device.state === "on" || device.state === "off") {
        return device.state;
    }
    if (device.state === "power.on" || device.state === "power.off") {
        return device.state === "power.on" ? "on" : "off";
    }
    if (device.state === "turn_on" || device.state === "turn_off") {
        return device.state === "turn_on" ? "on" : "off";
    }
    if (device.last_command_status === "sent" && ["on", "off", "turn_on", "turn_off", "power.on", "power.off"].includes(device.last_command)) {
        return ["on", "turn_on", "power.on"].includes(device.last_command) ? "on" : "off";
    }
    return "unknown";
}

export function formatCommandStatus(device) {
    if (!device) {
        return "Chưa rõ";
    }
    const effectiveState = getEffectiveDeviceState(device);
    if (device.state_verified && (effectiveState === "on" || effectiveState === "off")) {
        return formatState(effectiveState);
    }
    if (effectiveState === "on" || effectiveState === "off") {
        return formatState(effectiveState);
    }
    return "Chưa rõ";
}

export function getActionButtonClass(action) {
    if (action === "on" || action === "turn_on" || action === "power.on") return "btn-on";
    if (action === "off" || action === "turn_off" || action === "power.off") return "btn-off";
    return "btn-default";
}

export function getDeviceIcon(device) {
    return app.constants.DEVICE_TYPE_ICONS[device?.type] || app.constants.DEVICE_TYPE_ICONS.unknown;
}

export function getStatusBannerClass(state, processing = false) {
    if (processing) return "device-status-banner";
    if (state === "on") return "device-status-banner is-on";
    if (state === "off") return "device-status-banner is-off";
    return "device-status-banner";
}

export function normalizeIrFilenameInput(value) {
    return String(value || "").trim().replaceAll(/\s+/g, "");
}

export function slugifyVietnameseText(value) {
    return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/đ/gi, "d")
        .replace(/[^a-zA-Z0-9\s]/g, " ")
        .trim()
        .replace(/\s+/g, "_")
        .toLowerCase();
}

export function suggestLearnFilename(deviceName, signalType = "ir") {
    const normalizedName = slugifyVietnameseText(deviceName);
    if (!normalizedName) {
        return "";
    }
    return signalType === "rf" ? `${normalizedName}_on.json` : `${normalizedName}_on.bin`;
}

export function parseMultilinePhrases(value) {
    return Array.from(new Set(
        String(value || "")
            .split(/\n+/)
            .map((item) => item.trim())
            .filter(Boolean)
    ));
}

export function getIrSemanticConfig(kind) {
    const configs = {
        "power.on": { requiresValue: false },
        "power.off": { requiresValue: false },
        "timer.off_after": {
            requiresValue: true,
            label: "Số phút",
            hint: "Ví dụ: nhập 1 để tạo lệnh hẹn tắt sau 1 phút.",
            min: "1",
            step: "1",
            placeholder: "Ví dụ: 1",
        },
        "climate.set_temperature": {
            requiresValue: true,
            label: "Nhiệt độ",
            hint: "Ví dụ: nhập 24 để tạo lệnh đặt điều hòa 24 độ.",
            min: "16",
            step: "1",
            placeholder: "Ví dụ: 24",
        },
    };
    return configs[kind] || configs["power.on"];
}

export function buildSemanticActionPayload(kind, rawValue, inferActionKeyFromFilename) {
    const normalizedKind = String(kind || "").trim();
    const valueText = String(rawValue || "").trim();

    if (normalizedKind === "power.on") {
        return { actionKey: "power.on", semantic: { domain: "power", operation: "on" } };
    }
    if (normalizedKind === "power.off") {
        return { actionKey: "power.off", semantic: { domain: "power", operation: "off" } };
    }
    if (normalizedKind === "timer.off_after") {
        const minutes = Number.parseInt(valueText, 10);
        if (!Number.isFinite(minutes) || minutes <= 0) {
            throw new Error("Vui lòng nhập số phút hợp lệ cho lệnh hẹn tắt.");
        }
        return {
            actionKey: `timer.off_after_${minutes}_min`,
            semantic: { domain: "timer", operation: "off_after", duration_seconds: minutes * 60 },
        };
    }
    if (normalizedKind === "climate.set_temperature") {
        const temperature = Number.parseInt(valueText, 10);
        if (!Number.isFinite(temperature) || temperature <= 0) {
            throw new Error("Vui lòng nhập nhiệt độ hợp lệ.");
        }
        return {
            actionKey: `climate.set_${temperature}c`,
            semantic: { domain: "climate", operation: "set_temperature", temperature_c: temperature },
        };
    }
    return { actionKey: inferActionKeyFromFilename(""), semantic: {} };
}

export function buildDefaultActionPhrases(deviceName, kind, rawValue) {
    const targetName = String(deviceName || "").trim().toLowerCase();
    if (!targetName) {
        return [];
    }
    if (kind === "power.on") return [`bật ${targetName}`];
    if (kind === "power.off") return [`tắt ${targetName}`];
    if (kind === "timer.off_after") {
        const minutes = Number.parseInt(String(rawValue || "").trim(), 10);
        if (!Number.isFinite(minutes) || minutes <= 0) {
            return [];
        }
        return [`tắt ${targetName} sau ${minutes} phút`, `bật ${targetName} ${minutes} phút`];
    }
    if (kind === "climate.set_temperature") {
        const temperature = Number.parseInt(String(rawValue || "").trim(), 10);
        if (!Number.isFinite(temperature) || temperature <= 0) {
            return [];
        }
        return [`bật ${targetName} ${temperature} độ`, `${targetName} ${temperature} độ`];
    }
    return [];
}

export function isValidLearnFilename(filename, signalType = "ir") {
    const normalized = normalizeIrFilenameInput(filename);
    const extension = signalType === "rf" ? ".json" : ".bin";
    return normalized.toLowerCase().endsWith(extension) && normalized.length > extension.length;
}
