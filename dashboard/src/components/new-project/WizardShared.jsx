import React from 'react';
import { TEMPLATE_COLORS } from './wizardData';

export const StepIndicator = ({ step }) => {
  const steps = ['Type', 'Describe', 'Configure', 'Launch'];
  return (
    <div className="flex items-center justify-center mb-10">
      {steps.map((label, i) => {
        const idx = i + 1;
        const active = idx === step;
        const done = idx < step;
        return (
          <React.Fragment key={idx}>
            <div className={`flex items-center gap-2 px-3 py-2 rounded-full text-sm font-medium transition-all ${
              done ? 'text-violet-400' : active ? 'text-white bg-violet-600/20 border border-violet-500/30' : 'text-slate-600'
            }`}>
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                done ? 'bg-violet-600 text-white' : active ? 'bg-violet-600/30 border border-violet-500 text-violet-300' : 'bg-white/[0.04] border border-white/[0.08] text-slate-600'
              }`}>{done ? '✓' : idx}</span>
              {label}
            </div>
            {i < steps.length - 1 && (
              <div className={`w-10 h-px mx-1 transition-colors ${done ? 'bg-violet-600' : 'bg-white/[0.08]'}`} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};

export const TemplateCard = ({ tpl, selected, onClick }) => {
  const color = TEMPLATE_COLORS[tpl.id] || 'from-violet-500 to-indigo-600';
  return (
    <button onClick={onClick} className={`group p-4 rounded-2xl border text-left transition-all duration-200 hover:-translate-y-1 ${
      selected
        ? 'border-violet-500/60 bg-violet-500/10 shadow-lg shadow-violet-500/10'
        : 'border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] hover:bg-white/[0.04]'
    }`}>
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center text-xl mb-3 group-hover:scale-110 transition-transform duration-300`}>
        {tpl.icon}
      </div>
      <div className="text-sm font-semibold text-white">{tpl.label}</div>
      {selected && <div className="mt-2 text-violet-400 text-xs font-medium">✓ Selected</div>}
    </button>
  );
};

export const PillGroup = ({ options, value, onChange }) => (
  <div className="flex gap-2 flex-wrap">
    {options.map(([val, label]) => {
      const active = Array.isArray(value) ? value.includes(val) : value === val;
      return (
        <button key={String(val)} type="button" onClick={() => onChange(val)}
          className={`px-4 py-2 rounded-lg border text-sm font-medium transition-all ${
            active ? 'border-accent bg-accent/15 text-accent' : 'border-border text-muted hover:border-accent/40 hover:text-bright'
          }`}>
          {label}
        </button>
      );
    })}
  </div>
);
