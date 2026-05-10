import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Users, Shield, CheckCircle2, XCircle, ChevronDown } from 'lucide-react';

const ROLES = ['owner', 'admin', 'member', 'viewer'];

const AdminUsers = () => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [changingRole, setChangingRole] = useState({});

  const fetchUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.client.get('/admin/users');
      setUsers(res.data ?? []);
    } catch (e) {
      if (e.response?.status === 403) {
        setError('Admin access required.');
      } else {
        setError('Failed to load users.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUsers(); }, []);

  const handleRoleChange = async (userId, newRole) => {
    setChangingRole(prev => ({ ...prev, [userId]: true }));
    try {
      await api.client.post(`/admin/users/${userId}/role`, { role: newRole });
      setUsers(prev => prev.map(u => u.id === userId ? { ...u, role: newRole } : u));
    } catch {
      // silent
    } finally {
      setChangingRole(prev => ({ ...prev, [userId]: false }));
    }
  };

  const handleDeactivate = async (userId) => {
    if (!confirm('Deactivate this user?')) return;
    try {
      await api.client.post(`/admin/users/${userId}/deactivate`);
      setUsers(prev => prev.map(u => u.id === userId ? { ...u, is_active: false } : u));
    } catch {
      // silent
    }
  };

  if (loading) return (
    <div className="p-8 flex items-center justify-center">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
    </div>
  );

  if (error) return (
    <div className="p-8">
      <div className="panel p-6 border-danger/30 bg-danger/5">
        <Shield className="w-8 h-8 text-danger mb-3" />
        <p className="text-danger font-medium">{error}</p>
      </div>
    </div>
  );

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-bright">User Management</h1>
        <p className="text-muted mt-1">Manage organisation members and their access levels.</p>
      </header>

      <section className="panel overflow-hidden">
        <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center">
            <Users className="w-4 h-4 mr-2 text-accent" />
            <h3 className="text-xs font-bold text-muted uppercase tracking-widest">
              Organisation Members ({users.length})
            </h3>
          </div>
        </div>

        {users.length === 0 ? (
          <div className="p-12 text-center text-muted">No users found.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-border/10">
                <th className="text-left text-[10px] font-bold text-muted uppercase px-6 py-3">Email</th>
                <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Role</th>
                <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Status</th>
                <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Joined</th>
                <th className="text-right text-[10px] font-bold text-muted uppercase px-6 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map(u => (
                <tr key={u.id} className="hover:bg-border/5 transition-colors">
                  <td className="px-6 py-4">
                    <span className="text-sm font-medium text-bright">{u.email}</span>
                  </td>
                  <td className="px-4 py-4">
                    <select
                      value={u.role}
                      disabled={changingRole[u.id]}
                      onChange={e => handleRoleChange(u.id, e.target.value)}
                      className="bg-surface border border-border rounded px-2 py-1 text-xs text-bright focus:outline-none focus:border-accent"
                    >
                      {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td className="px-4 py-4">
                    {u.is_active !== false ? (
                      <span className="inline-flex items-center text-xs text-success">
                        <CheckCircle2 className="w-3 h-3 mr-1" /> Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center text-xs text-muted">
                        <XCircle className="w-3 h-3 mr-1" /> Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-4 text-xs text-muted font-mono">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-6 py-4 text-right">
                    {u.is_active !== false && (
                      <button
                        onClick={() => handleDeactivate(u.id)}
                        className="text-[10px] font-bold text-danger/70 hover:text-danger uppercase tracking-wider transition-colors"
                      >
                        Deactivate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
};

export default AdminUsers;
