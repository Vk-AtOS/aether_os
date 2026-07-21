/**
 * RunControlPanel — run summary card + pause/resume/cancel/rerun controls.
 */
import React from 'react';
import { Pause, Play, X, Loader2 } from 'lucide-react';
import RerunDropdown from '../RerunDropdown';
import { formatTime, PRIORITY_CONFIG } from './projectConstants';

const RunControlPanel = ({
  run,
  elapsed,
  eta,
  artifactCount,
  successRate,
  secFindings,
  isViewer,
  isRunning,
  isPaused,
  isDone,
  priority,
  controlLoading,
  progressPercent,
  onPause,
  onResume,
  onCancel,
  onRerun,
  onFullRestart,
  onEditRestart,
}) => {
  const priConf = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG.normal;
  const runStatus = run.status;

  return (
    <section className="panel p-5 space-y-4">
      <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
        <div>
          <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Duration</div>
          <div className="text-lg font-bold text-bright font-mono">{formatTime(elapsed)}</div>
          {eta !== null && (
            <div className="text-[10px] text-muted mt-0.5">ETA ~{formatTime(Math.round(eta))}</div>
          )}
        </div>
        <div>
          <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Artifacts</div>
          <div className="text-lg font-bold text-bright">{artifactCount}</div>
        </div>
        <div>
          <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Phase Pass Rate</div>
          <div className={`text-lg font-bold ${successRate >= 80 ? 'text-emerald-400' : successRate >= 50 ? 'text-warning' : 'text-danger'}`}>
            {successRate}%
          </div>
        </div>
        <div>
          <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Security</div>
          {secFindings === null ? (
            <div className="text-lg font-bold text-muted">—</div>
          ) : secFindings === 0 ? (
            <div className="text-lg font-bold text-emerald-400">✓ Clean</div>
          ) : (
            <div className={`text-lg font-bold ${secFindings >= 5 ? 'text-danger' : 'text-warning'}`}>
              {secFindings} finding{secFindings !== 1 ? 's' : ''}
            </div>
          )}
        </div>
      </div>

      {/* Control buttons */}
      {!isViewer && (isRunning || isPaused || isDone) && (
        <div className="flex flex-wrap items-center gap-3 pt-3 border-t border-border/50">
          {isRunning && (
            <>
              <button
                onClick={onPause}
                disabled={!!controlLoading}
                className="flex items-center space-x-2 px-4 py-2 bg-yellow-500 hover:bg-yellow-400 text-black font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
              >
                {controlLoading === 'pause' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Pause className="w-4 h-4" />}
                <span>Pause</span>
              </button>
              <button
                onClick={onCancel}
                disabled={!!controlLoading}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
              >
                {controlLoading === 'cancel' ? <Loader2 className="w-4 h-4 animate-spin" /> : <X className="w-4 h-4" />}
                <span>Cancel</span>
              </button>
            </>
          )}
          {isPaused && (
            <>
              <button
                onClick={onResume}
                disabled={!!controlLoading}
                className="flex items-center space-x-2 px-4 py-2 bg-green-600 hover:bg-green-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
              >
                {controlLoading === 'resume' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                <span>Resume</span>
              </button>
              <button
                onClick={onCancel}
                disabled={!!controlLoading}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
              >
                {controlLoading === 'cancel' ? <Loader2 className="w-4 h-4 animate-spin" /> : <X className="w-4 h-4" />}
                <span>Cancel</span>
              </button>
            </>
          )}
          {isDone && (
            <RerunDropdown
              status={runStatus}
              rawInput={run.raw_input || run.requirement || ''}
              variant="button"
              onContinue={onResume}
              onRerunPhase={onRerun}
              onFullRestart={onFullRestart}
              onEditRestart={onEditRestart}
            />
          )}
        </div>
      )}
    </section>
  );
};

export default RunControlPanel;
