let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
    unauthorizedHandler = handler;
}

export async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const result = await response.json().catch(() => ({}));

    if (response.status === 401) {
        const message = result.message || "Phiên đăng nhập không hợp lệ. Vui lòng đăng nhập lại.";
        const authError = new Error(message);
        authError.isAuth = true;
        unauthorizedHandler?.(message);
        throw authError;
    }

    if (!response.ok || (result && result.ok === false && options.allowResultError !== true)) {
        const requestError = new Error(result.message || result.reply_text || "Yêu cầu không thành công.");
        requestError.result = result;
        throw requestError;
    }

    return { response, result };
}
