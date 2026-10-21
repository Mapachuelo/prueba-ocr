export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

export async function api(path, { method = 'GET', body, form } = {}) {
    const headers = { 'X-Requested-With': 'XMLHttpRequest' };
    let payload;
    if (form) {
        payload = form;
    } else if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
        payload = JSON.stringify(body);
    }
    const res = await fetch(path, { method, headers, body: payload });
    if (res.status === 401 && !path.startsWith('/api/auth/')) {
        window.dispatchEvent(new CustomEvent('auth:expired'));
        throw new ApiError('Sesión requerida', 401);
    }
    const type = res.headers.get('content-type') || '';
    if (!res.ok) {
        let detail = `Error ${res.status}`;
        if (type.includes('application/json')) {
            const data = await res.json().catch(() => ({}));
            detail = data.detail || detail;
        }
        throw new ApiError(detail, res.status);
    }
    if (type.includes('application/json')) {
        return res.json();
    }
    return res.blob();
}

export function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
}

export async function downloadFrom(path, body, filename) {
    const blob = await api(path, { method: 'POST', body: body || {} });
    downloadBlob(blob, filename);
}
