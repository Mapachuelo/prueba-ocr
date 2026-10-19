import { api, downloadFrom } from '../api.js';
import { h, clear, toast, statusBadge, confirmDialog, fmtDateTime, emptyState } from '../ui.js';
import { icon } from '../icons.js';

const STATUS_OPTIONS = [
    ['', 'Todos'], ['queued', 'Encolado'], ['processing', 'Procesando'],
    ['done', 'Listo'], ['error', 'Error'], ['cancelled', 'Cancelado'],
];
const ENGINE_OPTIONS = [
    ['', 'Todos'], ['local', 'Local'], ['ai', 'IA local'], ['compare', 'Comparación'],
];

export function render(container, { user, navigate }) {
    const state = { filters: {}, page: 1, size: 20 };
    let timer = null;
    let interval = null;

    const q = h('input', { type: 'search', placeholder: 'Nombre de archivo…' });
    const status = h('select', {});
    const engine = h('select', {});
    const dateFrom = h('input', { type: 'date' });
    const dateTo = h('input', { type: 'date' });
    const userSelect = h('select', {});
    for (const [value, label] of STATUS_OPTIONS) status.append(h('option', { value }, label));
    for (const [value, label] of ENGINE_OPTIONS) engine.append(h('option', { value }, label));

    const holder = h('div', {});
    const pager = h('div', { class: 'pager' });
    const summary = h('div', { class: 'muted' });

    container.append(h('div', { class: 'card' },
        h('div', { class: 'card-head' },
            h('div', {}, h('h2', {}, 'Historial'), h('p', { class: 'muted' }, 'Estado y acciones de cada trabajo.')),
            h('button', { class: 'btn outline sm', onclick: () => load() }, icon('refresh'), 'Actualizar'),
        ),
        h('div', { class: 'filters' },
            h('label', { class: 'field' }, 'Archivo', q),
            h('label', { class: 'field' }, 'Estado', status),
            h('label', { class: 'field' }, 'Motor', engine),
            h('label', { class: 'field' }, 'Desde', dateFrom),
            h('label', { class: 'field' }, 'Hasta', dateTo),
            user.role === 'admin' ? h('label', { class: 'field' }, 'Usuario', userSelect) : '',
            h('div', { class: 'btn-row', style: 'align-self:end' },
                h('button', { class: 'btn primary', onclick: () => { state.page = 1; load(); } }, 'Filtrar'),
                h('button', { class: 'btn outline', onclick: resetFilters }, 'Limpiar'),
            ),
        ),
        summary,
        holder,
        pager,
    ));

    async function loadUsers() {
        if (user.role !== 'admin') return;
        try {
            const data = await api('/api/users');
            userSelect.append(h('option', { value: '' }, 'Todos'));
            for (const item of data.items) {
                userSelect.append(h('option', { value: item.id }, `${item.username} (${item.role})`));
            }
        } catch (error) { /* ignora */ }
    }

    function buildFilters() {
        const value = { ...state.filters };
        if (q.value.trim()) value.q = q.value.trim();
        if (status.value) value.status = status.value;
        if (engine.value) value.engine = engine.value;
        if (dateFrom.value) value.date_from = dateFrom.value;
        if (dateTo.value) value.date_to = dateTo.value;
        if (user.role === 'admin' && userSelect.value) value.user_id = Number(userSelect.value);
        state.filters = value;
    }

    function resetFilters() {
        q.value = '';
        status.value = '';
        engine.value = '';
        dateFrom.value = '';
        dateTo.value = '';
        if (user.role === 'admin') userSelect.value = '';
        state.filters = {};
        state.page = 1;
        load();
    }

    async function load() {
        buildFilters();
        try {
            const query = new URLSearchParams({
                filters: JSON.stringify(state.filters),
                page: state.page,
                size: state.size,
            });
            const data = await api(`/api/jobs?${query}`);
            summary.textContent = `${data.total} trabajos`;
            renderTable(data.items);
            renderPager(data);
            clearTimeout(timer);
            if (data.items.some((job) => ['queued', 'processing'].includes(job.status))) {
                timer = setTimeout(load, 4000);
            }
        } catch (error) {
            clear(holder);
            holder.append(h('div', { class: 'alert error' }, error.message));
        }
    }

    function actionButtons(job) {
        const buttons = [
            h('button', {
                class: 'btn outline sm',
                onclick: () => navigate(job.engine === 'compare' ? `comparar?job=${job.id}` : `datos?job=${job.id}`),
            }, 'Abrir'),
        ];
        if (job.status === 'done' && job.engine !== 'compare') {
            buttons.push(h('button', {
                class: 'btn outline sm',
                onclick: () => downloadFrom(`/api/jobs/${job.id}/export/xlsx`, { filters: {} }, `${job.filename}.xlsx`)
                    .catch((error) => toast(error.message, 'error')),
            }, 'XLSX'));
        }
        if (['queued', 'processing'].includes(job.status)) {
            buttons.push(h('button', {
                class: 'btn warning sm',
                onclick: () => api(`/api/jobs/${job.id}/cancel`, { method: 'POST' })
                    .then(() => load()).catch((error) => toast(error.message, 'error')),
            }, 'Cancelar'));
        } else {
            buttons.push(h('button', {
                class: 'btn outline sm',
                onclick: () => api(`/api/jobs/${job.id}/retry`, { method: 'POST', body: {} })
                    .then(() => { toast('Reprocesando', 'success'); load(); })
                    .catch((error) => toast(error.message, 'error')),
            }, 'Reintentar'));
        }
        buttons.push(h('button', {
            class: 'btn danger sm',
            onclick: async () => {
                if (!(await confirmDialog(`¿Eliminar el trabajo “${job.filename}”?`))) return;
                try {
                    await api(`/api/jobs/${job.id}`, { method: 'DELETE' });
                    toast('Trabajo eliminado', 'success');
                    load();
                } catch (error) { toast(error.message, 'error'); }
            },
        }, 'Borrar'));
        return h('div', { class: 'table-actions' }, ...buttons);
    }

    function renderTable(items) {
        clear(holder);
        if (!items.length) {
            holder.append(emptyState('Sin trabajos', 'No hay resultados para los filtros actuales.'));
            return;
        }
        const showUser = user.role === 'admin';
        const table = h('table', {});
        const head = h('tr', {},
            h('th', {}, 'Fecha'), h('th', {}, 'Archivo'), h('th', {}, 'Motor'),
            h('th', {}, 'Estado'), h('th', {}, 'Progreso'), h('th', { class: 'num' }, 'Páginas'),
            h('th', { class: 'num' }, 'Filas'), showUser ? h('th', {}, 'Usuario') : '',
            h('th', {}, 'Acciones'),
        );
        table.append(h('thead', {}, head));
        const tbody = h('tbody', {});
        for (const job of items) {
            tbody.append(h('tr', {},
                h('td', {}, fmtDateTime(job.created_at)),
                h('td', {}, job.filename),
                h('td', {}, job.engine),
                h('td', {}, statusBadge(job.status)),
                h('td', {}, `${job.progress || 0}%`),
                h('td', { class: 'num' }, job.total_pages),
                h('td', { class: 'num' }, job.row_count),
                showUser ? h('td', {}, job.user || '—') : '',
                h('td', {}, actionButtons(job)),
            ));
        }
        table.append(tbody);
        holder.append(h('div', { class: 'table-wrap desktop-table' }, table));

        const cards = h('div', { class: 'mobile-cards' });
        for (const job of items) {
            cards.append(h('div', { class: 'mobile-card' },
                h('div', { class: 'mc-head' }, h('strong', {}, job.filename), statusBadge(job.status)),
                h('div', { class: 'mc-row' }, h('span', {}, 'Fecha'), h('span', {}, fmtDateTime(job.created_at))),
                h('div', { class: 'mc-row' }, h('span', {}, 'Motor'), h('span', {}, job.engine)),
                h('div', { class: 'mc-row' }, h('span', {}, 'Filas'), h('span', {}, job.row_count)),
                h('div', { class: 'btn-row', style: 'margin-top:0.7rem' }, actionButtons(job)),
            ));
        }
        holder.append(cards);
    }

    function renderPager(data) {
        clear(pager);
        const pages = Math.max(1, Math.ceil(data.total / data.size));
        pager.append(
            h('div', { class: 'btn-row' },
                h('button', { class: 'btn outline sm', disabled: data.page <= 1, onclick: () => { state.page -= 1; load(); } }, '← Anterior'),
                h('span', {}, `Página ${data.page} de ${pages}`),
                h('button', { class: 'btn outline sm', disabled: data.page >= pages, onclick: () => { state.page += 1; load(); } }, 'Siguiente →'),
            ),
        );
    }

    (async () => {
        await loadUsers();
        await load();
    })();
    interval = setInterval(load, 15000);

    return { destroy() { clearTimeout(timer); clearInterval(interval); } };
}
