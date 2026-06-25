import { useState } from 'react';
import { Bell, Mail, Globe, CheckCircle2, Loader2, AlertCircle, MessageSquare } from 'lucide-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import api from '../lib/api';

const Notifications = () => {
  const [slack, setSlack]   = useState('');
  const [email, setEmail]   = useState('');
  const [webhook, setWebhook] = useState('');
  const [saved, setSaved]   = useState(false);

  useQuery({
    queryKey: ['notification-settings'],
    queryFn: () => api.get('/api/settings').then(r => r.data).catch(() => ({})),
  });

  const saveMutation = useMutation({
    mutationFn: () => api.post('/api/settings', {
      slack_webhook_url: slack,
      notification_email: email,
      custom_webhook_url: webhook,
    }),
    onSuccess: () => { setSaved(true); setTimeout(() => setSaved(false), 3000); },
  });

  const channels = [
    {
      key: 'slack',
      label: 'Slack',
      icon: MessageSquare,
      description: 'Post repair alerts to a Slack channel via Incoming Webhook.',
      value: slack,
      onChange: setSlack,
      placeholder: 'https://hooks.slack.com/services/…',
    },
    {
      key: 'email',
      label: 'Email',
      icon: Mail,
      description: 'Receive email notifications when repairs complete or escalate.',
      value: email,
      onChange: setEmail,
      placeholder: 'you@company.com',
      type: 'email',
    },
    {
      key: 'webhook',
      label: 'Custom Webhook',
      icon: Globe,
      description: 'Send a JSON POST to your own endpoint on every repair event.',
      value: webhook,
      onChange: setWebhook,
      placeholder: 'https://your.system/dcsp-events',
    },
  ];

  const triggers = [
    { id: 'on_success',   label: 'Patch generated',     desc: 'AI produced a verified fix' },
    { id: 'on_escalated', label: 'Escalated to human',  desc: 'AI could not auto-fix — needs review' },
    { id: 'on_approved',  label: 'Patch approved & PR', desc: 'User approved, PR created' },
  ];

  return (
    <div className="max-w-xl space-y-7">
      <div>
        <h2 className="text-xl font-bold text-white">Notifications</h2>
        <p className="text-slate-500 text-xs mt-0.5">Get alerted the moment DCSP acts on a CI failure.</p>
      </div>

      {/* Channels */}
      <div className="space-y-4">
        {channels.map(ch => (
          <div key={ch.key} className="bg-surface border border-border rounded-lg p-5">
            <div className="flex items-start gap-3 mb-3">
              <div className="p-2 bg-background border border-border rounded-md">
                <ch.icon size={15} className="text-slate-400" />
              </div>
              <div>
                <p className="text-white font-semibold text-sm">{ch.label}</p>
                <p className="text-slate-500 text-xs mt-0.5">{ch.description}</p>
              </div>
            </div>
            <input
              type={ch.type ?? 'text'}
              value={ch.value}
              onChange={e => ch.onChange(e.target.value)}
              placeholder={ch.placeholder}
              className="w-full bg-background border border-border rounded-md px-3 py-2.5 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        ))}
      </div>

      {/* Trigger events */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
          <Bell size={14} className="text-slate-500" />
          Notify on
        </h3>
        <div className="space-y-3">
          {triggers.map(t => (
            <label key={t.id} className="flex items-start gap-3 cursor-pointer group">
              <input type="checkbox" defaultChecked className="mt-0.5 accent-accent" />
              <div>
                <p className="text-sm text-white font-medium">{t.label}</p>
                <p className="text-xs text-slate-500">{t.desc}</p>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-md transition-colors disabled:opacity-60"
        >
          {saveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
          Save Settings
        </button>
        {saved && (
          <span className="text-success text-xs flex items-center gap-1 font-semibold">
            <CheckCircle2 size={13} /> Saved
          </span>
        )}
        {saveMutation.isError && (
          <span className="text-error text-xs flex items-center gap-1">
            <AlertCircle size={13} /> Save failed
          </span>
        )}
      </div>
    </div>
  );
};

export default Notifications;
