/* Rian v19 polish layer: accessible command palette and keyboard navigation. */
(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const overlay = $('#commandPalette');
  const input = $('#commandInput');
  const results = $('#commandResults');
  if (!overlay || !input || !results) return;

  const commands = [
    { title: 'Overview', detail: 'Your dashboard and today at a glance', icon: '⌂', group: 'Navigate', run: () => Hub.go('home') },
    { title: 'Timetable', detail: 'See your lessons and schedule', icon: '▤', group: 'Navigate', run: () => Hub.go('timetable') },
    { title: 'Tasks & deadlines', detail: 'Manage homework and upcoming work', icon: '✓', group: 'Navigate', run: () => Hub.go('tasks') },
    { title: 'Revision', detail: 'Courses, subjects and revision tools', icon: '◈', group: 'Navigate', run: () => Hub.go('revision') },
    { title: 'Flashcards', detail: 'Review cards and open study modes', icon: '▣', group: 'Navigate', run: () => Hub.go('flashcards') },
    { title: 'AI study assistant', detail: 'Ask a question or plan revision', icon: '✦', group: 'Navigate', run: () => Hub.go('assistant') },
    { title: 'Settings', detail: 'Profile, courses and quick links', icon: '⚙', group: 'Navigate', run: () => Hub.go('settings') },
    { title: 'Create a task', detail: 'Add homework or a deadline', icon: '+', group: 'Create', run: () => { Hub.go('tasks'); $('#addTaskBtn')?.click(); } },
    { title: 'Create a flashcard', detail: 'Add a question and answer', icon: '+', group: 'Create', run: () => { Hub.go('flashcards'); $('#newFlashcardBtn')?.click(); } },
    { title: 'Create a study set', detail: 'Start a new deck of cards', icon: '+', group: 'Create', run: () => { Hub.go('flashcards'); $('#newFlashcardSetBtn')?.click(); } },
    { title: 'Start a focus session', detail: 'Begin a 25-minute focus block', icon: '◷', group: 'Study', run: () => { Hub.go('revision'); $('#focusBtn')?.click(); } },
    { title: 'Refresh dashboard', detail: 'Reload your saved student data', icon: '↻', group: 'Actions', run: () => $('#refreshHub')?.click() }
  ];
  let visible = [...commands], active = 0, priorFocus = null;

  const escape = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render() {
    const q = input.value.trim().toLocaleLowerCase();
    visible = commands.filter(c => `${c.title} ${c.detail} ${c.group}`.toLocaleLowerCase().includes(q));
    active = Math.min(active, Math.max(visible.length - 1, 0));
    if (!visible.length) {
      results.innerHTML = '<div class="command-empty"><strong>No results</strong><span>Try a page name or an action.</span></div>';
      return;
    }
    let lastGroup = '';
    results.innerHTML = visible.map((c, i) => {
      const group = c.group !== lastGroup ? `<div class="command-group-label">${escape(c.group)}</div>` : '';
      lastGroup = c.group;
      return `${group}<button class="command-result${i === active ? ' selected' : ''}" type="button" role="option" aria-selected="${i === active}" data-command-index="${i}"><span class="command-result-icon">${escape(c.icon)}</span><span class="command-result-copy"><strong>${escape(c.title)}</strong><small>${escape(c.detail)}</small></span><span class="command-result-enter">↵</span></button>`;
    }).join('');
    results.querySelector('.selected')?.scrollIntoView({ block: 'nearest' });
  }
  function open() {
    priorFocus = document.activeElement;
    overlay.hidden = false;
    input.value = '';
    active = 0;
    render();
    requestAnimationFrame(() => input.focus());
  }
  function close() {
    overlay.hidden = true;
    priorFocus?.focus?.();
  }
  function run(index = active) {
    const command = visible[index];
    if (!command) return;
    close();
    command.run();
  }
  $('#commandOpen')?.addEventListener('click', open);
  input.addEventListener('input', () => { active = 0; render(); });
  results.addEventListener('click', e => {
    const button = e.target.closest('[data-command-index]');
    if (button) run(Number(button.dataset.commandIndex));
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, visible.length - 1); render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
    else if (e.key === 'Enter') { e.preventDefault(); run(); }
    else if (e.key === 'Escape') { e.preventDefault(); close(); }
  });
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); overlay.hidden ? open() : close(); }
    if (e.key === 'Escape' && !overlay.hidden) close();
  });
})();
