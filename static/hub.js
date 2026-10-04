const Hub = (() => {
  let data = { profile:{}, tasks:[], timetable:[], subjects:[], quick_links:[], flashcards:[] };
  let flashcardIndex=0, flashcardFlipped=false, flashcardDeck='all';
  const boards=['AQA','OCR','Pearson Edexcel','CCEA','WJEC / Eduqas','Cambridge International','IB','Other'];
  function normaliseCourse(s){ if(typeof s==='string') return {name:s, exam_board:'', specification:'', course:'', progress:0}; return {name:String(s?.name||'').trim(),exam_board:String(s?.exam_board||s?.examBoard||'').trim(),specification:String(s?.specification||s?.spec_link||'').trim(),course:String(s?.course||'').trim(),progress:Math.max(0,Math.min(100,Number(s?.progress)||0))}; }
  function courseList(){ data.subjects=(data.subjects||[]).map(normaliseCourse).filter(s=>s.name); return data.subjects; }
  let taskFilter = 'all';
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const auth = (url, opts={}) => fetch(url, { ...opts, credentials:'same-origin', cache:'no-store', headers:{'Content-Type':'application/json',...(opts.headers||{})} });
  const toast = msg => { const el=$('#toast'); el.textContent=msg; el.classList.add('show'); clearTimeout(window._toast); window._toast=setTimeout(()=>el.classList.remove('show'),2400); };
  const formatDate = d => { if(!d) return 'No date'; const x=new Date(d+'T12:00:00'); if(isNaN(x)) return d; const diff=Math.round((new Date(d+'T00:00:00')-new Date(todayISO+'T00:00:00'))/864e5); return diff===0?'Today':diff===1?'Tomorrow':diff===-1?'Yesterday':x.toLocaleDateString('en-GB',{day:'numeric',month:'short'}); };
  let today, dayName, todayISO;
  const refreshToday=()=>{today=new Date();dayName=today.toLocaleDateString('en-GB',{weekday:'long'});todayISO=[today.getFullYear(),String(today.getMonth()+1).padStart(2,'0'),String(today.getDate()).padStart(2,'0')].join('-');};
  refreshToday();

  async function load(){ try { const r=await auth('/api/student'); if(r.status===401){if(typeof showLogin==='function')showLogin('Your session expired. Please sign in again.');return;} if(!r.ok) throw new Error('Could not load your hub.'); const j=await r.json(); data=j.student||data; renderAll(); } catch(e){toast(e.message||'Could not load your hub.');} }
  async function save(){ try { const r=await auth('/api/student',{method:'PUT',body:JSON.stringify(data)}); if(!r.ok){toast('Could not save changes');return false;} data=(await r.json()).student; return true; } catch(e){toast('Could not save changes');return false;} }
  function renderProfile(){
    const p=data.profile||{}; const name=p.display_name||p.username||'Student';
    $('#sidebarName').textContent=name; $('#sidebarUsername').textContent='@'+(p.username||'student'); $('#avatarInitial').textContent=name.charAt(0).toUpperCase();
    $('#welcomeTitle').textContent=`Good ${new Date().getHours()<12?'morning':new Date().getHours()<18?'afternoon':'evening'}, ${name.split(' ')[0]}.`;
    $('#welcomeSub').textContent=p.year_group ? `${p.year_group}${p.school?' · '+p.school:''} · ${dayName}` : `It’s ${dayName}. Add your year group in Settings to personalise this message.`;
    $('#pageTitle').textContent=`${dayName}`; $('#todayLabel').textContent=today.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
    renderCourseEditor(); renderQuickLinkEditor();
  }
  function renderStats(){
    const open=(data.tasks||[]).filter(t=>!t.done); $('#statTasks').textContent=open.length; $('#taskBadge').textContent=open.length;
    $('#statTasksSub').textContent=open.length?(open.filter(t=>t.due===todayISO).length+' due today'): 'All caught up';
    const lessons=(data.timetable||[]).filter(t=>t.day===dayName.toLowerCase()); $('#statLessons').textContent=lessons.length; $('#statLessonsSub').textContent=lessons.length?'On today’s schedule':'No lessons added';
    $('#statSubjects').textContent=(data.subjects||[]).length; $('#statFocus').textContent=open.length?'25 min':'Ready';
  }
  function renderHome(){
    const lessons=(data.timetable||[]).filter(t=>t.day===dayName.toLowerCase()).sort((a,b)=>(a.start||'').localeCompare(b.start||''));
    $('#homeTimetable').innerHTML=lessons.length?lessons.slice(0,5).map(t=>`<div class="compact-row"><span class="time">${esc(t.start||'—')}</span><div><strong>${esc(t.subject||'Lesson')}</strong><small>${esc(t.room||'')}</small></div></div>`).join(''):'<div class="empty">No lessons for today. Add your timetable in the Timetable page.</div>';
    const tasks=(data.tasks||[]).filter(t=>!t.done).sort((a,b)=>(a.due||'9999').localeCompare(b.due||'9999')).slice(0,5);
    $('#homeTasks').innerHTML=tasks.length?tasks.map(t=>`<div class="compact-row"><span class="priority ${esc(t.priority)}"></span><div><strong>${esc(t.title)}</strong><small>${esc(t.subject)} · ${formatDate(t.due)}</small></div></div>`).join(''):'<div class="empty">No open tasks. Nice.</div>';
    $('#quickLinks').innerHTML=(data.quick_links||[]).map(l=>`<a class="quick-link" href="${esc(l.url)}" target="_blank" rel="noopener"><span>${esc(l.icon||'↗')}</span><div><strong>${esc(l.title)}</strong><small>Open ↗</small></div></a>`).join('') || '<div class="empty">Add your school links in Settings.</div>';
  }
  function renderTimetable(){
    const days=['monday','tuesday','wednesday','thursday','friday']; const labels=['Monday','Tuesday','Wednesday','Thursday','Friday'];
    $('#timetableList').innerHTML=labels.map((d,i)=>{const rows=(data.timetable||[]).filter(t=>t.day===days[i]).sort((a,b)=>(a.start||'').localeCompare(b.start||'')); return `<div class="day-card glass ${days[i]===dayName.toLowerCase()?'today':''}"><div class="day-head"><strong>${d}</strong>${days[i]===dayName.toLowerCase()?'<span>Today</span>':''}</div>${rows.length?rows.map(t=>`<div class="lesson"><time>${esc(t.start||'')}<br>${esc(t.end||'')}</time><div><strong>${esc(t.subject||'Lesson')}</strong><small>${esc(t.room||'')}</small></div><button class="delete-lesson" data-id="${esc(t.id)}">×</button></div>`).join(''):'<div class="day-empty">No lessons</div>'}</div>`;}).join('');
    document.querySelectorAll('.delete-lesson').forEach(b=>b.onclick=async()=>{data.timetable=data.timetable.filter(t=>t.id!==b.dataset.id);await save();renderAll();});
  }
  function renderTasks(){
    let tasks=[...(data.tasks||[])].sort((a,b)=>Number(a.done)-Number(b.done)||(a.due||'9999').localeCompare(b.due||'9999'));
    tasks=tasks.filter(t=>taskFilter==='all'||(taskFilter==='open'&&!t.done)||(taskFilter==='done'&&t.done)||(taskFilter==='high'&&t.priority==='high'));
    $('#taskList').innerHTML=tasks.length?tasks.map(t=>`<div class="task-row glass ${t.done?'done':''} ${!t.done&&t.due&&t.due<todayISO?'overdue':''}"><button class="check ${t.done?'checked':''}" data-task="${esc(t.id)}">${t.done?'✓':''}</button><div class="task-main"><strong>${esc(t.title)}</strong><div><span>${esc(t.subject)}</span><span>${t.due?formatDate(t.due):'No due date'}</span><span class="priority-label ${esc(t.priority)}">${esc(t.priority)}</span></div></div><button class="delete-task" data-task="${esc(t.id)}">×</button></div>`).join(''):'<div class="empty large-empty">No tasks in this view. Add one when you have something to remember.</div>';
    document.querySelectorAll('.check').forEach(b=>b.onclick=async()=>{const t=data.tasks.find(x=>x.id===b.dataset.task);t.done=!t.done;await save();renderAll();});
    document.querySelectorAll('.delete-task').forEach(b=>b.onclick=async()=>{const r=await auth('/api/student/tasks/'+b.dataset.task,{method:'DELETE'});if(!r.ok){toast('Could not delete task');return;}data.tasks=data.tasks.filter(x=>x.id!==b.dataset.task);renderAll();toast('Task deleted');});
  }
  function renderSubjects(){ const courses=courseList(); $('#subjectGrid').innerHTML=courses.map((s,i)=>{const colour=['mint','blue','purple','orange','pink'][i%5]; const board=s.exam_board||'Exam board not set'; const pct=s.progress||0; return `<article class="subject-card glass ${colour}"><div class="subject-dot"></div><span>${esc(s.exam_board||'Course')}</span><h3>${esc(s.name)}</h3><p>${esc(s.course||'Course not set')} · ${esc(board)}</p><div class="course-progress"><div><span>Course progress</span><strong>${pct}%</strong></div><div class="progress-track"><i style="width:${pct}%"></i></div></div>${s.specification?`<a class="text-button" href="${esc(s.specification)}" target="_blank" rel="noopener">Open specification ↗</a>`:''}<button class="text-button subject-ai" data-subject="${esc(s.name)}">Study ${esc(s.name)} →</button><button class="subject-remove" data-index="${i}">×</button></article>`}).join('') || '<div class="empty large-empty">No courses yet. Add one from Settings.</div>'; document.querySelectorAll('.subject-ai').forEach(b=>b.onclick=()=>{go('assistant'); $('#prompt').value=`Help me revise ${b.dataset.subject}. Start by asking what topic I am studying.`; $('#prompt').focus();}); document.querySelectorAll('.subject-remove').forEach(b=>b.onclick=async()=>{data.subjects.splice(Number(b.dataset.index),1);await save();renderAll();}); }
  function renderCourseEditor(){ const courses=courseList(); const el=$('#courseEditor'); if(!el)return; el.innerHTML=courses.length?courses.map((c,i)=>`<div class="course-editor-row" data-course="${i}"><div class="course-row-main"><label>Subject<input data-field="name" value="${esc(c.name)}" placeholder="e.g. Biology"></label><label>Course / qualification<input data-field="course" value="${esc(c.course)}" placeholder="e.g. GCSE Biology"></label><label>Exam board<select data-field="exam_board"><option value="">Select board</option>${boards.map(b=>`<option ${c.exam_board===b?'selected':''}>${b}</option>`).join('')}</select></label><label>Specification link<input data-field="specification" type="url" value="${esc(c.specification)}" placeholder="https://…"></label></div><div class="course-row-bottom"><label class="progress-field">Course progress <div class="progress-input"><input data-field="progress" type="range" min="0" max="100" step="5" value="${c.progress}"><output>${c.progress}%</output></div></label><button type="button" class="delete-editor" data-course-delete="${i}">Remove</button></div></div>`).join(''):'<div class="empty editor-empty">No courses added yet. Click “Add course” to create your first one.</div>'; el.querySelectorAll('[data-field=progress]').forEach(input=>input.oninput=()=>input.nextElementSibling.value=input.value+'%'); el.querySelectorAll('[data-course-delete]').forEach(b=>b.onclick=()=>{data.subjects.splice(Number(b.dataset.courseDelete),1);renderCourseEditor();renderSubjects();}); }
  function renderQuickLinkEditor(){ const el=$('#quickLinkEditor'); if(!el)return; const links=data.quick_links||[]; el.innerHTML=links.map((l,i)=>`<div class="editor-row"><input data-link="title" data-index="${i}" value="${esc(l.title||'')}" placeholder="Link name"><input data-link="url" data-index="${i}" type="url" value="${esc(l.url||'')}" placeholder="https://example.com"><button type="button" class="delete-editor" data-link-delete="${i}">Remove</button></div>`).join('')||'<div class="empty editor-empty">No quick links yet. Add your school platforms here.</div>'; el.querySelectorAll('[data-link-delete]').forEach(b=>b.onclick=()=>{data.quick_links.splice(Number(b.dataset.linkDelete),1);renderQuickLinkEditor();}); }
  function renderFlashcards(){
    const all=data.flashcards||[], cards=all.filter(c=>flashcardDeck==='all'||(c.deck||'General')===flashcardDeck);
    const decks=[...new Set(all.map(c=>c.deck||'General'))].sort((a,b)=>a.localeCompare(b));
    const filter=$('#flashcardDeckFilter');
    if(filter){filter.innerHTML='<option value="all">All decks</option>'+decks.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join('');filter.value=decks.includes(flashcardDeck)?flashcardDeck:'all';}
    const progress=data.learn_progress||{}, mastered=cards.filter(c=>Number(progress[c.id]?.mastery||0)>=2).length;
    const due=cards.filter(c=>{const d=progress[c.id]?.due_at;return !d||new Date(d).getTime()<=Date.now();}).length;
    $('#flashcardSetKicker').textContent=flashcardDeck==='all'?'All decks':flashcardDeck;
    $('#flashcardSetTitle').textContent=flashcardDeck==='all'?'Your flashcards':flashcardDeck;
    $('#flashcardSetMeta').textContent=cards.length?`${cards.length} cards · ${mastered} mastered · ${due} ready to review`:'Create or import cards to start studying.';
    $('#setCardCount').textContent=cards.length; $('#setMastery').textContent=cards.length?Math.round(mastered/cards.length*100)+'%':'0%'; $('#setDue').textContent=due;
    if(!cards.length){$('#flashcardStudy').innerHTML='<div class="flashcard-empty"><div class="empty-card-icon">＋</div><strong>This set is empty</strong><span>Import cards or create your first question and answer.</span><div class="empty-actions"><button class="primary-button" id="emptyCreateCard">Create card</button><button class="small-button" id="emptyImportCards">Import cards</button></div></div>';$('#emptyCreateCard').onclick=addFlashcard;$('#emptyImportCards').onclick=importFlashcards;$('#flashcardList').innerHTML='';return;}
    flashcardIndex=Math.min(flashcardIndex,cards.length-1); const c=cards[flashcardIndex];
    $('#flashcardStudy').innerHTML=`<div class="flashcard-stage"><div class="study-count">${flashcardIndex+1} / ${cards.length}</div><div class="study-flip-wrap ${flashcardFlipped?'is-flipped':''}" id="studyCard" tabindex="0" role="button" aria-label="${flashcardFlipped?'Hide answer':'Reveal answer'}"><div class="study-face study-front"><div class="flashcard-label">Question</div><div class="flashcard-question">${esc(c.question)}</div><div class="flip-hint">Click or press Space to reveal</div></div><div class="study-face study-back"><div class="flashcard-label">Answer</div><div class="flashcard-answer">${esc(c.answer)}</div><div class="flip-hint">Click or press Space to hide</div></div></div><div class="flashcard-actions"><button class="small-button" id="prevCard" aria-label="Previous card">←</button><button class="primary-button" id="flipCard">${flashcardFlipped?'Hide answer':'Reveal answer'}</button><button class="small-button" id="nextCard" aria-label="Next card">→</button></div><div class="study-shortcuts"><span>← / → navigate</span><span>Space reveal</span></div></div>`;
    const flip=()=>{flashcardFlipped=!flashcardFlipped;renderFlashcards();};
    $('#studyCard').onclick=flip; $('#studyCard').onkeydown=e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();flip();}};
    $('#flipCard').onclick=flip; $('#prevCard').onclick=()=>{flashcardIndex=(flashcardIndex-1+cards.length)%cards.length;flashcardFlipped=false;renderFlashcards();}; $('#nextCard').onclick=()=>{flashcardIndex=(flashcardIndex+1)%cards.length;flashcardFlipped=false;renderFlashcards();};
    $('#flashcardList').innerHTML=cards.slice(0,100).map((c,i)=>`<div class="flashcard-row glass"><div class="flashcard-row-number">${i+1}</div><div class="flashcard-row-main"><strong>${esc(c.question)}</strong><small>${esc(c.deck||'General')} · ${esc(c.subject||'')}</small></div><span class="mastery-pill mastery-${Number(progress[c.id]?.mastery||0)}">${Number(progress[c.id]?.mastery||0)>=2?'Mastered':Number(progress[c.id]?.mastery||0)>0?'Learning':'New'}</span><div class="flashcard-row-actions"><button class="small-button" data-card-study="${esc(c.id)}">Study</button><button class="small-button" data-card-delete="${esc(c.id)}">Delete</button></div></div>`).join('');
    document.querySelectorAll('[data-card-study]').forEach(b=>b.onclick=()=>{const i=cards.findIndex(c=>c.id===b.dataset.cardStudy);flashcardIndex=Math.max(0,i);flashcardFlipped=false;renderFlashcards();});
    document.querySelectorAll('[data-card-delete]').forEach(b=>b.onclick=async()=>{if(!confirm('Delete this flashcard?'))return;const r=await auth('/api/student/flashcards/'+b.dataset.cardDelete,{method:'DELETE'});if(!r.ok){toast('Could not delete card');return;}data.flashcards=data.flashcards.filter(c=>c.id!==b.dataset.cardDelete);renderAll();toast('Flashcard deleted');});
  }

  let studyMode='flashcards', testState=null, matchState=null;
  function studyCards(){return (data.flashcards||[]).filter(c=>flashcardDeck==='all'||(c.deck||'General')===flashcardDeck);}
  function openStudyMode(mode){
    studyMode=mode; document.querySelectorAll('.study-tab').forEach(b=>b.classList.toggle('active',b.dataset.studyMode===mode));
    if(mode==='flashcards'){go('flashcards');return;}
    if(mode==='learn'){go('learn');startLearn();return;}
    const cards=studyCards(); if(!cards.length){toast('Add some flashcards first.');return;}
    if(mode==='test') startTest(); else startMatch();
  }
  function startTest(){
    const cards=[...studyCards()].sort(()=>Math.random()-.5); testState={cards,idx:0,correct:0,answered:0,locked:false}; modal('<div class="study-modal-shell" id="testShell"></div>');renderTest();
  }
  function renderTest(){
    const s=testState;if(!s)return;const c=s.cards[s.idx];
    if(s.idx>=s.cards.length){$('#testShell').innerHTML=`<div class="study-result"><div class="result-icon">✓</div><span class="eyebrow">Test complete</span><h2>${s.correct} / ${s.cards.length}</h2><p>${Math.round(s.correct/s.cards.length*100)}% correct. Use Learn to revisit anything you missed.</p><div class="result-actions"><button class="primary-button" id="testAgain">Retake test</button><button class="small-button" id="testClose">Done</button></div></div>`;$('#testAgain').onclick=startTest;$('#testClose').onclick=closeModal;return;}
    const others=s.cards.filter(x=>x.id!==c.id).sort(()=>Math.random()-.5).slice(0,3);const opts=[c.answer,...others.map(x=>x.answer)].sort(()=>Math.random()-.5);
    $('#testShell').innerHTML=`<div class="test-header"><div><span class="eyebrow">Test</span><h2>Check your recall</h2></div><span>${s.idx+1} / ${s.cards.length}</span></div><div class="test-progress"><i style="width:${s.idx/s.cards.length*100}%"></i></div><div class="test-question">${esc(c.question)}</div><div class="test-options">${opts.map(o=>`<button class="test-option" data-test-answer="${esc(o)}">${esc(o)}</button>`).join('')}</div><div class="test-footer"><span>Multiple choice · one answer</span><button class="text-button" id="testExit">Exit</button></div>`;
    document.querySelectorAll('[data-test-answer]').forEach(b=>b.onclick=()=>{if(s.locked)return;s.locked=true;const ok=b.dataset.testAnswer===c.answer;b.classList.add(ok?'correct':'wrong');if(!ok)document.querySelectorAll('[data-test-answer]').forEach(x=>{if(x.dataset.testAnswer===c.answer)x.classList.add('correct');});if(ok)s.correct++;s.answered++;setTimeout(()=>{s.idx++;s.locked=false;renderTest();},650);});$('#testExit').onclick=closeModal;
  }
  function startMatch(){
    const source=[...studyCards()].sort(()=>Math.random()-.5).slice(0,Math.min(6,studyCards().length)); const tiles=[...source.map(c=>({id:c.id,type:'term',text:c.question})),...source.map(c=>({id:c.id,type:'answer',text:c.answer}))].sort(()=>Math.random()-.5);matchState={tiles,selected:null,matches:0,moves:0,started:Date.now(),wrong:[]};modal('<div class="study-modal-shell" id="matchShell"></div>');renderMatch();
  }
  function renderMatch(){
    const s=matchState;if(!s)return; if(s.matches*2===s.tiles.length){const sec=Math.max(1,Math.round((Date.now()-s.started)/1000));$('#matchShell').innerHTML=`<div class="study-result"><div class="result-icon">✦</div><span class="eyebrow">Match complete</span><h2>${s.moves} moves</h2><p>You matched ${s.matches} pairs in ${sec}s.</p><div class="result-actions"><button class="primary-button" id="matchAgain">Play again</button><button class="small-button" id="matchClose">Done</button></div></div>`;$('#matchAgain').onclick=startMatch;$('#matchClose').onclick=closeModal;return;}
    $('#matchShell').innerHTML=`<div class="test-header"><div><span class="eyebrow">Match</span><h2>Find the pairs</h2></div><span>${s.matches} / ${s.tiles.length/2}</span></div><div class="match-grid">${s.tiles.map((t,i)=>`<button class="match-tile ${t.matched?'matched':''} ${s.selected===i?'selected':''} ${s.wrong?.includes(i)?'wrong':''}" data-match="${i}" ${t.matched?'disabled':''}>${esc(t.text)}</button>`).join('')}</div><div class="test-footer"><span>Moves: ${s.moves}</span><button class="text-button" id="matchExit">Exit</button></div>`;
    document.querySelectorAll('[data-match]').forEach(b=>b.onclick=()=>{const i=Number(b.dataset.match);if(s.tiles[i].matched||s.selected===i)return;if(s.selected===null){s.selected=i;renderMatch();return;}s.moves++;const a=s.tiles[s.selected],bb=s.tiles[i];if(a.id===bb.id&&a.type!==bb.type){a.matched=bb.matched=true;s.matches++;s.selected=null;renderMatch();}else{const first=s.selected;s.wrong=[first,i];s.selected=null;renderMatch();setTimeout(()=>{s.wrong=[];renderMatch();},420);}});$('#matchExit').onclick=closeModal;
  }

  let learnGoal=10, learnSession=null;
  function learnStats(){
    const cards=data.flashcards||[], progress=data.learn_progress||{};
    let mastered=0,familiar=0,newCards=0;
    cards.forEach(c=>{const m=Number(progress[c.id]?.mastery||0); if(m>=2) mastered++; else if(m===1) familiar++; else newCards++;});
    const pct=cards.length?Math.round(mastered/cards.length*100):0;
    if($('#learnNew')) $('#learnNew').textContent=newCards;
    if($('#learnFamiliar')) $('#learnFamiliar').textContent=familiar;
    if($('#learnMastered')) $('#learnMastered').textContent=mastered;
    if($('#learnPercent')) $('#learnPercent').textContent=pct+'%';
    const filter=$('#learnDeckFilter');
    if(filter){const decks=[...new Set(cards.map(c=>c.deck||'General'))].sort(); const old=filter.value||'all'; filter.innerHTML='<option value="all">All decks</option>'+decks.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join(''); filter.value=decks.includes(old)?old:'all';}
  }
  function learnCards(){const deck=$('#learnDeckFilter')?.value||'all'; return (data.flashcards||[]).filter(c=>deck==='all'||(c.deck||'General')===deck);}
  function chooseLearnCard(){
    const cards=learnCards(); if(!cards.length)return null;
    const now=Date.now(), progress=data.learn_progress||{}, seen=learnSession?.seen||new Set();
    const due=cards.filter(c=>!progress[c.id]||Number(progress[c.id].due_at||0)<=now||Number(progress[c.id].mastery||0)<2);
    const unSeen=due.filter(c=>!seen.has(c.id));
    const pool=(unSeen.length?unSeen:(due.length?due:cards));
    pool.sort((a,b)=>{const pa=progress[a.id]||{},pb=progress[b.id]||{}; return Number(pa.mastery||0)-Number(pb.mastery||0) || Number(pa.due_at||0)-Number(pb.due_at||0) || Math.random()-.5;});
    return pool[0];
  }
  function answerMatches(input,answer){
    const norm=x=>String(x||'').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
    const a=norm(answer), b=norm(input); if(!a||!b)return false; if(a===b)return true;
    const tokens=a.split(' ').filter(Boolean); const bt=new Set(b.split(' ').filter(Boolean));
    const overlap=tokens.filter(x=>bt.has(x)).length/Math.max(tokens.length,1); return overlap>=.78 && b.length>=Math.min(8,a.length*.55);
  }
  function questionType(card){const m=Number(data.learn_progress?.[card.id]?.mastery||0); if(m===0)return 'choice'; const roll=Math.random(); return roll<.42?'written':roll<.7?'choice':'flash';}
  function startLearn(){
    document.querySelectorAll('.study-tab').forEach(b=>b.classList.toggle('active',b.dataset.studyMode==='learn'));
    const cards=learnCards(); if(!cards.length){toast('Add or import some flashcards first.');go('flashcards');return;}
    learnSession={total:Math.min(learnGoal,Math.max(1,cards.length*2)),answered:0,correct:0,card:null,type:null,locked:false,seen:new Set()}; go('learn'); nextLearnQuestion();
  }
  function finishLearn(){
    const score=learnSession?.answered?Math.round(learnSession.correct/learnSession.answered*100):0;
    $('#learnCard').innerHTML=`<div class="learn-start"><div class="learn-symbol">✓</div><h2>Session complete</h2><p>You answered <strong>${learnSession.correct}</strong> of <strong>${learnSession.answered}</strong> correctly — ${score}% for this session.</p><button class="primary-button" id="learnAgain">Keep going</button><button class="text-button" id="learnBackCards">Back to flashcards →</button></div>`;
    $('#learnAgain').onclick=startLearn; $('#learnBackCards').onclick=()=>go('flashcards'); learnStats();
  }
  function renderLearnQuestion(){
    const s=learnSession, c=s.card, stats=data.learn_progress?.[c.id]||{}; const answered=s.answered, pct=Math.round(answered/s.total*100); const m=Number(stats.mastery||0); const type=s.type;
    let body='';
    if(type==='choice'){
      const others=learnCards().filter(x=>x.id!==c.id).sort(()=>Math.random()-.5).slice(0,3); const opts=[c.answer,...others.map(x=>x.answer)].sort(()=>Math.random()-.5);
      body=`<div class="learn-options">${opts.map((o,i)=>`<button class="learn-option" data-answer="${esc(o)}">${esc(o)}</button>`).join('')}</div>`;
    } else if(type==='written') body=`<form id="learnAnswerForm"><input class="learn-input" id="learnInput" autocomplete="off" placeholder="Type the answer from memory…"><div class="learn-footer"><button class="primary-button" type="submit">Check answer</button></div></form>`;
    else body=`<div class="learn-reveal"><div class="learn-recall-card"><div class="flashcard-label">Recall before revealing</div><p>Say the answer in your head, then reveal it.</p><button class="primary-button" id="revealLearnAnswer">Reveal answer</button><div id="revealedLearnAnswer" class="revealed-answer" hidden>${esc(c.answer)}</div></div><div class="learn-footer" id="learnSelfButtons" hidden><button class="small-button" id="learnDontKnow">Still learning</button><button class="primary-button" id="learnKnow">I knew it</button></div></div>`;
    $('#learnCard').innerHTML=`<div class="learn-question"><div class="learn-meta"><span>${esc(c.deck||'General')} · ${type==='choice'?'Multiple choice':type==='written'?'Written recall':'Self-check'}</span><span>${answered+1} of ${s.total}</span></div><div class="learn-progressbar"><i style="width:${pct}%"></i></div><div class="learn-prompt">${esc(c.question)}</div>${body}<div id="learnFeedback" class="learn-feedback" hidden></div></div>`;
    if(type==='choice') document.querySelectorAll('.learn-option').forEach(b=>b.onclick=()=>submitLearn(b.dataset.answer,c.answer,b));
    if(type==='written'){$('#learnAnswerForm').onsubmit=e=>{e.preventDefault();submitLearn($('#learnInput').value,c.answer,null);};setTimeout(()=>$('#learnInput')?.focus(),0);}
    if(type==='flash'){ $('#revealLearnAnswer').onclick=()=>{ $('#revealedLearnAnswer').hidden=false; $('#revealLearnAnswer').hidden=true; $('#learnSelfButtons').hidden=false; }; $('#learnDontKnow').onclick=()=>submitLearn('',c.answer,null,false); $('#learnKnow').onclick=()=>submitLearn(c.answer,c.answer,null,true); }
  }
  async function submitLearn(given,expected,button,forced){
    if(!learnSession||learnSession.locked)return; learnSession.locked=true;
    const correct=typeof forced==='boolean'?forced:answerMatches(given,expected); if(button)button.classList.add(correct?'correct':'wrong');
    const feedback=$('#learnFeedback'); if(feedback){feedback.hidden=false;feedback.innerHTML=correct?'<strong>Nice.</strong> This card is moving further away in your review schedule.':`<strong>Keep this one in rotation.</strong><br><span>${esc(expected)}</span>`;}
    try{const r=await auth('/api/student/learn/answer',{method:'POST',body:JSON.stringify({card_id:learnSession.card.id,correct,question_type:learnSession.type})}); const j=await r.json().catch(()=>({})); if(r.ok){data=j.student||data;} else toast(j.error||'Could not save Learn progress.');}catch(_){toast('Progress could not be saved.');}
    learnSession.answered++; if(correct)learnSession.correct++;
    learnStats(); setTimeout(()=>{if(learnSession.answered>=learnSession.total){finishLearn();return;} learnSession.locked=false; nextLearnQuestion();},700);
  }
  function nextLearnQuestion(){const c=chooseLearnCard(); if(!c){finishLearn();return;} learnSession.seen.add(c.id); learnSession.card=c; learnSession.type=questionType(c); renderLearnQuestion();}
  function initLearn(){learnStats(); document.querySelectorAll('.goal').forEach(b=>b.onclick=()=>{document.querySelectorAll('.goal').forEach(x=>x.classList.remove('active'));b.classList.add('active');learnGoal=Number(b.dataset.goal);}); $('#startLearnBtn').onclick=startLearn; $('#learnStartHero').onclick=startLearn; $('#openLearnFromCards').onclick=()=>go('learn'); $('#learnDeckFilter').onchange=()=>learnStats();}
  function addFlashcard(){modal(`<div class="modal-kicker">Active recall</div><h2>New flashcard</h2><form id="flashcardForm" class="modal-form"><label>Question<textarea id="fcQuestion" rows="3" required placeholder="What is…?"></textarea></label><label>Answer<textarea id="fcAnswer" rows="4" required placeholder="The answer…"></textarea></label><div class="form-row"><label>Deck<input id="fcDeck" value="General"></label><label>Subject<input id="fcSubject" placeholder="Optional"></label></div><p id="fcError" class="form-error"></p><button class="primary-button" type="submit">Add flashcard</button></form>`);$('#flashcardForm').onsubmit=async e=>{e.preventDefault();const q=$('#fcQuestion').value.trim(),a=$('#fcAnswer').value.trim();if(!q||!a){$('#fcError').textContent='Question and answer are required.';return;}const r=await auth('/api/student/flashcards/import',{method:'POST',body:JSON.stringify({text:`${q}\t${a}`,deck:$('#fcDeck').value.trim()||'General',subject:$('#fcSubject').value.trim(),format:'txt'})});const j=await r.json().catch(()=>({}));if(!r.ok){$('#fcError').textContent=j.error||'Could not add flashcard.';return;}data=j.student||data;closeModal();renderFlashcards();toast('Flashcard added');};setTimeout(()=>$('#fcQuestion')?.focus(),0);}
  function importFlashcards(){
    modal(`<div class="modal-kicker">Import</div><h2>Bring in your cards</h2><p class="modal-subtitle">Upload a CSV/TXT file or paste your cards. Rian accepts question/answer pairs separated by commas, tabs, <code>::</code> or <code>|</code>.</p><form id="importForm" class="modal-form"><label>Deck<input id="importDeck" value="General" maxlength="80"></label><label>Subject<input id="importSubject" placeholder="Optional" maxlength="80"></label><label>File <input id="importFile" type="file" accept=".csv,.txt,text/csv,text/plain"></label><label>Or paste cards<textarea id="importText" rows="10" placeholder="Question,Answer\nWhat is ATP?,The cell's energy currency\n\nOr: question :: answer"></textarea></label><p class="flashcard-import-help">Up to 1,000 cards per import. Duplicates are skipped automatically.</p><p id="importError" class="form-error"></p><button class="primary-button" type="submit">Import cards</button></form>`);
    $('#importFile').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;try{$('#importText').value=await file.text();$('#importText').focus();toast(`${file.name} ready to import`);}catch(_){$('#importError').textContent='We could not read that file.';}};
    $('#importForm').onsubmit=async e=>{e.preventDefault();const btn=$('#importForm button[type=submit]');const error=$('#importError');error.textContent='';const raw=$('#importText').value.trim();if(!raw){error.textContent='Choose a CSV/TXT file or paste some cards first.';return;}btn.disabled=true;btn.textContent='Importing…';try{const r=await auth('/api/student/flashcards/import',{method:'POST',body:JSON.stringify({text:raw,deck:$('#importDeck').value,subject:$('#importSubject').value,format:'auto'})});const j=await r.json().catch(()=>({}));if(!r.ok){error.textContent=j.error||'Import failed.';return;}data=j.student||data;closeModal();flashcardDeck='all';flashcardIndex=0;renderAll();toast(`${j.added} card${j.added===1?'':'s'} imported${j.duplicates?` · ${j.duplicates} duplicate${j.duplicates===1?'':'s'} skipped`:''}`);}catch(_){error.textContent='Could not reach the hub.';}finally{btn.disabled=false;btn.textContent='Import cards';}};setTimeout(()=>$('#importText')?.focus(),0);
  }
  function renderAll(){refreshToday();renderProfile();renderStats();renderHome();renderTimetable();renderTasks();renderSubjects();renderFlashcards();learnStats();}
  function go(view){document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id==='view-'+view));document.querySelectorAll('.nav-item[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));const titles={home:'Overview',timetable:'Schedule',tasks:'Planning',revision:'Learning',flashcards:'Active recall',assistant:'Study assistant',settings:'Personalise'};$('#pageKicker').textContent=titles[view]||'STUDENT HUB';window.scrollTo({top:0,behavior:'smooth'});}
  function modal(html){$('#modalContent').innerHTML=html;$('#modal').hidden=false;}
  function closeModal(){$('#modal').hidden=true;}
  function addTask(){modal(`<div class="modal-kicker">New task</div><h2>Add a task</h2><form id="taskForm" class="modal-form"><label>Task title<input id="mTaskTitle" required placeholder="e.g. Finish Biology worksheet"></label><div class="form-row"><label>Subject<input id="mTaskSubject" placeholder="Biology"></label><label>Due date<input id="mTaskDue" type="date"></label></div><label>Priority<select id="mTaskPriority"><option value="normal">Normal</option><option value="high">High</option><option value="low">Low</option></select></label><button class="primary-button" type="submit">Add task</button></form>`);$('#taskForm').onsubmit=async e=>{e.preventDefault();const r=await auth('/api/student/tasks',{method:'POST',body:JSON.stringify({title:$('#mTaskTitle').value,subject:$('#mTaskSubject').value,due:$('#mTaskDue').value,priority:$('#mTaskPriority').value})});if(!r.ok){toast('Could not add task');return;}data.tasks.push((await r.json()).task);closeModal();renderAll();toast('Task added');};}
  function addLesson(){modal(`<div class="modal-kicker">Timetable</div><h2>Add a lesson</h2><form id="lessonForm" class="modal-form"><div class="form-row"><label>Day<select id="mDay">${['Monday','Tuesday','Wednesday','Thursday','Friday'].map(d=>`<option value="${d.toLowerCase()}">${d}</option>`).join('')}</select></label><label>Subject<input id="mSubject" required placeholder="Maths"></label></div><div class="form-row"><label>Start<input id="mStart" type="time" required></label><label>End<input id="mEnd" type="time" required></label></div><label>Room / teacher<input id="mRoom" placeholder="M2 · Ms Smith"></label><button class="primary-button" type="submit">Add lesson</button></form>`);$('#lessonForm').onsubmit=async e=>{e.preventDefault();data.timetable.push({id:crypto.randomUUID(),day:$('#mDay').value,subject:$('#mSubject').value,start:$('#mStart').value,end:$('#mEnd').value,room:$('#mRoom').value});await save();closeModal();renderAll();toast('Lesson added');};}
  function addSubject(){
    go('settings');
    modal(`<div class="modal-kicker">New course</div><h2>Add a course</h2><p class="modal-subtitle">Set the basics now. You can edit the course later from Settings.</p><form id="courseForm" class="modal-form">
      <label>Subject <input id="mCourseName" required maxlength=120 placeholder="e.g. Biology" autocomplete="off"></label>
      <div class="form-row"><label>Course / qualification <input id="mCourseType" maxlength=120 placeholder="e.g. GCSE Biology"></label><label>Exam board <select id="mCourseBoard"><option value="">Select board</option>${boards.map(b=>`<option value="${esc(b)}">${esc(b)}</option>`).join('')}</select></label></div>
      <label>Specification link <input id="mCourseSpec" type="url" placeholder="https://…" autocomplete="url"><small class="field-help">Optional. Use the official specification page or PDF.</small></label>
      <label>Course progress <div class="progress-input"><input id="mCourseProgress" type="range" min="0" max="100" step="5" value="0"><output id="mCourseProgressOut">0%</output></div></label>
      <p id="courseFormError" class="form-error" role="alert"></p><button class="primary-button" type="submit">Add course</button>
    </form>`);
    const progress=$('#mCourseProgress'), output=$('#mCourseProgressOut');
    progress.oninput=()=>output.value=progress.value+'%';
    $('#courseForm').onsubmit=async e=>{
      e.preventDefault();
      const error=$('#courseFormError'); error.textContent='';
      const name=$('#mCourseName').value.trim(), course=$('#mCourseType').value.trim(), board=$('#mCourseBoard').value, specification=$('#mCourseSpec').value.trim();
      if(!name){error.textContent='Enter a subject name.';$('#mCourseName').focus();return;}
      if(specification && !/^https?:\/\//i.test(specification)){error.textContent='The specification link must start with http:// or https://.';$('#mCourseSpec').focus();return;}
      const submit=$('#courseForm button[type=submit]'); submit.disabled=true; submit.textContent='Adding…';
      try{
        const r=await auth('/api/student/courses',{method:'POST',body:JSON.stringify({name,course,exam_board:board,specification,progress:Number(progress.value)})});
        const j=await r.json().catch(()=>({}));
        if(!r.ok){error.textContent=j.error||'Could not add this course.';return;}
        data=j.student||data; closeModal(); renderAll(); toast(`${name} added to your courses`);
      }catch(err){error.textContent='Could not reach the hub. Check your connection and try again.';}
      finally{submit.disabled=false;submit.textContent='Add course';}
    };
    setTimeout(()=>$('#mCourseName')?.focus(),0);
  }
  async function settings(){ const courseRows=[...document.querySelectorAll('.course-editor-row')]; data.subjects=courseRows.map(row=>{const get=k=>row.querySelector(`[data-field=\"${k}\"]`)?.value?.trim()||'';return {name:get('name'),course:get('course'),exam_board:get('exam_board'),specification:get('specification'),progress:Number(row.querySelector('[data-field=progress]')?.value||0)};}).filter(x=>x.name); const linkRows=[...document.querySelectorAll('.editor-row')]; data.quick_links=linkRows.map((row,i)=>({title:row.querySelector('[data-link=title]')?.value?.trim()||'',url:row.querySelector('[data-link=url]')?.value?.trim()||'',icon:(row.querySelector('[data-link=title]')?.value?.trim()||'↗').charAt(0).toUpperCase()})).filter(x=>x.title&&x.url); data.profile={...(data.profile||{}),display_name:$('#settingName').value.trim(),year_group:$('#settingYear').value.trim(),school:$('#settingSchool').value.trim()}; if(await save()){renderAll();$('#settingsMessage').textContent='Saved successfully.';setTimeout(()=>$('#settingsMessage').textContent='',2200);toast('Settings saved');}}
  function init(){document.querySelectorAll('.nav-item[data-view]').forEach(b=>b.onclick=()=>go(b.dataset.view));document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>go(b.dataset.go));$('#addTaskBtn').onclick=addTask;$('#addLessonBtn').onclick=addLesson;$('#addSubjectBtn').onclick=addSubject;$('#addCourse').onclick=addSubject;$('#newFlashcardBtn').onclick=addFlashcard;$('#importFlashcardsBtn').onclick=importFlashcards;document.querySelectorAll('.study-tab').forEach(b=>b.onclick=()=>openStudyMode(b.dataset.studyMode));initLearn();$('#shuffleFlashcards').onclick=()=>{const cards=data.flashcards||[];if(cards.length){flashcardDeck=$('#flashcardDeckFilter')?.value||'all';const filtered=cards.filter(c=>flashcardDeck==='all'||(c.deck||'General')===flashcardDeck);flashcardIndex=filtered.length?Math.floor(Math.random()*filtered.length):0;flashcardFlipped=false;renderFlashcards();}};$('#flashcardDeckFilter').onchange=e=>{flashcardDeck=e.target.value;flashcardIndex=0;flashcardFlipped=false;renderFlashcards();};document.addEventListener('keydown',e=>{if(document.querySelector('#view-flashcards.active')&&!document.querySelector('#modal:not([hidden])')&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)){const cards=studyCards();if(e.key==='ArrowLeft'&&cards.length){flashcardIndex=(flashcardIndex-1+cards.length)%cards.length;flashcardFlipped=false;renderFlashcards();}if(e.key==='ArrowRight'&&cards.length){flashcardIndex=(flashcardIndex+1)%cards.length;flashcardFlipped=false;renderFlashcards();}if(e.key===' '&&cards.length){e.preventDefault();flashcardFlipped=!flashcardFlipped;renderFlashcards();}}});$('#addQuickLink').onclick=()=>{data.quick_links.push({title:'',url:'',icon:'↗'});renderQuickLinkEditor();setTimeout(()=>document.querySelector('#quickLinkEditor .editor-row:last-child input')?.focus(),0);};$('#saveSettings').onclick=settings;$('#modalClose').onclick=closeModal;document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});$('#modal').onclick=e=>{if(e.target.id==='modal')closeModal()};$('#refreshHub').onclick=load;document.querySelectorAll('.filter').forEach(b=>b.onclick=()=>{taskFilter=b.dataset.filter;document.querySelectorAll('.filter').forEach(x=>x.classList.toggle('active',x===b));renderTasks();});let focusTimer=null,focusEndsAt=0;$('#focusBtn').onclick=()=>{if(focusTimer){clearInterval(focusTimer);focusTimer=null;$('#focusBtn').textContent='Start 25 min →';$('#statFocus').textContent='Ready';toast('Focus session stopped');return;}focusEndsAt=Date.now()+25*60*1000;const tick=()=>{const left=Math.max(0,focusEndsAt-Date.now()),mins=Math.floor(left/60000),secs=Math.floor((left%60000)/1000);$('#statFocus').textContent=`${mins}:${String(secs).padStart(2,'0')}`;$('#focusBtn').textContent=left?'Stop focus →':'Start 25 min →';if(!left){clearInterval(focusTimer);focusTimer=null;toast('Focus session complete');$('#statFocus').textContent='Ready';}};tick();focusTimer=setInterval(tick,1000);toast('Focus session started');};if(document.body.classList.contains('logged-in'))load();}
  const reset=()=>{data={profile:{},tasks:[],timetable:[],subjects:[],quick_links:[],flashcards:[]};renderAll();};
  return {init,load,go,reset};
})();
document.addEventListener('DOMContentLoaded',()=>Hub.init());
