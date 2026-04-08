import { app } from "./core.js";
import { bootstrapAuthentication, handleLogout, submitLogin, submitPasswordChange } from "./auth.js";
import { startVoiceRecognition } from "./chat.js";
import {
    closeAddDeviceModal,
    closeAddFunctionButtonModal,
    closeDeviceControlPage,
    closeIrLearnModal as closeIrLearnForm,
    learnIrCommand,
    loadDevices,
    openAddFunctionButtonModal,
    openAddDeviceModal,
    openIrLearnModal,
    submitAddFunctionButton,
    submitAddDevice,
    syncIrDeviceSelection,
    updateIrSemanticForm,
    updateIrSignalTypeForm,
} from "./devices.js";
import {
    closeDeviceMenus,
    closePasswordModal,
    closeSettingsMenu,
    openPasswordModal,
    positionSettingsMenu,
    registerPwaServiceWorker,
    setAuthMode,
    toggleSettingsMenu,
} from "./ui.js";

function bindEvents() {
    app.dom.reloadBtnEl?.addEventListener("click", loadDevices);
    app.dom.chatFormEl?.addEventListener("submit", (event) => event.preventDefault());
    app.dom.micBtnEl?.addEventListener("click", startVoiceRecognition);
    app.dom.authFormEl?.addEventListener("submit", submitLogin);
    app.dom.authLoginTabEl?.addEventListener("click", () => setAuthMode("login"));
    app.dom.authRegisterTabEl?.addEventListener("click", () => setAuthMode("register"));
    app.dom.settingsBtnEl?.addEventListener("click", toggleSettingsMenu);
    app.dom.addDeviceBtnEl?.addEventListener("click", openAddDeviceModal);
    app.dom.learnCommandBtnEl?.addEventListener("click", openIrLearnModal);
    app.dom.changePasswordBtnEl?.addEventListener("click", openPasswordModal);
    app.dom.logoutBtnEl?.addEventListener("click", handleLogout);
    app.dom.passwordCloseBtnEl?.addEventListener("click", closePasswordModal);
    app.dom.passwordBackdropEl?.addEventListener("click", closePasswordModal);
    app.dom.passwordFormEl?.addEventListener("submit", submitPasswordChange);
    app.dom.addDeviceCloseBtnEl?.addEventListener("click", closeAddDeviceModal);
    app.dom.addDeviceBackdropEl?.addEventListener("click", closeAddDeviceModal);
    app.dom.addDeviceFormEl?.addEventListener("submit", submitAddDevice);
    app.dom.deviceControlBackBtnEl?.addEventListener("click", closeDeviceControlPage);
    app.dom.addFunctionTriggerBtnEl?.addEventListener("click", openAddFunctionButtonModal);
    app.dom.addFunctionButtonCloseBtnEl?.addEventListener("click", closeAddFunctionButtonModal);
    app.dom.addFunctionButtonBackdropEl?.addEventListener("click", closeAddFunctionButtonModal);
    app.dom.addFunctionButtonCancelBtnEl?.addEventListener("click", closeAddFunctionButtonModal);
    app.dom.addFunctionButtonFormEl?.addEventListener("submit", submitAddFunctionButton);
    app.dom.irLearnCloseBtnEl?.addEventListener("click", closeIrLearnForm);
    app.dom.irLearnBackdropEl?.addEventListener("click", closeIrLearnForm);
    app.dom.irSignalTypeSelectEl?.addEventListener("change", updateIrSignalTypeForm);
    app.dom.irLearnFormEl?.addEventListener("submit", learnIrCommand);
    app.dom.irCancelBtnEl?.addEventListener("click", closeIrLearnForm);
    app.dom.addDeviceCancelBtnEl?.addEventListener("click", closeAddDeviceModal);
    app.dom.irDeviceSelectEl?.addEventListener("change", () => syncIrDeviceSelection(app.dom.irDeviceSelectEl.value));
    app.dom.irSemanticKindSelectEl?.addEventListener("change", updateIrSemanticForm);

    document.addEventListener("click", (event) => {
        if (!app.dom.settingsMenuEl || !app.dom.settingsBtnEl) {
            closeDeviceMenus();
            return;
        }
        const target = event.target;
        if (target instanceof Node && !app.dom.settingsMenuEl.contains(target) && !app.dom.settingsBtnEl.contains(target)) {
            closeSettingsMenu();
        }
        if (target instanceof Node && !target.closest("[data-device-menu-anchor]")) {
            closeDeviceMenus();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeSettingsMenu();
            closeDeviceMenus();
            closePasswordModal();
            closeAddDeviceModal();
            closeAddFunctionButtonModal();
            closeIrLearnForm();
        }
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth <= 640) {
            app.dom.settingsMenuEl?.style.removeProperty("width");
            app.dom.settingsMenuEl?.style.removeProperty("--settings-menu-left");
            app.dom.settingsMenuEl?.style.removeProperty("--settings-menu-top");
        }
        if (app.dom.settingsMenuEl?.classList.contains("is-open")) {
            positionSettingsMenu();
        }
    });

    window.addEventListener("scroll", () => {
        if (app.dom.settingsMenuEl?.classList.contains("is-open")) {
            positionSettingsMenu();
        }
    }, { passive: true });
}

export function startApp() {
    setAuthMode("login");
    updateIrSemanticForm();
    updateIrSignalTypeForm();
    bindEvents();
    registerPwaServiceWorker();
    bootstrapAuthentication();
}
