"""Frontend pattern library (part B) — NotificationCenter and SettingsPage components."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# NotificationCenter.tsx — Bell icon with unread badge, real-time WebSocket support
# ---------------------------------------------------------------------------

NOTIFICATION_CENTER_COMPONENT = '''\
import React, { useEffect, useRef, useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Bell } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

// ── Types ──────────────────────────────────────────────────────────────────

interface Notification {
  id: string;
  icon?: string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
}

interface NotificationCenterProps {
  /** Optional WebSocket URL for real-time push notifications */
  websocketUrl?: string;
}

// ── Relative time helper ───────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  return `${days}d ago`;
}

const API_BASE = import.meta.env.VITE_API_URL ?? "";

// ── NotificationCenter ─────────────────────────────────────────────────────

export function NotificationCenter({ websocketUrl }: NotificationCenterProps) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);

  const { data: notifications = [] } = useQuery<Notification[]>({
    queryKey: ["notifications"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/notifications`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
      });
      if (!res.ok) throw new Error("Failed to fetch notifications");
      return res.json();
    },
    refetchInterval: 30_000,
  });

  const markReadMutation = useMutation({
    mutationFn: async (id: string) => {
      await fetch(`${API_BASE}/api/notifications/${id}/read`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
    onError: (err) => console.error("mark read failed:", err),
  });

  const markAllReadMutation = useMutation({
    mutationFn: async () => {
      await fetch(`${API_BASE}/api/notifications/read-all`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
    onError: (err) => console.error("mark all read failed:", err),
  });

  // Optional WebSocket real-time push
  useEffect(() => {
    if (!websocketUrl) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(websocketUrl);
      wsRef.current = ws;
      ws.onmessage = () => {
        queryClient.invalidateQueries({ queryKey: ["notifications"] });
      };
      ws.onerror = (err) => console.warn("NotificationCenter WS error:", err);
    } catch (e) {
      console.warn("NotificationCenter: could not open WebSocket:", e);
    }
    return () => wsRef.current?.close();
  }, [websocketUrl, queryClient]);

  const unread = notifications.filter((n) => !n.read);

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button
          aria-label="Notifications"
          className="relative rounded-full p-2 text-gray-500 hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          <Bell className="h-5 w-5" />
          {unread.length > 0 && (
            <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white leading-none">
              {unread.length > 99 ? "99+" : unread.length}
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 w-80 rounded-xl border border-gray-200 bg-white shadow-xl focus:outline-none"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-900">Notifications</h2>
            {unread.length > 0 && (
              <button
                onClick={() => markAllReadMutation.mutate()}
                className="text-xs text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
                disabled={markAllReadMutation.isPending}
              >
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-96 overflow-y-auto divide-y divide-gray-100">
            {notifications.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-gray-400">
                No notifications yet
              </p>
            ) : (
              notifications.map((n) => (
                <DropdownMenu.Item
                  key={n.id}
                  onSelect={() => !n.read && markReadMutation.mutate(n.id)}
                  className={`flex gap-3 px-4 py-3 text-left focus:outline-none cursor-pointer ${
                    n.read ? "bg-white" : "bg-indigo-50"
                  } hover:bg-gray-50`}
                >
                  {n.icon && (
                    <span className="flex-shrink-0 text-lg">{n.icon}</span>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {n.title}
                    </p>
                    <p className="mt-0.5 text-xs text-gray-500 line-clamp-2">
                      {n.body}
                    </p>
                    <p className="mt-1 text-xs text-gray-400">
                      {relativeTime(n.created_at)}
                    </p>
                  </div>
                  {!n.read && (
                    <span className="mt-1.5 flex-shrink-0 h-2 w-2 rounded-full bg-indigo-500" />
                  )}
                </DropdownMenu.Item>
              ))
            )}
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default NotificationCenter;
'''

# ---------------------------------------------------------------------------
# SettingsPage.tsx — 5-tab settings page (Profile/Security/Team/Billing/API Keys)
# ---------------------------------------------------------------------------

SETTINGS_PAGE_COMPONENT = '''\
import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}`, "Content-Type": "application/json" };
}

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...authHeaders(), ...(init?.headers ?? {}) } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ── TIMEZONES ──────────────────────────────────────────────────────────────

const COMMON_TIMEZONES = [
  "UTC", "America/New_York", "America/Chicago", "America/Denver",
  "America/Los_Angeles", "America/Toronto", "America/Sao_Paulo",
  "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow",
  "Asia/Dubai", "Asia/Kolkata", "Asia/Singapore", "Asia/Tokyo",
  "Australia/Sydney", "Pacific/Auckland",
];

// ── Profile Tab ────────────────────────────────────────────────────────────

function ProfileTab() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => apiFetch("/api/users/me") });
  const [displayName, setDisplayName] = useState(me?.display_name ?? "");
  const [timezone, setTimezone] = useState(me?.timezone ?? "UTC");

  const saveProfile = useMutation({
    mutationFn: () => apiFetch("/api/users/me", { method: "PATCH", body: JSON.stringify({ display_name: displayName, timezone }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
    onError: (err) => alert(`Save failed: ${err}`),
  });

  const uploadAvatar = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      await fetch(`${API_BASE}/api/users/me/avatar`, {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
        body: form,
      });
      qc.invalidateQueries({ queryKey: ["me"] });
    } catch (err) {
      alert(`Avatar upload failed: ${err}`);
    }
  };

  return (
    <div className="space-y-6 max-w-md">
      <div className="space-y-2">
        <Label>Avatar</Label>
        <div className="flex items-center gap-4">
          {me?.avatar_url ? (
            <img src={me.avatar_url} alt="avatar" className="h-16 w-16 rounded-full object-cover" />
          ) : (
            <span className="flex h-16 w-16 items-center justify-center rounded-full bg-indigo-100 text-2xl font-bold text-indigo-700">
              {(me?.display_name ?? me?.email ?? "?")[0].toUpperCase()}
            </span>
          )}
          <label className="cursor-pointer rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">
            Change photo
            <input type="file" accept="image/*" className="sr-only" onChange={uploadAvatar} />
          </label>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="display-name">Display name</Label>
        <Input id="display-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="email">Email</Label>
        <div className="flex items-center gap-2">
          <Input id="email" value={me?.email ?? ""} readOnly className="bg-gray-50" />
          {me?.email_verified && <Badge variant="outline" className="text-green-700 border-green-300">Verified</Badge>}
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="timezone">Timezone</Label>
        <select
          id="timezone"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          {COMMON_TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
        </select>
      </div>

      <Button onClick={() => saveProfile.mutate()} disabled={saveProfile.isPending}>
        {saveProfile.isPending ? "Saving…" : "Save changes"}
      </Button>
    </div>
  );
}

// ── Security Tab ───────────────────────────────────────────────────────────

function SecurityTab() {
  const [current, setCurrent] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirm, setConfirm] = useState("");

  const { data: sessions = [] } = useQuery({ queryKey: ["sessions"], queryFn: () => apiFetch("/api/auth/sessions") });

  const changePw = useMutation({
    mutationFn: () => apiFetch("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: current, new_password: newPw }) }),
    onSuccess: () => { setCurrent(""); setNewPw(""); setConfirm(""); alert("Password changed."); },
    onError: (err) => alert(`Error: ${err}`),
  });

  const revokeSession = useMutation({
    mutationFn: (sessionId: string) => apiFetch(`/api/auth/sessions/${sessionId}`, { method: "DELETE" }),
    onError: (err) => alert(`Revoke failed: ${err}`),
  });

  function handleChangePw() {
    if (newPw !== confirm) { alert("Passwords do not match"); return; }
    changePw.mutate();
  }

  return (
    <div className="space-y-8 max-w-md">
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-gray-900">Change password</h3>
        <div className="space-y-2">
          <Label htmlFor="current-pw">Current password</Label>
          <Input id="current-pw" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-pw">New password</Label>
          <Input id="new-pw" type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="confirm-pw">Confirm new password</Label>
          <Input id="confirm-pw" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <Button onClick={handleChangePw} disabled={changePw.isPending}>
          {changePw.isPending ? "Saving…" : "Change password"}
        </Button>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-900">Active sessions</h3>
        {sessions.length === 0 ? (
          <p className="text-sm text-gray-500">No active sessions.</p>
        ) : (
          sessions.map((s: { id: string; user_agent?: string; created_at: string; is_current?: boolean }) => (
            <div key={s.id} className="flex items-center justify-between rounded-lg border border-gray-200 p-3">
              <div>
                <p className="text-sm text-gray-700 truncate max-w-[200px]">{s.user_agent ?? "Unknown device"}</p>
                <p className="text-xs text-gray-400 mt-0.5">{new Date(s.created_at).toLocaleDateString()}</p>
              </div>
              {s.is_current ? (
                <Badge variant="outline" className="text-green-700 border-green-300">Current</Badge>
              ) : (
                <Button size="sm" variant="outline" onClick={() => revokeSession.mutate(s.id)}>Revoke</Button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ── Team Tab ───────────────────────────────────────────────────────────────

function TeamTab() {
  const qc = useQueryClient();
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");

  const { data: members = [] } = useQuery({ queryKey: ["team-members"], queryFn: () => apiFetch("/api/orgs/members") });

  const inviteMember = useMutation({
    mutationFn: () => apiFetch("/api/orgs/invite", { method: "POST", body: JSON.stringify({ email: inviteEmail, role: inviteRole }) }),
    onSuccess: () => { setInviteEmail(""); qc.invalidateQueries({ queryKey: ["team-members"] }); alert("Invite sent."); },
    onError: (err) => alert(`Invite failed: ${err}`),
  });

  const removeMember = useMutation({
    mutationFn: (userId: string) => apiFetch(`/api/orgs/members/${userId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["team-members"] }),
    onError: (err) => alert(`Remove failed: ${err}`),
  });

  return (
    <div className="space-y-6 max-w-lg">
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-900">Invite a team member</h3>
        <div className="flex gap-2">
          <Input placeholder="email@example.com" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} />
          <select
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="admin">Admin</option>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
          </select>
          <Button onClick={() => inviteMember.mutate()} disabled={inviteMember.isPending || !inviteEmail}>
            Invite
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-gray-900">Members</h3>
        {members.map((m: { id: string; user_id: string; name: string; email: string; role: string; joined_at: string }) => (
          <div key={m.id} className="flex items-center justify-between rounded-lg border border-gray-200 p-3">
            <div>
              <p className="text-sm font-medium text-gray-900">{m.name || m.email}</p>
              <p className="text-xs text-gray-500">{m.email} \xb7 joined {new Date(m.joined_at).toLocaleDateString()}</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="capitalize">{m.role}</Badge>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="sm" variant="outline" className="text-red-600 border-red-200 hover:bg-red-50">Remove</Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Remove member?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This will remove {m.name || m.email} from the team. They will lose access immediately.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => removeMember.mutate(m.user_id)} className="bg-red-600 hover:bg-red-700">
                      Remove
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Billing Tab ────────────────────────────────────────────────────────────

function BillingTab() {
  const { data: billing } = useQuery({ queryKey: ["billing"], queryFn: () => apiFetch("/api/billing/subscription") });

  return (
    <div className="space-y-6 max-w-md">
      <div className="rounded-xl border border-gray-200 p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-gray-900 capitalize">{billing?.plan ?? "Free"} plan</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {billing?.current_period_end
                ? `Renews ${new Date(billing.current_period_end * 1000).toLocaleDateString()}`
                : "No active subscription"}
            </p>
          </div>
          <Badge variant="outline" className={billing?.status === "active" ? "text-green-700 border-green-300" : "text-gray-500"}>
            {billing?.status ?? "inactive"}
          </Badge>
        </div>

        {billing?.usage_percent != null && (
          <div>
            <div className="flex justify-between text-xs text-gray-500 mb-1">
              <span>Usage this period</span>
              <span>{Math.round(billing.usage_percent)}%</span>
            </div>
            <div className="h-2 rounded-full bg-gray-200">
              <div
                className="h-2 rounded-full bg-indigo-500 transition-all"
                style={{ width: `${Math.min(billing.usage_percent, 100)}%` }}
              />
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-3">
        <Button variant="outline" onClick={() => window.open("/billing/upgrade", "_blank")}>
          Upgrade plan
        </Button>
        {billing?.status === "active" && !billing?.cancel_at_period_end && (
          <Button variant="outline" className="text-red-600 border-red-200 hover:bg-red-50">
            Cancel subscription
          </Button>
        )}
      </div>
    </div>
  );
}

// ── API Keys Tab ───────────────────────────────────────────────────────────

function ApiKeysTab() {
  const qc = useQueryClient();
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);

  const { data: keys = [] } = useQuery({ queryKey: ["api-keys"], queryFn: () => apiFetch("/api/auth/keys") });

  const createKey = useMutation({
    mutationFn: () => apiFetch("/api/auth/keys", { method: "POST", body: JSON.stringify({ name: newKeyName }) }),
    onSuccess: (data) => {
      setNewKeyName("");
      setNewKeyValue(data.key);
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (err) => alert(`Create failed: ${err}`),
  });

  const revokeKey = useMutation({
    mutationFn: (keyId: string) => apiFetch(`/api/auth/keys/${keyId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
    onError: (err) => alert(`Revoke failed: ${err}`),
  });

  function maskKey(key: string): string {
    if (key.length <= 12) return key;
    return key.slice(0, 8) + "•".repeat(key.length - 12) + key.slice(-4);
  }

  return (
    <div className="space-y-6 max-w-lg">
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-900">Create new API key</h3>
        <div className="flex gap-2">
          <Input
            placeholder="Key name (e.g. Production)"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
          />
          <Button onClick={() => createKey.mutate()} disabled={createKey.isPending || !newKeyName}>
            Create
          </Button>
        </div>
        {newKeyValue && (
          <div className="rounded-lg border border-green-200 bg-green-50 p-3">
            <p className="text-xs font-semibold text-green-800 mb-1">Copy this key now — it won&apos;t be shown again.</p>
            <code className="text-xs text-green-900 break-all">{newKeyValue}</code>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-gray-900">Your API keys</h3>
        {keys.length === 0 ? (
          <p className="text-sm text-gray-500">No API keys yet.</p>
        ) : (
          keys.map((k: { id: string; name: string; key_preview: string; created_at: string }) => (
            <div key={k.id} className="flex items-center justify-between rounded-lg border border-gray-200 p-3">
              <div>
                <p className="text-sm font-medium text-gray-900">{k.name}</p>
                <code className="text-xs text-gray-500">{maskKey(k.key_preview)}</code>
                <p className="text-xs text-gray-400 mt-0.5">Created {new Date(k.created_at).toLocaleDateString()}</p>
              </div>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="sm" variant="outline" className="text-red-600 border-red-200 hover:bg-red-50">Revoke</Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Revoke API key?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Any applications using &ldquo;{k.name}&rdquo; will stop working immediately.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => revokeKey.mutate(k.id)} className="bg-red-600 hover:bg-red-700">
                      Revoke
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ── SettingsPage ───────────────────────────────────────────────────────────

export function SettingsPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Settings</h1>
      <Tabs defaultValue="profile">
        <TabsList className="mb-6">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
          <TabsTrigger value="team">Team</TabsTrigger>
          <TabsTrigger value="billing">Billing</TabsTrigger>
          <TabsTrigger value="api-keys">API Keys</TabsTrigger>
        </TabsList>

        <TabsContent value="profile"><ProfileTab /></TabsContent>
        <TabsContent value="security"><SecurityTab /></TabsContent>
        <TabsContent value="team"><TeamTab /></TabsContent>
        <TabsContent value="billing"><BillingTab /></TabsContent>
        <TabsContent value="api-keys"><ApiKeysTab /></TabsContent>
      </Tabs>
    </div>
  );
}

export default SettingsPage;
'''
