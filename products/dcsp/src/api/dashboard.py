"""
Dashboard core: router definitions, login/logout, and the main /dashboard route.

All view pages live in dashboard_views.py.
Job management routes live in dashboard_jobs.py.
HTML templates and CSS constants live in templates.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.api.auth_router import get_current_user
from src.api.templates import render_main_dashboard_html
from src.database import SessionLocal
from src.db.audit_repo import save_audit_log

logger = logging.getLogger(__name__)

# Public routes (login, logout, landing, register, forgot/reset password)
router = APIRouter()

# Authenticated routes — dependency ensures valid session on every endpoint
auth_dashboard_router = APIRouter(dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def landing_page():
    """Public landing page — redirects authenticated users to dashboard."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DCSP — AI-Powered CI Self-Healing</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#07070F;--surface:#0E0E1A;--border:rgba(124,58,237,0.18);--purple:#7C3AED;--pglow:rgba(124,58,237,0.35);--cyan:#00C4D4;--cglow:rgba(0,196,212,0.25);--text:#E8E6F0;--muted:#9896A8}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);overflow-x:hidden}
a{text-decoration:none;color:inherit}
#pc{position:fixed;inset:0;z-index:0;pointer-events:none}
.wrap{position:relative;z-index:1}
nav{display:flex;align-items:center;justify-content:space-between;padding:20px 48px;border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100;background:rgba(7,7,15,0.85);backdrop-filter:blur(16px)}
.nav-logo{font-family:'Syne',sans-serif;font-weight:800;font-size:22px;letter-spacing:-0.5px;color:#fff}
.nav-logo span{color:var(--cyan)}
.nav-mid{display:flex;gap:32px;align-items:center}
.nav-mid a{font-size:14px;color:var(--muted);font-weight:500;transition:color .2s}
.nav-mid a:hover{color:#fff}
.nav-cta{display:flex;gap:12px}
.btn{display:inline-flex;align-items:center;justify-content:center;padding:10px 22px;border-radius:8px;font-weight:600;font-size:14px;cursor:pointer;transition:all .2s;font-family:'DM Sans',sans-serif}
.btn-ghost{border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{border-color:var(--purple);color:#fff}
.btn-primary{background:var(--purple);color:#fff;box-shadow:0 0 20px var(--pglow)}
.btn-primary:hover{background:#6D28D9;box-shadow:0 0 30px var(--pglow);transform:translateY(-1px)}
.hero{text-align:center;padding:110px 24px 90px;max-width:920px;margin:0 auto}
.hero-badge{display:inline-flex;align-items:center;gap:8px;padding:6px 16px;border-radius:40px;border:1px solid rgba(0,196,212,.35);background:rgba(0,196,212,.08);font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--cyan);margin-bottom:28px}
.badge-dot{width:6px;height:6px;border-radius:50%;background:var(--cyan);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.hero h1{font-family:'Syne',sans-serif;font-size:clamp(36px,5.5vw,68px);font-weight:800;line-height:1.1;letter-spacing:-1.5px;color:#fff;margin-bottom:24px;word-break:break-word;overflow-wrap:break-word}
.hero h1 em{font-style:normal;color:var(--purple)}
.hero h1 .c{color:var(--cyan)}
.hero-sub{font-size:18px;color:var(--muted);max-width:580px;margin:0 auto 40px;line-height:1.7}
.hero-cta{display:flex;gap:14px;justify-content:center;flex-wrap:wrap}
.slabel{font-size:11px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:var(--cyan);margin-bottom:12px}
.stitle{font-family:'Syne',sans-serif;font-size:clamp(28px,3.5vw,44px);font-weight:800;letter-spacing:-1px;color:#fff;line-height:1.15;margin-bottom:16px}
.ssub{font-size:17px;color:var(--muted);max-width:560px;line-height:1.65}
.feat-sec{padding:100px 48px;max-width:1200px;margin:0 auto}
.feat-hd{margin-bottom:56px}
.feat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}
.fcard{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:32px;transition:border-color .3s,transform .3s,box-shadow .3s;position:relative;overflow:hidden}
.fcard::before{content:'';position:absolute;inset:0;background:radial-gradient(circle at 50% 0%,rgba(124,58,237,.07) 0%,transparent 70%);pointer-events:none}
.fcard:hover{border-color:rgba(124,58,237,.45);transform:translateY(-4px);box-shadow:0 12px 40px rgba(124,58,237,.12)}
.fcard-icon{font-size:30px;margin-bottom:20px}
.fcard h3{font-family:'Syne',sans-serif;font-size:20px;font-weight:700;color:#fff;margin-bottom:10px}
.fcard p{font-size:14px;color:var(--muted);line-height:1.7}
.hiw-sec{padding:100px 48px;background:linear-gradient(180deg,transparent 0%,rgba(124,58,237,.04) 50%,transparent 100%)}
.hiw-in{max-width:1100px;margin:0 auto}
.hiw-hd{text-align:center;margin-bottom:64px}
.hiw-hd .ssub{margin:0 auto}
.steps-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:32px}
.scard{display:flex;gap:20px;align-items:flex-start}
.snum{flex-shrink:0;width:44px;height:44px;border-radius:50%;border:1px solid var(--border);background:rgba(124,58,237,.12);display:flex;align-items:center;justify-content:center;font-family:'DM Mono',monospace;font-size:14px;font-weight:500;color:var(--purple)}
.sbody h4{font-family:'Syne',sans-serif;font-size:17px;font-weight:700;color:#fff;margin-bottom:6px}
.sbody p{font-size:13px;color:var(--muted);line-height:1.65}
.price-sec{padding:100px 48px;max-width:1200px;margin:0 auto}
.price-hd{text-align:center;margin-bottom:56px}
.price-hd .ssub{margin:0 auto}
.plans-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}
.pcard{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:36px;position:relative;overflow:hidden;transition:transform .3s,box-shadow .3s}
.pcard:hover{transform:translateY(-4px);box-shadow:0 16px 50px rgba(124,58,237,.1)}
.pcard.featured{border-color:var(--purple);background:linear-gradient(160deg,rgba(124,58,237,.08) 0%,var(--surface) 100%)}
.pcard.featured::after{content:'MOST POPULAR';position:absolute;top:20px;right:20px;font-size:9px;font-weight:700;letter-spacing:.12em;color:var(--purple);background:rgba(124,58,237,.15);padding:4px 10px;border-radius:20px}
.pname{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:14px}
.pprice{font-family:'Syne',sans-serif;font-size:52px;font-weight:800;color:#fff;line-height:1;display:flex;align-items:flex-start;gap:4px}
.pprice sup{font-size:22px;margin-top:10px;color:var(--muted)}
.pperiod{font-size:13px;color:var(--muted);margin-top:4px;margin-bottom:24px}
.pdiv{height:1px;background:var(--border);margin-bottom:22px}
.pfeats{list-style:none;margin-bottom:28px}
.pfeats li{font-size:14px;color:var(--muted);padding:6px 0;display:flex;align-items:center;gap:10px}
.pfeats li::before{content:'✓';color:var(--purple);font-weight:700;font-size:14px;flex-shrink:0}
.pcta{display:block;width:100%;text-align:center;padding:14px;border-radius:10px;font-weight:600;font-size:15px;transition:all .2s;font-family:'DM Sans',sans-serif}
.pcta-ghost{border:1px solid var(--border);color:var(--text)}
.pcta-ghost:hover{border-color:var(--purple);color:#fff}
.pcta-purple{background:var(--purple);color:#fff;box-shadow:0 0 24px var(--pglow)}
.pcta-purple:hover{background:#6D28D9;transform:translateY(-1px)}
.pcta-cyan{background:var(--cyan);color:#07070F;font-weight:700}
.pcta-cyan:hover{background:#00AABB;transform:translateY(-1px)}
.reveal{opacity:0;transform:translateY(28px);transition:opacity .7s ease,transform .7s ease}
.reveal.visible{opacity:1;transform:none}
footer{border-top:1px solid var(--border);padding:40px 48px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:20px}
.flogo{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:#fff}
.flogo span{color:var(--cyan)}
footer p{font-size:13px;color:var(--muted)}
.flinks{display:flex;gap:24px}
.flinks a{font-size:13px;color:var(--muted);transition:color .2s}
.flinks a:hover{color:#fff}
@media(max-width:768px){
  nav{padding:16px 20px}
  .nav-mid{display:none}
  .feat-sec,.price-sec,.hiw-sec{padding:60px 20px}
  .hero{padding:80px 20px 60px}
  footer{padding:30px 20px;flex-direction:column;text-align:center}
  .flinks{justify-content:center}
}
</style>
</head>
<body>
<canvas id="pc"></canvas>
<div class="wrap">

<nav>
  <div class="nav-logo">DC<span>SP</span></div>
  <div class="nav-mid">
    <a href="#features">Features</a>
    <a href="#how-it-works">How It Works</a>
    <a href="#pricing">Pricing</a>
  </div>
  <div class="nav-cta">
    <a href="/login" class="btn btn-ghost">Sign in</a>
    <a href="/register" class="btn btn-primary">Start free</a>
  </div>
</nav>

<section class="hero">
  <div class="hero-badge"><span class="badge-dot"></span>Powered by AWS Bedrock Nova Pro</div>
  <h1>AI-Powered CI <em>Self-Healing</em><br><span class="c">Platform</span></h1>
  <p class="hero-sub">DCSP fixes your broken builds automatically using LLMs. Zero human intervention for 80% of failures — patches generated, sandboxed, and applied in seconds.</p>
  <div class="hero-cta">
    <a href="/register" class="btn btn-primary" style="padding:14px 32px;font-size:16px">Start free trial</a>
    <a href="/login" class="btn btn-ghost" style="padding:14px 32px;font-size:16px">View dashboard &rarr;</a>
  </div>
</section>

<section id="features" class="feat-sec">
  <div class="feat-hd reveal">
    <div class="slabel">Capabilities</div>
    <h2 class="stitle">Everything your CI needs<br>to heal itself</h2>
    <p class="ssub">From webhook to merged patch — fully automated, fully auditable.</p>
  </div>
  <div class="feat-grid">
    <div class="fcard reveal"><div class="fcard-icon">🔗</div><h3>Any CI System</h3><p>Webhooks for GitHub Actions, GitLab CI, and Jenkins. HMAC-verified for security.</p></div>
    <div class="fcard reveal"><div class="fcard-icon">🧠</div><h3>LLM-Powered Repair</h3><p>AWS Bedrock Nova Pro generates context-aware patches. Falls back to pattern memory for known errors.</p></div>
    <div class="fcard reveal"><div class="fcard-icon">🏖</div><h3>Sandboxed Execution</h3><p>Every patch runs in a Docker sandbox before it reaches your repo. No untested code ever lands.</p></div>
    <div class="fcard reveal"><div class="fcard-icon">📊</div><h3>10-Tab Dashboard</h3><p>Analytics, compliance reports, incident tracking, security audit, and one-click patch approval.</p></div>
    <div class="fcard reveal"><div class="fcard-icon">🏢</div><h3>Multi-Tenant SaaS</h3><p>Full tenant isolation — each organisation sees only their own repair jobs and data.</p></div>
    <div class="fcard reveal"><div class="fcard-icon">📄</div><h3>Compliance-Ready</h3><p>Full audit log plus PDF/CSV compliance exports for SOC 2 and ISO 27001 readiness.</p></div>
  </div>
</section>

<section id="how-it-works" class="hiw-sec">
  <div class="hiw-in">
    <div class="hiw-hd reveal">
      <div class="slabel">Process</div>
      <h2 class="stitle">Fix in six steps,<br>not six hours</h2>
      <p class="ssub">From CI failure to merged patch in under 90 seconds on average.</p>
    </div>
    <div class="steps-grid">
      <div class="scard reveal"><div class="snum">01</div><div class="sbody"><h4>Webhook received</h4><p>CI failure triggers an HMAC-verified webhook to DCSP.</p></div></div>
      <div class="scard reveal"><div class="snum">02</div><div class="sbody"><h4>Log parsed</h4><p>AST analysis and log parser identify the root cause.</p></div></div>
      <div class="scard reveal"><div class="snum">03</div><div class="sbody"><h4>Patch generated</h4><p>Bedrock LLM generates a minimal, targeted patch.</p></div></div>
      <div class="scard reveal"><div class="snum">04</div><div class="sbody"><h4>Sandbox tested</h4><p>Patch runs in a Docker sandbox — zero risk to your repo.</p></div></div>
      <div class="scard reveal"><div class="snum">05</div><div class="sbody"><h4>Human approval</h4><p>One click to approve, or auto-approve above threshold.</p></div></div>
      <div class="scard reveal"><div class="snum">06</div><div class="sbody"><h4>PR created</h4><p>Approved patch opens a PR on GitHub or GitLab automatically.</p></div></div>
    </div>
  </div>
</section>

<section id="pricing" class="price-sec">
  <div class="price-hd reveal">
    <div class="slabel">Pricing</div>
    <h2 class="stitle">Simple pricing,<br>serious uptime</h2>
    <p class="ssub">Start free. Scale as your team grows. No hidden fees.</p>
  </div>
  <div class="plans-grid">
    <div class="pcard reveal">
      <div class="pname">Free</div>
      <div class="pprice"><sup>$</sup>0</div>
      <div class="pperiod">forever</div>
      <div class="pdiv"></div>
      <ul class="pfeats"><li>5 repairs / month</li><li>GitHub &amp; GitLab</li><li>Dashboard access</li><li>Audit log</li></ul>
      <a href="/register" class="pcta pcta-ghost">Get started free</a>
    </div>
    <div class="pcard featured reveal">
      <div class="pname" style="color:var(--purple)">Pro</div>
      <div class="pprice"><sup>$</sup>49</div>
      <div class="pperiod">per month</div>
      <div class="pdiv"></div>
      <ul class="pfeats"><li>100 repairs / month</li><li>All CI systems</li><li>Slack &amp; email alerts</li><li>Compliance exports</li><li>API key access</li></ul>
      <a href="/register" class="pcta pcta-purple">Start Pro trial</a>
    </div>
    <div class="pcard reveal">
      <div class="pname" style="color:var(--cyan)">Enterprise</div>
      <div class="pprice"><sup>$</sup>199</div>
      <div class="pperiod">per month</div>
      <div class="pdiv"></div>
      <ul class="pfeats"><li>Unlimited repairs</li><li>SAML / SSO</li><li>SLA &amp; support</li><li>Custom integrations</li><li>Dedicated instance</li></ul>
      <a href="/register" class="pcta pcta-cyan">Contact us</a>
    </div>
  </div>
</section>

<footer>
  <div class="flogo">DC<span>SP</span></div>
  <p>&copy; 2025 DCSP &middot; A VKatos Platform Product</p>
  <div class="flinks">
    <a href="/login">Sign in</a>
    <a href="/register">Create account</a>
    <a href="https://vkatos.com">vkatos.com</a>
  </div>
</footer>
</div>

<script>
(function(){
  var c=document.getElementById('pc'),ctx=c.getContext('2d');
  var W,H,pts=[];
  var N=80,DIST=120;
  function init(){
    W=c.width=innerWidth;H=c.height=innerHeight;pts=[];
    for(var i=0;i<N;i++) pts.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.38,vy:(Math.random()-.5)*.38});
  }
  init();window.addEventListener('resize',init);
  function draw(){
    ctx.clearRect(0,0,W,H);
    for(var i=0;i<N;i++){
      var p=pts[i];p.x+=p.vx;p.y+=p.vy;
      if(p.x<0||p.x>W)p.vx*=-1;if(p.y<0||p.y>H)p.vy*=-1;
      ctx.beginPath();ctx.arc(p.x,p.y,1.8,0,Math.PI*2);ctx.fillStyle='rgba(124,58,237,.65)';ctx.fill();
      for(var j=i+1;j<N;j++){
        var q=pts[j],dx=p.x-q.x,dy=p.y-q.y,d=Math.sqrt(dx*dx+dy*dy);
        if(d<DIST){ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.strokeStyle='rgba(124,58,237,'+(1-d/DIST)*.22+')';ctx.lineWidth=.8;ctx.stroke();}
      }
    }
    requestAnimationFrame(draw);
  }
  draw();
})();
var obs=new IntersectionObserver(function(entries){entries.forEach(function(e){if(e.isIntersecting){e.target.classList.add('visible');obs.unobserve(e.target);}});},{threshold:.12});
document.querySelectorAll('.reveal').forEach(function(el){obs.observe(el);});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    """Serve the login page."""
    error = request.query_params.get("error")
    error_msg = ""
    if error:
        error_msg = '<p style="color: var(--error-color); text-align: center;">Invalid username or password</p>'

    if error:
        try:
            session = SessionLocal()
            save_audit_log(
                session, "login_failed", "unknown",
                details="Invalid credentials",
                ip_address=request.client.host
            )
            session.close()
        except Exception as e:
            logger.warning("Could not write login_failed audit log: %s", e)

    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DCSP Login</title>
    <style>
        :root { --bg-color: #0d1117; --card-bg: #161b22; --text-color: #c9d1d9; --accent-color: #58a6ff; --success-color: #238636; --error-color: #da3633; --border-color: #30363d; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; background-color: var(--bg-color); color: var(--text-color); display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .login-card { background-color: var(--card-bg); border: 1px solid var(--border-color); border-radius: 6px; padding: 40px; width: 100%; max-width: 400px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
        h1 { text-align: center; margin-bottom: 30px; font-size: 24px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; font-size: 14px; color: #8b949e; }
        input { width: 100%; padding: 10px; background-color: var(--bg-color); border: 1px solid var(--border-color); border-radius: 6px; color: var(--text-color); box-sizing: border-box; }
        button { width: 100%; padding: 12px; background-color: var(--success-color); color: white; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; margin-top: 10px; }
        button:hover { background-color: #2ea043; }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>DCSP Login</h1>
        {error_msg}
        <form action="/auth/login" method="post">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autocomplete="username">
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required autocomplete="current-password">
            </div>
            <button type="submit">Sign In</button>
        </form>
        <div style="margin-top: 20px; text-align: center; font-size: 14px; color: #8b949e; display: flex; justify-content: center; gap: 20px;">
            <a href="/auth/forgot-password" style="color: #58a6ff; text-decoration: none;">Forgot password?</a>
            <a href="/register" style="color: #58a6ff; text-decoration: none;">Create account</a>
        </div>
    </div>
</body>
</html>
    """
    reset_msg = ""
    if request.query_params.get("reset"):
        reset_msg = '<p style="color: var(--success-color); text-align: center;">Password reset successful. Please log in.</p>'
    return HTMLResponse(content=html_template.replace("{error_msg}", error_msg + reset_msg))


@router.get("/logout")
async def logout():
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")
    return response


# ---------------------------------------------------------------------------
# Main dashboard home
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    nav_links = [
        ("Dashboard", "/dashboard"),
        ("Analytics", "/dashboard/analytics"),
        ("Incidents", "/dashboard/incidents"),
        ("Compliance", "/dashboard/compliance"),
        ("Audit Log", "/dashboard/audit"),
        ("Intelligence", "/dashboard/intelligence"),
        ("Admin", "/dashboard/admin"),
        ("API Keys", "/dashboard/api-keys"),
        ("GitHub", "/dashboard/github"),
        ("Security", "/dashboard/security"),
        ("Billing", "/dashboard/billing"),
        ("Settings", "/dashboard/settings"),
        ("Profile", "/dashboard/profile"),
    ]
    nav_html = "".join([
        f'<a href="{url}" class="{ "active" if name == "Dashboard" else "" }">{name}</a>'
        for name, url in nav_links
    ])

    return HTMLResponse(content=render_main_dashboard_html(username, nav_html))
