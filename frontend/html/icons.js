const ICONS = {
    home: ['M3 10.5 12 3l9 7.5', 'M5 9.5V21h5v-6h4v6h5V9.5'],
    upload: ['M12 16V4', 'm7 9 5-5 5 5', 'M5 20h14'],
    table: ['M4 5h16v14H4z', 'M4 10h16', 'M10 10v9'],
    compare: ['M8 4v12', 'm5 7 3-3 3 3', 'M16 20V8', 'm13 17 3 3 3-3'],
    history: ['M3 12a9 9 0 1 0 9-9 9 9 0 0 0-7.5 4', 'M3 4v5h5', 'M12 7v5l3 2'],
    settings: ['M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', 'M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z'],
    file: ['M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z', 'M14 3v6h6'],
    check: ['m4 12 5 5L20 6'],
    alert: ['M12 8v5', 'M12 17h.01', 'M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
    x: ['M6 6l12 12', 'M18 6 6 18'],
    refresh: ['M20 11a8 8 0 0 0-14.9-4L3 10', 'M3 4v6h6', 'M4 13a8 8 0 0 0 14.9 4L21 14', 'M21 20v-6h-6'],
    download: ['M12 3v12', 'm7 10 5 5 5-5', 'M5 21h14'],
    edit: ['M12 20h9', 'M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z'],
    trash: ['M3 6h18', 'M8 6V4h8v2', 'M19 6l-1 14H6L5 6', 'M10 11v5', 'M14 11v5'],
    eye: ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z', 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z'],
    users: ['M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2', 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M23 21v-2a4 4 0 0 0-3-3.87', 'M16 3.13a4 4 0 0 1 0 7.75'],
    cpu: ['M9 9h6v6H9z', 'M4 4h16v16H4z', 'M9 1v3', 'M15 1v3', 'M9 20v3', 'M15 20v3', 'M1 9h3', 'M1 15h3', 'M20 9h3', 'M20 15h3'],
    chart: ['M4 20V10', 'M10 20V4', 'M16 20v-7', 'M22 20H2'],
    menu: ['M3 6h18', 'M3 12h18', 'M3 18h18'],
    search: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z', 'm21 21-4.3-4.3'],
    filter: ['M3 5h18l-7 8v6l-4 2v-8z'],
    columns: ['M4 4h16v16H4z', 'M9 4v16', 'M15 4v16'],
    plus: ['M12 5v14', 'M5 12h14'],
    logout: ['M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4', 'M16 17l5-5-5-5', 'M21 12H9'],
    key: ['M21 2l-2 2', 'M15.5 8.5 19 12l2-2-3.5-3.5', 'M10 14a5 5 0 1 1 7-7 5 5 0 0 1-7 7z', 'M10 14 3 21'],
    scan: ['M3 7V5a2 2 0 0 1 2-2h2', 'M17 3h2a2 2 0 0 1 2 2v2', 'M21 17v2a2 2 0 0 1-2 2h-2', 'M7 21H5a2 2 0 0 1-2-2v-2', 'M7 12h10'],
    info: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 16v-4', 'M12 8h.01'],
};

export function icon(name, size = 18) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = (ICONS[name] || ICONS.info).map((d) => `<path d="${d}"/>`).join('');
    return svg;
}
