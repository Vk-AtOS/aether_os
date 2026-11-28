"""Frontend pattern library (part B) — NotificationCenter component.

SettingsPage lives in frontend_patterns_b2.py to keep both files under 600 lines.
"""
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
          className="relative rounded-full p-2 text-muted-foreground hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Bell className="h-5 w-5" />
          {unread.length > 0 && (
            <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-bold text-destructive-foreground leading-none">
              {unread.length > 99 ? "99+" : unread.length}
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 w-80 rounded-xl border border-border bg-card shadow-xl focus:outline-none"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h2 className="text-sm font-semibold text-foreground">Notifications</h2>
            {unread.length > 0 && (
              <button
                onClick={() => markAllReadMutation.mutate()}
                className="text-xs text-primary hover:text-accent-foreground disabled:opacity-50"
                disabled={markAllReadMutation.isPending}
              >
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-96 overflow-y-auto divide-y divide-border">
            {notifications.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                No notifications yet
              </p>
            ) : (
              notifications.map((n) => (
                <DropdownMenu.Item
                  key={n.id}
                  onSelect={() => !n.read && markReadMutation.mutate(n.id)}
                  className={`flex gap-3 px-4 py-3 text-left focus:outline-none cursor-pointer ${
                    n.read ? "bg-card" : "bg-accent"
                  } hover:bg-muted`}
                >
                  {n.icon && (
                    <span className="flex-shrink-0 text-lg">{n.icon}</span>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground truncate">
                      {n.title}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                      {n.body}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {relativeTime(n.created_at)}
                    </p>
                  </div>
                  {!n.read && (
                    <span className="mt-1.5 flex-shrink-0 h-2 w-2 rounded-full bg-primary" />
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
