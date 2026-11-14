"""
Cloud Console Page Generators — AetherOS Layer 7.

Contains JSX generator functions for each route-level page of the console:
  Dashboard, ServiceCatalog, ResourceExplorer, CostDashboard, Settings.

App-shell generators (package.json, index.html, main.jsx, App.jsx, vite.config)
live in cloud_console_app.py.
"""
from __future__ import annotations

from typing import Dict, List


def generate_dashboard_jsx(services: List[Dict]) -> str:
    services_json = str([s["name"] for s in services]).replace("'", '"')
    return f"""\
import React from 'react';
import {{ useQuery }} from '@tanstack/react-query';
import {{ BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer }} from 'recharts';

const API = import.meta.env.VITE_API_URL || '';

async function fetchStats() {{
  const r = await fetch(`${{API}}/api/platform/stats`, {{
    headers: {{ Authorization: `Bearer ${{localStorage.getItem('access_token') || ''}}` }},
  }});
  if (!r.ok) throw new Error('stats fetch failed');
  return r.json();
}}

async function fetchEvents() {{
  const r = await fetch(`${{API}}/api/platform/events`, {{
    headers: {{ Authorization: `Bearer ${{localStorage.getItem('access_token') || ''}}` }},
  }});
  if (!r.ok) throw new Error('events fetch failed');
  return r.json();
}}

const cardStyle = {{
  background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 10,
  padding: '20px 24px', minWidth: 160,
}};

function StatCard({{ label, value, icon, color }}) {{
  return (
    <div style={{{{...cardStyle, flex: 1}}}}>
      <div style={{{{ fontSize: 24, marginBottom: 8 }}}}>{{icon}}</div>
      <div style={{{{ fontSize: 28, fontWeight: 700, color: color || '#63b3ed' }}}}>{{value ?? '—'}}</div>
      <div style={{{{ fontSize: 13, color: '#718096', marginTop: 4 }}}}>{{label}}</div>
    </div>
  );
}}

export default function Dashboard() {{
  const {{ data: stats }} = useQuery({{ queryKey: ['platform-stats'], queryFn: fetchStats }});
  const {{ data: events }} = useQuery({{ queryKey: ['platform-events'], queryFn: fetchEvents }});

  const chartData = {services_json}.map((name) => ({{
    name, resources: (stats?.resource_counts?.[name] ?? 0),   // no invented counts: unknown is 0
  }}));

  return (
    <div>
      <h1 style={{{{ fontSize: 22, fontWeight: 700, marginBottom: 24 }}}}>Platform Overview</h1>
      <div style={{{{ display: 'flex', gap: 16, marginBottom: 32, flexWrap: 'wrap' }}}}>
        <StatCard label="Total Resources" value={{stats?.total_resources}} icon="🖥️" />
        <StatCard label="Monthly Spend" value={{stats?.monthly_spend != null ? `$${{stats.monthly_spend.toFixed(2)}}` : '—'}} icon="💰" color="#68d391" />
        <StatCard label="Active Services" value={{stats?.active_services}} icon="⚡" color="#f6ad55" />
        <StatCard label="Health Score" value={{stats?.health_score != null ? `${{stats.health_score}}%` : '—'}} icon="❤️" color="#fc8181" />
      </div>
      <div style={{{{...cardStyle, marginBottom: 32}}}}>
        <h2 style={{{{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}}}>Resources by Service</h2>
        <ResponsiveContainer width="100%" height={{220}}>
          <BarChart data={{chartData}}>
            <XAxis dataKey="name" tick={{{{ fill: '#718096', fontSize: 12 }}}} />
            <YAxis tick={{{{ fill: '#718096', fontSize: 12 }}}} />
            <Tooltip contentStyle={{{{ background: '#2d3748', border: 'none', color: '#e2e8f0' }}}} />
            <Bar dataKey="resources" fill="#63b3ed" radius={{[4, 4, 0, 0]}} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div style={{cardStyle}}>
        <h2 style={{{{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}}}>Recent Activity</h2>
        {{(events?.events || []).slice(0, 10).map((ev, i) => (
          <div key={{i}} style={{{{ display: 'flex', gap: 12, padding: '10px 0', borderBottom: '1px solid #2d3748' }}}}>
            <span style={{{{ color: '#718096', fontSize: 12, minWidth: 140 }}}}>{{new Date(ev.created_at).toLocaleString()}}</span>
            <span style={{{{ fontSize: 13 }}}}>{{ev.event_type}}: {{ev.resource_id}}</span>
          </div>
        ))}}
        {{(!events?.events?.length) && <p style={{{{ color: '#718096', fontSize: 13 }}}}>No recent activity.</p>}}
      </div>
    </div>
  );
}}
"""


def generate_service_catalog_jsx(services: List[Dict]) -> str:
    services_json = (
        "[\n"
        + ",\n".join(
            f'  {{name: "{s["name"]}", description: "{s.get("description","")}", icon: "{s.get("icon","📦")}", status: "GA"}}'
            for s in services
        )
        + "\n]"
    )
    return f"""\
import React, {{ useState }} from 'react';

const API = import.meta.env.VITE_API_URL || '';
const SERVICES = {services_json};
const STATUS_COLOR = {{ GA: '#68d391', Beta: '#f6ad55', Preview: '#fc8181' }};

function LaunchModal({{ service, onClose }}) {{
  const [form, setForm] = useState({{ name: '', size: 'small', region: 'us-east-1' }});
  const [status, setStatus] = useState('idle');
  const [resourceId, setResourceId] = useState(null);

  async function launch() {{
    setStatus('loading');
    try {{
      const r = await fetch(`${{API}}/api/services/${{service.name}}/launch`, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json', Authorization: `Bearer ${{localStorage.getItem('access_token') || ''}}` }},
        body: JSON.stringify(form),
      }});
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setResourceId(data.id);
      setStatus('provisioning');
      pollStatus(data.id);
    }} catch (e) {{
      console.error('launch failed', e);
      setStatus('error');
    }}
  }}

  async function pollStatus(id) {{
    let attempts = 0;
    const iv = setInterval(async () => {{
      attempts++;
      try {{
        const r = await fetch(`${{API}}/api/resources/${{id}}/status`, {{
          headers: {{ Authorization: `Bearer ${{localStorage.getItem('access_token') || ''}}` }},
        }});
        if (r.ok) {{
          const d = await r.json();
          if (d.status === 'running') {{ clearInterval(iv); setStatus('done'); }}
          else if (d.status === 'error') {{ clearInterval(iv); setStatus('error'); }}
        }}
      }} catch (err) {{
        console.error('poll status error', err);
      }}
      if (attempts > 30) clearInterval(iv);
    }}, 3000);
  }}

  return (
    <div style={{{{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 999 }}}}>
      <div style={{{{ background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 12, padding: 28, minWidth: 380, maxWidth: 480 }}}}>
        <h2 style={{{{ fontSize: 18, fontWeight: 700, marginBottom: 20 }}}}>Launch {{service.icon}} {{service.name}}</h2>
        {{status === 'idle' || status === 'error' ? (
          <>
            {{['name', 'size', 'region'].map(field => (
              <div key={{field}} style={{{{ marginBottom: 14 }}}}>
                <label style={{{{ display: 'block', fontSize: 13, color: '#a0aec0', marginBottom: 6 }}}}>{{field.charAt(0).toUpperCase() + field.slice(1)}}</label>
                <input value={{form[field]}} onChange={{e => setForm(p => ({{...p, [field]: e.target.value}}))}}
                  style={{{{ width: '100%', background: '#2d3748', border: '1px solid #4a5568', borderRadius: 6, padding: '8px 12px', color: '#e2e8f0', fontSize: 14 }}}} />
              </div>
            ))}}
            {{status === 'error' && <p style={{{{ color: '#fc8181', fontSize: 13, marginBottom: 12 }}}}>Launch failed. Please try again.</p>}}
            <div style={{{{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}}}>
              <button onClick={{onClose}} style={{{{ padding: '8px 18px', borderRadius: 6, background: '#2d3748', color: '#a0aec0', border: 'none', cursor: 'pointer' }}}}>Cancel</button>
              <button onClick={{launch}} style={{{{ padding: '8px 18px', borderRadius: 6, background: '#3182ce', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600 }}}}>Launch</button>
            </div>
          </>
        ) : status === 'loading' ? (
          <p style={{{{ color: '#a0aec0', textAlign: 'center', padding: 24 }}}}>⏳ Launching...</p>
        ) : status === 'provisioning' ? (
          <div style={{{{ textAlign: 'center', padding: 24 }}}}>
            <div style={{{{ fontSize: 32, marginBottom: 12 }}}}>⚙️</div>
            <p style={{{{ color: '#f6ad55' }}}}>Provisioning resource {{resourceId}}...</p>
            <p style={{{{ color: '#718096', fontSize: 12, marginTop: 8 }}}}>Polling for status every 3s</p>
          </div>
        ) : (
          <div style={{{{ textAlign: 'center', padding: 24 }}}}>
            <div style={{{{ fontSize: 40, marginBottom: 12 }}}}>✅</div>
            <p style={{{{ color: '#68d391', fontWeight: 600 }}}}>Resource is running!</p>
            <button onClick={{onClose}} style={{{{ marginTop: 16, padding: '8px 20px', borderRadius: 6, background: '#2d3748', color: '#e2e8f0', border: 'none', cursor: 'pointer' }}}}>Close</button>
          </div>
        )}}
      </div>
    </div>
  );
}}

export default function ServiceCatalog() {{
  const [modal, setModal] = useState(null);
  return (
    <div>
      <h1 style={{{{ fontSize: 22, fontWeight: 700, marginBottom: 24 }}}}>Service Catalog</h1>
      {{modal && <LaunchModal service={{modal}} onClose={{() => setModal(null)}} />}}
      <div style={{{{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}}}>
        {{SERVICES.map(svc => (
          <div key={{svc.name}} style={{{{ background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 10, padding: 20, display: 'flex', flexDirection: 'column', gap: 12 }}}}>
            <div style={{{{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}}}>
              <span style={{{{ fontSize: 32 }}}}>{{svc.icon}}</span>
              <span style={{{{ fontSize: 11, padding: '3px 10px', borderRadius: 12, background: (STATUS_COLOR[svc.status] || '#68d391') + '22', color: STATUS_COLOR[svc.status] || '#68d391', fontWeight: 600 }}}}>{{svc.status}}</span>
            </div>
            <div>
              <div style={{{{ fontSize: 16, fontWeight: 600 }}}}>{{svc.name}}</div>
              <div style={{{{ fontSize: 13, color: '#718096', marginTop: 4 }}}}>{{svc.description}}</div>
            </div>
            <button onClick={{() => setModal(svc)}} style={{{{ marginTop: 4, padding: '9px 0', borderRadius: 7, background: '#3182ce', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: 14 }}}}>Launch</button>
          </div>
        ))}}
      </div>
    </div>
  );
}}
"""


def generate_resource_explorer_jsx(entities: List[Dict]) -> str:
    types_json = (
        "[\n"
        + ",\n".join(f'  "{e.get("table", e.get("name", "resource"))}"' for e in entities)
        + "\n]"
    )
    return f"""\
import React, {{ useState, useEffect, useRef }} from 'react';
import {{ useQuery }} from '@tanstack/react-query';

const API = import.meta.env.VITE_API_URL || '';
const WS_BASE = API.replace(/^http/, 'ws');
const RESOURCE_TYPES = {types_json};
const STATUS_COLORS = {{
  running: '#68d391', provisioning: '#f6ad55', error: '#fc8181', stopped: '#718096',
}};

function StatusBadge({{ status }}) {{
  const color = STATUS_COLORS[status] || '#718096';
  return (
    <span style={{{{ padding: '3px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600,
                    background: color + '22', color }}}}>{{status || 'unknown'}}</span>
  );
}}

export default function ResourceExplorer() {{
  const [selected, setSelected] = useState(RESOURCE_TYPES[0] || 'resource');
  const [liveRows, setLiveRows] = useState({{}});
  const wsRef = useRef(null);

  const {{ data }} = useQuery({{
    queryKey: ['resources', selected],
    queryFn: async () => {{
      const r = await fetch(`${{API}}/api/${{selected}}s`, {{
        headers: {{ Authorization: `Bearer ${{localStorage.getItem('access_token') || ''}}` }},
      }});
      if (!r.ok) return {{ items: [] }};
      const j = await r.json();
      return {{ items: j.items ?? j ?? [] }};
    }},
  }});

  useEffect(() => {{
    try {{
      const ws = new WebSocket(`${{WS_BASE}}/ws/resources`);
      ws.onmessage = (ev) => {{
        try {{
          const msg = JSON.parse(ev.data);
          if (msg.id && msg.status) setLiveRows(prev => ({{...prev, [msg.id]: msg.status}}));
        }} catch (err) {{
          console.error('ws parse error', err);
        }}
      }};
      ws.onerror = (e) => console.error('resource ws error', e);
      wsRef.current = ws;
    }} catch (err) {{
      console.error('ws connect failed', err);
    }}
    return () => {{ if (wsRef.current) wsRef.current.close(); }};
  }}, []);

  const rows = data?.items || [];

  async function stopResource(id) {{
    try {{
      await fetch(`${{API}}/api/resources/${{id}}/stop`, {{
        method: 'POST',
        headers: {{ Authorization: `Bearer ${{localStorage.getItem('access_token') || ''}}` }},
      }});
    }} catch (e) {{
      console.error('stop resource failed', e);
    }}
  }}

  async function deleteResource(id) {{
    try {{
      await fetch(`${{API}}/api/resources/${{id}}`, {{
        method: 'DELETE',
        headers: {{ Authorization: `Bearer ${{localStorage.getItem('access_token') || ''}}` }},
      }});
    }} catch (e) {{
      console.error('delete resource failed', e);
    }}
  }}

  return (
    <div style={{{{ display: 'flex', gap: 20 }}}}>
      <div style={{{{ width: 180, background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 10, padding: 16 }}}}>
        <div style={{{{ fontSize: 13, color: '#718096', marginBottom: 12, textTransform: 'uppercase', letterSpacing: 1 }}}}>Types</div>
        {{RESOURCE_TYPES.map(rt => (
          <div key={{rt}} onClick={{() => setSelected(rt)}}
            style={{{{ padding: '8px 12px', cursor: 'pointer', borderRadius: 6, fontSize: 14, marginBottom: 4,
                      background: selected === rt ? '#2d3748' : 'transparent',
                      color: selected === rt ? '#63b3ed' : '#a0aec0' }}}}>
            📁 {{rt}}
          </div>
        ))}}
      </div>
      <div style={{{{ flex: 1, background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 10, padding: 20 }}}}>
        <h2 style={{{{ fontSize: 16, fontWeight: 600, marginBottom: 16, textTransform: 'capitalize' }}}}>{{selected}} Resources</h2>
        <table style={{{{ width: '100%', borderCollapse: 'collapse' }}}}>
          <thead>
            <tr style={{{{ borderBottom: '1px solid #2d3748' }}}}>
              {{['ID', 'Name', 'Status', 'Created', 'Actions'].map(h => (
                <th key={{h}} style={{{{ textAlign: 'left', padding: '8px 12px', fontSize: 12, color: '#718096', fontWeight: 600 }}}}>{{h}}</th>
              ))}}
            </tr>
          </thead>
          <tbody>
            {{rows.map(row => (
              <tr key={{row.id}} style={{{{ borderBottom: '1px solid #1e2130' }}}}>
                <td style={{{{ padding: '10px 12px', fontSize: 12, color: '#718096' }}}}>{{String(row.id).slice(0, 8)}}...</td>
                <td style={{{{ padding: '10px 12px', fontSize: 14 }}}}>{{row.name || row.title || '—'}}</td>
                <td style={{{{ padding: '10px 12px' }}}}>
                  <StatusBadge status={{liveRows[row.id] || row.status || 'running'}} />
                </td>
                <td style={{{{ padding: '10px 12px', fontSize: 12, color: '#718096' }}}}>
                  {{row.created_at ? new Date(row.created_at).toLocaleDateString() : '—'}}
                </td>
                <td style={{{{ padding: '10px 12px', display: 'flex', gap: 8 }}}}>
                  <button onClick={{() => stopResource(row.id)}} style={{{{ padding: '4px 10px', borderRadius: 5, border: '1px solid #f6ad55', background: 'transparent', color: '#f6ad55', cursor: 'pointer', fontSize: 12 }}}}>Stop</button>
                  <button onClick={{() => deleteResource(row.id)}} style={{{{ padding: '4px 10px', borderRadius: 5, border: '1px solid #fc8181', background: 'transparent', color: '#fc8181', cursor: 'pointer', fontSize: 12 }}}}>Delete</button>
                </td>
              </tr>
            ))}}
            {{!rows.length && (
              <tr><td colSpan={{5}} style={{{{ padding: 32, textAlign: 'center', color: '#718096' }}}}>No resources found.</td></tr>
            )}}
          </tbody>
        </table>
      </div>
    </div>
  );
}}
"""


def generate_cost_dashboard_jsx() -> str:
    return """\
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

const API = import.meta.env.VITE_API_URL || '';
const cardStyle = {
  background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 10, padding: 24, marginBottom: 20,
};

export default function CostDashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ['billing'],
    queryFn: async () => {
      const r = await fetch(`${API}/api/billing/current`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
      });
      if (!r.ok) throw new Error('billing fetch failed');
      return r.json();
    },
  });

  async function downloadInvoice() {
    try {
      const r = await fetch(`${API}/api/billing/invoice/current`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
      });
      if (!r.ok) throw new Error('invoice failed');
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'invoice.json'; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('invoice download failed', e);
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Billing & Cost</h1>
        <button onClick={downloadInvoice} style={{ padding: '8px 18px', background: '#2d3748', color: '#e2e8f0', border: 'none', borderRadius: 7, cursor: 'pointer', fontSize: 13 }}>
          ⬇ Download Invoice
        </button>
      </div>
      <div style={{ ...cardStyle, display: 'flex', gap: 40 }}>
        <div>
          <div style={{ fontSize: 13, color: '#718096' }}>Current Month</div>
          <div style={{ fontSize: 36, fontWeight: 700, color: '#68d391', marginTop: 4 }}>
            {isLoading ? '...' : `$${(data?.total_usd ?? 0).toFixed(2)}`}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 13, color: '#718096' }}>Billing Period</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginTop: 4 }}>{data?.month || '—'}</div>
        </div>
      </div>
      <div style={cardStyle}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Daily Spend (Last 30 Days)</h2>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data?.daily_spend || []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
            <XAxis dataKey="date" tick={{ fill: '#718096', fontSize: 12 }} />
            <YAxis tick={{ fill: '#718096', fontSize: 12 }} />
            <Tooltip contentStyle={{ background: '#2d3748', border: 'none', color: '#e2e8f0' }} />
            <Line type="monotone" dataKey="amount" stroke="#63b3ed" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={cardStyle}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Cost Breakdown</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #2d3748' }}>
              {['Service', 'Resources', 'Cost This Month'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 12px', fontSize: 12, color: '#718096', fontWeight: 600 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.breakdown || []).map((row, i) => (
              <tr key={i} style={{ borderBottom: '1px solid #1e2130' }}>
                <td style={{ padding: '10px 12px', fontSize: 14 }}>{row.service}</td>
                <td style={{ padding: '10px 12px', fontSize: 14 }}>{row.resource_count ?? '—'}</td>
                <td style={{ padding: '10px 12px', fontSize: 14, color: '#68d391' }}>${(row.cost ?? 0).toFixed(2)}</td>
              </tr>
            ))}
            {!data?.breakdown?.length && (
              <tr><td colSpan={3} style={{ padding: 32, textAlign: 'center', color: '#718096' }}>No billing data.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
"""


def generate_settings_jsx() -> str:
    return """\
import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

const API = import.meta.env.VITE_API_URL || '';
const cardStyle = {
  background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 10, padding: 24, marginBottom: 20,
};
const inputStyle = {
  width: '100%', background: '#2d3748', border: '1px solid #4a5568', borderRadius: 6,
  padding: '8px 12px', color: '#e2e8f0', fontSize: 14,
};
const btnStyle = {
  padding: '8px 18px', borderRadius: 7, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600,
};

export default function Settings() {
  const { data: keys = [] } = useQuery({
    queryKey: ['api-keys'],
    queryFn: async () => {
      const r = await fetch(`${API}/api/settings/api-keys`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
      });
      return r.ok ? r.json() : [];
    },
  });
  const [webhook, setWebhook] = useState('');
  const [email, setEmail] = useState('');
  const [regions, setRegions] = useState({ 'us-east-1': true, 'us-west-2': false, 'eu-west-1': false });

  async function createApiKey() {
    try {
      await fetch(`${API}/api/settings/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` },
        body: JSON.stringify({ name: `key-${Date.now()}` }),
      });
      window.location.reload();
    } catch (e) {
      console.error('create api key failed', e);
    }
  }

  return (
    <div style={{ maxWidth: 680 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 24 }}>Settings</h1>
      <div style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600 }}>API Keys</h2>
          <button onClick={createApiKey} style={{ ...btnStyle, background: '#3182ce', color: '#fff' }}>+ Create Key</button>
        </div>
        {(Array.isArray(keys) ? keys : []).map((k, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid #2d3748' }}>
            <span style={{ fontSize: 13, fontFamily: 'monospace', color: '#a0aec0' }}>{k.prefix || k.name || 'key'}***</span>
            <span style={{ fontSize: 12, color: '#718096' }}>Created {k.created_at ? new Date(k.created_at).toLocaleDateString() : '—'}</span>
          </div>
        ))}
        {!keys.length && <p style={{ color: '#718096', fontSize: 13 }}>No API keys yet.</p>}
      </div>
      <div style={cardStyle}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Active Regions</h2>
        {Object.entries(regions).map(([r, active]) => (
          <div key={r} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <input type="checkbox" checked={active}
              onChange={() => setRegions(p => ({ ...p, [r]: !p[r] }))}
              style={{ width: 16, height: 16, cursor: 'pointer' }} />
            <span style={{ fontSize: 14 }}>{r}</span>
          </div>
        ))}
      </div>
      <div style={cardStyle}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Notifications</h2>
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#a0aec0', marginBottom: 6 }}>Email</label>
          <input value={email} onChange={e => setEmail(e.target.value)} placeholder="alerts@example.com" style={inputStyle} />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#a0aec0', marginBottom: 6 }}>Webhook URL</label>
          <input value={webhook} onChange={e => setWebhook(e.target.value)} placeholder="https://hooks.example.com/..." style={inputStyle} />
        </div>
        <button style={{ ...btnStyle, background: '#2d4a22', color: '#68d391', border: '1px solid #68d391' }}>
          Save Notifications
        </button>
      </div>
    </div>
  );
}
"""
