// Turns the text of a Python signature, as Velaris sends it ("(a: str, b: int = 3) -> dict"),
// into form fields. Anything not understood falls back to a plain text field.
const splitTop = (text) => {
  const parts = [];
  let depth = 0;
  let cur = '';
  for (const ch of text) {
    if ('([{'.includes(ch)) depth += 1;
    if (')]}'.includes(ch)) depth -= 1;
    if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; } else { cur += ch; }
  }
  if (cur.trim()) parts.push(cur);
  return parts;
};

export const parseSignature = (sig) => {
  const open = sig.indexOf('(');
  const close = sig.lastIndexOf(')');
  if (open < 0 || close < open) return [];
  return splitTop(sig.slice(open + 1, close)).map((p) => p.trim()).filter((p) => p && p !== '*' && p !== '/' && !p.startsWith('*'))
    .map((p) => {
      const [head, ...def] = p.split('=');
      const [name, ...ann] = head.split(':');
      const type = ann.join(':').trim();
      const kind = /\bbool\b/.test(type) ? 'bool' : /\b(int|float)\b/.test(type) ? 'number'
        : /\b(list|dict|List|Dict|Any)\b/i.test(type) ? 'json' : 'text';
      return { name: name.trim(), type, kind, required: def.length === 0 };
    });
};

// Form values -> the JSON body. Empty fields are left out so the agent's own defaults apply.
export const buildArgs = (fields, values) => {
  const args = {};
  for (const f of fields) {
    const v = values[f.name];
    if (v === undefined || v === '') continue;
    if (f.kind === 'number') args[f.name] = Number(v);
    else if (f.kind === 'bool') args[f.name] = v === 'true';
    else if (f.kind === 'json') args[f.name] = JSON.parse(v);
    else args[f.name] = v;
  }
  return args;
};
