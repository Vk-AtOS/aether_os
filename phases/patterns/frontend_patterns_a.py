"""Frontend pattern library (part A) — KanbanBoard and CommandPalette components."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# KanbanBoard.tsx — HTML5 native drag-and-drop Kanban with priority badges
# ---------------------------------------------------------------------------

KANBAN_COMPONENT = '''\
import React, { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

// ── Types ──────────────────────────────────────────────────────────────────

type Priority = "low" | "medium" | "high" | "urgent";

interface KanbanCardData {
  id: string;
  title: string;
  priority?: Priority;
  assigneeInitials?: string;
  dueDate?: string;
}

interface KanbanColumnData {
  id: string;
  title: string;
  color?: string;
  cards: KanbanCardData[];
}

interface KanbanBoardProps {
  columns: KanbanColumnData[];
  onCardMove: (cardId: string, fromColumnId: string, toColumnId: string) => void;
}

// ── Priority helpers ───────────────────────────────────────────────────────

const PRIORITY_COLORS: Record<Priority, string> = {
  low: "bg-accent text-accent-foreground",
  medium: "bg-warning-soft text-warning-foreground",
  high: "bg-warning-soft text-warning-foreground",
  urgent: "bg-destructive-soft text-destructive",
};

// ── KanbanCard ─────────────────────────────────────────────────────────────

interface KanbanCardProps {
  card: KanbanCardData;
  columnId: string;
  onDragStart: (e: React.DragEvent, cardId: string, fromColumnId: string) => void;
}

function KanbanCard({ card, columnId, onDragStart }: KanbanCardProps) {
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, card.id, columnId)}
      className="rounded-lg border border-border bg-card p-3 shadow-sm cursor-grab active:cursor-grabbing hover:shadow-md transition-shadow select-none"
    >
      <p className="text-sm font-medium text-foreground mb-2">{card.title}</p>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {card.priority && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${PRIORITY_COLORS[card.priority]}`}
            >
              {card.priority}
            </span>
          )}
          {card.dueDate && (
            <span className="text-xs text-muted-foreground">{card.dueDate}</span>
          )}
        </div>
        {card.assigneeInitials && (
          <span className="inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
            {card.assigneeInitials.slice(0, 2).toUpperCase()}
          </span>
        )}
      </div>
    </div>
  );
}

// ── KanbanColumn ───────────────────────────────────────────────────────────

interface KanbanColumnProps {
  column: KanbanColumnData;
  onDragStart: (e: React.DragEvent, cardId: string, fromColumnId: string) => void;
  onDrop: (e: React.DragEvent, toColumnId: string) => void;
  onDragOver: (e: React.DragEvent) => void;
}

function KanbanColumn({ column, onDragStart, onDrop, onDragOver }: KanbanColumnProps) {
  const [isDragOver, setIsDragOver] = useState(false);

  return (
    <div
      className={`flex w-72 flex-shrink-0 flex-col rounded-xl border-2 ${
        isDragOver ? "border-primary bg-accent" : "border-border bg-muted"
      } transition-colors`}
      onDragOver={(e) => {
        onDragOver(e);
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={(e) => {
        setIsDragOver(false);
        onDrop(e, column.id);
      }}
    >
      {/* Column header */}
      <div
        className="flex items-center justify-between rounded-t-xl px-4 py-3"
        style={{ backgroundColor: column.color || "var(--muted)" }}
      >
        <h3 className="text-sm font-semibold text-foreground">{column.title}</h3>
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-card px-1.5 text-xs font-bold text-foreground shadow-sm">
          {column.cards.length}
        </span>
      </div>

      {/* Cards */}
      <div className="flex flex-1 flex-col gap-2 p-3 min-h-[120px]">
        {column.cards.map((card) => (
          <KanbanCard
            key={card.id}
            card={card}
            columnId={column.id}
            onDragStart={onDragStart}
          />
        ))}
      </div>
    </div>
  );
}

// ── KanbanBoard ────────────────────────────────────────────────────────────

export function KanbanBoard({ columns, onCardMove }: KanbanBoardProps) {
  const dragRef = React.useRef<{ cardId: string; fromColumnId: string } | null>(null);

  function handleDragStart(
    e: React.DragEvent,
    cardId: string,
    fromColumnId: string
  ) {
    dragRef.current = { cardId, fromColumnId };
    e.dataTransfer.effectAllowed = "move";
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }

  function handleDrop(e: React.DragEvent, toColumnId: string) {
    e.preventDefault();
    if (!dragRef.current) return;
    const { cardId, fromColumnId } = dragRef.current;
    if (fromColumnId !== toColumnId) {
      onCardMove(cardId, fromColumnId, toColumnId);
    }
    dragRef.current = null;
  }

  return (
    <div className="flex gap-4 overflow-x-auto pb-4">
      {columns.map((column) => (
        <KanbanColumn
          key={column.id}
          column={column}
          onDragStart={handleDragStart}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
        />
      ))}
    </div>
  );
}

export default KanbanBoard;
'''

# ---------------------------------------------------------------------------
# CommandPalette.tsx — Cmd+K palette with keyboard navigation
# ---------------------------------------------------------------------------

COMMAND_PALETTE_COMPONENT = '''\
import React, { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Search } from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────

export interface CommandItem {
  id: string;
  label: string;
  group: "Navigation" | "Actions" | "Recent" | string;
  shortcut?: string;
  onSelect: () => void;
}

interface CommandPaletteProps {
  items: CommandItem[];
}

// ── Helpers ────────────────────────────────────────────────────────────────

function groupBy<T>(arr: T[], key: (item: T) => string): Record<string, T[]> {
  return arr.reduce<Record<string, T[]>>((acc, item) => {
    const k = key(item);
    (acc[k] = acc[k] || []).push(item);
    return acc;
  }, {});
}

// ── CommandPalette ─────────────────────────────────────────────────────────

export function CommandPalette({ items }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Global Cmd+K / Ctrl+K shortcut
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setQuery("");
      setActiveIndex(0);
    }
  }, [open]);

  const filtered = query
    ? items.filter((item) =>
        item.label.toLowerCase().includes(query.toLowerCase())
      )
    : items;

  const grouped = groupBy(filtered, (item) => item.group);
  const groupOrder = ["Navigation", "Actions", "Recent"].filter(
    (g) => grouped[g]
  );
  // Append any extra groups not in the ordered list
  Object.keys(grouped).forEach((g) => {
    if (!groupOrder.includes(g)) groupOrder.push(g);
  });

  // Flat list for keyboard navigation
  const flatItems = groupOrder.flatMap((g) => grouped[g] || []);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, flatItems.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = flatItems[activeIndex];
      if (item) {
        item.onSelect();
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  // Scroll active item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-active="true"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  let flatIndex = 0;

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50" />
        <Dialog.Content className="fixed left-1/2 top-[20vh] z-50 w-full max-w-xl -translate-x-1/2 rounded-xl border border-border bg-card shadow-2xl focus:outline-none">
          <Dialog.Title className="sr-only">Command Palette</Dialog.Title>

          {/* Search input */}
          <div className="flex items-center gap-3 border-b px-4 py-3">
            <Search className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={handleKeyDown}
              placeholder="Type a command or search..."
              className="flex-1 bg-transparent text-sm text-foreground placeholder-muted-foreground outline-none"
            />
            <kbd className="hidden rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground sm:inline-flex">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div ref={listRef} className="max-h-80 overflow-y-auto py-2">
            {flatItems.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                No results for &ldquo;{query}&rdquo;
              </p>
            ) : (
              groupOrder.map((group) => {
                const groupItems = grouped[group] || [];
                return (
                  <div key={group}>
                    <p className="px-4 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      {group}
                    </p>
                    {groupItems.map((item) => {
                      const idx = flatIndex++;
                      const isActive = idx === activeIndex;
                      return (
                        <button
                          key={item.id}
                          data-active={isActive}
                          onClick={() => {
                            item.onSelect();
                            setOpen(false);
                          }}
                          onMouseEnter={() => setActiveIndex(idx)}
                          className={`flex w-full items-center justify-between px-4 py-2 text-sm ${
                            isActive
                              ? "bg-primary text-primary-foreground"
                              : "text-foreground hover:bg-muted"
                          }`}
                        >
                          <span>{item.label}</span>
                          {item.shortcut && (
                            <kbd
                              className={`rounded border px-1.5 py-0.5 text-xs ${
                                isActive
                                  ? "border-primary text-primary"
                                  : "border-border text-muted-foreground"
                              }`}
                            >
                              {item.shortcut}
                            </kbd>
                          )}
                        </button>
                      );
                    })}
                  </div>
                );
              })
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default CommandPalette;
'''
