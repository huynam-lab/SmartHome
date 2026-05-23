import { app } from "./core.js";
import { bootstrapAuthentication, handleLogout, submitLogin, submitPasswordChange } from "./auth.js";
import { startMic, stopMic } from "./chat.js";
import { stopMicrophoneTracks } from "../js/mic-permission.js";
import {
    closeAddCameraModal,
    closeAddDeviceModal,
    closeAddFunctionButtonModal,
    closeCameraCenterPage,
    closeCameraControlPage,
    openCameraCenterPage,
    openCameraControlPageFromCurrentRoute,
    closeSceneKeywordsModal,
    openAddCameraModal,
    openCurrentCameraEditModal,
    closeDeviceControlPage,
    closeDeviceScheduleModal,
    closeIrLearnModal as closeIrLearnForm,
    learnIrCommand,
    loadDevices,
    openSceneKeywordsModal,
    openAddFunctionButtonModal,
    openAddDeviceModal,
    openDeviceScheduleModal,
    openIrLearnModal,
    submitSceneKeywords,
    setDeviceScheduleAction,
    submitAddCamera,
    submitAddFunctionButton,
    submitAddDevice,
    submitDeviceSchedule,
    syncRouteFromLocation,
    syncIrDeviceSelection,
    updateAddDeviceTemplatePreview,
    updateIrSemanticForm,
    updateIrSignalTypeForm,
} from "./devices.js";
import {
    closeDeviceMenus,
    closePasswordModal,
    closeSettingsMenu,
    initPasswordVisibilityToggles,
    openPasswordModal,
    positionSettingsMenu,
    registerPwaServiceWorker,
    setAuthMode,
    toggleSettingsMenu,
} from "./ui.js";

function bindEvents() {
    document.querySelectorAll("[data-unlock-readonly]").forEach((element) => {
        const unlock = () => element.removeAttribute("readonly");
        element.addEventListener("focus", unlock, { once: true });
        element.addEventListener("pointerdown", unlock, { once: true });
    });

    app.dom.reloadBtnEl?.addEventListener("click", loadDevices);
    app.dom.cameraCenterOpenBtnEl?.addEventListener("click", openCameraCenterPage);
    app.dom.cameraCenterBackBtnEl?.addEventListener("click", closeCameraCenterPage);
    app.dom.cameraAddTriggerBtnEl?.addEventListener("click", openAddCameraModal);
    app.dom.cameraControlBackBtnEl?.addEventListener("click", closeCameraControlPage);
    app.dom.cameraControlEditBtnEl?.addEventListener("click", openCurrentCameraEditModal);
    app.dom.addCameraCloseBtnEl?.addEventListener("click", closeAddCameraModal);
    app.dom.addCameraBackdropEl?.addEventListener("click", closeAddCameraModal);
    app.dom.addCameraCancelBtnEl?.addEventListener("click", closeAddCameraModal);
    app.dom.addCameraFormEl?.addEventListener("submit", submitAddCamera);
    app.dom.chatFormEl?.addEventListener("submit", (event) => event.preventDefault());
    app.dom.micBtnEl?.addEventListener("click", () => {
        startMic().catch((error) => {
            console.error("[voice-chat] startMic() failed", error);
        });
    });
    app.dom.authFormEl?.addEventListener("submit", submitLogin);
    app.dom.authLoginTabEl?.addEventListener("click", () => setAuthMode("login"));
    app.dom.authRegisterTabEl?.addEventListener("click", () => setAuthMode("register"));
    app.dom.settingsBtnEl?.addEventListener("click", toggleSettingsMenu);
    app.dom.addDeviceBtnEl?.addEventListener("click", openAddDeviceModal);
    app.dom.sceneKeywordsBtnEl?.addEventListener("click", openSceneKeywordsModal);
    app.dom.learnCommandBtnEl?.addEventListener("click", openIrLearnModal);
    app.dom.changePasswordBtnEl?.addEventListener("click", openPasswordModal);
    app.dom.logoutBtnEl?.addEventListener("click", handleLogout);
    app.dom.passwordCloseBtnEl?.addEventListener("click", closePasswordModal);
    app.dom.passwordBackdropEl?.addEventListener("click", closePasswordModal);
    app.dom.passwordFormEl?.addEventListener("submit", submitPasswordChange);
    app.dom.addDeviceCloseBtnEl?.addEventListener("click", closeAddDeviceModal);
    app.dom.addDeviceBackdropEl?.addEventListener("click", closeAddDeviceModal);
    app.dom.addDeviceFormEl?.addEventListener("submit", submitAddDevice);
    app.dom.addDeviceTemplateSelectEl?.addEventListener("change", updateAddDeviceTemplatePreview);
    app.dom.deviceControlBackBtnEl?.addEventListener("click", closeDeviceControlPage);
    app.dom.deviceScheduleTriggerBtnEl?.addEventListener("click", openDeviceScheduleModal);
    app.dom.addFunctionTriggerBtnEl?.addEventListener("click", openAddFunctionButtonModal);
    app.dom.addFunctionButtonCloseBtnEl?.addEventListener("click", closeAddFunctionButtonModal);
    app.dom.addFunctionButtonBackdropEl?.addEventListener("click", closeAddFunctionButtonModal);
    app.dom.addFunctionButtonCancelBtnEl?.addEventListener("click", closeAddFunctionButtonModal);
    app.dom.addFunctionButtonFormEl?.addEventListener("submit", submitAddFunctionButton);
    app.dom.deviceScheduleCloseBtnEl?.addEventListener("click", closeDeviceScheduleModal);
    app.dom.deviceScheduleBackdropEl?.addEventListener("click", closeDeviceScheduleModal);
    app.dom.deviceScheduleCancelBtnEl?.addEventListener("click", closeDeviceScheduleModal);
    app.dom.deviceScheduleFormEl?.addEventListener("submit", submitDeviceSchedule);
    app.dom.sceneKeywordsCloseBtnEl?.addEventListener("click", closeSceneKeywordsModal);
    app.dom.sceneKeywordsBackdropEl?.addEventListener("click", closeSceneKeywordsModal);
    app.dom.sceneKeywordsCancelBtnEl?.addEventListener("click", closeSceneKeywordsModal);
    app.dom.sceneKeywordsFormEl?.addEventListener("submit", submitSceneKeywords);
    app.dom.deviceScheduleActionInputEl?.addEventListener("change", (event) => {
        setDeviceScheduleAction(event.target?.value);
    });
    app.dom.irLearnCloseBtnEl?.addEventListener("click", closeIrLearnForm);
    app.dom.irLearnBackdropEl?.addEventListener("click", closeIrLearnForm);
    app.dom.irSignalTypeSelectEl?.addEventListener("change", updateIrSignalTypeForm);
    app.dom.irLearnFormEl?.addEventListener("submit", learnIrCommand);
    app.dom.irCancelBtnEl?.addEventListener("click", closeIrLearnForm);
    app.dom.addDeviceCancelBtnEl?.addEventListener("click", closeAddDeviceModal);
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
            closeAddCameraModal();
            closeAddFunctionButtonModal();
            closeDeviceScheduleModal();
            closeSceneKeywordsModal();
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

    window.addEventListener("popstate", () => {
        syncRouteFromLocation();
        openCameraControlPageFromCurrentRoute({ renderOnly: true });
    });
}

export function startApp() {
    syncRouteFromLocation({ render: false });
    openCameraControlPageFromCurrentRoute({ renderOnly: true });
    setAuthMode("login");
    updateIrSemanticForm();
    updateIrSignalTypeForm();
    initPasswordVisibilityToggles();
    bindEvents();
    window.addEventListener("pagehide", () => {
        stopMic({ force: true, updateUi: false });
        stopMicrophoneTracks();
    });
    registerPwaServiceWorker();
    bootstrapAuthentication();
}
