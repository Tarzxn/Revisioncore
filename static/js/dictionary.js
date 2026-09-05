// ─── Dictionary lookup (English / Spanish / French / German) ──────────────────
// Uses the free, keyless dictionaryapi.dev endpoint, which supports several
// language codes via the URL path — no API key or backend involved.

document.addEventListener('DOMContentLoaded', () => {
    const input   = document.getElementById('dictInput');
    const langSel = document.getElementById('dictLang');
    const btn     = document.getElementById('dictSearchBtn');
    const results  = document.getElementById('dictResults');
    if (!btn) return;

    async function lookup() {
        const word = input.value.trim();
        const lang = langSel.value;
        if (!word) return;
        results.innerHTML = '<div class="dict-loading">Looking up…</div>';
        try {
            const res = await fetch(`https://api.dictionaryapi.dev/api/v2/entries/${lang}/${encodeURIComponent(word)}`);
            if (!res.ok) {
                results.innerHTML = `<div class="dict-empty">No definition found for "${escapeHtml(word)}".</div>`;
                return;
            }
            const data = await res.json();
            renderResults(data);
        } catch {
            results.innerHTML = '<div class="dict-empty">Lookup failed — check your connection and try again.</div>';
        }
    }

    function renderResults(entries) {
        results.innerHTML = '';
        entries.forEach(entry => {
            const card = document.createElement('div');
            card.className = 'dict-entry-card';
            const phonetic = entry.phonetic || (entry.phonetics || []).map(p => p.text).find(Boolean) || '';
            let html = `<h3>${escapeHtml(entry.word)} ${phonetic ? `<span class="dict-phonetic">${escapeHtml(phonetic)}</span>` : ''}</h3>`;
            (entry.meanings || []).forEach(meaning => {
                html += `<div class="dict-meaning"><span class="dict-pos">${escapeHtml(meaning.partOfSpeech || '')}</span>`;
                html += '<ol class="dict-defs">';
                (meaning.definitions || []).slice(0, 4).forEach(d => {
                    html += `<li>${escapeHtml(d.definition)}${d.example ? `<div class="dict-example">"${escapeHtml(d.example)}"</div>` : ''}</li>`;
                });
                html += '</ol></div>';
            });
            card.innerHTML = html;
            results.appendChild(card);
        });
    }

    function escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    btn.addEventListener('click', lookup);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') lookup(); });
});
