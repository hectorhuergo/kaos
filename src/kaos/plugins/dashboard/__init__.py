"""Static dashboard: a self-contained HTML view of KAOS knowledge.

A dashboard is just a *view* over artifacts (Knowledge before Reports). This
renders a single, dependency-free HTML file: the per-workspace artifacts as
cards (the executive summaries) plus a Mermaid traceability graph. It needs no
web server and no build step — open the file in a browser. A live API/dashboard
can come later; this is the immediate, testable first version.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from datetime import datetime

from kaos.contracts.artifact import Artifact
from kaos.contracts.event import utcnow
from kaos.core.knowledge import KnowledgeGraph, group_artifacts
from kaos.plugins.dashboard.metrics import summarize_workspace

_STYLE = """
:root{color-scheme:light dark}
body{font-family:system-ui,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header{padding:1.2rem 1.6rem;background:#161a22;border-bottom:1px solid #262b36}
h1{margin:0;font-size:1.3rem}
.meta{color:#8a93a2;font-size:.85rem;margin-top:.3rem}
main{padding:1.6rem;max-width:1100px;margin:0 auto}
section{margin-bottom:2rem}
.card{background:#161a22;border:1px solid #262b36;border-radius:10px;padding:1rem 1.2rem;margin:.8rem 0}
.card h3{margin:.1rem 0 .4rem}
.tags{color:#8a93a2;font-size:.8rem;margin-bottom:.6rem}
.tags span{margin-right:.9rem}
pre{white-space:pre-wrap;word-wrap:break-word;font-family:inherit;margin:0;line-height:1.45}
.graph{background:#161a22;border:1px solid #262b36;border-radius:10px;padding:1rem;overflow:auto;max-height:78vh}
/* Scale the diagram to the container instead of letting a few nodes grow huge:
   a percentage max-width + smaller fonts and thinner strokes keep small graphs
   readable (see Mermaid useMaxWidth in the init script). */
.mermaid{display:flex;justify-content:center}
.mermaid svg{max-width:100% !important;height:auto}
.mermaid .node rect,.mermaid .node polygon,.mermaid .node circle,.mermaid .node path{stroke-width:1px}
.mermaid .edgePath path,.mermaid .flowchart-link{stroke-width:1px !important}
.mermaid .nodeLabel,.mermaid .edgeLabel,.mermaid span{font-size:11px}
.mermaid .edgeLabel{background:#161a22}
/* Dashboard header: channel/forum details + indicators. */
.hdr-sub{color:#8a93a2;font-size:.9rem;margin-top:.2rem}
.hdr-topic{color:#a7b0be;font-size:.85rem;margin-top:.35rem;max-width:70ch}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.55rem}
.chip{font-size:.75rem;padding:.2rem .55rem;border-radius:999px;border:1px solid #2f3646;color:#c9d1da;background:#0f1115}
.chip b{color:#e6e6e6;font-weight:600}
.ws-id{color:#5b6472;font-size:.75rem;font-weight:400;margin-left:.5rem}
.kpis{display:flex;flex-direction:column;gap:.35rem;margin:.6rem 0 0}
.kpi-stats{display:flex;flex-wrap:wrap;gap:.15rem 1.1rem;color:#8a93a2;font-size:.8rem}
.kpi-stat .l{color:#6f7a89}
.kpi-stat b{color:#e6e6e6;font-weight:600}
.kpi-pills{display:flex;flex-wrap:wrap;gap:.35rem;align-items:center}
.kpi{font-size:.75rem;padding:.18rem .52rem;border-radius:999px;border:1px solid #2f3646;color:#c9d1da;background:#0f1115}
.kpi b{color:#fff;font-weight:600}
.kpi-cat{color:#6f7a89;font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;margin-right:.1rem}
.ver-nav{display:flex;align-items:center;gap:.6rem;margin:.1rem 0 .7rem}
.ver-btn{background:#0f1115;border:1px solid #2f3646;color:#e6e6e6;border-radius:6px;padding:.15rem .55rem;cursor:pointer;font-size:.9rem}
.ver-btn:hover{border-color:#4f8cff}
.ver-label{color:#8a93a2;font-size:.82rem}
.version[hidden]{display:none}
"""

_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"

_SCRIPT = """
function verNav(btn, dir){
  var card = btn.closest('.card');
  var vs = Array.prototype.slice.call(card.querySelectorAll('.version'));
  var cur = vs.findIndex(function(v){ return !v.hidden; });
  vs[cur].hidden = true;
  cur = (cur + dir + vs.length) % vs.length;
  vs[cur].hidden = false;
  var v = vs[cur];
  card.querySelector('.ver-label').textContent =
    (cur + 1) + ' / ' + vs.length + ' · 🤖 ' + (v.dataset.model || '—') + ' · ' + v.dataset.date;
}
"""


def render_dashboard(
    artifacts_by_workspace: Sequence[tuple[str, Sequence[Artifact]]],
    graph: KnowledgeGraph,
    *,
    title: str = "KAOS — Conocimiento",
    generated_at: datetime | None = None,
    header: dict[str, object] | None = None,
    workspace_labels: dict[str, str] | None = None,
) -> str:
    """Render a self-contained HTML dashboard for the given knowledge.

    Artifacts that describe the same logical node (e.g. the same thread
    summarized by two different models) are grouped into a single, navigable card
    — arrows switch between versions, showing the model and date of each.

    ``header`` optionally carries resolved channel/guild details (name, topic,
    member/online counts, …) shown in the page header. ``workspace_labels`` maps a
    workspace id (``discord:123``) to a friendly name so section titles read as
    the channel/forum name instead of a raw id.
    """
    when = (generated_at or utcnow()).isoformat(timespec="seconds")
    total = sum(len(arts) for _, arts in artifacts_by_workspace)
    labels = workspace_labels or {}

    sections: list[str] = []
    for workspace, artifacts in artifacts_by_workspace:
        groups = group_artifacts(list(artifacts))
        cards = "\n".join(_card_group(g) for g in groups) or (
            "<p class='meta'>(sin artifacts)</p>"
        )
        label = labels.get(workspace, workspace)
        heading = html.escape(label)
        if label != workspace:
            heading += f"<span class='ws-id'>{html.escape(workspace)}</span>"
        metrics = summarize_workspace(artifacts)
        sections.append(
            f"<section><h2>{heading}</h2>{_metrics_html(metrics)}\n{cards}</section>"
        )

    mermaid = html.escape(graph.to_mermaid())
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
{_header_html(title, when, total, header)}
<main>
  <section class="graph">
    <h2>Trazabilidad</h2>
    <pre class="mermaid">{mermaid}</pre>
  </section>
  {"".join(sections)}
</main>
<script src="{_MERMAID_CDN}"></script>
<script>
  mermaid.initialize({{
    startOnLoad: true, theme: "dark", securityLevel: "loose",
    themeVariables: {{ fontSize: "12px" }},
    flowchart: {{ useMaxWidth: true, htmlLabels: true,
                 nodeSpacing: 25, rankSpacing: 35, padding: 6 }}
  }});
</script>
<script>{_SCRIPT}</script>
</body>
</html>
"""


def _header_html(
    title: str, when: str, total: int, header: dict[str, object] | None
) -> str:
    """Render the page header, enriched with channel/guild details when known."""
    meta = f"{total} artifact(s) · generado {html.escape(when)}"
    if not header:
        return (
            "<header>\n"
            f'  <h1>{html.escape(title)}</h1>\n'
            f'  <div class="meta">{meta}</div>\n'
            "</header>"
        )

    channel = _as_dict(header.get("channel"))
    guild = _as_dict(header.get("guild"))
    name = str(channel.get("name") or header.get("workspace") or title)
    guild_name = str(guild.get("name") or "")
    sub = f"💬 {html.escape(name)}"
    if guild_name:
        sub += f" · 🏠 {html.escape(guild_name)}"

    topic = str(channel.get("topic") or "")
    topic_html = f'<div class="hdr-topic">{html.escape(topic)}</div>' if topic else ""

    chips = "".join(_chip(lbl, val) for lbl, val in _indicators(channel, guild))
    chips_html = f'<div class="chips">{chips}</div>' if chips else ""

    return (
        "<header>\n"
        f'  <h1>{html.escape(title)}</h1>\n'
        f'  <div class="hdr-sub">{sub}</div>\n'
        f"  {topic_html}\n"
        f"  {chips_html}\n"
        f'  <div class="meta" style="margin-top:.55rem">{meta}</div>\n'
        "</header>"
    )


def _as_dict(value: object) -> dict[str, object]:
    """Coerce a header sub-section to a dict (empty when missing/malformed)."""
    return value if isinstance(value, dict) else {}


def _indicators(
    channel: dict[str, object], guild: dict[str, object]
) -> list[tuple[str, object]]:
    """The available channel/guild indicators, skipping unknown ones."""
    candidates: list[tuple[str, object]] = [
        ("👥 miembros", guild.get("members")),
        ("🟢 en línea", guild.get("online")),
        ("🛡️ roles admin", guild.get("admin_roles")),
        ("🚀 boosts", guild.get("boosts")),
        ("🧵 tipo", channel.get("type_label")),
    ]
    return [(label, value) for label, value in candidates if value not in (None, "")]


def _chip(label: str, value: object) -> str:
    return f"<span class='chip'>{html.escape(label)} <b>{html.escape(str(value))}</b></span>"


def _metrics_html(metrics: dict[str, object]) -> str:
    stats = []
    if metrics.get("asset_count") is not None:
        stats.append(_stat("Assets", metrics["asset_count"]))
    if metrics.get("artifact_count") is not None:
        stats.append(_stat("Artefactos", metrics["artifact_count"]))
    if metrics.get("last_execution"):
        stats.append(_stat("Última ejecución", metrics["last_execution"]))
    if metrics.get("session_count"):
        stats.append(_stat("Sesiones", metrics["session_count"]))
    if metrics.get("message_count"):
        stats.append(_stat("Mensajes", metrics["message_count"]))
    agents = _as_str_list(metrics.get("agent_labels") or metrics.get("agents"))
    models = _as_str_list(metrics.get("models"))
    pills = _kpi_group("Agentes", agents) + _kpi_group("Modelos", models)
    stat_row = f"<div class='kpi-stats'>{''.join(stats)}</div>" if stats else ""
    pill_row = f"<div class='kpi-pills'>{pills}</div>" if pills else ""
    body = stat_row + pill_row
    return f"<div class='kpis'>{body}</div>" if body else ""


def _stat(label: str, value: object) -> str:
    return (
        f"<span class='kpi-stat'><span class='l'>{html.escape(label)}:</span> "
        f"<b>{html.escape(str(value))}</b></span>"
    )


def _as_str_list(value: object) -> list[str]:
    """Coerce a metrics value into a list of strings (empty when not a sequence)."""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def _kpi_group(label: str, values: Sequence[str]) -> str:
    """Render a labelled category (``Agentes``/``Modelos``) with one chip per value."""
    if not values:
        return ""
    tag = f"<span class='kpi-cat'>{html.escape(label)}</span>"
    items = "".join(
        f"<span class='kpi'>{html.escape(v)}</span>" for v in values
    )
    return tag + items


def _artifact_title(artifact: Artifact) -> str:
    return str(
        artifact.metadata.get("thread_name")
        or ("📊 Estado del Proyecto" if artifact.kind == "project.status" else artifact.kind)
    )


def _version_body(artifact: Artifact, *, hidden: bool) -> str:
    """Render one version (tags + summary) inside a grouped card."""
    tags = [f"<span>{html.escape(str(artifact.produced_by))}</span>"]
    model = artifact.metadata.get("model")
    if model:
        tags.append(f"<span>🤖 {html.escape(str(model))}</span>")
    count = artifact.content.get("message_count")
    if count is not None:
        tags.append(f"<span>{html.escape(str(count))} mensajes</span>")
    date = artifact.timestamp.isoformat(timespec="seconds")
    tags.append(f"<span>{html.escape(date)}</span>")

    summary = html.escape(str(artifact.content.get("summary", "")))
    hide = " hidden" if hidden else ""
    return (
        f"<div class='version'{hide} data-model='{html.escape(str(model or '—'))}' "
        f"data-date='{html.escape(date)}'>"
        f"<div class='tags'>{''.join(tags)}</div>"
        f"<pre>{summary}</pre></div>"
    )


def _card_group(artifacts: Sequence[Artifact]) -> str:
    """Render a node's artifacts as one card; multiple versions become a carousel.

    ``artifacts`` are the versions of the same logical node, newest first.
    """
    first = artifacts[0]
    title = _artifact_title(first)
    n = len(artifacts)

    nav = ""
    if n > 1:
        model = html.escape(str(first.metadata.get("model") or "—"))
        date = html.escape(first.timestamp.isoformat(timespec="seconds"))
        nav = (
            "<div class='ver-nav'>"
            "<button class='ver-btn' onclick='verNav(this,-1)'>◀</button>"
            f"<span class='ver-label'>1 / {n} · 🤖 {model} · {date}</span>"
            "<button class='ver-btn' onclick='verNav(this,1)'>▶</button>"
            "</div>"
        )

    versions = "".join(
        _version_body(a, hidden=(i != 0)) for i, a in enumerate(artifacts)
    )
    return (
        f"<div class='card'><h3>{html.escape(title)}</h3>"
        f"{nav}<div class='versions'>{versions}</div></div>"
    )


