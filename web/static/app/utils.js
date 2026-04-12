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
        bat: "Bật",
        tat: "Tắt",
        turn_on: "Bật",
        turn_off: "Tắt",
        "power.on": "Bật",
        "power.off": "Tắt",
        "climate.set_mode": "Đặt chế độ",
        "climate.set_fan_speed": "Đặt tốc độ quạt",
        "climate.set_swing": "Đặt đảo gió",
        "climate.set_sleep": "Đặt chế độ ngủ",
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
    if (device.state === "bat" || device.state === "tat") {
        return device.state === "bat" ? "on" : "off";
    }
    if (device.state === "power.on" || device.state === "power.off") {
        return device.state === "power.on" ? "on" : "off";
    }
    if (device.state === "turn_on" || device.state === "turn_off") {
        return device.state === "turn_on" ? "on" : "off";
    }
    if (device.last_command_status === "sent" && ["on", "off", "turn_on", "turn_off", "power.on", "power.off", "bat", "tat"].includes(device.last_command)) {
        return ["on", "turn_on", "power.on", "bat"].includes(device.last_command) ? "on" : "off";
    }
    return "unknown";
}

export function getEffectiveActiveAction(device) {
    if (!device) {
        return "";
    }
    const activeAction = String(device.active_action || "").trim().toLowerCase();
    if (activeAction) {
        return activeAction;
    }
    const lastCommand = String(device.last_command || "").trim().toLowerCase();
    if (lastCommand && String(device.last_command_status || "").trim().toLowerCase() === "sent") {
        return lastCommand;
    }

    const effectiveState = getEffectiveDeviceState(device);
    if (effectiveState === "on") {
        return "on";
    }
    if (effectiveState === "off") {
        return "off";
    }
    return "";
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
    if (action === "on" || action === "bat" || action === "turn_on" || action === "power.on") return "btn-on";
    if (action === "off" || action === "tat" || action === "turn_off" || action === "power.off") return "btn-off";
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
            placeholder: "Ví dụ: 24",
        },
        "climate.set_mode": {
            requiresValue: true,
            label: "Chế độ",
            hint: "Nhập: cool, dry, heat, fan hoặc auto.",
            placeholder: "Ví dụ: cool",
        },
        "climate.set_fan_speed": {
            requiresValue: true,
            label: "Tốc độ quạt",
            hint: "Nhập: low, medium, high, auto, quiet hoặc turbo.",
            placeholder: "Ví dụ: low",
        },
        "climate.set_swing": {
            requiresValue: true,
            label: "Đảo gió",
            hint: "Nhập: on, off, auto, vertical hoặc horizontal.",
            placeholder: "Ví dụ: on",
        },
        "climate.set_sleep": {
            requiresValue: true,
            label: "Chế độ ngủ",
            hint: "Nhập: on hoặc off.",
            placeholder: "Ví dụ: on",
        },
    };
    return configs[kind] || configs["power.on"];
}

function normalizeSemanticChoice(rawValue, aliases, fieldLabel) {
    const normalized = String(rawValue || "").trim().toLowerCase();
    for (const [canonical, values] of Object.entries(aliases)) {
        if (normalized === canonical || values.includes(normalized)) {
            return canonical;
        }
    }
    throw new Error(`Giá trị ${fieldLabel} chưa hợp lệ.`);
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
    if (normalizedKind === "climate.set_mode") {
        const mode = normalizeSemanticChoice(valueText, {
            cool: ["mat", "lam mat"],
            dry: ["kho", "hut am"],
            heat: ["nong", "suoi"],
            fan: ["quat"],
            auto: ["tu dong"],
        }, "mode");
        return {
            actionKey: `climate.mode.${mode}`,
            semantic: { domain: "climate", operation: "set_mode", mode },
        };
    }
    if (normalizedKind === "climate.set_fan_speed") {
        const fanSpeed = normalizeSemanticChoice(valueText, {
            low: ["thap", "nhe"],
            medium: ["trung binh", "vua"],
            high: ["cao", "manh"],
            auto: ["tu dong"],
            quiet: ["silent", "im"],
            turbo: ["boost"],
        }, "fan_speed");
        return {
            actionKey: `climate.fan.${fanSpeed}`,
            semantic: { domain: "climate", operation: "set_fan_speed", fan_speed: fanSpeed },
        };
    }
    if (normalizedKind === "climate.set_swing") {
        const swing = normalizeSemanticChoice(valueText, {
            on: ["bat"],
            off: ["tat"],
            auto: ["tu dong"],
            vertical: ["doc"],
            horizontal: ["ngang"],
        }, "swing");
        return {
            actionKey: `climate.swing.${swing}`,
            semantic: { domain: "climate", operation: "set_swing", swing },
        };
    }
    if (normalizedKind === "climate.set_sleep") {
        const sleepState = normalizeSemanticChoice(valueText, {
            on: ["bat", "true", "1"],
            off: ["tat", "false", "0"],
        }, "sleep");
        return {
            actionKey: `climate.sleep.${sleepState}`,
            semantic: { domain: "climate", operation: "set_sleep", enabled: sleepState === "on" },
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
    if (kind === "climate.set_mode") {
        return [`bật ${targetName} chế độ ${String(rawValue || "").trim()}`, `${targetName} chế độ ${String(rawValue || "").trim()}`];
    }
    if (kind === "climate.set_fan_speed") {
        return [`bật ${targetName} quạt ${String(rawValue || "").trim()}`, `${targetName} quạt ${String(rawValue || "").trim()}`];
    }
    if (kind === "climate.set_swing") {
        return [`bật ${targetName} đảo gió ${String(rawValue || "").trim()}`, `${targetName} đảo gió ${String(rawValue || "").trim()}`];
    }
    if (kind === "climate.set_sleep") {
        const value = String(rawValue || "").trim().toLowerCase();
        return value === "off"
            ? [`tắt chế độ ngủ ${targetName}`, `${targetName} tắt chế độ ngủ`]
            : [`bật chế độ ngủ ${targetName}`, `${targetName} chế độ ngủ`];
    }
    return [];
}

export function isValidLearnFilename(filename, signalType = "ir") {
    const normalized = normalizeIrFilenameInput(filename);
    const extension = signalType === "rf" ? ".json" : ".bin";
    return normalized.toLowerCase().endsWith(extension) && normalized.length > extension.length;
}
