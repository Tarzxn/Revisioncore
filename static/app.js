const $ = s => document.querySelector(s);
const convo = $('#conversation');
const promptEl = $('#prompt');
const sendBtn = $('#send');
const HERO_HTML = $('#hero') ? $('#hero').outerHTML : '';

// Conversations AND the auth token both live in sessionStorage, never
// localStorage and never a cookie: sessionStorage is wiped the moment the
// tab/browser closes, so nothing is "remembered" past that point, and
// because it's not a cookie the browser never auto-attaches it anywhere —
// every request explicitly carries the token itself.
const CONV_KEY = 'forge.conversations';
const TOKEN_KEY = 'forge.token';

const state = {
  model: 'gpt-oss:20b',
  history: [],
  webSearch: false,
  webSearchAvailable: false,
  power: 'medium',
  conversations: {},
  activeId: null,
  sending: false,
  controller: null,
  token: null,
};

function escapeHtml(t) {
  return String(t).replace(/[&<>'"]/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));
}

// ---- Markdown-lite rendering -----------------------------------------
// Everything is HTML-escaped first, so model output can never inject raw
// HTML. Fenced code blocks are pulled out before escaping (so code content
// is preserved verbatim) and restored, individually escaped, at the end.
function inlineMd(line) {
  let out = line.replace(/`([^`\n]+)`/g, '<code class="inline">$1</code>');
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return out;
}

function renderReply(text) {
  const raw = text || '';
  const codeBlocks = [];
  const withPlaceholders = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    codeBlocks.push(code.replace(/\n$/, ''));
    return `\u0000CODEBLOCK${codeBlocks.length - 1}\u0000`;
  });
  const escaped = escapeHtml(withPlaceholders);
  const lines = escaped.split('\n');

  let html = '', listType = null, paraBuffer = [];
  const flushPara = () => { if (paraBuffer.length) { html += `<p>${paraBuffer.join('<br>')}</p>`; paraBuffer = []; } };
  const closeList = () => { if (listType) { html += `</${listType}>`; listType = null; } };

  for (const line of lines) {
    const codePlaceholder = line.match(/^\u0000CODEBLOCK(\d+)\u0000$/);
    const heading = line.match(/^(#{1,3})\s+(.*)/);
    const bullet = line.match(/^[-*]\s+(.*)/);
    const numbered = line.match(/^\d+\.\s+(.*)/);
    const quote = line.match(/^&gt;\s?(.*)/);
    if (codePlaceholder) {
      // Code blocks are block-level — keep them out of the paragraph buffer
      // so they never end up nested inside a <p> (invalid, and lets the
      // browser silently "fix" the DOM in ways that are harder to reason about).
      flushPara(); closeList();
      html += line;
    } else if (heading) {
      flushPara(); closeList();
      html += `<div class="md-h${heading[1].length}">${inlineMd(heading[2])}</div>`;
    } else if (bullet) {
      flushPara();
      if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; }
      html += `<li>${inlineMd(bullet[1])}</li>`;
    } else if (numbered) {
      flushPara();
      if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; }
      html += `<li>${inlineMd(numbered[1])}</li>`;
    } else if (quote) {
      flushPara(); closeList();
      html += `<blockquote>${inlineMd(quote[1])}</blockquote>`;
    } else if (line.trim() === '') {
      flushPara(); closeList();
    } else {
      closeList();
      paraBuffer.push(inlineMd(line));
    }
  }
  flushPara(); closeList();

  html = html.replace(/\u0000CODEBLOCK(\d+)\u0000/g, (m, i) => `<pre class="glass"><code>${escapeHtml(codeBlocks[i])}</code></pre>`);
  return `<div class="reply-text">${html}</div>`;
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const FILE_ICONS = {
  '.py':'🐍', '.js':'📜', '.ts':'📜', '.html':'🌐', '.css':'🎨', '.json':'🗂️',
  '.csv':'📊', '.md':'📝', '.txt':'📄', '.docx':'📃', '.xlsx':'📊', '.pptx':'📽️',
  '.pdf':'📕', '.stl':'🧊', '.svg':'🖼️', '.png':'🖼️', '.jpg':'🖼️', '.jpeg':'🖼️',
  '.webp':'🖼️', '.gif':'🖼️',
};
function fileIcon(path) {
  const ext = path.slice(path.lastIndexOf('.')).toLowerCase();
  return FILE_ICONS[ext] || '📦';
}

// Keeps each path segment correctly percent-encoded without turning the "/"
// separators between folders into a literal "%2F" (which broke nested-file
// downloads, since Flask's <path:filename> route never saw the real slash).
// Plain <a href> links can't carry an Authorization header, so the auth
// token rides along as a query parameter for these two routes specifically.
function workspaceUrl(base, workspace, path) {
  const segments = path.split('/').map(encodeURIComponent).join('/');
  const sep = base.includes('?') ? '&' : '?';
  return `${base}/${workspace}/${segments}${sep}token=${encodeURIComponent(state.token || '')}`;
}

// Same idea but for the whole-workspace zip route, which has no per-file
// path segment at all.
function workspaceZipUrl(workspace) {
  return `/api/download/${workspace}?token=${encodeURIComponent(state.token || '')}`;
}

function buildArtifactHtml(data) {
  if (!data.files || data.files.length === 0) return '';
  const images = data.files.filter(f => f.isImage);
  const gallery = images.length ? `
    <div class="artifact-gallery">
      ${images.map(f => `
        <a href="${workspaceUrl('/api/preview', data.workspace, f.path)}" target="_blank" rel="noopener">
          <img loading="lazy" src="${workspaceUrl('/api/preview', data.workspace, f.path)}" alt="${escapeHtml(f.path)}">
        </a>`).join('')}
    </div>` : '';
  const rows = data.files.map(f => `
    <li>
      <span class="ficon">${fileIcon(f.path)}</span>
      <span class="fname">${escapeHtml(f.path)}</span>
      <span class="fbytes">${formatBytes(f.bytes)}</span>
      <a href="${workspaceUrl('/api/download', data.workspace, f.path)}" download>Download</a>
    </li>`).join('');
  return `
    <div class="artifact glass">
      ${gallery}
      <div class="artifact-head"><strong>${data.files.length} file${data.files.length === 1 ? '' : 's'} created</strong></div>
      <ul>${rows}</ul>
      <a class="download-all" href="${workspaceZipUrl(data.workspace)}">Download all (.zip) ↓</a>
    </div>`;
}

function add(role, html) {
  const el = document.createElement('div');
  // User bubbles get the full glass treatment; assistant replies stay
  // transparent (only their code blocks/artifact cards are glass panels).
  el.className = `message ${role}${role === 'user' ? ' glass' : ''}`;
  el.innerHTML = html;
  convo.append(el);
  el.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return el;
}

// ---- Per-message chatbot affordances: copy buttons on code blocks, and a
// copy/regenerate toolbar on every assistant reply. ----------------------
function attachCodeCopyButtons(container) {
  container.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.code-copy')) return; // avoid double-attaching during streaming re-renders
    const btn = document.createElement('button');
    btn.className = 'code-copy'; btn.type = 'button'; btn.textContent = 'Copy';
    btn.onclick = () => {
      navigator.clipboard?.writeText(pre.innerText || '');
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = 'Copy'; }, 1200);
    };
    pre.appendChild(btn);
  });
}

function attachMessageTools(container, replyText, msgIndex) {
  const bar = document.createElement('div');
  bar.className = 'msg-tools';
  bar.innerHTML = `<button type="button" class="tool-btn copy-msg">📋 Copy</button><button type="button" class="tool-btn regen-msg">↻ Regenerate</button>`;
  container.appendChild(bar);
  bar.querySelector('.copy-msg').onclick = (e) => {
    navigator.clipboard?.writeText(replyText || '');
    e.target.textContent = 'Copied!';
    setTimeout(() => { e.target.textContent = '📋 Copy'; }, 1200);
  };
  bar.querySelector('.regen-msg').onclick = () => regenerate(msgIndex, container);
}

// ---- Conversation persistence (sessionStorage — cleared when the tab/
// browser closes; nothing about a conversation survives past that). --------
function loadConversations() {
  try { return JSON.parse(sessionStorage.getItem(CONV_KEY)) || {}; }
  catch (e) { return {}; }
}
function saveConversations() {
  try { sessionStorage.setItem(CONV_KEY, JSON.stringify(state.conversations)); }
  catch (e) { /* storage full or unavailable — conversation still works for this page view */ }
}
function newConversationId() { return 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
function titleFor(text) {
  const t = text.trim().replace(/\s+/g, ' ');
  return t.length > 42 ? t.slice(0, 42) + '…' : (t || 'New task');
}

function ensureActiveConversation() {
  if (state.activeId && state.conversations[state.activeId]) return;
  const id = newConversationId();
  state.conversations[id] = { id, title: null, messages: [], updatedAt: Date.now() };
  state.activeId = id;
}

function persistActive() {
  const conv = state.conversations[state.activeId];
  if (!conv) return;
  conv.updatedAt = Date.now();
  saveConversations();
  renderRecentList();
}

function renderRecentList() {
  const container = $('#recent');
  const items = Object.values(state.conversations)
    .filter(c => c.messages.length > 0)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, 30);
  if (!items.length) {
    container.innerHTML = '<button class="history active" disabled>No conversations yet</button>';
    return;
  }
  container.innerHTML = items.map(c => `
    <button class="history${c.id === state.activeId ? ' active' : ''}" data-id="${c.id}">
      <span class="hist-title">${escapeHtml(c.title || 'New task')}</span>
      <span class="hist-del" data-del="${c.id}" title="Delete">×</span>
    </button>`).join('');
  container.querySelectorAll('.history').forEach(btn => btn.addEventListener('click', (e) => {
    if (e.target.closest('[data-del]')) return;
    switchConversation(btn.dataset.id);
  }));
  container.querySelectorAll('[data-del]').forEach(el => el.addEventListener('click', (e) => {
    e.stopPropagation();
    deleteConversation(el.dataset.del);
  }));
}

function redrawConversation() {
  convo.innerHTML = '';
  const conv = state.conversations[state.activeId];
  if (!conv || conv.messages.length === 0) {
    convo.innerHTML = HERO_HTML;
    rebindSuggestions();
    return;
  }
  conv.messages.forEach((m, i) => {
    if (m.role === 'user') {
      add('user', escapeHtml(m.content));
    } else {
      const el = add('assistant', renderReply(m.content) + (m.data ? buildArtifactHtml(m.data) : ''));
      attachCodeCopyButtons(el);
      if (!m.error) attachMessageTools(el, m.content, i);
    }
  });
}

function switchConversation(id) {
  if (id === state.activeId || !state.conversations[id]) return;
  state.activeId = id;
  const conv = state.conversations[id];
  state.history = conv.messages.filter(m => !m.error).map(m => ({ role: m.role, content: m.content }));
  redrawConversation();
  renderRecentList();
}

function deleteConversation(id) {
  delete state.conversations[id];
  saveConversations();
  if (id === state.activeId) {
    const remaining = Object.values(state.conversations).sort((a, b) => b.updatedAt - a.updatedAt);
    if (remaining.length) switchConversation(remaining[0].id);
    else startNewConversation();
  } else {
    renderRecentList();
  }
}

function startNewConversation() {
  state.activeId = null;
  state.history = [];
  redrawConversation();
  renderRecentList();
  promptEl.value = '';
  autoResize();
  promptEl.focus();
}

// ---- Auth ------------------------------------------------------------
// authFetch centralizes attaching the bearer token and reacting to a 401 by
// dropping back to the login screen — every authenticated call in this file
// goes through it instead of calling fetch() directly.
async function authFetch(url, opts = {}) {
  const headers = Object.assign({}, opts.headers, state.token ? { Authorization: `Bearer ${state.token}` } : {});
  const response = await fetch(url, Object.assign({}, opts, { headers }));
  if (response.status === 401) {
    sessionStorage.removeItem(TOKEN_KEY);
    state.token = null;
    showLogin('Your session expired. Please sign in again.');
  }
  return response;
}

function showApp() {
  document.body.classList.remove('logged-out');
  initApp();
}

function showLogin(message) {
  document.body.classList.add('logged-out');
  setAuthMode('login');
  $('#loginError').textContent = message || '';
  $('#loginPassword').value = '';
  setTimeout(() => $('#loginUsername').focus(), 0);
}

// ---- Login / Create account ------------------------------------------
// Two entirely separate <form>s (only one visible at a time), rather than
// one shared form with a conditionally-hidden confirm-password field. That
// used to leave an inert "new-password" field sitting in the DOM even while
// signing in, which is exactly the shape that trips up browser password
// managers into odd autofill/"confirm your password" behavior on login.
function setAuthMode(mode) {
  const signingUp = mode === 'signup';
  $('#loginForm').hidden = signingUp;
  $('#signupForm').hidden = !signingUp;
  $('#loginError').textContent = '';
  $('#signupError').textContent = '';
}

$('#toSignupLink').addEventListener('click', (e) => { e.preventDefault(); setAuthMode('signup'); });
$('#toLoginLink').addEventListener('click', (e) => { e.preventDefault(); setAuthMode('login'); });

$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = $('#loginUsername').value.trim();
  const password = $('#loginPassword').value;
  $('#loginError').textContent = '';
  $('#loginSubmit').disabled = true;
  try {
    const r = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await r.json();
    if (!r.ok) {
      if (r.status === 404) {
        // No accounts exist on this server yet — steer straight to signup instead of a dead-end error.
        setAuthMode('signup');
        $('#signupUsername').value = username;
        $('#signupError').textContent = 'No accounts exist yet — create the first one below.';
        return;
      }
      throw new Error(data.error || 'Sign-in failed.');
    }
    state.token = data.token;
    sessionStorage.setItem(TOKEN_KEY, data.token);
    showApp();
  } catch (err) {
    $('#loginError').textContent = err.message;
  } finally {
    $('#loginSubmit').disabled = false;
  }
});

$('#signupForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = $('#signupUsername').value.trim();
  const password = $('#signupPassword').value;
  $('#signupError').textContent = '';

  if (password !== $('#signupConfirm').value) {
    $('#signupError').textContent = "Passwords don't match.";
    return;
  }
  if (password.length < 8) {
    $('#signupError').textContent = 'Password must be at least 8 characters.';
    return;
  }

  $('#signupSubmit').disabled = true;
  try {
    const r = await fetch('/api/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'Could not create account.');
    state.token = data.token;
    sessionStorage.setItem(TOKEN_KEY, data.token);
    showApp();
  } catch (err) {
    $('#signupError').textContent = err.message;
  } finally {
    $('#signupSubmit').disabled = false;
  }
});

$('#logoutButton').addEventListener('click', async () => {
  try { await authFetch('/api/logout', { method: 'POST' }); } catch (e) { /* best-effort */ }
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(CONV_KEY);
  state.token = null;
  state.conversations = {};
  state.activeId = null;
  state.history = [];
  showLogin();
});

// ---- Config / model list -------------------------------------------------
async function loadConfig() {
  try {
    const res = await authFetch('/api/config');
    const cfg = await res.json();
    state.webSearchAvailable = !!cfg.webSearchEnabled;
    const btn = $('#webSearchToggle');
    btn.disabled = !state.webSearchAvailable;
    btn.title = state.webSearchAvailable ? 'Search the web before answering' : 'Web search needs a TAVILY_API_KEY set on the server';
  } catch (e) { /* leave the toggle disabled if config can't be reached */ }
}

async function loadModels() {
  try {
    const res = await authFetch('/api/models');
    const models = await res.json();
    $('#models').innerHTML = models.map(m => `
      <button class="model-choice" data-id="${escapeHtml(m.id)}" data-name="${escapeHtml(m.name)}">
        <strong>${escapeHtml(m.name)}</strong>
        <small>${escapeHtml(m.family)} · ${escapeHtml(m.tag)}</small>
      </button>`).join('');
    document.querySelectorAll('.model-choice').forEach(b => b.onclick = () => {
      state.model = b.dataset.id;
      $('#modelName').textContent = b.dataset.name;
      $('#modelMenu').classList.remove('open');
    });
  } catch (e) {
    $('#models').textContent = 'Model list unavailable.';
  }
}

function closeMenus() { $('#modelMenu').classList.remove('open'); }

function rebindSuggestions() {
  document.querySelectorAll('.suggestions button').forEach(b => b.onclick = () => {
    promptEl.value = b.textContent;
    autoResize();
    promptEl.focus();
  });
}

function autoResize() {
  promptEl.style.height = 'auto';
  promptEl.style.height = Math.min(promptEl.scrollHeight, 220) + 'px';
}

function setSending(sending) {
  state.sending = sending;
  sendBtn.textContent = sending ? '■' : '↑';
  sendBtn.setAttribute('aria-label', sending ? 'Stop' : 'Send');
  sendBtn.classList.toggle('stopping', sending);
}

function handleComposerAction() {
  if (state.sending) { state.controller?.abort(); return; }
  submitPrompt();
}

// ---- Streaming reader ------------------------------------------------
// Reads the server's newline-delimited JSON event stream (see /api/chat):
// {"type":"delta","text":...} arrives as the reply is generated, ending in
// either {"type":"done",...} or {"type":"error","error":...}.
async function readEventStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (!line) continue;
      try { onEvent(JSON.parse(line)); } catch (e) { /* skip a malformed line rather than aborting the whole stream */ }
    }
  }
  const trailing = buffer.trim();
  if (trailing) {
    try { onEvent(JSON.parse(trailing)); } catch (e) { /* ignore */ }
  }
}

async function askModel(promptText) {
  const conv = state.conversations[state.activeId];
  const pending = add('assistant typing', `<div class="reply-text typing-indicator"><span></span><span></span><span></span></div>${state.webSearch ? '<div class="reply-text" style="opacity:.6;font-size:12px;margin-top:2px">Searching the web, then building…</div>' : ''}`);
  state.controller = new AbortController();
  setSending(true);

  let streamedText = '', thinkingText = '', infoText = '', finalEvent = null, streamError = null;

  // Composes whatever's arrived so far into the pending message: an optional
  // info note (e.g. "auto-using the best model for 3D"), a live/collapsible
  // "Thinking…" trace of the model's own reasoning (this is what "take its
  // time and think before building" looks like from the outside), then the
  // reply text itself (or the typing dots before any of it has arrived).
  function renderPending(open) {
    let html = '';
    if (infoText) html += `<div class="info-note">💡 ${escapeHtml(infoText)}</div>`;
    if (thinkingText) html += `<details class="thinking-trace"${open ? ' open' : ''}><summary>${open ? 'Thinking…' : 'Thinking'}</summary><div class="thinking-body">${escapeHtml(thinkingText)}</div></details>`;
    html += streamedText ? renderReply(streamedText) : (thinkingText || infoText ? '' : '<div class="reply-text typing-indicator"><span></span><span></span><span></span></div>');
    return html;
  }

  // Re-parsing and re-rendering the whole accumulated reply on every single
  // small streamed chunk gets both wasteful (the same markdown gets
  // re-parsed dozens of times a second on a long reply) and visibly janky.
  // Batch updates to at most once per animation frame instead — the closure
  // always picks up whichever text is freshest by the time the frame fires.
  let renderScheduled = false, pendingOpen = false;
  function scheduleRender(open) {
    pendingOpen = open;
    if (renderScheduled) return;
    renderScheduled = true;
    requestAnimationFrame(() => {
      renderScheduled = false;
      pending.innerHTML = renderPending(pendingOpen);
    });
  }

  try {
    const r = await authFetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: promptText, model: state.model, history: state.history, web_search: state.webSearch, power: state.power }),
      signal: state.controller.signal,
    });

    if (r.status === 401) throw new Error('Your session expired. Please sign in again.');

    // A non-streaming, non-JSON body (HTML error page from a proxy/gateway
    // timeout, etc.) should never surface as a raw "Unexpected token '<'".
    const contentType = r.headers.get('content-type') || '';
    if (!contentType.includes('application/x-ndjson')) {
      if (contentType.includes('application/json')) {
        const data = await r.json();
        throw new Error(data.error || 'Request failed');
      }
      const label = r.status === 504 || r.status === 502
        ? 'The server took too long to respond (likely a slow or overloaded model). Try again, or switch to a faster model.'
        : `Server error (HTTP ${r.status}). Try again in a moment.`;
      throw new Error(label);
    }

    await readEventStream(r, (event) => {
      if (event.type === 'info') {
        infoText = event.text;
        pending.classList.remove('typing');
        scheduleRender(true);
      } else if (event.type === 'thinking') {
        thinkingText += event.text;
        pending.classList.remove('typing');
        scheduleRender(true);
      } else if (event.type === 'delta') {
        streamedText += event.text;
        pending.classList.remove('typing');
        scheduleRender(false);
      } else if (event.type === 'done') {
        finalEvent = event;
      } else if (event.type === 'error') {
        streamError = event.error;
      }
    });

    if (streamError) throw new Error(streamError);
    if (!finalEvent) throw new Error('The model stopped responding unexpectedly. Please try again.');

    pending.classList.remove('typing');
    pending.innerHTML = renderPending(false) + buildArtifactHtml(finalEvent);
    attachCodeCopyButtons(pending);
    const msgIndex = conv.messages.length;
    conv.messages.push({ role: 'assistant', content: finalEvent.reply, data: finalEvent });
    attachMessageTools(pending, finalEvent.reply, msgIndex);
    pending.scrollIntoView({ behavior: 'smooth', block: 'end' });

    state.history.push({ role: 'user', content: promptText }, { role: 'assistant', content: finalEvent.reply });
    if (!conv.title) conv.title = titleFor(promptText);
    persistActive();
  } catch (err) {
    pending.classList.remove('typing');
    if (err.name === 'AbortError') {
      // If some text had already streamed in before Stop was pressed, keep it
      // visible rather than discarding useful partial output.
      pending.innerHTML = renderPending(false) + '<div class="reply-text error-text" style="margin-top:6px">Stopped.</div>';
      conv.messages.push({ role: 'assistant', content: streamedText || 'Stopped.', error: !streamedText });
    } else {
      pending.innerHTML = `<span class="error-text">${escapeHtml(err.message)}</span>`;
      conv.messages.push({ role: 'assistant', content: err.message, error: true });
    }
    persistActive();
  } finally {
    setSending(false);
    state.controller = null;
    promptEl.focus();
  }
}

async function submitPrompt() {
  const prompt = promptEl.value.trim();
  if (!prompt) return;
  ensureActiveConversation();
  const conv = state.conversations[state.activeId];

  $('#hero')?.remove();
  add('user', escapeHtml(prompt));
  conv.messages.push({ role: 'user', content: prompt });
  if (!conv.title) conv.title = titleFor(prompt);
  promptEl.value = '';
  autoResize();
  persistActive();

  await askModel(prompt);
}

// Regenerating message at `msgIndex` drops it (and anything after it) and
// re-asks the same preceding user prompt — works on any assistant message,
// not just the latest one.
async function regenerate(msgIndex, containerEl) {
  if (state.sending) return;
  const conv = state.conversations[state.activeId];
  if (!conv) return;
  const userMsg = conv.messages[msgIndex - 1];
  if (!userMsg || userMsg.role !== 'user') return;

  conv.messages = conv.messages.slice(0, msgIndex);
  state.history = conv.messages.filter(m => !m.error).map(m => ({ role: m.role, content: m.content }));

  let node = containerEl;
  while (node && node.nextSibling) node.parentNode.removeChild(node.nextSibling);
  node.remove();

  persistActive();
  await askModel(userMsg.content);
}

// ---- Wiring & init ------------------------------------------------------
$('#modelButton').onclick = (e) => { e.stopPropagation(); $('#modelMenu').classList.toggle('open'); };
$('#modelMenu').onclick = (e) => e.stopPropagation();
$('#webSearchToggle').onclick = () => {
  if ($('#webSearchToggle').disabled) return;
  state.webSearch = !state.webSearch;
  $('#webSearchToggle').classList.toggle('active', state.webSearch);
};
document.querySelectorAll('.power-option').forEach(btn => btn.addEventListener('click', () => {
  state.power = btn.dataset.power;
  document.querySelectorAll('.power-option').forEach(b => b.classList.toggle('active', b === btn));
  $('#powerThumb').style.transform = `translateX(${btn.dataset.index * 100}%)`;
}));
$('#newChat').onclick = startNewConversation;
document.addEventListener('click', closeMenus);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenus(); });
promptEl.addEventListener('input', autoResize);
sendBtn.addEventListener('click', handleComposerAction);
promptEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!state.sending) handleComposerAction();
  }
});

function initApp() {
  state.conversations = loadConversations();
  const mostRecent = Object.values(state.conversations).filter(c => c.messages.length > 0).sort((a, b) => b.updatedAt - a.updatedAt)[0];
  if (mostRecent) {
    state.activeId = mostRecent.id;
    state.history = mostRecent.messages.filter(m => !m.error).map(m => ({ role: m.role, content: m.content }));
    redrawConversation();
  } else {
    rebindSuggestions();
  }
  renderRecentList();
  loadConfig();
  loadModels();
  autoResize();
}

// A page reload keeps the same tab's sessionStorage, so a valid token found
// here means "still the same session" — not a persisted auto-login across
// visits, since sessionStorage never survives the tab/browser closing.
const existingToken = sessionStorage.getItem(TOKEN_KEY);
if (existingToken) {
  state.token = existingToken;
  showApp();
} else {
  showLogin();
}
