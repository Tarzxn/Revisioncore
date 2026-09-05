// ─── AI Settings page ─────────────────────────────────────────────────────────
let currentSettings = {};

document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    initProviderToggle();
    initOllamaSettings();
    initGeminiSettings();
    // Also refresh status when navigating to settings page
    document.querySelector('[data-page="settings"]')?.addEventListener('click', () => {
        setTimeout(refreshSettingsStatus, 300);
    });
});

// ─── Load settings from server ────────────────────────────────────────────────
async function loadSettings() {
    try {
        const res  = await fetch('/api/settings');
        currentSettings = await res.json();
    } catch {
        currentSettings = { provider: 'ollama', openrouter_model: 'google/gemini-2.0-flash-exp:free-exp:free', ollama_model: 'llama3.2' };
    }
    applySettings();
    refreshSettingsStatus();
}

function applySettings() {
    const s = currentSettings;

    // Provider buttons
    document.querySelectorAll('.provider-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.provider === s.provider);
    });

    // Show/hide panels
    document.getElementById('ollamaSettings').style.display = s.provider === 'ollama' ? 'block' : 'none';
    document.getElementById('openrouterSettings').style.display = s.provider === 'openrouter' ? 'block' : 'none';
    document.getElementById('openrouterGuide').style.display    = s.provider === 'openrouter' ? 'block' : 'none';

    // Ollama model input
    const ollamaInput = document.getElementById('ollamaModelInput');
    if (ollamaInput) ollamaInput.value = s.ollama_model || 'llama3.2';

    // Gemini key status
    const keyStatus = document.getElementById('keyStatus');
    if (keyStatus) {
        if (s.openrouter_key_set) {
            keyStatus.innerHTML = `<span class="key-set">🔑 Key saved: ${s.openrouter_key_preview}</span>`;
        } else {
            keyStatus.innerHTML = '<span class="key-unset">No API key saved yet</span>';
        }
    }

    // Build Gemini model grid
    buildModelGrid(s.openrouter_model, s.openrouter_models || {});
}

// ─── Status pill (top right of settings page) ─────────────────────────────────
async function refreshSettingsStatus() {
    const pill = document.getElementById('settingsStatusPill');
    const dot  = document.getElementById('settingsStatusDot');
    const txt  = document.getElementById('settingsStatusText');
    if (!pill) return;

    pill.className = 'ai-status-pill ai-status-checking';
    if (dot) dot.className = 'ai-status-dot dot-checking';
    if (txt) txt.textContent = 'Checking…';

    try {
        const res  = await fetch('/api/ai/status');
        const data = await res.json();
        if (data.running) {
            pill.className = 'ai-status-pill ai-status-online';
            if (dot) dot.className = 'ai-status-dot dot-online';
            const providerLabel = data.provider === 'openrouter' ? `🌐 OpenRouter — ${data.model}` : `🟢 Ollama — ${data.model}`;
            if (txt) txt.textContent = providerLabel;
        } else {
            pill.className = 'ai-status-pill ai-status-offline';
            if (dot) dot.className = 'ai-status-dot dot-offline';
            if (txt) txt.textContent = `🔴 ${data.error || 'Offline'}`;
        }
    } catch {
        pill.className = 'ai-status-pill ai-status-offline';
        if (txt) txt.textContent = '🔴 Cannot reach server';
    }

    // Also update the main AI page pill
    if (typeof checkAiStatus === 'function') checkAiStatus();
}

// ─── Provider toggle ──────────────────────────────────────────────────────────
function initProviderToggle() {
    document.querySelectorAll('.provider-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const provider = btn.dataset.provider;
            currentSettings.provider = provider;

            document.querySelectorAll('.provider-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            document.getElementById('ollamaSettings').style.display = provider === 'ollama' ? 'block' : 'none';
            document.getElementById('openrouterSettings').style.display = provider === 'openrouter' ? 'block' : 'none';
            document.getElementById('openrouterGuide').style.display    = provider === 'openrouter' ? 'block' : 'none';

            // Save provider choice immediately
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider })
            });
            refreshSettingsStatus();
        });
    });
}

// ─── Ollama settings ──────────────────────────────────────────────────────────
function initOllamaSettings() {
    document.getElementById('saveOllamaBtn')?.addEventListener('click', async () => {
        const model  = document.getElementById('ollamaModelInput').value.trim() || 'llama3.2';
        const box    = document.getElementById('ollamaStatusBox');
        const btn    = document.getElementById('saveOllamaBtn');

        btn.textContent = 'Saving…';
        btn.disabled    = true;
        setStatusBox(box, 'loading', 'Testing connection to Ollama…');

        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: 'ollama', ollama_model: model })
        });

        // Test it
        try {
            const res  = await fetch('/api/ai/status');
            const data = await res.json();
            if (data.running) {
                setStatusBox(box, 'success', `✅ Connected! Model: ${model}`);
            } else {
                setStatusBox(box, 'error', `❌ ${data.error || 'Ollama not running'}`);
            }
        } catch {
            setStatusBox(box, 'error', '❌ Could not reach the server');
        }

        btn.textContent = 'Save';
        btn.disabled    = false;
        currentSettings.ollama_model = model;
        refreshSettingsStatus();
    });
}

// ─── Gemini settings ──────────────────────────────────────────────────────────
function initGeminiSettings() {
    // Show/hide key
    document.getElementById('toggleKeyVisibility')?.addEventListener('click', () => {
        const input = document.getElementById('openrouterKeyInput');
        input.type  = input.type === 'password' ? 'text' : 'password';
    });

    // Save & test
    document.getElementById('saveOpenRouterBtn')?.addEventListener('click', saveAndTestOpenRouter);

    // Clear key
    document.getElementById('clearOpenRouterKeyBtn')?.addEventListener('click', async () => {
        if (!confirm('Remove your saved Gemini API key?')) return;
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ clear_openrouter_key: true })
        });
        document.getElementById('openrouterKeyInput').value = '';
        document.getElementById('keyStatus').innerHTML  = '<span class="key-unset">Key cleared</span>';
        setStatusBox(document.getElementById('openrouterStatusBox'), '', '');
        await loadSettings();
    });
}

async function saveAndTestOpenRouter() {
    const keyInput = document.getElementById('openrouterKeyInput');
    const key      = keyInput.value.trim();
    const box      = document.getElementById('openrouterStatusBox');
    const btn      = document.getElementById('saveOpenRouterBtn');

    const selectedModel = document.querySelector('.model-card.active')?.dataset.model
                       || currentSettings.openrouter_model
                       || 'gemini-2.0-flash';

    // If no new key typed and one already saved, just save model change
    if (!key && !currentSettings.openrouter_key_set) {
        setStatusBox(box, 'error', '❌ Please paste your Gemini API key first');
        return;
    }

    btn.textContent = 'Testing…';
    btn.disabled    = true;
    setStatusBox(box, 'loading', '⏳ Testing your API key…');

    const payload = { provider: 'gemini', openrouter_model: selectedModel };
    if (key) payload.openrouter_key = key;

    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    try {
        const res  = await fetch('/api/ai/status');
        const data = await res.json();
        if (data.running) {
            setStatusBox(box, 'success', `✅ Gemini connected! Model: ${selectedModel}`);
            if (key) {
                const preview = key.length > 10 ? `${key.slice(0,6)}…${key.slice(-4)}` : '(set)';
                document.getElementById('keyStatus').innerHTML = `<span class="key-set">🔑 Key saved: ${preview}</span>`;
                keyInput.value = '';
            }
            currentSettings.openrouter_key_set  = true;
            currentSettings.openrouter_model    = selectedModel;
        } else {
            setStatusBox(box, 'error', `❌ ${data.error || 'Connection failed — check your API key'}`);
        }
    } catch {
        setStatusBox(box, 'error', '❌ Could not test — server error');
    }

    btn.textContent = 'Save & Test';
    btn.disabled    = false;
    refreshSettingsStatus();
}

function buildModelGrid(selectedModel, models) {
    const grid = document.getElementById('openrouterModelGrid');
    if (!grid) return;

    const recommended = 'gemini-2.0-flash';
    grid.innerHTML = '';

    for (const [id, label] of Object.entries(models)) {
        const [name, desc] = label.split(' (');
        const card = document.createElement('div');
        card.className   = 'model-card' + (id === selectedModel ? ' active' : '');
        card.dataset.model = id;
        card.innerHTML = `
            <div class="model-card-name">${name}${id === recommended ? ' <span class="model-rec">Recommended</span>' : ''}</div>
            <div class="model-card-desc">${desc ? desc.replace(')','') : ''}</div>`;
        card.addEventListener('click', () => {
            grid.querySelectorAll('.model-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
        });
        grid.appendChild(card);
    }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function setStatusBox(box, type, msg) {
    if (!box) return;
    if (!msg) { box.innerHTML = ''; box.className = 'settings-status-box'; return; }
    box.className   = `settings-status-box status-${type}`;
    box.textContent = msg;
}
