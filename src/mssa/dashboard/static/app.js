"use strict";

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clone = (value) => structuredClone(value);
const colors = {friendly: "#66dac4", hostile: "#fa8b80", neutral: "#f0c672"};
const affiliations = {friendly: "Aliado", hostile: "Adversário", neutral: "Neutro"};
const policyNames = {patrol: "Patrulha", react: "Reação", idle: "Em espera", react_approach: "Aproximando", react_avoid: "Afastando", react_hold: "Parado por contato"};
const eventNames = {sent: "Enviada", delivered: "Entregue", lost: "Perdida", out_of_range: "Sem alcance", queue_full: "Fila cheia", expired: "Expirada"};
const freshScenario = () => ({schema_version: 1, environment: {width: 1000, height: 700}, simulation: {duration: 120, dt: 0.25, seed: 42}, agents: [], communication_links: [], mission: null});
let draft = freshScenario(), frame = null, sessionId = null, selected = null, examples = [];
let dirty = true, busy = false, playing = false, timer = null, tab = "agent", mapMode = null;
let events = [], trails = new Map(), zoom = 1, pan = {x: 0, y: 0};
let transform = {scale: 1, x: 0, y: 0}, drag = null;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    const details = (data.details || []).map((item) => `${item.loc.join(" → ")}: ${item.msg}`).join("\n");
    throw new Error(`${data.error || "Não foi possível concluir a operação."}${details ? "\n" + details : ""}`);
  }
  return data;
}
function notice(message = "", success = false) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
  $("notice").className = success ? "success" : "";
}
function persist() { try { localStorage.setItem("mssa.scenario.v1", JSON.stringify(draft)); } catch { /* Export remains available. */ } }
function stop() { playing = false; clearTimeout(timer); updateControls(); }
function markDirty() { stop(); dirty = true; persist(); notice(); renderList(); updateControls(); }
function currentAgent() { return draft.agents.find((agent) => agent.id === selected); }
function displayedWorld() {
  return dirty || !frame ? {time: 0, ...draft.environment, agents: draft.agents.map((a) => ({...a, agent_id: a.id}))} : frame.world;
}
function updateControls() {
  $("play").textContent = playing ? "Ⅱ Pausar" : "▶ Executar";
  $("play").disabled = dirty || !sessionId || (frame?.finished ?? false) || (busy && !playing);
  $("step").disabled = dirty || busy || playing || !sessionId || (frame?.finished ?? false);
  $("apply").disabled = busy;
  $("reset").disabled = busy || !sessionId;
  $("export-state").disabled = dirty || !frame;
  for (const id of ["new", "import", "export", "examples", "add-agent"]) $(id).disabled = busy;
  document.querySelectorAll("#editor input, #editor select, #editor textarea, #editor button, #world-fields input").forEach((node) => { node.disabled = busy; });
  $("dirty-label").textContent = dirty ? "Alterações pendentes · aplique para executar" : "Cenário aplicado";
  $("dirty-label").className = dirty ? "status-dirty" : "";
  $("status-label").textContent = busy ? "Processando…" : dirty ? "Editando cenário" : playing ? "Simulação em execução" : frame?.finished ? "Execução concluída" : "Simulação pausada";
  $("map-mode").hidden = !mapMode;
  $("map-mode").textContent = mapMode === "position" ? "Clique no mapa para posicionar o agente · Esc cancela" : "Clique no mapa para adicionar pontos à rota · Esc encerra";
  $("map-title").textContent = $("local-view").checked ? "Percepção do agente" : dirty ? "Editor espacial" : "Visão do mundo";
}
function field(label, key, value, opts = {}) {
  return `<label>${esc(label)}<input type="number" step="any" required data-key="${esc(key)}" value="${esc(value)}" ${opts.min !== undefined ? `min="${opts.min}"` : ""} ${opts.max !== undefined ? `max="${opts.max}"` : ""}></label>`;
}
function options(values, value) { return Object.entries(values).map(([key, label]) => `<option value="${esc(key)}" ${key === value ? "selected" : ""}>${esc(label)}</option>`).join(""); }
function renderWorldFields() {
  $("world-fields").innerHTML = field("Largura (m)", "width", draft.environment.width, {min: 1}) + field("Altura (m)", "height", draft.environment.height, {min: 1}) + field("Duração (s)", "duration", draft.simulation.duration, {min: .001}) + field("Passo (s)", "dt", draft.simulation.dt, {min: .001}) + field("Semente", "seed", draft.simulation.seed, {min: 0});
  $("world-fields").querySelector('[data-key="seed"]').step = "1";
  $("world-fields").querySelectorAll("input").forEach((input) => input.addEventListener("change", () => {
    if (!input.reportValidity()) return;
    const key = input.dataset.key;
    (key === "width" || key === "height" ? draft.environment : draft.simulation)[key] = input.valueAsNumber;
    markDirty();
  }));
}
function renderList() {
  $("agent-count").textContent = draft.agents.length;
  $("agent-list").innerHTML = draft.agents.length ? draft.agents.map((agent, index) => {
    const live = !dirty && frame ? frame.world.agents.find((a) => a.agent_id === agent.id) : agent;
    const mode = !dirty && frame?.policies[agent.id]?.mode;
    return `<button class="agent-item ${selected === agent.id ? "selected" : ""}" data-index="${index}"><span class="agent-symbol" style="color:${colors[agent.affiliation]}">◈</span><span><strong>${esc(agent.id)}</strong><small>${affiliations[agent.affiliation]} · ${policyNames[mode] || policyNames[agent.policy?.kind] || "Movimento constante"}</small><span class="agent-meta">${Number(live?.x || 0).toFixed(0)}, ${Number(live?.y || 0).toFixed(0)} m</span></span></button>`;
  }).join("") : '<p class="empty">Adicione o primeiro agente para criar seu cenário.</p>';
  $("agent-list").querySelectorAll("button").forEach((button) => button.addEventListener("click", () => selectAgent(draft.agents[Number(button.dataset.index)].id)));
  renderLiveInfo();
}
function selectAgent(id) { selected = id; mapMode = null; renderList(); renderEditor(); updateControls(); }
function renderLiveInfo() {
  const context = !dirty && frame?.contexts.find((c) => c.own_state.agent_id === selected);
  $("live-info").textContent = context ? `${context.own_state.speed.toFixed(1)} m/s · ${context.own_state.heading.toFixed(0)}° · ${context.observations.length} medições locais · ${context.messages.length} relatórios recebidos` : "";
}
function bindNumeric(root, callback) {
  root.querySelectorAll('input[type="number"]').forEach((input) => input.addEventListener("change", () => {
    if (!input.reportValidity()) return;
    callback(input.dataset.key, input.valueAsNumber, input);
    markDirty();
  }));
}
function renderEditor() {
  document.querySelectorAll("[data-tab]").forEach((button) => { button.classList.toggle("active", button.dataset.tab === tab); button.setAttribute("aria-selected", String(button.dataset.tab === tab)); });
  const editor = $("editor"), agent = currentAgent();
  if (tab === "agent") {
    if (!agent) { editor.innerHTML = '<p class="empty">Selecione ou adicione um agente para configurar sensores e políticas.</p>'; return; }
    const policy = agent.policy;
    editor.innerHTML = `<label class="field">Identificador<input id="agent-id" value="${esc(agent.id)}" required></label>
      <label class="field">Afiliação<select id="affiliation">${options(affiliations, agent.affiliation)}</select></label>
      <div id="agent-numbers" class="field-grid">${field("X (m)", "x", agent.x)}${field("Y (m)", "y", agent.y)}${field("Velocidade inicial", "speed", agent.speed ?? 0, {min: 0})}${field("Orientação (°)", "heading", agent.heading ?? 0)}</div>
      <div class="actions"><button id="place-agent">Posicionar no mapa</button><button id="delete-agent" class="danger">Excluir agente</button></div>
      <hr><h3>Política de movimento</h3><label class="field">Comportamento<select id="policy-kind">${options({none: "Movimento constante", patrol: "Patrulha por pontos", react: "Reação a contatos"}, policy?.kind || "none")}</select></label>
      ${policy ? `<div id="policy-numbers" class="field-grid">${field("Velocidade (m/s)", "speed", policy.speed, {min: 0})}${field("Raio de chegada (m)", "arrival_radius", policy.arrival_radius ?? 1, {min: 0})}</div>
      ${policy.kind === "react" ? `<label class="field">Ao receber contato<select id="reaction">${options({approach:"Aproximar da medição", avoid:"Afastar da medição", hold:"Parar"}, policy.reaction)}</select></label><div id="reaction-numbers" class="field-grid">${field("Distância de reação", "reaction_distance", policy.reaction_distance, {min: .001})}${field("Idade máxima (s)", "max_observation_age", policy.max_observation_age, {min: .001})}</div><label class="check"><input id="use-messages" type="checkbox" ${policy.use_messages ? "checked" : ""}>Usar relatórios recebidos</label><p class="hint">Contatos anônimos: não há distinção automática de afiliação. Sem contato válido, segue a rota ou aguarda.</p>` : ""}
      <label class="field">Pontos da rota · x, y por linha<textarea id="waypoints" rows="4" spellcheck="false">${esc(policy.waypoints.map((p) => `${p.x}, ${p.y}`).join("\n"))}</textarea></label><button id="plot-route" class="wide-button">+ Adicionar pontos no mapa</button><label class="check"><input id="loop" type="checkbox" ${policy.loop ? "checked" : ""}>Repetir rota</label>` : ""}
      <hr><h3>Sensores <span class="hint">${agent.sensors.length}</span></h3><div id="sensors">${agent.sensors.map((sensor, i) => `<section class="sub-card" data-sensor="${i}"><div class="card-heading"><strong>Sensor ${i + 1}</strong><button data-remove-sensor="${i}">Remover</button></div><label class="field">Identificador<input data-sensor-id="${i}" value="${esc(sensor.id)}" required></label><div class="field-grid">${field("Alcance (m)", "range", sensor.range, {min: .001})}${field("Campo de visão (°)", "field_of_view", sensor.field_of_view ?? 360, {min: .001, max:360})}${field("Desvio de orientação", "heading_offset", sensor.heading_offset ?? 0)}${field("Período (s)", "period", sensor.period ?? 1, {min: .001})}${field("Prob. de detecção", "probability_of_detection", sensor.probability_of_detection ?? 1, {min:0,max:1})}${field("Ruído posição (m)", "position_std", sensor.position_std ?? 0, {min:0})}</div></section>`).join("")}</div><button id="add-sensor" class="wide-button">+ Adicionar sensor</button>`;
    $("agent-id").addEventListener("change", (event) => {
      const id = event.target.value.trim(), old = agent.id;
      if (!id || draft.agents.some((a) => a !== agent && a.id === id)) { event.target.value = old; notice("Use um identificador único e não vazio."); return; }
      agent.id = id; selected = id;
      for (const link of draft.communication_links) { if (link.sender_id === old) link.sender_id = id; if (link.recipient_id === old) link.recipient_id = id; }
      if (draft.mission) for (const key of ["observer_ids", "target_ids"]) draft.mission[key] = draft.mission[key].map((v) => v === old ? id : v);
      markDirty();
    });
    $("affiliation").onchange = (event) => { agent.affiliation = event.target.value; markDirty(); };
    bindNumeric($("agent-numbers"), (key, value) => { agent[key] = value; });
    $("place-agent").onclick = () => { stop(); $("local-view").checked = false; mapMode = "position"; updateControls(); };
    $("delete-agent").onclick = () => {
      draft.agents = draft.agents.filter((a) => a !== agent);
      draft.communication_links = draft.communication_links.filter((l) => l.sender_id !== agent.id && l.recipient_id !== agent.id);
      if (draft.mission) {
        for (const key of ["observer_ids", "target_ids"]) draft.mission[key] = draft.mission[key].filter((id) => id !== agent.id);
        if (!draft.mission.observer_ids.length || !draft.mission.target_ids.length) draft.mission = null;
      }
      selected = draft.agents[0]?.id ?? null; markDirty(); renderEditor();
    };
    $("policy-kind").onchange = (event) => {
      const kind = event.target.value;
      agent.policy = kind === "none" ? null : {kind, speed:20, arrival_radius:1, loop:true, reaction:"approach", reaction_distance:250, max_observation_age:5, use_messages:true, waypoints:kind === "patrol" ? [{x:agent.x + 120,y:agent.y},{x:agent.x,y:agent.y + 120}] : []};
      markDirty(); renderEditor();
    };
    if (policy) {
      bindNumeric($("policy-numbers"), (key, value) => { policy[key] = value; });
      if (policy.kind === "react") {
        bindNumeric($("reaction-numbers"), (key, value) => { policy[key] = value; });
        $("reaction").onchange = (event) => { policy.reaction = event.target.value; markDirty(); };
        $("use-messages").onchange = (event) => { policy.use_messages = event.target.checked; markDirty(); };
      }
      $("waypoints").onchange = (event) => {
        try {
          const points = event.target.value.split("\n").filter((line) => line.trim()).map((line) => {
            const parts = line.split(",").map((v) => v.trim());
            if (parts.length !== 2 || parts.some((v) => !v || !Number.isFinite(Number(v)))) throw new Error("Use um ponto por linha, no formato x, y. Exemplo: 300, 200.");
            return {x:Number(parts[0]),y:Number(parts[1])};
          });
          event.target.setCustomValidity(""); policy.waypoints = points; markDirty();
        } catch (error) { event.target.setCustomValidity(error.message); notice(error.message); }
      };
      $("plot-route").onclick = () => { stop(); $("local-view").checked = false; mapMode = "waypoint"; updateControls(); };
      $("loop").onchange = (event) => { policy.loop = event.target.checked; markDirty(); };
    }
    editor.querySelectorAll("[data-sensor]").forEach((card) => bindNumeric(card, (key, value) => { agent.sensors[Number(card.dataset.sensor)][key] = value; }));
    editor.querySelectorAll("[data-sensor-id]").forEach((input) => { input.onchange = () => { agent.sensors[Number(input.dataset.sensorId)].id = input.value; markDirty(); }; });
    editor.querySelectorAll("[data-remove-sensor]").forEach((button) => { button.onclick = () => { agent.sensors.splice(Number(button.dataset.removeSensor),1); markDirty(); renderEditor(); }; });
    $("add-sensor").onclick = () => {
      let n = 1; while (agent.sensors.some((s) => s.id === `sensor-${n}`)) n++;
      agent.sensors.push({id:`sensor-${n}`,range:200,field_of_view:120,heading_offset:0,period:1,probability_of_detection:1,position_std:0}); markDirty(); renderEditor();
    };
  } else if (tab === "links") {
    const agentOptions = Object.fromEntries(draft.agents.map((a) => [a.id,a.id]));
    editor.innerHTML = '<p class="hint">Cada enlace envia as novas varreduras da origem. A direção inversa exige outro enlace.</p>' + draft.communication_links.map((link, index) => `<section class="sub-card" data-link="${index}"><div class="card-heading"><strong>Enlace ${index + 1}</strong><button data-remove-link="${index}">Remover</button></div><label class="field">Origem<select data-endpoint="sender_id">${options(agentOptions,link.sender_id)}</select></label><label class="field">Destino<select data-endpoint="recipient_id">${options(agentOptions,link.recipient_id)}</select></label><div class="field-grid">${field("Alcance (m)","range",link.range,{min:.001})}${field("Latência (s)","latency",link.latency,{min:0})}${field("Prob. de perda","loss_probability",link.loss_probability,{min:0,max:1})}${field("Fila (mensagens)","queue_capacity",link.queue_capacity,{min:1,max:1000})}${field("Validade / TTL (s)","ttl",link.ttl,{min:.001})}</div></section>`).join("") + '<button id="add-link" class="wide-button">+ Adicionar enlace</button><p class="hint">A fila limita mensagens em trânsito. Largura de banda e roteamento ainda não são modelados.</p>';
    editor.querySelectorAll("[data-link]").forEach((card) => {
      const link = draft.communication_links[Number(card.dataset.link)];
      bindNumeric(card, (key,value) => { link[key] = value; });
      card.querySelectorAll("[data-endpoint]").forEach((select) => { select.onchange = () => { link[select.dataset.endpoint] = select.value; markDirty(); }; });
    });
    editor.querySelectorAll("[data-remove-link]").forEach((button) => { button.onclick = () => { draft.communication_links.splice(Number(button.dataset.removeLink),1); markDirty(); renderEditor(); }; });
    $("add-link").onclick = () => {
      if (draft.agents.length < 2) { notice("Adicione pelo menos dois agentes para criar um enlace."); return; }
      const sender = currentAgent() || draft.agents[0], recipient = draft.agents.find((a) => a !== sender);
      draft.communication_links.push({sender_id:sender.id,recipient_id:recipient.id,range:400,latency:1,loss_probability:.1,queue_capacity:8,ttl:5}); markDirty(); renderEditor();
    };
  } else {
    const multi = (ids) => draft.agents.map((a) => `<option value="${esc(a.id)}" ${ids.includes(a.id) ? "selected" : ""}>${esc(a.id)}</option>`).join("");
    editor.innerHTML = `<label class="check"><input id="enable-mission" type="checkbox" ${draft.mission ? "checked" : ""}>Avaliar missão de observação</label>${draft.mission ? `<label class="field">Observadores (precisam de sensor)<select id="observers" multiple>${multi(draft.mission.observer_ids)}</select></label><label class="field">Alvos exigidos<select id="targets" multiple>${multi(draft.mission.target_ids)}</select></label><p class="hint">Use Ctrl/Cmd para selecionar vários. A missão pontua detecções locais, não a entrega de mensagens.</p>` : ""}<hr><h3>YAML / JSON</h3><p class="hint">Cole uma configuração completa ou ajuste os valores abaixo. Carregar texto atualiza o editor; aplicar reinicia a simulação.</p><textarea id="raw-scenario" class="yaml-editor" spellcheck="false" aria-label="Cenário em YAML ou JSON"></textarea><button id="load-text" class="wide-button">Carregar texto no editor</button>`;
    $("raw-scenario").value = JSON.stringify(draft,null,2);
    $("enable-mission").onchange = (event) => { draft.mission = event.target.checked ? {kind:"observe_targets",observer_ids:[],target_ids:[]} : null; markDirty(); renderEditor(); };
    if (draft.mission) for (const [id,key] of [["observers","observer_ids"],["targets","target_ids"]]) $(id).onchange = () => { draft.mission[key] = [...$(id).selectedOptions].map((o) => o.value); markDirty(); };
    $("load-text").onclick = async () => { try { const data = await api("/api/validate",{scenario:$("raw-scenario").value}); loadDraft(data.scenario); notice("Texto carregado. Aplique o cenário para executar.",true); } catch(error) { notice(error.message); } };
  }
  updateControls();
}
function loadDraft(scenario) {
  stop(); draft = clone(scenario); selected = draft.agents[0]?.id ?? null; dirty = true; mapMode = null; zoom = 1; pan = {x:0,y:0}; persist(); renderWorldFields(); renderList(); renderEditor(); updateControls();
}
async function applyScenario() {
  if (busy) return;
  const invalid = [...document.querySelectorAll("#editor input, #editor textarea, #world-fields input")].find((input) => !input.checkValidity());
  if (invalid) { invalid.reportValidity(); return; }
  stop(); busy = true; notice(); updateControls();
  try {
    const data = await api("/api/sessions",{scenario:draft,replace_id:sessionId});
    sessionId = data.session_id; draft = data.scenario; frame = data; dirty = false; mapMode = null;
    if (!draft.agents.some((a) => a.id === selected)) selected = draft.agents[0]?.id ?? null;
    events = []; trails = new Map(); persist(); renderWorldFields(); renderEditor(); updateFrame(data);
  } catch(error) { notice(error.message); }
  finally { busy = false; updateControls(); }
}
function updateFrame(data) {
  frame = data;
  for (const agent of data.world.agents) {
    const trail = trails.get(agent.agent_id) || [];
    trail.push([agent.x,agent.y]); if (trail.length > 600) trail.shift(); trails.set(agent.agent_id,trail);
  }
  const now = performance.now();
  events.push(...(data.events || []).map((event) => ({...event,seenAt:now})));
  events = events.slice(-200);
  $("time").innerHTML = `${data.world.time.toFixed(2)} <small>s</small>`;
  $("detections").textContent = data.total_detections;
  $("sent").textContent = data.network.enqueued;
  $("delivered").textContent = data.network.delivered;
  $("pending").textContent = data.network.pending;
  const status = {in_progress:"Em andamento",succeeded:"Concluída",timeout:"Tempo esgotado"};
  $("mission").textContent = data.mission ? status[data.mission.status] : "Sem missão";
  $("event-count").textContent = `${events.length} eventos recentes`;
  $("events").innerHTML = events.length ? events.slice().reverse().map((event) => `<div class="event-row"><time>${event.time.toFixed(2)} s</time><span class="${event.status}">${eventNames[event.status]}</span><span class="route-label">${esc(event.sender_id)} → ${esc(event.recipient_id)}</span></div>`).join("") : '<p class="empty">Nenhuma transmissão até o momento. Configure sensores e enlaces para gerar tráfego.</p>';
  if (data.finished) stop();
  renderList(); updateControls();
}
async function stepOnce() {
  if (busy || dirty || !sessionId || frame?.finished) return;
  busy = true; updateControls();
  try { updateFrame(await api(`/api/sessions/${sessionId}/step`,{steps:1})); }
  catch(error) { stop(); notice(error.message); }
  finally { busy = false; updateControls(); }
  if (playing) timer = setTimeout(stepOnce,Math.max(25,draft.simulation.dt * 1000 / Number($("speed").value)));
}
function download(name, contents, type) {
  const url = URL.createObjectURL(new Blob([contents],{type}));
  const link = document.createElement("a"); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
}

// Canvas coordinates stay in meters; rendering and playback never change physics.
const canvas = $("map"), ctx = canvas.getContext("2d");
function point(x,y) { return {x:transform.x + x * transform.scale,y:transform.y - y * transform.scale}; }
function worldPoint(x,y) { return {x:(x-transform.x)/transform.scale,y:(transform.y-y)/transform.scale}; }
function line(a,b,color,width=1,dash=[]) { ctx.beginPath(); ctx.setLineDash(dash); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.strokeStyle=color; ctx.lineWidth=width; ctx.stroke(); ctx.setLineDash([]); }
function ring(x,y,r,color,dash=[]) { const p=point(x,y); ctx.beginPath(); ctx.arc(p.x,p.y,Math.max(0,r*transform.scale),0,Math.PI*2); ctx.setLineDash(dash); ctx.strokeStyle=color; ctx.lineWidth=1; ctx.stroke(); ctx.setLineDash([]); }
function draw(now) {
  const rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(rect.width*ratio) || canvas.height !== Math.round(rect.height*ratio)) { canvas.width=Math.round(rect.width*ratio); canvas.height=Math.round(rect.height*ratio); }
  ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,rect.width,rect.height);
  const world=displayedWorld(), w=world.width, h=world.height;
  transform.scale=Math.min((rect.width-65)/w,(rect.height-65)/h)*zoom;
  transform.x=(rect.width-w*transform.scale)/2+pan.x; transform.y=(rect.height+h*transform.scale)/2+pan.y;
  const local=$("local-view").checked, selectedAgent=world.agents.find((a) => a.agent_id === selected);
  const tl=point(0,h); ctx.fillStyle="#0f1e2c"; ctx.fillRect(tl.x,tl.y,w*transform.scale,h*transform.scale);
  const spacing=10**Math.floor(Math.log10(Math.max(w,h)/8));
  ctx.font="9px ui-monospace,monospace"; ctx.fillStyle="#49617a";
  for(let x=0;x<=w && x/spacing<1000;x+=spacing) { line(point(x,0),point(x,h),"#1b3043"); const p=point(x,0); ctx.fillText(String(Math.round(x)),p.x+3,p.y+14); }
  for(let y=0;y<=h && y/spacing<1000;y+=spacing) { line(point(0,y),point(w,y),"#1b3043"); const p=point(0,y); ctx.fillText(String(Math.round(y)),p.x-28,p.y+3); }
  ctx.strokeStyle="#344d63"; ctx.strokeRect(tl.x,tl.y,w*transform.scale,h*transform.scale);
  const visible=local ? world.agents.filter((a) => a.agent_id===selected) : world.agents;
  if($("layer-radio").checked) for(const link of draft.communication_links) {
    const source=world.agents.find((a) => a.agent_id===link.sender_id), destination=world.agents.find((a) => a.agent_id===link.recipient_id);
    if(!source || !destination || (local && source.agent_id!==selected)) continue;
    ring(source.x,source.y,link.range,"#75aaff25",[4,5]);
    if(!local) { const reachable=Math.hypot(source.x-destination.x,source.y-destination.y)<=link.range; line(point(source.x,source.y),point(destination.x,destination.y),reachable?"#75aaff60":"#fa8b8040",1,[4,5]); }
  }
  for(const agent of visible) {
    const config=draft.agents.find((a)=>a.id===agent.agent_id), color=colors[agent.affiliation] || colors.neutral;
    if($("layer-trails").checked && !dirty) {
      const trail=trails.get(agent.agent_id)||[];
      for(let i=1;i<trail.length;i++) line(point(...trail[i-1]),point(...trail[i]),color+"55",1.4);
    }
    if($("layer-routes").checked && config?.policy?.waypoints.length) {
      const route=config.policy.waypoints;
      for(let i=0;i<route.length;i++) {
        const p=point(route[i].x,route[i].y), next=route[i+1] || (config.policy.loop?route[0]:null);
        if(next) line(p,point(next.x,next.y),color+"60",1,[4,4]);
        ctx.beginPath();ctx.arc(p.x,p.y,4,0,Math.PI*2);ctx.fillStyle="#0d1823";ctx.fill();ctx.strokeStyle=color;ctx.stroke();ctx.fillStyle=color;ctx.fillText(String(i+1),p.x+7,p.y-5);
      }
    }
    if($("layer-sensors").checked) for(const sensor of config?.sensors || []) {
      const p=point(agent.x,agent.y), radius=sensor.range*transform.scale;
      const heading=-(agent.heading+(sensor.heading_offset||0))*Math.PI/180, half=(sensor.field_of_view||360)*Math.PI/360;
      ctx.beginPath(); if(sensor.field_of_view<360) ctx.moveTo(p.x,p.y);
      ctx.arc(p.x,p.y,radius,heading-half,heading+half); ctx.closePath(); ctx.fillStyle=color+"0d";ctx.strokeStyle=color+"50";ctx.lineWidth=1;ctx.fill();ctx.stroke();
    }
  }
  if(!dirty && frame && !local && $("layer-radio").checked) {
    for(const message of frame.pending_messages) {
      const a=world.agents.find((a)=>a.agent_id===message.sender_id), b=world.agents.find((a)=>a.agent_id===message.recipient_id); if(!a||!b)continue;
      const from=point(a.x,a.y),to=point(b.x,b.y);
      const f=Math.min(.95,Math.max(.05,(world.time-message.sent_at)/Math.max(draft.simulation.dt,message.deliver_at-message.sent_at)));
      const p={x:from.x+(to.x-from.x)*f,y:from.y+(to.y-from.y)*f};
      ctx.beginPath();ctx.arc(p.x,p.y,3.5,0,Math.PI*2);ctx.fillStyle="#91bfff";ctx.shadowColor="#75aaff";ctx.shadowBlur=10;ctx.fill();ctx.shadowBlur=0;
    }
    for(const event of events) {
      const age=(now-event.seenAt)/1000; if(age>1.8)continue;
      const color=event.status==="delivered"?colors.friendly:event.status==="sent"?"#75aaff":colors.hostile;
      ctx.globalAlpha=Math.max(0,1-age/1.8); const a=point(...event.sender_position),b=point(...event.recipient_position);
      line(a,b,color,1.4);
      const p=event.status==="sent"?a:b;ctx.beginPath();ctx.arc(p.x,p.y,8+age*14,0,Math.PI*2);ctx.strokeStyle=color;ctx.stroke();ctx.globalAlpha=1;
    }
  }
  if(!dirty && selectedAgent && frame) {
    const context=frame.contexts.find((c)=>c.own_state.agent_id===selected);
    for(const observation of context?.observations || []) drawObservation(observation,"#f4d087");
    for(const message of context?.messages || []) for(const observation of message.observations) drawObservation(observation,"#89b8ff");
  }
  for(const agent of visible) {
    const p=point(agent.x,agent.y),color=colors[agent.affiliation]||colors.neutral,isSelected=agent.agent_id===selected;
    if(isSelected){ctx.beginPath();ctx.arc(p.x,p.y,14,0,Math.PI*2);ctx.strokeStyle=color+"a0";ctx.lineWidth=1;ctx.stroke();}
    ctx.save();ctx.translate(p.x,p.y);ctx.rotate(-agent.heading*Math.PI/180);ctx.beginPath();ctx.moveTo(9,0);ctx.lineTo(-6,-5.5);ctx.lineTo(-3,0);ctx.lineTo(-6,5.5);ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.restore();
    ctx.font="11px system-ui,sans-serif";ctx.fillStyle=isSelected?"#f1f7ff":"#b0c2d5";ctx.fillText(agent.agent_id,p.x+13,p.y-10);
  }
  if(local && !selectedAgent){ctx.fillStyle="#8ca2b9";ctx.font="13px system-ui";ctx.fillText("Selecione um agente para visualizar sua percepção.",30,50);}
  requestAnimationFrame(draw);
}
function drawObservation(observation,color) {
  const p=point(observation.x,observation.y);line({x:p.x-4,y:p.y},{x:p.x+4,y:p.y},color,1.5);line({x:p.x,y:p.y-4},{x:p.x,y:p.y+4},color,1.5);
  if(observation.position_std>0)ring(observation.x,observation.y,observation.position_std*2,color+"70");
}
canvas.addEventListener("pointerdown",(event)=>{ if(event.button!==0)return; drag={x:event.offsetX,y:event.offsetY,panX:pan.x,panY:pan.y,moved:false};canvas.setPointerCapture(event.pointerId); });
canvas.addEventListener("pointermove",(event)=>{
  const p=worldPoint(event.offsetX,event.offsetY);$("map-coordinates").textContent=`${p.x.toFixed(0)}, ${p.y.toFixed(0)} m`;
  if(drag){const dx=event.offsetX-drag.x,dy=event.offsetY-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;if(drag.moved){pan.x=drag.panX+dx;pan.y=drag.panY+dy;}}
});
canvas.addEventListener("pointerup",(event)=>{
  if(!drag)return;const moved=drag.moved;drag=null;if(moved||busy)return;
  const p=worldPoint(event.offsetX,event.offsetY), agent=currentAgent();
  if(mapMode && agent){
    const position={x:Math.round(p.x),y:Math.round(p.y)};
    if(mapMode==="position"){Object.assign(agent,position);mapMode=null;}else if(agent.policy)agent.policy.waypoints.push(position);
    markDirty();renderEditor();return;
  }
  const candidates=displayedWorld().agents.filter((a)=>!$("local-view").checked||a.agent_id===selected);
  const hit=candidates.find((a)=>{const pixel=point(a.x,a.y);return Math.hypot(pixel.x-event.offsetX,pixel.y-event.offsetY)<18;});
  if(hit)selectAgent(hit.agent_id);
});
canvas.addEventListener("pointercancel",()=>{drag=null;});
canvas.addEventListener("wheel",(event)=>{event.preventDefault();zoom=Math.max(.3,Math.min(6,zoom*Math.exp(-event.deltaY*.001)));},{passive:false});
document.addEventListener("keydown",(event)=>{if(event.key==="Escape"){mapMode=null;updateControls();}});
$("fit").onclick=()=>{zoom=1;pan={x:0,y:0};};
$("local-view").onchange=updateControls;
document.querySelectorAll("[data-tab]").forEach((button)=>{button.onclick=()=>{tab=button.dataset.tab;renderEditor();};});
$("apply").onclick=applyScenario;
$("reset").onclick=applyScenario;
$("step").onclick=stepOnce;
$("play").onclick=()=>{if(playing){stop();return;}playing=true;updateControls();stepOnce();};
$("add-agent").onclick=()=>{
  let n=1;while(draft.agents.some((a)=>a.id===`agent-${n}`))n++;
  const agent={id:`agent-${n}`,affiliation:"friendly",x:draft.environment.width/2,y:draft.environment.height/2,speed:0,heading:0,sensors:[],policy:null};
  draft.agents.push(agent);selected=agent.id;tab="agent";markDirty();renderEditor();
};
$("new").onclick=()=>{loadDraft(freshScenario());notice("Novo cenário. Adicione agentes, sensores e enlaces e clique em Aplicar cenário.",true);};
$("examples").onchange=async(event)=>{if(event.target.value!==""){loadDraft(examples[Number(event.target.value)].scenario);await applyScenario();}};
$("import").onclick=()=>{$("file").value="";$("file").click();};
$("file").onchange=async(event)=>{
  const file=event.target.files[0];if(!file)return;
  if(file.size>1_000_000){notice("O arquivo deve ter até 1 MB.");return;}
  try{const data=await api("/api/validate",{scenario:await file.text()});loadDraft(data.scenario);notice("Cenário importado. Aplique para iniciar a simulação.",true);}catch(error){notice(error.message);}
};
$("export").onclick=async()=>{try{const data=await api("/api/validate",{scenario:draft});download("mssa-cenario.yaml",data.yaml,"application/yaml");}catch(error){notice(error.message);}};
$("export-state").onclick=()=>{if(frame)download("mssa-estado.json",JSON.stringify({scenario:draft,...frame},null,2),"application/json");};

async function initialize() {
  requestAnimationFrame(draw);
  try {
    examples=await api("/api/examples");
    $("examples").innerHTML='<option value="">Cenários de exemplo</option>'+examples.map((example,i)=>`<option value="${i}">${esc(example.name)}</option>`).join("");
    let saved=null;try{saved=JSON.parse(localStorage.getItem("mssa.scenario.v1"));}catch{/* Ignore malformed local drafts. */}
    if(saved){try{saved=(await api("/api/validate",{scenario:saved})).scenario;}catch{saved=null;}}
    const index=examples.findIndex((example)=>example.name==="patrol_reaction.yaml");
    const initial=saved||examples[index>=0?index:0]?.scenario||freshScenario();
    loadDraft(initial);if(!saved&&examples.length)$("examples").value=String(index>=0?index:0);
    await applyScenario();
  }catch(error){loadDraft(freshScenario());notice(`Não foi possível conectar ao simulador. ${error.message}`);}
}
initialize();
