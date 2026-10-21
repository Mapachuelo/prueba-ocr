import { api } from '../api.js';
import { h, clear, toast, modal, confirmDialog, fmtDate, helpPopover } from '../ui.js';
import { createModelPicker } from '../model_picker.js';
import { icon } from '../icons.js';

const OPENCODE_BASE = 'https://opencode.ai/inference/go/openai/v1';
const OPENCODE_MODELS = 'https://opencode.ai/inference/go/v1/models';
const LOCAL_DEFAULT = 'http://host.containers.internal:9931/v1';

export function render(container, { user }) {
    let provider = 'local';
    let selectedModel = '';
    let providersData = null;
    let savedSettings = {};

    const providerChoices = h('div', { class: 'engine-choice' });
    const localPanel = h('div', { class: 'stack' });
    const apiPanel = h('div', { class: 'stack', hidden: true });
    const localUrl = h('input', { type: 'text', placeholder: LOCAL_DEFAULT });
    const localStatus = h('div', {});
    const localTitle = h('div', { class: 'section-title', hidden: true }, 'Modelo detectado');
    const localPicker = createModelPicker({
        placeholder: 'Buscar modelo local…',
        onSelect: (model) => { selectedModel = model.id; },
        meta: (model) => [
            h('span', { class: `badge ${model.loaded ? 'loaded' : 'unloaded'}` }, model.loaded ? 'Cargado' : 'No cargado'),
            model.vision ? h('span', { class: 'badge vision' }, 'Visión') : null,
            model.context ? h('span', { class: 'badge' }, `${Math.round(model.context / 1000)}k ctx`) : null,
        ],
    });
    localPicker.root.hidden = true;
    const apiUrl = h('input', { type: 'text', placeholder: 'https://api.example.com/v1' });
    const apiModelsUrl = h('input', { type: 'text', placeholder: 'https://api.example.com/v1/models' });
    const apiKey = h('input', { type: 'password', placeholder: 'API key (se guarda cifrada)', autocomplete: 'new-password' });
    const apiPicker = createModelPicker({
        placeholder: 'Buscar modelo de API…',
        onSelect: (model) => { selectedModel = model.id; },
        meta: () => h('span', { class: 'badge' }, provider === 'opencode' ? 'OpenCode' : 'API'),
    });
    const apiStatus = h('div', { class: 'model-status' });
    const apiModelHint = h('p', { class: 'muted' },
        'Para OCR elige un modelo con visión. La prueba de conexión valida texto e imagen.');
    const testBox = h('div', {});
    const providerMessage = h('div', {});

    const localHelp = helpPopover(h('div', { class: 'help-content' },
        h('strong', {}, 'URL del servidor local'),
        h('p', {}, 'Debe ser una URL compatible con OpenAI y accesible desde el contenedor.'),
        h('code', {}, 'https://lama.cpp.mapstest.tech'),
        h('code', {}, 'https://lama.cpp.mapstest.tech/v1'),
        h('code', {}, LOCAL_DEFAULT),
        h('p', { class: 'muted' }, 'Si no escribes una ruta, la app añade /v1 automáticamente. En un contenedor, localhost apunta al propio contenedor.'),
    ));

    localPanel.append(
        h('div', { class: 'field' },
            h('span', { class: 'field-label-row' }, h('span', {}, 'URL del servidor local'), localHelp),
            localUrl,
        ),
        h('div', { class: 'btn-row' },
            h('button', { class: 'btn outline sm', type: 'button', onclick: scanLocal }, icon('refresh'), 'Escanear esta URL'),
            h('button', {
                class: 'btn outline sm', type: 'button',
                onclick: () => { localUrl.value = LOCAL_DEFAULT; scanLocal(); },
            }, 'Restaurar URL interna'),
        ),
        localStatus,
        localTitle,
        localPicker.root,
    );

    apiPanel.append(
        h('label', { class: 'field' }, 'URL de chat / API', apiUrl),
        h('label', { class: 'field' }, 'URL de modelos (opcional)', apiModelsUrl),
        h('label', { class: 'field' }, 'API key', apiKey),
        h('p', { class: 'muted' }, 'La API key se guarda cifrada en disco y nunca se devuelve completa al navegador.'),
        h('div', { class: 'btn-row' },
            h('button', { class: 'btn outline sm', type: 'button', onclick: scanApi }, icon('refresh'), 'Detectar modelos'),
        ),
        apiStatus,
        h('div', { class: 'field' }, h('span', {}, 'Modelo'), apiPicker.root),
        apiModelHint,
    );

    const profile = h('select', {});
    for (const [value, label] of [['cand', 'cand (recomendado)'], ['legacy', 'legacy']]) {
        profile.append(h('option', { value }, label));
    }
    const dpi = h('select', {});
    for (const value of [150, 200, 300, 400]) dpi.append(h('option', { value }, value));
    const workers = h('select', {});
    for (const value of [1, 2, 3, 4]) workers.append(h('option', { value }, value));

    const usersHolder = h('div', {});

    container.append(
        h('div', { class: 'card' },
            h('div', { class: 'card-head' },
                h('div', {}, h('h2', {}, 'Proveedor de IA'),
                    h('p', { class: 'muted' }, 'Configura llama.cpp, OpenCode o un proveedor externo. La API key solo se usa en servicios de pago.')),
                h('button', { class: 'btn outline sm', onclick: () => loadProviders(true) }, icon('refresh'), 'Escanear'),
            ),
            providerChoices,
            localPanel,
            apiPanel,
            h('div', { class: 'btn-row', style: 'margin-top:1rem' },
                h('button', { class: 'btn primary', onclick: saveProvider }, 'Guardar proveedor'),
                h('button', { class: 'btn outline', onclick: testProvider }, icon('scan'), 'Probar conexión'),
            ),
            providerMessage,
            testBox,
        ),
        h('div', { class: 'card' },
            h('div', { class: 'card-head' },
                h('div', {}, h('h2', {}, 'OCR por defecto'), h('p', { class: 'muted' }, 'Se aplica a los nuevos trabajos.')),
            ),
            h('div', { class: 'filters' },
                h('label', { class: 'field' }, 'Perfil', profile),
                h('label', { class: 'field' }, 'DPI', dpi),
                h('label', { class: 'field' }, 'Workers (requiere reiniciar)', workers),
                h('div', { class: 'btn-row', style: 'align-self:end' },
                    h('button', { class: 'btn success', onclick: saveOcr }, 'Guardar OCR'),
                ),
            ),
            h('div', { id: 'ocrMessage' }),
        ),
        h('div', { class: 'card' },
            h('div', { class: 'card-head' },
                h('div', {}, h('h2', {}, 'Usuarios'),
                    h('p', { class: 'muted' }, 'El admin tiene acceso total; el usuario solo a OCR. La API de pago se habilita por usuario.')),
                h('div', { class: 'btn-row' },
                    h('button', { class: 'btn outline sm', onclick: () => setAllPaid(true) }, 'Activar API de pago a todos'),
                    h('button', { class: 'btn outline sm', onclick: () => setAllPaid(false) }, 'Desactivar a todos'),
                    h('button', { class: 'btn primary sm', onclick: newUser }, icon('plus'), 'Nuevo usuario'),
                ),
            ),
            usersHolder,
        ),
    );

    function renderProviderChoices() {
        clear(providerChoices);
        for (const option of [
            { id: 'local', title: 'Local (llama.cpp)', detail: 'Detección automática, sin API key' },
            { id: 'opencode', title: 'OpenCode Go', detail: 'Suscripción Go · API key y endpoint /go' },
            { id: 'external', title: 'Externo', detail: 'OpenAI-compatible de pago, requiere API key' },
        ]) {
            providerChoices.append(h('label', { class: `choice ${provider === option.id ? 'selected' : ''}` },
                h('input', {
                    type: 'radio', name: 'provider', checked: provider === option.id,
                    onchange: () => switchProvider(option.id),
                }),
                h('span', {}, h('strong', {}, option.title), h('small', {}, option.detail)),
            ));
        }
    }

    function switchProvider(next) {
        provider = next;
        renderProviderChoices();
        if (provider === 'local') {
            localUrl.value = savedSettings.provider === 'local' ? (savedSettings.base_url || '') : '';
            selectedModel = savedSettings.provider === 'local' ? (savedSettings.model || '') : '';
            togglePanels();
            return;
        }
        const same = savedSettings.provider === provider;
        apiUrl.value = same ? (savedSettings.base_url || '') : (provider === 'opencode' ? OPENCODE_BASE : '');
        apiModelsUrl.value = same ? (savedSettings.models_url || '') : (provider === 'opencode' ? OPENCODE_MODELS : '');
        apiKey.value = '';
        apiKey.placeholder = same && savedSettings.api_key_masked
            ? savedSettings.api_key_masked
            : (provider === 'opencode' ? 'API key de OpenCode' : 'API key (se guarda cifrada)');
        selectedModel = same ? (savedSettings.model || '') : '';
        apiPicker.setModels([], selectedModel);
        togglePanels();
    }

    function togglePanels() {
        localPanel.hidden = provider !== 'local';
        apiPanel.hidden = provider === 'local';
        if (provider === 'local') {
            if (!localUrl.value) {
                localUrl.value = providersData?.local?.base_url
                    || (savedSettings.provider === 'local' ? savedSettings.base_url : '')
                    || LOCAL_DEFAULT;
            }
            renderLocal();
        } else {
            if (!apiUrl.value && provider === 'opencode') apiUrl.value = OPENCODE_BASE;
            if (!apiModelsUrl.value && provider === 'opencode') apiModelsUrl.value = OPENCODE_MODELS;
            renderApiModels();
        }
    }

    async function loadProviders(refresh = false) {
        try {
            providersData = await api(`/api/ai/providers${refresh ? '?refresh=1' : ''}`);
        } catch (error) {
            providersData = {
                local: { reachable: false, models: [], error: error.message },
                external: { models: [], error: error.message },
            };
        }
        if (provider === 'local') {
            if (!localUrl.value) {
                localUrl.value = providersData.local?.base_url
                    || (savedSettings.provider === 'local' ? savedSettings.base_url : '')
                    || LOCAL_DEFAULT;
            }
            renderLocal();
        } else {
            renderApiModels();
        }
    }

    function renderLocal() {
        clear(localStatus);
        const local = providersData?.local || {};
        if (!local.reachable) {
            localTitle.hidden = true;
            localPicker.root.hidden = true;
            localStatus.append(h('div', { class: 'alert warning' },
                h('strong', {}, 'No se detectó el servidor local. '),
                local.error || 'Revisa la URL y que llama.cpp esté levantado.',
            ));
            if (local.base_url) {
                localStatus.append(h('p', { class: 'muted' }, `Última URL detectada: ${local.base_url}`));
            }
            return;
        }
        localStatus.append(h('div', { class: 'alert info' },
            `Detectado en ${local.base_url} · ${local.models.length} modelo(s)`));
        if (!local.models.length) {
            localTitle.hidden = true;
            localPicker.root.hidden = true;
            localStatus.append(h('div', { class: 'alert warning' }, 'El servidor responde pero no hay modelos cargados.'));
            return;
        }
        localTitle.hidden = false;
        localPicker.root.hidden = false;
        if (!local.models.some((model) => model.id === selectedModel)) {
            selectedModel = local.selected || local.models[0].id;
        }
        localPicker.setModels(local.models, selectedModel);
        localStatus.append(h('p', { class: 'muted' },
            'Para OCR se necesita un modelo con visión (mmproj) y ubatch-size ≥ 2048 en llama.cpp.'));
    }

    function preferredApiModel(models) {
        return models.find((model) => /(^|[-_])(vl|vision)([-_]|$)/i.test(model.id))
            || models.find((model) => /gemini|claude|gpt/i.test(model.id))
            || models[0];
    }

    function renderApiModels() {
        const models = providersData?.external?.models || [];
        if (models.length && (!selectedModel || !models.some((model) => model.id === selectedModel))) {
            selectedModel = preferredApiModel(models).id;
        }
        apiPicker.setModels(models, selectedModel);
        if (provider === 'opencode') {
            apiStatus.textContent = 'OpenCode Go requiere un modelo con visión para OCR. Usa “Probar conexión” después de elegir el modelo.';
            apiStatus.className = 'model-status';
        }
        clear(apiModelHint);
        if (provider === 'opencode') {
            apiModelHint.append(h('span', { class: 'muted' },
                'OpenCode Go incluye modelos gratuitos y de pago. Para OCR elige uno compatible con visión y prueba la conexión.'));
        } else {
            apiModelHint.append(h('span', { class: 'muted' },
                'Para OCR elige un modelo con visión. La prueba de conexión valida texto e imagen.'));
        }
    }

    async function scanLocal() {
        clear(localStatus);
        localStatus.append(h('div', { class: 'muted' }, 'Escaneando URL…'));
        try {
            const data = await api('/api/settings/ai/models', {
                method: 'POST',
                body: { base_url: localUrl.value.trim() },
            });
            providersData = providersData || {};
            providersData.local = {
                ...(providersData.local || {}),
                base_url: data.base_url,
                reachable: data.reachable,
                models: data.models,
                error: data.error,
                selected: selectedModel,
            };
            if (data.models.length && !selectedModel) selectedModel = data.models[0].id;
            renderLocal();
        } catch (error) {
            clear(localStatus);
            localStatus.append(h('div', { class: 'alert error' }, error.message));
        }
    }

    async function scanApi() {
        clear(apiStatus);
        apiStatus.textContent = 'Detectando modelos…';
        try {
            const data = await api('/api/settings/ai/models', {
                method: 'POST',
                body: {
                    base_url: apiUrl.value.trim(),
                    models_url: apiModelsUrl.value.trim(),
                    api_key: apiKey.value.trim(),
                },
            });
            providersData = providersData || {};
            providersData.external = {
                ...(providersData.external || {}),
                configured: true,
                base_url: data.base_url,
                models_url: data.models_url,
                models: data.models,
                error: data.error,
            };
            if (data.models.length) selectedModel = preferredApiModel(data.models).id;
            renderApiModels();
            apiStatus.textContent = data.reachable
                ? `${data.models.length} modelo(s) detectado(s)`
                : (data.error || 'Sin modelos');
            apiStatus.className = `model-status ${data.reachable ? 'ok' : 'error'}`;
        } catch (error) {
            apiStatus.textContent = error.message;
            apiStatus.className = 'model-status error';
        }
    }

    async function loadSettings() {
        const data = await api('/api/settings/ai');
        savedSettings = data;
        provider = data.provider || 'local';
        selectedModel = data.model || '';
        localUrl.value = data.provider === 'local' ? (data.base_url || '') : '';
        if (provider !== 'local') {
            apiUrl.value = data.base_url || (provider === 'opencode' ? OPENCODE_BASE : '');
            apiModelsUrl.value = data.models_url || (provider === 'opencode' ? OPENCODE_MODELS : '');
            apiKey.value = '';
            apiKey.placeholder = data.api_key_masked
                || (provider === 'opencode' ? 'API key de OpenCode' : 'API key (se guarda cifrada)');
        }
        renderProviderChoices();
        await loadProviders();
        togglePanels();
    }

    async function saveProvider() {
        clear(providerMessage);
        const payload = { provider, model: selectedModel };
        if (provider === 'local') {
            payload.base_url = localUrl.value.trim();
        } else {
            payload.base_url = apiUrl.value.trim();
            payload.models_url = apiModelsUrl.value.trim();
            payload.api_key = apiKey.value.trim();
            payload.model = apiPicker.getSelected() || selectedModel;
        }
        try {
            const saved = await api('/api/settings/ai', { method: 'PUT', body: payload });
            selectedModel = saved.model || selectedModel;
            providerMessage.append(h('div', { class: 'alert success' }, 'Proveedor guardado'));
            await loadSettings();
            toast('Proveedor guardado', 'success');
        } catch (error) {
            providerMessage.append(h('div', { class: 'alert error' }, error.message));
        }
    }

    async function testProvider() {
        clear(testBox);
        testBox.append(h('div', { class: 'muted' }, 'Probando conexión y visión…'));
        try {
            const result = await api('/api/settings/ai/test', { method: 'POST' });
            clear(testBox);
            const details = [];
            if (result.text_ok) details.push('texto correcto');
            if (result.vision_ok) details.push('visión correcta');
            const status = details.length ? details.join(' · ') : 'sin respuesta de texto';
            let reason = result.error || '';
            if (!result.ok && result.text_ok && !result.vision_ok) {
                reason = 'El modelo respondió texto, pero no procesó la imagen. '
                    + 'Para OCR elige un modelo con visión, por ejemplo Claude Haiku 5.5.';
            }
            testBox.append(h('div', { class: `alert ${result.ok ? 'success' : 'error'}` },
                h('strong', {}, result.ok ? 'Conexión y visión correctas. ' : 'La prueba falló. '),
                reason || `Modelo ${result.model} · ${result.latency_ms} ms · ${status}`,
            ));
            testBox.append(h('p', { class: 'muted' },
                `Modelo probado: ${result.model || '—'} · ${result.latency_ms ?? '—'} ms · ${status}. `
                + (result.models?.length ? `${result.models.length} modelos disponibles en el selector.` : ''),
            ));
        } catch (error) {
            clear(testBox);
            testBox.append(h('div', { class: 'alert error' }, error.message));
        }
    }

    async function loadOcr() {
        const data = await api('/api/settings/ocr');
        profile.value = data.profile;
        dpi.value = String(data.dpi);
        workers.value = String(data.workers);
    }

    async function saveOcr() {
        try {
            const data = await api('/api/settings/ocr', {
                method: 'PUT',
                body: { profile: profile.value, dpi: Number(dpi.value), workers: Number(workers.value) },
            });
            const message = document.getElementById('ocrMessage');
            if (message) {
                clear(message);
                message.append(h('div', { class: 'alert success' },
                    `Guardado · perfil ${data.profile}, ${data.dpi} dpi, ${data.workers} worker(s)`));
            }
        } catch (error) { toast(error.message, 'error'); }
    }

    async function setAllPaid(enabled) {
        const ok = await confirmDialog(
            enabled
                ? '¿Activar el acceso a los modelos de pago para todos los usuarios?'
                : '¿Desactivar el acceso a los modelos de pago para todos los usuarios?',
        );
        if (!ok) return;
        try {
            const data = await api('/api/users/paid-access', {
                method: 'POST', body: { enabled },
            });
            toast(
                data.enabled
                    ? `Acceso activado para ${data.affected} usuario(s)`
                    : `Acceso desactivado para ${data.affected} usuario(s)`,
                'success',
            );
            await loadUsers();
        } catch (error) { toast(error.message, 'error'); }
    }

    async function loadUsers() {
        const data = await api('/api/users');
        clear(usersHolder);
        const activeAdmins = data.items.filter((item) => item.role === 'admin' && item.active).length;
        for (const item of data.items) {
            const isSelf = item.username === user.username;
            const previousRole = item.role;
            const role = h('select', { disabled: isSelf, title: isSelf ? 'No puedes cambiar el rol de tu propia cuenta' : '' });
            for (const [value, label] of [['admin', 'Administrador'], ['usuario', 'Usuario']]) {
                role.append(h('option', { value, selected: value === item.role }, label));
            }
            role.addEventListener('change', async () => {
                const nextRole = role.value;
                if (nextRole === previousRole) return;
                const oldLabel = previousRole === 'admin' ? 'Administrador' : 'Usuario';
                const newLabel = nextRole === 'admin' ? 'Administrador' : 'Usuario';
                const ok = await confirmDialog(
                    `¿Cambiar el rol de “${item.username}” de ${oldLabel} a ${newLabel}?`,
                );
                if (!ok) { role.value = previousRole; return; }
                role.disabled = true;
                try {
                    await api(`/api/users/${item.id}`, { method: 'PATCH', body: { role: nextRole } });
                    toast('Rol actualizado', 'success');
                    await loadUsers();
                } catch (error) {
                    role.value = previousRole;
                    toast(error.message, 'error');
                } finally { role.disabled = false; }
            });

            const active = h('input', {
                type: 'checkbox', checked: item.active, disabled: isSelf,
                title: isSelf ? 'No puedes desactivar tu propia cuenta' : '',
            });
            active.addEventListener('change', async () => {
                if (item.active && active.checked === false) {
                    const ok = await confirmDialog(
                        `¿Desactivar a “${item.username}”? No podrá iniciar sesión hasta que lo reactives.`,
                    );
                    if (!ok) { active.checked = true; return; }
                }
                active.disabled = true;
                try {
                    await api(`/api/users/${item.id}`, { method: 'PATCH', body: { active: active.checked } });
                    toast(active.checked ? 'Usuario activado' : 'Usuario desactivado', 'success');
                    await loadUsers();
                } catch (error) {
                    active.checked = item.active;
                    toast(error.message, 'error');
                } finally { active.disabled = false; }
            });

            let paidControl;
            if (isSelf) {
                paidControl = h('span', { class: 'badge loaded' }, 'Siempre');
            } else {
                const paid = h('input', {
                    type: 'checkbox', checked: Boolean(item.paid_ai),
                });
                paid.addEventListener('change', async () => {
                    if (!paid.checked) {
                        const ok = await confirmDialog(
                            `¿Quitar el acceso a modelos de pago a “${item.username}”?`,
                        );
                        if (!ok) { paid.checked = true; return; }
                    }
                    paid.disabled = true;
                    try {
                        await api(`/api/users/${item.id}`, { method: 'PATCH', body: { paid_ai: paid.checked } });
                        toast(paid.checked ? 'Acceso a API de pago activado' : 'Acceso a API de pago desactivado', 'success');
                        await loadUsers();
                    } catch (error) {
                        paid.checked = Boolean(item.paid_ai);
                        toast(error.message, 'error');
                    } finally { paid.disabled = false; }
                });
                paidControl = h('label', { class: 'active-toggle paid-toggle' }, paid, 'API de pago');
            }

            const actions = h('div', { class: 'btn-row' });
            if (!isSelf) {
                actions.append(
                    h('button', { class: 'btn outline sm', onclick: () => resetPassword(item) }, 'Reset clave'),
                    h('button', {
                        class: 'btn danger sm',
                        onclick: async () => {
                            if (!(await confirmDialog(`¿Eliminar el usuario ${item.username}?`))) return;
                            try {
                                await api(`/api/users/${item.id}`, { method: 'DELETE' });
                                toast('Usuario eliminado', 'success');
                                loadUsers();
                            } catch (error) { toast(error.message, 'error'); }
                        },
                    }, 'Borrar'),
                );
            } else {
                actions.append(h('span', { class: 'muted' }, 'Tu cuenta'));
            }
            usersHolder.append(h('div', { class: 'user-row' },
                h('div', { class: 'grow' },
                    h('strong', {}, item.username),
                    h('div', { class: 'muted' },
                        `Creado ${item.created_at ? fmtDate(item.created_at) : '—'}`,
                        item.role === 'admin' && item.active && activeAdmins === 1
                            ? ' · Último administrador activo' : '')),
                h('div', { class: 'role-select' }, role),
                h('label', { class: 'active-toggle' }, active, 'Activo'),
                paidControl,
                actions,
            ));
        }
    }

    function newUser() {
        const username = h('input', { type: 'text', placeholder: 'usuario' });
        const password = h('input', { type: 'password', placeholder: 'mínimo 4 caracteres' });
        const role = h('select', {});
        role.append(h('option', { value: 'usuario' }, 'usuario'), h('option', { value: 'admin' }, 'admin'));
        const message = h('div', {});
        modal('Nuevo usuario', h('div', { class: 'stack' },
            h('label', { class: 'field' }, 'Usuario', username),
            h('label', { class: 'field' }, 'Contraseña', password),
            h('label', { class: 'field' }, 'Rol', role),
            message,
        ), [{
            label: 'Crear', class: 'primary',
            onClick: async (close) => {
                try {
                    await api('/api/users', {
                        method: 'POST',
                        body: { username: username.value, password: password.value, role: role.value },
                    });
                    toast('Usuario creado', 'success');
                    close();
                    loadUsers();
                } catch (error) {
                    clear(message);
                    message.append(h('div', { class: 'alert error' }, error.message));
                }
            },
        }]);
    }

    function resetPassword(item) {
        const password = h('input', { type: 'password', placeholder: 'mínimo 4 caracteres' });
        const message = h('div', {});
        modal(`Reset de contraseña · ${item.username}`, h('div', { class: 'stack' },
            h('label', { class: 'field' }, 'Nueva contraseña', password), message,
        ), [{
            label: 'Guardar', class: 'primary',
            onClick: async (close) => {
                try {
                    await api(`/api/users/${item.id}`, { method: 'PATCH', body: { password: password.value } });
                    toast('Contraseña restablecida', 'success');
                    close();
                } catch (error) {
                    clear(message);
                    message.append(h('div', { class: 'alert error' }, error.message));
                }
            },
        }]);
    }

    (async () => {
        try {
            await loadSettings();
            await loadOcr();
            await loadUsers();
        } catch (error) {
            toast(error.message, 'error');
        }
    })();

    return {
        destroy() {
            localPicker.destroy();
            apiPicker.destroy();
        },
    };
}
