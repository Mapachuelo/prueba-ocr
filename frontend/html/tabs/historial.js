import { api, downloadFrom } from '../api.js';
import { h, clear, toast, statusBadge, confirmDialog, fmtDateTime, emptyState, actionMenu, modal, notifyDataChanged, watchDataChanges } from '../ui.js';
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
            h('div', { class: 'btn-row' },
                user.role === 'admin' ? h('button', { class: 'btn danger sm', onclick: openDeleteAll }, icon('trash'), 'Borrar todos') : null,
                user.role === 'admin' ? h('button', { class: 'btn danger sm', onclick: openBulkDelete }, icon('trash'), 'Borrar por rango') : null,
                h('button', { class: 'btn outline sm', onclick: () => load() }, icon('refresh'), 'Actualizar'),
            ),
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



    function openDeleteAll() {
        const password = h('input', {
            type: 'password', placeholder: 'Contraseña actual del administrador',
            autocomplete: 'current-password',
        });
        const message = h('div', {});
        const preserve = h('input', { type: 'checkbox' });
        modal('Borrar todos los trabajos', h('div', { class: 'stack' },
            h('p', { class: 'muted' }, 'Esta acción elimina todos los trabajos, resultados y documentos/PDFs cargados. No se puede deshacer.'),
            h('label', { class: 'field' }, 'Contraseña', password),
            h('label', { class: 'checkbox' }, preserve, 'Conservar los PDFs y documentos originales'),
            message,
        ), [{
            label: 'Continuar', class: 'danger',
            onClick: async (close) => {
                clear(message);
                if (!password.value) {
                    message.append(h('div', { class: 'alert error' }, 'Escribe tu contraseña'));
                    return;
                }
                try {
                    await api('/api/auth/verify-password', {
                        method: 'POST', body: { password: password.value },
                    });
                } catch (error) {
                    message.append(h('div', { class: 'alert error' }, error.message));
                    return;
                }
                close();
                let total = 0;
                let documents = 0;
                try {
                    const [jobsData, docsData] = await Promise.all([
                        api('/api/jobs?size=1'),
                        api('/api/documents?limit=200'),
                    ]);
                    total = jobsData.total;
                    documents = docsData.items.length;
                } catch (error) { /* se confirma sin cantidad */ }
                const keep = preserve.checked;
                const ok = await confirmDialog(
                    keep
                        ? `¿Eliminar ${total || 'todos los'} trabajos? Los PDFs se conservarán.`
                        : `¿Eliminar ${total || 'todos los'} trabajos y ${documents || 'todos los'} documentos/PDFs? Esta acción no se puede deshacer.`,
                );
                if (!ok) return;
                try {
                    const result = await api('/api/jobs/delete-all', {
                        method: 'POST',
                        body: { password: password.value, include_documents: !keep },
                    });
                    toast(
                        `Se eliminaron ${result.jobs} trabajo(s)`
                        + (result.documents ? ` y ${result.documents} documento(s)` : ''),
                        'success',
                    );
                    notifyDataChanged();
                    load();
                } catch (error) {
                    toast(error.message, 'error');
                }
            },
        }]);
    }

    async function openBulkDelete() {
        const from = h('input', { type: 'date', value: dateFrom.value || '' });
        const to = h('input', { type: 'date', value: dateTo.value || '' });
        const owner = h('select', {}, h('option', { value: '' }, 'Todos los usuarios'));
        try {
            const data = await api('/api/users');
            for (const item of data.items) {
                owner.append(h('option', { value: item.id }, `${item.username} (${item.role})`));
            }
        } catch (error) { /* la lista de usuarios es opcional */ }
        if (userSelect.value) owner.value = userSelect.value;
        const includeDocuments = h('input', { type: 'checkbox' });
        const preview = h('div', { class: 'muted' }, 'Completa el rango y pulsa “Previsualizar”.');
        const body = h('div', { class: 'stack' },
            h('p', { class: 'muted' }, 'Se eliminarán los trabajos creados dentro del rango. Por defecto los PDFs se conservan.'),
            h('div', { class: 'filters' },
                h('label', { class: 'field' }, 'Fecha inicial', from),
                h('label', { class: 'field' }, 'Fecha final', to),
                h('label', { class: 'field' }, 'Usuario', owner),
            ),
            h('label', { class: 'checkbox' }, includeDocuments, 'Eliminar también documentos que queden sin trabajos'),
            preview,
        );
        const readForm = () => ({
            date_from: from.value,
            date_to: to.value,
            user_id: owner.value || null,
            include_documents: includeDocuments.checked,
        });
        const doPreview = async () => {
            const form = readForm();
            if (!form.date_from || !form.date_to) {
                toast('Indica la fecha inicial y la final', 'warning');
                return null;
            }
            if (form.date_from > form.date_to) {
                toast('La fecha inicial no puede ser posterior a la final', 'warning');
                return null;
            }
            const query = new URLSearchParams({ date_from: form.date_from, date_to: form.date_to });
            if (form.user_id) query.set('user_id', form.user_id);
            try {
                const data = await api(`/api/jobs/bulk-delete/preview?${query}`);
                clear(preview);
                preview.append(h('div', { class: `alert ${data.active_jobs ? 'warning' : 'info'}` },
                    `${data.jobs} trabajo(s) · ${data.users} usuario(s) · ${data.documents} documento(s).`
                    + (data.active_jobs ? ` ${data.active_jobs} en curso; cancélalos antes de borrar.` : ''),
                ));
                return data;
            } catch (error) {
                clear(preview);
                preview.append(h('div', { class: 'alert error' }, error.message));
                return null;
            }
        };
        modal('Borrar por rango', body, [
            { label: 'Previsualizar', class: 'outline', onClick: doPreview },
            {
                label: 'Borrar', class: 'danger',
                onClick: async (close) => {
                    const data = await doPreview();
                    if (!data || data.active_jobs) return;
                    if (!data.jobs) { toast('No hay trabajos en ese rango', 'warning'); return; }
                    const ok = await confirmDialog(
                        `¿Eliminar ${data.jobs} trabajo(s) entre ${from.value} y ${to.value}?`,
                    );
                    if (!ok) return;
                    try {
                        const result = await api('/api/jobs/bulk-delete', {
                            method: 'POST', body: readForm(),
                        });
                        toast(
                            `Se eliminaron ${result.jobs} trabajo(s)`
                            + (result.documents ? ` y ${result.documents} documento(s)` : ''),
                            'success',
                        );
                        close();
                        load();
                    } catch (error) { toast(error.message, 'error'); }
                },
            },
        ]);
    }

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

    function engineCell(job) {
        return h('span', {},
            job.engine,
            job.engine === 'ai' && !job.ai_used
                ? h('span', { class: 'badge-status warning', style: 'margin-left:0.35rem' }, 'Fallback local')
                : null,
        );
    }

    function actionButtons(job) {
        const primary = h('button', {
            class: 'btn outline sm',
            onclick: () => navigate(job.engine === 'compare' ? `comparar?job=${job.id}` : `datos?job=${job.id}`),
        }, 'Abrir');
        const secondary = [];
        if (job.status === 'done' && job.engine !== 'compare') {
            secondary.push({
                label: 'Descargar XLSX',
                onClick: () => downloadFrom(`/api/jobs/${job.id}/export/xlsx`, { filters: {} }, `${job.filename}.xlsx`)
                    .catch((error) => toast(error.message, 'error')),
            });
        }
        if (['queued', 'processing'].includes(job.status)) {
            secondary.push({
                label: 'Cancelar trabajo',
                onClick: () => api(`/api/jobs/${job.id}/cancel`, { method: 'POST' })
                    .then(() => load()).catch((error) => toast(error.message, 'error')),
            });
        } else {
            secondary.push({
                label: 'Reintentar OCR',
                onClick: () => api(`/api/jobs/${job.id}/retry`, { method: 'POST', body: {} })
                    .then(() => { toast('Reprocesando', 'success'); load(); })
                    .catch((error) => toast(error.message, 'error')),
            });
        }
        secondary.push({
            label: 'Borrar trabajo',
            danger: true,
            onClick: async () => {
                if (!(await confirmDialog(
                    `¿Eliminar el trabajo “${job.filename}”? El documento original se conservará en Cargar OCR.`,
                ))) return;
                try {
                    await api(`/api/jobs/${job.id}`, { method: 'DELETE' });
                    toast('Trabajo eliminado; el documento se conservó', 'success');
                    load();
                } catch (error) { toast(error.message, 'error'); }
            },
        });
        return h('div', { class: 'table-actions' }, primary, actionMenu(secondary));
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
                h('td', {}, h('strong', {}, job.filename),
                    job.original_filename && job.original_filename !== job.filename
                        ? h('div', { class: 'muted' }, `Original: ${job.original_filename}`)
                        : null),
                h('td', {}, engineCell(job)),
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
                job.original_filename && job.original_filename !== job.filename
                    ? h('div', { class: 'mc-row' }, h('span', {}, 'Original'), h('span', {}, job.original_filename))
                    : null,
                h('div', { class: 'mc-row' }, h('span', {}, 'Fecha'), h('span', {}, fmtDateTime(job.created_at))),
                h('div', { class: 'mc-row' }, h('span', {}, 'Motor'), h('span', {}, engineCell(job))),
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

    const stopWatch = watchDataChanges(load);
    return { destroy() { clearTimeout(timer); clearInterval(interval); stopWatch(); } };
}
