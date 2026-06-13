export function GlassCard({ children, className = '', hover = false, glow = false }) {
  return (
    <div className={`
      bg-white/[0.02] backdrop-blur-xl
      border border-white/[0.06] rounded-2xl
      ${hover ? 'hover:bg-white/[0.04] hover:border-white/[0.12] transition-all duration-300 cursor-pointer' : ''}
      ${glow ? 'hover:shadow-lg hover:shadow-violet-500/10' : ''}
      ${className}
    `}>
      {children}
    </div>
  );
}
