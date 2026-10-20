import { api } from '../api.js';
import { h, clear, toast, sourceDot, emptyState, FIELD_LABELS } from '../ui.js';
import { hbars } from '../charts.js';

export function render(container, { params, navigate }) {
    const state = { baseId: null, otherId: null, data: null };

    const baseSelect = h('select', { onchange: () => load() });
    const otherSelect = h('select', { onchange: () => load() });
    const fieldSelect = h('select', {});
    fieldSelect.append(h('option', { value: '' }, 'Todos los campos'));
    for (const [key, label] of Object.entries(FIELD_LABELS)) {
        fieldSelect.append(h('option', { value: key }, label));
    }
    const pageFrom = h('input', { type: 'number', min: 1, placeholder: 'Desde' });
    const pageTo = h('input', { type: 'number', min: 1, placeholder: 'Hasta' });
    const summaryBox = h('div', {});
    const diffBox = h('div', {});

    container.append(h('div', { class: 'card' },
        h('div', { class: 'card-head' },
            h('div', {}, h('h2', {}, 'Comparar modos'),
                h('p', { class: 'muted' }, 'Contrasta dos trabajos o un trabajo contra la referencia del agente.')),
        ),
        h('div', { class: 'filters' },
            h('label', { class: 'field' }, 'Trabajo A', baseSelect),
            h('label', { class: 'field' }, 'Contra (B)', otherSelect),
            h('label', { class: 'field' }, 'Campo', fieldSelect),
            h('label', { class: 'field' }, 'Página desde', pageFrom),
            h('label', { class: 'field' }, 'Página hasta', pageTo),
            h('div', { class: 'btn-row', style: 'align-self:end' },
                h('button', { class: 'btn primary', onclick: load }, 'Comparar'),
            ),
        ),
        summaryBox,
        diffBox,
    ));

    function filters() {
        const value = {};
        if (fieldSelect.value) value.field = fieldSelect.value;
        if (pageFrom.value) value.page_from = Number(pageFrom.value);
        if (pageTo.value) value.page_to = Number(pageTo.value);
        return value;
    }

    async function loadOptions() {
        const [jobsData, gt] = await Promise.all([
            api('/api/jobs?filters=' + encodeURIComponent(JSON.stringify({ status: 'done' })) + '&size=200'),
            api('/api/ground-truth').catch(() => null),
        ]);
        const jobs = jobsData.items.filter((job) => job.engine !== 'compare');
        clear(baseSelect);
        clear(otherSelect);
        for (const job of jobs) {
            const when = new Date(job.created_at).toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' });
            const label = `${when} · ${job.filename} · ${job.engine}`;
            baseSelect.append(h('option', { value: job.id }, label));
            otherSelect.append(h('option', { value: job.id }, label));
        }
        if (gt) {
            otherSelect.prepend(h('option', { value: gt.id }, 'Referencia · Agente (ground truth)'));
        }

        let baseId = params.job || null;
        let otherId = gt ? gt.id : null;
        if (baseId) {
            const job = await api(`/api/jobs/${baseId}`);
            if (job.engine === 'compare' && job.children?.length) {
                const localChild = job.children.find((child) => child.engine === 'local') || job.children[0];
                const otherChild = job.children.find((child) => child.engine !== localChild.engine);
                baseId = localChild.id;
                if (otherChild) otherId = otherChild.id;
            }
        }
        if (!baseId && jobs.length) baseId = jobs[0].id;
        if (!otherId) otherId = jobs.find((job) => job.id !== baseId)?.id || null;
        baseSelect.value = baseId || '';
        otherSelect.value = otherId || '';
    }

    async function load() {
        state.baseId = baseSelect.value;
        state.otherId = otherSelect.value;
        clear(summaryBox);
        clear(diffBox);
        if (!state.baseId || !state.otherId) {
            summaryBox.append(emptyState('Faltan trabajos', 'Necesitas al menos dos trabajos o la referencia para comparar.'));
            return;
        }
        summaryBox.append(h('div', { class: 'empty' }, 'Comparando…'));
        try {
            const query = new URLSearchParams({
                other_id: state.otherId,
                filters: JSON.stringify(filters()),
            });
            const data = await api(`/api/jobs/${state.baseId}/compare?${query}`);
            state.data = data;
            renderSummary(data);
            renderDiffs(data);
        } catch (error) {
            clear(summaryBox);
            summaryBox.append(h('div', { class: 'alert error' }, error.message));
        }
    }

    function renderSummary(data) {
        clear(summaryBox);
        const percent = data.total_cells ? Math.round((data.same_cells * 100) / data.total_cells) : 0;
        const cards = h('div', { class: 'kpi-grid', style: 'margin-top:1.2rem' },
            h('div', { class: 'kpi' }, h('div', { class: 'label' }, 'Coincidencia'), h('div', { class: 'value' }, `${percent}%`), h('div', { class: 'hint' }, 'del total de celdas')),
            h('div', { class: 'kpi' }, h('div', { class: 'label' }, 'Iguales'), h('div', { class: 'value' }, data.same_cells), h('div', { class: 'hint' }, 'mismo valor')),
            h('div', { class: 'kpi' }, h('div', { class: 'label' }, 'Distintas'), h('div', { class: 'value' }, data.diff_cells), h('div', { class: 'hint' }, 'requieren revisión')),
        );
        summaryBox.append(cards);
        summaryBox.append(h('p', { class: 'muted' },
            `A: ${data.base.filename} (${data.base.engine}) · B: ${data.other.filename} (${data.other.engine})`));

        const fieldItems = Object.entries(data.summary).map(([field, stats]) => {
            const total = stats.same + stats.diff;
            return {
                label: FIELD_LABELS[field] || field,
                value: total ? Math.round((stats.same * 100) / total) : 0,
            };
        });
        const chart = h('div', { class: 'chart-card', style: 'margin-top:1rem' },
            h('h3', {}, 'Coincidencia por campo'), h('div', {}));
        summaryBox.append(chart);
        hbars(chart.lastChild, fieldItems, { max: 100, format: (value) => `${value}%` });
    }

    function renderDiffs(data) {
        clear(diffBox);
        if (!data.diffs.length) {
            diffBox.append(emptyState('Sin diferencias', 'Los valores coinciden con los filtros actuales.'));
            return;
        }
        const table = h('table', {},
            h('thead', {}, h('tr', {},
                h('th', {}, 'Página'), h('th', {}, 'Campo'), h('th', {}, 'A'), h('th', {}, 'B'), h('th', {}, 'Acción'),
            )),
        );
        const tbody = h('tbody', {});
        for (const diff of data.diffs.slice(0, 500)) {
            tbody.append(h('tr', {},
                h('td', {}, diff.page),
                h('td', {}, FIELD_LABELS[diff.field] || diff.field),
                h('td', {}, diff.a || h('em', {}, 'vacío'), sourceDot(diff.a_source)),
                h('td', {}, diff.b || h('em', {}, 'vacío'), sourceDot(diff.b_source)),
                h('td', {}, h('button', {
                    class: 'btn outline sm',
                    onclick: () => useValue(diff),
                }, 'Usar B')),
            ));
        }
        table.append(tbody);
        const cards = h('div', { class: 'mobile-cards' });
        for (const diff of data.diffs.slice(0, 500)) {
            cards.append(h('div', { class: 'mobile-card' },
                h('div', { class: 'mc-head' },
                    h('strong', {}, `Página ${diff.page}`),
                    h('span', { class: 'muted' }, FIELD_LABELS[diff.field] || diff.field),
                ),
                h('div', { class: 'mc-row' }, h('span', {}, 'A'), h('span', {}, diff.a || 'vacío')),
                h('div', { class: 'mc-row' }, h('span', {}, 'B'), h('span', {}, diff.b || 'vacío')),
                h('div', { class: 'btn-row', style: 'margin-top:0.7rem' },
                    h('button', { class: 'btn outline sm', onclick: () => useValue(diff) }, 'Usar B'),
                ),
            ));
        }
        diffBox.append(
            h('div', { class: 'card-head', style: 'margin-top:1.2rem' },
                h('h3', {}, `Diferencias (${data.diffs.length})`),
                h('span', { class: 'muted' }, 'Máximo 500 filas en pantalla'),
            ),
            h('div', { class: 'table-wrap desktop-table' }, table),
            cards,
        );
    }

    async function useValue(diff) {
        try {
            await api(`/api/jobs/${state.baseId}/results`, {
                method: 'PATCH',
                body: { updates: [{ page: diff.page, field: diff.field, value: diff.b }] },
            });
            toast('Valor aplicado al trabajo A', 'success');
            load();
        } catch (error) {
            toast(error.message, 'error');
        }
    }

    (async () => {
        try {
            await loadOptions();
            await load();
        } catch (error) {
            toast(error.message, 'error');
        }
    })();

    return {};
}
