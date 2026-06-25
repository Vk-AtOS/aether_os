"""
JavaScript string constants for the DCSP main dashboard page.

Extracted from templates_dashboard.py to keep that file under 600 lines.
These are pure string constants — no Python logic.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Script 1: Core dashboard UI — job table, panel, approve/reject, metrics
# ---------------------------------------------------------------------------

DASHBOARD_MAIN_JS = """
    <script>
        let currentJobs = [];
        let currentJobId = null;

        function closePanel() {
            document.getElementById('detail-panel').classList.remove('open');
            document.getElementById('overlay').classList.remove('open');
            document.getElementById('panel-editor-view').style.display = 'none';
            document.getElementById('panel-diff-view').style.display = 'block';
        }

        document.getElementById('overlay').onclick = closePanel;

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closePanel();
        });

        function toggleEditor() {
            const diffView = document.getElementById('panel-diff-view');
            const editorView = document.getElementById('panel-editor-view');
            const editor = document.getElementById('patch-editor');

            if (editorView.style.display === 'none' || !editorView.style.display) {
                const job = currentJobs.find(j => j.id === currentJobId);
                if (job) { editor.value = job.patch_diff || ''; }
                diffView.style.display = 'none';
                editorView.style.display = 'block';
            } else {
                diffView.style.display = 'block';
                editorView.style.display = 'none';
            }
        }

        function showJobDetail(jobId) {
            currentJobId = jobId;
            const job = currentJobs.find(j => j.id === jobId);
            if (!job) return;

            document.getElementById('panel-repo').innerText = job.repo_name;

            const meta = document.getElementById('panel-meta');
            meta.innerHTML = `
                <div style="font-size: 12px; color: #8b949e; margin-bottom: 8px;">Branch: ${job.branch} | ${new Date(job.timestamp).toLocaleString()}</div>
                <span class="badge badge-info">${job.ci_system || 'unknown'}</span>
                <span class="badge badge-info">${job.detected_language || 'unknown'}</span>
                ${job.slm_generated ? '<span class="badge badge-slm">SLM-Generated</span>' : ''}
                ${job.source === 'memory' ? '<span class="badge badge-memory">&#9851; From Memory</span>' : ''}
            `;

            let statusClass = 'status-failed';
            let statusText = 'failed';
            if (job.success) { statusClass = 'status-success'; statusText = 'success'; }
            else if (job.escalated) { statusClass = 'status-escalated'; statusText = 'escalated'; }

            let approvalText = 'Pending';
            let approvalClass = '';
            if (job.approved === true) { approvalText = 'Approved'; approvalClass = 'status-text-approved'; }
            else if (job.approved === false) { approvalText = 'Rejected'; approvalClass = 'status-text-rejected'; }

            document.getElementById('panel-status-row').innerHTML = `
                <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
                    <span class="status-badge ${statusClass}">${statusText}</span>
                    <span style="font-size: 13px; color: #8b949e;">Confidence: <strong style="color: var(--text-color)">${job.confidence.toFixed(2)}</strong></span>
                    <span style="font-size: 13px; color: #8b949e;">Manual Approval: <strong class="${approvalClass}">${approvalText}</strong></span>
                    ${job.approved_pr_url ? `
                        <a href="${job.approved_pr_url}" target="_blank" class="action-btn"
                           style="background-color: var(--accent-color); color: white; border: none; text-decoration: none; padding: 4px 12px;">
                           View PR
                        </a>
                    ` : ''}
                </div>
            `;

            document.getElementById('panel-explanation').innerText = job.explanation;

            const errorMatch = job.explanation.match(/(\\w+Error|Exception)/);
            const errorType = errorMatch ? errorMatch[0] : 'Parsed from log';

            document.getElementById('panel-root-cause').innerHTML = `
                <div style="margin-bottom: 5px;"><strong>Language:</strong> ${job.detected_language || 'Unknown'}</div>
                <div style="margin-bottom: 5px;"><strong>Error Type:</strong> ${errorType}</div>
                ${job.fingerprint ? `<div style="font-family: monospace; color: #8b949e; font-size: 11px; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 5px;">FP: ${job.fingerprint}</div>` : ''}
            `;

            const diffEl = document.getElementById('panel-diff');
            const editBtn = document.getElementById('btn-edit-patch');

            if (job.patch_diff) {
                const lines = job.patch_diff.split('\\n');
                const highlighted = lines.map(line => {
                    if (line.startsWith('+') && !line.startsWith('+++')) return `<div class="diff-add">${line}</div>`;
                    if (line.startsWith('-') && !line.startsWith('---')) return `<div class="diff-remove">${line}</div>`;
                    return `<div class="diff-context">${line}</div>`;
                }).join('');
                diffEl.innerHTML = `<div class="diff-container">${highlighted}</div>`;
                if (job.success && job.approved === null) {
                    editBtn.style.display = 'inline-block';
                } else {
                    editBtn.style.display = 'none';
                }
            } else {
                diffEl.innerHTML = '<div style="color: #8b949e; font-style: italic; font-size: 13px;">No patch generated (escalated to developer)</div>';
                editBtn.style.display = 'none';
            }

            const violationsSec = document.getElementById('panel-violations-section');
            const violationsEl = document.getElementById('panel-violations');
            if (job.violations && job.violations.length > 0) {
                violationsSec.style.display = 'block';
                violationsEl.innerHTML = job.violations.map(v => `<div class="violation-item">${v}</div>`).join('');
            } else {
                violationsSec.style.display = 'none';
            }

            const actionsEl = document.getElementById('panel-actions');
            if (job.success && job.approved === null) {
                actionsEl.style.display = 'flex';
                actionsEl.innerHTML = `
                    <button class="action-btn btn-approve" style="flex: 1; padding: 12px; font-weight: bold;" onclick="approveJob('${job.id}'); closePanel();">Approve Patch</button>
                    <div style="width: 10px;"></div>
                    <button class="action-btn btn-reject" style="flex: 1; padding: 12px; font-weight: bold;" onclick="rejectJob('${job.id}'); closePanel();">Reject Patch</button>
                `;
            } else {
                actionsEl.style.display = 'none';
            }

            document.getElementById('detail-panel').classList.add('open');
            document.getElementById('overlay').classList.add('open');
        }

        async function fetchSystemStatus() {
            try {
                const response = await fetch('/health');
                const data = await response.json();
                const ollamaDot = document.getElementById('ollama-dot');
                const ollamaStatus = document.getElementById('ollama-status');
                if (data.bedrock === 'connected') {
                    ollamaDot.className = 'status-dot-small dot-green';
                    ollamaStatus.innerText = 'Online';
                } else {
                    ollamaDot.className = 'status-dot-small dot-red';
                    ollamaStatus.innerText = 'Offline';
                }
                const dbDot = document.getElementById('db-dot');
                const dbStatus = document.getElementById('db-status');
                if (data.database === 'connected') {
                    dbDot.className = 'status-dot-small dot-green';
                    dbStatus.innerText = 'Connected';
                } else {
                    dbDot.className = 'status-dot-small dot-red';
                    dbStatus.innerText = 'Disconnected';
                }
                const slackStatus = document.getElementById('slack-status');
                if (data.notifications && data.notifications.slack_configured) {
                    slackStatus.innerHTML = 'Slack: <span style="color: var(--success-color)">&#10003;</span>';
                } else {
                    slackStatus.innerHTML = 'Slack: <span style="color: #8b949e">&mdash;</span>';
                }
                const emailStatus = document.getElementById('email-status');
                if (data.notifications && data.notifications.email_configured) {
                    emailStatus.innerHTML = 'Email: <span style="color: var(--success-color)">&#10003;</span>';
                } else {
                    emailStatus.innerHTML = 'Email: <span style="color: #8b949e">&mdash;</span>';
                }
            } catch (error) {
                console.error('Error fetching health:', error);
            }
        }

        async function approveJob(jobId) {
            await fetch(`/dashboard/approve/${jobId}`, { method: 'POST' });
            fetchMetrics();
        }

        async function approveWithEdits() {
            if (!currentJobId) return;
            const editedPatch = document.getElementById('patch-editor').value;
            await fetch(`/dashboard/approve/${currentJobId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ edited_patch: editedPatch })
            });
            closePanel();
            fetchMetrics();
        }

        async function rejectJob(jobId) {
            await fetch(`/dashboard/reject/${jobId}`, { method: 'POST' });
            fetchMetrics();
        }

        async function fetchMetrics() {
            try {
                const response = await fetch('/api/metrics');
                const data = await response.json();
                currentJobs = data.recent_jobs;
                document.getElementById('total-jobs-count').innerText = data.total_jobs;
                document.getElementById('success-rate').innerText = (data.success_rate * 100).toFixed(1) + '%';
                document.getElementById('avg-confidence').innerText = data.avg_confidence.toFixed(2);
                document.getElementById('escalation-rate').innerText = (data.escalation_rate * 100).toFixed(1) + '%';
                const feed = document.getElementById('jobs-tbody');
                if (!feed) return;
                feed.innerHTML = '';
                data.recent_jobs.forEach(job => { feed.appendChild(buildJobRow(job)); });
            } catch (error) {
                console.error('Error fetching metrics:', error);
            }
        }

        function buildJobRow(job) {
            const tr = document.createElement('tr');
            tr.setAttribute('data-job-id', job.id);
            const statusClass = job.success ? 'status-success' : (job.escalated ? 'status-escalated' : 'status-failed');
            const statusText = job.success ? 'success' : (job.escalated ? 'escalated' : 'failed');
            const time = new Date(job.timestamp).toLocaleTimeString();
            let actionHtml = '';
            if (job.approved === true) {
                actionHtml = '<span class="status-text-approved">Approved</span>';
            } else if (job.approved === false) {
                actionHtml = '<span class="status-text-rejected">Rejected</span>';
            } else if (job.success) {
                actionHtml = `
                    <button class="action-btn btn-approve" onclick="event.stopPropagation(); approveJob('${job.id}')">Approve</button>
                    <button class="action-btn btn-reject" onclick="event.stopPropagation(); rejectJob('${job.id}')">Reject</button>
                `;
            } else {
                actionHtml = '<span style="color: #8b949e; font-style: italic;">N/A</span>';
            }
            tr.className = 'job-row';
            tr.onclick = (e) => { if (e.target.tagName !== 'BUTTON') showJobDetail(job.id); };
            const sandboxText = job.sandbox_result || 'N/A';
            const sandboxColor = job.sandbox_result === 'passed' ? '#238636' : (job.sandbox_result === 'failed' ? '#da3633' : '#8b949e');
            tr.innerHTML = `
                <td>${time}</td>
                <td>${job.repo_name}</td>
                <td>${job.confidence.toFixed(2)}</td>
                <td><span style="color:${sandboxColor}">${sandboxText}</span></td>
                <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${job.explanation}">${job.explanation}</td>
                <td>
                    ${actionHtml}
                    <a href="/dashboard/job/${job.id}" class="action-btn" style="text-decoration:none">Details</a>
                </td>
            `;
            return tr;
        }

        function updateAll() {
            fetchSystemStatus();
            fetchMetrics();
        }

        updateAll();
        setInterval(updateAll, 10000);
    </script>"""

# ---------------------------------------------------------------------------
# Script 2: WebSocket client with reconnect + real-time updates
# ---------------------------------------------------------------------------

DASHBOARD_WS_JS = """
    <script>
    // WebSocket client — reads 'ws_token' (non-HttpOnly) for WS auth.
    // session_token is HttpOnly by design (XSS protection), so ws_token
    // carries the same value but is JS-readable.
    (function() {
      const token = getCookie('ws_token');
      if (!token) return;

      let ws = null;
      let reconnectDelay = 1000;
      let reconnectTimer = null;
      const MAX_DELAY = 30000;

      function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? match[2] : null;
      }

      function updateConnectionStatus(connected) {
        const el = document.getElementById('ws-status');
        if (!el) return;
        el.textContent = connected ? '&#9679; Live' : '&#9675; Polling';
        el.style.color = connected ? '#238636' : '#d29922';
      }

      function handleMessage(event) {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'init') {
            refreshJobTable();
          } else if (msg.type === 'new_job') {
            prependJobRow(msg.job);
            updateMetricsCounts();
          } else if (msg.type === 'job_approved' || msg.type === 'job_rejected') {
            updateJobRow(msg.job);
          }
        } catch(e) {
          console.warn('WS message parse error:', e);
        }
      }

      function connect() {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const url = proto + '://' + location.host + '/ws/dashboard?token=' + token;
        ws = new WebSocket(url);
        ws.onopen = function() {
          reconnectDelay = 1000;
          updateConnectionStatus(true);
          setInterval(function() {
            if (ws.readyState === WebSocket.OPEN) { ws.send('ping'); }
          }, 30000);
        };
        ws.onmessage = handleMessage;
        ws.onclose = function() {
          updateConnectionStatus(false);
          reconnectTimer = setTimeout(function() {
            reconnectDelay = Math.min(reconnectDelay * 2, MAX_DELAY);
            connect();
          }, reconnectDelay);
        };
        ws.onerror = function() { ws.close(); };
      }

      function prependJobRow(job) {
        const tbody = document.getElementById('jobs-tbody');
        if (!tbody) return;
        const row = buildJobRow(job);
        tbody.insertBefore(row, tbody.firstChild);
        row.style.backgroundColor = '#1f4e2e';
        setTimeout(function() {
          row.style.backgroundColor = '';
          row.style.transition = 'background-color 1s';
        }, 2000);
      }

      function updateJobRow(job) {
        const row = document.querySelector('[data-job-id="' + job.id + '"]');
        if (!row) return;
        row.replaceWith(buildJobRow(job));
      }

      function refreshJobTable() {
        fetch('/api/metrics', { credentials: 'include' })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            const tbody = document.getElementById('jobs-tbody');
            if (!tbody) return;
            tbody.innerHTML = '';
            (data.recent_jobs || []).forEach(function(job) { tbody.appendChild(buildJobRow(job)); });
          }).catch(function() {});
      }

      function updateMetricsCounts() {
        fetch('/api/metrics', { credentials: 'include' })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            const el = document.getElementById('total-jobs-count');
            if (el) el.textContent = data.total_jobs;
          }).catch(function() {});
      }

      connect();
    })();
    </script>"""

# ---------------------------------------------------------------------------
# Script 3: Polling fallback when WebSocket is unavailable
# ---------------------------------------------------------------------------

DASHBOARD_POLL_JS = """
    <script>
    // Polling fallback — activates when WS shows 'Polling' status
    setInterval(function() {
      const statusEl = document.getElementById('ws-status');
      if (statusEl && statusEl.textContent.includes('Polling')) {
        fetch('/api/metrics', { credentials: 'include' })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            const tbody = document.getElementById('jobs-tbody');
            if (!tbody) return;
            if (tbody.rows.length !== data.total_jobs) { tbody.innerHTML = ''; }
          }).catch(function() {});
      }
    }, 30000);
    </script>"""
