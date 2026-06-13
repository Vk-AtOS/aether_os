export function GradientButton({ children, onClick, className = '', size = 'md', variant = 'primary', disabled = false, type = 'button' }) {
  const sizes = { sm: 'px-3 py-1.5 text-sm', md: 'px-5 py-2.5 text-sm', lg: 'px-6 py-3 text-base' };
  const variants = {
    primary: 'bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 shadow-lg shadow-violet-500/25 hover:shadow-violet-500/40',
    ghost: 'border border-white/10 hover:bg-white/[0.04] hover:border-white/20',
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`
        ${sizes[size]} ${variants[variant]}
        font-medium text-white rounded-xl
        transition-all duration-200 active:scale-95
        disabled:opacity-50 disabled:cursor-not-allowed
        ${className}
      `}
    >
      {children}
    </button>
  );
}
