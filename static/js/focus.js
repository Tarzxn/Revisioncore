// ─── Focus Room ───────────────────────────────────────────────────────────────
const FOCUS_QUOTES = [
    "The secret of getting ahead is getting started.",
    "You don't have to be great to start, but you have to start to be great.",
    "Small daily improvements are the key to staggering long-term results.",
    "Every expert was once a beginner. Every pro was once an amateur.",
    "The pain of studying is far less than the pain of not knowing.",
    "Your future self is watching you right now through your memories.",
    "Don't stop when you're tired. Stop when you're done.",
    "Discipline is choosing between what you want now and what you want most.",
    "Comfort is the enemy of achievement.",
    "The harder you work now, the easier the exam will feel.",
    "One hour of focused revision beats five hours of distracted studying.",
    "You've already started. That's the hardest part.",
];

const EMERGENCY_MESSAGES = [
    n => `You've already put in ${n} of solid focus. Stopping now means that time gets harder to build on. Just finish this session.`,
    n => `${n} in and you want to quit? The last stretch is where the real learning happens. Push through.`,
    n => `Studies show that stopping before completing a session makes it 40% harder to start the next one. You're so close.`,
    n => `Your brain is literally building pathways right now from ${n} of study. Stopping interrupts that process. Stay with it.`,
    n => `Imagine how good you'll feel in a few minutes when you've finished. That feeling is worth more than whatever is pulling you away.`,
];

// State
let focusDuration    = 25 * 60;  // seconds
let focusRemaining   = 25 * 60;
let focusElapsedSecs = 0;
let focusInterval    = null;
let focusRunning     = false;
let pauseReason      = '';
let resumeCountdownInterval = null;
let focusSubject     = '';
let sessionComplete  = false;

// Storage key
const FOCUS_STATS_KEY = 'rc_focus_stats';

document.addEventListener('DOMContentLoaded', () => {
    initFocusSetup();
    initFocusControls();
    initPauseModal();
    initResumeModal();
    initEmergencyModal();
    loadFocusStats();
    showQuote();
    blockTabSwitch();
});


// ─── Fullscreen ───────────────────────────────────────────────────────────────
function enterFullscreen() {
    const el = document.documentElement;
    const req = el.requestFullscreen || el.webkitRequestFullscreen || el.mozRequestFullScreen || el.msRequestFullscreen;
    if (req) req.call(el).catch(() => {});  // catch: user may deny
}

function exitFullscreen() {
    const exit = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
    if (exit && document.fullscreenElement) exit.call(document).catch(() => {});
}

function isFullscreen() {
    return !!(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement);
}

// ─── Tab lock ─────────────────────────────────────────────────────────────────
function blockTabSwitch() {
    // Fullscreen exit (Esc key / F11) → treat as pause
    const fsEvents = ['fullscreenchange', 'webkitfullscreenchange', 'mozfullscreenchange', 'MSFullscreenChange'];
    fsEvents.forEach(evt => {
        document.addEventListener(evt, () => {
            if (!focusRunning) return;
            if (!isFullscreen()) {
                // User pressed Esc or F11 to exit fullscreen — treat as involuntary pause
                pauseFocus(true);
            }
        });
    });

    // Warn on visibility change (tab switch / minimise)
    document.addEventListener('visibilitychange', () => {
        if (!focusRunning) return;
        if (document.hidden) {
            pauseFocus(true);
        }
    });

    // Warn on beforeunload
    window.addEventListener('beforeunload', e => {
        if (!focusRunning) return;
        e.preventDefault();
        e.returnValue = 'You have an active focus session! Are you sure you want to leave?';
        return e.returnValue;
    });
}

// ─── Setup ────────────────────────────────────────────────────────────────────
function initFocusSetup() {
    document.querySelectorAll('.focus-preset').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.focus-preset').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const customWrap = document.getElementById('customTimeWrap');
            if (btn.dataset.mins === 'custom') {
                customWrap.style.display = 'block';
            } else {
                customWrap.style.display = 'none';
                focusDuration  = parseInt(btn.dataset.mins) * 60;
                focusRemaining = focusDuration;
            }
        });
    });

    document.getElementById('customMins').addEventListener('input', e => {
        const v = Math.max(1, Math.min(240, parseInt(e.target.value) || 25));
        focusDuration  = v * 60;
        focusRemaining = focusDuration;
    });

    document.getElementById('startFocusBtn').addEventListener('click', startFocus);
    document.getElementById('focusAgainBtn').addEventListener('click', resetToSetup);
}

function showQuote() {
    const q = FOCUS_QUOTES[Math.floor(Math.random() * FOCUS_QUOTES.length)];
    const el = document.getElementById('focusQuote');
    if (el) el.textContent = `"${q}"`;
}

// ─── Focus controls ───────────────────────────────────────────────────────────
function initFocusControls() {
    document.getElementById('focusPauseBtn').addEventListener('click', () => pauseFocus(false));
}

function startFocus() {
    focusSubject   = document.getElementById('focusSubjectInput').value.trim() || 'General revision';
    focusRemaining = focusDuration;
    focusElapsedSecs = 0;
    sessionComplete  = false;
    pauseReason      = '';

    document.getElementById('focusSetup').style.display    = 'none';
    document.getElementById('focusComplete').style.display = 'none';
    document.getElementById('focusRoom').style.display     = 'flex';
    document.getElementById('focusRoomSubject').textContent = focusSubject;

    enterFullscreen();
    updateTimerDisplay();
    updateMotivate();
    runFocusTick();
}

function runFocusTick() {
    focusRunning = true;
    // Re-enter fullscreen if they left it during pause
    if (!isFullscreen()) enterFullscreen();
    document.getElementById('focusRoomStatus').textContent = 'Focusing…';
    document.getElementById('focusPauseBtn').textContent   = '⏸ Pause';

    focusInterval = setInterval(() => {
        focusRemaining--;
        focusElapsedSecs++;
        updateTimerDisplay();
        updateMotivate();

        if (focusRemaining <= 0) {
            clearInterval(focusInterval);
            focusRunning = false;
            completeSession();
        }
    }, 1000);
}

function pauseFocus(involuntary = false) {
    if (!focusRunning) return;

    // Stop the clock immediately
    clearInterval(focusInterval);
    focusRunning = false;

    if (involuntary) {
        // They switched tabs — show pause modal immediately
        document.getElementById('focusRoomStatus').textContent = 'Paused — you left the tab';
        showPauseModal('You switched tabs. What were you doing?');
    } else {
        showPauseModal();
    }
}

// ─── Pause modal ──────────────────────────────────────────────────────────────
function initPauseModal() {
    document.getElementById('cancelPauseBtn').addEventListener('click', () => {
        hidePauseModal();
        runFocusTick(); // resume without penalty
    });

    document.getElementById('confirmPauseBtn').addEventListener('click', () => {
        const reason = document.getElementById('pauseReason').value.trim();
        if (!reason) {
            document.getElementById('pauseReason').placeholder = 'Please write a reason before pausing…';
            document.getElementById('pauseReason').style.borderColor = 'var(--error)';
            return;
        }
        pauseReason = reason;
        hidePauseModal();
        showResumeModal();
    });
}

function showPauseModal(placeholder) {
    const el = document.getElementById('pauseReason');
    el.value = '';
    el.style.borderColor = '';
    if (placeholder) el.placeholder = placeholder;
    else el.placeholder = 'e.g. Getting my textbook from downstairs…';
    document.getElementById('pauseModal').style.display = 'flex';
    el.focus();
}

function hidePauseModal() {
    document.getElementById('pauseModal').style.display = 'none';
}

// ─── Resume modal (guilt trip + 10s countdown) ────────────────────────────────
function initResumeModal() {
    document.getElementById('confirmResumeBtn').addEventListener('click', () => {
        if (document.getElementById('confirmResumeBtn').disabled) return;
        clearInterval(resumeCountdownInterval);
        hideResumeModal();
        runFocusTick();
    });
}

function showResumeModal() {
    const elapsed   = fmtSecs(focusElapsedSecs);
    const remaining = fmtSecs(focusRemaining);

    document.getElementById('pauseReasonDisplay').textContent = `"${pauseReason}"`;
    document.getElementById('resumeElapsed').textContent      = elapsed;
    document.getElementById('resumeRemaining').textContent    = remaining;
    document.getElementById('focusRoomStatus').textContent    = 'Paused';

    const resumeBtn = document.getElementById('confirmResumeBtn');
    resumeBtn.disabled    = true;
    resumeBtn.textContent = 'Resume when ready';

    let countdown = 10;
    document.getElementById('resumeCountdown').textContent = countdown;
    document.getElementById('resumeModal').style.display = 'flex';

    resumeCountdownInterval = setInterval(() => {
        countdown--;
        document.getElementById('resumeCountdown').textContent = countdown;
        if (countdown <= 0) {
            clearInterval(resumeCountdownInterval);
            resumeBtn.disabled    = false;
            resumeBtn.textContent = '▶ Resume session';
            document.getElementById('resumeCountdown').textContent = '✓';
            document.querySelector('.resume-countdown-label').textContent = 'You can resume now';
        }
    }, 1000);
}

function hideResumeModal() {
    document.getElementById('resumeModal').style.display = 'none';
}

// ─── Emergency modal ──────────────────────────────────────────────────────────
function initEmergencyModal() {
    document.getElementById('focusEmergencyBtn').addEventListener('click', showEmergencyModal);

    document.getElementById('cancelEmergencyBtn').addEventListener('click', () => {
        hideEmergencyModal();
        // Resume if we were running
        if (!focusRunning && !sessionComplete) runFocusTick();
    });

    document.getElementById('confirmEmergencyBtn').addEventListener('click', () => {
        clearInterval(focusInterval);
        focusRunning = false;
        hideEmergencyModal();
        completeSession(true); // true = emergency stopped
    });
}

function showEmergencyModal() {
    // Pause clock while showing modal
    clearInterval(focusInterval);
    focusRunning = false;

    const elapsedSecs = focusElapsedSecs;
    const elapsed     = fmtSecs(elapsedSecs);
    const remaining   = fmtSecs(focusRemaining);
    const pct         = Math.round((focusElapsedSecs / focusDuration) * 100);

    document.getElementById('emergencyElapsed').textContent   = elapsed;
    document.getElementById('emergencyRemaining').textContent = remaining;
    document.getElementById('emergencyBarFill').style.width   = pct + '%';
    document.getElementById('emergencyPct').textContent       = pct + '% done';

    const msgFn = EMERGENCY_MESSAGES[Math.floor(Math.random() * EMERGENCY_MESSAGES.length)];
    document.getElementById('emergencyMessage').textContent = msgFn(elapsed);

    document.getElementById('emergencyModal').style.display = 'flex';
}

function hideEmergencyModal() {
    document.getElementById('emergencyModal').style.display = 'none';
}

// ─── Complete session ─────────────────────────────────────────────────────────
function completeSession(emergency = false) {
    sessionComplete = true;
    focusRunning    = false;
    clearInterval(focusInterval);

    const secsCompleted = focusElapsedSecs;
    const minsCompleted = Math.round(secsCompleted / 60);
    const xpEarned      = Math.max(10, minsCompleted * 2);

    // Save stats
    saveFocusSession(secsCompleted);

    // Award XP
    if (typeof progressData !== 'undefined' && progressData) {
        progressData.total_xp += xpEarned;
        if (typeof saveProgress === 'function') saveProgress();
        if (typeof updateDashboard === 'function') updateDashboard();
    }

    exitFullscreen();
    document.getElementById('focusRoom').style.display     = 'none';
    document.getElementById('focusSetup').style.display    = 'none';
    document.getElementById('focusComplete').style.display = 'block';

    document.getElementById('completeDuration').textContent = fmtSecs(secsCompleted);
    document.getElementById('completeXP').textContent       = `+${xpEarned}`;

    let msg;
    if (emergency) {
        msg = `You completed ${fmtSecs(secsCompleted)} of focused study. That's still ${minsCompleted} minute${minsCompleted !== 1 ? 's' : ''} of real progress — well done for starting. Next time, try to go the full session!`;
    } else if (minsCompleted >= 45) {
        msg = `Incredible work. ${minsCompleted} minutes of deep focus is a serious revision session. Your brain has been building connections the whole time. Take a proper break — you've earned it.`;
    } else {
        msg = `${minsCompleted} minutes of focused revision done! Consistent short sessions like this are proven to be more effective than marathon unfocused studying. Keep it up!`;
    }
    document.getElementById('focusCompleteMsg').textContent = msg;

    loadFocusStats();
    showQuote();
}

function resetToSetup() {
    document.getElementById('focusComplete').style.display = 'none';
    document.getElementById('focusSetup').style.display    = 'block';
    focusElapsedSecs = 0;
    pauseReason      = '';
}

// ─── Timer display ────────────────────────────────────────────────────────────
function updateTimerDisplay() {
    document.getElementById('focusTimeText').textContent  = fmtSecs(focusRemaining);
    document.getElementById('focusElapsed').textContent   = fmtSecs(focusElapsedSecs);

    // SVG ring
    const circumference = 2 * Math.PI * 88; // r=88
    const progress      = focusRemaining / focusDuration;
    const offset        = circumference * (1 - progress);
    const ring          = document.getElementById('ringProgress');
    if (ring) {
        ring.style.strokeDasharray  = circumference;
        ring.style.strokeDashoffset = offset;
    }
}

const MOTIVATE_MSGS = [
    [0,   0.25, ["You're just getting warmed up. Keep going.", "The hardest part is starting — you're past that now.", "Building momentum…"]],
    [0.25,0.5,  ["You're in the zone now. Don't break it.", "This is where real learning happens.", "Quarter done. You're doing great."]],
    [0.5, 0.75, ["More than halfway there. You've got this.", "The finish line is getting closer.", "Past halfway — the hard part is behind you."]],
    [0.75,0.9,  ["Almost there. Don't stop now.", "You can practically see the end. Push through.", "The last stretch is where champions are made."]],
    [0.9, 1.0,  ["Final push! Don't give up when you're this close.", "Nearly done — this is where it counts.", "So close. Finish strong!"]],
];

function updateMotivate() {
    const progress = focusElapsedSecs / focusDuration;
    const el       = document.getElementById('focusMotivate');
    if (!el) return;
    for (const [min, max, msgs] of MOTIVATE_MSGS) {
        if (progress >= min && progress < max) {
            if (!el._lastRange || el._lastRange !== `${min}-${max}`) {
                el._lastRange  = `${min}-${max}`;
                el.textContent = msgs[Math.floor(Math.random() * msgs.length)];
            }
            return;
        }
    }
}

// ─── Stats storage ────────────────────────────────────────────────────────────
function saveFocusSession(seconds) {
    const stats  = getFocusStats();
    const today  = new Date().toISOString().split('T')[0];

    stats.totalSeconds  = (stats.totalSeconds  || 0) + seconds;
    stats.totalSessions = (stats.totalSessions || 0) + 1;

    if (!stats.days) stats.days = {};
    if (!stats.days[today]) stats.days[today] = { seconds: 0, sessions: 0 };
    stats.days[today].seconds  += seconds;
    stats.days[today].sessions += 1;

    localStorage.setItem(FOCUS_STATS_KEY, JSON.stringify(stats));
}

function getFocusStats() {
    try {
        return JSON.parse(localStorage.getItem(FOCUS_STATS_KEY) || '{}');
    } catch { return {}; }
}

function loadFocusStats() {
    const stats = getFocusStats();
    const today = new Date().toISOString().split('T')[0];
    const todayData = (stats.days || {})[today] || { seconds: 0, sessions: 0 };

    const el1 = document.getElementById('todayFocusTime');
    const el2 = document.getElementById('todaySessionCount');
    const el3 = document.getElementById('totalFocusTime');

    if (el1) el1.textContent = fmtMins(todayData.seconds);
    if (el2) el2.textContent = todayData.sessions;
    if (el3) el3.textContent = fmtMins(stats.totalSeconds || 0);
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmtSecs(secs) {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function fmtMins(secs) {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}
