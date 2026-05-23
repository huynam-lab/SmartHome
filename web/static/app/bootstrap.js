(function bootstrapSmartHome() {
    const root = document.body;
    const dataset = root ? root.dataset : {};

    window.__SMART_HOME_BOOTSTRAP__ = {
        authenticated: String(dataset.authenticated || "").trim().toLowerCase() === "true",
        jetson_id: String(dataset.jetsonId || "").trim(),
        page: String(dataset.page || "index").trim() || "index",
        device_id: String(dataset.deviceId || "").trim(),
        device_name: String(dataset.deviceName || "").trim(),
    };
})();
