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
from kaos.core.knowledge import KnowledgeGraph

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
"""

_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"


def render_dashboard(
    artifacts_by_workspace: Sequence[tuple[str, Sequence[Artifact]]],
    graph: KnowledgeGraph,
    *,
    title: str = "KAOS — Conocimiento",
    generated_at: datetime | None = None,
) -> str:
    """Render a self-contained HTML dashboard for the given knowledge."""
    when = (generated_at or utcnow()).isoformat(timespec="seconds")
    total = sum(len(arts) for _, arts in artifacts_by_workspace)

    sections: list[str] = []
    for workspace, artifacts in artifacts_by_workspace:
        cards = "\n".join(_card(a) for a in artifacts) or "<p class='meta'>(sin artifacts)</p>"
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
</body>
</html>
"""


def _card(artifact: Artifact) -> str:
    """Render one artifact as an HTML card."""
    title = artifact.metadata.get("thread_name") or (
        "📊 Estado del Proyecto" if artifact.kind == "project.status" else artifact.kind
    )
    tags = [f"<span>{html.escape(str(artifact.produced_by))}</span>"]
    model = artifact.metadata.get("model")
    if model:
        tags.append(f"<span>🤖 {html.escape(str(model))}</span>")
    count = artifact.content.get("message_count")
    if count is not None:
        tags.append(f"<span>{html.escape(str(count))} mensajes</span>")
    tags.append(f"<span>{html.escape(artifact.timestamp.isoformat(timespec='seconds'))}</span>")

    summary = html.escape(str(artifact.content.get("summary", "")))
    return (
        f"<div class='card'><h3>{html.escape(str(title))}</h3>"
        f"<div class='tags'>{''.join(tags)}</div>"
        f"<pre>{summary}</pre></div>"
    )

