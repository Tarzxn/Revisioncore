// ─── PDF Viewer & Annotations ─────────────────────────────────────────────────
pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

let guides        = [];
let currentGuide  = null;
let pdfDoc        = null;
let currentPage   = 1;
let scale         = 1.5;
let pageRendering = false;
let pendingPage   = null;

let currentTool   = 'select';
let currentColor  = '#ffeb3b';
let isDrawing     = false;
let lastX = 0, lastY = 0;

// Annotations stored per page: { page: [ {tool,color,fromX,fromY,toX,toY} | {type:'note',x,y,text} ] }
let annotations = {};

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initGuidesLibrary();
    initUploadModal();
    initViewerControls();
    initDrawing();
});

// ─── Library ──────────────────────────────────────────────────────────────────
async function initGuidesLibrary() {
    await loadGuides();

    // Filter tabs
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            renderGuidesList(tab.dataset.filter);
        });
    });
}

async function loadGuides() {
    try {
        const res = await fetch('/api/guides');
        guides = await res.json();
    } catch { guides = []; }
    renderGuidesList('all');
}

function renderGuidesList(filter) {
    const list    = document.getElementById('guidesList');
    const empty   = document.getElementById('guidesEmpty');
    const icons   = { biology:'🧬', chemistry:'⚗️', physics:'⚛️', maths:'📐', general:'📚' };

    const filtered = filter === 'all' ? guides : guides.filter(g => g.subject === filter);

    if (filtered.length === 0) {
        list.innerHTML = '';
        empty.style.display = 'block';
        return;
    }
    empty.style.display = 'none';
    list.innerHTML = '';

    filtered.forEach(guide => {
        const card = document.createElement('div');
        card.className = 'guide-card';
        card.innerHTML = `
            <div class="guide-icon">${icons[guide.subject] || '📄'}</div>
            <div class="guide-name">${guide.name}</div>
            <span class="guide-subject-tag">${guide.subject}</span>
            <div class="guide-actions">
                <button class="guide-btn" onclick="openGuide(${guide.id})">📖 Open</button>
                <button class="guide-btn danger" onclick="deleteGuide(${guide.id})">🗑️ Delete</button>
            </div>`;
        list.appendChild(card);
    });
}

// ─── Upload modal ─────────────────────────────────────────────────────────────
function initUploadModal() {
    const modal    = document.getElementById('uploadModal');
    const openBtn  = document.getElementById('uploadGuideBtn');
    const closeBtn = document.getElementById('closeUpload');
    const form     = document.getElementById('uploadForm');

    openBtn.addEventListener('click',  () => { modal.style.display = 'block'; });
    closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    window.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none'; });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        const file    = document.getElementById('pdfFile').files[0];
        const subject = document.getElementById('guideSubject').value;

        if (!file) { alert('Please select a PDF file.'); return; }

        const fd = new FormData();
        fd.append('file', file);
        fd.append('subject', subject);

        const res  = await fetch('/api/guides/upload', { method:'POST', body: fd });
        const data = await res.json();

        if (data.status === 'success') {
            modal.style.display = 'none';
            form.reset();
            await loadGuides();
        } else {
            alert('Upload failed: ' + (data.error || 'Unknown error'));
        }
    });
}

async function deleteGuide(id) {
    if (!confirm('Delete this guide and all its annotations?')) return;
    await fetch(`/api/guides/${id}`, { method:'DELETE' });
    await loadGuides();
}

// ─── Open guide ───────────────────────────────────────────────────────────────
async function openGuide(id) {
    currentGuide = guides.find(g => g.id === id);
    if (!currentGuide) return;

    annotations  = {};
    currentPage  = 1;
    scale        = 1.5;

    document.getElementById('guidesLibrary').style.display = 'none';
    document.getElementById('pdfViewer').style.display     = 'flex';
    document.getElementById('currentGuideName').textContent = currentGuide.name;
    document.getElementById('zoomLevel').textContent = '100%';

    // Load saved annotations
    try {
        const res  = await fetch(`/api/guides/${id}/annotations`);
        const data = await res.json();
        annotations = data.annotations || {};
    } catch { annotations = {}; }

    // Load PDF
    const task = pdfjsLib.getDocument(`/api/guides/${id}/pdf`);
    pdfDoc = await task.promise;
    renderPage(1);
}

// ─── Render PDF page ──────────────────────────────────────────────────────────
function renderPage(num) {
    if (pageRendering) { pendingPage = num; return; }
    pageRendering = true;

    pdfDoc.getPage(num).then(page => {
        const pdfCanvas  = document.getElementById('pdfCanvas');
        const annCanvas  = document.getElementById('annotationCanvas');
        const pdfCtx     = pdfCanvas.getContext('2d');
        const viewport   = page.getViewport({ scale });

        pdfCanvas.width  = annCanvas.width  = viewport.width;
        pdfCanvas.height = annCanvas.height = viewport.height;

        page.render({ canvasContext: pdfCtx, viewport }).promise.then(() => {
            pageRendering = false;
            if (pendingPage !== null) {
                renderPage(pendingPage);
                pendingPage = null;
            }
            redrawAnnotations();
        });
    });

    document.getElementById('pageInfo').textContent = `Page ${num} / ${pdfDoc.numPages}`;
    currentPage = num;
}

// ─── Viewer toolbar controls ───────────────────────────────────────────────────
function initViewerControls() {
    // Back
    document.getElementById('backToLibrary').addEventListener('click', () => {
        document.getElementById('pdfViewer').style.display     = 'none';
        document.getElementById('guidesLibrary').style.display = 'block';
        pdfDoc = null; currentGuide = null;
    });

    // Save
    document.getElementById('saveAnnotations').addEventListener('click', saveAnnotations);

    // Tools
    document.querySelectorAll('.tool-btn[data-tool]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tool-btn[data-tool]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTool = btn.dataset.tool;
            const cp = document.getElementById('colorPicker');
            cp.style.display = (currentTool === 'highlighter' || currentTool === 'pen') ? 'flex' : 'none';
            const annCanvas = document.getElementById('annotationCanvas');
            annCanvas.style.cursor = currentTool === 'select' ? 'default' : 'crosshair';
        });
    });

    // Colours
    document.querySelectorAll('.color-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.color-btn').forEach(b => b.classList.remove('active-color'));
            btn.classList.add('active-color');
            currentColor = btn.dataset.color;
        });
    });

    // Page nav
    document.getElementById('prevPage').addEventListener('click', () => {
        if (currentPage > 1) renderPage(currentPage - 1);
    });
    document.getElementById('nextPage').addEventListener('click', () => {
        if (pdfDoc && currentPage < pdfDoc.numPages) renderPage(currentPage + 1);
    });

    // Zoom
    document.getElementById('zoomIn').addEventListener('click', () => {
        scale = Math.min(scale + 0.25, 4);
        document.getElementById('zoomLevel').textContent = Math.round(scale / 1.5 * 100) + '%';
        renderPage(currentPage);
    });
    document.getElementById('zoomOut').addEventListener('click', () => {
        scale = Math.max(scale - 0.25, 0.5);
        document.getElementById('zoomLevel').textContent = Math.round(scale / 1.5 * 100) + '%';
        renderPage(currentPage);
    });

    // Clear page annotations
    document.getElementById('clearAnnotations').addEventListener('click', () => {
        if (!confirm('Clear all annotations on this page?')) return;
        annotations[currentPage] = [];
        redrawAnnotations();
    });
}

// ─── Drawing ──────────────────────────────────────────────────────────────────
function initDrawing() {
    const canvas = document.getElementById('annotationCanvas');

    canvas.addEventListener('mousedown', e => {
        if (currentTool === 'select') return;
        if (currentTool === 'text') { addTextNote(e); return; }
        isDrawing = true;
        const r = canvas.getBoundingClientRect();
        lastX = e.clientX - r.left;
        lastY = e.clientY - r.top;
    });

    canvas.addEventListener('mousemove', e => {
        if (!isDrawing || currentTool === 'select' || currentTool === 'text') return;
        const r = canvas.getBoundingClientRect();
        const x = e.clientX - r.left;
        const y = e.clientY - r.top;

        // Draw live stroke
        const ctx = canvas.getContext('2d');
        ctx.strokeStyle = currentColor;
        ctx.lineWidth   = currentTool === 'highlighter' ? 18 : 3;
        ctx.lineCap     = 'round';
        ctx.lineJoin    = 'round';
        ctx.globalAlpha = currentTool === 'highlighter' ? 0.35 : 1;
        ctx.beginPath();
        ctx.moveTo(lastX, lastY);
        ctx.lineTo(x, y);
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Store stroke segment
        if (!annotations[currentPage]) annotations[currentPage] = [];
        annotations[currentPage].push({ tool: currentTool, color: currentColor, fromX: lastX, fromY: lastY, toX: x, toY: y });

        lastX = x; lastY = y;
    });

    canvas.addEventListener('mouseup',  () => { isDrawing = false; });
    canvas.addEventListener('mouseleave', () => { isDrawing = false; });

    // Touch support
    canvas.addEventListener('touchstart', e => {
        e.preventDefault();
        const touch = e.touches[0];
        canvas.dispatchEvent(new MouseEvent('mousedown', { clientX: touch.clientX, clientY: touch.clientY }));
    }, { passive: false });
    canvas.addEventListener('touchmove', e => {
        e.preventDefault();
        const touch = e.touches[0];
        canvas.dispatchEvent(new MouseEvent('mousemove', { clientX: touch.clientX, clientY: touch.clientY }));
    }, { passive: false });
    canvas.addEventListener('touchend', () => { isDrawing = false; });
}

function addTextNote(e) {
    const canvas = document.getElementById('annotationCanvas');
    const r      = canvas.getBoundingClientRect();
    const x      = e.clientX - r.left;
    const y      = e.clientY - r.top;
    const text   = prompt('Enter your note:');
    if (!text) return;
    if (!annotations[currentPage]) annotations[currentPage] = [];
    annotations[currentPage].push({ type: 'note', x, y, text });
    redrawAnnotations();
}

function redrawAnnotations() {
    const canvas = document.getElementById('annotationCanvas');
    const ctx    = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const pageAnns = annotations[currentPage] || [];

    pageAnns.forEach(ann => {
        if (ann.type === 'note') {
            // Draw sticky-note pin
            ctx.fillStyle   = '#f59e0b';
            ctx.strokeStyle = '#b45309';
            ctx.lineWidth   = 2;
            ctx.beginPath();
            ctx.arc(ann.x, ann.y, 11, 0, Math.PI * 2);
            ctx.fill(); ctx.stroke();
            ctx.fillStyle  = '#fff';
            ctx.font       = 'bold 13px Arial';
            ctx.textAlign  = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('N', ann.x, ann.y);

            // Tooltip label
            const label = ann.text.length > 28 ? ann.text.slice(0, 28) + '…' : ann.text;
            const pad   = 8;
            const tw    = ctx.measureText(label).width;
            ctx.fillStyle   = 'rgba(15,15,25,0.88)';
            ctx.strokeStyle = '#f59e0b';
            ctx.lineWidth   = 1;
            roundRect(ctx, ann.x + 16, ann.y - 14, tw + pad*2, 28, 6);
            ctx.fill(); ctx.stroke();
            ctx.fillStyle    = '#ffe082';
            ctx.font         = '12px Outfit, sans-serif';
            ctx.textAlign    = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, ann.x + 16 + pad, ann.y);
        } else {
            ctx.strokeStyle = ann.color;
            ctx.lineWidth   = ann.tool === 'highlighter' ? 18 : 3;
            ctx.lineCap     = 'round';
            ctx.lineJoin    = 'round';
            ctx.globalAlpha = ann.tool === 'highlighter' ? 0.35 : 1;
            ctx.beginPath();
            ctx.moveTo(ann.fromX, ann.fromY);
            ctx.lineTo(ann.toX,   ann.toY);
            ctx.stroke();
            ctx.globalAlpha = 1;
        }
    });
}

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

async function saveAnnotations() {
    if (!currentGuide) return;
    try {
        await fetch(`/api/guides/${currentGuide.id}/annotations`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ annotations })
        });
        // Brief visual confirmation on the button
        const btn = document.getElementById('saveAnnotations');
        const orig = btn.textContent;
        btn.textContent = '✅ Saved!';
        setTimeout(() => { btn.textContent = orig; }, 1500);
    } catch {
        alert('❌ Failed to save annotations.');
    }
}

// Expose for inline onclick
window.openGuide   = openGuide;
window.deleteGuide = deleteGuide;
