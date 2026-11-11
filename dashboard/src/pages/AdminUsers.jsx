import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { Users, Shield, CheckCircle2, XCircle, Search, UserPlus, RefreshCw, ChevronLeft, ChevronRight, Upload, Trash2, Loader2 } from 'lucide-react';
import { TableSkeleton } from '../components/PageLoader';
import { ROLES, ROLE_BADGE, InvitePanel, BulkImportPanel } from '../components/admin/UserPanels';
import { confirmAction } from '../components/confirmAction';

const AdminUsers = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [changingRole, setChangingRole] = useState({});
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [inviteStatus, setInviteStatus] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  const [showBulk, setShowBulk] = useState(false);
  const [bulkCsv, setBulkCsv] = useState('');
  const [bulkStatus, setBulkStatus] = useState(null); // null | 'importing' | { ok, errors }
  const [bulkRole, setBulkRole] = useState('member');
  const [pruning, setPruning] = useState(false);
  const [pruneResult, setPruneResult] = useState(null);
  const [confirmDeactivate, setConfirmDeactivate] = useState(null); // userId or 'bulk'
  const [prunePreview, setPrunePreview] = useState(null); // { deleted_count, deleted_mb }
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const LIMIT = 20;

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { page, limit: LIMIT };
      if (search) params.search = search;
      if (roleFilter) params.role = roleFilter;
      if (statusFilter) params.status = statusFilter;
      const res = await api.client.get('/admin/users', { params });
      const data = res.data;
      setItems(data.items ?? data ?? []);
      setTotal(data.total ?? (data.items ?? data ?? []).length);
    } catch (e) {
      setError(e.response?.status === 403 ? 'Admin access required.' : 'Failed to load users.');
    } finally {
      setLoading(false);
    }
  }, [page, search, roleFilter, statusFilter]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleSearch = (e) => {
    e.preventDefault();
    setSearch(searchInput);
    setPage(1);
  };

  const handleRoleChange = async (userId, newRole) => {
    setChangingRole(prev => ({ ...prev, [userId]: true }));
    try {
      await api.client.post(`/admin/users/${userId}/role`, { role: newRole });
      setItems(prev => prev.map(u => u.id === userId ? { ...u, role: newRole } : u));
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to change role.');
    } finally {
      setChangingRole(prev => { const n = { ...prev }; delete n[userId]; return n; });
    }
  };

  const handleReactivate = async (userId) => {
    try {
      await api.client.post(`/admin/users/${userId}/reactivate`);
      setItems(prev => prev.map(u => u.id === userId ? { ...u, is_active: true } : u));
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to reactivate user.');
    }
  };

  const handleResetPassword = async (userId) => {
    if (!(await confirmAction('Generate a temporary password for this user?'))) return;
    try {
      const res = await api.client.post(`/admin/users/${userId}/reset-password`);
      const { temp_password } = res.data;
      navigator.clipboard?.writeText(temp_password).catch(() => {});
      alert(`Temporary password (copied to clipboard):\n${temp_password}\n\nShare this securely with the user.`);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to reset password.');
    }
  };

  const handleDeactivate = async (userId) => {
    if (confirmDeactivate !== userId) { setConfirmDeactivate(userId); return; }
    setConfirmDeactivate(null);
    try {
      await api.client.post(`/admin/users/${userId}/deactivate`);
      setItems(prev => prev.map(u => u.id === userId ? { ...u, is_active: false } : u));
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to deactivate user.');
    }
  };

  const handleBulkDeactivate = async () => {
    if (!selectedIds.size) return;
    if (confirmDeactivate !== 'bulk') { setConfirmDeactivate('bulk'); return; }
    setConfirmDeactivate(null);
    const failures = [];
    for (const id of selectedIds) {
      try { await api.client.post(`/admin/users/${id}/deactivate`); } catch (err) {
        failures.push(id);
      }
    }
    if (failures.length) setError(`Failed to deactivate ${failures.length} user(s).`);
    setItems(prev => prev.map(u => selectedIds.has(u.id) ? { ...u, is_active: false } : u));
    setSelectedIds(new Set());
  };

  const handleInvite = async (e) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setInviteStatus('sending');
    try {
      const res = await api.client.post('/admin/users/invite', { email: inviteEmail, role: inviteRole });
      const data = res.data || {};
      if (data.email_sent === false && data.temp_password) {
        // Email failed — show temp password so admin can share it manually
        const msg = `Invite created but email could not be sent.\n\nShare these credentials manually:\nEmail: ${inviteEmail}\nTemporary password: ${data.temp_password}`;
        navigator.clipboard?.writeText(`Email: ${inviteEmail}\nPassword: ${data.temp_password}`).catch(() => {});
        setInviteStatus('sent');
        alert(msg);
      } else {
        setInviteStatus('sent');
      }
      setInviteEmail('');
      setTimeout(() => { setInviteStatus(null); setShowInvite(false); }, 2000);
      fetchUsers();
    } catch (err) {
      setInviteStatus('error');
    }
  };

  const handleBulkImport = async (e) => {
    e.preventDefault();
    if (!bulkCsv.trim()) return;
    const emails = bulkCsv.split(/[\n,]+/).map(s => s.trim()).filter(s => s.includes('@'));
    if (!emails.length) { setBulkStatus({ ok: 0, errors: ['No valid email addresses found.'] }); return; }
    setBulkStatus('importing');
    const errors = [];
    let ok = 0;
    for (const email of emails) {
      try {
        await api.client.post('/scim/v2/Users', {
          schemas: ['urn:ietf:params:scim:schemas:core:2.0:User'],
          userName: email,
          emails: [{ value: email, primary: true }],
          externalId: null,
          role: bulkRole,
        });
        ok++;
      } catch (err) {
        errors.push(`${email}: ${err.response?.data?.detail || 'failed'}`);
      }
    }
    setBulkStatus({ ok, errors });
    if (ok > 0) fetchUsers();
  };

  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map(u => u.id)));
    }
  };

  const handlePruneArtifacts = async () => {
    setPruneResult(null);
    // If we have preview data, proceed with actual prune
    if (prunePreview) {
      if (prunePreview.deleted_count === 0) { setPrunePreview(null); return; }
      setPruning('running');
      try {
        const res = await api.client.post('/admin/prune-artifacts', { ttl_days: 30, dry_run: false });
        setPruneResult({ ok: true, ...res.data });
      } catch (e) {
        setPruneResult({ ok: false, message: e.response?.data?.detail || 'Prune failed.' });
      } finally {
        setPruning(false);
        setPrunePreview(null);
      }
      return;
    }
    // Dry-run first to preview
    setPruning('dry');
    try {
      const dryRes = await api.client.post('/admin/prune-artifacts', { ttl_days: 30, dry_run: true });
      setPrunePreview(dryRes.data);
    } catch (e) {
      setPruneResult({ ok: false, message: e.response?.data?.detail || 'Prune dry-run failed.' });
    } finally {
      setPruning(false);
    }
  };

  const totalPages = Math.ceil(total / LIMIT);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright">User Management</h1>
          <p className="text-muted mt-1">Manage organisation members and their access levels.</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={fetchUsers}
            className="p-2 text-muted hover:text-bright border border-border rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            onClick={handlePruneArtifacts}
            disabled={!!pruning}
            className="flex items-center gap-2 bg-danger/10 hover:bg-danger/20 text-danger text-xs font-bold px-4 py-2 rounded-lg transition-colors border border-danger/30 disabled:opacity-50"
            title="Delete artifact files older than 30 days"
          >
            {pruning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
            {pruning === 'dry' ? 'Checking…' : pruning === 'running' ? 'Pruning…' : 'Prune Artifacts'}
          </button>
          <button
            onClick={() => { setShowBulk(v => !v); setShowInvite(false); }}
            className="flex items-center gap-2 bg-border hover:bg-border/80 text-muted hover:text-bright text-xs font-bold px-4 py-2 rounded-lg transition-colors border border-border"
          >
            <Upload className="w-3.5 h-3.5" /> Bulk Import
          </button>
          <button
            onClick={() => { setShowInvite(v => !v); setShowBulk(false); }}
            className="flex items-center gap-2 bg-accent hover:bg-accent/90 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors"
          >
            <UserPlus className="w-3.5 h-3.5" /> Invite User
          </button>
        </div>
      </header>

      {/* Prune preview confirmation */}
      {prunePreview && (
        <div className="flex items-center gap-4 p-4 rounded-xl border bg-yellow-500/10 border-yellow-500/30 text-sm">
          <div className="flex-1">
            {prunePreview.deleted_count === 0
              ? <span className="text-muted">No artifacts older than 30 days found. Nothing to prune.</span>
              : <span className="text-yellow-400">Prune <strong>{prunePreview.deleted_count}</strong> file(s) ({prunePreview.deleted_mb} MB older than 30 days)? This cannot be undone.</span>}
          </div>
          {prunePreview.deleted_count > 0 && (
            <button onClick={handlePruneArtifacts} disabled={!!pruning} className="text-xs font-bold bg-danger/20 hover:bg-danger/40 text-danger border border-danger/30 px-3 py-1.5 rounded-lg disabled:opacity-50 transition-colors">
              Confirm Prune
            </button>
          )}
          <button onClick={() => setPrunePreview(null)} className="text-xs text-muted hover:text-bright px-2 py-1 rounded">
            Cancel
          </button>
        </div>
      )}

      {/* Prune result banner */}
      {pruneResult && (
        <div className={`flex items-start gap-3 p-4 rounded-xl border text-sm ${pruneResult.ok ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-red-500/10 border-red-500/30 text-danger'}`}>
          {pruneResult.ok ? <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" /> : <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />}
          <div>
            {pruneResult.ok
              ? <span>Pruned <strong>{pruneResult.deleted_count}</strong> file(s) — freed <strong>{pruneResult.deleted_mb} MB</strong>.</span>
              : <span>{pruneResult.message}</span>}
          </div>
          <button onClick={() => setPruneResult(null)} className="ml-auto text-xs text-muted hover:text-bright">✕</button>
        </div>
      )}

      {showInvite && (
        <InvitePanel
          inviteEmail={inviteEmail} setInviteEmail={setInviteEmail}
          inviteRole={inviteRole} setInviteRole={setInviteRole}
          inviteStatus={inviteStatus}
          onSubmit={handleInvite}
          onClose={() => setShowInvite(false)}
        />
      )}

      {showBulk && (
        <BulkImportPanel
          bulkCsv={bulkCsv} setBulkCsv={setBulkCsv}
          bulkRole={bulkRole} setBulkRole={setBulkRole}
          bulkStatus={bulkStatus}
          onSubmit={handleBulkImport}
          onClose={() => { setShowBulk(false); setBulkCsv(''); setBulkStatus(null); }}
        />
      )}

      <section className="panel overflow-hidden">
        {/* Toolbar */}
        <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Users className="w-4 h-4 text-accent" />
            <h3 className="text-xs font-bold text-muted uppercase tracking-widest flex items-baseline gap-2">
              <span>Members</span>
              <span className="text-accent">{total}</span>
            </h3>
            {selectedIds.size > 0 && (
              confirmDeactivate === 'bulk' ? (
                <span className="ml-3 flex items-center gap-2 text-[10px]">
                  <span className="text-danger font-bold">Deactivate {selectedIds.size} user(s)?</span>
                  <button onClick={handleBulkDeactivate} className="text-danger font-bold underline">Yes</button>
                  <button onClick={() => setConfirmDeactivate(null)} className="text-muted hover:text-bright">Cancel</button>
                </span>
              ) : (
                <button
                  onClick={handleBulkDeactivate}
                  className="ml-3 text-[10px] font-bold text-danger/70 hover:text-danger uppercase tracking-wider transition-colors"
                >
                  Deactivate {selectedIds.size} selected
                </button>
              )
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <form onSubmit={handleSearch} className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted" />
                <input
                  type="text"
                  placeholder="Search by email…"
                  value={searchInput}
                  onChange={e => setSearchInput(e.target.value)}
                  className="bg-surface border border-border rounded-lg pl-9 pr-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent w-52"
                />
              </div>
              <button type="submit" className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-3 py-1.5 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors">
                Search
              </button>
            </form>
            <div className="flex items-center gap-2">
              <select
                value={roleFilter}
                onChange={e => { setRoleFilter(e.target.value); setPage(1); }}
                className="bg-surface border border-border rounded-lg px-2 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
              >
                <option value="">All roles</option>
                {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <select
                value={statusFilter}
                onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
                className="bg-surface border border-border rounded-lg px-2 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
              >
                <option value="">All status</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="p-6">
            <TableSkeleton rows={6} />
          </div>
        ) : error ? (
          <div className="p-8">
            <div className="flex items-center gap-3 text-danger">
              <Shield className="w-5 h-5" />
              <span className="text-sm font-medium">{error}</span>
            </div>
          </div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center text-muted text-sm">
            {search ? `No users matching "${search}".` : 'No users found.'}
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-border/10">
                <th className="w-10 px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === items.length && items.length > 0}
                    onChange={toggleSelectAll}
                    className="accent-accent"
                  />
                </th>
                <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Email</th>
                <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Role</th>
                <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Status</th>
                <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Joined</th>
                <th className="text-right text-[10px] font-bold text-muted uppercase px-6 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map(u => (
                <tr key={u.id} className={`hover:bg-border/5 transition-colors ${selectedIds.has(u.id) ? 'bg-accent/5' : ''}`}>
                  <td className="px-4 py-4">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(u.id)}
                      onChange={() => toggleSelect(u.id)}
                      className="accent-accent"
                    />
                  </td>
                  <td className="px-4 py-4">
                    <span className="text-sm font-medium text-bright">{u.email}</span>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider ${ROLE_BADGE[u.role] || ROLE_BADGE.member}`}>
                        {u.role}
                      </span>
                      <select
                        value={u.role}
                        disabled={!!changingRole[u.id]}
                        onChange={e => handleRoleChange(u.id, e.target.value)}
                        className="bg-surface border border-border/50 rounded px-1.5 py-0.5 text-[10px] text-muted focus:outline-none focus:border-accent"
                        title="Change role"
                      >
                        {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    {u.is_active !== false ? (
                      <span className="inline-flex items-center text-xs text-success gap-1">
                        <CheckCircle2 className="w-3 h-3" /> Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center text-xs text-muted gap-1">
                        <XCircle className="w-3 h-3" /> Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-4 text-xs text-muted font-mono">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => handleResetPassword(u.id)}
                        className="text-[10px] font-bold text-muted/60 hover:text-muted uppercase tracking-wider transition-colors"
                        title="Reset password"
                      >
                        Reset Pw
                      </button>
                      {u.is_active !== false ? (
                        confirmDeactivate === u.id ? (
                          <span className="flex items-center gap-2 text-[10px]">
                            <span className="text-danger font-bold">Confirm?</span>
                            <button onClick={() => handleDeactivate(u.id)} className="text-danger font-bold underline">Yes</button>
                            <button onClick={() => setConfirmDeactivate(null)} className="text-muted hover:text-bright">No</button>
                          </span>
                        ) : (
                          <button
                            onClick={() => handleDeactivate(u.id)}
                            className="text-[10px] font-bold text-danger/60 hover:text-danger uppercase tracking-wider transition-colors"
                          >
                            Deactivate
                          </button>
                        )
                      ) : (
                        <button
                          onClick={() => handleReactivate(u.id)}
                          className="text-[10px] font-bold text-success/70 hover:text-success uppercase tracking-wider transition-colors"
                        >
                          Reactivate
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="px-6 py-4 border-t border-border flex items-center justify-between">
            <span className="text-xs text-muted">
              Showing {(page - 1) * LIMIT + 1}–{Math.min(page * LIMIT, total)} of {total}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-1.5 rounded border border-border text-muted hover:text-bright disabled:opacity-40 transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="text-xs font-mono text-muted px-2">{page} / {totalPages}</span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-1.5 rounded border border-border text-muted hover:text-bright disabled:opacity-40 transition-colors"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

export default AdminUsers;
