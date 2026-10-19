import { api } from '../api.js';
import { h, clear, toast, statusBadge, fmtDateTime } from '../ui.js';
import { icon } from '../icons.js';

const ENGINES = [
    { id: 'local', title: 'Local', detail: 'Tesseract + OpenCV, sin IA', icon: 'cpu' },
    { id: 'ai', title: 'IA local', detail: 'Modelo de visión en llama.cpp', icon: 'scan' },
    { id: 'compare', title: 'Comparar', detail: 'Ejecuta local e IA y contrasta', icon: 'compare' },
];

export function render(container, { navigate }) {
    let file = null;
    let engine = 'local';
    let selectedModel = '';
    let jobId = null;
    let timer = null;

    const fileInput = h('input', {
        type: 'file', accept: '.pdf,.xlsx,.xls', hidden: true,
        onchange: () => { if (fileInput.files.length) setFile(fileInput.files[0]); },
    });
    const fileName = h('div', { class: 'file-name' }, 'Ningún archivo seleccionado');
    const dropzone = h('div', {
        class: 'dropzone',
        onclick: () => fileInput.click(),
        ondragover: (event) => { event.preventDefault(); dropzone.classList.add('dragover'); },
        ondragleave: () => dropzone.classList.remove('dragover'),
        ondrop: (event) => {
            event.preventDefault();
            dropzone.classList.remove('dragover');
            if (event.dataTransfer.files.length) setFile(event.dataTransfer.files[0]);
        },
    }, h('strong', {}, 'Selecciona o arrastra un archivo'), h('div', {}, 'PDF, XLSX o XLS · hasta 50 MB'), fileName);

    const engineBox = h('div', { class: 'engine-choice' });
    const modelBox = h('div', { class: 'model-box' });
    const profile = h('select', {},
        h('option', { value: 'cand' }, 'cand (recomendado)'),
        h('option', { value: 'legacy' }, 'legacy'),
        h('option', { value: '' }, 'Usar valor del servidor'),
    );
    const dpi = h('select', {},
        h('option', { value: '' }, 'Por defecto'),
        h('option', { value: '200' }, '200 dpi'),
        h('option', { value: '300' }, '300 dpi'),
        h('option', { value: '400' }, '400 dpi'),
    );
    const pages = h('input', { type: 'text', placeholder: 'todas, p. ej. 1-5,8' });
    const pdfOptions = h('div', { class: 'grid auto' },
        h('label', { class: 'field' }, 'Perfil OCR', profile),
        h('label', { class: 'field' }, 'DPI', dpi),
        h('label', { class: 'field' }, 'Páginas', pages),
    );
    const submit = h('button', { class: 'btn primary', type: 'submit' }, icon('upload'), 'Procesar archivo');

    const form = h('form', { class: 'stack', onsubmit: (event) => { event.preventDefault(); startJob(); } },
        submit,
    );

    const stepFile = h('section', { class: 'step-card' },
        h('div', { class: 'step-head' }, h('span', { class: 'step-num' }, '1'), h('h2', {}, 'Archivo')),
        dropzone, fileInput,
    );
    const stepEngine = h('section', { class: 'step-card' },
        h('div', { class: 'step-head' }, h('span', { class: 'step-num' }, '2'), h('h2', {}, 'Motor OCR')),
        engineBox, modelBox,
    );
    const stepOptions = h('section', { class: 'step-card' },
        h('div', { class: 'step-head' }, h('span', { class: 'step-num' }, '3'), h('h2', {}, 'Opciones')),
        pdfOptions, h('div', { style: 'margin-top:1rem' }, form),
    );

    const progressBar = h('div', { class: 'progress' }, h('div', { style: 'width:0%' }));
    const progressInfo = h('div', {});
    const logBox = h('div', { class: 'log' });
    const cancelBtn = h('button', { class: 'btn danger sm', onclick: cancelJob }, 'Cancelar');
    const resultsBtn = h('button', { class: 'btn success sm', onclick: () => navigate(`datos?job=${jobId}`) }, 'Ver resultados');
    const compareBtn = h('button', { class: 'btn warning sm', onclick: () => navigate(`comparar?job=${jobId}`) }, 'Comparar modos');
    const progressCard = h('div', { class: 'card', hidden: true },
        h('div', { class: 'card-head' }, h('div', {}, h('h2', {}, 'Progreso'), h('p', { class: 'muted' }, 'Puedes cambiar de sección; el trabajo continúa en segundo plano.'))),
        progressInfo, progressBar,
        h('div', { class: 'btn-row', style: 'margin-top:0.9rem' }, cancelBtn, resultsBtn, compareBtn),
        logBox,
    );
    const recent = h('div', {});

    container.append(
        h('div', { class: 'steps' }, stepFile, stepEngine, stepOptions),
        progressCard,
        h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('div', {}, h('h2', {}, 'Últimos trabajos'))), recent),
    );

    renderEngineChoices();
    loadProviders();
    loadRecent();

    function renderEngineChoices() {
        clear(engineBox);
        for (const option of ENGINES) {
            const choice = h('label', { class: `choice ${engine === option.id ? 'selected' : ''}` },
                h('input', {
                    type: 'radio', name: 'engine', value: option.id, checked: engine === option.id,
                    onchange: () => { engine = option.id; renderEngineChoices(); updateModelVisibility(); },
                }),
                h('span', { class: 'choice-icon' }, icon(option.icon, 18)),
                h('span', {}, h('strong', {}, option.title), h('small', {}, option.detail)),
            );
            engineBox.append(choice);
        }
    }

    function updateModelVisibility() {
        const ai = engine !== 'local';
        modelBox.hidden = !ai;
        if (ai) renderModels();
    }

    function setFile(selected) {
        file = selected;
        fileName.textContent = `${selected.name} · ${(selected.size / 1024).toFixed(0)} KB`;
        pdfOptions.hidden = !selected.name.toLowerCase().endsWith('.pdf');
        if (pdfOptions.hidden) { engine = 'local'; renderEngineChoices(); updateModelVisibility(); }
    }

    let providers = null;
    async function loadProviders(refresh = false) {
        try {
            providers = await api(`/api/ai/providers${refresh ? '?refresh=1' : ''}`);
            renderModels();
        } catch (error) {
            providers = { local: { reachable: false, models: [], error: error.message } };
            renderModels();
        }
    }

    function renderModels() {
        if (engine === 'local') { modelBox.innerHTML = ''; return; }
        clear(modelBox);
        const externalActive = providers?.active_provider === 'external' && providers?.external?.configured;
        const source = externalActive ? providers.external : (providers?.local || {});
        const models = source.models || [];
        if (!models.length) {
            modelBox.append(
                h('div', { class: 'alert warning' },
                    h('strong', {}, externalActive ? 'No hay modelos en el proveedor externo. ' : 'No se detectó un modelo local. '),
                    source.error || (externalActive ? 'Configúralo en Configuración.' : 'Revisa que llama.cpp esté levantado.'),
                ),
                h('div', { class: 'btn-row' },
                    h('button', { class: 'btn outline sm', type: 'button', onclick: () => loadProviders(true) }, icon('refresh'), 'Escanear de nuevo'),
                ),
                externalActive ? null : h('p', { class: 'muted' }, 'Servidor esperado: ' + (source.default_url || 'http://host.containers.internal:9931/v1')),
            );
            return;
        }
        const preferred = models.find((model) => model.id === selectedModel)
            || models.find((model) => model.loaded && model.vision)
            || models.find((model) => model.loaded)
            || models[0];
        selectedModel = preferred.id;
        modelBox.append(h('div', { class: 'section-title' }, externalActive ? 'Modelos del proveedor externo' : 'Modelo detectado'));
        for (const model of models) {
            modelBox.append(h('label', { class: `choice ${selectedModel === model.id ? 'selected' : ''}` },
                h('input', {
                    type: 'radio', name: 'model', checked: selectedModel === model.id,
                    onchange: () => { selectedModel = model.id; renderModels(); },
                }),
                h('span', { style: 'flex:1;min-width:0' },
                    h('strong', {}, model.id),
                    h('span', { class: 'btn-row', style: 'margin-top:0.25rem;gap:0.3rem' },
                        externalActive
                            ? h('span', { class: 'badge' }, 'Externo')
                            : h('span', { class: `badge ${model.loaded ? 'loaded' : 'unloaded'}` }, model.loaded ? 'Cargado' : 'No cargado'),
                        model.vision ? h('span', { class: 'badge vision' }, 'Visión') : null,
                        model.context ? h('span', { class: 'badge' }, `${Math.round(model.context / 1000)}k ctx`) : null,
                    ),
                ),
            ));
        }
        modelBox.append(h('div', { class: 'btn-row' },
            h('button', { class: 'btn outline sm', type: 'button', onclick: () => loadProviders(true) }, icon('refresh'), 'Escanear de nuevo'),
            h('span', { class: 'model-status ok' }, `${externalActive ? 'Proveedor' : 'Servidor'}: ${source.base_url || ''}`),
        ));
    }

    async function startJob() {
        if (!file) { toast('Selecciona un archivo primero', 'warning'); return; }
        if (engine !== 'local' && !selectedModel) {
            toast('Selecciona un modelo de IA disponible', 'warning');
            return;
        }
        submit.disabled = true;
        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('engine', engine);
            if (!pdfOptions.hidden) {
                if (profile.value) formData.append('profile', profile.value);
                if (dpi.value) formData.append('dpi', dpi.value);
                if (pages.value.trim()) formData.append('pages', pages.value.trim());
            }
            if (engine !== 'local' && selectedModel) formData.append('model', selectedModel);
            const data = await api('/api/jobs', { method: 'POST', form: formData });
            jobId = data.id;
            progressCard.hidden = false;
            resultsBtn.hidden = true;
            compareBtn.hidden = true;
            cancelBtn.hidden = false;
            progressBar.classList.remove('success', 'error');
            progressBar.firstChild.style.width = '0%';
            clear(logBox);
            poll();
        } catch (error) {
            toast(error.message, 'error');
        } finally {
            submit.disabled = false;
        }
    }

    async function poll() {
        clearTimeout(timer);
        try {
            const job = await api(`/api/jobs/${jobId}`);
            const final = ['done', 'error', 'cancelled'].includes(job.status);
            progressBar.firstChild.style.width = `${job.progress || 0}%`;
            progressBar.classList.toggle('success', job.status === 'done');
            progressBar.classList.toggle('error', job.status === 'error');
            clear(progressInfo);
            progressInfo.append(h('div', { class: 'btn-row', style: 'margin-bottom:0.5rem' },
                statusBadge(job.status),
                h('span', { class: 'muted' }, `${job.progress || 0}%`),
                job.total_pages ? h('span', { class: 'muted' }, `${job.total_pages} páginas`) : null,
                job.ai_used ? h('span', { class: 'badge vision' }, 'IA usada') : null,
            ));
            if (job.error) progressInfo.append(h('div', { class: 'alert error' }, job.error));
            const events = await api(`/api/jobs/${jobId}/events?limit=30`);
            clear(logBox);
            for (const event of events.items) {
                logBox.append(h('div', { class: event.level }, `[${fmtDateTime(event.ts)}] ${event.message}`));
            }
            logBox.scrollTop = logBox.scrollHeight;
            cancelBtn.hidden = final;
            resultsBtn.hidden = !final || job.status !== 'done' || job.engine === 'compare';
            compareBtn.hidden = !final || job.engine !== 'compare';
            if (!final) timer = setTimeout(poll, 1500);
            else loadRecent();
        } catch (error) {
            toast(error.message, 'error');
        }
    }

    async function cancelJob() {
        try {
            await api(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
            toast('Cancelación solicitada', 'warning');
            poll();
        } catch (error) { toast(error.message, 'error'); }
    }

    async function loadRecent() {
        try {
            const data = await api('/api/jobs?size=5');
            clear(recent);
            if (!data.items.length) {
                recent.append(h('div', { class: 'empty' }, 'Todavía no hay trabajos.'));
                return;
            }
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
            recent.append(h('div', { class: 'table-wrap desktop-table' },
                h('table', {}, h('thead', {}, h('tr', {},
                    h('th', {}, 'Fecha'), h('th', {}, 'Archivo'), h('th', {}, 'Motor'),
                    h('th', {}, 'Estado'), h('th', { class: 'num' }, 'Filas'),
                )), tbody),
            ));
            const cards = h('div', { class: 'mobile-cards' });
            for (const job of data.items) {
                cards.append(h('div', { class: 'mobile-card' },
                    h('div', { class: 'mc-head' }, h('strong', {}, job.filename), statusBadge(job.status)),
                    h('div', { class: 'mc-row' }, h('span', {}, 'Motor'), h('span', {}, job.engine)),
                    h('div', { class: 'mc-row' }, h('span', {}, 'Filas'), h('span', {}, job.row_count)),
                ));
            }
            recent.append(cards);
        } catch (error) { toast(error.message, 'error'); }
    }

    updateModelVisibility();

    return { destroy() { clearTimeout(timer); } };
}
