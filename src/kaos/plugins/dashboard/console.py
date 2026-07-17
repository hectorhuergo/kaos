"""KAOS web console: a self-contained admin page (Providers, Subscriptions, Dashboards).

Rendered as a single HTML document with vanilla JS that talks to the JSON API
exposed by :mod:`kaos.plugins.dashboard.app`. No build step: chat bubbles get
optional client-side Markdown rendering via ``markdown-it`` + ``DOMPurify``
loaded from a CDN (same pattern as the dashboard's Mermaid), degrading to
escaped plain text when offline. It is served by ``kaos serve`` at ``/console``.

The console edits durable state via the JSON API: the active LLM provider +
model and the subscriptions, plus each provider's credential (API key/token),
which can be persisted in PostgreSQL with the environment as fallback. Secrets
are write-only from here — they are sent to the server but never read back; the
UI only shows whether a credential is stored (Postgres) or inherited from
``.env``.
"""

from __future__ import annotations

_STYLE = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{font-family:system-ui,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header{padding:1.1rem 1.6rem;background:#161a22;border-bottom:1px solid #262b36;display:flex;align-items:center;gap:1rem}
header h1{margin:0;font-size:1.2rem}
header .meta{color:#8a93a2;font-size:.85rem}
/* Global collapsible sidebar navigation. */
.shell{display:flex;min-height:100vh}
.sidebar{width:212px;flex:none;background:#12151c;border-right:1px solid #262b36;display:flex;flex-direction:column;position:sticky;top:0;height:100vh;transition:width .15s ease}
.side-top{display:flex;align-items:center;justify-content:space-between;gap:.5rem;padding:1rem .9rem;border-bottom:1px solid #262b36}
.brand{font-size:1.05rem;font-weight:600;white-space:nowrap;overflow:hidden}
.collapse{background:none;border:1px solid #2f3646;color:#8a93a2;border-radius:6px;padding:.25rem .4rem;cursor:pointer;line-height:0;display:flex;align-items:center;justify-content:center}
.collapse:hover{color:#e6e6e6;border-color:#4f8cff}
.collapse svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;display:block;transition:transform .15s ease}
.shell.collapsed .collapse svg{transform:rotate(180deg)}
.sidebar nav{display:flex;flex-direction:column;gap:.15rem;padding:.6rem .5rem}
.sidebar nav button{display:flex;align-items:center;gap:.7rem;background:none;border:none;color:#8a93a2;padding:.6rem .7rem;cursor:pointer;font-size:.95rem;border-radius:8px;border-left:3px solid transparent;text-align:left;width:100%;white-space:nowrap;overflow:hidden}
.sidebar nav button:hover{background:#161a22;color:#e6e6e6}
.sidebar nav button.active{color:#e6e6e6;background:#141b2b;border-left-color:#4f8cff}
.sidebar nav .ic{width:1.3rem;flex:none;display:flex;align-items:center;justify-content:center}
.nav-group{padding:.9rem .9rem .3rem;margin-top:.4rem;border-top:1px solid #262b36;color:#5c6675;font-size:.66rem;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.shell.collapsed .nav-group{border-top:1px solid #262b36;padding:.5rem 0 .2rem;text-align:center}
.shell.collapsed .nav-group .lbl{display:none}
.sidebar nav .ic svg,.brand svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;display:block}
.content{flex:1;min-width:0}
.shell.collapsed .sidebar{width:58px}
.shell.collapsed .sidebar nav .lbl{display:none}
.shell.collapsed .side-top{flex-direction:column-reverse;gap:.5rem;padding:.7rem .2rem;justify-content:center}
.shell.collapsed .brand{font-size:.68rem;text-align:center}
.shell.collapsed .sidebar nav button{justify-content:center;gap:0;padding:.6rem 0}
main{padding:1.6rem;max-width:1200px;margin:0 auto}
@media(max-width:720px){.sidebar{width:58px}.sidebar nav .lbl{display:none}.side-top{flex-direction:column-reverse;gap:.5rem;padding:.7rem .2rem;justify-content:center}.brand{font-size:.68rem;text-align:center}.sidebar nav button{justify-content:center;gap:0;padding:.6rem 0}}
.tab{display:none}.tab.active{display:block}
h2{font-size:1.05rem;margin:0 0 1rem}
.card{background:#161a22;border:1px solid #262b36;border-radius:10px;padding:1rem 1.2rem;margin:.7rem 0}
.row{display:flex;align-items:center;gap:.8rem;flex-wrap:wrap}
.row .grow{flex:1}
.pill{font-size:.72rem;padding:.15rem .5rem;border-radius:999px;border:1px solid #2f3646;color:#8a93a2}
.pill.ok{color:#7ee787;border-color:#2ea04326}
.pill.no{color:#f8814f;border-color:#f8814f26}
.pill.active{color:#4f8cff;border-color:#4f8cff40}
.kpi-block{margin-top:.5rem;display:flex;flex-direction:column;gap:.35rem}
.stat-row{display:flex;flex-wrap:wrap;gap:.15rem 1.1rem;color:#8a93a2;font-size:.8rem}
.stat .stat-l{color:#6f7a89}
.stat b{color:#e6e6e6;font-weight:600}
.pill-row{display:flex;flex-wrap:wrap;gap:.35rem;align-items:center}
.cat-lbl{color:#6f7a89;font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;margin-right:.1rem}
label{display:block;font-size:.8rem;color:#8a93a2;margin:.6rem 0 .25rem}
input,select{width:100%;background:#0f1115;border:1px solid #2f3646;border-radius:8px;color:#e6e6e6;padding:.5rem .6rem;font-size:.95rem}
button.act{background:#4f8cff;border:none;color:#fff;border-radius:8px;padding:.55rem 1rem;cursor:pointer;font-size:.9rem}
button.act.ghost{background:none;border:1px solid #2f3646;color:#e6e6e6}
button.act.danger{background:none;border:1px solid #f8814f40;color:#f8814f}
.muted{color:#8a93a2;font-size:.85rem}
a{color:#4f8cff}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
pre.out{white-space:pre-wrap;word-wrap:break-word;background:#0f1115;border:1px solid #2f3646;border-radius:8px;padding:1rem;max-height:60vh;overflow:auto;font-size:.85rem;line-height:1.45;margin:.4rem 0}
.spin{color:#8a93a2;font-size:.9rem}
#toast{position:fixed;right:1.2rem;bottom:1.2rem;background:#161a22;border:1px solid #2f3646;border-radius:8px;padding:.7rem 1rem;opacity:0;transition:opacity .2s;pointer-events:none}
#toast.show{opacity:1}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
/* Chat: standard AI layout — left panel (chats + artifacts + catalog) and a
   main column with the thread on top and the composer at the bottom. */
.chat-layout{display:grid;grid-template-columns:280px 1fr;gap:1rem;align-items:start}
.chat-side{background:#12151c;border:1px solid #262b36;border-radius:10px;padding:.7rem;position:sticky;top:1rem;max-height:calc(100vh - 2rem);overflow:auto}
.chat-side-head{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:#8a93a2;margin:.8rem .2rem .35rem}
.chat-list{display:flex;flex-direction:column;gap:.35rem}
.chat-item{background:#0f1115;border:1px solid #262b36;border-radius:8px;padding:.45rem .55rem;cursor:pointer;font-size:.85rem}
.chat-item:hover{border-color:#4f8cff}
.chat-item.active{border-color:#4f8cff;background:#141b2b}
.chat-item .ci-title{color:#e6e6e6;font-weight:600;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chat-item .ci-meta{color:#8a93a2;font-size:.72rem}
.chat-item .ci-ico{margin-right:.35rem}
.ctx-card{background:#12151c;border:1px solid #2f3646;border-radius:10px;padding:.8rem}
.ctx-head{font-weight:600;margin-bottom:.4rem}
.ctx-body{white-space:pre-wrap;font-size:.9rem;color:#cdd3dd;max-height:42vh;overflow:auto}
.chat-anchor{margin:.1rem 0 .5rem;display:flex;gap:.6rem;align-items:center;flex-wrap:wrap}
.chat-grp{color:#6f7a89;font-size:.68rem;text-transform:uppercase;letter-spacing:.04em;font-weight:600;margin:.75rem .2rem .3rem;display:flex;align-items:center;gap:.4rem}
.chat-grp::after{content:'';flex:1;height:1px;background:#262b36}
.chat-catalog{margin-left:auto;display:flex;flex-wrap:wrap;gap:.3rem;align-items:center;justify-content:flex-end}
.chat-catalog .pill{font-size:.68rem}
.thread-more{align-self:center;background:none;border:1px solid #2f3646;color:#8a93a2;border-radius:999px;padding:.15rem .7rem;font-size:.72rem;cursor:pointer}
.thread-more:hover{color:#e6e6e6;border-color:#4f8cff}
.ver-nav{display:flex;align-items:center;justify-content:center;gap:.5rem;margin-bottom:.2rem}
.ver-btn{background:#12151c;border:1px solid #2f3646;color:#cdd3dd;border-radius:6px;padding:.05rem .5rem;font-size:.8rem;cursor:pointer}
.ver-btn:hover:not(:disabled){border-color:#4f8cff;color:#fff}
.ver-btn:disabled{opacity:.35;cursor:default}
.ver-label{color:#8a93a2;font-size:.72rem}
.bubble.msg{align-self:flex-start;background:#12151c;border:1px solid #262b36;max-width:92%}
.bubble.msg .b-author{display:block;color:#7aa2ff;font-size:.72rem;font-weight:600;margin-bottom:.2rem}
.chat-main{display:flex;flex-direction:column;min-height:60vh}
.chat-thread{flex:1;background:#0f1115;border:1px solid #262b36;border-radius:10px;padding:1rem;overflow:auto;max-height:60vh;display:flex;flex-direction:column;gap:.6rem}
.bubble{max-width:80%;padding:.55rem .8rem;border-radius:12px;font-size:.9rem;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}
.bubble.user{align-self:flex-end;background:#1d2b4a;border:1px solid #2c3f66}
.bubble.assistant{align-self:flex-start;background:#161a22;border:1px solid #2f3646}
.bubble .b-meta{display:block;color:#8a93a2;font-size:.68rem;margin-top:.3rem}
/* Rendered Markdown inside assistant bubbles (previewed .md). */
.bubble .md{white-space:normal}
.bubble .md>*:first-child{margin-top:0}
.bubble .md>*:last-child{margin-bottom:0}
.bubble .md p{margin:.4rem 0}
.bubble .md h1,.bubble .md h2,.bubble .md h3,.bubble .md h4{margin:.6rem 0 .3rem;line-height:1.25}
.bubble .md h1{font-size:1.1rem}.bubble .md h2{font-size:1.02rem}.bubble .md h3{font-size:.95rem}
.bubble .md ul,.bubble .md ol{margin:.3rem 0;padding-left:1.2rem}
.bubble .md li{margin:.15rem 0}
.bubble .md a{color:#7aa2ff}
.bubble .md code{background:#0f1115;border:1px solid #262b36;border-radius:5px;padding:.05rem .3rem;font-size:.85em}
.bubble .md pre{background:#0f1115;border:1px solid #262b36;border-radius:8px;padding:.6rem .7rem;overflow:auto;margin:.4rem 0}
.bubble .md pre code{background:none;border:none;padding:0}
.bubble .md blockquote{margin:.4rem 0;padding-left:.7rem;border-left:3px solid #2f3646;color:#b9c1cd}
.bubble .md table{border-collapse:collapse;margin:.4rem 0;font-size:.85em}
.bubble .md th,.bubble .md td{border:1px solid #2f3646;padding:.25rem .5rem}
.bubble .md hr{border:none;border-top:1px solid #262b36;margin:.6rem 0}
.chat-composer{margin-top:.8rem;background:#161a22;border:1px solid #262b36;border-radius:10px;padding:.8rem}
@media(max-width:820px){.chat-layout{grid-template-columns:1fr}.chat-side{position:static;max-height:none}}
"""

_SCRIPT = """
const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => [...r.querySelectorAll(s)];
let toastTimer;
function toast(msg, ok=true){
  const t = $('#toast'); t.textContent = msg;
  t.style.borderColor = ok ? '#2ea04366' : '#f8814f66';
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>t.classList.remove('show'), 2600);
}
async function api(path, opts){
  const res = await fetch(path, opts);
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null;
  if(!res.ok){ throw new Error((data && data.detail) || res.statusText); }
  return data;
}
function tab(name){
  $$('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab===name));
  $$('.tab').forEach(t => t.classList.toggle('active', t.id==='tab-'+name));
  if(name==='providers') loadProviders();
  if(name==='agents') loadAgents();
  if(name==='subscriptions') loadSubscriptions();
  if(name==='chat') loadChat();
  if(name==='dashboards') loadDashboards();
  if(name==='preview') loadPreview();
}

// ---- Reusable provider + model selectors (per-run LLM override) ----
// A pair of controls used in Subscriptions, Chat, Vista previa and the
// Dashboards run modal: a provider <select> (empty = use the global/subscription
// default) and a model field that becomes a <select> when the provider can list
// its models, or a free-text input when it cannot. Empty always means "default".
let PROVIDER_CATALOG = [];
const MODELS_CACHE = {};
async function ensureProviderCatalog(){
  if(PROVIDER_CATALOG.length) return PROVIDER_CATALOG;
  try{ const d = await api('/api/providers'); PROVIDER_CATALOG = d.providers || []; }
  catch(e){ PROVIDER_CATALOG = []; }
  return PROVIDER_CATALOG;
}
function providerOptions(selected){
  return ['<option value="">(por defecto)</option>'].concat(PROVIDER_CATALOG.map(p =>
    `<option value="${esc(p.id)}" ${p.id===selected?'selected':''}>${esc(p.label)}</option>`)).join('');
}
async function fetchModels(provider){
  if(!provider) return [];
  if(MODELS_CACHE[provider]) return MODELS_CACHE[provider];
  try{ const d = await api('/api/providers/'+encodeURIComponent(provider)+'/models');
    MODELS_CACHE[provider] = d.models || []; return MODELS_CACHE[provider];
  }catch(e){ return []; }
}
async function renderModelField(container, provider, current){
  const id = container.dataset.modelId;
  const models = await fetchModels(provider);
  if(models.length){
    const known = current && models.includes(current);
    const extra = (current && !known)
      ? `<option value="${esc(current)}" selected>${esc(current)} (actual)</option>` : '';
    container.innerHTML = `<select id="${id}"><option value="">(por defecto)</option>${extra}`
      + models.map(m => `<option value="${esc(m)}" ${m===current?'selected':''}>${esc(m)}</option>`).join('')
      + '</select>';
  } else {
    container.innerHTML = `<input id="${id}" placeholder="(por defecto)" value="${esc(current||'')}">`;
  }
}
// Populate a provider select + its model field; re-render the model field when
// the provider changes. Returns once the initial render is done.
async function bindProviderModel(provSelId, modelContainerId, provInit, modelInit){
  await ensureProviderCatalog();
  const provSel = $('#'+provSelId);
  const cont = $('#'+modelContainerId);
  if(!provSel || !cont) return;
  provSel.innerHTML = providerOptions(provInit||'');
  await renderModelField(cont, provInit||'', modelInit||'');
  provSel.onchange = () => renderModelField(cont, provSel.value, '');
}
function fieldValue(id){ const el = $('#'+id); return el && el.value.trim() ? el.value.trim() : null; }

// ---- Reusable agent selector ----
// A provider-style catalog of agents; an empty value means "default" (the
// resume-agent, or the subscription's stored agent for a per-run override).
let AGENT_CATALOG = [];
async function ensureAgentCatalog(){
  if(AGENT_CATALOG.length) return AGENT_CATALOG;
  try{ const d = await api('/api/agents'); AGENT_CATALOG = d.agents || [];
    AGENT_CATALOG.forEach(a => { AGENT_LABELS[a.id] = a.label; }); }
  catch(e){ AGENT_CATALOG = []; }
  return AGENT_CATALOG;
}
function agentOptions(selected, defaultLabel){
  return [`<option value="">${esc(defaultLabel)}</option>`].concat(AGENT_CATALOG.map(a =>
    `<option value="${esc(a.id)}" ${a.id===selected?'selected':''}>${esc(a.label)}</option>`)).join('');
}
async function bindAgent(selId, init, defaultLabel){
  await ensureAgentCatalog();
  const sel = $('#'+selId);
  if(!sel) return;
  sel.innerHTML = agentOptions(init||'', defaultLabel || '(por defecto)');
}

// ---- Agents ----
// Extra instructions are kept per-agent (by id) and persisted via the API. The
// summary pipeline (preview and run) consumes the resume-agent's, augmenting its
// prompt. The textarea is pre-filled with the saved value on load.
function agentExtra(id='resume-agent'){ const el = $('#agent-extra-'+id); return el ? el.value.trim() : ''; }
async function saveAgentInstructions(id){
  const el = $('#agent-extra-'+id); if(!el) return;
  try{
    await api('/api/agents/'+encodeURIComponent(id)+'/instructions',
      {method:'PUT', headers:{'content-type':'application/json'},
       body: JSON.stringify({instructions: el.value})});
    toast('Instrucciones guardadas');
  }catch(e){ toast(e.message, false); }
}
async function loadAgents(){
  const box = $('#agents'); box.innerHTML = '<p class="muted">Cargando…</p>';
  try{
    const d = await api('/api/agents');
    box.innerHTML = d.agents.map(a => `
      <div class="card">
        <div class="row">
          <div class="grow"><strong>${esc(a.label)}</strong> <span class="muted">${esc(a.id)}</span>
            <div class="muted">${esc(a.description)}</div>
            <div class="muted">produce: <code>${esc(a.produces)}</code> · disparo: <code>${esc(a.trigger)}</code></div>
          </div>
          ${a.augmentable?'<span class="pill ok">prompt aumentable</span>':'<span class="pill">prompt fijo</span>'}
        </div>
        ${a.base_prompt?`<details style="margin-top:.6rem"><summary class="muted" style="cursor:pointer">Ver prompt base</summary>
          <pre class="out">${esc(a.base_prompt)}</pre></details>`:''}
        ${a.augmentable?`<label for="agent-extra-${a.id}">Prompt extra para ${esc(a.label)}</label>
          <textarea id="agent-extra-${a.id}" rows="3" style="width:100%;background:#0f1115;border:1px solid #2f3646;border-radius:8px;color:#e6e6e6;padding:.5rem .6rem;font-size:.95rem" placeholder="p. ej.: enfocate en decisiones técnicas y montos; tono formal.">${esc(a.instructions)}</textarea>
          <div class="row" style="margin-top:.5rem">
            <button class="act" onclick="saveAgentInstructions('${a.id}')">Guardar instrucciones</button>
            ${a.id==='resume-agent'?'<span class="muted">Se aplica al generar Vista previa o Ejecutar.</span>':'<span class="muted">Se aplicará cuando se ejecute este agente.</span>'}
          </div>`:''}
      </div>`).join('');
  }catch(e){ box.innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
}

// ---- Providers ----
function credPill(p){
  if(!p.needs_secret) return '<span class="pill ok">no requiere credencial</span>';
  if(p.stored) return '<span class="pill ok">credencial en Postgres</span>';
  if(p.env_ready) return `<span class="pill ok">credencial en .env</span> <span class="pill">${esc((p.env_sources||[]).join(' | ') || '.env')}</span>`;
  return '<span class="pill no">sin credencial</span>';
}
function credForm(p){
  if(!p.needs_secret) return '';
  const clear = p.stored
    ? `<button class="act ghost danger" onclick="clearCredential('${p.id}')">Quitar</button>` : '';
  return `<div class="row" style="margin-top:.7rem">
      <input type="password" id="key-${p.id}" class="grow" placeholder="${p.stored?'•••••• (guardada) — escribí para reemplazar':'API key / token'}">
      <button class="act" onclick="saveCredential('${p.id}')">Guardar credencial</button>
      ${clear}
    </div>`;
}
async function loadProviders(){
  const box = $('#providers'); box.innerHTML = '<p class="muted">Cargando…</p>';
  try{
    const d = await api('/api/providers');
    const sel = $('#provider-select');
    sel.innerHTML = d.providers.map(p =>
      `<option value="${p.id}" ${p.selected?'selected':''}>${p.label}</option>`).join('');
    const modelCont = $('#model-input-wrap');
    await renderModelField(modelCont, sel.value, d.selected_model || '');
    sel.onchange = () => renderModelField(modelCont, sel.value, '');
    box.innerHTML = d.providers.map(p => `
      <div class="card">
        <div class="row">
          <div class="grow"><strong>${p.label}</strong> <span class="muted">${p.id}</span>
            <div class="muted">${p.notes}</div>
            <div class="muted">modelo por defecto: <code>${p.default_model}</code></div>
            ${p.env_ready && (p.env_sources||[]).length ? `<div class="muted">fuente real: ${esc((p.env_sources||[]).join(' | '))}</div>` : ''}
          </div>
          ${credPill(p)}
          ${p.selected?'<span class="pill active">seleccionado</span>':''}
        </div>
        ${credForm(p)}
      </div>`).join('');
    $('#persist-note').textContent = d.persistent
      ? 'Selección y credenciales se guardan en PostgreSQL (.env queda como fallback).'
      : 'Sin KAOS_DATABASE_URL: la selección y las credenciales no serán persistentes.';
  }catch(e){ box.innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
}
async function saveProvider(){
  const provider = $('#provider-select').value;
  const model = $('#model-input').value.trim();
  try{
    await api('/api/config/provider', {method:'PUT', headers:{'content-type':'application/json'},
      body: JSON.stringify({provider, model})});
    toast('Provider guardado');
    loadProviders();
  }catch(e){ toast(e.message, false); }
}
async function saveCredential(provider){
  const api_key = $('#key-'+provider).value.trim();
  if(!api_key){ toast('Escribí la API key', false); return; }
  try{
    await api('/api/providers/'+encodeURIComponent(provider)+'/credential',
      {method:'PUT', headers:{'content-type':'application/json'},
       body: JSON.stringify({api_key})});
    toast('Credencial guardada en Postgres');
    loadProviders();
  }catch(e){ toast(e.message, false); }
}
async function clearCredential(provider){
  try{
    await api('/api/providers/'+encodeURIComponent(provider)+'/credential', {method:'DELETE'});
    toast('Credencial quitada (usará .env)');
    loadProviders();
  }catch(e){ toast(e.message, false); }
}

// ---- Subscriptions ----
let SUBS = [];
let SUB_EDIT = null;
// Build <option>s for a workspace multiselect: every subscription except
// ``exclude`` (a workspace never relates to itself), preselecting ``selected``.
function wsOptions(selected, exclude){
  const sel = new Set(selected||[]);
  return SUBS.filter(s => s.workspace !== exclude).map(s =>
    `<option value="${esc(s.workspace)}" ${sel.has(s.workspace)?'selected':''}>${esc(s.name||s.channel_id)}</option>`).join('');
}
function selectedValues(el){ return el ? [...el.selectedOptions].map(o => o.value) : []; }
async function loadSubscriptions(){
  const box = $('#subs'); box.innerHTML = '<p class="muted">Cargando…</p>';
  try{
    const d = await api('/api/subscriptions');
    SUBS = d.subscriptions;
    const newRel = $('#sub-related'); if(newRel) newRel.innerHTML = wsOptions([], null);
    if(!SUB_EDIT) bindProviderModel('sub-llm-provider', 'sub-llm-model-wrap', '', '');
    if(!SUB_EDIT) bindAgent('sub-agent', '', '(por defecto)');
    if(!SUBS.length){ box.innerHTML = '<p class="muted">(sin suscripciones activas)</p>'; return; }
    box.innerHTML = SUBS.map((s,i) => `
      <div class="card">
        <div class="row">
          <div class="grow"><strong>${esc(s.name||s.channel_id)}</strong> <span class="pill">${esc(s.kind)}</span>${s.project?` <span class="pill">📦 ${esc(s.project)}</span>`:''}${s.publish_default?'':' <span class="pill no">solo conocimiento</span>'}${(s.related_to&&s.related_to.length)?` <span class="pill">🔗 ${s.related_to.length}</span>`:''}${s.llm_provider?` <span class="pill">🤖 ${esc(s.llm_provider)}${s.llm_model?(' · '+esc(s.llm_model)):''}</span>`:''}${s.agent_id?` <span class="pill">🧠 ${esc(agentLabel(s.agent_id))}</span>`:''}
            <div class="muted"><code>${esc(s.channel_id)}</code> · workspace: ${esc(s.workspace)} · resume: ${esc(s.resume_thread_id||'-')} · plan: ${s.interval_seconds?('cada '+s.interval_seconds+'s'):'cada pasada'}</div>
          </div>
          <button class="act ghost" onclick="editSub(${i})">Editar</button>
          <button class="act danger" onclick="removeSub('${esc(s.channel_id)}')">Quitar</button>
        </div>
      </div>`).join('');
  }catch(e){ box.innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
}
function subFormReset(){
  SUB_EDIT = null;
  $('#sub-channel').value=''; $('#sub-kind').value='forum'; $('#sub-guild').value='';
  $('#sub-resume').value=''; $('#sub-every').value=''; $('#sub-project').value='';
  $('#sub-publish').checked = true;
  ['sub-channel','sub-kind','sub-guild'].forEach(id => { const el=$('#'+id); if(el) el.disabled=false; });
  const rel = $('#sub-related'); if(rel) rel.innerHTML = wsOptions([], null);
  bindProviderModel('sub-llm-provider', 'sub-llm-model-wrap', '', '');
  bindAgent('sub-agent', '', '(por defecto)');
  $('#sub-form-title').textContent = 'Nueva suscripción';
  $('#sub-submit').textContent = 'Suscribir';
  $('#sub-cancel').style.display = 'none';
}
// Reuse the top form for editing: load the subscription, lock identity fields
// (channel/kind/guild can't be patched) and switch the primary button to save.
function editSub(i){
  const s = SUBS[i]; if(!s) return;
  SUB_EDIT = s.channel_id;
  $('#sub-channel').value = s.channel_id; $('#sub-channel').disabled = true;
  $('#sub-kind').value = s.kind; $('#sub-kind').disabled = true;
  $('#sub-guild').value = s.guild_id || ''; $('#sub-guild').disabled = true;
  $('#sub-resume').value = s.resume_thread_id || '';
  $('#sub-every').value = s.interval_seconds || '';
  $('#sub-project').value = s.project || '';
  $('#sub-publish').checked = !!s.publish_default;
  const rel = $('#sub-related'); if(rel) rel.innerHTML = wsOptions(s.related_to, s.workspace);
  bindProviderModel('sub-llm-provider', 'sub-llm-model-wrap', s.llm_provider || '', s.llm_model || '');
  bindAgent('sub-agent', s.agent_id || '', '(por defecto)');
  $('#sub-form-title').textContent = 'Editar suscripción';
  $('#sub-submit').textContent = 'Guardar cambios';
  $('#sub-cancel').style.display = '';
  $('#sub-form-title').scrollIntoView({behavior:'smooth', block:'start'});
}
function submitSub(){ return SUB_EDIT ? saveSubForm() : addSub(); }
async function addSub(){
  const every = parseInt($('#sub-every').value, 10);
  const body = {
    channel_id: $('#sub-channel').value.trim(),
    kind: $('#sub-kind').value,
    guild_id: $('#sub-guild').value.trim() || null,
    resume_thread_id: $('#sub-resume').value.trim() || null,
    interval_seconds: Number.isFinite(every) && every > 0 ? every : null,
    project: $('#sub-project').value.trim() || null,
    publish_default: $('#sub-publish').checked,
    related_to: selectedValues($('#sub-related')),
    llm_provider: $('#sub-llm-provider').value || null,
    llm_model: fieldValue('sub-llm-model'),
    agent_id: $('#sub-agent') ? ($('#sub-agent').value || null) : null,
  };
  if(!body.channel_id){ toast('Falta channel_id', false); return; }
  try{
    await api('/api/subscriptions', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify(body)});
    toast('Suscripción guardada');
    subFormReset();
    loadSubscriptions();
  }catch(e){ toast(e.message, false); }
}
async function saveSubForm(){
  const every = parseInt($('#sub-every').value, 10);
  const body = {
    resume_thread_id: $('#sub-resume').value.trim() || null,
    interval_seconds: Number.isFinite(every) && every > 0 ? every : null,
    project: $('#sub-project').value.trim() || null,
    publish_default: $('#sub-publish').checked,
    related_to: selectedValues($('#sub-related')),
    llm_provider: $('#sub-llm-provider').value || null,
    llm_model: fieldValue('sub-llm-model'),
    agent_id: $('#sub-agent') ? ($('#sub-agent').value || null) : null,
  };
  try{
    await api('/api/subscriptions/'+encodeURIComponent(SUB_EDIT),
      {method:'PATCH', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
    toast('Suscripción actualizada');
    subFormReset();
    loadSubscriptions();
  }catch(e){ toast(e.message, false); }
}
async function removeSub(id){
  try{ await api('/api/subscriptions/'+encodeURIComponent(id), {method:'DELETE'});
    toast('Suscripción quitada'); loadSubscriptions();
  }catch(e){ toast(e.message, false); }
}

// ---- Dashboards ----
let DASH_WS_CHANNEL = {};
let DASH_WS_PUBLISH = {};
let DASH_SUBS = {};
let RUN_MODAL_CHANNEL = '';
let DASH_BUSY = false;
let DASH_ABORT_CTRL = null;
let DASH_RUN_ID = null;
function setDashBusy(busy){
  DASH_BUSY = busy;
  if(busy){
    DASH_ABORT_CTRL = new AbortController();
    DASH_RUN_ID = 'dash-' + Date.now() + '-' + Math.random().toString(36).slice(2,8);
  } else {
    DASH_ABORT_CTRL = null;
    DASH_RUN_ID = null;
  }
  const cancel = $('#dash-cancel');
  if(cancel){ cancel.style.display = busy ? '' : 'none'; cancel.disabled = false; cancel.textContent = '⏹ Cancelar'; }
  $$('#tab-dashboards button.act:not(#dash-cancel)').forEach(b => b.disabled = busy);
}
async function cancelDash(){
  if(!DASH_BUSY) return;
  const cancel = $('#dash-cancel');
  if(cancel){ cancel.disabled = true; cancel.textContent = 'Cancelando…'; }
  if(DASH_ABORT_CTRL) DASH_ABORT_CTRL.abort();
  if(DASH_RUN_ID){
    try{ await fetch('/api/run/cancel', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({run_id:DASH_RUN_ID})}); }catch(e){}
  }
  toast('Operación cancelada');
}
async function loadDashboards(){
  const box = $('#dashboards'); box.innerHTML = '<p class="muted">Cargando…</p>';
  try{
    const [d, subsData, agentsData] = await Promise.all([
      api('/api/workspaces'), api('/api/subscriptions'), api('/api/agents')]);
    (agentsData.agents || []).forEach(a => { AGENT_LABELS[a.id] = a.label; });
    DASH_WS_CHANNEL = {}; DASH_WS_PUBLISH = {}; DASH_SUBS = {};
    (subsData.subscriptions || []).forEach(s => { if(s.workspace){ DASH_WS_CHANNEL[s.workspace] = s.channel_id; DASH_WS_PUBLISH[s.workspace] = !!s.publish_default; DASH_SUBS[s.channel_id] = s; } });
    if(!d.workspaces.length){ box.innerHTML = '<p class="muted">(sin workspaces — crea una suscripción)</p>'; return; }
    const labels = d.labels || {};
    const summaries = d.summaries || {};
    box.innerHTML = d.workspaces.map(ws => {
      const ch = DASH_WS_CHANNEL[ws];
      const actions = ch
        ? `<label class="row" style="gap:.3rem;color:#8a93a2;font-size:.85rem;margin:0">
             <input type="checkbox" id="dash-pub-${esc(ch)}" ${DASH_WS_PUBLISH[ws]?'checked':''} style="width:auto;margin:0">Publicar</label>
           <button class="act" onclick="dashRun('${esc(ch)}')">Ejecutar</button>`
        : '';
      return `<div class="card"><div class="row">
        <div class="grow">
          <strong>${esc(labels[ws]||ws)}</strong> <span class="muted">${esc(ws)}</span>
          ${workspacePills(summaries[ws] || {})}
        </div>
        <div class="row">${actions}
          <a class="act ghost" href="/?workspace=${encodeURIComponent(ws)}" target="_blank">Abrir dashboard ↗</a>
        </div>
      </div></div>`;
    }).join('');
  }catch(e){ box.innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
}

function dashRenderOut(data, note){
  const out = $('#dash-out'); if(!out) return;
  const arts = data.artifacts || [];
  const head = note ? `<div class="pill ok" style="margin-bottom:.6rem">${esc(note)}</div>` : '';
  if(!arts.length){ out.innerHTML = head + '<p class="muted">(sin resultado — no había contenido que resumir)</p>'; return; }
  out.innerHTML = head + arts.map(a => {
    const summary = (a.content && a.content.summary) || JSON.stringify(a.content, null, 2);
    const model = (a.metadata && a.metadata.model) ? ` · modelo: ${esc(a.metadata.model)}` : '';
    return `<div class="muted" style="margin:.4rem 0">${esc(a.kind)} · ${esc(a.workspace)}${model}</div>`
      + `<pre class="out">${esc(summary)}</pre>`;
  }).join('');
}
async function dashRun(channelId){
  RUN_MODAL_CHANNEL = channelId;
  const sub = DASH_SUBS[channelId] || {};
  $('#run-modal-sub').textContent = (sub.name || channelId) + ' · ' + (sub.kind || '');
  $('#run-publish').checked = document.getElementById('dash-pub-'+channelId)?.checked || false;
  await bindProviderModel('run-llm-provider', 'run-llm-model-wrap', sub.llm_provider || '', sub.llm_model || '');
  await bindAgent('run-agent', sub.agent_id || '', '(agente de la suscripción)');
  $('#run-modal').style.display = 'flex';
}
function closeRunModal(){ $('#run-modal').style.display = 'none'; RUN_MODAL_CHANNEL = ''; }
async function confirmRunModal(){
  const channelId = RUN_MODAL_CHANNEL;
  if(!channelId) return;
  if(DASH_BUSY){ toast('Ya hay una operación en curso', false); return; }
  const publish = $('#run-publish').checked;
  const override = {
    llm_provider: $('#run-llm-provider') ? ($('#run-llm-provider').value || null) : null,
    llm_model: fieldValue('run-llm-model'),
    agent_id: $('#run-agent') ? ($('#run-agent').value || null) : null,
  };
  closeRunModal();
  setDashBusy(true);
  const out = $('#dash-out');
  out.innerHTML = `<p class="spin">⏳ Ejecutando… (persiste + cache${publish?' y publica en Discord':', no publica'})</p>`;
  try{
    const signal = DASH_ABORT_CTRL ? DASH_ABORT_CTRL.signal : undefined;
    const data = await api('/api/run/subscription', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify(Object.assign({channel_id: channelId, run_id: DASH_RUN_ID, force:false, publish}, override)), signal});
    dashRenderOut(data, publish
      ? '✔ persistido · cache actualizada · publicado en Discord'
      : '✔ persistido · cache actualizada · no se publicó');
    toast('Corrida completa');
    loadDashboards();
  }catch(e){
    if(e.name === 'AbortError'){ out.innerHTML = '<p class="muted">Operación cancelada.</p>'; }
    else { out.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`; }
  }finally{ setDashBusy(false); }
}

// Friendly agent names (id -> label), filled from /api/agents when tabs load.
let AGENT_LABELS = {};
function agentLabel(id){ return AGENT_LABELS[id] || id; }
function kpiStat(label, value){
  return `<span class="stat"><span class="stat-l">${esc(label)}:</span> <b>${esc(String(value))}</b></span>`;
}
function catChips(label, values){
  if(!values || !values.length) return '';
  return `<span class="cat-lbl">${esc(label)}</span>`
    + values.map(v => `<span class="pill">${esc(String(v))}</span>`).join('');
}
function workspacePills(s){
  const stats = [];
  if(s.asset_count != null) stats.push(kpiStat('Assets', s.asset_count));
  if(s.artifact_count != null) stats.push(kpiStat('Artefactos', s.artifact_count));
  if(s.last_execution) stats.push(kpiStat('Última ejecución', s.last_execution));
  if((s.session_count || 0) > 0) stats.push(kpiStat('Sesiones', s.session_count));
  if((s.message_count || 0) > 0) stats.push(kpiStat('Mensajes', s.message_count));
  const agents = (s.agent_labels && s.agent_labels.length)
    ? s.agent_labels : (s.agents || []).map(agentLabel);
  const pills = [catChips('Agentes', agents), catChips('Modelos', s.models || [])].filter(Boolean).join('');
  const statRow = stats.length ? `<div class="stat-row">${stats.join('')}</div>` : '';
  const pillRow = pills ? `<div class="pill-row">${pills}</div>` : '';
  return (statRow || pillRow) ? `<div class="kpi-block">${statRow}${pillRow}</div>` : '';
}

// ---- Chat ----
let CHAT_SESSIONS = [];
let CHAT_ARTIFACTS = [];
let ABOUT_ARTIFACT = '';
let CHAT_LABELS = {};
let CHAT_WS_PROJECT = {};
let CURRENT_SESSION = '';
let PROV_ACTIVE = {provider:'', model:''};

async function loadChat(){
  try{
    const [wsData, agentsData, subsData, provData] = await Promise.all([
      api('/api/workspaces'), api('/api/agents'), api('/api/subscriptions'), api('/api/providers')]);
    const wsSel = $('#chat-workspace');
    const agentSel = $('#chat-agent');
    const workspaces = wsData.workspaces || [];
    CHAT_LABELS = Object.assign({}, wsData.labels || {});
    (agentsData.agents || []).forEach(a => { AGENT_LABELS[a.id] = a.label; });
    CHAT_WS_PROJECT = {};
    (subsData.subscriptions || []).forEach(s => {
      if(s.workspace && s.project) CHAT_WS_PROJECT[s.workspace] = s.project;
    });
    const active = (provData.providers || []).find(p => p.selected);
    PROV_ACTIVE = {provider: active ? active.label : '', model: provData.selected_model || (active && active.default_model) || ''};
    if(wsSel){
      const current = wsSel.value || '';
      wsSel.innerHTML = '<option value="">(todos)</option>' + workspaces.map(ws =>
        `<option value="${esc(ws)}" ${ws===current?'selected':''}>${esc(CHAT_LABELS[ws]||ws)}</option>`
      ).join('');
      wsSel.value = current;
    }
    if(agentSel){
      const currentAgent = agentSel.value || 'resume-agent';
      agentSel.innerHTML = (agentsData.agents||[]).map(a =>
        `<option value="${esc(a.id)}" ${a.id===currentAgent?'selected':''}>${esc(a.label)}</option>`
      ).join('');
      if(currentAgent && !agentSel.value) agentSel.value = currentAgent;
      agentSel.onchange = renderChatCatalog;
    }
    await loadChatSessions();
    renderThread([]);
    renderChatCatalog();
    bindProviderModel('chat-llm-provider', 'chat-llm-model-wrap', '', '');
  }catch(e){
    const box = $('#chat-thread'); if(box) box.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`;
  }
}

// Property pills for the current selection, shown to the right of the composer
// buttons: no title, just pills reflecting the selected chat/artifact (agent,
// model, kind, project). With nothing selected it falls back to the composer's
// agent and the active provider/model.
function renderChatCatalog(){
  const box = $('#chat-catalog'); if(!box) return;
  const pills = [];
  const push = (v, cls) => { if(v) pills.push(`<span class="pill ${cls||''}">${esc(String(v))}</span>`); };
  if(ABOUT_ARTIFACT){
    const a = (ART_THREAD && ART_THREAD.artifact) || null;
    if(a){ push(a.kind, 'active'); push(a.model); push(a.project); }
  } else if(CURRENT_SESSION){
    const s = CHAT_SESSIONS.find(x => x.session_id === CURRENT_SESSION);
    if(s){ push(agentLabel(s.agent_id||''), 'active'); push(s.model); push(s.kind); push(s.project); }
  }
  if(!pills.length){
    const aid = $('#chat-agent')?.value;
    push(agentLabel(aid||''), 'active');
    push(PROV_ACTIVE.model);
    if(PROV_ACTIVE.provider) push(PROV_ACTIVE.provider, 'ok');
  }
  box.innerHTML = pills.join('');
}

function autodetectProject(){
  const proj = $('#chat-project');
  const ws = $('#chat-workspace')?.value;
  if(proj && !proj.value && ws && CHAT_WS_PROJECT[ws]) proj.value = CHAT_WS_PROJECT[ws];
}

function onChatWorkspace(){
  autodetectProject();
  loadChatSessions();
}

// Start a fresh session: the server autogenerates a new session id on send.
function newChatSession(){
  CURRENT_SESSION = '';
  ABOUT_ARTIFACT = ''; ART_THREAD = null; renderAnchor(null);
  const sid = $('#chat-session'); if(sid) sid.value = '';
  const msg = $('#chat-message'); if(msg) msg.value = '';
  renderThread([]);
  renderChatSide();
  renderChatCatalog();
  toast('Nueva sesión (se creará al enviar)');
}

// Infinite scroll backwards: near the top of an artifact thread, load older.
function onThreadScroll(){
  const box = $('#chat-thread'); if(!box || !ART_THREAD) return;
  if(box.scrollTop <= 40 && ART_THREAD.hasMore && !ART_THREAD.loading){
    loadArtifactThread(false);
  }
}

async function loadChatSessions(){
  const ws = $('#chat-workspace')?.value;
  const url = '/api/chat/sessions' + (ws ? '?workspace='+encodeURIComponent(ws) : '');
  try{
    const d = await api(url);
    CHAT_SESSIONS = d.sessions || [];
    Object.assign(CHAT_LABELS, d.labels || {});
  }catch(e){ CHAT_SESSIONS = []; }
  await loadChatArtifacts();
  renderChatSide();
}

// All stored artifacts become chat-able knowledge, grouped by logical subject
// (workspace + kind + thread) so the many summary versions of one thread collapse
// into a single entry. We drop chat.turn (belongs to a session) and any artifact
// already tagged with a session_id (shown as its session). Within a group the
// versions are newest-first; groups themselves are ordered newest-first later.
async function loadChatArtifacts(){
  const ws = $('#chat-workspace')?.value;
  const url = '/api/artifacts' + (ws ? '?workspace='+encodeURIComponent(ws) : '');
  try{
    const d = await api(url);
    const groups = {}; const order = [];
    (d.artifacts || []).forEach(sec => (sec.items || []).forEach(a => {
      const meta = a.metadata || {}, c = a.content || {};
      if(a.kind === 'chat.turn' || meta.session_id) return;
      const key = [a.workspace, a.kind, String(meta.thread_name||'')].join('\\u0001');
      const ver = {
        id: a.id, kind: a.kind, workspace: a.workspace,
        title: artifactFriendlyTitle(a),
        project: String(meta.project || c.project || ''),
        summary: String(c.summary || ''),
        model: String(meta.model || ''),
        last: artifactLastActivity(a),
        ts: String(a.timestamp || ''),
        count: Number.isInteger(c.message_count) ? c.message_count : (Array.isArray(c.messages) ? c.messages.length : null),
      };
      if(!groups[key]){ groups[key] = []; order.push(key); }
      groups[key].push(ver);
    }));
    CHAT_ARTIFACTS = order.map(key => {
      const versions = groups[key].slice().sort((x,y) => (y.ts||'').localeCompare(x.ts||''));
      const head = versions[0];
      return {
        key, workspace: head.workspace, kind: head.kind, project: head.project,
        title: head.title, summary: head.summary, model: head.model,
        last: head.last, count: head.count, versions,
      };
    });
  }catch(e){ CHAT_ARTIFACTS = []; }
}

// Friendly label: explicit title, then thread name, then the last message's
// title/author, falling back to a readable kind.
function artifactFriendlyTitle(a){
  const meta = a.metadata || {}, c = a.content || {};
  let lastTitle = '';
  if(Array.isArray(c.messages) && c.messages.length){
    const m = c.messages[c.messages.length - 1] || {};
    lastTitle = String(m.title || m.author || '');
  }
  const cand = String(meta.title||'') || String(meta.thread_name||'') || String(c.title||'') || lastTitle;
  if(cand) return cand;
  if(a.kind === 'project.status') return '📊 Estado del Proyecto';
  if(a.kind === 'conversation.summary') return 'Resumen de conversación';
  return a.kind;
}

// Date of the last originating message when available, else the artifact's own.
function artifactLastActivity(a){
  const c = a.content || {};
  if(Array.isArray(c.messages) && c.messages.length){
    const stamps = c.messages.map(m => (m && m.timestamp) ? String(m.timestamp) : '').filter(Boolean);
    if(stamps.length) return stamps.sort()[stamps.length - 1];
  }
  return a.timestamp || '';
}

function shortDate(iso){
  if(!iso) return '';
  const s = String(iso);
  return s.length >= 16 ? s.slice(0, 16).replace('T', ' ') : s;
}

// Token-aware search: every space-separated token must match the start of a
// word (delimited on the left by a non-alphanumeric), so "proyecto-e" hits
// proyecto-e only, "proyecto e" no longer matches proyecto-x by an inner
// substring, yet a partial like "conv" still finds "conversation". Implemented
// without regex/backslashes to keep this JS clean inside the Python string.
function chatMatch(hay, q){
  if(!q) return true;
  const text = (hay || '').toLowerCase();
  const isWord = c => (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
  const tokens = q.toLowerCase().split(' ').map(t => t.trim()).filter(Boolean);
  return tokens.every(tok => {
    let from = 0;
    while(from <= text.length){
      const idx = text.indexOf(tok, from);
      if(idx < 0) return false;
      const before = idx === 0 ? '' : text[idx - 1];
      if(!isWord(before)) return true;
      from = idx + 1;
    }
    return false;
  });
}

function filterChatSide(){ renderChatSide(); }

// One unified list of knowledge (chats + artifacts), grouped by project
// (workspace when none). Chats open their thread; artifacts open as a context
// card to chat about them.
function renderChatSide(){
  const q = ($('#chat-search')?.value || '').trim();
  const box = $('#chat-sessions'); if(!box) return;
  const entries = [];
  CHAT_SESSIONS.forEach((s,i) => entries.push({
    type:'chat', ref:i, ws:s.workspace,
    project:(s.project && String(s.project).trim()) || '',
    title:s.title || s.session_id,
    meta:`${agentLabel(s.agent_id||'-')} · ${s.kind||'conversation'}${(s.message_count!=null)?' · '+s.message_count+' msg':''}`,
    active:s.session_id===CURRENT_SESSION && !ABOUT_ARTIFACT,
    sort:String(s.updated_at || s.created_at || ''),
    search:[s.title,s.session_id,s.user_id,s.agent_id,s.project,s.kind,s.last_message,
      CHAT_LABELS[s.workspace]||s.workspace].join(' '),
  }));
  CHAT_ARTIFACTS.forEach((a,j) => {
    const n = a.versions ? a.versions.length : 1;
    const vers = n > 1 ? ` · ${n} versiones` : '';
    entries.push({
      type:'artifact', ref:j, ws:a.workspace,
      project:a.project,
      title:a.title,
      meta:`${a.kind}${a.count!=null?' · '+a.count+' msg':''}${vers}${a.last?' · '+shortDate(a.last):''}`,
      active:(a.versions||[]).some(v => v.id===ABOUT_ARTIFACT),
      sort:String(a.last || ''),
      search:[a.title,a.kind,a.project,a.summary,CHAT_LABELS[a.workspace]||a.workspace].join(' '),
    });
  });
  const items = entries.filter(e => chatMatch(e.search, q));
  if(!items.length){ box.innerHTML = '<p class="muted" style="font-size:.8rem">(sin conocimiento)</p>'; return; }
  const groups = {}; const order = []; const recent = {};
  items.forEach(e => {
    const key = e.project || (CHAT_LABELS[e.ws] || e.ws || '(sin workspace)');
    if(!groups[key]){ groups[key] = []; order.push(key); recent[key] = ''; }
    groups[key].push(e);
    if((e.sort||'') > recent[key]) recent[key] = e.sort || '';
  });
  // Newest-first: order project groups and their rows by most recent activity.
  order.sort((x,y) => (recent[y]||'').localeCompare(recent[x]||''));
  box.innerHTML = order.map(key => {
    const rows = groups[key]
      .sort((x,y) => (y.sort||'').localeCompare(x.sort||''))
      .map(e => {
        const ico = e.type === 'chat' ? '💬' : '📄';
        const click = e.type === 'chat' ? `openChatSession(${e.ref})` : `openArtifact(${e.ref})`;
        return `
      <div class="chat-item ${e.active?'active':''}" onclick="${click}">
        <span class="ci-title"><span class="ci-ico">${ico}</span>${esc(e.title)}</span>
        <span class="ci-meta">${esc(e.meta)} · ${esc(CHAT_LABELS[e.ws]||e.ws||'')}</span>
      </div>`;
      }).join('');
    return `<div class="chat-grp">${esc(key)}</div>${rows}`;
  }).join('');
}

// Open an artifact group: anchor on its newest version (for message loading and
// grounding new chat messages) and render the full thread with every summary run
// interleaved chronologically among the originating messages.
let ART_THREAD = null;
function openArtifact(j){
  const g = CHAT_ARTIFACTS[j]; if(!g || !g.versions || !g.versions.length) return;
  ART_THREAD = {group:g, artifact:g.versions[0], offset:0, hasMore:false, loading:false, messages:[]};
  applyArtifactSelection();
  loadArtifactThread(true);
}

// Anchor the composer + side panel + catalog on ART_THREAD's current version.
function applyArtifactSelection(){
  const a = ART_THREAD.artifact;
  ABOUT_ARTIFACT = a.id;
  CURRENT_SESSION = '';
  const sid = $('#chat-session'); if(sid) sid.value = '';
  const wsSel = $('#chat-workspace');
  if(wsSel && a.workspace){
    if(![...wsSel.options].some(o => o.value===a.workspace)) wsSel.add(new Option(CHAT_LABELS[a.workspace]||a.workspace, a.workspace));
    wsSel.value = a.workspace;
  }
  if(a.project){ const p = $('#chat-project'); if(p) p.value = a.project; }
  renderAnchor(a);
  renderChatSide();
  renderChatCatalog();
}

async function loadArtifactThread(reset){
  if(!ART_THREAD) return;
  if(ART_THREAD.loading || (!reset && !ART_THREAD.hasMore)) return;
  ART_THREAD.loading = true;
  const a = ART_THREAD.artifact;
  const box = $('#chat-thread');
  if(reset && box) box.innerHTML = '<p class="muted">Cargando hilo…</p>';
  const prevH = box ? box.scrollHeight : 0;
  const prevTop = box ? box.scrollTop : 0;
  try{
    const d = await api('/api/artifacts/thread?workspace='+encodeURIComponent(a.workspace)
      +'&artifact_id='+encodeURIComponent(a.id)+'&offset='+ART_THREAD.offset);
    const older = d.messages || [];
    ART_THREAD.messages = reset ? older.slice() : older.concat(ART_THREAD.messages);
    ART_THREAD.offset = d.next_offset != null ? d.next_offset : ART_THREAD.offset;
    ART_THREAD.hasMore = !!d.has_more;
    renderArtifactThread();
    if(box){
      // Start pinned to the newest message (bottom); when loading older messages
      // on scroll-up, keep the viewport anchored on what the user was reading.
      if(reset){ box.scrollTop = box.scrollHeight; }
      else { box.scrollTop = box.scrollHeight - prevH + prevTop; }
    }
  }catch(e){
    if(box && reset) box.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`;
  }finally{ ART_THREAD.loading = false; }
}

function renderArtifactThread(){
  const box = $('#chat-thread'); if(!box || !ART_THREAD) return;
  const versions = (ART_THREAD.group && ART_THREAD.group.versions) ? ART_THREAD.group.versions : [];
  const total = versions.length;
  const more = ART_THREAD.hasMore
    ? `<button class="thread-more" onclick="loadArtifactThread(false)">Cargar mensajes anteriores</button>` : '';
  // One chronological timeline: the originating messages plus every summary run,
  // sorted by time so each re-run appears in place among the messages (instead
  // of a carousel that only shows one version at a time).
  const items = [];
  ART_THREAD.messages.forEach(m => items.push({ts:String(m.timestamp||''), type:'msg', m}));
  versions.forEach((v,i) => items.push({ts:String(v.ts||v.last||''), type:'sum', v, i}));
  items.sort((x,y) => (x.ts||'').localeCompare(y.ts||''));
  const body = items.map(it => {
    if(it.type === 'msg'){
      const m = it.m;
      return `<div class="bubble msg"><span class="b-author">${esc(m.author||'')}</span>${esc(m.text||'')}<span class="b-meta">${esc(shortDate(m.timestamp)||'')}</span></div>`;
    }
    const v = it.v;
    // versions are newest-first, so index 0 is the latest run.
    const label = total > 1 ? `Resumen · corrida ${total - it.i}/${total}` : 'Resumen';
    const meta = [label, v.model?('🤖 '+esc(v.model)):'', v.ts?esc(shortDate(v.ts)):''].filter(Boolean).join(' · ');
    return `<div class="ctx-card"><div class="ctx-head">📄 ${esc(v.title||ART_THREAD.group.title||'')} · ${meta}</div>`
      + `<div class="ctx-body">${esc(v.summary||'')}</div></div>`;
  }).join('');
  const empty = items.length ? '' : '<p class="muted" style="font-size:.85rem">(sin mensajes de origen para este artifact)</p>';
  box.innerHTML = more + body + empty
    + `<p class="muted" style="font-size:.8rem;margin:.5rem 0 0">Escribí abajo para enriquecer este conocimiento con el agente elegido.</p>`;
}

function renderAnchor(a){
  const bar = $('#chat-anchor'); if(!bar) return;
  if(!a){ bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = '';
  bar.innerHTML = `<span class="pill active">📄 sobre: ${esc(a.title||a.kind)}</span>`
    + ` <a href="#" class="muted" style="font-size:.8rem" onclick="clearAnchor();return false">✕ quitar</a>`;
}

function clearAnchor(){ ABOUT_ARTIFACT = ''; ART_THREAD = null; renderAnchor(null); renderThread([]); renderChatSide(); renderChatCatalog(); }

function renderThread(messages){
  const box = $('#chat-thread'); if(!box) return;
  if(!messages || !messages.length){
    box.innerHTML = '<p class="muted">(sin mensajes — escribí abajo para empezar un chat)</p>';
    return;
  }
  box.innerHTML = messages.map(m => {
    if(m.role === 'message'){
      return `<div class="bubble msg"><span class="b-author">${esc(m.author||'')}</span>${esc(m.text||'')}<span class="b-meta">${esc(shortDate(m.timestamp)||'')}</span></div>`;
    }
    const cls = m.role === 'user' ? 'user' : 'assistant';
    const meta = (m.role === 'assistant' && m.model) ? `🤖 ${esc(m.model)} · ${esc(m.timestamp||'')}` : esc(m.timestamp||'');
    const content = m.role === 'assistant' ? renderMarkdown(m.text) : esc(m.text||'');
    return `<div class="bubble ${cls}">${content}<span class="b-meta">${meta}</span></div>`;
  }).join('');
  box.scrollTop = box.scrollHeight;
}

async function loadThread(workspace, sessionId){
  const box = $('#chat-thread');
  if(!workspace || !sessionId){ renderThread([]); return; }
  if(box) box.innerHTML = '<p class="muted">Cargando…</p>';
  try{
    const d = await api('/api/chat/thread?workspace='+encodeURIComponent(workspace)+'&session_id='+encodeURIComponent(sessionId));
    renderThread(d.messages || []);
  }catch(e){ if(box) box.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`; }
}

function openChatSession(i){
  const s = CHAT_SESSIONS[i]; if(!s) return;
  ABOUT_ARTIFACT = ''; ART_THREAD = null; renderAnchor(null);
  CURRENT_SESSION = s.session_id;
  $('#chat-session').value = s.session_id;
  const wsSel = $('#chat-workspace');
  if(wsSel && s.workspace){
    if(![...wsSel.options].some(o => o.value===s.workspace)) wsSel.add(new Option(CHAT_LABELS[s.workspace]||s.workspace, s.workspace));
    wsSel.value = s.workspace;
  }
  if(s.user_id) $('#chat-user').value = s.user_id;
  const aid = $('#chat-agent'); if(aid && s.agent_id) aid.value = s.agent_id;
  $('#chat-project').value = s.project || '';
  const k = $('#chat-kind');
  if(k && s.kind){ if(![...k.options].some(o => o.value===s.kind)) k.add(new Option(s.kind, s.kind)); k.value = s.kind; }
  renderChatSide();
  renderChatCatalog();
  loadThread(s.workspace, s.session_id);
}

async function sendChat(){
  if(CHAT_BUSY) return;
  const sessEl = $('#chat-session');
  // Ensure a stable session id up-front so an in-flight turn can be cancelled
  // (the server keys cancellation by workspace + session_id).
  let sessionId = sessEl.value.trim();
  if(!sessionId){ sessionId = genId(); sessEl.value = sessionId; }
  const body = {
    workspace: $('#chat-workspace').value,
    user_id: $('#chat-user').value.trim() || 'consola',
    agent_id: $('#chat-agent').value,
    message: $('#chat-message').value.trim(),
    project: $('#chat-project').value.trim() || null,
    kind: $('#chat-kind').value.trim() || 'conversation',
    session_id: sessionId,
    title: $('#chat-title').value.trim() || null,
    about_artifact: ABOUT_ARTIFACT || null,
    llm_provider: $('#chat-llm-provider') ? ($('#chat-llm-provider').value || null) : null,
    llm_model: fieldValue('chat-llm-model'),
  };
  if(!body.message){ toast('Escribí un mensaje', false); return; }
  if(!body.workspace){
    toast('Elegí un workspace en «Más opciones»', false);
    const more = $('#chat-more'); if(more) more.open = true;
    return;
  }
  const box = $('#chat-thread');
  // Optimistic: show the user's message immediately, then the pending reply.
  const pending = `<div id="chat-pending"><div class="bubble user">${esc(body.message)}<span class="b-meta">enviando…</span></div>`
    + '<div class="bubble assistant"><span class="spin">⏳ generando respuesta…</span></div></div>';
  if(box){ box.insertAdjacentHTML('beforeend', pending); box.scrollTop = box.scrollHeight; }
  setChatBusy(true, body.workspace, sessionId);
  try{
    const data = await api('/api/chat/send', {
      method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
    CURRENT_SESSION = data.session.session_id;
    $('#chat-session').value = CURRENT_SESSION;
    $('#chat-message').value = '';
    ART_THREAD = null;
    await loadThread(body.workspace, CURRENT_SESSION);
    toast('Chat guardado');
    loadChatSessions();
    renderChatCatalog();
  }catch(e){
    // Drop the pending spinner; show what actually happened in its place.
    const p = $('#chat-pending'); if(p) p.remove();
    if(box && CHAT_CANCELLED){
      box.insertAdjacentHTML('beforeend', '<div class="bubble assistant" style="border-color:#f8814f66">⏹ generación cancelada</div>');
    } else if(box){
      box.insertAdjacentHTML('beforeend', `<div class="bubble assistant" style="border-color:#f8814f66"><strong>⚠ No se pudo generar la respuesta</strong><div class="md" style="margin-top:.3rem">${esc(e.message)}</div></div>`);
      box.scrollTop = box.scrollHeight;
    }
  }finally{
    setChatBusy(false);
  }
}

// ---- Chat cancellation (stop an in-flight provider call) ----
let CHAT_BUSY = false;
let CHAT_CANCELLED = false;
let CHAT_CANCEL_CTX = null;
function genId(){
  if(window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g,'');
  return 'c' + Date.now().toString(16) + Math.random().toString(16).slice(2, 10);
}
function setChatBusy(busy, workspace, sessionId){
  CHAT_BUSY = busy;
  if(busy){ CHAT_CANCELLED = false; CHAT_CANCEL_CTX = {workspace, session_id: sessionId}; }
  else { CHAT_CANCEL_CTX = null; }
  const send = $('#chat-send'); const cancel = $('#chat-cancel');
  if(send){ send.disabled = busy; send.style.display = busy ? 'none' : ''; }
  if(cancel){ cancel.style.display = busy ? '' : 'none'; }
}
async function cancelChat(){
  if(!CHAT_BUSY || !CHAT_CANCEL_CTX) return;
  const cancel = $('#chat-cancel');
  if(cancel){ cancel.disabled = true; cancel.textContent = 'Cancelando…'; }
  CHAT_CANCELLED = true;
  try{
    await api('/api/chat/cancel', {
      method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify(CHAT_CANCEL_CTX)});
    toast('Generación cancelada');
  }catch(e){ toast('No se pudo cancelar: '+e.message, false); CHAT_CANCELLED = false; }
  finally{ if(cancel){ cancel.disabled = false; cancel.textContent = '⏹ Cancelar'; } }
}

// ---- Preview/Run cancellation ----
let PV_BUSY = false;
let PV_ABORT_CTRL = null;
let PV_RUN_ID = null;
function setPvBusy(busy){
  PV_BUSY = busy;
  if(busy){
    PV_ABORT_CTRL = new AbortController();
    PV_RUN_ID = 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2,8);
  } else {
    PV_ABORT_CTRL = null;
    PV_RUN_ID = null;
  }
  const cancel = $('#pv-cancel');
  if(cancel){ cancel.style.display = busy ? '' : 'none'; cancel.disabled = false; cancel.textContent = '⏹ Cancelar'; }
  $$('#tab-preview button.act:not(#pv-cancel)').forEach(b => b.disabled = busy);
}
async function cancelPreview(){
  if(!PV_BUSY) return;
  const cancel = $('#pv-cancel');
  if(cancel){ cancel.disabled = true; cancel.textContent = 'Cancelando…'; }
  if(PV_ABORT_CTRL) PV_ABORT_CTRL.abort();
  if(PV_RUN_ID){
    try{ await fetch('/api/run/cancel', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({run_id:PV_RUN_ID})}); }catch(e){}
  }
  toast('Operación cancelada');
}

// ---- Preview (dry-run: summarize without publishing) ----
function esc(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
// Render Markdown to sanitized HTML for chat bubbles. Falls back to escaped
// plain text (with line breaks) when the CDN libs are unavailable (offline).
let _MD = null;
function markdown(){
  if(_MD) return _MD;
  if(window.markdownit){
    _MD = window.markdownit({ html:false, linkify:true, breaks:true });
  }
  return _MD;
}
function renderMarkdown(s){
  s = s || '';
  const md = markdown();
  if(!md || !window.DOMPurify){
    return `<div class="md">${esc(s).replace(/\\n/g,'<br>')}</div>`;
  }
  const html = DOMPurify.sanitize(md.render(s), {USE_PROFILES:{html:true}});
  return `<div class="md">${html}</div>`;
}
async function loadPreview(){
  try{
    const d = await api('/api/subscriptions');
    const sel = $('#pv-sub');
    if(!d.subscriptions.length){
      sel.innerHTML = '<option value="">(sin suscripciones)</option>';
    } else {
      sel.innerHTML = d.subscriptions.map(s =>
        `<option value="${s.channel_id}">${esc(s.name||s.channel_id)} · ${esc(s.kind)}</option>`).join('');
    }
    bindProviderModel('pv-llm-provider', 'pv-llm-model-wrap', '', '');
    bindAgent('pv-agent', '', '(por defecto)');
  }catch(e){ /* ignore */ }
}
function renderPreview(data){
  const out = $('#pv-out');
  const arts = data.artifacts || [];
  if(!arts.length){ out.innerHTML = '<p class="muted">(sin resultado — no había contenido que resumir)</p>'; return; }
  out.innerHTML = '<div class="pill ok" style="margin-bottom:.6rem">vista previa · no se publicó nada</div>' +
    arts.map(a => {
      const summary = (a.content && a.content.summary) || JSON.stringify(a.content, null, 2);
      const model = (a.metadata && a.metadata.model) ? ` · modelo: ${esc(a.metadata.model)}` : '';
      return `<div class="muted" style="margin:.4rem 0">${esc(a.kind)} · ${esc(a.workspace)}${model}</div>`
        + `<pre class="out">${esc(summary)}</pre>`;
    }).join('');
}
async function runPreview(url, opts){
  if(PV_BUSY){ toast('Ya hay una operación en curso', false); return; }
  setPvBusy(true);
  // Inject run_id into body
  if(opts.body){
    const parsed = JSON.parse(opts.body);
    parsed.run_id = PV_RUN_ID;
    opts.body = JSON.stringify(parsed);
  }
  const out = $('#pv-out');
  out.innerHTML = '<p class="spin">⏳ Resumiendo… (esto puede tardar según el modelo; no se publica nada)</p>';
  try{
    const signal = PV_ABORT_CTRL ? PV_ABORT_CTRL.signal : undefined;
    const data = await api(url, {...opts, signal});
    renderPreview(data);
  }catch(e){
    if(e.name === 'AbortError'){ out.innerHTML = '<p class="muted">Operación cancelada.</p>'; }
    else { out.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`; }
  }finally{ setPvBusy(false); }
}
function pvOverride(){
  return {
    llm_provider: $('#pv-llm-provider') ? ($('#pv-llm-provider').value || null) : null,
    llm_model: fieldValue('pv-llm-model'),
    agent_id: $('#pv-agent') ? ($('#pv-agent').value || null) : null,
  };
}
function previewSubscription(){
  const channel_id = $('#pv-sub').value;
  if(!channel_id){ toast('No hay suscripción para previsualizar', false); return; }
  runPreview('/api/preview/subscription', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify(Object.assign({channel_id, extra_instructions: agentExtra()}, pvOverride()))});
}
function runSubscription(){
  const channel_id = $('#pv-sub').value;
  if(!channel_id){ toast('No hay suscripción para ejecutar', false); return; }
  const body = Object.assign({channel_id, force: $('#pv-force').checked, publish: $('#pv-publish').checked, extra_instructions: agentExtra()}, pvOverride());
  execRun('/api/run/subscription', body);
}
function runAll(){
  const body = {force: $('#pv-force').checked, publish: $('#pv-publish').checked, extra_instructions: agentExtra()};
  execRun('/api/run/all', body);
}
async function execRun(path, body){
  if(PV_BUSY){ toast('Ya hay una operación en curso', false); return; }
  setPvBusy(true);
  body.run_id = PV_RUN_ID;
  const out = $('#pv-out');
  const verb = body.publish ? 'Ejecutando y publicando' : 'Ejecutando';
  out.innerHTML = `<p class="spin">⏳ ${verb}… genera resúmenes y llena la cache${body.publish?' y publica en Discord':' (no publica)'}</p>`;
  try{
    const signal = PV_ABORT_CTRL ? PV_ABORT_CTRL.signal : undefined;
    const data = await api(path, {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body), signal});
    renderPreview(data);
    const note = data.published ? '✔ persistido · cache actualizada · publicado en Discord'
                                : '✔ persistido · cache actualizada · no se publicó';
    out.innerHTML = `<div class="pill ok" style="margin-bottom:.6rem">${note}</div>` + out.innerHTML;
    toast('Corrida completa');
  }catch(e){
    if(e.name === 'AbortError'){ out.innerHTML = '<p class="muted">Operación cancelada.</p>'; }
    else { out.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`; }
  }finally{ setPvBusy(false); }
}
function previewGithub(){
  const repo = $('#pv-repo').value.trim();
  if(!repo){ toast('Escribí owner/repo', false); return; }
  const limit = parseInt($('#pv-limit').value, 10) || 30;
  runPreview('/api/preview/github', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify(Object.assign({repo, limit, extra_instructions: agentExtra()}, pvOverride()))});
}

function toggleNav(){
  const shell = $('#shell'); if(!shell) return;
  shell.classList.toggle('collapsed');
  try{ localStorage.setItem('kaos-nav-collapsed', shell.classList.contains('collapsed')?'1':'0'); }catch(e){}
}
document.addEventListener('DOMContentLoaded', () => {
  $$('nav button').forEach(b => b.addEventListener('click', () => tab(b.dataset.tab)));
  const thread = $('#chat-thread'); if(thread) thread.addEventListener('scroll', onThreadScroll);
  try{ if(localStorage.getItem('kaos-nav-collapsed')==='1') $('#shell').classList.add('collapsed'); }catch(e){}
  tab('dashboards');
});
"""


# Optional client-side Markdown rendering for chat bubbles. Loaded from a CDN
# (same pattern as the dashboard's Mermaid); the console degrades gracefully to
# escaped plain text when offline, so nothing breaks without a network.
_MARKDOWN_IT_CDN = "https://cdn.jsdelivr.net/npm/markdown-it@14/dist/markdown-it.min.js"
_DOMPURIFY_CDN = "https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"


def render_console(*, title: str = "KAOS — Consola") -> str:
    """Render the self-contained admin console HTML."""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="shell" id="shell">
  <aside class="sidebar">
    <div class="side-top">
      <span class="brand">⚙️ <span class="brand-txt">KAOS</span></span>
      <button class="collapse" onclick="toggleNav()" title="Colapsar/expandir"><svg viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"></polyline></svg></button>
    </div>
    <nav>
      <button data-tab="dashboards"><span class="ic"><svg viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg></span><span class="lbl">Dashboards</span></button>
      <button data-tab="subscriptions"><span class="ic"><svg viewBox="0 0 24 24"><path d="M4 11a9 9 0 0 1 9 9"></path><path d="M4 4a16 16 0 0 1 16 16"></path><circle cx="5" cy="19" r="1"></circle></svg></span><span class="lbl">Subscriptions</span></button>
      <button data-tab="preview"><span class="ic"><svg viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg></span><span class="lbl">Vista previa</span></button>
      <button data-tab="chat"><span class="ic"><svg viewBox="0 0 24 24"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg></span><span class="lbl">Chat</span></button>
      <div class="nav-group"><span class="lbl">Configuración</span></div>
      <button data-tab="agents"><span class="ic"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"></rect><rect x="9" y="9" width="6" height="6"></rect><line x1="9" y1="1" x2="9" y2="4"></line><line x1="15" y1="1" x2="15" y2="4"></line><line x1="9" y1="20" x2="9" y2="23"></line><line x1="15" y1="20" x2="15" y2="23"></line><line x1="20" y1="9" x2="23" y2="9"></line><line x1="20" y1="14" x2="23" y2="14"></line><line x1="1" y1="9" x2="4" y2="9"></line><line x1="1" y1="14" x2="4" y2="14"></line></svg></span><span class="lbl">Agentes</span></button>
      <button data-tab="providers"><span class="ic"><svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="8" rx="2"></rect><rect x="2" y="13" width="20" height="8" rx="2"></rect><line x1="6" y1="7" x2="6.01" y2="7"></line><line x1="6" y1="17" x2="6.01" y2="17"></line></svg></span><span class="lbl">Providers</span></button>
    </nav>
  </aside>
  <div class="content">
    <main>
  <section id="tab-providers" class="tab">
    <h2>Proveedor LLM activo</h2>
    <div class="card">
      <div class="grid">
        <div><label for="provider-select">Provider</label>
          <select id="provider-select"></select></div>
        <div><label for="model-input">Modelo</label>
          <div id="model-input-wrap" data-model-id="model-input">
            <input id="model-input" placeholder="gpt-4o-mini"></div></div>
      </div>
      <div class="row" style="margin-top:1rem">
        <button class="act" onclick="saveProvider()">Guardar</button>
        <span class="muted" id="persist-note"></span>
      </div>
    </div>
    <h2>Catálogo</h2>
    <div id="providers"></div>
  </section>

  <section id="tab-agents" class="tab">
    <h2>Agentes disponibles</h2>
    <p class="muted">Los agentes son plugins que transforman contexto en conocimiento.
      Cada agente <strong>aumentable</strong> tiene su propio campo de prompt extra
      (foco/tono), sin cambiar la estructura de su salida. El del Resume Agent se
      aplica en <a href="#" onclick="tab('preview');return false">Vista previa</a> y al Ejecutar.</p>
    <div id="agents"></div>
  </section>

  <section id="tab-chat" class="tab">
    <div class="chat-layout">
      <aside class="chat-side">
        <input id="chat-search" autocomplete="off" placeholder="Buscar en el conocimiento…" oninput="filterChatSide()">
        <div class="chat-side-head">Conocimiento</div>
        <div id="chat-sessions" class="chat-list"></div>
      </aside>
      <div class="chat-main">
        <div id="chat-thread" class="chat-thread"></div>
        <div class="chat-composer">
          <input type="hidden" id="chat-session">
          <div id="chat-anchor" class="chat-anchor" style="display:none"></div>
          <textarea id="chat-message" rows="3" style="width:100%;background:#0f1115;border:1px solid #2f3646;border-radius:8px;color:#e6e6e6;padding:.5rem .6rem;font-size:.95rem" placeholder="Escribí tu mensaje…"></textarea>
          <div class="row" style="margin-top:.6rem;align-items:center">
            <div style="min-width:180px"><select id="chat-agent"></select></div>
            <button id="chat-send" class="act" onclick="sendChat()">Enviar</button>
            <button id="chat-cancel" class="act ghost" style="display:none;border-color:#f8814f66;color:#f8814f" onclick="cancelChat()">⏹ Cancelar</button>
            <button class="act ghost" onclick="newChatSession()">Nueva sesión</button>
            <div id="chat-catalog" class="chat-catalog"></div>
          </div>
          <details id="chat-more" style="margin-top:.6rem">
            <summary class="muted" style="cursor:pointer">Más opciones</summary>
            <div class="grid" style="margin-top:.6rem">
              <div><label for="chat-workspace">Workspace</label>
                <select id="chat-workspace" onchange="onChatWorkspace()"></select></div>
              <div><label for="chat-user">Usuario</label>
                <input id="chat-user" autocomplete="off" placeholder="consola"></div>
              <div><label for="chat-kind">Tipo</label>
                <select id="chat-kind">
                  <option value="conversation" selected>conversation</option>
                  <option value="decision">decision</option>
                  <option value="task">task</option>
                  <option value="risk">risk</option>
                  <option value="requirement">requirement</option>
                  <option value="meeting">meeting</option>
                  <option value="document">document</option>
                  <option value="technology">technology</option>
                </select></div>
              <div><label for="chat-project">Proyecto</label>
                <input id="chat-project" autocomplete="off" placeholder="(se autodetecta del workspace)"></div>
              <div style="grid-column:1 / -1"><label for="chat-title">Título</label>
                <input id="chat-title" autocomplete="off" placeholder="opcional"></div>
              <div><label for="chat-llm-provider">Proveedor LLM (opcional)</label>
                <select id="chat-llm-provider"></select></div>
              <div><label for="chat-llm-model">Modelo (opcional)</label>
                <div id="chat-llm-model-wrap" data-model-id="chat-llm-model"></div></div>
            </div>
          </details>
        </div>
      </div>
    </div>
  </section>

  <section id="tab-subscriptions" class="tab">    <h2 id="sub-form-title">Nueva suscripción</h2>
    <div class="card">
      <div class="grid">
        <div><label for="sub-channel">Channel / Forum id · GitHub owner/repo</label>
          <input id="sub-channel" placeholder="123456789 · owner/repo"></div>
        <div><label for="sub-kind">Tipo</label>
          <select id="sub-kind"><option value="forum">forum</option><option value="channel">channel</option><option value="github">github</option></select></div>
        <div><label for="sub-guild">Guild id (opcional)</label>
          <input id="sub-guild" placeholder="hereda de .env"></div>
        <div><label for="sub-resume">Resume thread id (opcional)</label>
          <input id="sub-resume" placeholder="PMO"></div>
        <div><label for="sub-project">Proyecto (opcional)</label>
          <input id="sub-project" placeholder="proyecto-x (agrupa y relaciona en el grafo)"></div>
        <div><label for="sub-every">Plan: cada N segundos (opcional)</label>
          <input id="sub-every" type="number" min="1" placeholder="ej. 3600 (vacío = cada pasada)"></div>
        <div><label for="sub-related">Relacionada con (opcional)</label>
          <select id="sub-related" multiple size="3"></select></div>
        <div><label>Publicar por defecto al ejecutar</label>
          <label class="row" style="color:#8a93a2;font-size:.85rem"><input type="checkbox" id="sub-publish" checked style="width:auto;margin-right:.4rem"> el scheduler publica esta suscripción</label></div>
        <div><label for="sub-llm-provider">Proveedor LLM (opcional)</label>
          <select id="sub-llm-provider"></select></div>
        <div><label for="sub-llm-model">Modelo (opcional)</label>
          <div id="sub-llm-model-wrap" data-model-id="sub-llm-model"></div></div>
        <div><label for="sub-agent">Agente (opcional)</label>
          <select id="sub-agent"></select></div>
      </div>
      <div class="row" style="margin-top:1rem">
        <button class="act" id="sub-submit" onclick="submitSub()">Suscribir</button>
        <button class="act ghost" id="sub-cancel" onclick="subFormReset()" style="display:none">Cancelar</button>
      </div>
    </div>
    <h2>Suscripciones activas</h2>
    <div id="subs"></div>
  </section>

  <section id="tab-preview" class="tab">
    <h2>Vista previa (dry-run)</h2>
    <p class="muted">Genera el resumen y lo muestra acá <strong>sin publicar en Discord</strong>.
      Igual lee la fuente (Discord/GitHub) para poder resumir.</p>
    <div class="card">
      <div class="grid">
        <div><label for="pv-sub">Suscripción</label>
          <select id="pv-sub"></select></div>
        <div id="pv-buttons" style="display:flex;align-items:flex-end;gap:.6rem;flex-wrap:wrap">
          <button class="act ghost" onclick="previewSubscription()">Previsualizar (no persiste)</button>
          <button class="act" onclick="runSubscription()">Ejecutar (persistir + cache)</button>
          <button class="act ghost" onclick="runAll()">Ejecutar todas</button>
        </div>
      </div>
      <label class="row" style="margin-top:.6rem;color:#8a93a2;font-size:.85rem">
        <input type="checkbox" id="pv-force" style="width:auto;margin-right:.4rem">
        Forzar re-resumen (ignora la cache)
      </label>
      <label class="row" style="margin-top:.2rem;color:#8a93a2;font-size:.85rem">
        <input type="checkbox" id="pv-publish" style="width:auto;margin-right:.4rem">
        Publicar en Discord (por defecto solo persiste)
      </label>
      <div class="grid" style="margin-top:.6rem">
        <div><label for="pv-llm-provider">Proveedor LLM (opcional)</label>
          <select id="pv-llm-provider"></select></div>
        <div><label for="pv-llm-model">Modelo (opcional)</label>
          <div id="pv-llm-model-wrap" data-model-id="pv-llm-model"></div></div>
        <div><label for="pv-agent">Agente (opcional)</label>
          <select id="pv-agent"></select></div>
      </div>
      <div class="muted">«Ejecutar» corre el pipeline real: guarda los resúmenes y llena la cache
        de conocimiento. Sin «Publicar», <strong>no se envía a Discord</strong>. «Previsualizar» solo muestra.</div>
    </div>
    <div class="card">
      <div class="grid">
        <div><label for="pv-repo">Repo de GitHub (owner/repo)</label>
          <input id="pv-repo" placeholder="hectorhuergo/kaos"></div>
        <div><label for="pv-limit">Límite de items</label>
          <input id="pv-limit" type="number" value="30" min="1"></div>
      </div>
      <div class="row" style="margin-top:1rem">
        <button class="act" onclick="previewGithub()">Previsualizar repo</button>
      </div>
    </div>
    <div style="margin-top:.8rem;display:flex;gap:.6rem;align-items:center">
      <button class="act ghost" id="pv-cancel" onclick="cancelPreview()" style="display:none">⏹ Cancelar</button>
    </div>
    <div id="pv-out"></div>
  </section>

  <section id="tab-dashboards" class="tab">
    <h2>Dashboards disponibles</h2>
    <p class="muted">Cada workspace muestra sus KPIs. <strong>Ejecutar</strong> persiste y actualiza la cache de
      conocimiento; marcá <strong>Publicar</strong> (refleja el estado de la suscripción) para además enviarlo a Discord.</p>
    <div id="dashboards"></div>
    <div style="margin-top:.8rem;display:flex;gap:.6rem;align-items:center">
      <button class="act ghost" id="dash-cancel" onclick="cancelDash()" style="display:none">⏹ Cancelar</button>
    </div>
    <div id="dash-out" style="margin-top:1rem"></div>
  </section>
</main>
  </div>
</div>
<div id="toast"></div>
<div id="run-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);align-items:center;justify-content:center;z-index:50">
  <div class="card" style="max-width:480px;width:90%;margin:0">
    <h3 style="margin-top:0">Ejecutar dashboard</h3>
    <p class="muted" id="run-modal-sub"></p>
    <div class="grid">
      <div><label for="run-llm-provider">Proveedor LLM</label>
        <select id="run-llm-provider"></select></div>
      <div><label for="run-llm-model">Modelo</label>
        <div id="run-llm-model-wrap" data-model-id="run-llm-model"></div></div>
      <div><label for="run-agent">Agente</label>
        <select id="run-agent"></select></div>
    </div>
    <label class="row" style="margin-top:.6rem;color:#8a93a2;font-size:.85rem">
      <input type="checkbox" id="run-publish" style="width:auto;margin-right:.4rem">
      Publicar en Discord (por defecto solo persiste + cache)
    </label>
    <div class="row" style="margin-top:1rem">
      <button class="act" onclick="confirmRunModal()">Ejecutar</button>
      <button class="act ghost" onclick="closeRunModal()">Cancelar</button>
    </div>
  </div>
</div>
<script src="{_MARKDOWN_IT_CDN}"></script>
<script src="{_DOMPURIFY_CDN}"></script>
<script>{_SCRIPT}</script>
</body>
</html>
"""

