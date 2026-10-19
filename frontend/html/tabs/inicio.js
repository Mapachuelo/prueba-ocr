import { api } from '../api.js';
import { h, clear, emptyState, statusBadge, fmtDateTime, FIELD_LABELS } from '../ui.js';
import { icon } from '../icons.js';
import { donut, hbars, lineChart } from '../charts.js';

export function render(container, { navigate }) {
    const root = h('div', {});
    container.append(root);
    load();

    async function load() {
        clear(root);
        root.append(h('div', { class: 'empty' }, 'Cargando resumen…'));
        try {
            const [stats, jobs] = await Promise.all([
                api('/api/stats?filters=' + encodeURIComponent('{}')),
                api('/api/jobs?size=6'),
            ]);
            clear(root);
            renderStats(stats);
            renderRecent(jobs);
        } catch (error) {
            clear(root);
            root.append(h('div', { class: 'alert error' }, error.message));
        }
    }

    function renderStats(stats) {
        const completeness = stats.completeness || { complete: 0, partial: 0, incomplete: 0 };
        const totalPages = completeness.complete + completeness.partial + completeness.incomplete || stats.pages || 0;
        let ok = 0;
        let reference = 0;
        let filled = 0;
        for (const field of Object.values(stats.per_field || {})) {
            ok += field.ok;
            reference += field.total;
            filled += field.filled;
        }
        const accuracy = reference ? Math.round((ok * 100) / reference) : null;
        const completePct = totalPages ? Math.round((completeness.complete * 100) / totalPages) : 0;
        const coverage = totalPages ? Math.round((filled * 100) / (totalPages * 10)) : 0;

        if (!stats.jobs) {
            root.append(emptyState(
                'Todavía no hay trabajos',
                'Sube un PDF o Excel en “Cargar OCR” para empezar a ver métricas.',
            ), h('div', { class: 'btn-row' },
                h('button', { class: 'btn primary', onclick: () => navigate('cargar') }, icon('upload'), 'Cargar OCR'),
            ));
            return;
        }

        root.append(h('div', { class: 'kpi-grid' },
            kpi('Trabajos', stats.jobs, 'procesados', 'chart'),
            kpi('Páginas', stats.pages, 'analizadas', 'file'),
            kpi('Completas', `${completePct}%`, `${completeness.complete} de ${totalPages}`, 'check'),
            kpi('Precisión', accuracy === null ? '—' : `${accuracy}%`, reference ? `${ok}/${reference} campos` : 'sin referencia', 'compare'),
        ));

        const completenessBox = h('div', {});
        const coverageBox = h('div', {});
        const accuracyBox = h('div', {});
        const timelineBox = h('div', {});

        root.append(h('div', { class: 'charts-grid' },
            h('div', { class: 'chart-card' }, h('h3', {}, 'Estado de completitud'), completenessBox),
            h('div', { class: 'chart-card' }, h('h3', {}, 'Cobertura por campo'), coverageBox),
        ));
        root.append(h('div', { class: 'charts-grid' },
            h('div', { class: 'chart-card' }, h('h3', {}, 'Precisión por campo (vs. referencia)'), accuracyBox),
            h('div', { class: 'chart-card' }, h('h3', {}, 'Evolución de precisión'), timelineBox),
        ));

        donut(completenessBox, [
            { label: 'Completas', value: completeness.complete, color: '#0f9f6e' },
            { label: 'Parciales', value: completeness.partial, color: '#f59e0b' },
            { label: 'Incompletas', value: completeness.incomplete, color: '#cbd5e1' },
        ], { centerTop: `${completePct}%`, centerBottom: 'completas' });

        const coverageItems = Object.entries(stats.per_field || {}).map(([field, value]) => ({
            label: FIELD_LABELS[field] || field,
            value: totalPages ? Math.round((value.filled * 100) / totalPages) : 0,
        }));
        hbars(coverageBox, coverageItems, { max: 100, format: (value) => `${value}%` });

        const accuracyItems = Object.entries(stats.per_field || {})
            .filter(([, value]) => value.total > 0)
            .map(([field, value]) => ({
                label: FIELD_LABELS[field] || field,
                value: Math.round((value.ok * 100) / value.total),
                detail: `${value.ok}/${value.total}`,
            }));
        if (accuracyItems.length) {
            hbars(accuracyBox, accuracyItems, {
                max: 100,
                format: (value, item) => `${value}%`,
            });
            accuracyBox.append(h('p', { class: 'muted', style: 'margin-top:0.5rem' },
                `Cobertura global: ${coverage}% · referencia: ${stats.gt_pages} páginas`));
        } else {
            accuracyBox.append(emptyState('Sin referencia', 'Importa el ground truth para medir precisión.'));
        }

        const points = (stats.timeline || []).map((item) => ({ date: item.date, value: item.accuracy }));
        if (points.some((point) => point.value !== null)) {
            lineChart(timelineBox, points);
        } else {
            lineChart(timelineBox, (stats.timeline || []).map((item) => ({
                date: item.date, value: null,
            })));
        }
    }

    function kpi(label, value, hint, iconName) {
        return h('div', { class: 'kpi' },
            h('div', { class: 'label' }, icon(iconName, 15), ` ${label}`),
            h('div', { class: 'value' }, value),
            h('div', { class: 'hint' }, hint),
        );
    }

    function renderRecent(data) {
        if (!data.items.length) return;
        const tbody = h('tbody', {});
        for (const job of data.items) {
            tbody.append(h('tr', { class: 'row-click', onclick: () => navigate(job.engine === 'compare' ? `comparar?job=${job.id}` : `datos?job=${job.id}`) },
                h('td', {}, fmtDateTime(job.created_at)),
                h('td', {}, job.filename),
                h('td', {}, job.engine),
                h('td', {}, statusBadge(job.status)),
                h('td', { class: 'num' }, job.row_count),
            ));
        }
        root.append(h('div', { class: 'card' },
            h('div', { class: 'card-head' },
                h('div', {}, h('h2', {}, 'Trabajos recientes'), h('p', {}, 'Haz clic en una fila para abrirla')),
                h('button', { class: 'btn outline sm', onclick: () => navigate('historial') }, 'Ver historial'),
            ),
            h('div', { class: 'table-wrap desktop-table' },
                h('table', {},
                    h('thead', {}, h('tr', {},
                        h('th', {}, 'Fecha'), h('th', {}, 'Archivo'), h('th', {}, 'Motor'),
                        h('th', {}, 'Estado'), h('th', { class: 'num' }, 'Filas'),
                    )),
                    tbody,
                ),
            ),
            mobileJobs(data.items),
        ));
    }

    function mobileJobs(items) {
        const wrap = h('div', { class: 'mobile-cards' });
        for (const job of items) {
            wrap.append(h('div', { class: 'mobile-card', onclick: () => navigate(job.engine === 'compare' ? `comparar?job=${job.id}` : `datos?job=${job.id}`) },
                h('div', { class: 'mc-head' }, h('strong', {}, job.filename), statusBadge(job.status)),
                h('div', { class: 'mc-row' }, h('span', {}, 'Fecha'), h('span', {}, fmtDateTime(job.created_at))),
                h('div', { class: 'mc-row' }, h('span', {}, 'Motor'), h('span', {}, job.engine)),
                h('div', { class: 'mc-row' }, h('span', {}, 'Filas'), h('span', {}, job.row_count)),
            ));
        }
        return wrap;
    }

    return {};
}
