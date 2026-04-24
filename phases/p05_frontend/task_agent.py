"""P05 Frontend Task Agent — single-file CDN React dashboard.

Strategy for qwen2.5-coder:3b:
  1. Read architecture.json from p02 to get API endpoints.
  2. Show the model a concrete mini-example, then ask it to write
     a similar component for the real endpoints.
  3. Validate the output (must contain function App + return + JSX).
  4. If validation fails, use a guaranteed-working vanilla-JS fallback
     (no React, no Babel needed — just fetch + DOM manipulation).
  5. Write index.html; gate checks the file exists and has valid structure.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)

# ── Architecture reader ───────────────────────────────────────────────────────

def _read_architecture(data: dict) -> dict:
    """Return architecture dict from any known location."""
    # 1. Direct path recorded in accumulated context by factory_pipeline
    arch_path = data.get("p02_architecture_path", "")
    if arch_path:
        try:
            return json.loads(Path(arch_path).read_text())
        except Exception:
            pass

    # 2. Scan project_dir for architecture.json
    project_dir = Path(data.get("project_dir", ""))
    if project_dir.exists():
        for candidate in sorted(project_dir.rglob("architecture.json"))[:3]:
            try:
                return json.loads(candidate.read_text())
            except Exception:
                continue

    # 3. Minimal default
    return {
        "api_endpoints": [
            {"method": "GET", "path": "/health", "description": "Health check", "auth": False}
        ],
        "tech_stack": {"backend": "FastAPI", "frontend": "React"},
    }


# ── LLM prompt ────────────────────────────────────────────────────────────────

def _build_prompt(project_name: str, endpoints: list) -> str:
    ep_lines = "\n".join(
        f"// {ep.get('method','GET')} {ep.get('path','/')} — {ep.get('description','')}"
        for ep in endpoints[:6]
    )
    ep_fetch_hint = "\n".join(
        f"    fetch('{ep.get('path','/')}').then(r=>r.json()).then(set_{_safe_key(ep)}).catch(()=>{{}});"
        for ep in endpoints[:6]
        if ep.get("method", "GET").upper() == "GET"
    )
    ep_state_hint = "\n  ".join(
        f"const [{_safe_key(ep)}, set_{_safe_key(ep)}] = React.useState(null);"
        for ep in endpoints[:6]
        if ep.get("method", "GET").upper() == "GET"
    )

    return f"""Write a complete React function component for {project_name}.

// Available endpoints:
{ep_lines}

Use this exact pattern:

function App() {{
  const [health, setHealth] = React.useState(null);

  React.useEffect(() => {{
    fetch('/health').then(r=>r.json()).then(setHealth).catch(()=>{{}});
  }}, []);

  return (
    <div>
      <h1>My App</h1>
      <div className="card">
        <h2>Health</h2>
        <pre>{{JSON.stringify(health, null, 2)}}</pre>
      </div>
    </div>
  );
}}

Now write the COMPLETE function App() for {project_name} that fetches from ALL the endpoints listed above and displays results. React is a global — no imports. Use className not class. Return ONLY the function code, nothing else."""


def _safe_key(ep: dict) -> str:
    """Derive a safe JS identifier from an endpoint path."""
    path = ep.get("path", "/ep").lstrip("/")
    key = re.sub(r"[^a-zA-Z0-9]", "_", path) or "ep"
    return key[:20].rstrip("_") or "ep"


# ── HTML builders ─────────────────────────────────────────────────────────────

_CSS = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }
    h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 1.5rem; color: #f8fafc; }
    h2 { font-size: 0.8rem; font-weight: 600; margin-bottom: 0.5rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
    .card { background: #1e293b; border: 1px solid #334155; border-radius: 0.5rem; padding: 1.25rem; margin-bottom: 1rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    th { text-align: left; padding: 0.4rem 0.6rem; color: #64748b; border-bottom: 1px solid #334155; font-size: 0.75rem; }
    td { padding: 0.4rem 0.6rem; border-bottom: 1px solid #1e293b; }
    tr:last-child td { border-bottom: none; }
    pre { font-size: 0.75rem; color: #94a3b8; white-space: pre-wrap; word-break: break-all; max-height: 300px; overflow: auto; }
    .loading { color: #475569; font-style: italic; font-size: 0.875rem; }
    .error { color: #f87171; font-size: 0.875rem; }
    .method { display: inline-block; font-size: 0.65rem; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 3px; margin-right: 0.4rem; background: #1d4ed8; color: #bfdbfe; }
"""


def _build_react_html(project_name: str, endpoints: list, component_body: str) -> str:
    """Wrap LLM-generated JSX component in a CDN React + Babel page."""
    ep_comment = "\n".join(
        f"  // {ep.get('method','GET')} {ep.get('path','/')} — {ep.get('description','')}"
        for ep in endpoints[:8]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name}</title>
  <script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>{_CSS}</style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
  /* {project_name} — auto-generated by AetherOS p05_frontend
{ep_comment}
  */

  {component_body}

  const _root = ReactDOM.createRoot(document.getElementById('root'));
  _root.render(<App />);
  </script>
</body>
</html>"""


def _build_vanilla_html(project_name: str, endpoints: list) -> str:
    """
    Pure vanilla-JS fallback — no React, no Babel, no JSX.
    Guaranteed to load without JS errors in any browser.
    """
    # Build one card div + one fetch block per GET endpoint
    cards_html = ""
    fetch_blocks = ""

    for ep in endpoints[:8]:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/health")
        desc = ep.get("description", path.lstrip("/"))
        safe_id = re.sub(r"[^a-zA-Z0-9]", "_", path.strip("/")) or "root_ep"

        cards_html += f"""
    <div class="card">
      <h2><span class="method">{method}</span>{desc}</h2>
      <p style="font-size:0.7rem;color:#475569;margin-bottom:0.75rem;font-family:monospace">{path}</p>
      <div id="ep_{safe_id}"><p class="loading">Loading...</p></div>
    </div>"""

        if method == "GET":
            fetch_blocks += f"""
  (function() {{
    var el = document.getElementById('ep_{safe_id}');
    fetch('{path}')
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (Array.isArray(data)) {{
          if (data.length === 0) {{ el.innerHTML = '<p class="loading">No items.</p>'; return; }}
          var keys = Object.keys(data[0] || {{}});
          var html = '<table><thead><tr>';
          keys.forEach(function(k) {{ html += '<th>' + k + '</th>'; }});
          html += '</tr></thead><tbody>';
          data.slice(0, 30).forEach(function(row) {{
            html += '<tr>';
            keys.forEach(function(k) {{ html += '<td>' + String(row[k] !== undefined ? row[k] : '') + '</td>'; }});
            html += '</tr>';
          }});
          html += '</tbody></table>';
          el.innerHTML = html;
        }} else {{
          el.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
        }}
      }})
      .catch(function(err) {{
        el.innerHTML = '<p class="error">Error: ' + err.message + '</p>';
      }});
  }})();"""
        else:
            # Non-GET: show a simple form placeholder
            fetch_blocks += f"""
  document.getElementById('ep_{safe_id}').innerHTML =
    '<p class="loading">{method} endpoint — use a form or API client to submit.</p>';"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name}</title>
  <style>{_CSS}</style>
</head>
<body>
  <div id="root">
    <h1>{project_name}</h1>
    {cards_html}
  </div>

  <script>
  /* {project_name} — AetherOS p05_frontend (vanilla-JS fallback) */
  document.addEventListener('DOMContentLoaded', function() {{
    {fetch_blocks}
  }});
  </script>
</body>
</html>"""


# ── LLM output validator ──────────────────────────────────────────────────────

def _validate_component(text: str) -> bool:
    """Return True if text looks like a valid React function component."""
    if not text:
        return False
    has_func  = "function App" in text or "const App" in text or "App =" in text
    has_return = "return" in text
    # Must contain JSX (either < elements or React.createElement)
    has_jsx    = bool(re.search(r'<[A-Za-z]', text)) or "React.createElement" in text
    return has_func and has_return and has_jsx


# ── Main entry point ──────────────────────────────────────────────────────────

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data

    # 1. Read architecture
    arch = _read_architecture(data)
    endpoints = arch.get("api_endpoints", [])
    if not endpoints:
        endpoints = [{"method": "GET", "path": "/health", "description": "Health check"}]

    project_name = data.get("project_name", "Project Dashboard")
    client = get_llm_client()
    used_llm = False

    # 2. Try LLM generation (60 s hard cap — 3b model is slow but not that slow)
    component_body: str | None = None
    try:
        prompt = _build_prompt(project_name, endpoints)
        raw = await asyncio.wait_for(
            client.call(prompt, "code_generation", {}),
            timeout=60.0,
        )

        # Strip markdown fences
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip().rstrip("`").strip()

        # If model returned partial output (starting mid-function), prepend declaration
        if raw and "function App" not in raw and "const App" not in raw:
            # Check if it looks like a function body
            if raw.lstrip().startswith(("const ", "let ", "return", "{")):
                raw = "function App() {\n" + raw
                if not raw.rstrip().endswith("}"):
                    raw += "\n}"

        if _validate_component(raw):
            component_body = raw
            used_llm = True
            logger.info("p05_frontend: LLM component valid (%d chars)", len(raw))
        else:
            logger.warning("p05_frontend: LLM output failed validation, using fallback")
    except Exception as exc:
        logger.warning("p05_frontend: LLM call failed: %s — using fallback", exc)

    # 3. Build HTML
    if component_body:
        html = _build_react_html(project_name, endpoints, component_body)
    else:
        html = _build_vanilla_html(project_name, endpoints)

    # 4. Write output
    out_file = output_dir / "index.html"
    out_file.write_text(html, encoding="utf-8")

    meta = {
        "output_file": str(out_file),
        "file_size_bytes": out_file.stat().st_size,
        "endpoints_used": len(endpoints),
        "used_llm": used_llm,
        "renderer": "react-babel" if component_body else "vanilla-js",
        "project_name": project_name,
    }
    (output_dir / "frontend_meta.json").write_text(json.dumps(meta, indent=2))

    logger.info(
        "p05_frontend: wrote %s (%d bytes, renderer=%s)",
        out_file, out_file.stat().st_size, meta["renderer"],
    )

    return TaskResult(
        output_path=str(out_file),
        confidence=0.95 if component_body else 0.85,
        metadata=meta,
        success=True,
        issues=[],
    )
