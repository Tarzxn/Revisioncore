// ─── Client-side document generation (Word / Excel / PowerPoint) ──────────────
// Everything here runs entirely in the browser via CDN libraries (docx.js,
// SheetJS, PptxGenJS) — no server calls, no third-party API keys. Works
// identically on localhost and once deployed on Render.

function rcDownloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
}

// title: string, bodyText: plain text (paragraphs separated by \n)
async function rcCreateDocx(title, bodyText, filename) {
    const { Document, Packer, Paragraph, HeadingLevel, TextRun } = window.docx;
    const paragraphs = [
        new Paragraph({ text: title, heading: HeadingLevel.HEADING_1 }),
        ...bodyText.split('\n').filter(l => l.trim()).map(line =>
            new Paragraph({ children: [new TextRun(line)] }))
    ];
    const doc = new Document({ sections: [{ children: paragraphs }] });
    const blob = await Packer.toBlob(doc);
    rcDownloadBlob(blob, filename || `${title}.docx`);
}

// rows: array of arrays (first row = headers)
function rcCreateXlsx(rows, sheetName, filename) {
    const ws = XLSX.utils.aoa_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, sheetName || 'Sheet1');
    XLSX.writeFile(wb, filename || 'RevisionCore.xlsx');
}

// slides: array of { title, bullets: [] }
function rcCreatePptx(title, slides, filename) {
    const pptx = new PptxGenJS();
    const titleSlide = pptx.addSlide();
    titleSlide.addText(title, { x: 0.5, y: 2.2, w: 9, h: 1.2, fontSize: 32, bold: true, align: 'center' });
    slides.forEach(s => {
        const slide = pptx.addSlide();
        slide.addText(s.title, { x: 0.5, y: 0.4, w: 9, h: 0.8, fontSize: 24, bold: true });
        slide.addText(s.bullets.map(b => ({ text: b, options: { bullet: true, breakLine: true } })),
            { x: 0.5, y: 1.4, w: 9, h: 4.5, fontSize: 16 });
    });
    pptx.writeFile({ fileName: filename || `${title}.pptx` });
}

// Renders "Download as Word / Excel / PowerPoint" buttons into `container`.
// getText() returns the current plain-text content to export; used for docx & pptx.
// getRows() (optional) returns array-of-arrays for an Excel export; if absent, the Excel button is skipped.
function rcAttachDownloadButtons(container, { title, getText, getRows }) {
    if (!container || container.dataset.rcDlAttached) return;
    container.dataset.rcDlAttached = '1';
    const wrap = document.createElement('div');
    wrap.className = 'docgen-btns';

    const wordBtn = document.createElement('button');
    wordBtn.className = 'docgen-btn'; wordBtn.type = 'button';
    wordBtn.textContent = '📄 Download Word';
    wordBtn.addEventListener('click', () => rcCreateDocx(title(), getText(), `${title()}.docx`));
    wrap.appendChild(wordBtn);

    const pptBtn = document.createElement('button');
    pptBtn.className = 'docgen-btn'; pptBtn.type = 'button';
    pptBtn.textContent = '📊 Download PowerPoint';
    pptBtn.addEventListener('click', () => {
        const paras = getText().split('\n').filter(l => l.trim());
        rcCreatePptx(title(), [{ title: title(), bullets: paras.slice(0, 8) }], `${title()}.pptx`);
    });
    wrap.appendChild(pptBtn);

    if (getRows) {
        const xlsBtn = document.createElement('button');
        xlsBtn.className = 'docgen-btn'; xlsBtn.type = 'button';
        xlsBtn.textContent = '📈 Download Excel';
        xlsBtn.addEventListener('click', () => rcCreateXlsx(getRows(), title(), `${title()}.xlsx`));
        wrap.appendChild(xlsBtn);
    }

    container.appendChild(wrap);
}
