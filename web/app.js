const $ = (selector) => document.querySelector(selector);
const eventSource = new EventSource('/api/events');
let latest = null;

function pointKey([x, y]) { return `${x},${y}`; }
function esc(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function drawMap(state) {
  const root = $('#map');
  const walls = new Set(state.walls.map(pointKey));
  const blocked = new Set(state.blocked.map(pointKey));
  const routes = new Map();
  for (const robot of state.robots) for (const point of robot.route) {
    const key = pointKey(point);
    if (!routes.has(key)) routes.set(key, []);
    routes.get(key).push(robot.id.toLowerCase());
  }
  const robots = new Map(state.robots.map(robot => [pointKey(robot.pos), robot]));
  const pickups = new Map();
  state.tasks.filter(task => task.status !== 'complete').forEach(task => pickups.set(pointKey(task.pickup), task.id));
  const cells = [];
  for (let y = 0; y < state.height; y++) for (let x = 0; x < state.width; x++) {
    const key = `${x},${y}`;
    const robot = robots.get(key);
    const classes = ['cell', walls.has(key) ? 'wall' : '', blocked.has(key) ? 'blocked' : '', pointKey(state.staging) === key ? 'stage' : '', ...(routes.get(key) || []).map(id => `route-${id}`)].filter(Boolean).join(' ');
    cells.push(`<div class="${classes}" data-x="${x}" data-y="${y}" title="${x}, ${y}${pickups.has(key) ? ` · ${pickups.get(key)}` : ''}">${robot ? `<span class="robot ${robot.id.toLowerCase()}" title="${robot.id}: ${esc(robot.state)}">${robot.id}</span>` : ''}${pickups.has(key) && !robot ? `<span class="task-marker">${esc(pickups.get(key))}</span>` : ''}</div>`);
  }
  root.innerHTML = cells.join('');
  root.querySelectorAll('.cell:not(.wall)').forEach(cell => cell.addEventListener('click', () => {
    const x = Number(cell.dataset.x), y = Number(cell.dataset.y);
    const isBlocked = cell.classList.contains('blocked');
    post('/api/blockage', {x, y, blocked: !isBlocked});
  }));
}

function render(state) {
  latest = state;
  $('#connection').textContent = 'Connected';
  $('#collisions').textContent = state.metrics.collisions;
  $('#completed').textContent = state.metrics.completed;
  $('#task-total').textContent = ` / ${state.metrics.totalTasks}`;
  $('#tick').textContent = state.tick;
  $('#deadlocks').textContent = state.metrics.deadlocks;
  $('#run-state').textContent = state.running ? 'RUNNING' : 'PAUSED';
  $('#run').innerHTML = state.running ? '<span>Ⅱ</span> Pause' : '<span>▶</span> Run';
  document.querySelectorAll('.mode').forEach(button => button.classList.toggle('active', button.dataset.mode === state.mode));
  const active = state.robots.filter(r => r.battery > 0).length;
  $('#robot-count').textContent = `${active} ACTIVE`;
  $('#fleet').innerHTML = state.robots.map(robot => {
    const task = state.tasks.find(t => t.id === robot.task_id);
    return `<div class="fleet-row"><span class="fleet-badge ${robot.id.toLowerCase()}">${robot.id}</span><div><div class="fleet-name">${robot.id}</div><div class="fleet-task">${task ? `${task.id} · ${robot.loaded ? 'carrying' : 'pickup run'}` : 'No active assignment'}</div></div><span class="state-tag ${robot.state.replaceAll(' ', '-')} ">${esc(robot.state)}</span><div class="battery-row"><div class="battery-track"><div class="battery-fill" style="width:${robot.battery}%"></div></div><span class="battery-value">${robot.battery}%</span></div></div>`;
  }).join('');
  const queued = state.tasks.filter(task => task.status === 'queued').length;
  $('#queue-count').textContent = `${queued} QUEUED`;
  $('#tasks').innerHTML = state.tasks.map(task => `<div class="task-row"><span class="task-id">${esc(task.id)}</span><span class="task-route">${task.pickup.join(',')} → ${task.destination.join(',')}</span><span class="task-status ${task.status}">${esc(task.status.toUpperCase())}</span></div>`).join('');
  $('#events').innerHTML = state.events.slice(0, 18).map(event => `<div class="event-row"><span class="event-time">T+${String(event.tick).padStart(3, '0')}</span><span class="event-message" data-kind="${esc(event.kind)}">${esc(event.message)}</span></div>`).join('');
  drawMap(state);
}

async function post(path, payload) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  render(data);
  return data;
}

async function compare() {
  const button = $('#compare');
  button.disabled = true;
  button.textContent = 'Measuring…';
  $('#report').textContent = 'Running identical task sets through both simulation modes…';
  try {
    const response = await fetch('/api/compare');
    const result = await response.json();
    $('#report').innerHTML = `<div class="report-result"><div><span>STOP-AND-WAIT</span><strong>${result.baseline.ticks} ticks</strong></div><div><span>SWARMSYNC</span><strong class="winner">${result.swarm.ticks} ticks</strong></div><div><span>TIME CHANGE</span><strong class="${result.targetMet ? 'winner' : ''}">${result.timeReductionPercent}%</strong></div><div><span>BASELINE COLLISIONS</span><strong>${result.baseline.collisions}</strong></div><div><span>SWARMSYNC COLLISIONS</span><strong>${result.swarm.collisions}</strong></div><div><span>SWARMSYNC DEADLOCKS</span><strong>${result.swarm.deadlocks}</strong></div><div><span>20% TARGET</span><strong class="${result.targetMet ? 'winner' : ''}">${result.targetMet ? 'MET' : 'NOT MET'}</strong></div></div>`;
  } catch (error) { $('#report').textContent = error.message; }
  finally { button.disabled = false; button.innerHTML = 'Run comparison <span>→</span>'; }
}

eventSource.onmessage = event => render(JSON.parse(event.data));
eventSource.onerror = () => { $('#connection').textContent = 'Reconnecting'; };
$('#run').addEventListener('click', () => post('/api/control', {action: latest?.running ? 'pause' : 'run'}));
$('#step').addEventListener('click', () => post('/api/control', {action: 'step'}));
$('#reset').addEventListener('click', () => post('/api/control', {action: 'reset'}));
$('#clear-blockages').addEventListener('click', async () => {
  if (!latest) return;
  for (const [x, y] of latest.blocked) await post('/api/blockage', {x, y, blocked: false});
});
document.querySelectorAll('.mode').forEach(button => button.addEventListener('click', () => post('/api/control', {action: 'mode', mode: button.dataset.mode})));
$('#compare').addEventListener('click', compare);
$('#run-compare').addEventListener('click', compare);

fetch('/api/state').then(response => response.json()).then(render).catch(() => { $('#connection').textContent = 'Offline'; });
