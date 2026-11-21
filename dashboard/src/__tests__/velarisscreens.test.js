import { describe, it, expect } from 'vitest';
import { screenById } from '../components/velaris/screens';

const sections = (id) => screenById(id).sections;

describe('Velaris compliance screens (KAN-132, 137, 142)', () => {
  it('employee privacy: admin only, flagged for legal review, export and erase need a typed word', () => {
    const s = screenById('privacy');
    expect(s.role).toBe('admin');
    expect(s.banner).toMatch(/pending legal review \(KAN-80\)/);
    const typed = Object.fromEntries(s.sections.filter((x) => x.typed).map((x) => [x.typed, x]));
    expect(typed.EXPORT.download).toBeTruthy();
    expect(typed.ERASE.danger).toBe(true);
  });

  it('mail compliance: preview sends dry_run, the real run does not, hold can target messages', () => {
    const ss = sections('mail-compliance');
    const preview = ss.find((x) => /Preview retention/.test(x.title));
    const run = ss.find((x) => x.title === 'Run retention now');
    expect(preview.fixed).toEqual({ dry_run: true });
    expect(run.fixed).toBeUndefined();
    expect(ss.find((x) => /Legal hold/.test(x.title)).fields.map((f) => f.name)).toContain('message_ids');
    expect(ss.find((x) => x.typed === 'ERASE').call.method).toBe('delete');
  });

  it('leave approvals: Zoho attendance and employee list are reachable by admins', () => {
    const s = screenById('leave-approvals');
    expect(s.role).toBe('admin');
    const methods = s.sections.map((x) => x.call?.hr?.[1]);
    expect(methods).toEqual(expect.arrayContaining(['get_attendance', 'get_employees', 'approve', 'reject']));
  });
});
