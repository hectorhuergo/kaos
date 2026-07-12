"""KAOS web console: a self-contained admin page (Providers, Subscriptions, Dashboards).

Rendered as a single HTML document with vanilla JS that talks to the JSON API
exposed by :mod:`kaos.plugins.dashboard.app`. No build step and no frontend
dependencies — it is served by ``kaos serve`` at ``/console``.

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
nav{display:flex;gap:.4rem;padding:0 1.6rem;background:#12151c;border-bottom:1px solid #262b36}
nav button{background:none;border:none;color:#8a93a2;padding:.9rem 1rem;cursor:pointer;font-size:.95rem;border-bottom:2px solid transparent}
nav button.active{color:#e6e6e6;border-bottom-color:#4f8cff}
main{padding:1.6rem;max-width:1000px;margin:0 auto}
.tab{display:none}.tab.active{display:block}
h2{font-size:1.05rem;margin:0 0 1rem}
.card{background:#161a22;border:1px solid #262b36;border-radius:10px;padding:1rem 1.2rem;margin:.7rem 0}
.row{display:flex;align-items:center;gap:.8rem;flex-wrap:wrap}
.row .grow{flex:1}
.pill{font-size:.72rem;padding:.15rem .5rem;border-radius:999px;border:1px solid #2f3646;color:#8a93a2}
.pill.ok{color:#7ee787;border-color:#2ea04326}
.pill.no{color:#f8814f;border-color:#f8814f26}
.pill.active{color:#4f8cff;border-color:#4f8cff40}
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
  if(name==='dashboards') loadDashboards();
  if(name==='preview') loadPreview();
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
  if(p.env_ready) return '<span class="pill ok">credencial en .env</span>';
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
    if(!$('#model-input').value) $('#model-input').value = d.selected_model || '';
    box.innerHTML = d.providers.map(p => `
      <div class="card">
        <div class="row">
          <div class="grow"><strong>${p.label}</strong> <span class="muted">${p.id}</span>
            <div class="muted">${p.notes}</div>
            <div class="muted">modelo por defecto: <code>${p.default_model}</code></div>
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
    if(!SUBS.length){ box.innerHTML = '<p class="muted">(sin suscripciones activas)</p>'; return; }
    box.innerHTML = SUBS.map((s,i) => `
      <div class="card">
        <div class="row">
          <div class="grow"><strong>${esc(s.name||s.channel_id)}</strong> <span class="pill">${esc(s.kind)}</span>${s.project?` <span class="pill">📦 ${esc(s.project)}</span>`:''}${s.publish_default?'':' <span class="pill no">solo conocimiento</span>'}${(s.related_to&&s.related_to.length)?` <span class="pill">🔗 ${s.related_to.length}</span>`:''}
            <div class="muted"><code>${esc(s.channel_id)}</code> · workspace: ${esc(s.workspace)} · resume: ${esc(s.resume_thread_id||'-')} · plan: ${s.interval_seconds?('cada '+s.interval_seconds+'s'):'cada pasada'}</div>
          </div>
          <button class="act danger" onclick="removeSub('${esc(s.channel_id)}')">Quitar</button>
        </div>
        <details style="margin-top:.6rem">
          <summary class="muted" style="cursor:pointer">Editar</summary>
          <div class="grid" style="margin-top:.6rem">
            <div><label for="ed-project-${i}">Proyecto</label>
              <input id="ed-project-${i}" value="${esc(s.project||'')}" placeholder="proyecto-x"></div>
            <div><label>Publicar por defecto al ejecutar</label>
              <label class="row" style="color:#8a93a2;font-size:.85rem"><input type="checkbox" id="ed-publish-${i}" ${s.publish_default?'checked':''} style="width:auto;margin-right:.4rem"> el scheduler publica esta suscripción</label></div>
          </div>
          <label for="ed-related-${i}">Relacionada con (otras suscripciones)</label>
          <select id="ed-related-${i}" multiple size="4">${wsOptions(s.related_to, s.workspace)}</select>
          <div class="row" style="margin-top:.6rem"><button class="act" onclick="saveSubEdit(${i})">Guardar cambios</button></div>
        </details>
      </div>`).join('');
  }catch(e){ box.innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
}
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
  };
  if(!body.channel_id){ toast('Falta channel_id', false); return; }
  try{
    await api('/api/subscriptions', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify(body)});
    toast('Suscripción guardada');
    $('#sub-channel').value=''; $('#sub-guild').value=''; $('#sub-resume').value=''; $('#sub-every').value=''; $('#sub-project').value='';
    loadSubscriptions();
  }catch(e){ toast(e.message, false); }
}
async function saveSubEdit(i){
  const s = SUBS[i];
  const body = {
    project: $('#ed-project-'+i).value.trim() || null,
    publish_default: $('#ed-publish-'+i).checked,
    related_to: selectedValues($('#ed-related-'+i)),
  };
  try{
    await api('/api/subscriptions/'+encodeURIComponent(s.channel_id),
      {method:'PATCH', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
    toast('Suscripción actualizada');
    loadSubscriptions();
  }catch(e){ toast(e.message, false); }
}
async function removeSub(id){
  try{ await api('/api/subscriptions/'+encodeURIComponent(id), {method:'DELETE'});
    toast('Suscripción quitada'); loadSubscriptions();
  }catch(e){ toast(e.message, false); }
}

// ---- Dashboards ----
async function loadDashboards(){
  const box = $('#dashboards'); box.innerHTML = '<p class="muted">Cargando…</p>';
  try{
    const d = await api('/api/workspaces');
    if(!d.workspaces.length){ box.innerHTML = '<p class="muted">(sin workspaces — crea una suscripción)</p>'; return; }
    const labels = d.labels || {};
    box.innerHTML = d.workspaces.map(ws => `
      <div class="card"><div class="row">
        <div class="grow"><strong>${esc(labels[ws]||ws)}</strong> <span class="muted">${esc(ws)}</span></div>
        <a class="act ghost" href="/?workspace=${encodeURIComponent(ws)}" target="_blank">Abrir dashboard ↗</a>
      </div></div>`).join('');
  }catch(e){ box.innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
}

// ---- Preview (dry-run: summarize without publishing) ----
function esc(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
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
async function runPreview(promise){
  const out = $('#pv-out');
  out.innerHTML = '<p class="spin">⏳ Resumiendo… (esto puede tardar según el modelo; no se publica nada)</p>';
  try{ renderPreview(await promise); }
  catch(e){ out.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`; }
}
function previewSubscription(){
  const channel_id = $('#pv-sub').value;
  if(!channel_id){ toast('No hay suscripción para previsualizar', false); return; }
  runPreview(api('/api/preview/subscription', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({channel_id, extra_instructions: agentExtra()})}));
}
function runSubscription(){
  const channel_id = $('#pv-sub').value;
  if(!channel_id){ toast('No hay suscripción para ejecutar', false); return; }
  const body = {channel_id, force: $('#pv-force').checked, publish: $('#pv-publish').checked, extra_instructions: agentExtra()};
  execRun('/api/run/subscription', body);
}
function runAll(){
  const body = {force: $('#pv-force').checked, publish: $('#pv-publish').checked, extra_instructions: agentExtra()};
  execRun('/api/run/all', body);
}
function execRun(path, body){
  const out = $('#pv-out');
  const verb = body.publish ? 'Ejecutando y publicando' : 'Ejecutando';
  out.innerHTML = `<p class="spin">⏳ ${verb}… genera resúmenes y llena la cache${body.publish?' y publica en Discord':' (no publica)'}</p>`;
  api(path, {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)})
    .then(data => {
      renderPreview(data);
      const note = data.published ? '✔ persistido · cache actualizada · publicado en Discord'
                                  : '✔ persistido · cache actualizada · no se publicó';
      out.innerHTML = `<div class="pill ok" style="margin-bottom:.6rem">${note}</div>` + out.innerHTML;
      toast('Corrida completa');
    })
    .catch(e => { out.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`; });
}
function previewGithub(){
  const repo = $('#pv-repo').value.trim();
  if(!repo){ toast('Escribí owner/repo', false); return; }
  const limit = parseInt($('#pv-limit').value, 10) || 30;
  runPreview(api('/api/preview/github', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({repo, limit, extra_instructions: agentExtra()})}));
}

document.addEventListener('DOMContentLoaded', () => {
  $$('nav button').forEach(b => b.addEventListener('click', () => tab(b.dataset.tab)));
  tab('providers');
});
"""


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
<header>
  <h1>⚙️ {title}</h1>
  <div class="meta">Providers, Subscriptions, Vista previa y Dashboards</div>
</header>
<nav>
  <button data-tab="providers">Providers</button>
  <button data-tab="agents">Agentes</button>
  <button data-tab="subscriptions">Subscriptions</button>
  <button data-tab="preview">Vista previa</button>
  <button data-tab="dashboards">Dashboards</button>
</nav>
<main>
  <section id="tab-providers" class="tab">
    <h2>Proveedor LLM activo</h2>
    <div class="card">
      <div class="grid">
        <div><label for="provider-select">Provider</label>
          <select id="provider-select"></select></div>
        <div><label for="model-input">Modelo</label>
          <input id="model-input" placeholder="gpt-4o-mini"></div>
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

  <section id="tab-subscriptions" class="tab">    <h2>Nueva suscripción</h2>
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
      </div>
      <div class="row" style="margin-top:1rem">
        <button class="act" onclick="addSub()">Suscribir</button>
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
        <div style="display:flex;align-items:flex-end;gap:.6rem;flex-wrap:wrap">
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
    <div id="pv-out"></div>
  </section>

  <section id="tab-dashboards" class="tab">
    <h2>Dashboards disponibles</h2>
    <div id="dashboards"></div>
  </section>
</main>
<div id="toast"></div>
<script>{_SCRIPT}</script>
</body>
</html>
"""

