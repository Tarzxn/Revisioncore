// ─── First-open subject picker ─────────────────────────────────────────────
// The chosen subjects are stored in this browser's localStorage only, so the
// choice is specific to this device. Opening RevisionCore on another device
// (or another browser profile) has no saved selection and starts fresh —
// this also means separate people using their own device/browser each get
// their own independent selection, with no accounts needed.

const RC_STORAGE_KEY = 'rc_selected_subjects';

const RC_SUBJECTS = [
    { id: 'biology',          name: 'Biology',          icon: '🧬', desc: 'Cells, DNA & life processes' },
    { id: 'chemistry',        name: 'Chemistry',        icon: '⚗️', desc: 'Elements & reactions' },
    { id: 'physics',          name: 'Physics',          icon: '⚛️', desc: 'Forces, energy & motion' },
    { id: 'maths',            name: 'Maths',             icon: '📐', desc: 'Algebra & geometry' },
    { id: 'computer_science', name: 'Computer Science', icon: '💻', desc: 'Algorithms & programming' },
    { id: 'english',          name: 'English',          icon: '📖', desc: 'Literature & language' },
    { id: 'history',          name: 'History',          icon: '🏛️', desc: 'Key events & eras' },
    { id: 'geography',        name: 'Geography',        icon: '🌍', desc: 'Places, climate & maps' },
    { id: 'french',           name: 'French',           icon: '🇫🇷', desc: 'Vocabulary & grammar' },
    { id: 'spanish',          name: 'Spanish',          icon: '🇪🇸', desc: 'Vocabulary & grammar' },
    { id: 'german',           name: 'German',           icon: '🇩🇪', desc: 'Vocabulary & grammar' }
];

function rcGetSelectedSubjects() {
    try {
        const raw = localStorage.getItem(RC_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) && parsed.length ? parsed : null;
    } catch {
        return null;
    }
}

function rcSaveSelectedSubjects(ids) {
    localStorage.setItem(RC_STORAGE_KEY, JSON.stringify(ids));
}

// ── Rendering the picker (used both for first-run onboarding and for
//    editing the choice later via "My Subjects") ────────────────────────────
function rcRenderSubjectPicker(container, startBtn, preselected) {
    const selected = new Set(preselected || []);
    container.innerHTML = '';

    RC_SUBJECTS.forEach(sub => {
        const tile = document.createElement('div');
        tile.className = 'onboarding-subject-tile' + (selected.has(sub.id) ? ' selected' : '');
        tile.dataset.subject = sub.id;
        tile.innerHTML = `
            <div class="subject-icon">${sub.icon}</div>
            <div class="subject-name">${sub.name}</div>`;
        tile.addEventListener('click', () => {
            if (selected.has(sub.id)) {
                selected.delete(sub.id);
                tile.classList.remove('selected');
            } else {
                selected.add(sub.id);
                tile.classList.add('selected');
            }
            startBtn.disabled = selected.size === 0;
        });
        container.appendChild(tile);
    });

    startBtn.disabled = selected.size === 0;
    return selected;
}

// ── Filtering the app UI down to only the chosen subjects ──────────────────
function rcApplySubjectFilter() {
    const selected = rcGetSelectedSubjects();
    if (!selected) return; // nothing chosen yet (shouldn't happen once onboarded)
    const allowed = new Set(selected);

    document.querySelectorAll('.subject-tile[data-subject]').forEach(el => {
        el.style.display = allowed.has(el.dataset.subject) ? '' : 'none';
    });
    document.querySelectorAll('#quizSubjectSelect .subject-btn[data-subject]').forEach(el => {
        el.style.display = allowed.has(el.dataset.subject) ? '' : 'none';
    });
    document.querySelectorAll('#subjectProgress .subject-card[data-subject]').forEach(el => {
        el.style.display = allowed.has(el.dataset.subject) ? '' : 'none';
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const overlay  = document.getElementById('onboardingOverlay');
    const grid     = document.getElementById('onboardingSubjects');
    const startBtn = document.getElementById('onboardingStartBtn');
    const changeLink = document.getElementById('changeSubjectsLink');

    let currentSelection = null;

    function openPicker(existing) {
        currentSelection = rcRenderSubjectPicker(grid, startBtn, existing);
        overlay.classList.add('active');
    }

    function closePicker() {
        overlay.classList.remove('active');
    }

    startBtn.addEventListener('click', () => {
        if (currentSelection.size === 0) return;
        rcSaveSelectedSubjects(Array.from(currentSelection));
        closePicker();
        rcApplySubjectFilter();
    });

    changeLink.addEventListener('click', e => {
        e.preventDefault();
        openPicker(rcGetSelectedSubjects() || []);
    });

    // Called by auth.js once the user is confirmed logged in.
    window.rcInitOnboarding = function () {
        const saved = rcGetSelectedSubjects();
        if (!saved) {
            openPicker([]);
        } else {
            rcApplySubjectFilter();
        }
    };

    // subjectProgress is rebuilt dynamically by app.js on every load/update,
    // so re-apply the filter whenever its contents change.
    const progressWrap = document.getElementById('subjectProgress');
    if (progressWrap) {
        new MutationObserver(() => rcApplySubjectFilter()).observe(progressWrap, { childList: true });
    }
});
