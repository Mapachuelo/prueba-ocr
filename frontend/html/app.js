import { api } from './api.js';
import { h, clear, modal, toast } from './ui.js';
import { icon } from './icons.js';

const NAV = [
    { id: 'inicio', label: 'Inicio', icon: 'home', roles: ['admin', 'usuario'], load: () => import('./tabs/inicio.js') },
    { id: 'cargar', label: 'Cargar OCR', icon: 'upload', roles: ['admin', 'usuario'], load: () => import('./tabs/cargar.js') },
    { id: 'datos', label: 'Datos', icon: 'table', roles: ['admin', 'usuario'], load: () => import('./tabs/datos.js') },
    { id: 'comparar', label: 'Comparar', icon: 'compare', roles: ['admin', 'usuario'], load: () => import('./tabs/comparar.js') },
    { id: 'historial', label: 'Historial', icon: 'history', roles: ['admin', 'usuario'], load: () => import('./tabs/historial.js') },
    { id: 'config', label: 'Configuración', icon: 'settings', roles: ['admin'], load: () => import('./tabs/config.js') },
];

const TITLES = {
    inicio: ['Inicio', 'Resumen de tus trabajos de OCR'],
    cargar: ['Cargar OCR', 'Sube un archivo y elige cómo procesarlo'],
    datos: ['Datos', 'Revisa, filtra y edita los resultados'],
    comparar: ['Comparar', 'Contrasta dos motores o la referencia'],
    historial: ['Historial', 'Todos los trabajos y su estado'],
    config: ['Configuración', 'IA local, OCR y usuarios'],
};

const state = { user: null, setup: true, tab: null, current: null, params: {} };

const loginView = document.getElementById('loginView');
const appView = document.getElementById('appView');
const loginForm = document.getElementById('loginForm');
const loginHint = document.getElementById('loginHint');
const loginTitle = document.getElementById('loginTitle');
const loginError = document.getElementById('loginError');
const loginSubmit = document.getElementById('loginSubmit');
const confirmWrap = document.getElementById('loginConfirmWrap');
const rememberWrap = document.getElementById('rememberWrap');
const navRoot = document.getElementById('mainNav');
const content = document.getElementById('content');
const sidebar = document.getElementById('sidebar');
const backdrop = document.getElementById('sidebarBackdrop');

function renderLoginBenefits() {
    const benefits = [
        'Carga PDF o Excel y procesa con OCR local o IA',
        'Filtra, corrige y exporta sin salir del navegador',
        'Compara motores y revisa la calidad de los datos',
    ];
    const list = document.getElementById('loginBenefits');
    clear(list);
    for (const text of benefits) {
        list.append(h('li', {}, icon('check', 18), h('span', {}, text)));
    }
}

function showLogin(mode) {
    state.user = null;
    appView.hidden = true;
    loginView.hidden = false;
    loginError.hidden = true;
    const setup = mode === 'setup';
    state.setup = setup;
    loginTitle.textContent = setup ? 'Crear administrador' : 'Iniciar sesión';
    loginHint.textContent = setup
        ? 'Primer uso: define la cuenta con acceso total. Mínimo 4 caracteres.'
        : 'Entra con tu cuenta para continuar.';
    loginSubmit.textContent = setup ? 'Crear administrador' : 'Entrar';
    confirmWrap.hidden = !setup;
    rememberWrap.hidden = setup;
    document.getElementById('loginPass').autocomplete = setup ? 'new-password' : 'current-password';
    renderLoginBenefits();
}

function showApp() {
    loginView.hidden = true;
    appView.hidden = false;
    const initial = (state.user.username || 'U').slice(0, 1).toUpperCase();
    document.getElementById('userAvatar').textContent = initial;
    document.getElementById('userName').textContent = state.user.username;
    document.getElementById('userRole').textContent = state.user.role === 'admin' ? 'Administrador' : 'Usuario';
    document.getElementById('topUser').textContent = `${state.user.username} · ${state.user.role === 'admin' ? 'Admin' : 'Usuario'}`;
    renderNav();
    const hash = location.hash.replace(/^#\/?/, '') || 'cargar';
    navigate(hash, true);
}

function allowedNav() {
    if (!state.user) return [];
    return NAV.filter((item) => item.roles.includes(state.user.role));
}

function renderNav() {
    clear(navRoot);
    for (const item of allowedNav()) {
        navRoot.append(h('button', {
            dataset: { tab: item.id },
            class: state.tab === item.id ? 'active' : '',
            onclick: () => { closeSidebar(); navigate(item.id); },
        }, icon(item.icon), item.label));
    }
}

async function navigate(target, replace = false) {
    if (!state.user) return;
    const [id, query] = String(target).split('?');
    const item = allowedNav().find((entry) => entry.id === id) || allowedNav()[0];
    if (!item) return;
    state.params = Object.fromEntries(new URLSearchParams(query || ''));
    state.tab = item.id;
    if (!replace) history.replaceState(null, '', `#/${target}`);
    renderNav();
    const [title, subtitle] = TITLES[item.id] || [item.label, ''];
    document.getElementById('pageTitle').textContent = title;
    document.getElementById('pageSubtitle').textContent = subtitle;
    if (state.current && state.current.destroy) {
        try { state.current.destroy(); } catch (error) { /* ignora */ }
    }
    clear(content);
    content.append(h('div', { class: 'empty' }, 'Cargando…'));
    try {
        const module = await item.load();
        clear(content);
        state.current = module.render(content, {
            user: state.user,
            params: state.params,
            navigate: (next) => navigate(next),
        }) || {};
    } catch (error) {
        clear(content);
        content.append(h('div', { class: 'alert error' }, `No se pudo cargar la sección: ${error.message}`));
    }
}

function openSidebar() { appView.classList.add('sidebar-open'); }
function closeSidebar() { appView.classList.remove('sidebar-open'); }

document.getElementById('menuBtn').prepend(icon('menu', 20));
document.getElementById('menuBtn').addEventListener('click', () => {
    appView.classList.toggle('sidebar-open');
});
backdrop.addEventListener('click', closeSidebar);

loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    loginError.hidden = true;
    const username = document.getElementById('loginUser').value.trim();
    const password = document.getElementById('loginPass').value;
    if (state.setup && password !== document.getElementById('loginConfirm').value) {
        loginError.textContent = 'Las contraseñas no coinciden';
        loginError.hidden = false;
        return;
    }
    loginSubmit.disabled = true;
    try {
        const endpoint = state.setup ? '/api/auth/setup' : '/api/auth/login';
        const data = await api(endpoint, {
            method: 'POST',
            body: { username, password, remember: document.getElementById('loginRemember').checked },
        });
        state.user = { username: data.username, role: data.role };
        loginForm.reset();
        showApp();
    } catch (error) {
        loginError.textContent = error.message;
        loginError.hidden = false;
    } finally {
        loginSubmit.disabled = false;
    }
});

document.getElementById('btnLogout').addEventListener('click', async () => {
    try { await api('/api/auth/logout', { method: 'POST' }); } catch (error) { /* ignora */ }
    location.hash = '';
    showLogin('login');
});

document.getElementById('btnPassword').addEventListener('click', () => {
    const current = h('input', { type: 'password', placeholder: 'Contraseña actual', autocomplete: 'current-password' });
    const next = h('input', { type: 'password', placeholder: 'Nueva contraseña (mín. 4)', autocomplete: 'new-password' });
    const repeat = h('input', { type: 'password', placeholder: 'Repetir nueva contraseña', autocomplete: 'new-password' });
    const message = h('div', {});
    const body = h('div', { class: 'stack' },
        h('label', { class: 'field' }, 'Contraseña actual', current),
        h('label', { class: 'field' }, 'Nueva contraseña', next),
        h('label', { class: 'field' }, 'Repetir nueva contraseña', repeat),
        message,
    );
    modal('Cambiar contraseña', body, [{
        label: 'Guardar', class: 'primary',
        onClick: async (close) => {
            clear(message);
            if (next.value !== repeat.value) {
                message.append(h('div', { class: 'alert error' }, 'Las contraseñas no coinciden'));
                return;
            }
            try {
                await api('/api/auth/change-password', {
                    method: 'POST',
                    body: { current: current.value, new: next.value },
                });
                toast('Contraseña actualizada', 'success');
                close();
            } catch (error) {
                message.append(h('div', { class: 'alert error' }, error.message));
            }
        },
    }]);
});

window.addEventListener('auth:expired', () => showLogin('login'));
window.addEventListener('hashchange', () => {
    if (state.user) navigate(location.hash.replace(/^#\/?/, '') || 'cargar', true);
});

(async function boot() {
    renderLoginBenefits();
    try {
        const status = await api('/api/auth/status');
        if (!status.setup) showLogin('setup');
        else if (status.authenticated) {
            state.user = status.user;
            showApp();
        } else {
            showLogin('login');
        }
    } catch (error) {
        showLogin('login');
    }
})();
