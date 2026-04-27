import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

// ── Template definitions ─────────────────────────────────────────────────────

const TEMPLATES = [
  {
    id: 'meeting',
    icon: '🗒',
    label: 'Meeting Summarizer',
    name: 'MeetingMind',
    domain: 'general',
    prompt:
      'Build MeetingMind — an AI-powered meeting notes summarizer web app. ' +
      'Single HTML page frontend with dark theme. Large textarea for pasting notes, ' +
      'Summarize button that calls local Ollama at localhost:11434 to extract: ' +
      '3-sentence summary, action items with owners, key decisions, next steps. ' +
      'SQLite storage for history. Left sidebar showing past summaries.',
  },
  {
    id: 'task',
    icon: '✅',
    label: 'Task Manager',
    name: 'TaskFlow',
    domain: 'general',
    prompt:
      'Build a task management web app with dark UI. ' +
      'Features: create/edit/delete tasks with title, description, priority (High/Medium/Low), ' +
      'due date, status (Todo/In Progress/Done). List view with filters. SQLite storage. FastAPI backend.',
  },
  {
    id: 'voice',
    icon: '🎙',
    label: 'Voice Recorder',
    name: 'VoiceVault',
    domain: 'general',
    prompt:
      'Build a voice recording web app. Browser-based recording using MediaRecorder API. ' +
      'Features: record, pause, stop, playback, download. Save recordings as files. ' +
      'Show list of recordings with duration and date. Clean dark UI.',
  },
  {
    id: 'chat',
    icon: '💬',
    label: 'AI Chat App',
    name: 'ChatLab',
    domain: 'general',
    prompt:
      'Build a chat interface that talks to local Ollama at localhost:11434. ' +
      'Dark terminal-style UI. Message history in memory. Streaming-style responses. ' +
      'Clear chat button. FastAPI backend with POST /chat endpoint.',
  },
  {
    id: 'dashboard',
    icon: '📊',
    label: 'Analytics Dashboard',
    name: 'MetricBoard',
    domain: 'analytics',
    prompt:
      'Build an analytics dashboard with dark theme. Shows: line charts for metrics over time, ' +
      'bar charts for comparisons, stat cards. REST API for posting metrics data. ' +
      'Uses Chart.js for visualization. SQLite for data storage. FastAPI backend.',
  },
  {
    id: 'invoice',
    icon: '🧾',
    label: 'Invoice Generator',
    name: 'Invoicer',
    domain: 'fintech',
    prompt:
      'Build an invoice generator web app. Create invoices with client name, line items, ' +
      'quantities, prices. Auto-calculate totals. Store invoices in SQLite. ' +
      'List view of all invoices with total amounts. Dark UI. FastAPI backend.',
  },
  {
    id: 'game',
    icon: '🎮',
    label: 'Simple Game',
    name: 'SnakeGame',
    domain: 'general',
    prompt:
      'Build a browser-based Snake game with dark theme. HTML5 Canvas. ' +
      'Score tracking, high score saved in localStorage. Speed increases as score goes up. ' +
      'Game over screen with restart. Clean minimal UI. FastAPI serves the HTML page.',
  },
  {
    id: 'custom',
    icon: '✏️',
    label: 'Custom',
    name: '',
    domain: 'general',
    prompt: '',
  },
];

const MODELS = [
  { value: 'qwen2.5-coder:3b', label: 'Fast (3B)' },
  { value: 'qwen2.5-coder:7b', label: 'Balanced (7B)' },
  { value: 'llama3.2:3b', label: 'Llama 3.2 (3B)' },
];

const PRIORITIES = ['High', 'Normal', 'Low'];

// ── Sub-components ────────────────────────────────────────────────────────────

const StepIndicator = ({ step }) => {
  const steps = ['Choose Template', 'Customize', 'Configure', 'Launch'];
  return (
    <div className="flex items-center justify-center mb-8 gap-0">
      {steps.map((label, i) => {
        const idx = i + 1;
        const active = idx === step;
        const done = idx < step;
        return (
          <React.Fragment key={idx}>
            <div className="flex flex-col items-center gap-1">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-colors ${
                  active
                    ? 'bg-accent text-white'
                    : done
                    ? 'bg-success text-white'
                    : 'bg-surface border border-border text-muted'
                }`}
              >
                {done ? '✓' : idx}
              </div>
              <span className={`text-[10px] uppercase tracking-wider font-semibold whitespace-nowrap ${active ? 'text-accent' : 'text-muted'}`}>
                {label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div className={`h-px w-16 mb-5 mx-1 transition-colors ${done ? 'bg-success' : 'bg-border'}`} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};

const TemplateCard = ({ tpl, selected, onClick }) => (
  <button
    onClick={onClick}
    className={`p-4 rounded-xl border text-left transition-all ${
      selected
        ? 'border-accent bg-accent/10 shadow-lg shadow-accent/10'
        : 'border-border bg-surface hover:border-accent/50 hover:bg-surface/80'
    }`}
  >
    <div className="text-2xl mb-2">{tpl.icon}</div>
    <div className="text-sm font-semibold text-bright">{tpl.label}</div>
  </button>
);

// ── Main Wizard ───────────────────────────────────────────────────────────────

const NewProjectWizard = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [selectedTpl, setSelectedTpl] = useState(null);
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [domain, setDomain] = useState('general');
  const [model, setModel] = useState(MODELS[0].value);
  const [priority, setPriority] = useState('Normal');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const selectTemplate = (tpl) => {
    setSelectedTpl(tpl.id);
    setName(tpl.name || '');
    setPrompt(tpl.prompt || '');
    setDomain(tpl.domain || 'general');
  };

  const canProceed = () => {
    if (step === 1) return selectedTpl !== null;
    if (step === 2) return prompt.trim().length > 0;
    return true;
  };

  const handleLaunch = async () => {
    if (!prompt.trim()) { setError('Requirement is required.'); return; }
    setLoading(true);
    setError(null);
    try {
      await api.startPipeline({
        raw_input: prompt.trim(),
        project_name: name.trim() || undefined,
        domain,
        model_preference: model,
        priority: priority.toLowerCase(),
        client_id: name.trim()
          ? name.trim().toLowerCase().replace(/\s+/g, '-')
          : 'client-001',
      });
      navigate('/projects');
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to start run.');
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto py-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-bright">New Factory Run</h1>
        <p className="text-sm text-muted mt-1">AetherOS will generate a complete working application from your requirements.</p>
      </div>

      <StepIndicator step={step} />

      {/* ── Step 1: Template Picker ─── */}
      {step === 1 && (
        <div>
          <h2 className="text-base font-semibold text-bright mb-4">What do you want to build?</h2>
          <div className="grid grid-cols-4 gap-3">
            {TEMPLATES.map((tpl) => (
              <TemplateCard
                key={tpl.id}
                tpl={tpl}
                selected={selectedTpl === tpl.id}
                onClick={() => selectTemplate(tpl)}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Step 2: Customize ─── */}
      {step === 2 && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold text-bright">Customize your requirement</h2>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              Project Name <span className="text-slate-600 font-normal normal-case">(optional)</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. MeetingMind"
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              Requirement <span className="text-danger">*</span>
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={8}
              placeholder="Describe what you want to build..."
              className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent resize-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">Domain</label>
            <select
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm text-bright focus:outline-none focus:border-accent"
            >
              {['general','fintech','healthtech','ecommerce','edtech','analytics','devtools'].map((d) => (
                <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* ── Step 3: Configure ─── */}
      {step === 3 && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold text-bright">Configure the run</h2>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">LLM Model</label>
            <div className="flex gap-3">
              {MODELS.map((m) => (
                <button
                  key={m.value}
                  onClick={() => setModel(m.value)}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                    model === m.value
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-border text-muted hover:border-accent/50'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">Priority</label>
            <div className="flex gap-3">
              {PRIORITIES.map((p) => (
                <button
                  key={p}
                  onClick={() => setPriority(p)}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                    priority === p
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-border text-muted hover:border-accent/50'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Step 4: Review & Launch ─── */}
      {step === 4 && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold text-bright">Review & Launch</h2>

          <div className="bg-surface border border-border rounded-xl p-5 space-y-3">
            <div className="flex justify-between">
              <span className="text-xs text-muted uppercase font-semibold tracking-wider">Project</span>
              <span className="text-sm text-bright font-medium">{name || '(auto-named)'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-xs text-muted uppercase font-semibold tracking-wider">Domain</span>
              <span className="text-sm text-bright">{domain}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-xs text-muted uppercase font-semibold tracking-wider">Model</span>
              <span className="text-sm text-bright font-mono">{model}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-xs text-muted uppercase font-semibold tracking-wider">Priority</span>
              <span className="text-sm text-bright">{priority}</span>
            </div>
            <div className="border-t border-border pt-3">
              <span className="text-xs text-muted uppercase font-semibold tracking-wider">Requirement</span>
              <p className="text-sm text-bright mt-1 line-clamp-4 leading-relaxed">{prompt}</p>
            </div>
          </div>

          {error && (
            <div className="bg-danger/10 border border-danger/30 rounded-lg px-4 py-3 text-sm text-danger">
              {error}
            </div>
          )}

          <button
            onClick={handleLaunch}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 py-3 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-xl text-base transition-colors"
          >
            {loading ? (
              <>
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Starting Factory Run…
              </>
            ) : (
              '🚀 Start Factory Run'
            )}
          </button>
        </div>
      )}

      {/* ── Navigation ─── */}
      <div className="flex justify-between mt-8">
        <button
          onClick={() => step > 1 ? setStep(step - 1) : navigate('/projects')}
          className="px-5 py-2.5 text-sm font-medium text-muted hover:text-bright border border-border rounded-lg transition-colors"
        >
          {step === 1 ? 'Cancel' : '← Back'}
        </button>

        {step < 4 && (
          <button
            onClick={() => setStep(step + 1)}
            disabled={!canProceed()}
            className="px-6 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-bold rounded-lg transition-colors"
          >
            {step === 3 ? 'Review →' : 'Next →'}
          </button>
        )}
      </div>
    </div>
  );
};

export default NewProjectWizard;
