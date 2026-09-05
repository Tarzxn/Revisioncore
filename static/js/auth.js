// ─── Login / account creation ──────────────────────────────────────────────
// Accounts are stored server-side (SQLite) via session cookies, so a user's
// flashcards, guides, progress and streak follow them to any device once
// they log in — separate from the per-device subject choice in onboarding.js.

let rcAuthMode = 'login'; // 'login' | 'register'

document.addEventListener('DOMContentLoaded', () => {
    const overlay     = document.getElementById('authOverlay');
    const form         = document.getElementById('authForm');
    const title        = document.getElementById('authTitle');
    const sub          = document.getElementById('authSub');
    const emailField   = document.getElementById('authEmail');
    const errorBox     = document.getElementById('authError');
    const submitBtn    = document.getElementById('authSubmitBtn');
    const toggleText   = document.getElementById('authToggleText');
    const toggleLink   = document.getElementById('authToggleLink');

    function setMode(mode) {
        rcAuthMode = mode;
        errorBox.textContent = '';
        if (mode === 'register') {
            title.textContent = 'Create your account';
            sub.textContent   = 'One free account — use it to log in from any device.';
            emailField.style.display = 'block';
            submitBtn.textContent = 'Create Account';
            toggleText.textContent = 'Already have an account?';
            toggleLink.textContent = 'Sign in';
        } else {
            title.textContent = 'Sign in to RevisionCore';
            sub.textContent   = 'Your flashcards, guides and progress are saved to your account.';
            emailField.style.display = 'none';
            submitBtn.textContent = 'Sign In';
            toggleText.textContent = "Don't have an account?";
            toggleLink.textContent = 'Create one';
        }
    }

    toggleLink.addEventListener('click', e => {
        e.preventDefault();
        setMode(rcAuthMode === 'login' ? 'register' : 'login');
    });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        errorBox.textContent = '';
        submitBtn.disabled = true;
        const username = document.getElementById('authUsername').value.trim();
        const password = document.getElementById('authPassword').value;
        const email    = document.getElementById('authEmail').value.trim();
        const endpoint = rcAuthMode === 'login' ? '/api/auth/login' : '/api/auth/register';
        try {
            const res  = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, email })
            });
            const data = await res.json();
            if (!res.ok) {
                errorBox.textContent = data.error || 'Something went wrong.';
                submitBtn.disabled = false;
                return;
            }
            // Fresh reload so every page script re-fetches with the new session cookie.
            window.location.reload();
        } catch {
            errorBox.textContent = 'Could not reach the server. Please try again.';
            submitBtn.disabled = false;
        }
    });

    async function checkAuth() {
        try {
            const res = await fetch('/api/auth/me');
            if (res.ok) {
                overlay.classList.remove('active');
                if (window.rcInitOnboarding) window.rcInitOnboarding();
            } else {
                overlay.classList.add('active');
            }
        } catch {
            overlay.classList.add('active');
        }
    }

    checkAuth();
});

async function rcLogout() {
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.reload();
}
