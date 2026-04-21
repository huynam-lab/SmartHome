import { app } from "./core.js";
import { fetchJson } from "./api.js";
import {
    escapeHtml,
    formatCommandStatus,
    formatActionLabel,
    getEffectiveDeviceState,
    getEffectiveActiveAction,
    getActionButtonClass,
    getDeviceIcon,
    getStatusBannerClass,
    parseMultilinePhrases,
    getIrSemanticConfig,
    buildSemanticActionPayload,
    buildDefaultActionPhrases,
    slugifyVietnameseText,
} from "./utils.js";
import {
    addChatMessage,
    closeDeviceMenus,
    closeSettingsMenu,
    setAddDeviceFeedback,
    setAddFunctionButtonFeedback,
    setChatStatus,
    setDeviceScheduleFeedback,
    setIrLearnModalFeedback,
    setSummaryText,
    toggleDeviceMenu,
} from "./ui.js";

const DEVICE_FUNCTION_STORAGE_KEY = "smarthome.deviceFunctions.v1";
const DEVICE_INVENTORY_CACHE_KEY = "smarthome.deviceInventory.v1";
const LAST_OPENED_DEVICE_KEY = "smarthome.lastOpenedDevice.v1";
const FUNCTION_BUTTON_LONG_PRESS_MS = 1200;
let hasBoundFunctionDeleteDismissListener = false;

function isDeviceControlRoute() {
    return window.location.pathname === "/device-control";
}

function getRequestedDeviceIdFromUrl() {
    return new URLSearchParams(window.location.search).get("device_id") || "";
}

function getRequestedDeviceNameFromUrl() {
    return new URLSearchParams(window.location.search).get("device_name") || "";
}

function buildDeviceControlHref(device) {
    return `/device-control?device_id=${encodeURIComponent(device.id)}&device_name=${encodeURIComponent(device.name || "")}`;
}

function navigateTo(url, { replace = false } = {}) {
    const method = replace ? "replaceState" : "pushState";
    window.history[method]({}, "", url);
}

function setDeviceControlChrome(isActive) {
    document.body.dataset.page = isActive ? "device-control" : "index";
    document.body.classList.toggle("device-control-screen", isActive);
    app.dom.deviceCenterPageEl?.classList.toggle("is-hidden", isActive);
    app.dom.deviceCenterPageEl?.setAttribute("aria-hidden", String(isActive));
    app.dom.deviceControlPageEl?.classList.toggle("is-hidden", !isActive);
    app.dom.deviceControlPageEl?.setAttribute("aria-hidden", String(!isActive));
}

export function syncRouteFromLocation({ render = true } = {}) {
    const isControlView = isDeviceControlRoute();
    const requestedDeviceId = getRequestedDeviceIdFromUrl();
    const requestedDeviceName = getRequestedDeviceNameFromUrl();

    app.state.currentView = isControlView ? "device-control" : "device-center";
    setDeviceControlChrome(isControlView);

    if (!isControlView) {
        app.state.currentDeviceControlId = null;
        return;
    }

    if (requestedDeviceId) {
        app.state.currentDeviceControlId = requestedDeviceId;
    } else if (!app.state.currentDeviceControlId) {
        app.state.currentDeviceControlId = app.state.deviceInventory[0]?.id || null;
    }

    if (requestedDeviceName && !app.state.currentDeviceControlId && app.dom.deviceControlTitleEl) {
        app.dom.deviceControlTitleEl.textContent = requestedDeviceName;
    }

    if (render) {
        renderDeviceControlPage();
    }
}

function readCachedDeviceInventory() {
    try {
        const raw = window.sessionStorage.getItem(DEVICE_INVENTORY_CACHE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        console.warn("[devices] failed to read device inventory cache", error);
        return [];
    }
}

function writeCachedDeviceInventory(devices) {
    try {
        window.sessionStorage.setItem(DEVICE_INVENTORY_CACHE_KEY, JSON.stringify(devices));
    } catch (error) {
        console.warn("[devices] failed to write device inventory cache", error);
    }
}

function cacheOpenedDevice(device) {
    if (!device) {
        return;
    }
    try {
        window.sessionStorage.setItem(LAST_OPENED_DEVICE_KEY, JSON.stringify(device));
    } catch (error) {
        console.warn("[devices] failed to cache opened device", error);
    }
}

function readCachedOpenedDevice() {
    try {
        const raw = window.sessionStorage.getItem(LAST_OPENED_DEVICE_KEY);
        const parsed = raw ? JSON.parse(raw) : null;
        return parsed && typeof parsed === "object" ? parsed : null;
    } catch (error) {
        console.warn("[devices] failed to read opened device cache", error);
        return null;
    }
}

function readPersistedFunctionMap() {
    try {
        const raw = window.localStorage.getItem(DEVICE_FUNCTION_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : {};
        return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
        console.warn("[devices] failed to read function storage", error);
        return {};
    }
}

function writePersistedFunctionMap(storageMap) {
    try {
        window.localStorage.setItem(DEVICE_FUNCTION_STORAGE_KEY, JSON.stringify(storageMap));
    } catch (error) {
        console.warn("[devices] failed to persist function storage", error);
    }
}

function isLightLikeDevice(device) {
    const normalizedType = String(device?.type || "").trim().toLowerCase();
    return normalizedType === "light";
}

function buildFunctionId(name, commandKey = "") {
    const base = slugifyVietnameseText(commandKey || name) || "function";
    return `fn_${base}_${Date.now()}`;
}

function buildFunctionRecord(name, commandKey, options = {}) {
    const normalizedName = String(name || "").trim();
    const normalizedCommandKey = String(commandKey || "").trim();
    return {
        id: options.id || buildFunctionId(normalizedName, normalizedCommandKey),
        name: normalizedName,
        commandKey: normalizedCommandKey,
        backendAction: options.backendAction || normalizedCommandKey,
        learned: Boolean(options.learned),
        source: options.source || "custom",
    };
}

function normalizeActionKey(value) {
    return String(value || "").trim().toLowerCase();
}

function toPreferredLearningActionKey(value) {
    const key = normalizeActionKey(value);
    if (key === "turn_on" || key === "on") {
        return "power.on";
    }
    if (key === "turn_off" || key === "off") {
        return "power.off";
    }
    return key;
}

function expandActionKeyCandidates(value) {
    const key = normalizeActionKey(value);
    if (!key) {
        return [];
    }
    const candidates = new Set([key]);
    if (key === "turn_on" || key === "on") {
        candidates.add("power.on");
    }
    if (key === "turn_off" || key === "off") {
        candidates.add("power.off");
    }
    if (key === "power.on") {
        candidates.add("turn_on");
        candidates.add("on");
    }
    if (key === "power.off") {
        candidates.add("turn_off");
        candidates.add("off");
    }
    if (key.includes("_")) {
        candidates.add(key.replaceAll("_", "."));
    }
    if (key.includes(".")) {
        candidates.add(key.replaceAll(".", "_"));
    }
    return Array.from(candidates);
}

function isFunctionLearned(fn, learnedActionSet) {
    const candidateKeys = [
        ...expandActionKeyCandidates(fn?.backendAction),
        ...expandActionKeyCandidates(fn?.commandKey),
    ];
    return candidateKeys.some((key) => learnedActionSet.has(key));
}

function buildDefaultDeviceFunctions(device) {
    if (!isLightLikeDevice(device)) {
        return [];
    }

    const availableActions = Array.isArray(device.actions) ? device.actions : [];
    const onBackendAction = availableActions.find((action) => ["turn_on", "on", "power.on"].includes(action)) || "turn_on";
    const offBackendAction = availableActions.find((action) => ["turn_off", "off", "power.off"].includes(action)) || "turn_off";
    const hasOnAction = availableActions.some((action) => ["turn_on", "on", "power.on"].includes(action));
    const hasOffAction = availableActions.some((action) => ["turn_off", "off", "power.off"].includes(action));

    return [
        buildFunctionRecord("Bật", "turn_on", {
            id: "fn_on",
            backendAction: onBackendAction,
            learned: hasOnAction,
            source: "default",
        }),
        buildFunctionRecord("Tắt", "turn_off", {
            id: "fn_off",
            backendAction: offBackendAction,
            learned: hasOffAction,
            source: "default",
        }),
    ];
}

function getScheduleActionOptions(device) {
    const availableActions = Array.isArray(device?.actions) ? device.actions : [];
    const actionLabels = device?.action_labels && typeof device.action_labels === "object" ? device.action_labels : {};
    const options = [];
    const onAction = availableActions.find((action) => ["turn_on", "on", "power.on", "bat"].includes(normalizeActionKey(action)));
    const offAction = availableActions.find((action) => ["turn_off", "off", "power.off", "tat"].includes(normalizeActionKey(action)));

    if (onAction) {
        options.push({
            value: onAction,
            label: actionLabels[onAction] || formatActionLabel(onAction),
        });
    }
    if (offAction && normalizeActionKey(offAction) !== normalizeActionKey(onAction)) {
        options.push({
            value: offAction,
            label: actionLabels[offAction] || formatActionLabel(offAction),
        });
    }

    return options;
}

function getCurrentScheduleTimeParts() {
    const now = new Date();
    return {
        hour: String(now.getHours()),
        minute: String(now.getMinutes()),
    };
}

function renderDeviceScheduleActionOptions(device, preferredAction = "") {
    if (!app.dom.deviceScheduleActionInputEl) {
        return false;
    }

    const options = getScheduleActionOptions(device);
    if (!options.length) {
        app.dom.deviceScheduleActionInputEl.innerHTML = '<option value="">Thiết bị chưa có lệnh bật hoặc tắt</option>';
        app.dom.deviceScheduleActionInputEl.value = "";
        app.dom.deviceScheduleActionInputEl.disabled = true;
        if (app.dom.deviceScheduleSubmitBtnEl) {
            app.dom.deviceScheduleSubmitBtnEl.disabled = true;
        }
        return false;
    }

    app.dom.deviceScheduleActionInputEl.innerHTML = ['<option value="">Chế độ</option>', ...options.map((option) => `
        <option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>
    `)].join("");

    const preferredKey = normalizeActionKey(preferredAction);
    const selectedOption = options.find((option) => {
        const optionCandidates = expandActionKeyCandidates(option.value);
        if (optionCandidates.includes(preferredKey)) {
            return true;
        }
        const preferredCandidates = expandActionKeyCandidates(preferredKey);
        return preferredCandidates.some((candidate) => optionCandidates.includes(candidate));
    }) || null;

    app.dom.deviceScheduleActionInputEl.disabled = Boolean(app.state.isScheduleSubmitting);
    app.dom.deviceScheduleActionInputEl.value = selectedOption?.value || "";
    if (app.dom.deviceScheduleSubmitBtnEl) {
        app.dom.deviceScheduleSubmitBtnEl.disabled = Boolean(app.state.isScheduleSubmitting) || !selectedOption;
    }
    return true;
}

function buildFunctionsFromActions(device) {
    const availableActions = Array.isArray(device.actions) ? device.actions : [];
    return availableActions.map((action) => {
        const commandKey = action === "on" || action === "power.on"
            ? "turn_on"
            : action === "off" || action === "power.off"
                ? "turn_off"
                : slugifyVietnameseText(action).replaceAll(".", "_") || action;
        return buildFunctionRecord(device.action_labels?.[action] || formatActionLabel(action), commandKey, {
            id: `fn_${slugifyVietnameseText(action).replaceAll(".", "_") || action}`,
            backendAction: action,
            learned: true,
            source: "backend",
        });
    });
}

function mergeFunctionLists(...lists) {
    const merged = [];
    const indexByKey = new Map();

    lists.flat().forEach((item) => {
        const name = String(item?.name || "").trim();
        const commandKey = String(item?.commandKey || "").trim();
        if (!name || !commandKey) {
            return;
        }
        const dedupeKey = commandKey.toLowerCase();
        const normalizedItem = buildFunctionRecord(name, commandKey, item);
        const existingIndex = indexByKey.get(dedupeKey);

        if (existingIndex === undefined) {
            indexByKey.set(dedupeKey, merged.length);
            merged.push(normalizedItem);
            return;
        }

        const existing = merged[existingIndex];
        const existingSource = String(existing?.source || "").toLowerCase();
        const incomingSource = String(normalizedItem?.source || "").toLowerCase();
        const shouldPreferIncoming = incomingSource === "custom" && existingSource !== "custom";

        // Ưu tiên tên button custom (thường có dấu tiếng Việt) thay vì label auto từ backend.
        if (shouldPreferIncoming) {
            merged[existingIndex] = {
                ...existing,
                ...normalizedItem,
                source: "custom",
            };
        }
    });

    return merged;
}

function getPersistedFunctionsForDevice(deviceId) {
    const storageMap = readPersistedFunctionMap();
    return Array.isArray(storageMap?.[deviceId]) ? storageMap[deviceId] : [];
}

function persistCustomFunctionsForDevice(deviceId, functions) {
    const storageMap = readPersistedFunctionMap();
    storageMap[deviceId] = functions
        .filter((item) => item?.source === "custom")
        .map((item) => ({
            id: item.id,
            name: item.name,
            commandKey: item.commandKey,
            backendAction: item.backendAction || item.commandKey,
            learned: Boolean(item.learned),
            source: "custom",
        }));
    writePersistedFunctionMap(storageMap);
}

function normalizeDevice(device) {
    const learnedActionSet = new Set((Array.isArray(device.actions) ? device.actions : []).map(normalizeActionKey));
    const persistedFunctions = getPersistedFunctionsForDevice(device.id);
    const normalizedFunctions = mergeFunctionLists(
        buildFunctionsFromActions(device),
        Array.isArray(device.functions) ? device.functions : [],
        buildDefaultDeviceFunctions(device),
        persistedFunctions,
    ).map((fn) => buildFunctionRecord(fn.name, fn.commandKey, {
        ...fn,
        learned: isFunctionLearned(fn, learnedActionSet),
    }));

    return {
        ...device,
        functions: normalizedFunctions,
    };
}

function syncDeviceFunctionsMap(devices) {
    app.state.deviceFunctionsMap.clear();
    devices.forEach((device) => {
        app.state.deviceFunctionsMap.set(device.id, Array.isArray(device.functions) ? device.functions : []);
    });
}

function normalizeDeviceInventory(devices = []) {
    const normalizedDevices = Array.isArray(devices) ? devices.map(normalizeDevice) : [];
    syncDeviceFunctionsMap(normalizedDevices);
    return normalizedDevices;
}

function updateDeviceRecord(deviceId, updater) {
    app.state.deviceInventory = app.state.deviceInventory.map((device) => {
        if (String(device.id || "") !== String(deviceId || "")) {
            return device;
        }
        const nextDevice = typeof updater === "function" ? updater(device) : { ...device, ...updater };
        app.state.deviceFunctionsMap.set(nextDevice.id, Array.isArray(nextDevice.functions) ? nextDevice.functions : []);
        return nextDevice;
    });
}

export function getDeviceById(deviceId) {
    return app.state.deviceInventory.find((device) => String(device.id || "") === String(deviceId || "")) || null;
}

function getAddableTemplateOptions() {
    return app.state.irTemplateOptions.filter((template) =>
        app.constants.ADDABLE_TEMPLATE_IDS.has(String(template.id || "").trim())
    );
}

function getLearnableDevices() {
    return app.state.deviceInventory;
}

function padSchedulePart(value) {
    return String(Math.max(0, Number.parseInt(value, 10) || 0)).padStart(2, "0");
}

function renderDeviceScheduleList() {
    if (!app.dom.deviceScheduleListEl) {
        return;
    }
    const schedules = Array.isArray(app.state.deviceSchedules) ? app.state.deviceSchedules : [];
    if (!schedules.length) {
        app.dom.deviceScheduleListEl.innerHTML = '<div class="device-schedule-empty">Chưa có lịch hẹn nào cho thiết bị này.</div>';
        return;
    }

    app.dom.deviceScheduleListEl.innerHTML = schedules.map((schedule) => `
        <article class="device-schedule-card">
            <div class="device-schedule-card-content">
                <strong>${escapeHtml(schedule.action_label || (schedule.action === "power.on" ? "Bật" : "Tắt"))} lúc ${escapeHtml(schedule.time_label || `${padSchedulePart(schedule.hour)}:${padSchedulePart(schedule.minute)}`)}</strong>
                ${schedule.repeat ? `<small>${escapeHtml(schedule.repeat_label || "Lặp lại hằng ngày")}</small>` : ""}
            </div>
            <button type="button" class="device-schedule-delete-btn" data-schedule-delete="${escapeHtml(schedule.id || "")}">
                Xóa
            </button>
        </article>
    `).join("");

    app.dom.deviceScheduleListEl.querySelectorAll("[data-schedule-delete]").forEach((button) => {
        button.addEventListener("click", async () => {
            const scheduleId = String(button.dataset.scheduleDelete || "").trim();
            const deviceId = String(app.state.currentDeviceControlId || "").trim();
            if (!scheduleId || !deviceId) {
                return;
            }
            try {
                await fetchJson(`/api/devices/${encodeURIComponent(deviceId)}/schedules/${encodeURIComponent(scheduleId)}`, {
                    method: "DELETE",
                    headers: { "Content-Type": "application/json" },
                });
                app.state.deviceSchedules = app.state.deviceSchedules.filter((item) => String(item.id || "") !== scheduleId);
                renderDeviceScheduleList();
                setDeviceScheduleFeedback("Đã xóa lịch hẹn.", "success");
            } catch (error) {
                if (!error.isAuth) {
                    setDeviceScheduleFeedback(error.message || "Không xóa được lịch hẹn.");
                }
            }
        });
    });
}

async function loadDeviceSchedules(deviceId) {
    const normalizedDeviceId = String(deviceId || "").trim();
    if (!normalizedDeviceId) {
        app.state.deviceSchedules = [];
        renderDeviceScheduleList();
        return;
    }
    const { result } = await fetchJson(`/api/devices/${encodeURIComponent(normalizedDeviceId)}/schedules`);
    app.state.deviceSchedules = Array.isArray(result.schedules) ? result.schedules : [];
    renderDeviceScheduleList();
}

function setDeviceScheduleLoadingState(loading) {
    app.state.isScheduleSubmitting = loading;
    [
        app.dom.deviceScheduleCancelBtnEl,
        app.dom.deviceScheduleCloseBtnEl,
        app.dom.deviceScheduleHourInputEl,
        app.dom.deviceScheduleMinuteInputEl,
        app.dom.deviceScheduleRepeatInputEl,
    ].forEach((el) => {
        if (el) {
            el.disabled = loading;
        }
    });
    if (app.dom.deviceScheduleActionInputEl) {
        const hasAction = Boolean(String(app.dom.deviceScheduleActionInputEl.value || "").trim());
        app.dom.deviceScheduleActionInputEl.disabled = loading || !hasAction;
    }
    if (app.dom.deviceScheduleSubmitBtnEl) {
        const hasAction = Boolean(String(app.dom.deviceScheduleActionInputEl?.value || "").trim());
        app.dom.deviceScheduleSubmitBtnEl.disabled = loading || !hasAction;
    }
}

export function setDeviceScheduleAction(action) {
    const device = getDeviceById(app.state.currentDeviceControlId);
    renderDeviceScheduleActionOptions(device, action);
}

export function renderAddDeviceTemplateOptions() {
    if (!app.dom.addDeviceTemplateSelectEl) {
        return;
    }
    const optionsMarkup = ['<option value="">Chọn loại thiết bị</option>'];
    getAddableTemplateOptions().forEach((template) => {
        const templateId = escapeHtml(template.id || "");
        const templateName = escapeHtml(template.template_name || templateId);
        optionsMarkup.push(`<option value="${templateId}">${templateName}</option>`);
    });
    app.dom.addDeviceTemplateSelectEl.innerHTML = optionsMarkup.join("");
    app.dom.addDeviceTemplateSelectEl.disabled = getAddableTemplateOptions().length === 0;
}

export function renderIrDeviceOptions() {
    return;
}

export function updateIrSemanticForm() {
    const config = getIrSemanticConfig(String(app.dom.irSemanticKindSelectEl?.value || "power.on"));
    const requiresValue = Boolean(config.requiresValue);

    app.dom.irSemanticValueFieldEl?.classList.toggle("is-hidden", !requiresValue);
    if (app.dom.irSemanticValueLabelEl) app.dom.irSemanticValueLabelEl.textContent = config.label || "Giá trị";
    if (app.dom.irSemanticValueHintEl) app.dom.irSemanticValueHintEl.textContent = config.hint || "";
    if (app.dom.irSemanticValueInputEl) {
        app.dom.irSemanticValueInputEl.required = requiresValue;
        app.dom.irSemanticValueInputEl.placeholder = config.placeholder || "";
        if (!requiresValue) {
            app.dom.irSemanticValueInputEl.value = "";
        }
    }
}

export function updateIrSignalTypeForm() {
    const signalType = String(app.dom.irSignalTypeSelectEl?.value || "ir").trim().toLowerCase();
    const isRf = signalType === "rf";
    app.dom.irRfFrequencyFieldEl?.classList.toggle("is-hidden", !isRf);
    if (app.dom.irRfFrequencySelectEl) {
        app.dom.irRfFrequencySelectEl.required = isRf;
        if (!isRf) {
            app.dom.irRfFrequencySelectEl.value = "";
        }
    }
}

export function syncIrDeviceSelection(deviceId = "") {
    const selectedDevice = getDeviceById(deviceId);
    if (!selectedDevice) {
        if (app.dom.irCurrentDeviceNameEl) app.dom.irCurrentDeviceNameEl.textContent = "Thiết bị hiện tại";
        if (app.dom.irSignalTypeSelectEl) app.dom.irSignalTypeSelectEl.value = "ir";
        if (app.dom.irRfFrequencySelectEl) app.dom.irRfFrequencySelectEl.value = "";
        updateIrSignalTypeForm();
        return;
    }

    if (app.dom.irCurrentDeviceNameEl) app.dom.irCurrentDeviceNameEl.textContent = selectedDevice.name || selectedDevice.id || "Thiết bị hiện tại";
    if (app.dom.irSignalTypeSelectEl) {
        const signalType = String(selectedDevice.control_type || "").trim().toLowerCase();
        app.dom.irSignalTypeSelectEl.value = signalType === "rf" ? "rf" : "ir";
    }
    if (app.dom.irRfFrequencySelectEl) {
        const rfFrequency = String(selectedDevice.rf_frequency || "").trim();
        app.dom.irRfFrequencySelectEl.value = rfFrequency === "315" || rfFrequency === "433" ? rfFrequency : "";
    }
    updateIrSignalTypeForm();
}

export async function loadIrTemplateOptions() {
    if (!app.state.isAuthenticated || app.state.irTemplateOptions.length > 0) {
        renderAddDeviceTemplateOptions();
        return;
    }

    if (app.dom.addDeviceTemplateSelectEl) {
        app.dom.addDeviceTemplateSelectEl.innerHTML = '<option value="">Đang tải danh sách mẫu thiết bị...</option>';
        app.dom.addDeviceTemplateSelectEl.disabled = true;
    }

    try {
        const { result } = await fetchJson("/api/device-templates");
        app.state.irTemplateOptions = Array.isArray(result.templates) ? result.templates : [];
        renderAddDeviceTemplateOptions();
    } catch (error) {
        app.state.irTemplateOptions = [];
        if (app.dom.addDeviceTemplateSelectEl) {
            app.dom.addDeviceTemplateSelectEl.innerHTML = '<option value="">Không tải được danh sách mẫu thiết bị</option>';
            app.dom.addDeviceTemplateSelectEl.disabled = true;
        }
        setAddDeviceFeedback(error.message || "Không tải được danh sách mẫu thiết bị.");
    }
}

export function openAddDeviceModal() {
    if (!app.state.isAuthenticated || app.state.isAddDeviceSubmitting) {
        return;
    }
    closeSettingsMenu();
    setAddDeviceFeedback("");
    app.dom.addDeviceFormEl?.reset();
    renderAddDeviceTemplateOptions();
    app.dom.addDeviceModalEl?.classList.add("is-visible");
    app.dom.addDeviceModalEl?.setAttribute("aria-hidden", "false");
    loadIrTemplateOptions().finally(() => window.setTimeout(() => app.dom.addDeviceTemplateSelectEl?.focus(), 0));
}

export function closeAddDeviceModal() {
    if (app.state.isAddDeviceSubmitting) {
        return;
    }
    app.dom.addDeviceModalEl?.classList.remove("is-visible");
    app.dom.addDeviceModalEl?.setAttribute("aria-hidden", "true");
    app.dom.addDeviceFormEl?.reset();
    setAddDeviceFeedback("");
}

export function openIrLearnModal() {
    if (!app.state.isAuthenticated || app.state.isLearningIr || !app.state.currentDeviceControlId) {
        return;
    }
    app.state.pendingLearnContext = null;
    closeSettingsMenu();
    setIrLearnModalFeedback("");
    app.dom.irLearnFormEl?.reset();
    if (app.dom.irSemanticKindSelectEl) app.dom.irSemanticKindSelectEl.value = "power.on";
    if (app.dom.irSignalTypeSelectEl) app.dom.irSignalTypeSelectEl.value = "ir";
    if (app.dom.irRfFrequencySelectEl) app.dom.irRfFrequencySelectEl.value = "";
    updateIrSemanticForm();
    syncIrDeviceSelection(app.state.currentDeviceControlId);
    setIrLearnModalMode("learn");
    app.dom.irLearnModalEl?.classList.add("is-visible");
    app.dom.irLearnModalEl?.setAttribute("aria-hidden", "false");
    window.setTimeout(() => app.dom.irSignalTypeSelectEl?.focus(), 0);
}

export function closeIrLearnModal({ force = false } = {}) {
    if (app.state.isLearningIr && !force) {
        return;
    }
    app.state.pendingLearnContext = null;
    app.dom.irLearnModalEl?.classList.remove("is-visible");
    app.dom.irLearnModalEl?.setAttribute("aria-hidden", "true");
    app.dom.irLearnFormEl?.reset();
    setIrLearnModalMode("learn");
    updateIrSemanticForm();
    updateIrSignalTypeForm();
    setIrLearnModalFeedback("");
}

function setIrLearnLoadingState(loading) {
    app.state.isLearningIr = loading;
    [
        app.dom.irStartBtnEl,
        app.dom.irCancelBtnEl,
        app.dom.irLearnCloseBtnEl,
        app.dom.irSemanticKindSelectEl,
        app.dom.irSignalTypeSelectEl,
        app.dom.irRfFrequencySelectEl,
        app.dom.irSemanticValueInputEl,
        app.dom.irActionPhrasesInputEl,
    ].forEach((el) => {
        if (el) {
            el.disabled = loading;
        }
    });
    if (!loading) {
        setIrLearnModalMode(String(app.state.pendingLearnContext?.mode || "").trim().toLowerCase() === "edit" ? "edit" : "learn");
    }
}

function setAddDeviceLoadingState(loading) {
    app.state.isAddDeviceSubmitting = loading;
    [
        app.dom.addDeviceSubmitBtnEl,
        app.dom.addDeviceCancelBtnEl,
        app.dom.addDeviceCloseBtnEl,
        app.dom.addDeviceTemplateSelectEl,
        app.dom.addDeviceNameInputEl,
    ].forEach((el) => {
        if (el) {
            el.disabled = loading;
        }
    });
}

function setAddFunctionButtonLoadingState(loading) {
    [
        app.dom.addFunctionButtonSubmitBtnEl,
        app.dom.addFunctionButtonCancelBtnEl,
        app.dom.addFunctionButtonCloseBtnEl,
        app.dom.addFunctionButtonNameInputEl,
    ].forEach((el) => {
        if (el) {
            el.disabled = loading;
        }
    });
}

function buildDeviceCard(device) {
    const currentState = getEffectiveDeviceState(device);
    const deviceControlHref = buildDeviceControlHref(device);

    return `
        <article class="device-card ${currentState === "on" ? "is-on" : ""}" data-device-id="${escapeHtml(device.id)}">
            <a class="device-card-main" href="${escapeHtml(deviceControlHref)}" aria-label="Mở điều khiển cho ${escapeHtml(device.name)}">
                <div class="device-card-top">
                    <div class="device-title-group">
                        <div class="device-icon">${getDeviceIcon(device)}</div>
                        <div>
                            <h3>${escapeHtml(device.name)}</h3>
                        </div>
                    </div>
                </div>
            </a>
            <div class="device-card-tools">
                <div class="device-card-menu-anchor" data-device-menu-anchor>
                    <button type="button" class="settings-btn device-card-settings-btn" aria-label="Mở tác vụ cho ${escapeHtml(device.name)}" aria-haspopup="menu" aria-expanded="false" data-device-menu-btn>
                        <span class="settings-gear" aria-hidden="true">
                            <svg viewBox="0 0 24 24" class="settings-gear-icon" focusable="false">
                                <path fill="currentColor" d="M19.14 12.94c.04-.31.06-.62.06-.94s-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.25 7.25 0 0 0-1.63-.94l-.36-2.54a.5.5 0 0 0-.49-.42h-3.84a.5.5 0 0 0-.49.42l-.36 2.54c-.58.22-1.12.53-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.7 8.84a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.62-.06.94s.02.63.06.94L2.82 14.52a.5.5 0 0 0-.12.64l1.92 3.32a.5.5 0 0 0 .6.22l2.39-.96c.5.41 1.05.72 1.63.94l.36 2.54a.5.5 0 0 0 .49.42h3.84a.5.5 0 0 0 .49-.42l.36-2.54c.58-.22 1.12-.53 1.63-.94l2.39.96a.5.5 0 0 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7Z" />
                            </svg>
                        </span>
                    </button>
                    <div class="settings-menu device-card-menu" role="menu" aria-hidden="true" data-device-menu>
                        <button type="button" class="settings-menu-item danger" role="menuitem" data-device-delete="${escapeHtml(device.id)}">
                            Xóa thiết bị
                        </button>
                    </div>
                </div>
            </div>
        </article>
    `;
}

function buildDeviceFunctionButtonMarkup(deviceId, fn, disabled = false) {
    const isLearned = Boolean(fn.learned);
    return `
        <div class="device-function-item" data-function-item>
            <button
                type="button"
                class="action-btn ${getActionButtonClass(fn.commandKey)} device-function-btn ${isLearned ? "" : "is-unlearned"}"
                data-device-function="${escapeHtml(deviceId)}"
                data-function-id="${escapeHtml(fn.id || "")}"
                data-command-key="${escapeHtml(fn.commandKey || "")}"
                data-backend-action="${escapeHtml(fn.backendAction || fn.commandKey || "")}"
                data-function-name="${escapeHtml(fn.name || "Function")}"
                data-function-source="${escapeHtml(fn.source || "custom")}"
                data-function-learned="${isLearned ? "true" : "false"}"
                ${disabled ? "disabled" : ""}
            >
                ${escapeHtml(fn.name || "Function")}
            </button>
            <div class="device-function-tools">
                ${isLearned ? `
                    <button
                        type="button"
                        class="device-function-edit-btn"
                        data-function-edit="${escapeHtml(deviceId)}"
                        data-function-id="${escapeHtml(fn.id || "")}"
                        data-command-key="${escapeHtml(fn.commandKey || "")}"
                        data-backend-action="${escapeHtml(fn.backendAction || fn.commandKey || "")}"
                        data-function-name="${escapeHtml(fn.name || "Function")}"
                    >
                        Sửa
                    </button>
                ` : ""}
                <button
                    type="button"
                    class="device-function-delete-btn"
                    data-function-delete="${escapeHtml(deviceId)}"
                    data-function-id="${escapeHtml(fn.id || "")}"
                    data-command-key="${escapeHtml(fn.commandKey || "")}"
                    data-backend-action="${escapeHtml(fn.backendAction || fn.commandKey || "")}"
                    data-function-name="${escapeHtml(fn.name || "Function")}"
                    data-function-source="${escapeHtml(fn.source || "custom")}"
                    data-function-learned="${isLearned ? "true" : "false"}"
                >
                    Xóa nút
                </button>
            </div>
        </div>
    `;
}

function prefillSemanticFromActionKey(actionKey) {
    const normalizedAction = normalizeActionKey(actionKey);
    if (["power.on", "turn_on", "on"].includes(normalizedAction)) {
        app.dom.irSemanticKindSelectEl.value = "power.on";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = "";
        return;
    }
    if (["power.off", "turn_off", "off"].includes(normalizedAction)) {
        app.dom.irSemanticKindSelectEl.value = "power.off";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = "";
        return;
    }
    const timerMatch = normalizedAction.match(/(?:timer[._])?off_after_(\d+)_min/);
    if (timerMatch) {
        app.dom.irSemanticKindSelectEl.value = "timer.off_after";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = timerMatch[1];
        return;
    }
    const temperatureMatch = normalizedAction.match(/climate[._]set[_]?(\d+)c/);
    if (temperatureMatch) {
        app.dom.irSemanticKindSelectEl.value = "climate.set_temperature";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = temperatureMatch[1];
        return;
    }
    const modeMatch = normalizedAction.match(/(?:climate[._])?mode[._]([a-z0-9_]+)/);
    if (modeMatch) {
        app.dom.irSemanticKindSelectEl.value = "climate.set_mode";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = modeMatch[1];
        return;
    }
    const fanMatch = normalizedAction.match(/(?:climate[._])?(?:fan|fan_speed)[._]([a-z0-9_]+)/);
    if (fanMatch) {
        app.dom.irSemanticKindSelectEl.value = "climate.set_fan_speed";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = fanMatch[1];
        return;
    }
    const swingMatch = normalizedAction.match(/(?:climate[._])?swing[._]([a-z0-9_]+)/);
    if (swingMatch) {
        app.dom.irSemanticKindSelectEl.value = "climate.set_swing";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = swingMatch[1];
        return;
    }
    const sleepMatch = normalizedAction.match(/(?:climate[._])?sleep[._]([a-z0-9_]+)/);
    if (sleepMatch) {
        app.dom.irSemanticKindSelectEl.value = "climate.set_sleep";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = sleepMatch[1];
    }
}

function getActionDetails(device, actionKey) {
    if (!device) {
        return null;
    }
    const actionDetails = device.action_details && typeof device.action_details === "object" ? device.action_details : {};
    return actionDetails[actionKey] || null;
}

function prefillSemanticFromActionDetail(actionDetail, actionKey = "") {
    const semantic = actionDetail?.semantic && typeof actionDetail.semantic === "object" ? actionDetail.semantic : {};
    const operation = String(semantic.operation || "").trim().toLowerCase();
    if (operation === "on") {
        app.dom.irSemanticKindSelectEl.value = "power.on";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = "";
        return;
    }
    if (operation === "off") {
        app.dom.irSemanticKindSelectEl.value = "power.off";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = "";
        return;
    }
    if (operation === "off_after") {
        app.dom.irSemanticKindSelectEl.value = "timer.off_after";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = String(Math.max(1, Math.round(Number(semantic.duration_seconds || 0) / 60)));
        return;
    }
    if (operation === "set_temperature") {
        app.dom.irSemanticKindSelectEl.value = "climate.set_temperature";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = String(semantic.temperature_c || "");
        return;
    }
    if (operation === "set_mode") {
        app.dom.irSemanticKindSelectEl.value = "climate.set_mode";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = String(semantic.mode || "");
        return;
    }
    if (operation === "set_fan_speed") {
        app.dom.irSemanticKindSelectEl.value = "climate.set_fan_speed";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = String(semantic.fan_speed || "");
        return;
    }
    if (operation === "set_swing") {
        app.dom.irSemanticKindSelectEl.value = "climate.set_swing";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = String(semantic.swing || "");
        return;
    }
    if (operation === "set_sleep") {
        app.dom.irSemanticKindSelectEl.value = "climate.set_sleep";
        if (app.dom.irSemanticValueInputEl) app.dom.irSemanticValueInputEl.value = semantic.enabled ? "on" : "off";
        return;
    }
    prefillSemanticFromActionKey(actionKey);
}

function setIrLearnModalMode(mode = "learn", functionName = "") {
    const isEditMode = mode === "edit";
    if (app.dom.irLearnModalTitleEl) {
        app.dom.irLearnModalTitleEl.textContent = isEditMode ? "Sửa semantic" : "Học lệnh";
    }
    if (app.dom.irStartBtnEl) {
        app.dom.irStartBtnEl.textContent = isEditMode ? "Lưu thay đổi" : "Bắt đầu học";
    }
    if (app.dom.irSignalTypeSelectEl) {
        app.dom.irSignalTypeSelectEl.disabled = isEditMode || app.state.isLearningIr;
    }
    if (app.dom.irRfFrequencySelectEl) {
        app.dom.irRfFrequencySelectEl.disabled = isEditMode || app.state.isLearningIr;
    }
    if (app.dom.irCurrentDeviceNameEl && functionName && isEditMode) {
        app.dom.irCurrentDeviceNameEl.textContent = `${app.dom.irCurrentDeviceNameEl.textContent} • ${functionName}`;
    }
}

function openIrLearnModalForFunction(device, fn) {
    if (!device || !fn) {
        return;
    }
    openIrLearnModal();
    app.state.pendingLearnContext = {
        mode: "learn",
        deviceId: String(device.id || ""),
        actionKey: toPreferredLearningActionKey(fn.backendAction || fn.commandKey || ""),
        functionName: String(fn.name || "").trim(),
    };

    syncIrDeviceSelection(device.id);
    prefillSemanticFromActionKey(fn.backendAction || fn.commandKey || "");
    updateIrSemanticForm();
    setIrLearnModalMode("learn");

    setIrLearnModalFeedback("");
}

function openIrEditModalForFunction(device, fn) {
    if (!device || !fn) {
        return;
    }
    const backendAction = String(fn.backendAction || fn.commandKey || "").trim();
    const actionDetail = getActionDetails(device, backendAction);
    if (!actionDetail) {
        setChatStatus("Không tìm thấy metadata của action để chỉnh sửa", "error");
        return;
    }

    openIrLearnModal();
    app.state.pendingLearnContext = {
        mode: "edit",
        deviceId: String(device.id || ""),
        actionKey: backendAction,
        functionName: String(fn.name || "").trim(),
    };

    syncIrDeviceSelection(device.id);
    if (app.dom.irSignalTypeSelectEl) {
        app.dom.irSignalTypeSelectEl.value = String(actionDetail.type || device.control_type || "ir").trim().toLowerCase() === "rf" ? "rf" : "ir";
    }
    if (app.dom.irRfFrequencySelectEl) {
        const rfValue = String(actionDetail.rf_frequency || device.rf_frequency || "").trim();
        app.dom.irRfFrequencySelectEl.value = rfValue === "315" || rfValue === "433" ? rfValue : "";
    }
    prefillSemanticFromActionDetail(actionDetail, backendAction);
    if (app.dom.irActionPhrasesInputEl) {
        app.dom.irActionPhrasesInputEl.value = Array.isArray(actionDetail.phrases) ? actionDetail.phrases.join("\n") : "";
    }
    updateIrSemanticForm();
    updateIrSignalTypeForm();
    setIrLearnModalMode("edit", fn.name || backendAction);
    setIrLearnModalFeedback("");
}

function clearFunctionDeleteArmedState(exceptItem = null) {
    app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-function-item].is-delete-armed").forEach((item) => {
        if (exceptItem && item === exceptItem) {
            return;
        }
        item.classList.remove("is-delete-armed");
    });
}

function removeFunctionLocally(deviceId, functionId, commandKey) {
    const device = getDeviceById(deviceId);
    if (!device) {
        return null;
    }

    const currentFunctions = Array.isArray(device.functions) ? device.functions : [];
    const nextFunctions = currentFunctions.filter((fn) => {
        const sameId = functionId && String(fn.id || "") === String(functionId || "");
        const sameCommand = commandKey && String(fn.commandKey || "").toLowerCase() === String(commandKey || "").toLowerCase();
        return !(sameId || sameCommand);
    });

    updateDeviceRecord(deviceId, (current) => ({ ...current, functions: nextFunctions }));
    persistCustomFunctionsForDevice(deviceId, nextFunctions);
    app.state.deviceStateMap.set(deviceId, getDeviceById(deviceId));
    renderDevices(app.state.deviceInventory);
    return getDeviceById(deviceId);
}

async function handleDeleteFunctionButton({ deviceId, functionId, functionName, commandKey, backendAction, learned }) {
    const device = getDeviceById(deviceId);
    if (!device) {
        return;
    }

    const normalizedFunctionName = String(functionName || "nút").trim();
    const normalizedBackendAction = String(backendAction || commandKey || "").trim();
    const isLearned = Boolean(learned);
    const isLocalOnly = !isLearned;

    const confirmed = window.confirm(
        isLearned
            ? `Xóa nút "${normalizedFunctionName}"?\n\nHệ thống sẽ xóa action đã học khỏi thiết bị và xóa file IR/RF liên quan nếu không còn action nào dùng chung.`
            : `Xóa nút "${normalizedFunctionName}" khỏi giao diện điều khiển?`
    );
    if (!confirmed) {
        return;
    }

    setChatStatus(`Đang xóa nút ${normalizedFunctionName}...`, "processing");

    try {
        if (isLocalOnly) {
            removeFunctionLocally(deviceId, functionId, commandKey);
            setChatStatus("Đã xóa nút chức năng", "live");
            addChatMessage("system", `Đã xóa nút "${normalizedFunctionName}" trên ${device.name || deviceId}.`, Date.now(), {
                fingerprint: `device-function-local-delete-${deviceId}-${functionId || commandKey}`,
            });
            return;
        }

        const { result } = await fetchJson(
            `/api/devices/${encodeURIComponent(deviceId)}/actions/${encodeURIComponent(normalizedBackendAction)}`,
            {
                method: "DELETE",
                headers: { "Content-Type": "application/json" },
            }
        );
        removeFunctionLocally(deviceId, functionId, commandKey);
        await loadDevices();

        const deletedSummary = Array.isArray(result.deleted_files) && result.deleted_files.length
            ? ` File đã xóa: ${result.deleted_files.join(", ")}.`
            : "";
        const skippedSummary = Array.isArray(result.skipped_files) && result.skipped_files.length
            ? ` File giữ lại vì còn action khác dùng: ${result.skipped_files.join(", ")}.`
            : "";
        setChatStatus("Đã xóa nút chức năng", "live");
        addChatMessage("system", `${result.message || `Đã xóa nút ${normalizedFunctionName}.`}${deletedSummary}${skippedSummary}`, Date.now(), {
            fingerprint: `device-function-delete-${deviceId}-${normalizedBackendAction}`,
        });
    } catch (error) {
        if (!error.isAuth) {
            setChatStatus("Không xóa được nút chức năng", "error");
            addChatMessage("system", `Không xóa được nút "${normalizedFunctionName}": ${error.message}`, Date.now(), {
                isError: true,
                fingerprint: `device-function-delete-error-${deviceId}-${normalizedBackendAction || commandKey}`,
            });
        }
    }
}

function renderDeviceControlPage() {
    const device = getDeviceById(app.state.currentDeviceControlId);
    if (!device || !app.dom.deviceControlPageEl) {
        if (isDeviceControlRoute()) {
            if (app.dom.deviceControlFunctionsEl) {
                app.dom.deviceControlFunctionsEl.innerHTML = '<div class="empty-device-actions">Không tìm thấy thiết bị cần điều khiển.</div>';
            }
        } else {
            closeDeviceControlPage({ navigate: false });
        }
        return;
    }

    const currentState = getEffectiveDeviceState(device);
    const displayState = formatCommandStatus(device);
    const functions = Array.isArray(device.functions) ? device.functions : [];

    app.dom.deviceControlTitleEl.textContent = device.name || "Thiết bị";
    app.dom.deviceControlSubtitleEl.textContent = `${device.type_label || device.type || "Thiết bị"} • ${device.brand || "unknown"} / ${device.control_type || "unknown"}`;
    app.dom.deviceControlStatusTextEl.textContent = displayState;
    app.dom.deviceControlStatusBannerEl.className = getStatusBannerClass(currentState, false);
    app.dom.deviceControlFunctionsEl.innerHTML = functions.length
        ? functions.map((fn) => buildDeviceFunctionButtonMarkup(device.id, fn)).join("")
        : '<div class="empty-device-actions">Thiết bị này chưa có function button. Hãy thêm button đầu tiên ở cuối trang.</div>';

    bindDeviceControlActions();
    updateDeviceActionButtons(device.id, device, false);
}

function bindDeviceControlActions() {
    if (!hasBoundFunctionDeleteDismissListener) {
        document.addEventListener("pointerdown", (event) => {
            const target = event.target;
            if (target instanceof Node && target.closest("[data-function-item]")) {
                return;
            }
            clearFunctionDeleteArmedState();
        });
        hasBoundFunctionDeleteDismissListener = true;
    }

    app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-device-function]").forEach((button) => {
        let longPressTimer = null;

        const clearLongPressTimer = () => {
            if (longPressTimer) {
                window.clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        };

        button.addEventListener("pointerdown", (event) => {
            if (button.disabled) {
                return;
            }
            if (event.pointerType === "mouse" && event.button !== 0) {
                return;
            }
            clearLongPressTimer();
            longPressTimer = window.setTimeout(() => {
                const functionItem = button.closest("[data-function-item]");
                if (!functionItem) {
                    return;
                }
                clearFunctionDeleteArmedState(functionItem);
                functionItem.classList.add("is-delete-armed");
                button.dataset.longPressTriggered = "true";
                if (typeof navigator.vibrate === "function") {
                    navigator.vibrate(25);
                }
            }, FUNCTION_BUTTON_LONG_PRESS_MS);
        });

        button.addEventListener("pointerup", clearLongPressTimer);
        button.addEventListener("pointercancel", clearLongPressTimer);
        button.addEventListener("pointerleave", clearLongPressTimer);
        button.addEventListener("contextmenu", (event) => event.preventDefault());

        button.addEventListener("click", () => {
            if (button.dataset.longPressTriggered === "true") {
                button.dataset.longPressTriggered = "false";
                return;
            }
            if (button.disabled) {
                return;
            }
            clearFunctionDeleteArmedState();
            const deviceId = button.dataset.deviceFunction;
            const commandKey = button.dataset.commandKey;
            const backendAction = button.dataset.backendAction || commandKey;
            const functionName = button.dataset.functionName || commandKey || "Function";
            const functionLearned = button.dataset.functionLearned === "true";

            if (!functionLearned) {
                const device = getDeviceById(deviceId);
                openIrLearnModalForFunction(device, {
                    name: functionName,
                    commandKey,
                    backendAction,
                });
                return;
            }

            sendDeviceCommand(deviceId, backendAction, button, { commandKey });
        });
    });

    app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-function-delete]").forEach((deleteBtn) => {
        deleteBtn.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();
            const functionItem = deleteBtn.closest("[data-function-item]");
            if (!functionItem?.classList.contains("is-delete-armed")) {
                return;
            }

            clearFunctionDeleteArmedState();
            await handleDeleteFunctionButton({
                deviceId: String(deleteBtn.dataset.functionDelete || ""),
                functionId: String(deleteBtn.dataset.functionId || ""),
                functionName: String(deleteBtn.dataset.functionName || ""),
                commandKey: String(deleteBtn.dataset.commandKey || ""),
                backendAction: String(deleteBtn.dataset.backendAction || ""),
                learned: deleteBtn.dataset.functionLearned === "true",
            });
        });
    });

    app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-function-edit]").forEach((editBtn) => {
        editBtn.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const deviceId = String(editBtn.dataset.functionEdit || "");
            const device = getDeviceById(deviceId);
            if (!device) {
                return;
            }
            openIrEditModalForFunction(device, {
                id: String(editBtn.dataset.functionId || ""),
                name: String(editBtn.dataset.functionName || ""),
                commandKey: String(editBtn.dataset.commandKey || ""),
                backendAction: String(editBtn.dataset.backendAction || ""),
                learned: true,
            });
        });
    });
}

function renderDeviceControlSkeleton(device) {
    if (!device || !app.dom.deviceControlPageEl) {
        return;
    }
    const currentState = getEffectiveDeviceState(device);
    const displayState = formatCommandStatus(device);
    const functions = Array.isArray(device.functions) ? device.functions : [];

    app.dom.deviceControlTitleEl.textContent = device.name || "Thiết bị";
    app.dom.deviceControlSubtitleEl.textContent = `${device.type_label || device.type || "Thiết bị"} • ${device.brand || "unknown"} / ${device.control_type || "unknown"}`;
    app.dom.deviceControlStatusTextEl.textContent = displayState;
    app.dom.deviceControlStatusBannerEl.className = getStatusBannerClass(currentState, false);
    app.dom.deviceControlFunctionsEl.innerHTML = functions.length
        ? functions.map((fn) => buildDeviceFunctionButtonMarkup(device.id, fn)).join("")
        : '<div class="empty-device-actions">Đang tải điều khiển thiết bị...</div>';

    bindDeviceControlActions();
    updateDeviceActionButtons(device.id, device, false);
}

export function openDeviceControlPage(deviceId) {
    const device = getDeviceById(deviceId);
    if (!device) {
        return;
    }
    cacheOpenedDevice(device);
    closeDeviceMenus();
    app.state.currentDeviceControlId = device.id;
    navigateTo(buildDeviceControlHref(device));
    syncRouteFromLocation();
    window.setTimeout(() => app.dom.deviceControlBackBtnEl?.focus(), 0);
}

export function closeDeviceControlPage({ navigate = true } = {}) {
    if (navigate && isDeviceControlRoute()) {
        navigateTo("/index");
        syncRouteFromLocation({ render: false });
        return;
    }
    app.state.currentView = "device-center";
    app.state.currentDeviceControlId = null;
    setDeviceControlChrome(false);
}

export function openAddFunctionButtonModal() {
    if (!app.state.isAuthenticated || !app.state.currentDeviceControlId) {
        return;
    }
    setAddFunctionButtonFeedback("");
    app.dom.addFunctionButtonFormEl?.reset();
    app.dom.addFunctionButtonModalEl?.classList.add("is-visible");
    app.dom.addFunctionButtonModalEl?.setAttribute("aria-hidden", "false");
    window.setTimeout(() => app.dom.addFunctionButtonNameInputEl?.focus(), 0);
}

export function closeAddFunctionButtonModal() {
    app.dom.addFunctionButtonModalEl?.classList.remove("is-visible");
    app.dom.addFunctionButtonModalEl?.setAttribute("aria-hidden", "true");
    app.dom.addFunctionButtonFormEl?.reset();
    setAddFunctionButtonFeedback("");
    setAddFunctionButtonLoadingState(false);
}

export async function openDeviceScheduleModal() {
    if (!app.state.isAuthenticated || !app.state.currentDeviceControlId || app.state.isScheduleSubmitting) {
        return;
    }
    const device = getDeviceById(app.state.currentDeviceControlId);
    if (!device) {
        return;
    }

    setDeviceScheduleFeedback("");
    app.dom.deviceScheduleFormEl?.reset();
    if (app.dom.deviceScheduleDeviceNameEl) {
        app.dom.deviceScheduleDeviceNameEl.textContent = device.name || device.id || "Thiết bị hiện tại";
    }
    const currentTimeParts = getCurrentScheduleTimeParts();
    if (app.dom.deviceScheduleHourInputEl) {
        app.dom.deviceScheduleHourInputEl.value = currentTimeParts.hour;
    }
    if (app.dom.deviceScheduleMinuteInputEl) {
        app.dom.deviceScheduleMinuteInputEl.value = currentTimeParts.minute;
    }
    if (app.dom.deviceScheduleRepeatInputEl) {
        app.dom.deviceScheduleRepeatInputEl.checked = false;
    }
    const hasSupportedScheduleAction = renderDeviceScheduleActionOptions(device);
    if (!hasSupportedScheduleAction) {
        setDeviceScheduleFeedback("Thiết bị này chưa có action bật/tắt để hẹn giờ.");
    }
    app.state.deviceSchedules = [];
    renderDeviceScheduleList();

    app.dom.deviceScheduleModalEl?.classList.add("is-visible");
    app.dom.deviceScheduleModalEl?.setAttribute("aria-hidden", "false");
    window.setTimeout(() => app.dom.deviceScheduleHourInputEl?.focus(), 0);

    try {
        await loadDeviceSchedules(device.id);
    } catch (error) {
        if (!error.isAuth) {
            setDeviceScheduleFeedback(error.message || "Không tải được danh sách lịch hẹn.");
        }
    }
}

export function closeDeviceScheduleModal() {
    if (app.state.isScheduleSubmitting) {
        return;
    }
    app.dom.deviceScheduleModalEl?.classList.remove("is-visible");
    app.dom.deviceScheduleModalEl?.setAttribute("aria-hidden", "true");
    app.dom.deviceScheduleFormEl?.reset();
    app.state.deviceSchedules = [];
    renderDeviceScheduleList();
    setDeviceScheduleFeedback("");
    setDeviceScheduleLoadingState(false);
}

export function renderDevices(devices) {
    app.state.deviceStateMap.clear();
    syncRouteFromLocation({ render: false });
    if (!devices.length) {
        app.dom.deviceListEl.innerHTML = '<p class="empty-state">Chưa có thiết bị nào trong hệ thống.</p>';
        setSummaryText("0 thiết bị");
        if (app.dom.deviceControlFunctionsEl) {
            app.dom.deviceControlFunctionsEl.innerHTML = '<div class="empty-device-actions">Chưa có thiết bị nào trong hệ thống.</div>';
        }
        return;
    }
    devices.forEach((device) => app.state.deviceStateMap.set(device.id, device));
    app.dom.deviceListEl.innerHTML = devices.map((device) => buildDeviceCard(device)).join("");
    setSummaryText(`${devices.length} thiết bị khả dụng`);
    bindDeviceActions();
    renderDeviceControlPage();
}

export function hydrateCachedDevices() {
    const cachedDevices = normalizeDeviceInventory(readCachedDeviceInventory());
    if (cachedDevices.length) {
        app.state.deviceInventory = cachedDevices;
        renderIrDeviceOptions();
        renderDevices(app.state.deviceInventory);
        return true;
    }

    if (isDeviceControlRoute()) {
        const cachedOpenedDevice = readCachedOpenedDevice();
        if (cachedOpenedDevice) {
            app.state.currentDeviceControlId = getRequestedDeviceIdFromUrl() || cachedOpenedDevice.id || null;
            syncRouteFromLocation({ render: false });
            renderDeviceControlSkeleton(normalizeDevice(cachedOpenedDevice));
            return true;
        }
    }

    return false;
}

function bindDeviceActions() {
    document.querySelectorAll(".device-card-main[href]").forEach((link) => {
        const cacheFromLink = () => {
            const card = link.closest("[data-device-id]");
            const deviceId = card?.dataset.deviceId;
            if (!deviceId) {
                return;
            }
            const device = getDeviceById(deviceId);
            if (device) {
                cacheOpenedDevice(device);
            }
        };
        link.addEventListener("pointerdown", cacheFromLink, { passive: true });
        link.addEventListener("click", (event) => {
            event.preventDefault();
            cacheFromLink();
            const card = link.closest("[data-device-id]");
            const deviceId = String(card?.dataset.deviceId || "");
            if (deviceId) {
                openDeviceControlPage(deviceId);
            }
        });
    });

    document.querySelectorAll("[data-device-menu-btn]").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            toggleDeviceMenu(button);
        });
    });

    document.querySelectorAll("[data-device-delete]").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            handleDeleteDevice(button.dataset.deviceDelete);
        });
    });
}

export async function loadDevices() {
    if (!app.state.deviceInventory.length && app.dom.deviceListEl) {
        app.dom.deviceListEl.innerHTML = '<p class="empty-state">Đang tải thiết bị...</p>';
        setSummaryText("Đang đồng bộ...");
    } else if (!app.state.deviceInventory.length && app.dom.deviceControlFunctionsEl) {
        app.dom.deviceControlFunctionsEl.innerHTML = '<div class="empty-device-actions">Đang tải thiết bị...</div>';
    }
    try {
        const { result } = await fetchJson("/api/devices");
        app.state.deviceInventory = normalizeDeviceInventory(Array.isArray(result.devices) ? result.devices : []);
        writeCachedDeviceInventory(app.state.deviceInventory);
        const activeDevice = getDeviceById(getRequestedDeviceIdFromUrl() || app.state.currentDeviceControlId);
        if (activeDevice) {
            cacheOpenedDevice(activeDevice);
        }
        renderIrDeviceOptions();
        renderDevices(app.state.deviceInventory);
    } catch (error) {
        if (error.isAuth) {
            return;
        }
        app.state.deviceInventory = [];
        renderIrDeviceOptions();
        if (app.dom.deviceListEl) {
            app.dom.deviceListEl.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
            setSummaryText("Tải dữ liệu thất bại");
        }
        if (app.dom.deviceControlFunctionsEl) {
            app.dom.deviceControlFunctionsEl.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
        }
        addChatMessage("system", `Không tải được danh sách thiết bị: ${error.message}`, Date.now(), {
            isError: true,
            fingerprint: "load-devices-error",
        });
    }
}

export async function submitAddDevice(event) {
    event.preventDefault();
    if (!app.state.isAuthenticated || app.state.isAddDeviceSubmitting || !app.dom.addDeviceFormEl?.reportValidity()) {
        return;
    }

    const templateId = String(app.dom.addDeviceTemplateSelectEl?.value || "").trim();
    const deviceName = String(app.dom.addDeviceNameInputEl?.value || "").trim();
    if (!templateId) {
        setAddDeviceFeedback("Vui lòng chọn loại thiết bị.");
        app.dom.addDeviceTemplateSelectEl?.focus();
        return;
    }
    if (!deviceName) {
        setAddDeviceFeedback("Vui lòng nhập tên thiết bị.");
        app.dom.addDeviceNameInputEl?.focus();
        return;
    }

    setAddDeviceFeedback("");
    setAddDeviceLoadingState(true);

    try {
        const { result } = await fetchJson("/api/devices", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ template_id: templateId, device: { name: deviceName, aliases: [deviceName] } }),
        });

        const successText = result.message || "Thêm thiết bị thành công";
        setAddDeviceFeedback(successText, "success");
        await loadDevices();
        addChatMessage("assistant", `${successText}: ${deviceName}`, Date.now(), {
            fingerprint: `device-add-${result.device_id || Date.now()}`,
        });
        window.setTimeout(() => closeAddDeviceModal(), 500);
    } catch (error) {
        if (!error.isAuth) {
            setAddDeviceFeedback(error.message || "Thêm thiết bị thất bại.");
        }
    } finally {
        setAddDeviceLoadingState(false);
    }
}

export async function submitAddFunctionButton(event) {
    event.preventDefault();
    if (!app.state.isAuthenticated || !app.state.currentDeviceControlId || !app.dom.addFunctionButtonFormEl?.reportValidity()) {
        return;
    }

    const device = getDeviceById(app.state.currentDeviceControlId);
    const rawName = String(app.dom.addFunctionButtonNameInputEl?.value || "").trim();
    const commandSlug = slugifyVietnameseText(rawName);

    if (!device) {
        setAddFunctionButtonFeedback("Không tìm thấy thiết bị đang mở.");
        return;
    }
    if (!rawName) {
        setAddFunctionButtonFeedback("Vui lòng nhập tên button.");
        app.dom.addFunctionButtonNameInputEl?.focus();
        return;
    }
    if (!commandSlug) {
        setAddFunctionButtonFeedback("Tên button chưa hợp lệ để tạo command key.");
        app.dom.addFunctionButtonNameInputEl?.focus();
        return;
    }

    const nextFunction = buildFunctionRecord(rawName, commandSlug, {
        backendAction: commandSlug,
        learned: false,
        source: "custom",
    });
    const existingFunctions = Array.isArray(device.functions) ? device.functions : [];
    if (existingFunctions.some((item) => String(item.commandKey || "").toLowerCase() === commandSlug.toLowerCase())) {
        setAddFunctionButtonFeedback("Function button này đã tồn tại trên thiết bị.");
        app.dom.addFunctionButtonNameInputEl?.focus();
        return;
    }

    setAddFunctionButtonFeedback("");
    setAddFunctionButtonLoadingState(true);

    const nextFunctions = [...existingFunctions, nextFunction];
    updateDeviceRecord(device.id, (current) => ({ ...current, functions: nextFunctions }));
    persistCustomFunctionsForDevice(device.id, nextFunctions);
    app.state.deviceStateMap.set(device.id, getDeviceById(device.id));
    renderDevices(app.state.deviceInventory);
    addChatMessage("system", `Đã thêm function button "${rawName}" cho ${device.name}.`, Date.now(), {
        fingerprint: `device-function-add-${device.id}-${commandSlug}`,
    });
    closeAddFunctionButtonModal();
}

export async function submitDeviceSchedule(event) {
    event.preventDefault();
    if (!app.state.isAuthenticated || !app.state.currentDeviceControlId || app.state.isScheduleSubmitting) {
        return;
    }

    const device = getDeviceById(app.state.currentDeviceControlId);
    const hour = String(app.dom.deviceScheduleHourInputEl?.value || "").trim();
    const minute = String(app.dom.deviceScheduleMinuteInputEl?.value || "").trim();
    const action = String(app.dom.deviceScheduleActionInputEl?.value || "").trim();
    const repeat = Boolean(app.dom.deviceScheduleRepeatInputEl?.checked);

    if (!device) {
        setDeviceScheduleFeedback("Không tìm thấy thiết bị đang mở.");
        return;
    }
    if (hour === "" || minute === "") {
        setDeviceScheduleFeedback("Vui lòng nhập đủ giờ và phút.");
        return;
    }
    if (!action) {
        setDeviceScheduleFeedback("Vui lòng chọn chế độ Bật hoặc Tắt trước khi hẹn giờ.");
        app.dom.deviceScheduleActionInputEl?.focus();
        return;
    }
    if ((app.state.deviceSchedules || []).length >= 2) {
        setDeviceScheduleFeedback("Vui lòng xóa bớt lịch hẹn trước khi tạo mới");
        return;
    }

    setDeviceScheduleFeedback("");
    setDeviceScheduleLoadingState(true);

    try {
        const { result } = await fetchJson(`/api/devices/${encodeURIComponent(device.id)}/schedules`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                hour: Number.parseInt(hour, 10),
                minute: Number.parseInt(minute, 10),
                action,
                repeat,
            }),
        });
        const createdSchedule = result.schedule || null;
        if (createdSchedule) {
            app.state.deviceSchedules = [...app.state.deviceSchedules, createdSchedule].sort((a, b) => {
                const hourDiff = Number(a.hour || 0) - Number(b.hour || 0);
                if (hourDiff !== 0) return hourDiff;
                const minuteDiff = Number(a.minute || 0) - Number(b.minute || 0);
                if (minuteDiff !== 0) return minuteDiff;
                return String(a.id || "").localeCompare(String(b.id || ""));
            });
            renderDeviceScheduleList();
        } else {
            await loadDeviceSchedules(device.id);
        }

        const successText = result.message || "Đã tạo lịch hẹn thiết bị.";
        setDeviceScheduleFeedback(successText, "success");
    } catch (error) {
        if (!error.isAuth) {
            setDeviceScheduleFeedback(error.message || "Không lưu được lịch hẹn.");
        }
    } finally {
        setDeviceScheduleLoadingState(false);
    }
}

function updateDeviceActionButtons(deviceId, device, processing = false) {
    const currentState = getEffectiveDeviceState(device);
    const currentAction = getEffectiveActiveAction(device);
    const cardEl = document.querySelector(`[data-device-id="${deviceId}"]`);
    const buttons = Array.from(cardEl?.querySelectorAll("[data-device-action]") || []);

    buttons.forEach((button) => {
        const action = button.dataset.deviceAction;
        const isTogglePair = ["on", "off", "bat", "tat", "turn_on", "turn_off", "power.on", "power.off"].includes(action);
        const isCurrentStateAction = currentState === "on"
            ? ["on", "bat", "turn_on", "power.on"].includes(action)
            : currentState === "off"
                ? ["off", "tat", "turn_off", "power.off"].includes(action)
                : false;
        const isActionActive = (currentAction && String(action || "").trim().toLowerCase() === currentAction) || (isTogglePair && isCurrentStateAction);
        button.classList.toggle("is-active", Boolean(isActionActive));
        button.classList.remove("is-inactive");
        button.setAttribute("aria-pressed", isTogglePair && isCurrentStateAction ? "true" : "false");
        button.disabled = processing;
    });

    if (String(app.state.currentDeviceControlId || "") === String(deviceId || "")) {
        app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-device-function]").forEach((button) => {
            const commandKey = String(button.dataset.commandKey || "");
            const isLearned = button.dataset.functionLearned === "true";
            if (!isLearned) {
                button.classList.remove("is-active", "is-inactive");
                button.disabled = processing;
                return;
            }
            const backendAction = String(button.dataset.backendAction || commandKey || "").trim().toLowerCase();
            const isTogglePair = ["turn_on", "turn_off", "on", "off", "bat", "tat", "power.on", "power.off"].includes(commandKey)
                || ["turn_on", "turn_off", "on", "off", "bat", "tat", "power.on", "power.off"].includes(backendAction);
            const isCurrentStateAction = currentState === "on"
                ? ["turn_on", "on", "bat", "power.on"].includes(commandKey) || ["turn_on", "on", "bat", "power.on"].includes(backendAction)
                : currentState === "off"
                    ? ["turn_off", "off", "tat", "power.off"].includes(commandKey) || ["turn_off", "off", "tat", "power.off"].includes(backendAction)
                    : false;
            const normalizedCommandKey = String(commandKey || "").trim().toLowerCase();
            const isActionActive = [normalizedCommandKey, backendAction].filter(Boolean).includes(currentAction) || (isTogglePair && isCurrentStateAction);
            button.classList.toggle("is-active", Boolean(isActionActive));
            button.classList.remove("is-inactive");
            button.disabled = processing;
        });
    }
}

export function updateDeviceState(deviceId, state, processing = false) {
    const stateEl = document.querySelector(`[data-device-state="${deviceId}"]`);
    const cardEl = document.querySelector(`[data-device-id="${deviceId}"]`);
    const bannerEl = document.querySelector(`[data-device-status-banner="${deviceId}"]`);
    const current = app.state.deviceStateMap.get(deviceId) || {};
    const nextDevice = typeof state === "object" ? { ...current, ...state } : { ...current, state };

    if (stateEl) {
        stateEl.textContent = formatCommandStatus(nextDevice);
        stateEl.classList.toggle("is-processing", processing);
    }

    const effectiveState = getEffectiveDeviceState(nextDevice);
    if (cardEl) cardEl.classList.toggle("is-on", effectiveState === "on");
    if (bannerEl) {
        bannerEl.className = getStatusBannerClass(effectiveState, processing);
    }

    if (String(app.state.currentDeviceControlId || "") === String(deviceId || "")) {
        if (app.dom.deviceControlStatusTextEl) {
            app.dom.deviceControlStatusTextEl.textContent = formatCommandStatus(nextDevice);
        }
        if (app.dom.deviceControlStatusBannerEl) {
            app.dom.deviceControlStatusBannerEl.className = getStatusBannerClass(effectiveState, processing);
        }
    }

    updateDeviceActionButtons(deviceId, nextDevice, processing);
}

export function mergeDeviceState(deviceId, state) {
    const current = app.state.deviceStateMap.get(deviceId) || {};
    const nextState = typeof state === "object" ? { ...current, ...state } : { ...current, state };
    app.state.deviceStateMap.set(deviceId, nextState);
    updateDeviceRecord(deviceId, (device) => ({ ...device, ...nextState }));
    updateDeviceState(deviceId, nextState, false);
}

function deriveOptimisticPowerState(action) {
    const normalizedAction = String(action || "").trim().toLowerCase();
    if (["off", "tat", "turn_off", "power.off"].includes(normalizedAction)) {
        return "off";
    }
    return "on";
}

function applyOptimisticDeviceState(deviceId, action) {
    const current = app.state.deviceStateMap.get(deviceId) || {};
    const optimisticState = {
        ...current,
        state: deriveOptimisticPowerState(action),
        active_action: action,
        state_verified: false,
        last_command: action,
        last_command_status: "sent",
        last_command_at: new Date().toISOString(),
        last_command_message: `Da gui lenh ${action}`,
    };
    app.state.deviceStateMap.set(deviceId, optimisticState);
    updateDeviceRecord(deviceId, (device) => ({ ...device, ...optimisticState }));
    updateDeviceState(deviceId, optimisticState, false);
}

async function handleDeleteDevice(deviceId) {
    const device = getDeviceById(deviceId);
    const deviceName = device?.name || deviceId;
    const confirmed = window.confirm(
        `Xóa thiết bị "${deviceName}"?\n\nHệ thống sẽ xóa thiết bị khỏi device_map và xóa các file IR/RF liên quan nếu không còn thiết bị khác sử dụng.`
    );
    if (!confirmed || app.state.isDeletingDevice) {
        return;
    }

    app.state.isDeletingDevice = true;
    closeDeviceMenus();
    setChatStatus(`Đang xóa thiết bị ${deviceName}...`, "processing");

    try {
        const { result } = await fetchJson(`/api/devices/${encodeURIComponent(deviceId)}`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
        });
        if (String(app.state.currentDeviceControlId || "") === String(deviceId || "")) {
            closeDeviceControlPage();
        }
        const storageMap = readPersistedFunctionMap();
        delete storageMap[deviceId];
        writePersistedFunctionMap(storageMap);
        await loadDevices();
        setChatStatus("Đã xóa thiết bị", "live");
        const deletedSummary = Array.isArray(result.deleted_files) && result.deleted_files.length
            ? ` File đã xóa: ${result.deleted_files.join(", ")}.`
            : "";
        const skippedSummary = Array.isArray(result.skipped_files) && result.skipped_files.length
            ? ` File giữ lại vì còn thiết bị khác dùng: ${result.skipped_files.join(", ")}.`
            : "";
        addChatMessage("system", `${result.message || `Đã xóa thiết bị ${deviceName}.`}${deletedSummary}${skippedSummary}`, Date.now(), {
            fingerprint: `device-delete-${deviceId}-${Date.now()}`,
        });
    } catch (error) {
        if (!error.isAuth) {
            setChatStatus("Không xóa được thiết bị", "error");
            addChatMessage("system", `Không xóa được thiết bị ${deviceName}: ${error.message}`, Date.now(), {
                isError: true,
                fingerprint: `device-delete-error-${deviceId}-${Date.now()}`,
            });
        }
    } finally {
        app.state.isDeletingDevice = false;
    }
}

export async function sendDeviceCommand(deviceId, action, buttonEl, options = {}) {
    if (!app.state.isAuthenticated) {
        return;
    }

    const functionButtons = app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-device-function]") || [];
    const functionDeleteButtons = app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-function-delete]") || [];
    const previousState = { ...(app.state.deviceStateMap.get(deviceId) || {}) };
    const commandKey = String(options.commandKey || action || "").trim();
    const device = getDeviceById(deviceId);
    const silentChat = options.silentChat !== false;

    if (!silentChat && commandKey && !["turn_on", "turn_off", "on", "off", "power.on", "power.off"].includes(commandKey)) {
        addChatMessage("system", `Đang gửi function "${commandKey}" xuống backend. Nếu Broadlink chưa có lệnh thật, backend có thể trả về cảnh báo.`, Date.now(), {
            fingerprint: `device-function-warning-${deviceId}-${commandKey}`,
        });
    }

    applyOptimisticDeviceState(deviceId, action);
    setChatStatus("Jetson đang xử lý thiết bị...", "processing");

    try {
        const { result } = await fetchJson("/api/device/control", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_id: deviceId, action }),
        });

        if (result.intent?.device) {
            mergeDeviceState(result.intent.device, {
                state: result.state || "unknown",
                state_verified: result.state_verified,
                last_command: result.last_command,
                last_command_at: result.last_command_at,
                last_command_status: result.last_command_status,
                last_command_message: result.last_command_message,
                active_action: result.active_action,
            });
        }

        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
    } catch (error) {
        if (error.isAuth) {
            app.state.deviceStateMap.set(deviceId, previousState);
            updateDeviceRecord(deviceId, (current) => ({ ...current, ...previousState }));
            updateDeviceState(deviceId, previousState, false);
            return;
        }
        app.state.deviceStateMap.set(deviceId, previousState);
        updateDeviceRecord(deviceId, (current) => ({ ...current, ...previousState }));
        updateDeviceState(deviceId, previousState, false);
        if (!silentChat) {
            addChatMessage("system", `Không thể điều khiển thiết bị: ${error.message}`, Date.now(), {
                isError: true,
                fingerprint: `device-control-error-${deviceId}-${action}`,
            });
        }
        setChatStatus("Có lỗi khi điều khiển thiết bị", "error");
    } finally {
        void functionButtons;
        void functionDeleteButtons;
        void buttonEl;
        updateDeviceActionButtons(deviceId, app.state.deviceStateMap.get(deviceId) || previousState, false);
    }
}

export async function learnIrCommand(event) {
    event?.preventDefault();
    if (!app.state.isAuthenticated || app.state.isLearningIr) {
        return;
    }

    const deviceId = String(app.state.currentDeviceControlId || "").trim();
    const selectedDevice = getDeviceById(deviceId);
    const templateId = String(selectedDevice?.template_id || "").trim();
    const deviceName = String(selectedDevice?.name || "").trim();
    const signalType = String(app.dom.irSignalTypeSelectEl?.value || selectedDevice?.control_type || "ir").trim().toLowerCase();
    const rfFrequency = String(app.dom.irRfFrequencySelectEl?.value || selectedDevice?.rf_frequency || "").trim();
    const semanticKind = String(app.dom.irSemanticKindSelectEl?.value || "power.on").trim();
    const semanticValue = String(app.dom.irSemanticValueInputEl?.value || "").trim();
    const actionPhrases = parseMultilinePhrases(app.dom.irActionPhrasesInputEl?.value || "");

    if (!deviceId || !selectedDevice) {
        setIrLearnModalFeedback("Không tìm thấy thiết bị đang mở để học lệnh.");
        return;
    }
    if (!["ir", "rf"].includes(signalType)) {
        setIrLearnModalFeedback("Vui lòng chọn kiểu tín hiệu IR hoặc RF.");
        app.dom.irSignalTypeSelectEl?.focus();
        return;
    }
    if (signalType === "rf" && !["315", "433"].includes(rfFrequency)) {
        setIrLearnModalFeedback("Thiết bị RF cần chọn tần số 315 hoặc 433.");
        app.dom.irRfFrequencySelectEl?.focus();
        return;
    }

    let actionPayload;
    try {
        actionPayload = buildSemanticActionPayload(semanticKind, semanticValue, () => "power.on");
    } catch (error) {
        setIrLearnModalFeedback(error.message || "Thông tin ngữ nghĩa lệnh chưa hợp lệ.");
        app.dom.irSemanticValueInputEl?.focus();
        return;
    }

    const pendingLearnContext = app.state.pendingLearnContext;
    const forcedActionKey = normalizeActionKey(pendingLearnContext?.actionKey);
    const isMatchingPendingDevice = normalizeActionKey(pendingLearnContext?.deviceId) === normalizeActionKey(deviceId);
    const isEditMode = String(pendingLearnContext?.mode || "").trim().toLowerCase() === "edit";
    if (forcedActionKey && isMatchingPendingDevice) {
        actionPayload = {
            ...actionPayload,
            actionKey: forcedActionKey,
        };
    }

    const phrasesPayload = actionPhrases.length
        ? actionPhrases
        : buildDefaultActionPhrases(deviceName, semanticKind, semanticValue);

    setIrLearnModalFeedback("");
    setIrLearnLoadingState(true);
    setChatStatus(isEditMode ? "Đang cập nhật semantic action..." : `Broadlink đang học tín hiệu ${signalType.toUpperCase()}...`, "processing");

    try {
        let result;
        let learnedFile = "";

        if (isEditMode) {
            ({ result } = await fetchJson(
                `/api/devices/${encodeURIComponent(deviceId)}/actions/${encodeURIComponent(actionPayload.actionKey)}`,
                {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        action: {
                            semantic: actionPayload.semantic,
                            phrases: phrasesPayload,
                        },
                    }),
                }
            ));
        } else {
            const { result: learnResult } = await fetchJson("/api/ir/learn", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    device_name: deviceName,
                    signal_type: signalType,
                    rf_frequency: signalType === "rf" ? Number.parseInt(rfFrequency, 10) : null,
                }),
            });

            const actionRecord = {
                type: signalType,
                file: String(learnResult?.filename || "").trim(),
                semantic: actionPayload.semantic,
                phrases: phrasesPayload,
            };
            if (signalType === "rf") {
                actionRecord.rf_frequency = Number.parseInt(rfFrequency, 10);
            }
            if (!actionRecord.file) {
                throw new Error("Backend không trả về tên file đã học.");
            }
            learnedFile = actionRecord.file;

            ({ result } = await fetchJson("/api/device-learn/save", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    template_id: templateId,
                    device: {
                        id: selectedDevice.id,
                        name: deviceName,
                        control_type: signalType,
                        rf_frequency: signalType === "rf" ? Number.parseInt(rfFrequency, 10) : null,
                        aliases: Array.isArray(selectedDevice.aliases) ? selectedDevice.aliases : [deviceName],
                    },
                    actions: { [actionPayload.actionKey]: actionRecord },
                    presets: {},
                }),
            }));
        }

        const successText = result.message || (isEditMode ? "Cập nhật semantic thành công" : "Học lệnh và lưu thiết bị thành công");
        setIrLearnModalFeedback(successText, "success");
        setChatStatus(isEditMode ? "Đã cập nhật semantic action" : "Học lệnh thành công", "live");
        await loadDevices();
        addChatMessage("assistant", isEditMode ? successText : `${successText}. File lưu: ${learnedFile}`, Date.now(), {
            fingerprint: `${isEditMode ? "device-action-update" : "device-learn-save"}-${result.device_id || Date.now()}`,
        });
        window.setTimeout(() => closeIrLearnModal({ force: true }), 500);
    } catch (error) {
        if (!error.isAuth) {
            const message = error.message || (isEditMode ? "Cập nhật semantic thất bại" : "Học lệnh thất bại");
            setIrLearnModalFeedback(message);
            setChatStatus(isEditMode ? "Có lỗi khi cập nhật semantic" : "Có lỗi khi học lệnh", "error");
            addChatMessage("system", message, Date.now(), {
                isError: true,
                fingerprint: `${isEditMode ? "device-action-update-error" : "device-learn-save-error"}-${Date.now()}`,
            });
        }
    } finally {
        setIrLearnLoadingState(false);
    }
}

export function handleSnapshot(payload) {
    app.state.deviceInventory = normalizeDeviceInventory(payload?.devices || []);
    writeCachedDeviceInventory(app.state.deviceInventory);
    renderIrDeviceOptions();
    renderDevices(app.state.deviceInventory);
}

export function handleDeviceStateChanged(payload) {
    if (payload?.removed && payload?.id) {
        app.state.deviceInventory = app.state.deviceInventory.filter((device) => String(device.id || "") !== String(payload.id));
        if (String(app.state.currentDeviceControlId || "") === String(payload.id || "")) {
            closeDeviceControlPage();
        }
        renderIrDeviceOptions();
        renderDevices(app.state.deviceInventory);
        return;
    }
    if (payload?.id) {
        mergeDeviceState(payload.id, payload);
    }
}
