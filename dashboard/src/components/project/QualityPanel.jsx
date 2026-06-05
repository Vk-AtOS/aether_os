import React from 'react';
import { Star } from 'lucide-react';

const QualityPanel = ({ qualityData }) => {
  if (!qualityData || qualityData === false) return null;

  return (
    <section className="panel p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Star className="w-4 h-4 text-accent" />
          <span className="text-xs font-bold text-muted uppercase tracking-wider">Quality Score</span>
        </div>
        {/* Circular badge */}
        <div className={`flex items-center justify-center w-14 h-14 rounded-full border-4 font-black text-lg ${
          qualityData.total >= 80
            ? 'border-emerald-500 text-emerald-400 bg-emerald-900/20'
            : qualityData.total >= 60
            ? 'border-yellow-500 text-yellow-400 bg-yellow-900/20'
            : 'border-red-500 text-red-400 bg-red-900/20'
        }`}>
          {qualityData.total}
        </div>
      </div>
      {/* Progress bar */}
      <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${
            qualityData.total >= 80 ? 'bg-emerald-500' : qualityData.total >= 60 ? 'bg-yellow-500' : 'bg-red-500'
          }`}
          style={{ width: `${qualityData.total}%` }}
        />
      </div>
      {/* Dimensions breakdown */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'Auth Coverage',    value: qualityData.auth_coverage,   unit: '%' },
          { label: 'Input Validation', value: qualityData.input_validation, unit: '%' },
          { label: 'Test Coverage',    value: qualityData.test_coverage,   unit: '%' },
          { label: 'Docker',           value: qualityData.has_docker ? 100 : 0, unit: qualityData.has_docker ? '✓' : '✗', binary: true },
        ].map(({ label, value, unit, binary }) => (
          <div key={label} className="bg-border/10 rounded-lg p-3">
            <div className="text-[9px] font-bold text-muted uppercase tracking-wider mb-1">{label}</div>
            <div className={`text-sm font-bold ${
              value >= 80 ? 'text-emerald-400' : value >= 60 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {binary ? unit : `${value}${unit}`}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

export default QualityPanel;
