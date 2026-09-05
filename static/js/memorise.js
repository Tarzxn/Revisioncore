// ─── Memorise — type or speak a text, diff highlights mistakes ───────────────
let memoriseItems  = [];
let currentItem    = null;
let recognition    = null;
let spokenText     = '';
let showingOriginal = true;

document.addEventListener('DOMContentLoaded', () => {
    loadMemoriseItems();
    initMemoriseModal();
    initPractice();
});

// ─── Library ──────────────────────────────────────────────────────────────────
async function loadMemoriseItems() {
    try {
        const res  = await fetch('/api/memorise');
        memoriseItems = await res.json();
    } catch { memoriseItems = []; }
    renderMemoriseLibrary();
}

function renderMemoriseLibrary() {
    const list  = document.getElementById('memoriseList');
    const empty = document.getElementById('memoriseEmpty');
    const icons = { biology:'🧬', chemistry:'⚗️', physics:'⚛️', maths:'📐',
                    english:'📖', history:'🏛️', general:'📚' };

    if (memoriseItems.length === 0) {
        list.innerHTML      = '';
        empty.style.display = 'block';
        return;
    }
    empty.style.display = 'none';
    list.innerHTML = '';

    memoriseItems.forEach(item => {
        const wordCount = item.text.trim().split(/\s+/).length;
        const preview   = item.text.length > 100 ? item.text.slice(0, 100) + '…' : item.text;
        const card      = document.createElement('div');
        card.className  = 'guide-card';
        card.innerHTML  = `
            <div class="guide-icon">${icons[item.subject] || '📚'}</div>
            <div class="guide-name">${esc(item.title)}</div>
            <span class="guide-subject-tag">${item.subject}</span>
            <div class="set-card-count">${wordCount} words</div>
            <div style="color:var(--text-muted);font-size:.8125rem;margin-bottom:.875rem;line-height:1.5">${esc(preview)}</div>
            <div class="guide-actions">
                <button class="guide-btn" onclick="openPractice('${item.id}')">🧠 Practice</button>
                <button class="guide-btn danger" onclick="deleteMemoriseItem('${item.id}')">🗑️</button>
            </div>`;
        list.appendChild(card);
    });
}

window.openPractice         = openPractice;
window.deleteMemoriseItem   = deleteMemoriseItem;

async function deleteMemoriseItem(id) {
    if (!confirm('Delete this text?')) return;
    await fetch(`/api/memorise/${id}`, { method: 'DELETE' });
    await loadMemoriseItems();
}

// ─── Modal ────────────────────────────────────────────────────────────────────
function initMemoriseModal() {
    const modal    = document.getElementById('memoriseModal');
    const openBtn  = document.getElementById('newMemoriseBtn');
    const closeBtn = document.getElementById('closeMemoriseModal');
    const saveBtn  = document.getElementById('saveMemoriseBtn');

    openBtn.addEventListener('click',  () => { modal.style.display = 'block'; });
    closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    window.addEventListener('click',   e  => { if (e.target === modal) modal.style.display = 'none'; });

    saveBtn.addEventListener('click', async () => {
        const title   = document.getElementById('memoriseTitle').value.trim();
        const subject = document.getElementById('memoriseSubject').value;
        const text    = document.getElementById('memoriseText').value.trim();

        if (!title) { alert('Please enter a title.'); return; }
        if (!text)  { alert('Please enter some text to memorise.'); return; }

        const res  = await fetch('/api/memorise', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ title, subject, text })
        });
        const data = await res.json();
        if (data.status === 'success') {
            modal.style.display = 'none';
            document.getElementById('memoriseTitle').value   = '';
            document.getElementById('memoriseText').value    = '';
            await loadMemoriseItems();
        }
    });
}

// ─── Practice view ────────────────────────────────────────────────────────────
function initPractice() {
    document.getElementById('backToMemoriseLib').addEventListener('click', () => {
        document.getElementById('memorisePractice').style.display = 'none';
        document.getElementById('memoriseLibrary').style.display  = 'block';
        stopSpeech();
        currentItem = null;
    });

    // Mode toggle
    document.getElementById('modeTypeBtn').addEventListener('click', () => {
        setMode('type');
    });
    document.getElementById('modeSpeakBtn').addEventListener('click', () => {
        setMode('speak');
    });

    // Show/hide original
    document.getElementById('toggleOriginal').addEventListener('click', () => {
        showingOriginal = !showingOriginal;
        const orig = document.getElementById('memOriginalText');
        const btn  = document.getElementById('toggleOriginal');
        orig.style.display  = showingOriginal ? 'block' : 'none';
        btn.textContent     = showingOriginal ? '👁 Hide original' : '👁 Show original';
    });

    // Type mode
    document.getElementById('checkTypedBtn').addEventListener('click', () => {
        const attempt = document.getElementById('memTypeInput').value;
        runDiff(currentItem.text, attempt);
    });
    document.getElementById('clearTypedBtn').addEventListener('click', () => {
        document.getElementById('memTypeInput').value = '';
        hideDiff();
    });

    // Speak mode
    document.getElementById('startSpeakBtn').addEventListener('click', toggleSpeech);
    document.getElementById('checkSpokenBtn').addEventListener('click', () => {
        runDiff(currentItem.text, spokenText);
    });

    // Try again
    document.getElementById('tryAgainBtn').addEventListener('click', () => {
        hideDiff();
        document.getElementById('memTypeInput').value = '';
        spokenText = '';
        document.getElementById('speakTranscript').textContent  = '';
        document.getElementById('transcriptWrap').style.display = 'none';
        document.getElementById('speakStatus').textContent      = 'Press the button and speak';
        document.getElementById('startSpeakBtn').textContent    = '🎤 Start Recording';
        document.getElementById('startSpeakBtn').classList.remove('recording');
    });

    // Show hints
    document.getElementById('showHintsBtn').addEventListener('click', showHints);
}

function openPractice(id) {
    currentItem = memoriseItems.find(i => i.id === id);
    if (!currentItem) return;

    document.getElementById('memoriseLibrary').style.display  = 'none';
    document.getElementById('memorisePractice').style.display = 'block';
    document.getElementById('practiceTitle').textContent      = currentItem.title;
    document.getElementById('practiceSubject').textContent    = currentItem.subject;
    document.getElementById('memOriginalText').textContent    = currentItem.text;
    document.getElementById('memOriginalText').style.display  = 'block';
    document.getElementById('toggleOriginal').textContent     = '👁 Hide original';
    showingOriginal = true;

    // Reset everything
    hideDiff();
    document.getElementById('memTypeInput').value = '';
    spokenText = '';
    document.getElementById('speakTranscript').textContent  = '';
    document.getElementById('transcriptWrap').style.display = 'none';
    stopSpeech();
    setMode('type');
}

function setMode(mode) {
    const typeBtn   = document.getElementById('modeTypeBtn');
    const speakBtn  = document.getElementById('modeSpeakBtn');
    const typeArea  = document.getElementById('typeModeArea');
    const speakArea = document.getElementById('speakModeArea');

    typeBtn.classList.toggle('active',  mode === 'type');
    speakBtn.classList.toggle('active', mode === 'speak');
    typeArea.style.display  = mode === 'type'  ? 'block' : 'none';
    speakArea.style.display = mode === 'speak' ? 'block' : 'none';

    hideDiff();
    if (mode !== 'speak') stopSpeech();
}

// ─── Speech recognition ───────────────────────────────────────────────────────
function toggleSpeech() {
    const btn    = document.getElementById('startSpeakBtn');
    const status = document.getElementById('speakStatus');

    if (recognition && btn.classList.contains('recording')) {
        recognition.stop();
        return;
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
        alert('Speech recognition is not supported in this browser. Try Chrome or Edge.');
        return;
    }

    recognition = new SR();
    recognition.continuous     = true;
    recognition.interimResults = true;
    recognition.lang           = 'en-GB';

    let finalTranscript = '';

    recognition.onstart = () => {
        btn.textContent = '⏹ Stop Recording';
        btn.classList.add('recording');
        status.textContent = '🔴 Recording… speak clearly';
        spokenText = '';
    };

    recognition.onresult = (e) => {
        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
            const t = e.results[i][0].transcript;
            if (e.results[i].isFinal) finalTranscript += t + ' ';
            else interim = t;
        }
        spokenText = (finalTranscript + interim).trim();
        const el   = document.getElementById('speakTranscript');
        el.textContent = spokenText;
        document.getElementById('transcriptWrap').style.display = 'block';
    };

    recognition.onerror = (e) => {
        status.textContent = `Error: ${e.error}. Try again.`;
        btn.textContent    = '🎤 Start Recording';
        btn.classList.remove('recording');
    };

    recognition.onend = () => {
        btn.textContent = '🎤 Start Recording';
        btn.classList.remove('recording');
        if (spokenText) {
            status.textContent = '✓ Recording complete — click "Check my attempt"';
        } else {
            status.textContent = 'No speech detected — try again';
        }
    };

    recognition.start();
}

function stopSpeech() {
    if (recognition) {
        try { recognition.stop(); } catch {}
        recognition = null;
    }
    const btn = document.getElementById('startSpeakBtn');
    if (btn) {
        btn.textContent = '🎤 Start Recording';
        btn.classList.remove('recording');
    }
}

// ─── Diff engine ──────────────────────────────────────────────────────────────
function tokenise(text) {
    // Split into words preserving punctuation attached to words
    return text.trim().toLowerCase()
               .replace(/[""'']/g, '"')
               .split(/\s+/)
               .filter(w => w.length > 0)
               .map(w => w.replace(/[.,!?;:"""]+$/, '').replace(/^["""]+/, ''));
}

function lcs(a, b) {
    // Longest common subsequence — returns matrix
    const m = a.length, n = b.length;
    const dp = Array.from({length: m+1}, () => new Array(n+1).fill(0));
    for (let i = 1; i <= m; i++)
        for (let j = 1; j <= n; j++)
            dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
    return dp;
}

function diffWords(original, attempt) {
    const orig = tokenise(original);
    const att  = tokenise(attempt);
    const dp   = lcs(orig, att);

    // Backtrack to get edit operations
    const opsOrig = []; // what to show in original column
    const opsAtt  = []; // what to show in attempt column

    let i = orig.length, j = att.length;
    const ops = [];
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && orig[i-1] === att[j-1]) {
            ops.unshift({ type: 'equal', orig: orig[i-1], att: att[j-1] });
            i--; j--;
        } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
            ops.unshift({ type: 'extra', att: att[j-1] }); // extra word in attempt
            j--;
        } else {
            ops.unshift({ type: 'missing', orig: orig[i-1] }); // missing from attempt
            i--;
        }
    }
    return ops;
}

function runDiff(original, attempt) {
    if (!attempt.trim()) { alert('Please write or speak something first!'); return; }

    const ops = diffWords(original, attempt);

    let origHtml    = '';
    let attemptHtml = '';
    let correct = 0, total = 0;

    ops.forEach(op => {
        if (op.type === 'equal') {
            origHtml    += `<span class="diff-correct">${esc(op.orig)} </span>`;
            attemptHtml += `<span class="diff-correct">${esc(op.att)} </span>`;
            correct++;
            total++;
        } else if (op.type === 'missing') {
            origHtml    += `<span class="diff-missing">${esc(op.orig)} </span>`;
            attemptHtml += `<span class="diff-missing">▢ </span>`;
            total++;
        } else if (op.type === 'extra') {
            origHtml    += `<span class="diff-extra">· </span>`;
            attemptHtml += `<span class="diff-extra">${esc(op.att)} </span>`;
        }
    });

    const pct   = total > 0 ? Math.round((correct / total) * 100) : 0;
    const emoji = pct === 100 ? '🎉' : pct >= 80 ? '👍' : pct >= 50 ? '📝' : '💪';

    document.getElementById('diffOriginal').innerHTML = origHtml;
    document.getElementById('diffAttempt').innerHTML  = attemptHtml;
    document.getElementById('memScoreBadge').textContent = `${emoji} ${pct}% — ${correct}/${total} words correct`;
    document.getElementById('memScoreBadge').className = 'mem-score-badge ' +
        (pct === 100 ? 'score-perfect' : pct >= 80 ? 'score-good' : pct >= 50 ? 'score-ok' : 'score-low');

    document.getElementById('diffResult').style.display  = 'block';
    document.getElementById('hintsArea').style.display   = 'none';
    document.getElementById('diffResult').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function hideDiff() {
    document.getElementById('diffResult').style.display = 'none';
    document.getElementById('hintsArea').style.display  = 'none';
}

// ─── Hints: first letter of each word ────────────────────────────────────────
function showHints() {
    if (!currentItem) return;
    const words = currentItem.text.trim().split(/\s+/);
    const hints = words.map(w => {
        const clean = w.replace(/[^a-zA-Z0-9]/g, '');
        if (!clean) return w; // punctuation only
        return w[0] + '_'.repeat(Math.max(0, clean.length - 1)) + w.slice(clean.length + w.indexOf(clean[0]) + clean.length - 1 - w.indexOf(clean[0]));
    }).join(' ');

    // Simpler approach: just show first char + underscores for each word
    const hintLine = words.map(w => {
        const letters = w.replace(/[^a-zA-Z0-9']/g, '');
        if (letters.length === 0) return w;
        return w[0] + '_ '.repeat(Math.max(0, letters.length - 1)).trim();
    }).join(' ');

    document.getElementById('hintsArea').textContent    = hintLine;
    document.getElementById('hintsArea').style.display  = 'block';
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
