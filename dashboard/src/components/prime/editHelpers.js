// Pure helpers for the edit-before-approve form (KAN-23): build the patch the API accepts from
// what was typed, and the before/after rows shown before saving. No React, so they are testable.

// fields: the request's `detail.editable_fields` ({name: {type, bound}}), current: {amount, params}.
// typed: {name: string} from the form. Returns {amount?, params?} with only what changed.
export const buildPatch = (fields, current, typed) => {
  const patch = { params: {} };
  for (const [name, spec] of Object.entries(fields)) {
    if (!(name in typed)) continue;
    const raw = typed[name];
    if (name === 'amount') {
      if (raw !== '' && Number(raw) !== Number(current.amount)) patch.amount = raw;
      continue;
    }
    const value = spec.type === 'int' ? (raw === '' ? '' : Number(raw)) : raw;
    if (value !== '' && value !== (current.params?.[name] ?? '')) patch.params[name] = value;
  }
  if (Object.keys(patch.params).length === 0) delete patch.params;
  return patch;
};

export const isEmptyPatch = (patch) => !('amount' in patch) && !('params' in patch);

// Rows [{field, before, after}] for the fields the patch changes.
export const diffRows = (current, patch) => {
  const rows = [];
  if ('amount' in patch) rows.push({ field: 'amount', before: current.amount ?? '', after: String(patch.amount) });
  for (const [k, v] of Object.entries(patch.params || {})) {
    rows.push({ field: k, before: String(current.params?.[k] ?? ''), after: String(v) });
  }
  return rows;
};

// Client-side hints only; the server validates again and is the authority.
export const fieldProblem = (name, spec, raw) => {
  if (raw === '' || raw === undefined) return '';
  if (name === 'amount') return Number(raw) > 0 ? '' : 'Enter an amount above zero (INR).';
  if (spec.type === 'int') {
    const [lo, hi] = spec.bound;
    const n = Number(raw);
    return Number.isInteger(n) && n >= lo && n <= hi ? '' : `Enter a whole number from ${lo} to ${hi}.`;
  }
  return String(raw).length <= spec.bound ? '' : `At most ${spec.bound} characters.`;
};
