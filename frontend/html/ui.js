export function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
        if (key === 'class') el.className = value;
        else if (key === 'dataset') Object.assign(el.dataset, value);
        else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
        else if (key.startsWith('on') && typeof value === 'function') {
            el.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (value === true) el.setAttribute(key, '');
        else if (value !== false && value !== null && value !== undefined) el.setAttribute(key, value);
    }
    for (const child of children.flat(Infinity)) {
        if (child === null || child === undefined || child === false) continue;
        el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
}

export function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
}

export function toast(message, type = 'info', ms = 3800) {
    const root = document.getElementById('toasts');
    const node = h('div', { class: `toast ${type}` }, message);
    root.append(node);
    setTimeout(() => node.remove(), ms);
}

export function modal(title, content, actions = [], onClose = null) {
    const root = document.getElementById('modalRoot');
    const close = () => {
        backdrop.remove();
        if (onClose) onClose();
    };
    const backdrop = h('div', {
        class: 'modal-backdrop',
        onclick: (event) => { if (event.target === backdrop) close(); },
    });
    const body = h('div', { class: 'modal' },
        h('h2', {}, title),
        content,
        h('div', { class: 'btn-row end' },
            ...actions.map((action) => h('button', {
                class: `btn ${action.class || ''}`,
                onclick: () => action.onClick ? action.onClick(close) : close(),
            }, action.label)),
            h('button', { class: 'btn outline', onclick: close }, 'Cerrar'),
        ),
    );
    backdrop.append(body);
    root.append(backdrop);
    return { close, body };
}

export function actionMenu(items, label = 'Más acciones') {
    return h('button', {
        class: 'btn outline sm menu-toggle',
        title: label,
        'aria-label': label,
        onclick: (event) => {
            event.stopPropagation();
            modal(label, h('p', { class: 'muted' }, 'Elige una acción para este elemento.'), items
                .filter(Boolean)
                .map((item) => ({
                    label: item.label,
                    class: item.danger ? 'danger' : 'outline',
                    onClick: (close) => { close(); item.onClick(); },
                })));
        },
    }, '⋯');
}

export function confirmDialog(message) {
    return new Promise((resolve) => {
        let answered = false;
        const { close } = modal('Confirmar', h('p', {}, message), [
            {
                label: 'Sí, continuar', class: 'danger',
                onClick: () => { answered = true; resolve(true); close(); },
            },
        ], () => { if (!answered) resolve(false); });
    });
}

export function openDrawer({ title, subtitle = '', content, footer = [], onClose = null }) {
    const root = document.getElementById('modalRoot');
    const close = () => {
        backdrop.remove();
        panel.remove();
        if (onClose) onClose();
    };
    const backdrop = h('div', { class: 'drawer-backdrop', onclick: close });
    const panel = h('aside', { class: 'drawer', role: 'dialog', 'aria-modal': 'true' },
        h('div', { class: 'drawer-head' },
            h('div', {}, h('h2', {}, title), subtitle ? h('p', { class: 'muted' }, subtitle) : null),
            h('button', { class: 'icon-btn', onclick: close, 'aria-label': 'Cerrar' }, '×'),
        ),
        h('div', { class: 'drawer-body' }, content),
        footer.length ? h('div', { class: 'drawer-foot' }, ...footer) : null,
    );
    const onKey = (event) => { if (event.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey, { once: true });
    root.append(backdrop, panel);
    return { close, panel };
}

export function statusBadge(status) {
    const labels = {
        queued: 'Encolado', processing: 'Procesando', done: 'Listo',
        error: 'Error', cancelled: 'Cancelado',
    };
    return h('span', { class: `badge-status ${status}` }, labels[status] || status);
}

export const SOURCE_LABELS = {
    regex: 'OCR local', ai: 'IA local', mrz: 'MRZ', barcode: 'Código de barras',
    manual: 'Editado a mano', excel: 'Excel', agent: 'Referencia',
};

export function sourceDot(source) {
    return h('span', {
        class: `dot ${source || 'regex'}`,
        title: SOURCE_LABELS[source] || source || '',
    });
}

export function fmtDateTime(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' });
}

export function fmtDate(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleDateString('es-CO', { dateStyle: 'medium' });
}

export function debounce(fn, ms = 350) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), ms);
    };
}

export function normalize(value) {
    return String(value ?? '').trim().toUpperCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

export const CEDULA_FIELDS = [
    'numero', 'apellidos', 'nombres', 'fecha_nacimiento', 'lugar_nacimiento',
    'rh', 'sexo', 'estatura', 'fecha_expedicion', 'lugar_expedicion',
];

export const FIELD_LABELS = {
    numero: 'Cédula', apellidos: 'Apellidos', nombres: 'Nombres',
    fecha_nacimiento: 'Fecha de nacimiento', lugar_nacimiento: 'Lugar de nacimiento',
    rh: 'RH', sexo: 'Sexo', estatura: 'Estatura',
    fecha_expedicion: 'Fecha de expedición', lugar_expedicion: 'Lugar de expedición',
};

export function completeness(values) {
    const filled = CEDULA_FIELDS.filter((field) => String(values[field] ?? '').trim()).length;
    if (filled >= CEDULA_FIELDS.length) return { key: 'complete', label: 'Completo', filled };
    if (filled >= 5) return { key: 'partial', label: 'Parcial', filled };
    return { key: 'incomplete', label: 'Incompleto', filled };
}

export function completenessBadge(values) {
    const state = completeness(values);
    const colors = { complete: 'done', partial: 'processing', incomplete: 'queued' };
    return h('span', { class: `badge-status ${colors[state.key]}`, title: `${state.filled}/10 campos` }, state.label);
}

export function emptyState(title, detail = '') {
    return h('div', { class: 'empty' },
        h('strong', {}, title),
        detail ? h('span', {}, detail) : null,
    );
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
