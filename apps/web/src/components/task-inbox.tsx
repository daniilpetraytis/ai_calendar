"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Draggable } from "@fullcalendar/interaction";

import {
  completeTask as apiComplete,
  createTask,
  deferTask,
  deleteTask,
  FocusKind,
  listTasks,
  runScheduler,
  SchedulerProposalDTO,
  TaskCreateInput,
  TaskDTO,
} from "@/lib/api";
import { cn } from "@/lib/cn";

export function TaskInbox({
  onAfterChange,
}: {
  onAfterChange: () => void | Promise<void>;
}) {
  const [tasks, setTasks] = useState<TaskDTO[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"pending" | "scheduled" | "done">(
    "pending",
  );
  const [planning, setPlanning] = useState(false);
  const [proposal, setProposal] = useState<SchedulerProposalDTO | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const draggableRef = useRef<Draggable | null>(null);

  const reload = useCallback(async () => {
    try {
      const rows = await listTasks(filter);
      setTasks(rows);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [filter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (!listRef.current) return;
    draggableRef.current?.destroy();
    draggableRef.current = new Draggable(listRef.current, {
      itemSelector: ".task-card",
      eventData: (el) => {
        const title = el.getAttribute("data-task-title") ?? "Task";
        const duration = Number(el.getAttribute("data-task-duration") ?? 30);
        return {
          title,
          duration: { minutes: duration },
        };
      },
    });
    return () => {
      draggableRef.current?.destroy();
      draggableRef.current = null;
    };
  }, [tasks]);

  const pendingCount = useMemo(
    () => tasks.filter((t) => t.status === "pending").length,
    [tasks],
  );

  const handleComplete = async (task: TaskDTO) => {
    setBusy(task.id);
    try {
      await apiComplete(task.id);
      await reload();
      await onAfterChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const handleDefer = async (task: TaskDTO) => {
    setBusy(task.id);
    try {
      await deferTask(task.id);
      await reload();
      await onAfterChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async (task: TaskDTO) => {
    if (!confirm(`Удалить задачу «${task.title}»?`)) return;
    setBusy(task.id);
    try {
      await deleteTask(task.id);
      await reload();
      await onAfterChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const planWeek = async () => {
    setPlanning(true);
    setError(null);
    try {
      const resp = await runScheduler(7, false);
      setProposal(resp.proposal);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPlanning(false);
    }
  };

  const applyProposal = async () => {
    setPlanning(true);
    try {
      await runScheduler(7, true);
      setProposal(null);
      await reload();
      await onAfterChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPlanning(false);
    }
  };

  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-panel p-3">
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">Tasks</h2>
          <p className="text-[11px] text-muted">
            {pendingCount} в очереди · перетащи на календарь, чтобы запланировать
          </p>
        </div>
        <button
          onClick={planWeek}
          disabled={planning || filter !== "pending" || tasks.length === 0}
          className="rounded-md bg-accent px-2.5 py-1 text-[11px] font-medium text-white disabled:opacity-50"
          title="Auto-schedule all pending tasks for the next 7 days"
        >
          {planning ? "…" : "Plan week"}
        </button>
      </header>

      <div className="mb-2 flex gap-1 text-[11px]">
        {(["pending", "scheduled", "done"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "rounded-md border px-2 py-0.5",
              filter === f
                ? "border-accent bg-accent/10 text-accent"
                : "border-border text-muted hover:text-text",
            )}
          >
            {f}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-2 rounded border border-danger/40 bg-danger/10 p-1.5 text-[11px] text-danger">
          {error}
        </div>
      )}

      {proposal && (
        <SchedulerProposalCard
          proposal={proposal}
          onApply={applyProposal}
          onCancel={() => setProposal(null)}
          busy={planning}
        />
      )}

      <NewTaskInline
        open={creating}
        onCancel={() => setCreating(false)}
        onCreated={async () => {
          setCreating(false);
          await reload();
          await onAfterChange();
        }}
      />

      {!creating && (
        <button
          onClick={() => setCreating(true)}
          className="mb-2 rounded-md border border-dashed border-border px-2 py-1 text-[11px] text-muted hover:border-accent hover:text-accent"
        >
          + Новая задача
        </button>
      )}

      <div
        ref={listRef}
        className="flex-1 space-y-1.5 overflow-y-auto pr-1"
      >
        {tasks.length === 0 && (
          <p className="py-4 text-center text-[11px] text-muted">
            Пусто. Добавь задачу выше или попроси агента.
          </p>
        )}
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            busy={busy === task.id}
            onComplete={() => handleComplete(task)}
            onDefer={() => handleDefer(task)}
            onDelete={() => handleDelete(task)}
          />
        ))}
      </div>
    </div>
  );
}

function focusKindStyle(kind: FocusKind): string {
  switch (kind) {
    case "deep":
      return "border-l-purple-400";
    case "shallow":
      return "border-l-sky-400";
    case "admin":
      return "border-l-amber-400";
  }
}

function fmtDuration(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

function fmtDeadline(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function TaskCard({
  task,
  busy,
  onComplete,
  onDefer,
  onDelete,
}: {
  task: TaskDTO;
  busy: boolean;
  onComplete: () => void;
  onDefer: () => void;
  onDelete: () => void;
}) {
  const isPending = task.status === "pending";
  return (
    <div
      data-task-id={task.id}
      data-task-title={task.title}
      data-task-duration={task.duration_minutes}
      data-task-focus={task.focus_required}
      className={cn(
        "task-card group rounded-md border border-border bg-bg p-2 text-xs",
        "border-l-4",
        focusKindStyle(task.focus_required),
        isPending && "cursor-grab active:cursor-grabbing",
        busy && "opacity-50",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium text-text">{task.title}</span>
        <span className="shrink-0 text-[10px] text-muted">
          {fmtDuration(task.duration_minutes)}
        </span>
      </div>
      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted">
        <span className="uppercase tracking-wider">{task.focus_required}</span>
        <span>· prio {task.priority}</span>
        {task.deadline_at && (
          <span className="text-danger/80">
            · do {fmtDeadline(task.deadline_at)}
          </span>
        )}
      </div>
      <div className="mt-1.5 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        {isPending && (
          <button
            onClick={onComplete}
            disabled={busy}
            className="rounded border border-border bg-panel px-1.5 py-0.5 text-[10px] hover:text-success disabled:opacity-50"
          >
            ✓ done
          </button>
        )}
        {task.status === "scheduled" && (
          <button
            onClick={onDefer}
            disabled={busy}
            className="rounded border border-border bg-panel px-1.5 py-0.5 text-[10px] hover:text-accent disabled:opacity-50"
          >
            ↩ defer
          </button>
        )}
        <button
          onClick={onDelete}
          disabled={busy}
          className="rounded border border-border bg-panel px-1.5 py-0.5 text-[10px] hover:text-danger disabled:opacity-50"
        >
          delete
        </button>
      </div>
    </div>
  );
}

function NewTaskInline({
  open,
  onCancel,
  onCreated,
}: {
  open: boolean;
  onCancel: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [duration, setDuration] = useState("30");
  const [focus, setFocus] = useState<FocusKind>("shallow");
  const [deadline, setDeadline] = useState("");
  const [priority, setPriority] = useState("5");
  const [autoSchedule, setAutoSchedule] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setTitle("");
      setDuration("30");
      setFocus("shallow");
      setDeadline("");
      setPriority("5");
      setAutoSchedule(true);
      setErr(null);
    }
  }, [open]);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setSubmitting(true);
    setErr(null);
    try {
      const body: TaskCreateInput = {
        title: title.trim(),
        duration_minutes: Number(duration) || 30,
        focus_required: focus,
        priority: Number(priority) || 5,
        auto_schedule: autoSchedule,
      };
      if (deadline) {
        body.deadline_at = new Date(deadline).toISOString();
      }
      await createTask(body);
      onCreated();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="mb-2 space-y-1.5 rounded-md border border-accent/40 bg-bg p-2"
    >
      <input
        placeholder="Что нужно сделать?"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
        className="w-full rounded border border-border bg-panel px-2 py-1 text-xs"
      />
      <div className="grid grid-cols-3 gap-1.5 text-[11px]">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted">Длительность (мин)</span>
          <input
            type="number"
            min="5"
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            className="rounded border border-border bg-panel px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted">Фокус</span>
          <select
            value={focus}
            onChange={(e) => setFocus(e.target.value as FocusKind)}
            className="rounded border border-border bg-panel px-2 py-1"
          >
            <option value="deep">deep</option>
            <option value="shallow">shallow</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted">Prio (0–10)</span>
          <input
            type="number"
            min="0"
            max="10"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="rounded border border-border bg-panel px-2 py-1"
          />
        </label>
      </div>
      <label className="flex flex-col gap-0.5 text-[11px]">
        <span className="text-[10px] text-muted">Дедлайн (опционально)</span>
        <input
          type="datetime-local"
          value={deadline}
          onChange={(e) => setDeadline(e.target.value)}
          className="rounded border border-border bg-panel px-2 py-1"
        />
      </label>
      <label className="flex items-center gap-1.5 text-[11px] text-muted">
        <input
          type="checkbox"
          checked={autoSchedule}
          onChange={(e) => setAutoSchedule(e.target.checked)}
        />
        Сразу запланировать (auto-schedule)
      </label>
      {err && <p className="text-[10px] text-danger">{err}</p>}
      <div className="flex justify-end gap-1.5">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-border px-2 py-0.5 text-[11px] text-muted"
        >
          Отмена
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-accent px-2 py-0.5 text-[11px] text-white disabled:opacity-50"
        >
          {submitting ? "…" : "Создать"}
        </button>
      </div>
    </form>
  );
}

function SchedulerProposalCard({
  proposal,
  onApply,
  onCancel,
  busy,
}: {
  proposal: SchedulerProposalDTO;
  onApply: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div className="mb-2 rounded-md border border-accent/40 bg-accent/5 p-2 text-[11px]">
      <div className="mb-1 font-medium">{proposal.summary}</div>
      <ul className="mb-2 space-y-0.5 text-muted">
        {proposal.changes.slice(0, 6).map((c, i) => (
          <li key={i}>
            <span className="text-text">{c.title}</span>
            {" — "}
            {new Date(c.new_start_iso).toLocaleString(undefined, {
              weekday: "short",
              hour: "2-digit",
              minute: "2-digit",
              month: "short",
              day: "numeric",
            })}
          </li>
        ))}
        {proposal.changes.length > 6 && (
          <li>и ещё {proposal.changes.length - 6}…</li>
        )}
        {proposal.unscheduled.length > 0 && (
          <li className="mt-1 text-danger">
            {proposal.unscheduled.length} не поместилось
          </li>
        )}
      </ul>
      <div className="flex justify-end gap-1.5">
        <button
          onClick={onCancel}
          disabled={busy}
          className="rounded border border-border px-2 py-0.5 text-[11px] text-muted hover:text-danger"
        >
          Cancel
        </button>
        <button
          onClick={onApply}
          disabled={busy || proposal.changes.length === 0}
          className="rounded bg-accent px-2 py-0.5 text-[11px] text-white disabled:opacity-50"
        >
          Apply all
        </button>
      </div>
    </div>
  );
}
