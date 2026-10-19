const NS = 'http://www.w3.org/2000/svg';

function svgEl(name, attrs = {}) {
    const el = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    return el;
}

export function donut(container, segments, options = {}) {
    container.innerHTML = '';
    const total = segments.reduce((sum, item) => sum + item.value, 0);
    if (!total) {
        container.append(empty('Sin datos suficientes'));
        return;
    }
    const size = options.size || 220;
    const thickness = options.thickness || 26;
    const radius = (size - thickness) / 2;
    const circumference = 2 * Math.PI * radius;
    const center = size / 2;
    const svg = svgEl('svg', { viewBox: `0 0 ${size} ${size}`, role: 'img' });

    const track = svgEl('circle', {
        cx: center, cy: center, r: radius, fill: 'none',
        stroke: '#eef2f7', 'stroke-width': thickness,
    });
    svg.append(track);

    let offset = 0;
    for (const segment of segments) {
        if (!segment.value) continue;
        const length = (segment.value / total) * circumference;
        const circle = svgEl('circle', {
            cx: center, cy: center, r: radius, fill: 'none',
            stroke: segment.color, 'stroke-width': thickness,
            'stroke-dasharray': `${length} ${circumference - length}`,
            'stroke-dashoffset': -offset,
            transform: `rotate(-90 ${center} ${center})`,
        });
        const title = svgEl('title');
        title.textContent = `${segment.label}: ${segment.value}`;
        circle.append(title);
        svg.append(circle);
        offset += length;
    }

    if (options.centerTop !== undefined) {
        const top = svgEl('text', {
            x: center, y: center - 2, 'text-anchor': 'middle',
            'font-size': 26, 'font-weight': 800, fill: '#0f172a',
        });
        top.textContent = options.centerTop;
        svg.append(top);
    }
    if (options.centerBottom !== undefined) {
        const bottom = svgEl('text', {
            x: center, y: center + 20, 'text-anchor': 'middle',
            'font-size': 11, fill: '#64748b',
        });
        bottom.textContent = options.centerBottom;
        svg.append(bottom);
    }
    container.append(svg);

    const legend = document.createElement('div');
    legend.className = 'legend';
    for (const segment of segments) {
        const item = document.createElement('span');
        const dot = document.createElement('i');
        dot.style.background = segment.color;
        item.append(dot, `${segment.label}: ${segment.value}`);
        legend.append(item);
    }
    container.append(legend);
}

export function hbars(container, items, options = {}) {
    container.innerHTML = '';
    if (!items.length) {
        container.append(empty('Sin datos'));
        return;
    }
    const max = options.max || Math.max(...items.map((item) => item.value), 1);
    const format = options.format || ((value) => value);
    for (const item of items) {
        const row = document.createElement('div');
        row.className = 'hbar-row';

        const label = document.createElement('span');
        label.className = 'hbar-label';
        label.textContent = item.label;

        const track = document.createElement('div');
        track.className = 'hbar-track';
        const fill = document.createElement('div');
        fill.className = 'hbar-fill';
        fill.style.width = `${Math.max(2, (item.value / max) * 100)}%`;
        if (item.color) fill.style.background = item.color;
        track.append(fill);

        const value = document.createElement('span');
        value.className = 'hbar-value';
        value.textContent = format(item.value, item);

        row.append(label, track, value);
        container.append(row);
    }
}

export function lineChart(container, points, options = {}) {
    container.innerHTML = '';
    if (!points.length) {
        container.append(empty('Sin datos'));
        return;
    }
    const width = 640;
    const height = 230;
    const pad = { top: 18, right: 16, bottom: 34, left: 34 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;
    const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img' });

    for (const level of [0, 25, 50, 75, 100]) {
        const y = pad.top + innerH - (level / 100) * innerH;
        const line = svgEl('line', {
            x1: pad.left, x2: width - pad.right, y1: y, y2: y,
            stroke: '#eef2f7', 'stroke-width': 1,
        });
        svg.append(line);
        const text = svgEl('text', {
            x: pad.left - 6, y: y + 3, 'text-anchor': 'end', 'font-size': 9, fill: '#94a3b8',
        });
        text.textContent = level;
        svg.append(text);
    }

    const valid = points.filter((point) => point.value !== null && point.value !== undefined);
    if (!valid.length) {
        container.append(empty('Sin datos de precisión'));
        return;
    }
    const stepX = points.length > 1 ? innerW / (points.length - 1) : innerW;
    const coords = points.map((point, index) => {
        const x = pad.left + index * stepX;
        const value = point.value === null || point.value === undefined ? null : point.value;
        const y = value === null ? null : pad.top + innerH - (value / 100) * innerH;
        return { x, y, ...point };
    });

    const pathParts = [];
    coords.forEach((point) => {
        if (point.y === null) return;
        pathParts.push(`${pathParts.length ? 'L' : 'M'} ${point.x} ${point.y}`);
    });
    const path = svgEl('path', {
        d: pathParts.join(' '), fill: 'none', stroke: options.color || '#2563eb',
        'stroke-width': 2.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    });
    svg.append(path);

    coords.forEach((point) => {
        if (point.y !== null) {
            const circle = svgEl('circle', {
                cx: point.x, cy: point.y, r: 3.5,
                fill: '#fff', stroke: options.color || '#2563eb', 'stroke-width': 2,
            });
            const title = svgEl('title');
            title.textContent = `${point.date}: ${point.value}%`;
            circle.append(title);
            svg.append(circle);
        }
        if (points.length <= 14 || point === coords[0] || point === coords[coords.length - 1]) {
            const label = svgEl('text', {
                x: point.x, y: height - 10, 'text-anchor': 'middle',
                'font-size': 9, fill: '#94a3b8',
            });
            label.textContent = (point.date || '').slice(5);
            svg.append(label);
        }
    });

    container.append(svg);
}

function empty(message) {
    const node = document.createElement('div');
    node.className = 'chart-empty';
    node.textContent = message;
    return node;
}
