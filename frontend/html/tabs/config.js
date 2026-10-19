import { api } from '../api.js';
import { h, clear, toast, modal, confirmDialog, fmtDate } from '../ui.js';
import { icon } from '../icons.js';

export function render(container, { user }) {
    let provider = 'local';
    let selectedModel = '';
    let providersData = null;

    const providerChoices = h('div', { class: 'engine-choice' });
    const localPanel = h('div', { class: 'stack' });
    const externalPanel = h('div', { class: 'stack', hidden: true });
    const externalUrl = h('input', { type: 'text', placeholder: 'https://api.example.com/v1' });
    const externalKey = h('input', { type: 'password', placeholder: 'API key (se guarda cifrada)', autocomplete: 'new-password' });
    const externalModel = h('select', {});
    const externalStatus = h('div', { class: 'model-status' });
    const testBox = h('div', {});
    const providerMessage = h('div', {});

    externalPanel.append(
        h('label', { class: 'field' }, 'URL base', externalUrl),
        h('label', { class: 'field' }, 'API key', externalKey),
        h('div', { class: 'btn-row' },
            h('button', {
                class: 'btn outline sm', type: 'button',
                onclick: async () => {
                    clear(externalStatus);
                    externalStatus.textContent = 'Detectando modelos…';
                    try {
                        const data = await api('/api/settings/ai/models', {
                            method: 'POST',
                            body: { base_url: externalUrl.value.trim(), api_key: externalKey.value.trim() },
                        });
                        clear(externalModel);
                        if (!data.reachable || !data.models.length) {
                            externalModel.append(h('option', { value: '' }, 'Sin modelos detectados'));
                            externalStatus.textContent = data.error || 'Sin modelos';
                            externalStatus.className = 'model-status error';
                            return;
                        }
                        for (const model of data.models) {
                            externalModel.append(h('option', { value: model.id }, model.id));
                        }
                        selectedModel = data.models[0].id;
                        externalModel.value = selectedModel;
                        externalStatus.textContent = `${data.models.length} modelo(s) detectado(s)`;
                        externalStatus.className = 'model-status ok';
                    } catch (error) {
                        externalStatus.textContent = error.message;
                        externalStatus.className = 'model-status error';
                    }
                },
            }, icon('refresh'), 'Detectar modelos'),
        ),
        externalStatus,
        h('label', { class: 'field' }, 'Modelo', externalModel),
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
                    h('p', { class: 'muted' }, 'Los modelos locales se detectan automáticamente. La API key solo se usa en proveedores externos de pago.')),
                h('button', { class: 'btn outline sm', onclick: () => loadProviders(true) }, icon('refresh'), 'Escanear'),
            ),
            providerChoices,
            localPanel,
            externalPanel,
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
                h('div', {}, h('h2', {}, 'Usuarios'), h('p', { class: 'muted' }, 'El admin tiene acceso total; el usuario solo a OCR.')),
                h('button', { class: 'btn primary sm', onclick: newUser }, icon('plus'), 'Nuevo usuario'),
            ),
            usersHolder,
        ),
    );

    function renderProviderChoices() {
        clear(providerChoices);
        for (const option of [
            { id: 'local', title: 'Local (llama.cpp)', detail: 'Detección automática, sin API key' },
            { id: 'external', title: 'Externo', detail: 'OpenAI-compatible de pago, requiere API key' },
        ]) {
            providerChoices.append(h('label', { class: `choice ${provider === option.id ? 'selected' : ''}` },
                h('input', {
                    type: 'radio', name: 'provider', checked: provider === option.id,
                    onchange: () => { provider = option.id; renderProviderChoices(); togglePanels(); },
                }),
                h('span', {}, h('strong', {}, option.title), h('small', {}, option.detail)),
            ));
        }
    }

    function togglePanels() {
        localPanel.hidden = provider !== 'local';
        externalPanel.hidden = provider !== 'external';
        if (provider === 'local') {
            selectedModel = providersData?.local?.selected || '';
            renderLocal();
        } else {
            selectedModel = providersData?.external?.selected || '';
            toggleExternalModels();
        }
    }

    async function loadProviders(refresh = false) {
        try {
            providersData = await api(`/api/ai/providers${refresh ? '?refresh=1' : ''}`);
            renderLocal();
        } catch (error) {
            providersData = { local: { reachable: false, models: [], error: error.message } };
            renderLocal();
        }
    }

    function renderLocal() {
        clear(localPanel);
        const local = providersData?.local || {};
        if (!local.reachable) {
            localPanel.append(h('div', { class: 'alert warning' },
                h('strong', {}, 'No se detectó llama.cpp. '),
                local.error || 'Revisa que el servidor esté levantado.',
            ));
            localPanel.append(h('p', { class: 'muted' },
                `URL esperada: ${local.default_url || 'http://host.containers.internal:9931/v1'}. ` +
                'Si usas contenedores, evita “localhost”: apunta al contenedor, no al host.'));
            return;
        }
        localPanel.append(h('div', { class: 'alert info' },
            `Detectado en ${local.base_url} · ${local.models.length} modelo(s)`));
        if (!local.models.length) {
            localPanel.append(h('div', { class: 'alert warning' }, 'El servidor responde pero no hay modelos cargados.'));
            return;
        }
        if (!selectedModel && local.selected) selectedModel = local.selected;
        const box = h('div', { class: 'stack tight' });
        for (const model of local.models) {
            box.append(h('label', { class: `choice ${selectedModel === model.id ? 'selected' : ''}` },
                h('input', {
                    type: 'radio', name: 'local-model', checked: selectedModel === model.id,
                    onchange: () => { selectedModel = model.id; renderLocal(); },
                }),
                h('span', { style: 'flex:1;min-width:0' },
                    h('strong', {}, model.id),
                    h('span', { class: 'btn-row', style: 'margin-top:0.25rem;gap:0.3rem' },
                        h('span', { class: `badge ${model.loaded ? 'loaded' : 'unloaded'}` }, model.loaded ? 'Cargado' : 'No cargado'),
                        model.vision ? h('span', { class: 'badge vision' }, 'Visión') : null,
                        model.context ? h('span', { class: 'badge' }, `${Math.round(model.context / 1000)}k ctx`) : null,
                    ),
                ),
            ));
        }
        localPanel.append(box);
        localPanel.append(h('p', { class: 'muted' },
            'Para OCR se necesita un modelo con visión (mmproj) y ubatch-size ≥ 2048 en llama.cpp.'));
    }

    function toggleExternalModels() {
        clear(externalModel);
        const models = providersData?.external?.models || [];
        if (!models.length) {
            externalModel.append(h('option', { value: '' }, 'Detecta modelos con la URL/API key'));
            return;
        }
        for (const model of models) {
            externalModel.append(h('option', { value: model.id, selected: model.id === selectedModel }, model.id));
        }
        if (!selectedModel) {
            selectedModel = models[0].id;
            externalModel.value = selectedModel;
        }
    }

    async function loadSettings() {
        const data = await api('/api/settings/ai');
        provider = data.provider || 'local';
        selectedModel = data.model || '';
        externalUrl.value = data.provider === 'external' ? (data.base_url || '') : '';
        externalKey.value = '';
        externalKey.placeholder = data.api_key_masked || 'API key (se guarda cifrada)';
        renderProviderChoices();
        await loadProviders();
        togglePanels();
        toggleExternalModels();
    }

    async function saveProvider() {
        clear(providerMessage);
        const payload = { provider, model: selectedModel };
        if (provider === 'external') {
            payload.base_url = externalUrl.value.trim();
            payload.api_key = externalKey.value.trim();
            payload.model = externalModel.value || selectedModel;
        }
        try {
            const saved = await api('/api/settings/ai', { method: 'PUT', body: payload });
            selectedModel = saved.model || selectedModel;
            providerMessage.append(h('div', { class: 'alert success' }, 'Proveedor guardado'));
            await loadSettings();
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
            testBox.append(h('div', { class: `alert ${result.ok ? 'success' : 'error'}` },
                h('strong', {}, result.ok ? 'Conexión y visión correctas. ' : 'La prueba falló. '),
                result.error || `Modelo ${result.model} · ${result.latency_ms} ms`,
            ));
            if (result.models?.length) {
                testBox.append(h('p', { class: 'muted' },
                    'Modelos: ' + result.models.map((m) => m.id + (m.loaded ? ' (cargado)' : '')).join(', ')));
            }
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

    async function loadUsers() {
        const data = await api('/api/users');
        clear(usersHolder);
        for (const item of data.items) {
            const role = h('select', {
                onchange: () => api(`/api/users/${item.id}`, { method: 'PATCH', body: { role: role.value } })
                    .then(() => toast('Rol actualizado', 'success'))
                    .catch((error) => toast(error.message, 'error')),
            });
            for (const value of ['admin', 'usuario']) {
                role.append(h('option', { value, selected: value === item.role }, value));
            }
            const active = h('input', {
                type: 'checkbox', checked: item.active,
                onchange: () => api(`/api/users/${item.id}`, { method: 'PATCH', body: { active: active.checked } })
                    .then(() => toast('Usuario actualizado', 'success'))
                    .catch((error) => { toast(error.message, 'error'); active.checked = !active.checked; }),
            });
            const actions = h('div', { class: 'btn-row' });
            if (item.username !== user.username) {
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
                h('div', { class: 'grow' }, h('strong', {}, item.username),
                    h('div', { class: 'muted' }, `Creado ${item.created_at ? fmtDate(item.created_at) : '—'}`)),
                h('div', { class: 'role-select' }, role),
                h('label', { class: 'active-toggle' }, active, 'Activo'),
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

    return {};
}
