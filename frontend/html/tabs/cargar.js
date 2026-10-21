import { api } from '../api.js';
import {
    h, clear, toast, statusBadge, fmtDateTime, confirmDialog, modal, actionMenu, emptyState,
    notifyDataChanged, watchDataChanges,
} from '../ui.js';
import { icon } from '../icons.js';
import { createModelPicker } from '../model_picker.js';

const BASE_ENGINES = [
    { id: 'local', title: 'Local', detail: 'Tesseract + OpenCV, sin IA', icon: 'cpu' },
    { id: 'ai', title: 'IA local', detail: 'Modelo de visión en llama.cpp', icon: 'scan' },
    { id: 'compare', title: 'Comparar', detail: 'Ejecuta local e IA y contrasta', icon: 'compare' },
];

export function render(container, { user, navigate }) {
    let file = null;
    let engine = 'local';
    let selectedModel = '';
    let providers = null;
    let displayFormat = 'pdf';
    let jobId = null;
    let timer = null;

    const fileInput = h('input', {
        type: 'file', accept: '.pdf,.xlsx,.xls', hidden: true,
        onchange: () => { if (fileInput.files.length) setFile(fileInput.files[0]); },
    });
    const fileName = h('div', { class: 'file-name' }, 'Ningún archivo seleccionado');
    const displayName = h('input', { type: 'text', placeholder: 'Nombre sin extensión', maxlength: '115' });
    const formatBox = h('div', { class: 'format-choice' });
    const displayNameWrap = h('div', { class: 'field', hidden: true },
        h('span', { class: 'field-label-row' },
            h('span', {}, 'Nombre para el análisis'),
            h('button', {
                class: 'link-btn', type: 'button',
                onclick: () => { if (file) { displayName.value = baseName(file.name); updateSummary(); } },
            }, 'Restablecer nombre'),
        ),
        displayName,
        h('span', { class: 'field-label-row' }, h('span', { class: 'muted' }, 'Guardar como')),
        formatBox,
    );
    displayName.addEventListener('input', updateSummary);
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
    const accessHint = h('div', { class: 'alert warning', hidden: true });
    const modelPicker = createModelPicker({
        placeholder: 'Buscar modelo para OCR…',
        onSelect: (model) => { selectedModel = model.id; },
        meta: (model) => {
            const active = providers?.active_provider || 'local';
            if (['external', 'opencode'].includes(active)) {
                return h('span', { class: 'badge' }, providerTitle());
            }
            return [
                h('span', { class: `badge ${model.loaded ? 'loaded' : 'unloaded'}` }, model.loaded ? 'Cargado' : 'No cargado'),
                model.vision ? h('span', { class: 'badge vision' }, 'Visión') : null,
                model.context ? h('span', { class: 'badge' }, `${Math.round(model.context / 1000)}k ctx`) : null,
            ];
        },
    });
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
    const nonPdfHint = h('div', { class: 'alert info', hidden: true },
        'Las opciones de perfil OCR, DPI y páginas solo aplican a archivos PDF.');
    const submit = h('button', { class: 'btn primary', type: 'submit', disabled: true }, icon('upload'), 'Procesar archivo');
    const actionSummary = h('div', { class: 'wizard-summary' });
    const form = h('form', { onsubmit: (event) => { event.preventDefault(); startJob(); } }, submit);
    const wizardActions = h('div', { class: 'wizard-actions' }, actionSummary, form);

    const stepFile = h('section', { class: 'step-card' },
        h('div', { class: 'step-head' }, h('span', { class: 'step-num' }, '1'), h('h2', {}, 'Archivo')),
        dropzone, fileInput, displayNameWrap,
    );
    const stepEngine = h('section', { class: 'step-card' },
        h('div', { class: 'step-head' }, h('span', { class: 'step-num' }, '2'), h('h2', {}, 'Motor OCR')),
        engineBox, accessHint, modelBox,
    );
    const stepOptions = h('section', { class: 'step-card' },
        h('div', { class: 'step-head' }, h('span', { class: 'step-num' }, '3'), h('h2', {}, 'Opciones')),
        pdfOptions, nonPdfHint,
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
    const documentsBox = h('div', {});

    container.append(
        h('div', { class: 'steps' }, stepFile, stepEngine, stepOptions),
        wizardActions,
        progressCard,
        h('div', { class: 'card' },
            h('div', { class: 'card-head' },
                h('div', {},
                    h('h2', {}, 'Documentos cargados'),
                    h('p', { class: 'muted' }, 'Los archivos originales se conservan aunque borres un trabajo OCR.')),
                h('button', { class: 'btn outline sm', type: 'button', onclick: loadDocuments }, icon('refresh'), 'Actualizar'),
            ),
            documentsBox,
        ),
        h('div', { class: 'card' },
            h('div', { class: 'card-head' }, h('div', {}, h('h2', {}, 'Últimos trabajos'))),
            recent,
        ),
    );

    renderEngineChoices();
    loadProviders();
    loadRecent();
    loadDocuments();
    updateSummary();

    function paidBlocked() {
        return Boolean(providers?.paid_provider && providers?.paid_access === false);
    }

    function providerTitle() {
        const active = providers?.active_provider || 'local';
        if (active === 'opencode') return 'OpenCode Go';
        if (active === 'external') return 'API externa';
        return 'IA local';
    }

    function engineOptions() {
        const active = providers?.active_provider || 'local';
        const blocked = paidBlocked();
        const ai = active === 'local'
            ? { title: 'IA local', detail: 'Modelo de visión en llama.cpp' }
            : { title: `IA de pago · ${providerTitle()}`, detail: 'Modelo de visión mediante API' };
        return BASE_ENGINES.map((option) => {
            if (option.id === 'ai') return { ...option, ...ai, disabled: blocked };
            if (option.id === 'compare') {
                return {
                    ...option,
                    detail: blocked ? 'Requiere acceso a modelos de pago' : 'Ejecuta local e IA y contrasta',
                    disabled: blocked,
                };
            }
            return option;
        });
    }

    function renderEngineChoices() {
        clear(engineBox);
        const options = engineOptions();
        if (paidBlocked() && engine !== 'local') {
            engine = 'local';
        }
        accessHint.hidden = !paidBlocked();
        if (paidBlocked()) {
            clear(accessHint);
            accessHint.append('El administrador no ha habilitado tu acceso a los modelos de pago. Puedes usar OCR local.');
        }
        for (const option of options) {
            const choice = h('label', { class: `choice ${engine === option.id ? 'selected' : ''} ${option.disabled ? 'disabled' : ''}` },
                h('input', {
                    type: 'radio', name: 'engine', value: option.id, checked: engine === option.id,
                    disabled: Boolean(option.disabled),
                    onchange: () => { engine = option.id; renderEngineChoices(); updateModelVisibility(); updateSummary(); },
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

    function baseName(name) {
        return String(name || '').replace(/\.[^.]+$/, '');
    }

    function fileFormat() {
        const ext = String(file?.name || '').split('.').pop().toLowerCase();
        return ext === 'pdf' ? 'pdf' : (ext === 'xls' ? 'xls' : 'xlsx');
    }

    function renderFormatChoices() {
        clear(formatBox);
        const original = fileFormat();
        const options = [
            { id: 'pdf', label: 'PDF' },
            { id: 'xlsx', label: 'XLSX' },
            { id: 'xls', label: 'XLS' },
        ];
        for (const option of options) {
            const compatible = original === 'pdf' ? option.id === 'pdf' : option.id !== 'pdf';
            formatBox.append(h('button', {
                type: 'button',
                class: `format-choice-btn${displayFormat === option.id ? ' selected' : ''}`,
                disabled: !compatible,
                title: compatible ? `Guardar como .${option.id}` : `No compatible con ${original.toUpperCase()}`,
                onclick: () => { displayFormat = option.id; renderFormatChoices(); updateSummary(); },
            }, option.label));
        }
    }

    function finalDisplayName() {
        const base = displayName.value.trim().replace(new RegExp(`\\.${displayFormat}$`, 'i'), '');
        return `${base}.${displayFormat}`;
    }

    function updateSummary() {
        const option = engineOptions().find((item) => item.id === engine) || engineOptions()[0];
        clear(actionSummary);
        const name = file ? (displayName.value.trim() ? finalDisplayName() : file.name) : 'Ningún archivo seleccionado';
        actionSummary.append(
            h('strong', {}, name),
            h('span', { class: 'muted' }, file
                ? `${formatSize(file.size)} · ${option.title}`
                : 'Elige un PDF o Excel y el motor de OCR'),
        );
        submit.disabled = !file;
    }

    function formatSize(bytes) {
        if (!bytes) return '0 KB';
        if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }

    function setFile(selected) {
        file = selected;
        fileName.textContent = `${selected.name} · ${formatSize(selected.size)}`;
        displayName.value = baseName(selected.name);
        displayFormat = fileFormat();
        renderFormatChoices();
        displayNameWrap.hidden = false;
        pdfOptions.hidden = !selected.name.toLowerCase().endsWith('.pdf');
        nonPdfHint.hidden = !pdfOptions.hidden;
        if (pdfOptions.hidden) { engine = 'local'; renderEngineChoices(); updateModelVisibility(); }
        updateSummary();
    }

    async function loadProviders(refresh = false) {
        try {
            providers = await api(`/api/ai/providers${refresh ? '?refresh=1' : ''}`);
            renderEngineChoices();
            updateModelVisibility();
        } catch (error) {
            providers = {
                local: { reachable: false, models: [], error: error.message },
                external: { models: [] },
                active_provider: 'local',
                paid_provider: false,
                paid_access: true,
            };
            renderEngineChoices();
            updateModelVisibility();
        }
    }

    function renderModels() {
        if (engine === 'local') { modelBox.innerHTML = ''; return; }
        clear(modelBox);
        if (paidBlocked()) return;
        const active = providers?.active_provider || 'local';
        const apiActive = ['external', 'opencode'].includes(active) && providers?.external?.configured;
        const source = apiActive ? providers.external : (providers?.local || {});
        const models = source.models || [];
        if (!models.length) {
            modelBox.append(
                h('div', { class: 'alert warning' },
                    h('strong', {}, apiActive ? `No hay modelos en ${providerTitle()}. ` : 'No se detectó un modelo local. '),
                    source.error || (apiActive ? 'Configúralo en Configuración.' : 'Revisa que llama.cpp esté levantado.'),
                ),
                h('div', { class: 'btn-row' },
                    h('button', { class: 'btn outline sm', type: 'button', onclick: () => loadProviders(true) }, icon('refresh'), 'Escanear de nuevo'),
                ),
                apiActive ? null : h('p', { class: 'muted' }, 'Servidor esperado: ' + (source.default_url || 'http://host.containers.internal:9931/v1')),
            );
            return;
        }
        const configured = apiActive ? providers?.external?.selected : providers?.local?.selected;
        const preferred = models.find((model) => model.id === selectedModel)
            || models.find((model) => model.id === configured)
            || models.find((model) => model.loaded && model.vision)
            || models.find((model) => model.loaded)
            || models[0];
        selectedModel = preferred.id;
        modelPicker.setModels(models, selectedModel);
        selectedModel = modelPicker.getSelected();
        modelBox.append(
            h('div', { class: 'section-title' }, apiActive ? `Modelos · ${providerTitle()}` : 'Modelo detectado'),
            modelPicker.root,
        );
        if (apiActive) {
            modelBox.append(h('p', { class: 'muted' }, 'Elige un modelo con visión. Si no la admite, “Probar conexión” fallará en Configuración.'));
        }
        modelBox.append(h('div', { class: 'btn-row' },
            h('button', { class: 'btn outline sm', type: 'button', onclick: () => loadProviders(true) }, icon('refresh'), 'Escanear de nuevo'),
            h('span', { class: 'model-status ok' }, `${apiActive ? 'Proveedor' : 'Servidor'}: ${source.base_url || ''}`),
        ));
    }

    function beginJob(id) {
        jobId = id;
        progressCard.hidden = false;
        resultsBtn.hidden = true;
        compareBtn.hidden = true;
        cancelBtn.hidden = false;
        progressBar.classList.remove('success', 'error');
        progressBar.firstChild.style.width = '0%';
        clear(logBox);
        progressCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
        notifyDataChanged();
        loadDocuments();
        poll();
    }

    async function startJob() {
        if (!file) { toast('Selecciona un archivo primero', 'warning'); return; }
        if (!displayName.value.trim()) {
            toast('Escribe un nombre para el documento', 'warning');
            return;
        }
        if (engine !== 'local' && paidBlocked()) {
            toast('El administrador no ha habilitado tu acceso a modelos de pago', 'warning');
            return;
        }
        if (engine !== 'local' && !selectedModel) {
            toast('Selecciona un modelo de IA disponible', 'warning');
            return;
        }
        submit.disabled = true;
        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('engine', engine);
            formData.append('display_name', finalDisplayName());
            if (!pdfOptions.hidden) {
                if (profile.value) formData.append('profile', profile.value);
                if (dpi.value) formData.append('dpi', dpi.value);
                if (pages.value.trim()) formData.append('pages', pages.value.trim());
            }
            if (engine !== 'local' && selectedModel) formData.append('model', selectedModel);
            const data = await api('/api/jobs', { method: 'POST', form: formData });
            beginJob(data.id);
        } catch (error) {
            toast(error.message, 'error');
        } finally {
            submit.disabled = !file;
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
                job.ai_used
                    ? h('span', { class: 'badge vision' }, 'IA usada')
                    : (job.engine === 'ai' ? h('span', { class: 'badge-status warning' }, 'Fallback local') : null),
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
            else { loadRecent(); loadDocuments(); }
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

    function recentEngine(job) {
        return h('span', {},
            job.engine,
            job.engine === 'ai' && !job.ai_used
                ? h('span', { class: 'badge-status warning', style: 'margin-left:0.35rem' }, 'Fallback local')
                : null,
        );
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
                    h('td', {}, recentEngine(job)),
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
                    h('div', { class: 'mc-row' }, h('span', {}, 'Motor'), h('span', {}, recentEngine(job))),
                    h('div', { class: 'mc-row' }, h('span', {}, 'Filas'), h('span', {}, job.row_count)),
                ));
            }
            recent.append(cards);
        } catch (error) { toast(error.message, 'error'); }
    }

    function documentMenu(document) {
        return actionMenu([
            { label: 'Renombrar', onClick: () => renameDocument(document) },
            { label: 'Borrar documento', danger: true, onClick: () => deleteDocument(document) },
        ]);
    }

    function renameDocument(document) {
        const base = document.filename.replace(/\.[^.]+$/, '');
        const originalExt = String(document.filename).split('.').pop().toLowerCase();
        let format = document.kind === 'pdf' ? 'pdf' : (originalExt === 'xls' ? 'xls' : 'xlsx');
        const name = h('input', { type: 'text', value: base, maxlength: '115', placeholder: 'Nombre sin extensión' });
        const formatBox = h('div', { class: 'format-choice' });
        const message = h('div', {});
        const renderFormats = () => {
            clear(formatBox);
            for (const option of [
                { id: 'pdf', label: 'PDF' },
                { id: 'xlsx', label: 'XLSX' },
                { id: 'xls', label: 'XLS' },
            ]) {
                const compatible = document.kind === 'pdf' ? option.id === 'pdf' : option.id !== 'pdf';
                formatBox.append(h('button', {
                    type: 'button',
                    class: `format-choice-btn${format === option.id ? ' selected' : ''}`,
                    disabled: !compatible,
                    onclick: () => { format = option.id; renderFormats(); },
                }, option.label));
            }
        };
        renderFormats();
        modal(`Renombrar · ${document.filename}`, h('div', { class: 'stack' },
            h('p', { class: 'muted' }, 'El nombre se actualizará en Cargar, Historial, Datos e Inicio.'),
            h('label', { class: 'field' }, 'Nombre', name),
            h('span', { class: 'field-label-row' }, h('span', { class: 'muted' }, 'Extensión')),
            formatBox,
            message,
        ), [{
            label: 'Guardar', class: 'primary',
            onClick: async (close) => {
                clear(message);
                if (!name.value.trim()) {
                    message.append(h('div', { class: 'alert error' }, 'Escribe un nombre'));
                    return;
                }
                try {
                    await api(`/api/documents/${document.id}`, {
                        method: 'PATCH',
                        body: { filename: `${name.value.trim()}.${format}` },
                    });
                    toast('Documento renombrado', 'success');
                    close();
                    notifyDataChanged();
                    await Promise.all([loadDocuments(), loadRecent()]);
                } catch (error) {
                    message.append(h('div', { class: 'alert error' }, error.message));
                }
            },
        }]);
    }

    async function loadDocuments() {
        try {
            const data = await api('/api/documents?limit=30');
            clear(documentsBox);
            if (!data.items.length) {
                documentsBox.append(emptyState(
                    'Sin documentos',
                    'Sube un PDF o Excel para conservarlo aquí y reprocesarlo cuando quieras.',
                ));
                return;
            }
            const showUser = user?.role === 'admin';
            const tbody = h('tbody', {});
            for (const document of data.items) {
                const last = document.last_job;
                tbody.append(h('tr', {},
                    h('td', {}, fmtDateTime(document.created_at)),
                    h('td', {}, h('strong', {}, document.filename),
                        h('div', { class: 'muted' }, document.kind === 'pdf' ? 'PDF' : 'Excel'),
                        document.original_filename && document.original_filename !== document.filename
                            ? h('div', { class: 'muted' }, `Original: ${document.original_filename}`)
                            : null),
                    h('td', { class: 'num' }, formatSize(document.size)),
                    h('td', { class: 'num' }, document.job_count),
                    showUser ? h('td', {}, document.user || '—') : '',
                    h('td', {}, last ? statusBadge(last.status) : h('em', {}, 'Sin trabajos')),
                    h('td', {}, h('div', { class: 'table-actions' },
                        h('button', { class: 'btn outline sm', onclick: () => reprocessDocument(document) }, 'Procesar'),
                        documentMenu(document),
                    )),
                ));
            }
            documentsBox.append(h('div', { class: 'table-wrap desktop-table' },
                h('table', {},
                    h('thead', {}, h('tr', {},
                        h('th', {}, 'Fecha'), h('th', {}, 'Documento'), h('th', { class: 'num' }, 'Tamaño'),
                        h('th', { class: 'num' }, 'Trabajos'), showUser ? h('th', {}, 'Usuario') : '',
                        h('th', {}, 'Último estado'), h('th', {}, 'Acciones'),
                    )),
                    tbody,
                ),
            ));
            const cards = h('div', { class: 'mobile-cards' });
            for (const document of data.items) {
                const last = document.last_job;
                cards.append(h('div', { class: 'mobile-card' },
                    h('div', { class: 'mc-head' },
                        h('strong', {}, document.filename),
                        last ? statusBadge(last.status) : h('em', {}, 'Sin trabajos'),
                    ),
                    h('div', { class: 'mc-row' }, h('span', {}, 'Fecha'), h('span', {}, fmtDateTime(document.created_at))),
                    h('div', { class: 'mc-row' }, h('span', {}, 'Tamaño'), h('span', {}, formatSize(document.size))),
                    h('div', { class: 'mc-row' }, h('span', {}, 'Trabajos'), h('span', {}, document.job_count)),
                    user?.role === 'admin' ? h('div', { class: 'mc-row' }, h('span', {}, 'Usuario'), h('span', {}, document.user || '—')) : '',
                    h('div', { class: 'btn-row', style: 'margin-top:0.7rem' },
                        h('button', { class: 'btn outline sm', onclick: () => reprocessDocument(document) }, 'Procesar'),
                        documentMenu(document),
                    ),
                ));
            }
            documentsBox.append(cards);
        } catch (error) {
            clear(documentsBox);
            documentsBox.append(h('div', { class: 'alert error' }, error.message));
        }
    }

    function reprocessDocument(document) {
        const blocked = paidBlocked();
        const engineSelect = h('select', {},
            h('option', { value: 'local' }, 'Local · Tesseract + OpenCV'),
            h('option', { value: 'ai', disabled: blocked }, `${providerTitle()} · modelo de visión`),
            h('option', { value: 'compare', disabled: blocked }, 'Comparar local e IA'),
        );
        if (blocked) {
            engineSelect.title = 'El administrador no ha habilitado tu acceso a modelos de pago';
        }
        const message = h('div', {});
        modal(`Procesar de nuevo · ${document.filename}`, h('div', { class: 'stack' },
            h('p', { class: 'muted' }, 'Se reutiliza el archivo original; no hace falta volver a subirlo.'),
            h('label', { class: 'field' }, 'Motor OCR', engineSelect),
            message,
        ), [{
            label: 'Procesar', class: 'primary',
            onClick: async (close) => {
                try {
                    if (engineSelect.value !== 'local' && paidBlocked()) {
                        throw new Error('El administrador no ha habilitado tu acceso a modelos de pago');
                    }
                    const data = await api(`/api/documents/${document.id}/jobs`, {
                        method: 'POST',
                        body: {
                            engine: engineSelect.value,
                            model: engineSelect.value === 'local' ? '' : selectedModel,
                        },
                    });
                    close();
                    beginJob(data.id);
                    toast('Trabajo creado desde el documento', 'success');
                    loadRecent();
                    loadDocuments();
                } catch (error) {
                    clear(message);
                    message.append(h('div', { class: 'alert error' }, error.message));
                }
            },
        }]);
    }

    async function deleteDocument(document) {
        if (!(await confirmDialog(
            `¿Eliminar el documento “${document.filename}” y todos sus trabajos? Esta acción borra el archivo original.`,
        ))) return;
        try {
            await api(`/api/documents/${document.id}`, { method: 'DELETE' });
            toast('Documento eliminado', 'success');
            notifyDataChanged();
            await Promise.all([loadDocuments(), loadRecent()]);
        } catch (error) { toast(error.message, 'error'); }
    }

    const stopWatch = watchDataChanges(() => {
        loadRecent();
        loadDocuments();
    });
    updateModelVisibility();

    return { destroy() { clearTimeout(timer); modelPicker.destroy(); stopWatch(); } };
}
