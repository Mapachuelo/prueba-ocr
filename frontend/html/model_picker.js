import { h, clear, normalize } from './ui.js';

/**
 * Selector de modelos con búsqueda, altura fija y navegación por teclado.
 * La lista se muestra como panel flotante para no alargar la página.
 */
export function createModelPicker({
    models = [],
    selected = '',
    onSelect = () => {},
    meta = null,
    placeholder = 'Buscar modelo…',
} = {}) {
    let items = [...models];
    let current = selected || '';
    let open = false;
    let activeIndex = 0;
    const controller = new AbortController();

    const triggerValue = h('span', { class: 'model-picker-value' });
    const trigger = h('button', {
        type: 'button',
        class: 'model-picker-trigger',
        'aria-haspopup': 'listbox',
        'aria-expanded': 'false',
    }, triggerValue, h('span', { class: 'model-picker-chevron', 'aria-hidden': 'true' }, '⌄'));

    const search = h('input', {
        type: 'search',
        class: 'model-picker-search',
        placeholder,
        autocomplete: 'off',
        'aria-label': 'Buscar modelo',
    });
    const list = h('div', { class: 'model-picker-list', role: 'listbox' });
    const count = h('div', { class: 'model-picker-count' });
    const panel = h('div', { class: 'model-picker-panel', hidden: true }, search, list, count);
    const root = h('div', { class: 'model-picker' }, trigger, panel);

    function selectedModel() {
        return items.find((model) => model.id === current) || null;
    }

    function metaNodes(model) {
        const value = meta ? meta(model) : null;
        if (!value) return [];
        return Array.isArray(value) ? value.filter(Boolean) : [value];
    }

    function renderTrigger() {
        clear(triggerValue);
        const model = selectedModel();
        if (!model) {
            triggerValue.append(h('span', { class: 'muted' }, 'Selecciona un modelo'));
            return;
        }
        triggerValue.append(
            h('strong', {}, model.id),
            h('span', { class: 'model-picker-meta' }, ...metaNodes(model)),
        );
    }

    function filtered() {
        const needle = normalize(search.value);
        if (!needle) return items;
        return items.filter((model) => normalize(model.id).includes(needle));
    }

    function renderList() {
        clear(list);
        const visible = filtered();
        if (activeIndex >= visible.length) activeIndex = Math.max(0, visible.length - 1);
        if (!visible.length) {
            list.append(h('div', { class: 'model-picker-empty' }, 'No se encontraron modelos'));
            count.textContent = `0 de ${items.length}`;
            return;
        }
        visible.forEach((model, index) => {
            const option = h('button', {
                type: 'button',
                class: `model-option${index === activeIndex ? ' active' : ''}`,
                role: 'option',
                'aria-selected': model.id === current ? 'true' : 'false',
                onclick: () => choose(model),
                onpointerenter: () => {
                    if (activeIndex !== index) {
                        const previous = list.querySelectorAll('.model-option')[activeIndex];
                        if (previous) previous.classList.remove('active');
                        activeIndex = index;
                        option.classList.add('active');
                    }
                },
            },
                h('span', { class: 'model-option-id' }, model.id),
                h('span', { class: 'model-option-meta' }, ...metaNodes(model)),
            );
            list.append(option);
        });
        count.textContent = `${visible.length} de ${items.length}`;
        const active = list.children[activeIndex];
        if (active) active.scrollIntoView({ block: 'nearest' });
    }

    function choose(model) {
        current = model.id;
        renderTrigger();
        closePanel(true);
        onSelect(model);
    }

    function openPanel() {
        open = true;
        panel.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        search.value = '';
        const visible = filtered();
        activeIndex = Math.max(0, visible.findIndex((model) => model.id === current));
        renderList();
        search.focus();
        search.select();
    }

    function closePanel(focusTrigger = false) {
        open = false;
        panel.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        if (focusTrigger) trigger.focus();
    }

    trigger.addEventListener('click', () => {
        if (open) closePanel();
        else openPanel();
    });
    search.addEventListener('input', () => {
        activeIndex = 0;
        renderList();
    });
    search.addEventListener('keydown', (event) => {
        const visible = filtered();
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            activeIndex = Math.min(visible.length - 1, activeIndex + 1);
            renderList();
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            activeIndex = Math.max(0, activeIndex - 1);
            renderList();
        } else if (event.key === 'Enter') {
            event.preventDefault();
            if (visible[activeIndex]) choose(visible[activeIndex]);
        } else if (event.key === 'Escape') {
            event.preventDefault();
            closePanel(true);
        } else if (event.key === 'Home') {
            event.preventDefault();
            activeIndex = 0;
            renderList();
        } else if (event.key === 'End') {
            event.preventDefault();
            activeIndex = Math.max(0, visible.length - 1);
            renderList();
        }
    });
    panel.addEventListener('click', (event) => event.stopPropagation());

    document.addEventListener('click', (event) => {
        if (open && !root.contains(event.target)) closePanel();
    }, { signal: controller.signal });
    document.addEventListener('keydown', (event) => {
        if (!root.isConnected || root.offsetParent === null) return;
        const tag = (event.target?.tagName || '').toLowerCase();
        const editing = ['input', 'textarea', 'select'].includes(tag) || event.target?.isContentEditable;
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
            event.preventDefault();
            openPanel();
        } else if (event.key === '/' && !editing && !open) {
            event.preventDefault();
            openPanel();
        }
    }, { signal: controller.signal });

    function setModels(nextModels, selectedId) {
        items = [...nextModels];
        if (selectedId !== undefined) current = selectedId;
        if (!items.some((model) => model.id === current)) {
            current = items[0]?.id || '';
        }
        renderTrigger();
        if (open) renderList();
    }

    function setSelected(id) {
        current = id || '';
        renderTrigger();
    }

    renderTrigger();
    return {
        root,
        setModels,
        setSelected,
        getSelected: () => current,
        open: openPanel,
        destroy: () => controller.abort(),
    };
}
