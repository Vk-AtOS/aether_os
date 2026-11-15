import { describe, expect, it } from 'vitest';
import { buildPatch, diffRows, fieldProblem, isEmptyPatch } from '../components/prime/editHelpers';

const fields = { amount: { type: 'decimal' }, note: { type: 'str', bound: 10 }, days: { type: 'int', bound: [1, 365] } };
const current = { amount: '250', params: { note: 'march', days: 2 } };

describe('edit-before-approve helpers', () => {
  it('keeps only what changed and types integers', () => {
    const patch = buildPatch(fields, current, { amount: '300', note: 'march', days: '5' });
    expect(patch).toEqual({ amount: '300', params: { days: 5 } });
    expect(diffRows(current, patch)).toEqual([
      { field: 'amount', before: '250', after: '300' },
      { field: 'days', before: '2', after: '5' },
    ]);
  });

  it('an untouched form is an empty patch', () => {
    expect(isEmptyPatch(buildPatch(fields, current, { amount: '250', note: 'march', days: '2' }))).toBe(true);
    expect(isEmptyPatch(buildPatch(fields, current, {}))).toBe(true);
  });

  it('flags values the server would refuse', () => {
    expect(fieldProblem('days', fields.days, '0')).not.toBe('');
    expect(fieldProblem('days', fields.days, '2.5')).not.toBe('');
    expect(fieldProblem('note', fields.note, 'x'.repeat(11))).not.toBe('');
    expect(fieldProblem('amount', fields.amount, '-1')).not.toBe('');
    expect(fieldProblem('days', fields.days, '30')).toBe('');
  });
});
