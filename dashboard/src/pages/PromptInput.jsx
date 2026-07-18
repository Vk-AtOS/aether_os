import React, { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Send, Loader2, Bot, User, AlertCircle, Sparkles } from 'lucide-react';

const SCOPE_GUARD = "I'm focused on your project. What aspect of the project should I help you with?";

const Message = ({ msg }) => {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${isUser ? 'bg-accent/20 text-accent' : 'bg-surface border border-border text-muted'}`}>
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>
      <div className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
        isUser
          ? 'bg-accent text-white rounded-tr-sm'
          : 'bg-panel border border-border text-bright rounded-tl-sm'
      }`}>
        {msg.content}
      </div>
    </div>
  );
};

const PromptInput = () => {
  const { id: runId } = useParams();
  const navigate = useNavigate();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [projectName, setProjectName] = useState(runId ? `Run ${runId}` : 'New Project');
  const [error, setError] = useState(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (!runId) return;
    api.client.get(`/factory/runs/${runId}`)
      .then(r => {
        const name = r.data?.project_name || r.data?.run?.project_name;
        if (name) setProjectName(name);
      })
      .catch(() => {});
  }, [runId]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setError(null);

    const userMsg = { role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      if (runId) {
        const r = await api.client.post(`/factory/runs/${runId}/chat`, {
          message: text,
          history: messages.slice(-10),
        });
        setMessages(prev => [...prev, { role: 'assistant', content: r.data.reply }]);
      } else {
        // No run context — start a new project
        await api.startPipeline?.({ raw_input: text });
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: "I've received your requirements and started the pipeline. You'll be redirected to your project shortly.",
        }]);
        setTimeout(() => navigate('/projects'), 2000);
      }
    } catch (e) {
      const detail = e.response?.data?.detail || e.message || 'An error occurred';
      setError(detail);
      setMessages(prev => [...prev, { role: 'assistant', content: `Sorry, something went wrong: ${detail}` }]);
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const STARTERS = [
    "I need a SaaS dashboard with user management and subscription billing",
    "Build a REST API for an e-commerce platform with product catalog and orders",
    "Create a project management tool with Kanban boards and team collaboration",
    "I need a real-time chat application with rooms and message history",
  ];

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] max-w-3xl mx-auto p-4">
      <div className="flex items-center gap-3 mb-4 pb-4 border-b border-border">
        <div className="w-9 h-9 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center">
          <Sparkles className="w-5 h-5 text-accent" />
        </div>
        <div>
          <h1 className="font-bold text-bright">{projectName}</h1>
          <p className="text-xs text-muted">Project-scoped AI assistant · All conversations stay on-topic</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pb-4 custom-scrollbar">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-6">
            <div className="w-16 h-16 rounded-2xl bg-accent/10 border border-accent/20 flex items-center justify-center">
              <Bot className="w-8 h-8 text-accent" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-bright mb-2">
                {runId ? `What do you want to build?` : 'Start a new project'}
              </h2>
              <p className="text-muted text-sm max-w-sm">
                {runId
                  ? `I'm focused on "${projectName}". Ask me about requirements, architecture, code review, testing, or deployment.`
                  : "Describe what you want to build and I'll start the factory pipeline."}
              </p>
            </div>
            <div className="grid grid-cols-1 gap-2 w-full max-w-sm">
              {STARTERS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => { setInput(s); inputRef.current?.focus(); }}
                  className="text-left p-3 bg-panel border border-border hover:border-accent/40 rounded-lg text-sm text-muted hover:text-bright transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => <Message key={m.id || `${m.role}-${i}`} msg={m} />)}

        {loading && (
          <div className="flex gap-3">
            <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-surface border border-border text-muted">
              <Bot className="w-4 h-4" />
            </div>
            <div className="bg-panel border border-border rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-muted" />
              <span className="text-sm text-muted">Thinking…</span>
            </div>
          </div>
        )}

        <div ref={endRef} />
      </div>

      {error && (
        <div className="flex items-center gap-2 mb-2 p-2 bg-red-900/20 border border-red-700/40 rounded text-red-400 text-xs">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          {error}
        </div>
      )}

      <div className="flex gap-2 pt-2 border-t border-border">
        <textarea
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={runId ? `Ask about ${projectName}…` : 'Describe the project you want to build…'}
          rows={2}
          className="flex-1 bg-surface border border-border rounded-xl px-4 py-2.5 text-sm text-bright focus:outline-none focus:border-accent transition-colors resize-none custom-scrollbar"
        />
        <button
          onClick={send}
          disabled={!input.trim() || loading}
          className="shrink-0 w-10 h-10 self-end mb-0.5 bg-accent hover:bg-accent/90 disabled:opacity-40 rounded-xl flex items-center justify-center transition-colors"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin text-white" /> : <Send className="w-4 h-4 text-white" />}
        </button>
      </div>
      <p className="text-[10px] text-muted text-center mt-2">
        Press Enter to send · Shift+Enter for new line · Responses are scoped to this project
      </p>
    </div>
  );
};

export default PromptInput;
