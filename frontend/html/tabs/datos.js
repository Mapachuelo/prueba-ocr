import { api, downloadFrom } from '../api.js';
import {
    h, clear, toast, sourceDot, completenessBadge,
    fmtDateTime, emptyState, openDrawer, modal,
} from '../ui.js';
import { icon } from '../icons.js';

const SOURCE_OPTIONS = [
    ['', 'Cualquier origen'], ['ai', 'IA local'], ['regex', 'OCR local'], ['mrz', 'MRZ'],
    ['barcode', 'Código de barras'], ['manual', 'Editado'], ['excel', 'Excel'],
];
const COMPLETENESS_OPTIONS = [
    ['', 'Todos'], ['complete', 'Completos'], ['partial', 'Parciales'], ['incomplete', 'Incompletos'],
];
const DEFAULT_COLUMNS = ['numero', 'apellidos', 'nombres', 'fecha_nacimiento', 'lugar_nacimiento', 'rh', 'sexo'];

export function render(container, { user, params, navigate }) {
    const state = {
        jobId: params.job || null,
        page: 1,
        size: 25,
        sort: 'pagina',
        dir: 'asc',
        filters: {},
        data: null,
        selected: new Set(),
        visible: null,
        jobs: [],
    };

    const jobSelect = h('select', { onchange: () => { state.jobId = jobSelect.value; state.page = 1; state.selected.clear(); load(); } });
    const searchInput = h('input', { type: 'search', placeholder: 'Buscar en cualquier campo…' });
    const filtersPanel = h('div', { class: 'filter-panel', hidden: true });
    const chipsBox = h('div', { class: 'chips' });
    const tableHolder = h('div', {});
    const pager = h('div', { class: 'pager' });
    const summary = h('div', { class: 'muted' });

    const f = {};
    const filterFields = h('div', { class: 'filters' },
        h('label', { class: 'field' }, 'Estado', f.completeness = select(COMPLETENESS_OPTIONS)),
        h('label', { class: 'field' }, 'Origen', f.source = select(SOURCE_OPTIONS)),
        textField('numero', 'Cédula contiene'),
        textField('apellidos', 'Apellidos contiene'),
        textField('nombres', 'Nombres contiene'),
        textField('lugar_nacimiento', 'Lugar de nacimiento'),
        textField('lugar_expedicion', 'Lugar de expedición'),
        h('label', { class: 'field' }, 'RH', f.rh = select([
            ['', 'Cualquiera'], ...['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-'].map((v) => [v, v]),
        ])),
        h('label', { class: 'field' }, 'Sexo', f.sexo = select([['', 'Cualquiera'], ['M', 'M'], ['F', 'F']])),
        numberField('estatura_min', 'Estatura mín.'),
        numberField('estatura_max', 'Estatura máx.'),
        dateField('fecha_nacimiento_from', 'Nacimiento desde'),
        dateField('fecha_nacimiento_to', 'Nacimiento hasta'),
        dateField('fecha_expedicion_from', 'Expedición desde'),
        dateField('fecha_expedicion_to', 'Expedición hasta'),
        numberField('page_from', 'Página desde'),
        numberField('page_to', 'Página hasta'),
        h('label', { class: 'field' }, 'Solo duplicados', f.only_duplicates = h('input', { type: 'checkbox' })),
    );

    filtersPanel.append(filterFields, h('div', { class: 'btn-row', style: 'margin-top:0.9rem' },
        h('button', { class: 'btn primary sm', onclick: applyFilters }, 'Aplicar filtros'),
        h('button', { class: 'btn outline sm', onclick: clearFilters }, 'Limpiar'),
    ));

    const toolbar = h('div', { class: 'btn-row', style: 'margin-top:1rem' },
        h('div', { style: 'flex:1 1 260px' }, searchInput),
        h('button', { class: 'btn outline', onclick: () => { filtersPanel.hidden = !filtersPanel.hidden; } }, icon('filter'), 'Filtros'),
        h('button', { class: 'btn outline', onclick: openColumnSelector }, icon('columns'), 'Columnas'),
        h('button', { class: 'btn outline sm', onclick: () => exportResults('xlsx') }, 'XLSX'),
        h('button', { class: 'btn outline sm', onclick: () => exportResults('xls') }, 'XLS'),
        h('button', { class: 'btn outline sm', onclick: () => exportResults('csv') }, 'CSV'),
        h('button', { class: 'btn outline sm', onclick: () => exportResults('pdf') }, 'PDF'),
    );
    searchInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') applyFilters(); });
    searchInput.addEventListener('search', applyFilters);

    container.append(h('div', { class: 'card' },
        h('div', { class: 'card-head' },
            h('div', { style: 'flex:1 1 320px' }, h('h2', {}, 'Resultados'), h('p', { class: 'muted' }, 'Filtra, revisa el detalle y exporta. Haz clic en una fila para ver y editar todos los campos.')),
            h('div', { style: 'flex:1 1 320px' }, jobSelect),
        ),
        toolbar,
        filtersPanel,
        chipsBox,
        summary,
        tableHolder,
        pager,
    ));

    function textField(key, label) {
        f[key] = h('input', { type: 'text' });
        return h('label', { class: 'field' }, label, f[key]);
    }
    function numberField(key, label) {
        f[key] = h('input', { type: 'number', min: 0 });
        return h('label', { class: 'field' }, label, f[key]);
    }
    function dateField(key, label) {
        f[key] = h('input', { type: 'date' });
        return h('label', { class: 'field' }, label, f[key]);
    }
    function select(options) {
        const el = h('select', {});
        for (const [value, label] of options) el.append(h('option', { value }, label));
        return el;
    }

    function readFilters() {
        const filters = {};
        if (searchInput.value.trim()) filters.q = searchInput.value.trim();
        if (f.completeness.value) filters.completeness = f.completeness.value;
        if (f.source.value) filters.source = f.source.value;
        for (const key of ['numero', 'apellidos', 'nombres', 'lugar_nacimiento', 'lugar_expedicion',
            'rh', 'sexo', 'estatura_min', 'estatura_max',
            'fecha_nacimiento_from', 'fecha_nacimiento_to',
            'fecha_expedicion_from', 'fecha_expedicion_to', 'page_from', 'page_to']) {
            if (f[key].value) filters[key] = f[key].value;
        }
        if (f.only_duplicates.checked) filters.only_duplicates = true;
        return filters;
    }

    function applyFilters() {
        state.filters = readFilters();
        state.page = 1;
        state.selected.clear();
        load();
    }

    function clearFilters() {
        searchInput.value = '';
        for (const element of Object.values(f)) {
            if (element.type === 'checkbox') element.checked = false;
            else element.value = '';
        }
        state.filters = {};
        state.page = 1;
        state.selected.clear();
        load();
    }

    function chips() {
        clear(chipsBox);
        const labels = {
            q: 'Buscar', completeness: 'Estado', source: 'Origen', numero: 'Cédula',
            apellidos: 'Apellidos', nombres: 'Nombres', lugar_nacimiento: 'Lugar nac.',
            lugar_expedicion: 'Lugar exp.', rh: 'RH', sexo: 'Sexo',
            estatura_min: 'Estatura mín.', estatura_max: 'Estatura máx.',
            fecha_nacimiento_from: 'Nac. desde', fecha_nacimiento_to: 'Nac. hasta',
            fecha_expedicion_from: 'Exp. desde', fecha_expedicion_to: 'Exp. hasta',
            page_from: 'Página desde', page_to: 'Página hasta', only_duplicates: 'Duplicados',
        };
        for (const [key, value] of Object.entries(state.filters)) {
            if (value === undefined || value === '') continue;
            chipsBox.append(h('span', { class: 'chip' },
                `${labels[key] || key}: ${key === 'only_duplicates' ? 'sí' : value}`,
                h('button', {
                    title: 'Quitar filtro',
                    onclick: () => {
                        state.filters = { ...state.filters };
                        delete state.filters[key];
                        if (key === 'q') searchInput.value = '';
                        else if (f[key]) {
                            if (f[key].type === 'checkbox') f[key].checked = false;
                            else f[key].value = '';
                        }
                        state.page = 1;
                        load();
                    },
                }, '×'),
            ));
        }
    }

    async function loadJobs() {
        const data = await api('/api/jobs?filters=' + encodeURIComponent(JSON.stringify({ status: 'done' })) + '&size=200');
        state.jobs = data.items.filter((job) => job.engine !== 'compare');
        clear(jobSelect);
        if (!state.jobs.length) {
            jobSelect.append(h('option', { value: '' }, 'Sin trabajos terminados'));
            return;
        }
        for (const job of state.jobs) {
            jobSelect.append(h('option', { value: job.id },
                `${fmtDateTime(job.created_at)} · ${job.filename} · ${job.engine}`));
        }
        if (!state.jobId || !state.jobs.some((job) => job.id === state.jobId)) {
            state.jobId = state.jobs[0].id;
        }
        jobSelect.value = state.jobId;
    }

    function defaultColumns(columns) {
        const available = columns.map((column) => column.key);
        const chosen = DEFAULT_COLUMNS.filter((key) => available.includes(key));
        return chosen.length ? chosen : available.slice(0, 6);
    }

    function visibleColumns(data) {
        if (!state.visible) {
            try {
                const stored = JSON.parse(localStorage.getItem('ocr.visibleColumns') || 'null');
                if (Array.isArray(stored)) state.visible = stored.filter((key) => data.columns.some((column) => column.key === key));
            } catch (error) { state.visible = null; }
            if (!state.visible || !state.visible.length) state.visible = defaultColumns(data.columns);
        }
        return data.columns.filter((column) => state.visible.includes(column.key));
    }

    async function load() {
        if (!state.jobId) {
            clear(tableHolder);
            tableHolder.append(emptyState('Sin trabajos', 'Procesa un archivo en “Cargar OCR” para ver resultados.'));
            pager.innerHTML = '';
            summary.textContent = '';
            return;
        }
        chips();
        clear(tableHolder);
        tableHolder.append(h('div', { class: 'empty' }, 'Cargando resultados…'));
        try {
            const query = new URLSearchParams({
                filters: JSON.stringify(state.filters),
                page: state.page,
                size: state.size,
                sort: state.sort,
                direction: state.dir,
            });
            const data = await api(`/api/jobs/${state.jobId}/results?${query}`);
            state.data = data;
            state.visible = null;
            renderTable(data);
            summary.textContent = `${data.total} filas · ${data.job.filename} · ${data.job.extractor || ''}`;
            renderPager(data);
        } catch (error) {
            clear(tableHolder);
            tableHolder.append(h('div', { class: 'alert error' }, error.message));
        }
    }

    function originalSource(source) {
        return source || 'regex';
    }

    function dominantSource(row) {
        const values = Object.values(row.sources || {});
        for (const source of ['manual', 'ai', 'mrz', 'barcode', 'excel', 'regex']) {
            if (values.includes(source)) return source;
        }
        return 'regex';
    }

    function renderTable(data) {
        const columns = visibleColumns(data);
        const isCedula = data.columns.some((column) => column.key === 'numero');
        const table = h('table');
        const headRow = h('tr', {},
            h('th', {}, h('input', {
                type: 'checkbox', title: 'Seleccionar página',
                onchange: (event) => {
                    if (event.target.checked) data.rows.forEach((row) => state.selected.add(row.page));
                    else data.rows.forEach((row) => state.selected.delete(row.page));
                    renderTable(data);
                },
            })),
            h('th', { class: 'sortable', onclick: () => sortBy('pagina') }, 'Página', sortMark('pagina')),
        );
        for (const column of columns) {
            headRow.append(h('th', { class: 'sortable', onclick: () => sortBy(column.key) },
                column.label, sortMark(column.key)));
        }
        if (isCedula) headRow.append(h('th', {}, 'Estado'), h('th', {}, 'Origen'));
        table.append(h('thead', {}, headRow));

        const tbody = h('tbody', {});
        for (const row of data.rows) {
            const tr = h('tr', { class: 'row-click', onclick: (event) => {
                if (event.target.closest('input,button')) return;
                openRow(row);
            } },
                h('td', {}, h('input', {
                    type: 'checkbox', checked: state.selected.has(row.page),
                    onchange: (event) => {
                        if (event.target.checked) state.selected.add(row.page);
                        else state.selected.delete(row.page);
                    },
                })),
                h('td', { class: 'num' }, row.page),
            );
            for (const column of columns) {
                const value = row.values[column.key] ?? '';
                const source = originalSource(row.sources[column.key]);
                if (column.key === 'OCR_Raw') {
                    tr.append(h('td', { title: value }, truncate(value, 60)));
                } else {
                    tr.append(h('td', {}, value || h('em', {}, '—'), sourceDot(source)));
                }
            }
            if (isCedula) {
                tr.append(
                    h('td', {}, completenessBadge(row.values)),
                    h('td', {}, sourceDot(dominantSource(row)), sourceLabel(dominantSource(row))),
                );
            }
            tbody.append(tr);
        }
        table.append(tbody);

        clear(tableHolder);
        tableHolder.append(h('div', { class: 'table-wrap desktop-table' }, table), renderCards(data, columns, isCedula));
    }

    function sourceLabel(source) {
        const labels = { regex: 'OCR', ai: 'IA', mrz: 'MRZ', barcode: 'Barras', manual: 'Manual', excel: 'Excel' };
        return h('span', { class: 'muted', style: 'margin-left:0.3rem' }, labels[source] || source);
    }

    function sortMark(key) {
        if (state.sort !== key) return '';
        return state.dir === 'asc' ? ' ↑' : ' ↓';
    }

    function truncate(value, size) {
        const text = String(value || '');
        return text.length > size ? `${text.slice(0, size)}…` : text;
    }

    function renderCards(data, columns, isCedula) {
        const wrap = h('div', { class: 'mobile-cards' });
        for (const row of data.rows) {
            const card = h('div', { class: 'mobile-card' },
                h('div', { class: 'mc-head' },
                    h('strong', {}, `Página ${row.page}`),
                    isCedula ? completenessBadge(row.values) : null,
                ),
            );
            for (const column of columns.slice(0, 4)) {
                card.append(h('div', { class: 'mc-row' },
                    h('span', {}, column.label),
                    h('span', {}, truncate(row.values[column.key] ?? '—', 40)),
                ));
            }
            card.append(h('div', { class: 'btn-row', style: 'margin-top:0.7rem' },
                h('button', { class: 'btn outline sm', onclick: () => openRow(row) }, 'Ver / editar'),
            ));
            wrap.append(card);
        }
        return wrap;
    }

    function openRow(row) {
        const data = state.data;
        const inputs = {};
        const body = h('div', { class: 'stack' });
        for (const column of data.columns) {
            if (column.key === 'OCR_Raw') continue;
            inputs[column.key] = h('input', { type: 'text', value: row.values[column.key] ?? '' });
            body.append(h('div', {},
                h('label', { class: 'field' }, column.label, inputs[column.key]),
                h('div', { class: 'field-source' },
                    sourceDot(row.sources[column.key]),
                    `Origen: ${sourceText(row.sources[column.key])}`),
            ));
        }
        if (row.values.OCR_Raw) {
            body.append(h('div', {},
                h('div', { class: 'section-title' }, 'Texto OCR crudo'),
                h('div', { class: 'raw-text' }, row.values.OCR_Raw),
            ));
        }

        const drawer = openDrawer({
            title: `Página ${row.page}`,
            subtitle: data.job.filename,
            content: body,
            footer: [
                h('button', { class: 'btn outline', onclick: () => drawer.close() }, 'Cancelar'),
                h('button', { class: 'btn primary', onclick: () => saveRow(row, inputs, drawer) }, 'Guardar cambios'),
            ],
        });
    }

    async function saveRow(row, inputs, drawerElement) {
        const updates = [];
        for (const [field, input] of Object.entries(inputs)) {
            if ((row.values[field] ?? '') !== input.value) {
                updates.push({ page: row.page, field, value: input.value });
            }
        }
        if (!updates.length) { toast('Sin cambios', 'info'); return; }
        try {
            await api(`/api/jobs/${state.jobId}/results`, { method: 'PATCH', body: { updates } });
            toast('Cambios guardados', 'success');
            if (drawerElement && drawerElement.close) drawerElement.close();
            load();
        } catch (error) {
            toast(error.message, 'error');
        }
    }

    function sourceText(source) {
        const labels = { regex: 'OCR local', ai: 'IA local', mrz: 'MRZ', barcode: 'Código de barras', manual: 'Editado a mano', excel: 'Excel', agent: 'Referencia' };
        return labels[source] || source || 'OCR local';
    }

    function sortBy(key) {
        if (state.sort === key) state.dir = state.dir === 'asc' ? 'desc' : 'asc';
        else { state.sort = key; state.dir = 'asc'; }
        load();
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
            h('div', { class: 'btn-row' },
                h('span', { class: 'muted' }, `${state.selected.size} seleccionadas`),
                h('select', {
                    onchange: (event) => { state.size = Number(event.target.value); state.page = 1; load(); },
                }, ...[25, 50, 100, 200].map((size) => h('option', { value: size, selected: size === state.size }, `${size} por página`))),
            ),
        );
    }

    function openColumnSelector() {
        if (!state.data) return;
        const selected = new Set(visibleColumns(state.data).map((column) => column.key));
        const body = h('div', { class: 'stack' });
        for (const column of state.data.columns) {
            body.append(h('label', { class: 'checkbox' },
                h('input', {
                    type: 'checkbox', checked: selected.has(column.key),
                    onchange: (event) => {
                        if (event.target.checked) selected.add(column.key);
                        else selected.delete(column.key);
                    },
                }),
                column.label,
            ));
        }
        modal('Columnas visibles', body, [{
            label: 'Aplicar', class: 'primary',
            onClick: (close) => {
                if (!selected.size) { toast('Elige al menos una columna', 'warning'); return; }
                state.visible = [...selected];
                localStorage.setItem('ocr.visibleColumns', JSON.stringify(state.visible));
                close();
                renderTable(state.data);
            },
        }]);
    }

    async function exportResults(fmt) {
        if (!state.jobId || !state.data) return;
        const filters = { ...state.filters };
        if (state.selected.size) filters.pages = [...state.selected];
        try {
            toast(`Generando ${fmt.toUpperCase()}…`);
            const stem = (state.data.job.filename || 'resultados').replace(/\.[^.]+$/, '');
            await downloadFrom(`/api/jobs/${state.jobId}/export/${fmt}`, { filters }, `${stem}.${fmt}`);
        } catch (error) {
            toast(error.message, 'error');
        }
    }

    (async () => {
        try {
            await loadJobs();
            await load();
        } catch (error) {
            toast(error.message, 'error');
        }
    })();

    return {};
}
