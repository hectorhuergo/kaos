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
.mermaid{min-width:max-content}
.mermaid svg{max-width:none !important;height:auto}
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
) -> str:
    """Render a self-contained HTML dashboard for the given knowledge.

    Artifacts that describe the same logical node (e.g. the same thread
    summarized by two different models) are grouped into a single, navigable card
    — arrows switch between versions, showing the model and date of each.
    """
    when = (generated_at or utcnow()).isoformat(timespec="seconds")
    total = sum(len(arts) for _, arts in artifacts_by_workspace)

    sections: list[str] = []
    for workspace, artifacts in artifacts_by_workspace:
        groups = group_artifacts(list(artifacts))
        cards = "\n".join(_card_group(g) for g in groups) or (
            "<p class='meta'>(sin artifacts)</p>"
        )
        sections.append(
            f"<section><h2>{html.escape(workspace)}</h2>\n{cards}</section>"
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
<header>
  <h1>{html.escape(title)}</h1>
  <div class="meta">{total} artifact(s) · generado {html.escape(when)}</div>
</header>
<main>
  <section class="graph">
    <h2>Trazabilidad</h2>
    <pre class="mermaid">{mermaid}</pre>
  </section>
  {"".join(sections)}
</main>
<script src="{_MERMAID_CDN}"></script>
<script>
  mermaid.initialize({{ startOnLoad: true, theme: "dark", securityLevel: "loose" }});
</script>
<script>{_SCRIPT}</script>
</body>
</html>
"""


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


