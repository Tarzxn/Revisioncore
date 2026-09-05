// ─── State ────────────────────────────────────────────────────────────────────
let progressData          = null;
let allSets               = [];      // all flashcard sets from server
let currentSet            = null;    // the set currently being studied
let currentSubject        = null;    // used by quiz
let flashcards            = [];
let currentFlashcardIndex = 0;
let gotItCount            = 0;
let notSureCount          = 0;
let quizzes               = [];
let currentQuizIndex      = 0;
let quizScore             = 0;
let termDefSep            = ',';
let cardSep               = 'newline';
let fcFilter              = 'all';

// ─── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    initNavigation();
    await loadProgress();
    await loadSets();
    initSetLibrary();
    initNewSetModal();
    initStudyView();
    initQuiz();
});

// ─── Navigation ───────────────────────────────────────────────────────────────
function initNavigation() {
    document.querySelectorAll('.nav-link[data-page]').forEach(link => {
        link.addEventListener('click', e => {
            e.preventDefault();
            switchPage(link.dataset.page);
        });
    });
}

function switchPage(pageId) {
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const link = document.querySelector(`.nav-link[data-page="${pageId}"]`);
    if (link) link.classList.add('active');
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(pageId).classList.add('active');
}

// ─── Progress & Streak ────────────────────────────────────────────────────────
async function loadProgress() {
    try {
        const res = await fetch('/api/progress');
        progressData = await res.json();
    } catch {
        progressData = {
            subjects: {
                biology:   { score: 0, quizzes_completed: 0, cards_mastered: 0 },
                chemistry: { score: 0, quizzes_completed: 0, cards_mastered: 0 },
                physics:   { score: 0, quizzes_completed: 0, cards_mastered: 0 },
                maths:     { score: 0, quizzes_completed: 0, cards_mastered: 0 }
            },
            total_xp: 0, streak: 0, last_active: ''
        };
    }
    checkStreak();
    updateDashboard();
}

async function saveProgress() {
    if (!progressData) return;
    try {
        await fetch('/api/progress', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(progressData)
        });
    } catch (e) { console.error('Save failed', e); }
}

function checkStreak() {
    const today = new Date().toISOString().split('T')[0];
    const last  = progressData.last_active || '';
    if (!last) {
        progressData.streak = 1;
        progressData.last_active = today;
        saveProgress();
        return;
    }
    if (last === today) return;
    const diff = Math.round((new Date(today) - new Date(last)) / 86400000);
    progressData.streak      = diff === 1 ? progressData.streak + 1 : 1;
    progressData.last_active = today;
    saveProgress();
}

function recordActivity() {
    const today = new Date().toISOString().split('T')[0];
    if (progressData && progressData.last_active !== today) checkStreak();
}

function updateDashboard() {
    if (!progressData) return;
    document.getElementById('totalXP').textContent      = progressData.total_xp;
    document.getElementById('streakCount').textContent   = progressData.streak;
    document.getElementById('currentStreak').textContent = progressData.streak;

    let totalQuizzes = 0, totalCards = 0, scoreSum = 0, scoredSubs = 0;
    for (const sub in progressData.subjects) {
        const d = progressData.subjects[sub];
        totalQuizzes += d.quizzes_completed;
        totalCards   += d.cards_mastered;
        if (d.quizzes_completed > 0) { scoreSum += d.score; scoredSubs++; }
    }
    document.getElementById('totalQuizzes').textContent = totalQuizzes;
    document.getElementById('totalCards').textContent   = totalCards;
    document.getElementById('avgScore').textContent     =
        scoredSubs > 0 ? Math.round(scoreSum / scoredSubs) + '%' : '0%';

    const icons = { biology:'🧬', chemistry:'⚗️', physics:'⚛️', maths:'📐', computer_science:'💻',
                     english:'📖', history:'🏛️', geography:'🌍', french:'🇫🇷', spanish:'🇪🇸', german:'🇩🇪' };
    const wrap  = document.getElementById('subjectProgress');
    wrap.innerHTML = '';
    for (const sub in progressData.subjects) {
        const d   = progressData.subjects[sub];
        const pct = d.quizzes_completed > 0 ? d.score : 0;
        const el  = document.createElement('div');
        el.className = 'subject-card';
        el.dataset.subject = sub;
        el.innerHTML = `
            <h4>${icons[sub] || '📚'} ${sub[0].toUpperCase() + sub.slice(1)}</h4>
            <p>Score: ${d.score}% &nbsp;|&nbsp; Quizzes: ${d.quizzes_completed} &nbsp;|&nbsp; Cards mastered: ${d.cards_mastered}</p>
            <div class="subject-progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
            <div class="progress-info"><span>Progress</span><span>${pct}%</span></div>`;
        wrap.appendChild(el);
    }
}

// ─── Sets Library ─────────────────────────────────────────────────────────────
async function loadSets() {
    try {
        const res = await fetch('/api/sets');
        allSets = await res.json();
    } catch { allSets = []; }
}

function initSetLibrary() {
    // Subject page tiles → go to flashcards filtered by subject
    document.querySelectorAll('.subject-tile').forEach(tile => {
        tile.addEventListener('click', () => {
            switchPage('flashcards');
            setFcFilter(tile.dataset.subject);
        });
    });

    // Filter tabs
    document.querySelectorAll('#fcFilterTabs .filter-tab').forEach(tab => {
        tab.addEventListener('click', () => setFcFilter(tab.dataset.filter));
    });

    renderSetsList();
}

function setFcFilter(filter) {
    fcFilter = filter;
    document.querySelectorAll('#fcFilterTabs .filter-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.filter === filter);
    });
    renderSetsList();
}

function renderSetsList() {
    const list  = document.getElementById('setsList');
    const empty = document.getElementById('setsEmpty');
    const icons = { biology:'🧬', chemistry:'⚗️', physics:'⚛️', maths:'📐', general:'📚' };

    const filtered = fcFilter === 'all' ? allSets : allSets.filter(s => s.subject === fcFilter);

    list.innerHTML = '';
    if (filtered.length === 0) {
        empty.style.display = 'block';
        return;
    }
    empty.style.display = 'none';

    filtered.forEach(set => {
        const card = document.createElement('div');
        card.className = 'guide-card';
        card.innerHTML = `
            <div class="guide-icon">${icons[set.subject] || '📚'}</div>
            <div class="guide-name">${esc(set.name)}</div>
            <span class="guide-subject-tag">${set.subject}</span>
            <div class="set-card-count">${set.cards.length} card${set.cards.length !== 1 ? 's' : ''}</div>
            <div class="guide-actions" style="margin-top:0.75rem">
                <button class="guide-btn" onclick="openSet('${set.id}')">📖 Study</button>
                <button class="guide-btn danger" onclick="deleteSet('${set.id}')">🗑️</button>
            </div>`;
        list.appendChild(card);
    });
}

async function deleteSet(setId) {
    if (!confirm('Delete this set and all its cards?')) return;
    await fetch(`/api/sets/${setId}`, { method: 'DELETE' });
    await loadSets();
    renderSetsList();
}

function openSet(setId) {
    currentSet = allSets.find(s => s.id === setId);
    if (!currentSet) return;
    window.currentSet     = currentSet;   // expose for learn.js
    flashcards            = currentSet.cards;
    currentFlashcardIndex = 0;
    gotItCount            = 0;
    notSureCount          = 0;

    document.getElementById('setsLibrary').style.display  = 'none';
    document.getElementById('studyView').style.display    = 'block';
    document.getElementById('learnView').style.display    = 'none';
    document.getElementById('learnComplete').style.display = 'none';
    document.getElementById('studySetName').textContent    = currentSet.name;
    document.getElementById('studySetSubject').textContent = currentSet.subject;

    renderCard();
}

window.openSet   = openSet;
window.deleteSet = deleteSet;

// ─── New Set Modal ────────────────────────────────────────────────────────────
function initNewSetModal() {
    const modal    = document.getElementById('newSetModal');
    const openBtn  = document.getElementById('newSetBtn');
    const closeBtn = document.getElementById('closeNewSet');

    openBtn.addEventListener('click', () => {
        resetNewSetModal();
        modal.style.display = 'block';
    });
    closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    window.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none'; });

    // Separator buttons
    document.querySelectorAll('#termDefSepOptions .sep-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#termDefSepOptions .sep-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            termDefSep = btn.dataset.sep;
            refreshPreview();
        });
    });

    document.querySelectorAll('#cardSepOptions .sep-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#cardSepOptions .sep-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            cardSep = btn.dataset.sep;
            refreshPreview();
        });
    });

    document.getElementById('importText').addEventListener('input', refreshPreview);
    document.getElementById('previewCardsBtn').addEventListener('click', refreshPreview);
    document.getElementById('saveImportedCards').addEventListener('click', saveNewSet);
}

function resetNewSetModal() {
    document.getElementById('setName').value    = '';
    document.getElementById('importText').value = '';
    document.getElementById('cardPreview').classList.remove('visible');
    document.getElementById('cardPreview').style.display = 'none';
    document.getElementById('previewPlaceholder').style.display = 'flex';
    document.getElementById('previewList').innerHTML = '';
    termDefSep = ',';
    cardSep    = 'newline';
    document.querySelectorAll('#termDefSepOptions .sep-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
    document.querySelectorAll('#cardSepOptions .sep-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
    window._parsedCards = [];
}

function parseCards() {
    const raw = document.getElementById('importText').value.trim();
    if (!raw) return [];

    let chunks;
    if      (cardSep === 'newline') chunks = raw.split(/\r?\n/);
    else if (cardSep === '||')      chunks = raw.split('||');
    else                            chunks = raw.split('|');

    const sep = termDefSep === 'TAB' ? '\t' : termDefSep;

    const results = [];
    for (let chunk of chunks) {
        chunk = chunk.trim();
        if (!chunk) continue;
        const idx = chunk.indexOf(sep);
        if (idx === -1) continue;
        const term = chunk.slice(0, idx).trim();
        const def  = chunk.slice(idx + sep.length).trim();
        if (term && def) results.push({ question: term, answer: def });
    }
    return results;
}

function refreshPreview() {
    const cards       = parseCards();
    const preview     = document.getElementById('cardPreview');
    const placeholder = document.getElementById('previewPlaceholder');

    if (cards.length === 0) {
        preview.style.display     = 'none';
        placeholder.style.display = 'flex';
        return;
    }

    placeholder.style.display = 'none';
    preview.style.display     = 'flex';

    document.getElementById('previewCount').textContent = cards.length;
    const list = document.getElementById('previewList');
    list.innerHTML = '';
    cards.forEach(card => {
        const div = document.createElement('div');
        div.className = 'preview-card';
        div.innerHTML =
            `<div class="preview-term"><div class="preview-label">Term</div>${esc(card.question)}</div>` +
            `<div class="preview-def"><div class="preview-label">Definition</div>${esc(card.answer)}</div>`;
        list.appendChild(div);
    });
    window._parsedCards = cards;
}

async function saveNewSet() {
    const name    = document.getElementById('setName').value.trim();
    const subject = document.getElementById('setSubject').value;
    const cards   = window._parsedCards || [];

    if (!name)            { alert('Please enter a set name.'); document.getElementById('setName').focus(); return; }
    if (cards.length === 0) { alert('No cards to save — paste some text and click Preview first.'); return; }

    const res  = await fetch('/api/sets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, subject, cards })
    });
    const data = await res.json();

    if (data.status === 'success') {
        document.getElementById('newSetModal').style.display = 'none';
        await loadSets();
        renderSetsList();
        // Auto-open the new set
        openSet(data.set.id);
    }
}

// ─── Study View ───────────────────────────────────────────────────────────────
function initStudyView() {
    document.getElementById('backToSets').addEventListener('click', () => {
        document.getElementById('studyView').style.display    = 'none';
        document.getElementById('learnView').style.display    = 'none';
        document.getElementById('learnComplete').style.display = 'none';
        document.getElementById('setsLibrary').style.display  = 'block';
        currentSet = null;
        window.currentSet = null;
    });

    document.getElementById('flashcard').addEventListener('click', () => {
        document.getElementById('flashcard').classList.toggle('flipped');
    });

    document.getElementById('prevCard').addEventListener('click', e => {
        e.stopPropagation();
        if (currentFlashcardIndex > 0) { currentFlashcardIndex--; renderCard(); }
    });

    document.getElementById('nextCard').addEventListener('click', e => {
        e.stopPropagation();
        if (currentFlashcardIndex < flashcards.length - 1) { currentFlashcardIndex++; renderCard(); }
    });

    document.getElementById('markKnown').addEventListener('click', e => {
        e.stopPropagation();
        if (!progressData || flashcards.length === 0) return;
        gotItCount++;
        progressData.total_xp += 10;
        const sub = currentSet ? currentSet.subject : 'biology';
        if (progressData.subjects[sub]) progressData.subjects[sub].cards_mastered++;
        recordActivity();
        saveProgress();
        updateDashboard();
        updateStudyCounters();

        if (currentFlashcardIndex < flashcards.length - 1) {
            currentFlashcardIndex++;
            renderCard();
        } else {
            progressData.total_xp += 50;
            saveProgress();
            updateDashboard();
            showDeckComplete();
        }
    });

    document.getElementById('markUnsure').addEventListener('click', e => {
        e.stopPropagation();
        if (flashcards.length === 0) return;
        notSureCount++;
        updateStudyCounters();
        if (currentFlashcardIndex < flashcards.length - 1) { currentFlashcardIndex++; renderCard(); }
    });
}

function renderCard() {
    if (flashcards.length === 0) return;
    const card = flashcards[currentFlashcardIndex];
    document.getElementById('cardQuestion').textContent = card.question;
    document.getElementById('cardAnswer').textContent   = card.answer;
    document.getElementById('cardCurrent').textContent  = currentFlashcardIndex + 1;
    document.getElementById('cardTotal').textContent    = flashcards.length;
    document.getElementById('studyCardCount').textContent = `${flashcards.length} card${flashcards.length !== 1 ? 's' : ''}`;
    document.getElementById('flashcard').classList.remove('flipped');
    updateStudyCounters();
}

function updateStudyCounters() {
    const done = gotItCount + notSureCount;
    const pct  = flashcards.length > 0 ? Math.round((done / flashcards.length) * 100) : 0;
    document.getElementById('fcProgressFill').style.width = pct + '%';
    document.getElementById('gotItCount').textContent     = gotItCount;
    document.getElementById('notSureCount').textContent   = notSureCount;
}

function showDeckComplete() {
    const pct = flashcards.length > 0 ? Math.round((gotItCount / flashcards.length) * 100) : 0;
    alert(`🎉 Deck complete!\n✓ Got it: ${gotItCount}  ✗ Not sure: ${notSureCount}\nScore: ${pct}%\n+50 bonus XP!`);
}

// ─── Quiz ─────────────────────────────────────────────────────────────────────
function initQuiz() {
    document.querySelectorAll('#quizSubjectSelect .subject-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#quizSubjectSelect .subject-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            startQuiz(btn.dataset.subject);
        });
    });

    document.getElementById('quizNext').addEventListener('click', () => {
        currentQuizIndex++;
        if (currentQuizIndex < quizzes.length) renderQuestion();
        else showQuizResults();
    });

    document.getElementById('retakeQuiz').addEventListener('click', () => {
        document.getElementById('quizResults').style.display   = 'none';
        document.getElementById('quizEmpty').style.display     = 'block';
        document.getElementById('quizContainer').style.display = 'none';
        document.querySelectorAll('#quizSubjectSelect .subject-btn').forEach(b => b.classList.remove('active'));
    });
}

async function startQuiz(subject) {
    currentSubject   = subject;
    currentQuizIndex = 0;
    quizScore        = 0;
    try {
        const res = await fetch(`/api/quizzes/${subject}`);
        quizzes = await res.json();
    } catch { quizzes = []; }
    if (quizzes.length === 0) { alert('No quiz questions found for this subject.'); return; }
    document.getElementById('quizEmpty').style.display     = 'none';
    document.getElementById('quizResults').style.display   = 'none';
    document.getElementById('quizContainer').style.display = 'block';
    renderQuestion();
}

function renderQuestion() {
    const q   = quizzes[currentQuizIndex];
    const pct = ((currentQuizIndex + 1) / quizzes.length) * 100;
    document.getElementById('quizProgressBar').style.width = pct + '%';
    document.getElementById('quizCurrent').textContent     = currentQuizIndex + 1;
    document.getElementById('quizTotal').textContent       = quizzes.length;
    document.getElementById('quizQuestion').textContent    = q.question;
    document.getElementById('quizFeedback').style.display  = 'none';
    document.getElementById('quizNext').style.display      = 'none';
    const opts = document.getElementById('quizOptions');
    opts.innerHTML = '';
    q.options.forEach((opt, i) => {
        const div = document.createElement('div');
        div.className   = 'quiz-option';
        div.textContent = opt;
        div.addEventListener('click', () => answerQuestion(i));
        opts.appendChild(div);
    });
}

function answerQuestion(selected) {
    if (!progressData) return;
    const q       = quizzes[currentQuizIndex];
    const options = document.querySelectorAll('.quiz-option');
    const correct = selected === q.correct;
    options.forEach(o => { o.classList.add('disabled'); o.style.pointerEvents = 'none'; });
    options[selected].classList.add(correct ? 'correct' : 'incorrect');
    if (!correct) options[q.correct].classList.add('correct');
    progressData.total_xp += correct ? 15 : 5;
    if (correct) quizScore++;
    const fb = document.getElementById('quizFeedback');
    fb.className     = 'quiz-feedback ' + (correct ? 'correct' : 'incorrect');
    fb.textContent   = correct ? '✓ Correct! Well done!' : '✗ Incorrect — the right answer is highlighted.';
    fb.style.display = 'block';
    document.getElementById('quizNext').style.display = 'block';
}

function showQuizResults() {
    if (!progressData) return;
    document.getElementById('quizContainer').style.display = 'none';
    document.getElementById('quizResults').style.display   = 'block';
    const pct    = Math.round((quizScore / quizzes.length) * 100);
    const bonus  = pct === 100 ? 50 : pct >= 80 ? 25 : 0;
    const earned = quizScore * 15 + (quizzes.length - quizScore) * 5 + bonus;
    document.getElementById('finalScore').textContent   = pct;
    document.getElementById('correctCount').textContent = quizScore;
    document.getElementById('totalCount').textContent   = quizzes.length;
    document.getElementById('xpEarned').textContent     = earned;
    if (progressData.subjects[currentSubject]) {
        progressData.subjects[currentSubject].quizzes_completed++;
        progressData.subjects[currentSubject].score = pct;
    }
    progressData.total_xp += bonus;
    recordActivity();
    saveProgress();
    updateDashboard();
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function esc(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─── AI Features ──────────────────────────────────────────────────────────────

// Check Ollama status on load
async function checkOllamaStatus() {
    const el = document.getElementById('ollamaStatus');
    if (!el) return;
    try {
        const res  = await fetch('/api/ai/status');
        const data = await res.json();
        if (data.online) {
            const modelList = data.models.join(', ') || 'unknown';
            el.textContent  = `✅ Ollama online — ${modelList}`;
            el.className    = 'ollama-status online';
        } else {
            el.textContent = '❌ Ollama offline — run: ollama serve';
            el.className   = 'ollama-status offline';
        }
    } catch {
        el.textContent = '❌ Ollama offline — run: ollama serve';
        el.className   = 'ollama-status offline';
    }
}

// Initialise AI buttons in study view
function initAIButtons() {
    document.getElementById('studyExplainBtn').addEventListener('click', runExplain);
    document.getElementById('writtenModeBtn').addEventListener('click', openWrittenMode);
    document.getElementById('generateQuizBtn').addEventListener('click', runGenerateQuiz);
    document.getElementById('submitWritten').addEventListener('click', runMarkAnswer);
}

window.closePanel = function(id) {
    document.getElementById(id).style.display = 'none';
};

// ── Explain ───────────────────────────────────────────────────────────────────
async function runExplain() {
    if (!currentSet || flashcards.length === 0) return;
    const card    = flashcards[currentFlashcardIndex];
    const panel   = document.getElementById('explainPanel');
    const textEl  = document.getElementById('explainText');
    panel.style.display = 'block';
    textEl.innerHTML    = '<span class="ai-thinking">🤖 Thinking...</span>';

    const prompt = `You are a clear and friendly GCSE tutor for ${currentSet.subject}. `+
        `Explain this concept simply for a GCSE student:\n\nTerm: ${card.question}\nDefinition: ${card.answer}\n\n`+
        `Give a clear 2-4 sentence explanation then one real-world example. Use plain English, no bullet points.`;
    try {
        await rcAIChat(prompt, { stream: true, onChunk: text => { textEl.innerHTML = rcFormatAI(text); } });
    } catch (e) {
        textEl.textContent = '❌ ' + e.message;
    }
}

// ── Written Mode ──────────────────────────────────────────────────────────────
function openWrittenMode() {
    if (!currentSet || flashcards.length === 0) return;
    const card  = flashcards[currentFlashcardIndex];
    const panel = document.getElementById('writtenPanel');
    document.getElementById('writtenQuestion').textContent = card.question;
    document.getElementById('writtenAnswer').value         = '';
    document.getElementById('writtenFeedback').style.display = 'none';
    panel.style.display = 'block';
    document.getElementById('writtenAnswer').focus();
}

async function runMarkAnswer() {
    if (!currentSet) return;
    const card          = flashcards[currentFlashcardIndex];
    const studentAnswer = document.getElementById('writtenAnswer').value.trim();
    if (!studentAnswer) { alert('Write an answer first!'); return; }

    const feedbackEl = document.getElementById('writtenFeedback');
    feedbackEl.style.display = 'block';
    feedbackEl.innerHTML     = '<span class="ai-thinking">🤖 Marking your answer...</span>';

    const prompt = `You are a GCSE examiner marking a ${currentSet.subject} answer.\n`+
        `Question: ${card.question}\nModel answer: ${card.answer}\nStudent answer: ${studentAnswer}\n\n`+
        `Give a mark out of 3 (0=wrong,1=partial,2=mostly,3=fully correct). Then give feedback and a memory tip.`;
    try {
        await rcAIChat(prompt, { stream: true, onChunk: text => { feedbackEl.innerHTML = rcFormatAI(text); } });
    } catch (e) {
        feedbackEl.textContent = '❌ ' + e.message;
    }
}

// ── Generate Quiz ─────────────────────────────────────────────────────────────
async function runGenerateQuiz() {
    if (!currentSet || currentSet.cards.length === 0) return;
    const panel  = document.getElementById('genQuizPanel');
    const body   = document.getElementById('genQuizBody');
    panel.style.display = 'block';
    body.innerHTML      = '<span class="ai-thinking">⚡ Generating quiz from your set — this takes a few seconds...</span>';

    const facts  = currentSet.cards.map(c => `- ${c.question}: ${c.answer}`).join('\n');
    const prompt = `Create exactly 5 multiple choice questions for a GCSE ${currentSet.subject} student.\n`+
        `Use ONLY these facts:\n${facts}\n\nRespond with ONLY a JSON array:\n`+
        `[{"question":"...","options":["...","...","...","..."],"correct":0}]`;
    try {
        const reply = await rcAIChat(prompt);
        const questions = rcExtractJson(reply);
        renderInlineQuiz(questions, body);
    } catch (e) {
        body.innerHTML = `<p style="color:var(--error)">❌ ${e.message}</p>`;
    }
}

function renderInlineQuiz(questions, container) {
    let score = 0, answered = 0;
    container.innerHTML = '';

    questions.forEach((q, qi) => {
        const div = document.createElement('div');
        div.className = 'inline-quiz-q';
        div.innerHTML = `<p class="inline-q-text"><strong>Q${qi+1}:</strong> ${esc(q.question)}</p>
            <div class="inline-q-opts">${q.options.map((o, oi) =>
                `<button class="inline-opt" data-qi="${qi}" data-oi="${oi}" data-correct="${q.correct}">${esc(o)}</button>`
            ).join('')}</div>
            <div class="inline-q-feedback" id="iqf-${qi}" style="display:none"></div>`;
        container.appendChild(div);
    });

    const scoreEl = document.createElement('div');
    scoreEl.className = 'inline-quiz-score';
    scoreEl.style.display = 'none';
    scoreEl.id = 'inlineScore';
    container.appendChild(scoreEl);

    container.querySelectorAll('.inline-opt').forEach(btn => {
        btn.addEventListener('click', () => {
            const qi      = parseInt(btn.dataset.qi);
            const oi      = parseInt(btn.dataset.oi);
            const correct = parseInt(btn.dataset.correct);
            const fb      = document.getElementById(`iqf-${qi}`);

            // Disable all options in this question
            container.querySelectorAll(`.inline-opt[data-qi="${qi}"]`).forEach(b => {
                b.disabled = true;
                if (parseInt(b.dataset.oi) === correct) b.classList.add('correct');
                else if (b === btn) b.classList.add('incorrect');
            });

            fb.style.display = 'block';
            if (oi === correct) {
                fb.textContent = '✓ Correct!';
                fb.className   = 'inline-q-feedback correct';
                score++;
            } else {
                fb.textContent = `✗ The answer was: ${esc(questions[qi].options[correct])}`;
                fb.className   = 'inline-q-feedback incorrect';
            }

            answered++;
            if (answered === questions.length) {
                const pct = Math.round((score / questions.length) * 100);
                scoreEl.style.display = 'block';
                scoreEl.innerHTML = `<strong>Score: ${score}/${questions.length} (${pct}%)</strong>`;
                if (progressData) {
                    progressData.total_xp += score * 15;
                    saveProgress();
                    updateDashboard();
                }
            }
        });
    });
}

// ── AI Tutor ──────────────────────────────────────────────────────────────────
let tutorMessages  = [];
let tutorSubject   = 'biology';
let tutorStreaming  = false;

function initTutor() {
    checkOllamaStatus();

    // Subject buttons
    document.querySelectorAll('#aitutor .subject-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#aitutor .subject-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            tutorSubject = btn.dataset.subject;
            updateTutorChips(tutorSubject);
        });
    });

    // Send button
    document.getElementById('tutorSend').addEventListener('click', sendTutorMessage);

    // Enter key sends (Shift+Enter = newline)
    document.getElementById('tutorInput').addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTutorMessage(); }
    });

    // Auto-grow textarea
    document.getElementById('tutorInput').addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 140) + 'px';
    });
}

function updateTutorChips(subject) {
    const chips = {
        biology:   ['Explain the cell cycle','What is natural selection?','How does the heart work?','Difference between mitosis and meiosis'],
        chemistry: ['What is a covalent bond?','Explain oxidation and reduction','How do catalysts work?','What is the mole concept?'],
        physics:   ['Explain Newton\'s three laws','What is electromagnetic induction?','How does a transformer work?','Explain wave-particle duality'],
        maths:     ['How do I solve quadratics?','Explain differentiation simply','What are surds?','How do I do algebraic fractions?'],
        general:   ['Help me make a revision plan','What are the best revision techniques?','How do I reduce exam stress?','Explain spaced repetition']
    };
    const list = chips[subject] || chips.general;
    document.getElementById('tutorChips').innerHTML = list
        .map(c => `<button class="chip" onclick="sendChip(this)">${c}</button>`)
        .join('');
}

window.sendChip = function(btn) {
    document.getElementById('tutorInput').value = btn.textContent;
    sendTutorMessage();
};

async function sendTutorMessage() {
    if (tutorStreaming) return;
    const input = document.getElementById('tutorInput');
    const text  = input.value.trim();
    if (!text) return;

    input.value      = '';
    input.style.height = 'auto';
    tutorStreaming   = true;

    // Add user bubble
    tutorMessages.push({ role: 'user', content: text });
    appendChatBubble('user', text);

    // Add empty tutor bubble for streaming
    const tutorBubble = appendChatBubble('tutor', '');
    const bubbleText  = tutorBubble.querySelector('.chat-bubble');
    bubbleText.innerHTML = '<span class="ai-thinking">🤖 Thinking...</span>';

    let context = `You are RevisionCore AI, a friendly GCSE ${tutorSubject} tutor. `+
        `Give clear, helpful answers. Use examples. Keep focused on studying.\n\n`;
    tutorMessages.slice(-8).forEach(m => { context += `${m.role === 'user' ? 'Student' : 'Tutor'}: ${m.content}\n`; });

    try {
        let full = '';
        await rcAIChat(context, { stream: true, onChunk: text => {
            full = text;
            bubbleText.innerHTML = rcFormatAI(text);
            const chat = document.getElementById('tutorChat');
            if (chat) chat.scrollTop = chat.scrollHeight;
        }});
        tutorMessages.push({ role: 'assistant', content: full });
        rcAttachDownloadButtons(tutorBubble, { title: () => `Tutor answer — ${tutorSubject}`, getText: () => full });
    } catch (e) {
        bubbleText.textContent = '❌ ' + e.message;
    }

    tutorStreaming = false;
}

function appendChatBubble(role, text) {
    const chat = document.getElementById('tutorChat');
    const div  = document.createElement('div');
    div.className = `chat-msg ${role}`;
    div.innerHTML = `<div class="chat-bubble">${esc(text)}</div>`;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
}

// ── Markdown-ish formatting for streamed AI text ────────────────────────────
function rcFormatAI(full) {
    return full
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

// ── Hook init calls into DOMContentLoaded ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initAIButtons();
    initTutor();
});
