import { app } from "./core.js";
import { fetchJson } from "./api.js";
import {
    escapeHtml,
    formatCommandStatus,
    formatActionLabel,
    getEffectiveDeviceState,
    getActionButtonClass,
    getDeviceIcon,
    getStatusBannerClass,
    normalizeIrFilenameInput,
    suggestLearnFilename,
    parseMultilinePhrases,
    getIrSemanticConfig,
    buildSemanticActionPayload,
    buildDefaultActionPhrases,
    isValidLearnFilename,
    slugifyVietnameseText,
} from "./utils.js";
import {
    addChatMessage,
    closeDeviceMenus,
    closeSettingsMenu,
    setAddDeviceFeedback,
    setAddFunctionButtonFeedback,
    setChatStatus,
    setIrLearnModalFeedback,
    setSummaryText,
    toggleDeviceMenu,
} from "./ui.js";

const DEVICE_FUNCTION_STORAGE_KEY = "smarthome.deviceFunctions.v1";
const DEVICE_INVENTORY_CACHE_KEY = "smarthome.deviceInventory.v1";
const LAST_OPENED_DEVICE_KEY = "smarthome.lastOpenedDevice.v1";

function isDeviceControlRoute() {
    return window.location.pathname === "/device-control";
}

function getRequestedDeviceIdFromUrl() {
    return new URLSearchParams(window.location.search).get("device_id") || "";
}

function getRequestedDeviceNameFromUrl() {
    return new URLSearchParams(window.location.search).get("device_name") || "";
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
        source: options.source || "custom",
    };
}

function buildDefaultDeviceFunctions(device) {
    if (!isLightLikeDevice(device)) {
        return [];
    }

    const availableActions = Array.isArray(device.actions) ? device.actions : [];
    const onBackendAction = availableActions.find((action) => ["turn_on", "on", "power.on"].includes(action)) || "turn_on";
    const offBackendAction = availableActions.find((action) => ["turn_off", "off", "power.off"].includes(action)) || "turn_off";

    return [
        buildFunctionRecord("Bật", "turn_on", {
            id: "fn_on",
            backendAction: onBackendAction,
            source: "default",
        }),
        buildFunctionRecord("Tắt", "turn_off", {
            id: "fn_off",
            backendAction: offBackendAction,
            source: "default",
        }),
    ];
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
            source: "backend",
        });
    });
}

function mergeFunctionLists(...lists) {
    const merged = [];
    const seen = new Set();

    lists.flat().forEach((item) => {
        const name = String(item?.name || "").trim();
        const commandKey = String(item?.commandKey || "").trim();
        if (!name || !commandKey) {
            return;
        }
        const dedupeKey = commandKey.toLowerCase();
        if (seen.has(dedupeKey)) {
            return;
        }
        seen.add(dedupeKey);
        merged.push(buildFunctionRecord(name, commandKey, item));
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
            source: "custom",
        }));
    writePersistedFunctionMap(storageMap);
}

function normalizeDevice(device) {
    const persistedFunctions = getPersistedFunctionsForDevice(device.id);
    const normalizedFunctions = mergeFunctionLists(
        buildFunctionsFromActions(device),
        Array.isArray(device.functions) ? device.functions : [],
        buildDefaultDeviceFunctions(device),
        persistedFunctions,
    );

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
    if (!app.dom.irDeviceSelectEl) {
        return;
    }
    const learnableDevices = getLearnableDevices();
    const optionsMarkup = ['<option value="">Chọn thiết bị đã thêm</option>'];
    learnableDevices.forEach((device) => {
        optionsMarkup.push(`<option value="${escapeHtml(device.id || "")}">${escapeHtml(device.name || device.id || "")}</option>`);
    });
    app.dom.irDeviceSelectEl.innerHTML = optionsMarkup.join("");
    app.dom.irDeviceSelectEl.disabled = learnableDevices.length === 0;
}

export function updateIrSemanticForm() {
    const config = getIrSemanticConfig(String(app.dom.irSemanticKindSelectEl?.value || "power.on"));
    const requiresValue = Boolean(config.requiresValue);

    app.dom.irSemanticValueFieldEl?.classList.toggle("is-hidden", !requiresValue);
    if (app.dom.irSemanticValueLabelEl) app.dom.irSemanticValueLabelEl.textContent = config.label || "Giá trị";
    if (app.dom.irSemanticValueHintEl) app.dom.irSemanticValueHintEl.textContent = config.hint || "";
    if (app.dom.irSemanticValueInputEl) {
        app.dom.irSemanticValueInputEl.required = requiresValue;
        app.dom.irSemanticValueInputEl.min = config.min || "1";
        app.dom.irSemanticValueInputEl.step = config.step || "1";
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
    if (app.dom.irFilenameLabelEl) app.dom.irFilenameLabelEl.textContent = isRf ? "Tên file .json" : "Tên file .bin";
    if (app.dom.irFilenameInputEl) app.dom.irFilenameInputEl.placeholder = isRf ? "Ví dụ: den_san_on.json" : "Ví dụ: den_san_on.bin";
    if (app.dom.irFilenameHintEl) {
        app.dom.irFilenameHintEl.textContent = isRf
            ? "Ví dụ: den_san_on.json, den_san_off.json"
            : "Ví dụ: den_san_on.bin, den_san_off.bin";
    }
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
        if (app.dom.irDeviceNameInputEl) app.dom.irDeviceNameInputEl.value = "";
        if (app.dom.irSignalTypeSelectEl) app.dom.irSignalTypeSelectEl.value = "ir";
        if (app.dom.irRfFrequencySelectEl) app.dom.irRfFrequencySelectEl.value = "";
        updateIrSignalTypeForm();
        return;
    }

    if (app.dom.irDeviceNameInputEl) app.dom.irDeviceNameInputEl.value = selectedDevice.name || selectedDevice.id || "";
    if (app.dom.irSignalTypeSelectEl) {
        const signalType = String(selectedDevice.control_type || "").trim().toLowerCase();
        app.dom.irSignalTypeSelectEl.value = signalType === "rf" ? "rf" : "ir";
    }
    if (app.dom.irRfFrequencySelectEl) {
        const rfFrequency = String(selectedDevice.rf_frequency || "").trim();
        app.dom.irRfFrequencySelectEl.value = rfFrequency === "315" || rfFrequency === "433" ? rfFrequency : "";
    }
    updateIrSignalTypeForm();

    const currentFilename = normalizeIrFilenameInput(app.dom.irFilenameInputEl?.value || "");
    if (!currentFilename) {
        const suggestion = suggestLearnFilename(
            selectedDevice.name || selectedDevice.id || "",
            String(app.dom.irSignalTypeSelectEl?.value || selectedDevice.control_type || "ir").trim().toLowerCase(),
        );
        if (suggestion && app.dom.irFilenameInputEl) {
            app.dom.irFilenameInputEl.value = suggestion;
        }
    }
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
    if (!app.state.isAuthenticated || app.state.isLearningIr) {
        return;
    }
    closeSettingsMenu();
    setIrLearnModalFeedback("");
    app.dom.irLearnFormEl?.reset();
    if (app.dom.irSemanticKindSelectEl) app.dom.irSemanticKindSelectEl.value = "power.on";
    if (app.dom.irSignalTypeSelectEl) app.dom.irSignalTypeSelectEl.value = "ir";
    if (app.dom.irRfFrequencySelectEl) app.dom.irRfFrequencySelectEl.value = "";
    updateIrSemanticForm();
    updateIrSignalTypeForm();
    renderIrDeviceOptions();
    app.dom.irLearnModalEl?.classList.add("is-visible");
    app.dom.irLearnModalEl?.setAttribute("aria-hidden", "false");
    window.setTimeout(() => app.dom.irDeviceSelectEl?.focus(), 0);
}

export function closeIrLearnModal({ force = false } = {}) {
    if (app.state.isLearningIr && !force) {
        return;
    }
    app.dom.irLearnModalEl?.classList.remove("is-visible");
    app.dom.irLearnModalEl?.setAttribute("aria-hidden", "true");
    app.dom.irLearnFormEl?.reset();
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
        app.dom.irDeviceSelectEl,
        app.dom.irDeviceNameInputEl,
        app.dom.irFilenameInputEl,
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
    const deviceControlHref = `/device-control?device_id=${encodeURIComponent(device.id)}&device_name=${encodeURIComponent(device.name || "")}`;

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
    return `
        <button
            type="button"
            class="action-btn ${getActionButtonClass(fn.commandKey)} device-function-btn"
            data-device-function="${escapeHtml(deviceId)}"
            data-function-id="${escapeHtml(fn.id || "")}"
            data-command-key="${escapeHtml(fn.commandKey || "")}"
            data-backend-action="${escapeHtml(fn.backendAction || fn.commandKey || "")}"
            ${disabled ? "disabled" : ""}
        >
            ${escapeHtml(fn.name || "Function")}
        </button>
    `;
}

function renderDeviceControlPage() {
    const device = getDeviceById(app.state.currentDeviceControlId);
    if (!device || !app.dom.deviceControlPageEl) {
        if (isDeviceControlRoute()) {
            if (app.dom.deviceControlFunctionsEl) {
                app.dom.deviceControlFunctionsEl.innerHTML = '<div class="empty-device-actions">Không tìm thấy thiết bị cần điều khiển.</div>';
            }
        } else {
            closeDeviceControlPage();
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
}

function bindDeviceControlActions() {
    app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-device-function]").forEach((button) => {
        button.addEventListener("click", () => {
            if (button.disabled) {
                return;
            }
            const deviceId = button.dataset.deviceFunction;
            const commandKey = button.dataset.commandKey;
            const backendAction = button.dataset.backendAction || commandKey;
            sendDeviceCommand(deviceId, backendAction, button, { commandKey });
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
}

export function openDeviceControlPage(deviceId) {
    const device = getDeviceById(deviceId);
    if (!device) {
        return;
    }
    cacheOpenedDevice(device);
    if (!isDeviceControlRoute()) {
        window.location.href = `/device-control?device_id=${encodeURIComponent(device.id)}&device_name=${encodeURIComponent(device.name || "")}`;
        return;
    }
    if (!app.dom.deviceControlPageEl) {
        return;
    }
    closeDeviceMenus();
    app.state.currentView = "device-control";
    app.state.currentDeviceControlId = device.id;
    app.dom.deviceControlPageEl.classList.remove("is-hidden");
    app.dom.deviceControlPageEl.setAttribute("aria-hidden", "false");
    renderDeviceControlPage();
    window.setTimeout(() => app.dom.deviceControlBackBtnEl?.focus(), 0);
}

export function closeDeviceControlPage({ navigate = true } = {}) {
    if (isDeviceControlRoute() && navigate) {
        window.location.href = "/";
        return;
    }
    app.state.currentView = "device-center";
    app.state.currentDeviceControlId = null;
    app.dom.deviceControlPageEl?.classList.add("is-hidden");
    app.dom.deviceControlPageEl?.setAttribute("aria-hidden", "true");
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

export function renderDevices(devices) {
    app.state.deviceStateMap.clear();
    if (!app.dom.deviceListEl) {
        devices.forEach((device) => app.state.deviceStateMap.set(device.id, device));
        const requestedDeviceId = getRequestedDeviceIdFromUrl();
        const requestedDeviceName = getRequestedDeviceNameFromUrl();
        if (!requestedDeviceId && requestedDeviceName && app.dom.deviceControlTitleEl) {
            app.dom.deviceControlTitleEl.textContent = requestedDeviceName;
        }
        app.state.currentDeviceControlId = requestedDeviceId || app.state.currentDeviceControlId || devices[0]?.id || null;
        renderDeviceControlPage();
        return;
    }
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
        link.addEventListener("click", cacheFromLink, { passive: true });
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

function updateDeviceActionButtons(deviceId, device, processing = false) {
    const currentState = getEffectiveDeviceState(device);
    const cardEl = document.querySelector(`[data-device-id="${deviceId}"]`);
    const buttons = Array.from(cardEl?.querySelectorAll("[data-device-action]") || []);

    buttons.forEach((button) => {
        const action = button.dataset.deviceAction;
        const isTogglePair = ["on", "off", "turn_on", "turn_off", "power.on", "power.off"].includes(action);
        const isAllowedNextAction = currentState === "on"
            ? ["off", "turn_off", "power.off"].includes(action)
            : currentState === "off"
                ? ["on", "turn_on", "power.on"].includes(action)
                : true;
        button.classList.toggle("is-active", isTogglePair && isAllowedNextAction);
        button.classList.toggle("is-inactive", isTogglePair && !isAllowedNextAction);
        button.setAttribute("aria-pressed", isTogglePair && isAllowedNextAction ? "true" : "false");
        button.disabled = processing ? true : (isTogglePair ? !isAllowedNextAction : false);
    });

    if (String(app.state.currentDeviceControlId || "") === String(deviceId || "")) {
        app.dom.deviceControlFunctionsEl?.querySelectorAll("[data-device-function]").forEach((button) => {
            const commandKey = String(button.dataset.commandKey || "");
            const isTogglePair = ["turn_on", "turn_off", "on", "off", "power.on", "power.off"].includes(commandKey);
            const isAllowedNextAction = currentState === "on"
                ? ["turn_off", "off", "power.off"].includes(commandKey)
                : currentState === "off"
                    ? ["turn_on", "on", "power.on"].includes(commandKey)
                    : true;
            button.classList.toggle("is-active", isTogglePair && isAllowedNextAction);
            button.classList.toggle("is-inactive", isTogglePair && !isAllowedNextAction);
            button.disabled = processing ? true : (isTogglePair ? !isAllowedNextAction : false);
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

function applyOptimisticDeviceState(deviceId, action) {
    const current = app.state.deviceStateMap.get(deviceId) || {};
    const optimisticState = {
        ...current,
        state: action,
        state_verified: false,
        last_command: action,
        last_command_status: "sent",
        last_command_at: new Date().toISOString(),
        last_command_message: `Da gui lenh ${action}`,
    };
    app.state.deviceStateMap.set(deviceId, optimisticState);
    updateDeviceRecord(deviceId, (device) => ({ ...device, ...optimisticState }));
    updateDeviceState(deviceId, optimisticState, true);
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
    const previousState = { ...(app.state.deviceStateMap.get(deviceId) || {}) };
    const commandKey = String(options.commandKey || action || "").trim();
    const device = getDeviceById(deviceId);

    functionButtons.forEach((button) => {
        button.disabled = true;
        button.classList.add("is-loading");
    });
    if (buttonEl) {
        buttonEl.classList.add("is-loading");
    }

    if (commandKey && !["turn_on", "turn_off", "on", "off", "power.on", "power.off"].includes(commandKey)) {
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

        const replyText = result.reply_text || `Đã ${formatActionLabel(commandKey).toLowerCase()} thiết bị ${device?.name || deviceId}.`;
        addChatMessage("assistant", replyText, Date.now(), {
            fingerprint: `device-control-${deviceId}-${action}`,
        });

        if (result.intent?.device) {
            mergeDeviceState(result.intent.device, {
                state: result.state || "unknown",
                state_verified: result.state_verified,
                last_command: result.last_command,
                last_command_at: result.last_command_at,
                last_command_status: result.last_command_status,
                last_command_message: result.last_command_message,
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
        addChatMessage("system", `Không thể điều khiển thiết bị: ${error.message}`, Date.now(), {
            isError: true,
            fingerprint: `device-control-error-${deviceId}-${action}`,
        });
        setChatStatus("Có lỗi khi điều khiển thiết bị", "error");
    } finally {
        functionButtons.forEach((button) => button.classList.remove("is-loading"));
        updateDeviceActionButtons(deviceId, app.state.deviceStateMap.get(deviceId) || previousState, false);
    }
}

export function inferActionKeyFromFilename(filename) {
    const safeFilename = normalizeIrFilenameInput(filename).replace(/\.(bin|json)$/i, "");
    const parts = safeFilename.split("_").filter(Boolean);
    const actionToken = parts[parts.length - 1] || "";
    if (!actionToken) return "power.on";
    if (actionToken === "on") return "power.on";
    if (actionToken === "off") return "power.off";
    return actionToken.replaceAll("_", ".");
}

export async function learnIrCommand(event) {
    event?.preventDefault();
    if (!app.state.isAuthenticated || app.state.isLearningIr) {
        return;
    }

    const deviceId = String(app.dom.irDeviceSelectEl?.value || "").trim();
    const selectedDevice = getDeviceById(deviceId);
    const templateId = String(selectedDevice?.template_id || "").trim();
    const deviceName = String(selectedDevice?.name || app.dom.irDeviceNameInputEl?.value || "").trim();
    const signalType = String(app.dom.irSignalTypeSelectEl?.value || selectedDevice?.control_type || "ir").trim().toLowerCase();
    const rfFrequency = String(app.dom.irRfFrequencySelectEl?.value || selectedDevice?.rf_frequency || "").trim();
    const filename = normalizeIrFilenameInput(app.dom.irFilenameInputEl?.value || "");
    const semanticKind = String(app.dom.irSemanticKindSelectEl?.value || "power.on").trim();
    const semanticValue = String(app.dom.irSemanticValueInputEl?.value || "").trim();
    const actionPhrases = parseMultilinePhrases(app.dom.irActionPhrasesInputEl?.value || "");

    if (!deviceId || !selectedDevice) {
        setIrLearnModalFeedback("Vui lòng chọn thiết bị đã thêm trước khi học lệnh.");
        app.dom.irDeviceSelectEl?.focus();
        return;
    }
    if (!deviceName) {
        setIrLearnModalFeedback("Vui lòng nhập tên thiết bị.");
        app.dom.irDeviceNameInputEl?.focus();
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
    if (!filename) {
        setIrLearnModalFeedback(signalType === "rf" ? "Vui lòng nhập tên file .json." : "Vui lòng nhập tên file .bin.");
        app.dom.irFilenameInputEl?.focus();
        return;
    }
    if (!isValidLearnFilename(filename, signalType)) {
        setIrLearnModalFeedback(signalType === "rf"
            ? "Tên file RF không hợp lệ. Chỉ cần có đuôi .json và không được để trống."
            : "Tên file IR không hợp lệ. Chỉ cần có đuôi .bin và không được để trống.");
        app.dom.irFilenameInputEl?.focus();
        return;
    }

    let actionPayload;
    try {
        actionPayload = buildSemanticActionPayload(semanticKind, semanticValue, inferActionKeyFromFilename);
    } catch (error) {
        setIrLearnModalFeedback(error.message || "Thông tin ngữ nghĩa lệnh chưa hợp lệ.");
        app.dom.irSemanticValueInputEl?.focus();
        return;
    }

    const phrasesPayload = actionPhrases.length
        ? actionPhrases
        : buildDefaultActionPhrases(deviceName, semanticKind, semanticValue);

    setIrLearnModalFeedback("");
    setIrLearnLoadingState(true);
    setChatStatus(`Broadlink đang học tín hiệu ${signalType.toUpperCase()}...`, "processing");

    try {
        await fetchJson("/api/ir/learn", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                filename,
                device_name: deviceName,
                signal_type: signalType,
                rf_frequency: signalType === "rf" ? Number.parseInt(rfFrequency, 10) : null,
            }),
        });

        const actionRecord = {
            type: signalType,
            file: filename,
            semantic: actionPayload.semantic,
            phrases: phrasesPayload,
        };
        if (signalType === "rf") {
            actionRecord.rf_frequency = Number.parseInt(rfFrequency, 10);
        }

        const { result } = await fetchJson("/api/device-learn/save", {
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
        });

        const successText = result.message || "Học lệnh và lưu thiết bị thành công";
        setIrLearnModalFeedback(successText, "success");
        setChatStatus("Học lệnh thành công", "live");
        await loadDevices();
        addChatMessage("assistant", successText, Date.now(), {
            fingerprint: `device-learn-save-${result.device_id || Date.now()}`,
        });
        window.setTimeout(() => closeIrLearnModal({ force: true }), 500);
    } catch (error) {
        if (!error.isAuth) {
            const message = error.message || "Học lệnh thất bại";
            setIrLearnModalFeedback(message);
            setChatStatus("Có lỗi khi học lệnh", "error");
            addChatMessage("system", message, Date.now(), {
                isError: true,
                fingerprint: `device-learn-save-error-${Date.now()}`,
            });
        }
    } finally {
        setIrLearnLoadingState(false);
    }
}

export function handleSnapshot(payload) {
    app.state.deviceInventory = normalizeDeviceInventory(payload?.devices || []);
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
