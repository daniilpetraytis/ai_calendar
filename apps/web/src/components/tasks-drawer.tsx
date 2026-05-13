"use client";

import { useEffect } from "react";

import { TaskInbox } from "@/components/task-inbox";
import { cn } from "@/lib/cn";

export function TasksDrawer({
  open,
  onClose,
  onAfterChange,
}: {
  open: boolean;
  onClose: () => void;
  onAfterChange: () => void | Promise<void>;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const handlePointerDown = (e: React.PointerEvent<HTMLElement>) => {
    const target = e.target as HTMLElement;
    const card = target.closest(".task-card");
    if (!card) return;
    if (target.closest("button, input, select, textarea, label")) return;
    const startX = e.clientX;
    const startY = e.clientY;
    const onMove = (m: PointerEvent) => {
      if (Math.abs(m.clientX - startX) + Math.abs(m.clientY - startY) > 6) {
        cleanup();
        onClose();
      }
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", cleanup);
      window.removeEventListener("pointercancel", cleanup);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", cleanup);
    window.addEventListener("pointercancel", cleanup);
  };

  return (
    <>
      <div
        aria-hidden={!open}
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-30 bg-black/40 backdrop-blur-sm transition-opacity duration-200",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      />
      <aside
        role="dialog"
        aria-label="Tasks"
        aria-hidden={!open}
        onPointerDown={handlePointerDown}
        className={cn(
          "fixed right-0 top-0 z-40 flex h-screen w-[360px] max-w-[92vw] transform flex-col border-l border-border bg-panel shadow-2xl transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <button
          onClick={onClose}
          aria-label="Close tasks"
          className="absolute right-2 top-2 z-10 rounded-md border border-border bg-bg/80 px-2 py-0.5 text-xs text-muted hover:text-text"
        >
          ✕
        </button>
        <div className="min-h-0 flex-1 p-3">
          <TaskInbox onAfterChange={onAfterChange} />
        </div>
      </aside>
    </>
  );
}
