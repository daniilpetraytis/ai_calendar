"use client";

import { useMemo, useState } from "react";

import { Proposal } from "@/lib/api";
import { cn } from "@/lib/cn";

function fmt(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  });
}

const OP_LABEL: Record<string, string> = {
  create: "Create",
  move: "Move",
  update: "Update",
  delete: "Delete",
  skip: "Skip",
};

const OP_COLOR: Record<string, string> = {
  create: "border-success/40 text-success",
  move: "border-accent/40 text-accent",
  update: "border-accent/40 text-accent",
  delete: "border-danger/40 text-danger",
  skip: "border-muted/40 text-muted",
};

export function ProposalDiff({
  proposal,
  onApprove,
  onReject,
}: {
  proposal: Proposal;
  onApprove: (acceptedIndices: number[] | null) => void;
  onReject: () => void;
}) {
  const applicable = useMemo(
    () =>
      proposal.changes
        .map((c, idx) => ({ c, idx }))
        .filter(({ c }) => c.op !== "skip"),
    [proposal.changes],
  );

  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(applicable.map(({ idx }) => idx)),
  );

  const toggle = (idx: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });

  const acceptedArray = useMemo(
    () => Array.from(selected).sort((a, b) => a - b),
    [selected],
  );

  return (
    <div className="rounded-md border border-accent/40 bg-accent/5 p-3 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-medium text-text">Proposed changes</div>
        <div className="text-muted">{proposal.summary}</div>
      </div>
      <ul className="space-y-1.5">
        {proposal.changes.map((c, idx) => {
          const isApplicable = c.op !== "skip";
          return (
            <li
              key={idx}
              className={cn(
                "flex items-start gap-2 rounded border border-border bg-bg p-2",
                !isApplicable && "opacity-60",
              )}
            >
              <input
                type="checkbox"
                disabled={!isApplicable}
                checked={isApplicable && selected.has(idx)}
                onChange={() => toggle(idx)}
                className="mt-1"
              />
              <div className="flex-1 space-y-0.5">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
                      OP_COLOR[c.op] ?? "border-border text-muted",
                    )}
                  >
                    {OP_LABEL[c.op] ?? c.op}
                  </span>
                  <span className="text-text">{c.title}</span>
                </div>
                <div className="text-muted">
                  {c.new_start_iso ? (
                    <>
                      → {fmt(c.new_start_iso)} – {fmt(c.new_end_iso)}
                    </>
                  ) : (
                    <span>{c.reason ?? "—"}</span>
                  )}
                </div>
                {c.reason && c.new_start_iso && (
                  <div className="text-[10px] text-muted">{c.reason}</div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex items-center justify-end gap-2">
        <button
          onClick={onReject}
          className="rounded-md border border-border bg-panel px-3 py-1 text-muted hover:text-danger"
        >
          Reject all
        </button>
        <button
          onClick={() => onApprove(acceptedArray.length === applicable.length ? null : acceptedArray)}
          disabled={selected.size === 0}
          className="rounded-md bg-accent px-3 py-1 font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          Apply selected ({selected.size})
        </button>
      </div>
    </div>
  );
}
