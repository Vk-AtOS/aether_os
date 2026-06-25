"""
Standalone Dashboard UI server for DCSP.
Running on port 9000.
"""

import uvicorn
import math
import random
import time
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from src.database import SessionLocal
from src.intelligence.predictor import PIPELINE_PREDICTOR
from src.db.job_repo import get_all_stage_timings
from src.db.tenant_repo import list_tenants
from src.db.audit_repo import get_audit_logs, save_audit_log

app = FastAPI(title="DCSP Live Dashboard")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Embedded Dashboard HTML/CSS/JS
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DCSP Live Operations</title>
    <style>
        :root {
            --bg-color: #04080F;
            --card-bg: #0B1221;
            --accent-color: #00C2D4;
            --text-color: #E6EDF3;
            --success-color: #238636;
            --warning-color: #D29922;
            --critical-color: #DA3633;
            --border-color: #30363D;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: 'Courier New', Courier, monospace;
            margin: 0;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--accent-color);
            padding-bottom: 15px;
            margin-bottom: 30px;
        }
        h1 { margin: 0; color: var(--accent-color); text-transform: uppercase; letter-spacing: 2px; }
        
        .tenant-selector select {
            background: var(--card-bg);
            color: var(--accent-color);
            border: 1px solid var(--accent-color);
            padding: 8px;
            font-family: inherit;
            font-weight: bold;
        }

        .grid-container {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }

        .stage-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 20px;
            position: relative;
            transition: all 0.3s ease;
        }
        .stage-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0, 194, 212, 0.1); }
        
        .stage-header { display: flex; justify-content: space-between; margin-bottom: 15px; }
        .stage-name { font-weight: bold; font-size: 1.2em; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        
        .risk-normal { color: var(--success-color); border-color: var(--success-color); }
        .risk-warning { color: var(--warning-color); border-color: var(--warning-color); }
        .risk-critical { color: var(--critical-color); border-color: var(--critical-color); animation: pulse 2s infinite; }
        
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }

        .metric-row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 0.9em; }
        .metric-label { color: #8B949E; }
        
        .stall-btn {
            background: transparent;
            border: 1px solid var(--critical-color);
            color: var(--critical-color);
            width: 100%;
            padding: 8px;
            margin-top: 15px;
            cursor: pointer;
            font-family: inherit;
            transition: 0.2s;
        }
        .stall-btn:hover { background: var(--critical-color); color: white; }

        .prediction-panel {
            background: rgba(0, 194, 212, 0.05);
            border-left: 3px solid var(--accent-color);
            padding: 10px;
            margin-top: 10px;
            font-size: 0.85em;
        }

        .audit-log {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 20px;
            height: 300px;
            overflow-y: auto;
        }
        .log-entry {
            border-bottom: 1px solid rgba(48, 54, 61, 0.5);
            padding: 8px 0;
            font-size: 0.9em;
            display: flex;
        }
        .log-time { color: #8B949E; width: 160px; flex-shrink: 0; }
        .log-msg { color: var(--text-color); }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: var(--bg-color); }
        ::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--accent-color); }
    </style>
</head>
<body>
    <div class="header">
        <h1>DCSP Operations</h1>
        <div class="tenant-selector">
            <select id="tenantSelect" onchange="refreshData()">
                <option value="all">ALL TENANTS</option>
            </select>
        </div>
    </div>

    <div id="stagesGrid" class="grid-container">
        <!-- Stages injected here -->
    </div>

    <h2 style="color: var(--text-color); margin-top: 40px;">System Audit Log</h2>
    <div id="auditLog" class="audit-log">
        <!-- Logs injected here -->
    </div>

    <script>
        const API_BASE = "http://localhost:9000";
        let lastAuditId = null;

        async function init() {
            await loadTenants();
            refreshData();
            setInterval(refreshData, 10000);
        }

        async function loadTenants() {
            try {
                const res = await fetch(`${API_BASE}/api/tenants`);
                const tenants = await res.json();
                const select = document.getElementById('tenantSelect');
                tenants.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.id;
                    opt.innerText = t.name.toUpperCase();
                    select.appendChild(opt);
                });
            } catch(e) { console.error("Failed to load tenants", e); }
        }

        async function refreshData() {
            const tenantId = document.getElementById('tenantSelect').value;
            await Promise.all([
                loadStages(tenantId),
                loadAuditLog()
            ]);
        }

        async function loadStages(tenantId) {
            try {
                const url = tenantId === 'all' ? `${API_BASE}/api/stages` : `${API_BASE}/api/stages?tenant_id=${tenantId}`;
                const res = await fetch(url);
                const stages = await res.json();
                renderStages(stages);
            } catch(e) { console.error("Failed to load stages", e); }
        }

        function renderStages(stages) {
            const grid = document.getElementById('stagesGrid');
            grid.innerHTML = '';
            
            stages.forEach(stage => {
                const riskClass = getRiskClass(stage.risk_level);
                const statusColor = stage.status === 'active' ? '#238636' : '#8B949E';
                
                const card = document.createElement('div');
                card.className = `stage-card ${riskClass}`;
                card.style.borderColor = riskClass === 'risk-critical' ? 'var(--critical-color)' : 
                                       (riskClass === 'risk-warning' ? 'var(--warning-color)' : 'var(--border-color)');
                
                card.innerHTML = `
                    <div class="stage-header">
                        <span class="stage-name">${stage.name}</span>
                        <div class="status-dot" style="background-color: ${statusColor}"></div>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Avg Duration:</span>
                        <span>${stage.avg_duration}s</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Curr. Idle:</span>
                        <span>${stage.current_idle}s</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Z-Score:</span>
                        <span style="color:${getRiskColor(stage.risk_level)}">${stage.z_score.toFixed(2)}</span>
                    </div>
                    
                    <div class="prediction-panel">
                        <strong>PREDICTION:</strong><br>
                        ${stage.prediction_text}
                    </div>

                    <button class="stall-btn" onclick="simulateStall('${stage.name}')">
                        SIMULATE STALL
                    </button>
                `;
                grid.appendChild(card);
            });
        }

        async function loadAuditLog() {
            try {
                const res = await fetch(`${API_BASE}/api/audit`);
                const logs = await res.json();
                const container = document.getElementById('auditLog');
                container.innerHTML = ''; // Simple refresh
                
                logs.forEach(log => {
                    const div = document.createElement('div');
                    div.className = 'log-entry';
                    div.innerHTML = `
                        <div class="log-time">${new Date(log.timestamp).toLocaleTimeString()}</div>
                        <div class="log-msg">
                            <span style="color:var(--accent-color)">[${log.actor}]</span> 
                            ${log.action}: ${log.details || ''}
                        </div>
                    `;
                    container.appendChild(div);
                });
            } catch(e) { console.error("Failed to load audit logs", e); }
        }

        async function simulateStall(stageName) {
            const tenantId = document.getElementById('tenantSelect').value;
            const tid = tenantId === 'all' ? null : tenantId;
            
            try {
                await fetch(`${API_BASE}/api/simulate`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ stage_name: stageName, tenant_id: tid })
                });
                // Immediate refresh
                setTimeout(refreshData, 500);
            } catch(e) { alert("Simulation failed"); }
        }

        function getRiskClass(level) {
            if (level === 'CRITICAL') return 'risk-critical';
            if (level === 'HIGH' || level === 'MEDIUM') return 'risk-warning';
            return 'risk-normal';
        }

        function getRiskColor(level) {
            if (level === 'CRITICAL') return 'var(--critical-color)';
            if (level === 'HIGH' || level === 'MEDIUM') return 'var(--warning-color)';
            return 'var(--success-color)';
        }

        init();
    </script>
</body>
</html>
"""

@app.get("/")
async def get_dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)

@app.get("/api/tenants")
async def api_tenants():
    session = SessionLocal()
    try:
        tenants = list_tenants(session)
        return [{"id": t.id, "name": t.name} for t in tenants]
    finally:
        session.close()

@app.get("/api/stages")
async def api_stages(tenant_id: Optional[str] = None):
    # In a real system, we'd query active jobs. 
    # For this dashboard, we simulate active stages based on baselines + random jitter
    session = SessionLocal()
    try:
        baselines = get_all_stage_timings(session)
        # Group by stage name
        stage_map = {}
        for t in baselines:
            if t.stage_name not in stage_map:
                stage_map[t.stage_name] = []
            stage_map[t.stage_name].append(t.duration_seconds)
            
        results = []
        for name, durations in stage_map.items():
            avg = sum(durations) / len(durations)
            std_dev = (sum((x - avg) ** 2 for x in durations) / len(durations)) ** 0.5
            if std_dev == 0: std_dev = 1
            
            # Simulate current state
            # If tenant_id is provided, filter or adjust
            
            # Random "current" duration for demo purposes
            # Occasional spike to trigger risk
            current_idle = int(avg + (random.random() * std_dev * 1.5))
            if random.random() > 0.8: # 20% chance of spike
                current_idle += int(std_dev * 2)
            
            z_score = (current_idle - avg) / std_dev
            
            risk = "LOW"
            if z_score > 2.5: risk = "CRITICAL"
            elif z_score > 1.5: risk = "HIGH"
            elif z_score > 1.0: risk = "MEDIUM"
            
            # Prediction text
            prob = min(99, int(50 + (z_score * 20)))
            if prob < 50: prob = 5 # baseline
            
            pred_text = f"{prob}% probability of stall"
            if risk == "CRITICAL":
                pred_text += " - IMMEDIATE ACTION REQ"
            elif risk == "LOW":
                pred_text = "Operating normally"

            results.append({
                "name": name,
                "status": "active",
                "avg_duration": int(avg),
                "current_idle": current_idle,
                "z_score": z_score,
                "risk_level": risk,
                "prediction_text": pred_text
            })
            
        return results
    finally:
        session.close()

@app.get("/api/audit")
async def api_audit():
    session = SessionLocal()
    try:
        logs = get_audit_logs(session, limit=20)
        return [{
            "timestamp": l.timestamp.isoformat(),
            "actor": l.actor,
            "action": l.action,
            "details": l.details
        } for l in logs]
    finally:
        session.close()

@app.post("/api/simulate")
async def api_simulate(req: dict):
    stage = req.get("stage_name")
    tid = req.get("tenant_id")
    
    # Record a high duration to skew future predictions
    session = SessionLocal()
    try:
        # Save audit log
        save_audit_log(session, "simulate_stall", "dashboard_user", details=f"Simulated stall on {stage}")
        
        # We also record a "bad" timing to actually impact the predictor
        # This makes the "Simulation" real in the system
        PIPELINE_PREDICTOR.record_stage_timing("sim-job", stage, 9999, "failure", tenant_id=tid)
        
        return {"status": "simulated"}
    finally:
        session.close()

if __name__ == "__main__":
    print("Starting DCSP Dashboard on http://localhost:9000")
    uvicorn.run(app, host="0.0.0.0", port=9000)
