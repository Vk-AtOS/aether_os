// API returns scores either as 0-1 fractions OR 0-100 integers — normalise either way
export const normPct = (score) => {
  if (score == null) return 0;
  return score > 1 ? Math.round(score) : Math.round(score * 100);
};

// ── Small reusable components ──────────────────────────────────────────────────
