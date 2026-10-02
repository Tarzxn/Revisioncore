const Hub = (() => {
  let data = { profile:{}, tasks:[], timetable:[], subjects:[], quick_links:[] };
  let taskFilter = 'all';
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const token = () => sessionStorage.getItem('forge.token') || '';
  const auth = (url, opts={}) => fetch(url, { ...opts, headers:{'Content-Type':'application/json','Authorization':`Bearer ${token()}`,...(opts.headers||{})} });
  const toast = msg => { const el=$('#toast'); el.textContent=msg; el.classList.add('show'); clearTimeout(window._toast); window._toast=setTimeout(()=>el.classList.remove('show'),2400); };
  const formatDate = d => { if(!d) return 'No date'; const x=new Date(d+'T12:00:00'); return isNaN(x)?d:x.toLocaleDateString('en-GB',{day:'numeric',month:'short'}); };
  const today = new Date();
  const dayName = today.toLocaleDateString('en-GB',{weekday:'long'});
  const todayISO = today.toISOString().slice(0,10);

  async function load(){
    const r=await auth('/api/student');
    if(r.status===401){ sessionStorage.removeItem('forge.token'); location.reload(); return; }
    const j=await r.json(); data=j.student||data;
    renderAll();
  }
  async function save(){ const r=await auth('/api/student',{method:'PUT',body:JSON.stringify(data)}); if(!r.ok){toast('Could not save changes');return false;} data=(await r.json()).student; return true; }
  function renderProfile(){
    const p=data.profile||{}; const name=p.display_name||p.username||'Student';
    $('#sidebarName').textContent=name; $('#sidebarUsername').textContent='@'+(p.username||'student'); $('#avatarInitial').textContent=name.charAt(0).toUpperCase();
    $('#welcomeTitle').textContent=`Good ${new Date().getHours()<12?'morning':new Date().getHours()<18?'afternoon':'evening'}, ${name.split(' ')[0]}.`;
    $('#welcomeSub').textContent=p.year_group ? `${p.year_group}${p.school?' · '+p.school:''} · ${dayName}` : `It’s ${dayName}. Add your year group in Settings to personalise this message.`;
    $('#pageTitle').textContent=`${dayName}`; $('#todayLabel').textContent=today.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
    $('#settingName').value=p.display_name||''; $('#settingYear').value=p.year_group||''; $('#settingSchool').value=p.school||'';
    $('#settingSubjects').value=(data.subjects||[]).map(x=>typeof x==='string'?x:x.name).join(', ');
    $('#settingLinks').value=(data.quick_links||[]).map(x=>`${x.title} | ${x.url}`).join('\n');
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
    $('#taskList').innerHTML=tasks.length?tasks.map(t=>`<div class="task-row glass ${t.done?'done':''}"><button class="check ${t.done?'checked':''}" data-task="${esc(t.id)}">${t.done?'✓':''}</button><div class="task-main"><strong>${esc(t.title)}</strong><div><span>${esc(t.subject)}</span><span>${t.due?formatDate(t.due):'No due date'}</span><span class="priority-label ${esc(t.priority)}">${esc(t.priority)}</span></div></div><button class="delete-task" data-task="${esc(t.id)}">×</button></div>`).join(''):'<div class="empty large-empty">No tasks in this view. Add one when you have something to remember.</div>';
    document.querySelectorAll('.check').forEach(b=>b.onclick=async()=>{const t=data.tasks.find(x=>x.id===b.dataset.task);t.done=!t.done;await save();renderAll();});
    document.querySelectorAll('.delete-task').forEach(b=>b.onclick=async()=>{await auth('/api/student/tasks/'+b.dataset.task,{method:'DELETE'});data.tasks=data.tasks.filter(x=>x.id!==b.dataset.task);renderAll();});
  }
  function renderSubjects(){ $('#subjectGrid').innerHTML=(data.subjects||[]).map((s,i)=>{const name=typeof s==='string'?s:s.name; const colour=['mint','blue','purple','orange','pink'][i%5]; return `<article class="subject-card glass ${colour}"><div class="subject-dot"></div><span>SUBJECT ${String(i+1).padStart(2,'0')}</span><h3>${esc(name)}</h3><p>Ask the AI tutor for a quiz, explanation or revision plan.</p><button class="text-button subject-ai" data-subject="${esc(name)}">Study ${esc(name)} →</button><button class="subject-remove" data-index="${i}">×</button></article>`}).join('') || '<div class="empty large-empty">No subjects yet. Add some in Settings or use “Add subject”.</div>'; document.querySelectorAll('.subject-ai').forEach(b=>b.onclick=()=>{go('assistant'); $('#prompt').value=`Help me revise ${b.dataset.subject}. Start by asking what topic I am studying.`; $('#prompt').focus();}); document.querySelectorAll('.subject-remove').forEach(b=>b.onclick=async()=>{data.subjects.splice(Number(b.dataset.index),1);await save();renderAll();}); }
  function renderAll(){renderProfile();renderStats();renderHome();renderTimetable();renderTasks();renderSubjects();}
  function go(view){document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id==='view-'+view));document.querySelectorAll('.nav-item[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));const titles={home:'STUDENT OVERVIEW',timetable:'YOUR SCHEDULE',tasks:'PLANNING',revision:'LEARNING',assistant:'STUDY COPILOT',settings:'PERSONALISE'};$('#pageKicker').textContent=titles[view]||'STUDENT HUB';window.scrollTo({top:0,behavior:'smooth'});}
  function modal(html){$('#modalContent').innerHTML=html;$('#modal').hidden=false;}
  function closeModal(){$('#modal').hidden=true;}
  function addTask(){modal(`<div class="modal-kicker">NEW TASK</div><h2>Add a task</h2><form id="taskForm" class="modal-form"><label>Task title<input id="mTaskTitle" required placeholder="e.g. Finish Biology worksheet"></label><div class="form-row"><label>Subject<input id="mTaskSubject" placeholder="Biology"></label><label>Due date<input id="mTaskDue" type="date"></label></div><label>Priority<select id="mTaskPriority"><option value="normal">Normal</option><option value="high">High</option><option value="low">Low</option></select></label><button class="primary-button" type="submit">Add task</button></form>`);$('#taskForm').onsubmit=async e=>{e.preventDefault();const r=await auth('/api/student/tasks',{method:'POST',body:JSON.stringify({title:$('#mTaskTitle').value,subject:$('#mTaskSubject').value,due:$('#mTaskDue').value,priority:$('#mTaskPriority').value})});if(!r.ok){toast('Could not add task');return;}data.tasks.push((await r.json()).task);closeModal();renderAll();toast('Task added');};}
  function addLesson(){modal(`<div class="modal-kicker">TIMETABLE</div><h2>Add a lesson</h2><form id="lessonForm" class="modal-form"><div class="form-row"><label>Day<select id="mDay">${['Monday','Tuesday','Wednesday','Thursday','Friday'].map(d=>`<option value="${d.toLowerCase()}">${d}</option>`).join('')}</select></label><label>Subject<input id="mSubject" required placeholder="Maths"></label></div><div class="form-row"><label>Start<input id="mStart" type="time" required></label><label>End<input id="mEnd" type="time" required></label></div><label>Room / teacher<input id="mRoom" placeholder="M2 · Ms Smith"></label><button class="primary-button" type="submit">Add lesson</button></form>`);$('#lessonForm').onsubmit=async e=>{e.preventDefault();data.timetable.push({id:crypto.randomUUID(),day:$('#mDay').value,subject:$('#mSubject').value,start:$('#mStart').value,end:$('#mEnd').value,room:$('#mRoom').value});await save();closeModal();renderAll();toast('Lesson added');};}
  function addSubject(){modal(`<div class="modal-kicker">REVISION</div><h2>Add a subject</h2><form id="subjectForm" class="modal-form"><label>Subject name<input id="mSubjectName" required placeholder="e.g. Computer Science"></label><button class="primary-button" type="submit">Add subject</button></form>`);$('#subjectForm').onsubmit=async e=>{e.preventDefault();data.subjects.push($('#mSubjectName').value.trim());await save();closeModal();renderAll();toast('Subject added');};}
  async function settings(){const links=$('#settingLinks').value.split('\n').map(x=>x.trim()).filter(Boolean).map((line,i)=>{const [title,...rest]=line.split('|');return {title:title.trim(),url:(rest.join('|').trim()||'#'),icon:['▦','T','☁','↗'][i%4]};}).filter(x=>x.title&&x.url!=='#');data.profile={...(data.profile||{}),display_name:$('#settingName').value.trim(),year_group:$('#settingYear').value.trim(),school:$('#settingSchool').value.trim()};data.quick_links=links;data.subjects=$('#settingSubjects').value.split(',').map(x=>x.trim()).filter(Boolean);if(await save()){renderAll();$('#settingsMessage').textContent='Saved successfully.';setTimeout(()=>$('#settingsMessage').textContent='',2200);toast('Settings saved');}}
  function init(){document.querySelectorAll('.nav-item[data-view]').forEach(b=>b.onclick=()=>go(b.dataset.view));document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>go(b.dataset.go));$('#addTaskBtn').onclick=addTask;$('#addLessonBtn').onclick=addLesson;$('#addSubjectBtn').onclick=addSubject;$('#saveSettings').onclick=settings;$('#modalClose').onclick=closeModal;$('#modal').onclick=e=>{if(e.target.id==='modal')closeModal()};$('#refreshHub').onclick=load;document.querySelectorAll('.filter').forEach(b=>b.onclick=()=>{taskFilter=b.dataset.filter;document.querySelectorAll('.filter').forEach(x=>x.classList.toggle('active',x===b));renderTasks();});$('#focusBtn').onclick=()=>{toast('Focus session started — 25 minutes');$('#statFocus').textContent='25 min';setTimeout(()=>$('#statFocus').textContent='Ready',1500000);};load();}
  return {init};
})();
document.addEventListener('DOMContentLoaded',()=>Hub.init());
