// ─── Shared AI helper — always routed through Puter.js ─────────────────────
// No backend AI calls, no API keys: puter.ai.chat() runs entirely client-side
// (the user's free Puter account covers usage). Works on localhost and Render
// identically since it's just a CDN script talking to Puter's own servers.

async function rcAIReady() {
    // Puter.js attaches window.puter asynchronously after the script tag loads.
    for (let i = 0; i < 50; i++) {
        if (window.puter && window.puter.ai) return true;
        await new Promise(r => setTimeout(r, 100));
    }
    return false;
}

async function rcAIChat(prompt, opts = {}) {
    const { stream = false, onChunk } = opts;
    const ready = await rcAIReady();
    if (!ready) throw new Error('Puter.js did not load — check your internet connection.');

    if (stream) {
        const response = await puter.ai.chat(prompt, { stream: true });
        let full = '';
        for await (const part of response) {
            if (part?.text) {
                full += part.text;
                if (onChunk) onChunk(full);
            }
        }
        return full;
    }

    const response = await puter.ai.chat(prompt);
    if (typeof response === 'string') return response;
    return response?.message?.content || response?.text || String(response);
}

// Extracts the first valid JSON array/object substring from a model reply.
function rcExtractJson(text) {
    const arrStart = text.indexOf('['), objStart = text.indexOf('{');
    let start, endChar;
    if (arrStart !== -1 && (objStart === -1 || arrStart < objStart)) { start = arrStart; endChar = ']'; }
    else { start = objStart; endChar = '}'; }
    if (start === -1) throw new Error('No JSON found in AI response');
    const end = text.lastIndexOf(endChar);
    return JSON.parse(text.slice(start, end + 1));
}
