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
  if(name==='subscriptions') loadSubscriptions();
  if(name==='dashboards') loadDashboards();
  if(name==='preview') loadPreview();
}

// ---- Providers ----
function credPill(p){
  if(!p.needs_secret) return '<span class="pill ok">no requiere credencial</span>';
  if(p.stored) return '<span class="pill ok">credencial en Postgres</span>';
  if(p.active_env) return '<span class="pill ok">credencial en .env</span>';
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
async function loadSubscriptions(){
  const box = $('#subs'); box.innerHTML = '<p class="muted">Cargando…</p>';
  try{
    const d = await api('/api/subscriptions');
    if(!d.subscriptions.length){ box.innerHTML = '<p class="muted">(sin suscripciones activas)</p>'; return; }
    box.innerHTML = d.subscriptions.map(s => `
      <div class="card"><div class="row">
        <div class="grow"><strong>${s.kind}</strong> · <code>${s.channel_id}</code>
          <div class="muted">workspace: ${s.workspace} · guild: ${s.guild_id||'-'} · resume: ${s.resume_thread_id||'-'}</div>
        </div>
        <button class="act danger" onclick="removeSub('${s.channel_id}')">Quitar</button>
      </div></div>`).join('');
  }catch(e){ box.innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
}
async function addSub(){
  const body = {
    channel_id: $('#sub-channel').value.trim(),
    kind: $('#sub-kind').value,
    guild_id: $('#sub-guild').value.trim() || null,
    resume_thread_id: $('#sub-resume').value.trim() || null,
  };
  if(!body.channel_id){ toast('Falta channel_id', false); return; }
  try{
    await api('/api/subscriptions', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify(body)});
    toast('Suscripción guardada');
    $('#sub-channel').value=''; $('#sub-guild').value=''; $('#sub-resume').value='';
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
    box.innerHTML = d.workspaces.map(ws => `
      <div class="card"><div class="row">
        <div class="grow"><strong>${ws}</strong></div>
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
        `<option value="${s.channel_id}">${s.kind} · ${s.channel_id}</option>`).join('');
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
    body: JSON.stringify({channel_id})}));
}
function previewGithub(){
  const repo = $('#pv-repo').value.trim();
  if(!repo){ toast('Escribí owner/repo', false); return; }
  const limit = parseInt($('#pv-limit').value, 10) || 30;
  runPreview(api('/api/preview/github', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({repo, limit})}));
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

  <section id="tab-subscriptions" class="tab">
    <h2>Nueva suscripción</h2>
    <div class="card">
      <div class="grid">
        <div><label for="sub-channel">Channel / Forum id</label>
          <input id="sub-channel" placeholder="123456789"></div>
        <div><label for="sub-kind">Tipo</label>
          <select id="sub-kind"><option value="forum">forum</option><option value="channel">channel</option></select></div>
        <div><label for="sub-guild">Guild id (opcional)</label>
          <input id="sub-guild" placeholder="hereda de .env"></div>
        <div><label for="sub-resume">Resume thread id (opcional)</label>
          <input id="sub-resume" placeholder="PMO"></div>
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
        <div style="display:flex;align-items:flex-end">
          <button class="act" onclick="previewSubscription()">Previsualizar suscripción</button></div>
      </div>
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

