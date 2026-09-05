// ─── Learn Mode ───────────────────────────────────────────────────────────────
// Quizlet-style adaptive learning:
//   Phase 1: first 5 terms → multiple choice
//   Phase 2: first 5 terms → write out
//   ...batch 2 (terms 6-10), ...
//   Every ~5 questions: review a random older term
//   Mastered = correct twice in a row; unmasters if wrong
//   After all mastered: infinite random review mode

(function () {
    'use strict';

    // ── State ────────────────────────────────────────────────────────────────
    let learnCards    = [];     // shuffled copy of the set's cards
    let cardState     = [];     /* [{card, streak, totalCorrect, totalAttempts,
                                      mastered, inBatch}] */
    let batchSize     = 5;
    let currentBatch  = 0;      // index: 0 = terms 0-4, 1 = terms 5-9, …
    let batchPhase    = 'mc';   // 'mc' | 'write'
    let batchQueue    = [];     // ordered questions for current phase
    let reviewMode    = false;  // infinite random review after all mastered
    let totalMastered = 0;

    // Current question
    let currentQ       = null;  // {cardIdx, type:'mc'|'write', isReview}
    let answered       = false;

    // Stats
    let sessionCorrect = 0;
    let sessionTotal   = 0;
    let startTime      = null;

    // ── Helpers ──────────────────────────────────────────────────────────────
    function shuffle(arr) {
        const a = [...arr];
        for (let i = a.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [a[i], a[j]] = [a[j], a[i]];
        }
        return a;
    }

    function esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function normalise(s) {
        return s.trim().toLowerCase()
            .replace(/["""'']/g, '')
            .replace(/[.,!?;:]/g, '')
            .replace(/\s+/g, ' ');
    }

    function isClose(a, b) {
        // Levenshtein distance ≤ 2 for short answers, ≤ 3 for longer
        const na = normalise(a), nb = normalise(b);
        if (na === nb) return true;
        const limit = nb.length <= 6 ? 1 : nb.length <= 12 ? 2 : 3;
        return levenshtein(na, nb) <= limit;
    }

    function levenshtein(a, b) {
        if (Math.abs(a.length - b.length) > 4) return 99;
        const m = a.length, n = b.length;
        const dp = Array.from({length: m + 1}, (_, i) => [i]);
        for (let j = 0; j <= n; j++) dp[0][j] = j;
        for (let i = 1; i <= m; i++)
            for (let j = 1; j <= n; j++)
                dp[i][j] = a[i-1] === b[j-1]
                    ? dp[i-1][j-1]
                    : 1 + Math.min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]);
        return dp[m][n];
    }

    // ── Init (called from openSet) ────────────────────────────────────────────
    function startLearn(set) {
        if (!set || set.cards.length < 2) {
            alert('You need at least 2 cards to use Learn mode.');
            return;
        }

        learnCards = shuffle([...set.cards]);
        cardState  = learnCards.map(card => ({
            card,
            streak:        0,
            totalCorrect:  0,
            totalAttempts: 0,
            mastered:      false,
            inBatch:       false,
        }));

        currentBatch  = 0;
        batchPhase    = 'mc';
        reviewMode    = false;
        totalMastered = 0;
        sessionCorrect = 0;
        sessionTotal   = 0;
        startTime      = Date.now();

        // Show learn view
        const fc = document.getElementById('flashcards');
        document.getElementById('studyView').style.display    = 'none';
        document.getElementById('learnView').style.display    = 'block';
        document.getElementById('learnComplete').style.display = 'none';
        document.getElementById('learnSetName').textContent    = set.name;

        // Mark first batch
        markBatch(currentBatch);
        batchPhase = 'mc';
        buildBatchQueue();
        updateProgress();
        nextQuestion();
    }

    function markBatch(batchIdx) {
        const start = batchIdx * batchSize;
        const end   = Math.min(start + batchSize, cardState.length);
        for (let i = start; i < end; i++) {
            cardState[i].inBatch = true;
        }
    }

    // ── Build queue ──────────────────────────────────────────────────────────
    function buildBatchQueue() {
        const start = currentBatch * batchSize;
        const end   = Math.min(start + batchSize, cardState.length);

        // Collect unmastered cards in current batch (for this phase)
        let indices = [];
        for (let i = start; i < end; i++) {
            if (!cardState[i].mastered) indices.push(i);
        }
        indices = shuffle(indices);

        // Build questions
        batchQueue = indices.map(idx => ({
            cardIdx:  idx,
            type:     batchPhase,
            isReview: false,
        }));

        // Sprinkle in review of mastered/older terms every ~5 questions
        if (batchPhase === 'write') {
            const masteredBefore = cardState
                .slice(0, start)
                .map((s, i) => i)
                .filter(i => cardState[i].totalCorrect > 0);

            if (masteredBefore.length > 0) {
                const reviewCount = Math.max(1, Math.floor(batchQueue.length / 5));
                const picks = shuffle(masteredBefore).slice(0, reviewCount);
                picks.forEach((idx, pos) => {
                    // Insert review question every 4-5 real questions
                    const insertAt = Math.min((pos + 1) * 4, batchQueue.length);
                    batchQueue.splice(insertAt, 0, {
                        cardIdx:  idx,
                        type:     'write',
                        isReview: true,
                    });
                });
            }
        }
    }

    // ── Next question ─────────────────────────────────────────────────────────
    function nextQuestion() {
        answered = false;

        // Hide feedback
        document.getElementById('learnFeedback').style.display = 'none';
        document.getElementById('learnCard').classList.remove('correct', 'incorrect');

        // Review mode: random card from all
        if (reviewMode) {
            serveReviewQuestion();
            return;
        }

        // Dequeue
        if (batchQueue.length === 0) {
            advanceBatchOrPhase();
            return;
        }

        currentQ = batchQueue.shift();
        renderQuestion(currentQ);
        updateProgress();
    }

    function advanceBatchOrPhase() {
        // Check if any unmastered in current batch
        const start = currentBatch * batchSize;
        const end   = Math.min(start + batchSize, cardState.length);
        const unmastered = [];
        for (let i = start; i < end; i++) {
            if (!cardState[i].mastered) unmastered.push(i);
        }

        if (batchPhase === 'mc') {
            // Move to write phase for same batch
            batchPhase = 'write';
            buildBatchQueue();
            nextQuestion();
            return;
        }

        // Write phase done — check if all in batch are mastered
        if (unmastered.length > 0) {
            // Retry unmastered in write phase
            batchPhase = 'write';
            buildBatchQueue();
            // Only queue unmastered
            batchQueue = batchQueue.filter(q => !cardState[q.cardIdx].mastered);
            if (batchQueue.length === 0) {
                advanceToNextBatch();
            } else {
                nextQuestion();
            }
            return;
        }

        advanceToNextBatch();
    }

    function advanceToNextBatch() {
        // Check all mastered globally
        const allMastered = cardState.every(s => s.mastered);
        if (allMastered) {
            showComplete(false);
            return;
        }

        currentBatch++;
        const start = currentBatch * batchSize;
        if (start >= cardState.length) {
            // Wrap — re-queue unmastered
            currentBatch = 0;
        }

        markBatch(currentBatch);
        batchPhase = 'mc';
        buildBatchQueue();

        // Filter already mastered from MC phase
        batchQueue = batchQueue.filter(q => !cardState[q.cardIdx].mastered);
        if (batchQueue.length === 0) {
            batchPhase = 'write';
            buildBatchQueue();
            batchQueue = batchQueue.filter(q => !cardState[q.cardIdx].mastered);
        }

        if (batchQueue.length === 0) {
            showComplete(false);
            return;
        }

        nextQuestion();
    }

    function serveReviewQuestion() {
        // Pick a random card, bias toward less-recently-correct
        const allIdx = cardState.map((_, i) => i);
        const pick   = shuffle(allIdx)[0];
        currentQ = {
            cardIdx:  pick,
            type:     'write',
            isReview: true,
        };
        renderQuestion(currentQ);
        updateProgress();
    }

    // ── Render question ───────────────────────────────────────────────────────
    function renderQuestion(q) {
        const { cardIdx, type, isReview } = q;
        const state = cardState[cardIdx];
        const card  = state.card;

        const typeEl = document.getElementById('learnQType');
        const textEl = document.getElementById('learnQText');

        const batchStart = currentBatch * batchSize + 1;
        const batchEnd   = Math.min((currentBatch + 1) * batchSize, cardState.length);
        const phaseLabel = reviewMode
            ? '🔄 Review mode'
            : isReview
                ? '🔁 Revisiting earlier term'
                : batchPhase === 'mc'
                    ? `📚 Batch ${currentBatch + 1} · Multiple choice`
                    : `✍️ Batch ${currentBatch + 1} · Write it out`;

        document.getElementById('learnPhaseLabel').textContent = phaseLabel;

        // Always ask: "What is the definition of [term]?"
        // Randomly flip term/definition for variety
        const askForDef = true; // always show term, ask for definition

        typeEl.textContent = 'What is the definition of:';
        textEl.textContent = card.question;

        if (type === 'mc') {
            showMC(cardIdx, card);
        } else {
            showWrite(cardIdx, card);
        }
    }

    function showMC(cardIdx, card) {
        document.getElementById('learnMCOptions').style.display  = 'grid';
        document.getElementById('learnWriteArea').style.display  = 'none';

        // Pick 3 distractors
        const otherIndices = cardState
            .map((_, i) => i)
            .filter(i => i !== cardIdx);
        const picks = shuffle(otherIndices).slice(0, 3);
        const options = shuffle([
            { text: card.answer, correct: true },
            ...picks.map(i => ({ text: cardState[i].card.answer, correct: false })),
        ]);

        const container = document.getElementById('learnMCOptions');
        container.innerHTML = '';
        options.forEach(opt => {
            const btn = document.createElement('button');
            btn.className = 'learn-mc-btn';
            btn.textContent = opt.text;
            btn.dataset.correct = opt.correct;
            btn.addEventListener('click', () => handleMCAnswer(btn, opt.correct, card.answer));
            container.appendChild(btn);
        });
    }

    function showWrite(cardIdx, card) {
        document.getElementById('learnMCOptions').style.display  = 'none';
        document.getElementById('learnWriteArea').style.display  = 'block';

        const input = document.getElementById('learnWriteInput');
        input.value = '';
        input.className = 'learn-write-input';
        input.disabled = false;
        input.focus();

        // Enter key submits
        input.onkeydown = (e) => {
            if (e.key === 'Enter' && !answered) {
                e.preventDefault();
                handleWriteSubmit();
            }
        };
    }

    // ── Handle answers ────────────────────────────────────────────────────────
    function handleMCAnswer(btn, correct, correctAnswer) {
        if (answered) return;
        answered = true;
        sessionTotal++;

        const allBtns = document.querySelectorAll('.learn-mc-btn');
        allBtns.forEach(b => {
            b.disabled = true;
            if (b.dataset.correct === 'true') b.classList.add('mc-correct');
        });

        if (correct) {
            btn.classList.add('mc-correct');
            recordResult(currentQ.cardIdx, true);
            showFeedback(true, correctAnswer, false);
        } else {
            btn.classList.add('mc-wrong');
            recordResult(currentQ.cardIdx, false);
            showFeedback(false, correctAnswer, false);
        }
    }

    function handleWriteSubmit() {
        if (answered) return;
        const input = document.getElementById('learnWriteInput');
        const answer = input.value.trim();
        if (!answer) return;

        answered = true;
        sessionTotal++;

        const card    = cardState[currentQ.cardIdx].card;
        const correct = isClose(answer, card.answer);

        input.disabled = true;
        input.classList.add(correct ? 'inp-correct' : 'inp-incorrect');

        recordResult(currentQ.cardIdx, correct);
        showFeedback(correct, card.answer, !correct);
    }

    function showFeedback(correct, correctAnswer, showOverride) {
        const fbEl     = document.getElementById('learnFeedback');
        const statusEl = document.getElementById('learnFeedbackStatus');
        const correctEl = document.getElementById('learnFeedbackCorrect');
        const overrideBtn = document.getElementById('learnOverrideBtn');

        fbEl.style.display = 'block';

        if (correct) {
            statusEl.textContent = '✓ Correct!';
            statusEl.className   = 'learn-feedback-status fb-correct';
            correctEl.textContent = '';
            document.getElementById('learnCard').classList.add('correct');
        } else {
            statusEl.textContent = '✗ Not quite';
            statusEl.className   = 'learn-feedback-status fb-wrong';
            correctEl.innerHTML  = `<strong>Correct answer:</strong> ${esc(correctAnswer)}`;
            document.getElementById('learnCard').classList.add('incorrect');
        }

        overrideBtn.style.display = showOverride ? 'inline-block' : 'none';
        sessionCorrect += correct ? 1 : 0;
    }

    function recordResult(cardIdx, correct) {
        const state = cardState[cardIdx];
        state.totalAttempts++;
        if (correct) {
            state.streak++;
            state.totalCorrect++;
            if (state.streak >= 2 && !state.mastered) {
                state.mastered = true;
                totalMastered++;
            }
        } else {
            state.streak = 0;
            // Un-master if it was mastered and got it wrong
            if (state.mastered) {
                state.mastered = false;
                totalMastered = Math.max(0, totalMastered - 1);
            }
        }
        updateProgress();
    }

    // ── Override (typo) ───────────────────────────────────────────────────────
    function handleOverride() {
        if (!currentQ) return;
        const state = cardState[currentQ.cardIdx];
        // Undo the wrong, record correct
        state.totalAttempts--;
        recordResult(currentQ.cardIdx, true);
        sessionCorrect++;

        document.getElementById('learnFeedbackStatus').textContent = '✓ Marked correct!';
        document.getElementById('learnFeedbackStatus').className   = 'learn-feedback-status fb-correct';
        document.getElementById('learnOverrideBtn').style.display  = 'none';
        document.getElementById('learnCard').classList.remove('incorrect');
        document.getElementById('learnCard').classList.add('correct');

        const input = document.getElementById('learnWriteInput');
        if (input) {
            input.classList.remove('inp-incorrect');
            input.classList.add('inp-correct');
        }
    }

    // ── Progress ─────────────────────────────────────────────────────────────
    function updateProgress() {
        const total    = cardState.length;
        const mastered = cardState.filter(s => s.mastered).length;
        const pct      = total > 0 ? (mastered / total) * 100 : 0;

        document.getElementById('learnProgressFill').style.width = pct + '%';
        document.getElementById('learnProgressText').textContent = `${mastered} / ${total} mastered`;
        document.getElementById('learnProgressLabel').textContent =
            `${mastered}/${total} mastered · ${sessionTotal} answered`;

        // Check if all mastered
        if (!reviewMode && mastered === total && total > 0) {
            showComplete(false);
        }
    }

    // ── Complete / review mode ────────────────────────────────────────────────
    function showComplete(isReviewComplete) {
        document.getElementById('learnView').style.display     = 'none';
        document.getElementById('learnComplete').style.display = 'block';

        const elapsed = Math.round((Date.now() - startTime) / 1000);
        const mins    = Math.floor(elapsed / 60);
        const secs    = elapsed % 60;
        const acc     = sessionTotal > 0 ? Math.round((sessionCorrect / sessionTotal) * 100) : 0;

        document.getElementById('learnCompleteTitle').textContent = '🎉 All Terms Mastered!';
        document.getElementById('learnCompleteSub').textContent   =
            `You've learnt all ${cardState.length} terms in this set.`;

        document.getElementById('learnCompleteStats').innerHTML = `
            <div class="lcs-item">
                <div class="lcs-num">${cardState.length}</div>
                <div class="lcs-label">Terms</div>
            </div>
            <div class="lcs-item">
                <div class="lcs-num">${acc}%</div>
                <div class="lcs-label">Accuracy</div>
            </div>
            <div class="lcs-item">
                <div class="lcs-num">${mins}m ${secs}s</div>
                <div class="lcs-label">Time</div>
            </div>`;
    }

    function startReviewMode() {
        reviewMode = true;

        document.getElementById('learnComplete').style.display = 'none';
        document.getElementById('learnView').style.display     = 'block';
        document.getElementById('learnPhaseLabel').textContent = '🔄 Review mode';

        updateProgress();
        nextQuestion();
    }

    // ── DOM init ─────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        // Launch learn from flashcard study view
        document.getElementById('startLearnBtn').addEventListener('click', () => {
            if (!window.currentSet) return;
            startLearn(window.currentSet);
        });

        // Back from learn to study view
        document.getElementById('backFromLearn').addEventListener('click', () => {
            document.getElementById('learnView').style.display     = 'none';
            document.getElementById('learnComplete').style.display = 'none';
            document.getElementById('studyView').style.display     = 'block';
        });

        // Submit write answer
        document.getElementById('learnSubmitWrite').addEventListener('click', handleWriteSubmit);

        // Continue after feedback
        document.getElementById('learnContinueBtn').addEventListener('click', nextQuestion);

        // Override (I was correct)
        document.getElementById('learnOverrideBtn').addEventListener('click', handleOverride);

        // Keep practising → review mode
        document.getElementById('learnKeepGoingBtn').addEventListener('click', startReviewMode);

        // Done → back to study view
        document.getElementById('learnFinishBtn').addEventListener('click', () => {
            document.getElementById('learnComplete').style.display = 'none';
            document.getElementById('studyView').style.display     = 'block';
        });
    });

    // Expose so app.js openSet can propagate the set reference
    window.startLearn = startLearn;

})();
