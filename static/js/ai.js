// ─── AI Tutor page — Ollama powered ───────────────────────────────────────────
let chatHistory = [];
let aiSets      = [];
let aiQuizData  = [];
let aiQuizIndex = 0;
let aiQuizScore = 0;
let genCount    = 5;
let aiThinking  = false;

document.addEventListener('DOMContentLoaded', () => {
    checkAiStatus();
    initAiNav();
    initChat();
    initExplain();
    initGenerate();
    initMark();
    document.getElementById('retryAiStatus').addEventListener('click', checkAiStatus);
});

// ─── AI status ────────────────────────────────────────────────────────────────
async function checkAiStatus() {
    setStatusPill('checking', '⏳ Connecting to Puter.js…');
    const ready = await rcAIReady();
    if (ready) {
        setStatusPill('online', '🟢 Puter.js AI ready');
        const lbl = document.getElementById('aiModelLabel');
        if (lbl) lbl.textContent = 'Powered by Puter.js';
        document.getElementById('aiOfflineWarning').style.display = 'none';
        document.getElementById('aiTools').style.display = 'block';
        await loadAiSets();
    } else {
        setStatusPill('offline', '🔴 Puter.js unavailable');
        const detail = document.getElementById('aiOfflineDetail');
        if (detail) detail.textContent = 'Could not load https://js.puter.com/v2/ — check your internet connection.';
        document.getElementById('aiOfflineWarning').style.display = 'block';
        document.getElementById('aiTools').style.display = 'none';
    }
}

function setStatusPill(state, text) {
    const pill = document.getElementById('aiStatus');
    const dot  = document.getElementById('aiStatusDot');
    const txt  = document.getElementById('aiStatusText');
    pill.className = `ai-status-pill ai-status-${state}`;
    if (dot) dot.className = `ai-status-dot dot-${state}`;
    if (txt) txt.textContent = text;
}

function setThinking(on) {
    aiThinking = on;
    const el   = document.getElementById('aiThinkingStatus');
    const pill = document.getElementById('aiStatus');
    if (el)   el.style.display = on ? 'flex' : 'none';
    if (pill) pill.classList.toggle('ai-status-thinking', on);
}

// ─── Sets ─────────────────────────────────────────────────────────────────────
async function loadAiSets() {
    try {
        const res = await fetch('/api/sets');
        aiSets = await res.json();
    } catch { aiSets = []; }
    populateAllSelects();
}

function populateAllSelects() {
    // Single-set selects (explain, mark)
    ['explainSetSelect', 'markSetSelect'].forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        sel.innerHTML = aiSets.length === 0
            ? '<option value="">No sets — create some in Flashcards first</option>'
            : aiSets.map(s => `<option value="${s.id}">${esc(s.name)} (${s.subject})</option>`).join('');
        sel.dispatchEvent(new Event('change'));
    });

    // Generate quiz: multi-select with ALL option and per-set checkboxes
    buildGenSetSelector();
}

function buildGenSetSelector() {
    const container = document.getElementById('genSetContainer');
    if (!container) return;

    if (aiSets.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted);font-size:.9rem">No sets found. Create some flashcard sets first.</p>';
        return;
    }

    // Group by subject
    const grouped = {};
    aiSets.forEach(s => {
        if (!grouped[s.subject]) grouped[s.subject] = [];
        grouped[s.subject].push(s);
    });

    const icons = { biology:'🧬', chemistry:'⚗️', physics:'⚛️', maths:'📐', computer_science:'💻',
                     english:'📖', history:'🏛️', geography:'🌍', french:'🇫🇷', spanish:'🇪🇸', german:'🇩🇪', general:'📚' };

    let html = `
        <div class="gen-set-all">
            <label class="gen-set-label">
                <input type="checkbox" id="genSelectAll" checked>
                <span>All sets (${aiSets.length} set${aiSets.length!==1?'s':''})</span>
            </label>
        </div>
        <div class="gen-set-groups">`;

    for (const [subj, sets] of Object.entries(grouped)) {
        html += `<div class="gen-set-group">
            <div class="gen-set-subject">${icons[subj]||'📚'} ${subj}</div>`;
        sets.forEach(s => {
            html += `<label class="gen-set-label gen-set-item">
                <input type="checkbox" class="gen-set-cb" value="${s.id}" checked>
                <span>${esc(s.name)} <em style="color:var(--text-muted)">${s.cards.length} cards</em></span>
            </label>`;
        });
        html += '</div>';
    }
    html += '</div>';
    container.innerHTML = html;

    // Select all toggle
    document.getElementById('genSelectAll').addEventListener('change', function() {
        container.querySelectorAll('.gen-set-cb').forEach(cb => cb.checked = this.checked);
    });
    container.querySelectorAll('.gen-set-cb').forEach(cb => {
        cb.addEventListener('change', () => {
            const all   = container.querySelectorAll('.gen-set-cb');
            const checked = container.querySelectorAll('.gen-set-cb:checked');
            document.getElementById('genSelectAll').checked = all.length === checked.length;
        });
    });
}

function getSelectedSetIds() {
    const cbs = document.querySelectorAll('.gen-set-cb:checked');
    return Array.from(cbs).map(cb => cb.value);
}

// ─── AI nav ───────────────────────────────────────────────────────────────────
function initAiNav() {
    document.querySelectorAll('.ai-nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.ai-nav-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.ai-panel').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`ai-panel-${btn.dataset.tab}`).classList.add('active');
        });
    });
}

// ─── Chat ─────────────────────────────────────────────────────────────────────
function initChat() {
    const input   = document.getElementById('chatInput');
    const sendBtn = document.getElementById('chatSendBtn');

    sendBtn.addEventListener('click', sendChat);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 140) + 'px';
    });
    document.querySelectorAll('.chat-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            input.value = chip.textContent;
            document.getElementById('chatChips').style.display = 'none';
            sendChat();
        });
    });
}

async function sendChat() {
    if (aiThinking) return;
    const input   = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message) return;

    const chips = document.getElementById('chatChips');
    if (chips) chips.style.display = 'none';

    input.value = '';
    input.style.height = 'auto';

    appendMsg('user', message);
    chatHistory.push({ role: 'user', content: message });

    setThinking(true);
    const typingEl = appendTyping();

    let context = "You are RevisionCore AI, a friendly GCSE tutor. Give clear, concise answers with examples. Keep focused on studying.\n\n";
    chatHistory.slice(-8).forEach(m => { context += `${m.role === 'user' ? 'Student' : 'Tutor'}: ${m.content}\n`; });

    try {
        const reply = await rcAIChat(context);
        typingEl.remove();
        setThinking(false);
        const row = appendMsg('ai', reply);
        chatHistory.push({ role: 'assistant', content: reply });
        rcAttachDownloadButtons(row.querySelector('.chat-bubble'), { title: () => 'AI Tutor answer', getText: () => reply });
    } catch (e) {
        typingEl.remove();
        setThinking(false);
        appendMsg('ai', '❌ ' + e.message);
    }
}

function appendMsg(role, text) {
    const win = document.getElementById('chatWindow');
    const row = document.createElement('div');
    row.className = `chat-row ${role === 'user' ? 'user-row' : 'ai-row'}`;
    row.innerHTML = `
        <div class="chat-avatar-wrap">
            <div class="chat-avatar ${role === 'user' ? 'user-avatar' : 'ai-avatar'}">${role==='user'?'🧑‍🎓':'🤖'}</div>
        </div>
        <div class="chat-bubble ${role === 'user' ? 'user-bubble' : 'ai-bubble'}">${fmt(text)}</div>`;
    win.appendChild(row);
    win.scrollTop = win.scrollHeight;
    return row;
}

function appendTyping() {
    const win = document.getElementById('chatWindow');
    const row = document.createElement('div');
    row.className = 'chat-row ai-row';
    row.innerHTML = `
        <div class="chat-avatar-wrap"><div class="chat-avatar ai-avatar">🤖</div></div>
        <div class="chat-bubble ai-bubble typing-bubble">
            <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
        </div>`;
    win.appendChild(row);
    win.scrollTop = win.scrollHeight;
    return row;
}

// ─── Explain ──────────────────────────────────────────────────────────────────
function initExplain() {
    document.getElementById('explainSetSelect').addEventListener('change', () => {
        populateCardSelect('explainSetSelect', 'explainCardSelect');
    });
    document.getElementById('explainBtn').addEventListener('click', runExplain);
}

function populateCardSelect(setSelId, cardSelId) {
    const set = aiSets.find(s => s.id === document.getElementById(setSelId).value);
    const sel = document.getElementById(cardSelId);
    if (!sel) return;
    sel.innerHTML = !set || set.cards.length === 0
        ? '<option>No cards in this set</option>'
        : set.cards.map((c, i) => `<option value="${i}">${esc(c.question)}</option>`).join('');
}

async function runExplain() {
    const setId   = document.getElementById('explainSetSelect').value;
    const cardIdx = parseInt(document.getElementById('explainCardSelect').value);
    const set     = aiSets.find(s => s.id === setId);
    if (!set || isNaN(cardIdx)) return;
    const card = set.cards[cardIdx];

    const result      = document.getElementById('explainResult');
    const placeholder = document.getElementById('explainPlaceholder');
    const btn         = document.getElementById('explainBtn');

    placeholder.style.display = 'none';
    result.style.display = 'block';
    result.innerHTML = loadingHTML('Explaining…');
    btn.disabled = true;
    setThinking(true);

    const prompt = `A student is studying ${set.subject}. Explain this concept simply for a GCSE student:\n\n`+
        `Term: ${card.question}\nDefinition: ${card.answer}\n\n`+
        `Give a clear 2-4 sentence explanation then one real-world example. Use plain English, no bullet points.`;
    try {
        const reply = await rcAIChat(prompt);
        result.innerHTML = `
            <div class="result-term-bar">
                <strong>${esc(card.question)}</strong>
                <span class="guide-subject-tag">${set.subject}</span>
            </div>
            <div class="result-body">${fmt(reply)}</div>`;
        rcAttachDownloadButtons(result, { title: () => card.question, getText: () => reply });
    } catch (e) {
        result.innerHTML = errorHTML(e.message);
    }
    btn.disabled = false;
    setThinking(false);
}

// ─── Generate Quiz ────────────────────────────────────────────────────────────
function initGenerate() {
    document.querySelectorAll('.count-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.count-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            genCount = parseInt(btn.dataset.count);
        });
    });

    // Use the renamed button ID
    const genBtn = document.getElementById('aiPageGenerateBtn');
    if (genBtn) genBtn.addEventListener('click', runGenerateQuiz);

    const retryBtn = document.getElementById('aiQuizRetry');
    if (retryBtn) retryBtn.addEventListener('click', () => {
        document.getElementById('aiQuizResults').style.display   = 'none';
        document.getElementById('aiQuizContainer').style.display = 'none';
        document.getElementById('genPlaceholder').style.display  = 'flex';
    });
}

async function runGenerateQuiz() {
    const setIds  = getSelectedSetIds();
    if (setIds.length === 0) { alert('Select at least one set!'); return; }

    const loading     = document.getElementById('aiQuizLoading');
    const container   = document.getElementById('aiQuizContainer');
    const results     = document.getElementById('aiQuizResults');
    const placeholder = document.getElementById('genPlaceholder');
    const btn         = document.getElementById('aiPageGenerateBtn');

    placeholder.style.display  = 'none';
    loading.style.display      = 'flex';
    container.style.display    = 'none';
    results.style.display      = 'none';
    if (btn) btn.disabled = true;
    setThinking(true);

    const chosen = aiSets.filter(s => setIds.includes(s.id));
    const cards  = chosen.flatMap(s => s.cards);
    const subjectsUsed = [...new Set(chosen.map(s => s.subject))];
    const subject = subjectsUsed.length > 1 ? subjectsUsed.join(', ') : (subjectsUsed[0] || 'mixed');

    if (cards.length === 0) {
        loading.style.display = 'none';
        placeholder.style.display = 'flex';
        placeholder.innerHTML = `<span style="font-size:2rem">❌</span><p>No cards found in the selected sets.</p>`;
        if (btn) btn.disabled = false;
        setThinking(false);
        return;
    }

    const sample = cards.length > 20 ? cards.sort(() => Math.random() - 0.5).slice(0, 20) : cards;
    const facts  = sample.map(c => `- ${c.question}: ${c.answer}`).join('\n');
    const prompt = `Create exactly ${genCount} multiple choice questions for a GCSE student studying ${subject}.\n`+
        `Use ONLY these facts:\n${facts}\n\nEach question must have exactly 4 options. Make wrong answers plausible.\n`+
        `'correct' is the 0-based index of the right answer.\n\nRespond with ONLY a JSON array:\n`+
        `[{"question":"...","options":["...","...","...","..."],"correct":0}]`;

    try {
        const reply = await rcAIChat(prompt);
        const questions = rcExtractJson(reply);
        loading.style.display = 'none';
        if (!Array.isArray(questions) || questions.length === 0) throw new Error('Empty question list');
        aiQuizData  = questions;
        aiQuizIndex = 0;
        aiQuizScore = 0;
        container.style.display = 'block';
        renderAiQuestion();
    } catch (e) {
        loading.style.display     = 'none';
        placeholder.style.display = 'flex';
        placeholder.innerHTML = `<span style="font-size:2rem">❌</span><p>${esc(e.message)}</p>`;
    }
    if (btn) btn.disabled = false;
    setThinking(false);
}

function renderAiQuestion() {
    const q    = aiQuizData[aiQuizIndex];
    const pct  = ((aiQuizIndex + 1) / aiQuizData.length) * 100;
    const wrap = document.getElementById('aiQuizQuestions');
    wrap.innerHTML = `
        <div class="ai-quiz-progress">
            <div class="quiz-bar"><div class="quiz-bar-fill" style="width:${pct}%"></div></div>
            <div class="quiz-counter">Question ${aiQuizIndex+1} of ${aiQuizData.length}</div>
        </div>
        <div class="quiz-card">
            <h3 class="quiz-question">${esc(q.question)}</h3>
            <div class="quiz-options" id="aiQuizOptions"></div>
        </div>
        <div id="aiQuizFeedback" class="quiz-feedback" style="display:none"></div>
        <button class="btn-primary" id="aiQuizNextBtn" style="display:none">
            ${aiQuizIndex < aiQuizData.length-1 ? 'Next Question →' : 'See Results'}
        </button>`;

    q.options.forEach((opt, i) => {
        const div = document.createElement('div');
        div.className   = 'quiz-option';
        div.textContent = opt;
        div.addEventListener('click', () => answerAiQuiz(i, q.correct));
        document.getElementById('aiQuizOptions').appendChild(div);
    });

    document.getElementById('aiQuizNextBtn').addEventListener('click', () => {
        aiQuizIndex++;
        if (aiQuizIndex < aiQuizData.length) renderAiQuestion();
        else showAiResults();
    });
}

function answerAiQuiz(sel, correct) {
    const opts = document.querySelectorAll('#aiQuizOptions .quiz-option');
    opts.forEach(o => { o.classList.add('disabled'); o.style.pointerEvents = 'none'; });
    opts[sel].classList.add(sel === correct ? 'correct' : 'incorrect');
    if (sel !== correct) opts[correct].classList.add('correct');
    if (sel === correct) aiQuizScore++;
    const fb = document.getElementById('aiQuizFeedback');
    fb.className     = 'quiz-feedback ' + (sel === correct ? 'correct' : 'incorrect');
    fb.textContent   = sel === correct ? '✓ Correct!' : '✗ Incorrect — right answer highlighted.';
    fb.style.display = 'block';
    document.getElementById('aiQuizNextBtn').style.display = 'block';
}

function showAiResults() {
    document.getElementById('aiQuizQuestions').innerHTML = '';
    const pct = Math.round((aiQuizScore / aiQuizData.length) * 100);
    document.getElementById('aiQuizScore').textContent  = pct;
    document.getElementById('aiQuizResults').style.display = 'block';
    // Award XP via the global progressData if available
    if (typeof progressData !== 'undefined' && progressData) {
        progressData.total_xp += aiQuizScore * 15;
        if (typeof saveProgress === 'function') saveProgress();
        if (typeof updateDashboard === 'function') updateDashboard();
    }
}

// ─── Mark Answer ──────────────────────────────────────────────────────────────
function initMark() {
    document.getElementById('markSetSelect').addEventListener('change', () => {
        populateCardSelect('markSetSelect', 'markCardSelect');
    });
    document.getElementById('markBtn').addEventListener('click', runMark);
}

async function runMark() {
    const setId   = document.getElementById('markSetSelect').value;
    const cardIdx = parseInt(document.getElementById('markCardSelect').value);
    const student = document.getElementById('markStudentAnswer').value.trim();
    const set     = aiSets.find(s => s.id === setId);
    if (!set || isNaN(cardIdx)) return;
    if (!student) { alert('Write your answer first!'); return; }

    const card        = set.cards[cardIdx];
    const result      = document.getElementById('markResult');
    const placeholder = document.getElementById('markPlaceholder');
    const btn         = document.getElementById('markBtn');

    placeholder.style.display = 'none';
    result.style.display      = 'block';
    result.innerHTML          = loadingHTML('Marking…');
    btn.disabled              = true;
    setThinking(true);

    const prompt = `Mark this GCSE ${set.subject} answer.\n`+
        `Question: ${card.question}\nModel answer: ${card.answer}\nStudent answer: ${student}\n\n`+
        `Give a mark out of 3 (0=wrong,1=partial,2=mostly,3=fully correct). Then give feedback and a memory tip.\n`+
        `Respond ONLY with JSON: {"mark":2,"feedback":"...","tip":"..."}`;
    try {
        const reply = await rcAIChat(prompt);
        const data  = rcExtractJson(reply);
        const mark   = data.mark ?? 0;
        const colour = mark >= 3 ? 'var(--success)' : mark >= 2 ? '#f59e0b' : 'var(--error)';
        const emoji  = mark >= 3 ? '🎉' : mark >= 2 ? '👍' : mark >= 1 ? '📝' : '❌';
        result.innerHTML = `
            <div class="mark-header">
                <div class="mark-score-ring" style="--ring-color:${colour}">
                    <span class="mark-emoji">${emoji}</span>
                    <span class="mark-fraction">${mark}<span style="font-size:1rem;opacity:.6">/3</span></span>
                </div>
            </div>
            <div class="mark-section">
                <div class="mark-label">📋 Feedback</div>
                <div class="mark-text">${fmt(data.feedback)}</div>
            </div>
            <div class="mark-section">
                <div class="mark-label">💡 Memory tip</div>
                <div class="mark-text">${fmt(data.tip)}</div>
            </div>
            <div class="mark-section">
                <div class="mark-label">✅ Model answer</div>
                <div class="mark-text">${esc(card.answer)}</div>
            </div>`;
    } catch (e) {
        result.innerHTML = errorHTML(e.message);
    }
    btn.disabled = false;
    setThinking(false);
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function fmt(s) {
    return esc(s).replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>').replace(/\n/g,'<br>');
}
function loadingHTML(msg) {
    return `<div class="inline-loading"><div class="inline-spinner"></div><span>${msg}</span></div>`;
}
function errorHTML(msg) {
    return `<div style="color:var(--error);padding:1rem;font-size:.9375rem">❌ ${esc(msg)}</div>`;
}
