"""
Renders a questionnaire as a fully self-contained, white-labeled HTML page.

No external JS or CSS dependencies — everything is inlined so the page works
even without internet access (important for air-gapped enterprise clients).
"""
from __future__ import annotations

import html as _html
import json as _json

STAGE_LABELS: dict[str, str] = {
    "s01_intake": "Project Setup",
    "s02_architecture": "Architecture Review",
    "s03_backend": "Backend Configuration",
    "s04_frontend": "Frontend & Design",
    "s05_quality": "Security Review",
    "s06_testing": "Testing Configuration",
    "s07_healing": "Auto-Repair Review",
    "s08_observability": "Monitoring Setup",
    "s09_devops": "Deployment Configuration",
    "s10_enterprise": "Enterprise Features",
    "s11_handoff": "Delivery Options",
    "s12_specialist": "Specialist Outputs",
}

STAGE_ORDER: list[str] = list(STAGE_LABELS.keys())

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
  background: #f5f5f5;
  color: #1a1a1a;
  min-height: 100vh;
  padding: 24px 16px;
}
.card {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 12px;
  max-width: 640px;
  margin: 0 auto;
  padding: 32px 28px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
.header img { height: 36px; object-fit: contain; }
.header-title { font-size: 18px; font-weight: 700; color: #111; }
.progress-bar { background: #e5e7eb; border-radius: 6px; height: 6px; margin-bottom: 8px; }
.progress-fill { background: #6d28d9; border-radius: 6px; height: 100%; transition: width 0.3s; }
.progress-label { font-size: 12px; color: #6b7280; margin-bottom: 24px; }
h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; color: #111; }
.subtitle { font-size: 14px; color: #6b7280; margin-bottom: 28px; }
.field { margin-bottom: 22px; }
.field label { display: block; font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 6px; }
.field .required { color: #ef4444; margin-left: 3px; }
.field .help { font-size: 12px; color: #9ca3af; margin-top: 4px; }
input[type=text], input[type=number], textarea, select {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #fafafa;
  color: #111;
  outline: none;
  transition: border-color 0.2s;
  font-family: inherit;
}
input[type=text]:focus, input[type=number]:focus, textarea:focus, select:focus {
  border-color: #6d28d9;
  background: #fff;
}
textarea { resize: vertical; }
.radio-group, .checkbox-group { display: flex; flex-direction: column; gap: 8px; }
.radio-group label, .checkbox-group label {
  display: flex; align-items: center; gap: 8px;
  font-weight: 400; cursor: pointer; font-size: 14px;
}
.radio-group input, .checkbox-group input { width: 16px; height: 16px; cursor: pointer; }
.btn {
  display: inline-block;
  padding: 12px 28px;
  background: #6d28d9;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  margin-top: 12px;
  transition: background 0.2s;
  font-family: inherit;
}
.btn:hover { background: #5b21b6; }
.btn:disabled { background: #c4b5fd; cursor: not-allowed; }
.success-box {
  text-align: center;
  padding: 32px 20px;
}
.success-box .check { font-size: 48px; margin-bottom: 16px; }
.success-box h2 { font-size: 20px; font-weight: 700; color: #111; margin-bottom: 8px; }
.success-box p { font-size: 14px; color: #6b7280; }
.error-msg { color: #ef4444; font-size: 13px; margin-top: 8px; display: none; }
.hidden { display: none !important; }
@media (max-width: 480px) {
  .card { padding: 20px 16px; }
  h1 { font-size: 18px; }
}
"""


def _e(text: str) -> str:
    """HTML-escape a string."""
    return _html.escape(str(text), quote=True)


def _render_question(q: dict) -> str:
    """Render a single question as HTML, wired up for depends_on visibility."""
    qid = q["id"]
    label = q.get("label", qid)
    qtype = q.get("type", "text")
    options = q.get("options", [])
    default = q.get("default", "")
    help_text = q.get("help", "")
    required = q.get("required", False)
    depends_on = q.get("depends_on")

    # Wrapper: hidden if depends_on is set (JS will show/hide)
    display_style = ' style="display:none"' if depends_on else ""
    dep_attrs = ""
    if depends_on:
        dep_attrs = (
            f' data-depends-on="{_e(depends_on["question_id"])}"'
            f' data-depends-value="{_e(str(depends_on["value"]).lower())}"'
        )

    req_mark = '<span class="required">*</span>' if required else ""
    help_html = f'<div class="help">{_e(help_text)}</div>' if help_text else ""

    if qtype == "text":
        input_html = (
            f'<input type="text" id="{_e(qid)}" name="{_e(qid)}"'
            f' value="{_e(str(default) if default else "")}"'
            f'{" required" if required else ""}>'
        )
    elif qtype == "textarea":
        input_html = (
            f'<textarea id="{_e(qid)}" name="{_e(qid)}" rows="4"'
            f'{" required" if required else ""}>{_e(str(default) if default else "")}</textarea>'
        )
    elif qtype == "number":
        input_html = (
            f'<input type="number" id="{_e(qid)}" name="{_e(qid)}"'
            f' value="{_e(str(default) if default is not None else "")}"'
            f'{" required" if required else ""}>'
        )
    elif qtype == "select":
        opts_html = ""
        for opt in options:
            selected = ' selected' if str(opt) == str(default) else ""
            opts_html += f'<option value="{_e(opt)}"{selected}>{_e(opt)}</option>'
        input_html = (
            f'<select id="{_e(qid)}" name="{_e(qid)}"'
            f'{" required" if required else ""}>{opts_html}</select>'
        )
    elif qtype == "multiselect":
        default_list = default if isinstance(default, list) else ([] if not default else [default])
        boxes = ""
        for opt in options:
            checked = ' checked' if opt in default_list else ""
            boxes += (
                f'<label><input type="checkbox" name="{_e(qid)}"'
                f' value="{_e(opt)}"{checked}> {_e(opt)}</label>'
            )
        input_html = f'<div class="checkbox-group">{boxes}</div>'
    elif qtype == "boolean":
        yes_checked = ' checked' if default is True else ""
        no_checked = ' checked' if default is False else ""
        input_html = (
            f'<div class="radio-group">'
            f'<label><input type="radio" name="{_e(qid)}" value="true"{yes_checked}> Yes</label>'
            f'<label><input type="radio" name="{_e(qid)}" value="false"{no_checked}> No</label>'
            f'</div>'
        )
    else:
        input_html = (
            f'<input type="text" id="{_e(qid)}" name="{_e(qid)}"'
            f' value="{_e(str(default) if default else "")}">'
        )

    return (
        f'<div class="field" id="field_{_e(qid)}"{display_style}{dep_attrs}>'
        f'<label for="{_e(qid)}">{_e(label)}{req_mark}</label>'
        f'{input_html}'
        f'{help_html}'
        f'</div>'
    )


def render_questionnaire_page(
    session_id: str,
    stage_id: str,
    questions: list[dict],
    agency_name: str | None,
    agency_logo_url: str | None,
    token: str,
    already_submitted: bool = False,
    submitted_at: str | None = None,
) -> str:
    """Return a complete, self-contained HTML page for the questionnaire.

    The page POSTs answers as JSON to /api/questionnaire/{token}/submit
    via the Fetch API — no page reload on success.
    """
    stage_label = STAGE_LABELS.get(stage_id, stage_id)
    brand = _e(agency_name) if agency_name else "AetherOS"
    title = f"{brand} — {_e(stage_label)}"

    stage_idx = STAGE_ORDER.index(stage_id) + 1 if stage_id in STAGE_ORDER else 1
    stage_total = len(STAGE_ORDER)
    pct = int(stage_idx / stage_total * 100)

    # Header branding
    if agency_logo_url:
        logo_html = f'<img src="{_e(agency_logo_url)}" alt="{brand} logo">'
    else:
        logo_html = ""
    header_html = (
        f'<div class="header">'
        f'{logo_html}'
        f'<div class="header-title">{brand}</div>'
        f'</div>'
    )

    if already_submitted:
        submitted_note = f"on {_e(submitted_at)}" if submitted_at else ""
        body_html = (
            f'<div class="success-box">'
            f'<div class="check">&#10003;</div>'
            f'<h2>Already submitted</h2>'
            f'<p>Your responses for <strong>{_e(stage_label)}</strong> have been recorded {submitted_note}.</p>'
            f'</div>'
        )
        script_html = ""
    else:
        # Render all question fields
        fields_html = "".join(_render_question(q) for q in questions)

        body_html = (
            f'<h1>{_e(stage_label)}</h1>'
            f'<p class="subtitle">Step {stage_idx} of {stage_total} — answer the questions below and click Submit.</p>'
            f'<form id="qform" novalidate>'
            f'{fields_html}'
            f'<div class="error-msg" id="form-error"></div>'
            f'<button type="submit" class="btn" id="submit-btn">Submit answers</button>'
            f'</form>'
            f'<div id="success-message" class="success-box hidden">'
            f'<div class="check">&#10003;</div>'
            f'<h2>Thank you!</h2>'
            f'<p>Your responses have been saved. The build will continue automatically.</p>'
            f'</div>'
        )

        # Build JS: depends_on show/hide + fetch submit
        questions_json = _json.dumps(questions)
        script_html = f"""
<script>
(function() {{
  var QUESTIONS = {questions_json};
  var TOKEN = "{_e(token)}";

  // ── depends_on show/hide ──────────────────────────────────────────────────
  function updateVisibility() {{
    document.querySelectorAll('[data-depends-on]').forEach(function(el) {{
      var depId = el.getAttribute('data-depends-on');
      var depVal = el.getAttribute('data-depends-value');
      var controller = document.querySelector('[name="' + depId + '"]');
      var visible = false;
      if (controller) {{
        if (controller.type === 'radio' || controller.type === 'checkbox') {{
          var checked = document.querySelector('[name="' + depId + '"]:checked');
          visible = checked && checked.value.toLowerCase() === depVal;
        }} else {{
          visible = controller.value.toLowerCase() === depVal;
        }}
      }}
      el.style.display = visible ? '' : 'none';
    }});
  }}
  document.addEventListener('change', updateVisibility);
  updateVisibility();

  // ── collect form values ──────────────────────────────────────────────────
  function collectAnswers() {{
    var answers = {{}};
    QUESTIONS.forEach(function(q) {{
      var id = q.id;
      var type = q.type;
      if (type === 'multiselect') {{
        var checked = Array.from(document.querySelectorAll('[name="' + id + '"]:checked')).map(function(el) {{ return el.value; }});
        answers[id] = checked;
      }} else if (type === 'boolean') {{
        var radio = document.querySelector('[name="' + id + '"]:checked');
        answers[id] = radio ? (radio.value === 'true') : null;
      }} else if (type === 'number') {{
        var el = document.getElementById(id);
        answers[id] = el && el.value !== '' ? parseFloat(el.value) : null;
      }} else {{
        var el = document.getElementById(id);
        answers[id] = el ? el.value : '';
      }}
    }});
    return answers;
  }}

  // ── validate required ────────────────────────────────────────────────────
  function validate(answers) {{
    var errors = [];
    QUESTIONS.forEach(function(q) {{
      if (!q.required) return;
      var fieldEl = document.getElementById('field_' + q.id);
      if (fieldEl && fieldEl.style.display === 'none') return; // hidden by depends_on
      var val = answers[q.id];
      if (val === null || val === undefined || val === '' || (Array.isArray(val) && val.length === 0)) {{
        errors.push(q.label + ' is required.');
      }}
    }});
    return errors;
  }}

  // ── submit ────────────────────────────────────────────────────────────────
  document.getElementById('qform').addEventListener('submit', function(e) {{
    e.preventDefault();
    var btn = document.getElementById('submit-btn');
    var errDiv = document.getElementById('form-error');
    errDiv.style.display = 'none';
    errDiv.textContent = '';
    var answers = collectAnswers();
    var errors = validate(answers);
    if (errors.length) {{
      errDiv.textContent = errors.join(' ');
      errDiv.style.display = 'block';
      return;
    }}
    btn.disabled = true;
    btn.textContent = 'Submitting…';
    fetch('/api/questionnaire/' + TOKEN + '/submit', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{answers: answers}})
    }}).then(function(r) {{
      return r.json().then(function(data) {{ return {{ok: r.ok, data: data}}; }});
    }}).then(function(res) {{
      if (res.ok) {{
        document.getElementById('qform').classList.add('hidden');
        document.getElementById('success-message').classList.remove('hidden');
      }} else {{
        errDiv.textContent = (res.data && res.data.error) ? res.data.error : 'Submission failed. Please try again.';
        errDiv.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Submit answers';
      }}
    }}).catch(function(err) {{
      errDiv.textContent = 'Network error. Please check your connection.';
      errDiv.style.display = 'block';
      btn.disabled = false;
      btn.textContent = 'Submit answers';
    }});
  }});
}})();
</script>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="card">
{header_html}
<div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>
<div class="progress-label">Step {stage_idx} of {stage_total}</div>
{body_html}
</div>
{script_html}
</body>
</html>"""
