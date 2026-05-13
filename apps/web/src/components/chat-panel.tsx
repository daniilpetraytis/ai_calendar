"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { applyProposal, ChatEvent, Proposal, streamChat } from "@/lib/api";
import { ProposalDiff } from "@/components/replan-diff";
import { cn } from "@/lib/cn";

type Message =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      text: string;
      runId?: string;
      proposal?: Proposal;
      proposalApplied?: boolean;
      tools: { name: string; ok?: boolean }[];
    };

export function ChatPanel({ onApplied }: { onApplied?: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages]);

  const send = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || streaming) return;
    setInput("");
    setStreaming(true);

    setMessages((m) => [
      ...m,
      { role: "user", text: trimmed },
      { role: "assistant", text: "", tools: [] },
    ]);

    const ctl = new AbortController();
    abortRef.current = ctl;

    const updateAssistant = (
      mut: (m: Extract<Message, { role: "assistant" }>) => Extract<Message, { role: "assistant" }>,
    ) =>
      setMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "assistant") {
            next[i] = mut(next[i] as Extract<Message, { role: "assistant" }>);
            break;
          }
        }
        return next;
      });

    try {
      await streamChat(trimmed, threadId, (evt: ChatEvent) => {
        if (evt.type === "token") {
          updateAssistant((m) => ({ ...m, text: m.text + evt.payload.text }));
        } else if (evt.type === "tool_start") {
          updateAssistant((m) => ({
            ...m,
            tools: [...m.tools, { name: evt.payload.name }],
          }));
        } else if (evt.type === "tool_end") {
          updateAssistant((m) => {
            const tools = [...m.tools];
            for (let i = tools.length - 1; i >= 0; i--) {
              if (tools[i].name === evt.payload.name && tools[i].ok === undefined) {
                tools[i] = { ...tools[i], ok: evt.payload.ok };
                break;
              }
            }
            return { ...m, tools };
          });
        } else if (evt.type === "proposal") {
          updateAssistant((m) => ({
            ...m,
            runId: evt.payload.run_id,
            proposal: evt.payload.proposal,
          }));
        } else if (evt.type === "final") {
          setThreadId(evt.payload.thread_id);
          updateAssistant((m) => ({ ...m, runId: m.runId ?? evt.payload.run_id }));
          onApplied?.();
        } else if (evt.type === "error") {
          updateAssistant((m) => ({ ...m, text: m.text + `\n[error] ${evt.payload.message}` }));
        }
      }, ctl.signal);
    } catch (err) {
      updateAssistant((m) => ({ ...m, text: m.text + `\n[stream error] ${(err as Error).message}` }));
    } finally {
      setStreaming(false);
    }
  }, [input, streaming, threadId, onApplied]);

  const handleApprove = useCallback(
    async (runId: string, acceptedIndices: number[] | null) => {
      try {
        await applyProposal(runId, true, acceptedIndices ?? undefined);
      } finally {
        setMessages((prev) =>
          prev.map((m) =>
            m.role === "assistant" && m.runId === runId
              ? { ...m, proposalApplied: true }
              : m,
          ),
        );
        onApplied?.();
      }
    },
    [onApplied],
  );

  const handleReject = useCallback(
    async (runId: string) => {
      try {
        await applyProposal(runId, false);
      } finally {
        setMessages((prev) =>
          prev.map((m) =>
            m.role === "assistant" && m.runId === runId
              ? { ...m, proposalApplied: true }
              : m,
          ),
        );
      }
    },
    [],
  );

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col rounded-lg border border-border bg-panel">
      <header className="border-b border-border px-4 py-2 text-sm font-medium">Chat</header>
      <div
        ref={scrollRef}
        className="flex-1 space-y-4 overflow-auto px-4 py-3 text-sm"
      >
        {messages.length === 0 && (
          <div className="space-y-2 text-muted">
            <p>Try:</p>
            <ul className="list-disc space-y-1 pl-5 text-xs">
              <li>&quot;что у меня сегодня?&quot;</li>
              <li>&quot;запланируй обед в 13:00 на час&quot;</li>
              <li>
                &quot;у меня встреча с 15 до 17, перепланируй остаток дня&quot;
              </li>
            </ul>
          </div>
        )}
        {messages.map((m, idx) => (
          <div key={idx} className={cn("space-y-2", m.role === "user" ? "text-text" : "text-muted")}>
            <div
              className={cn(
                "whitespace-pre-wrap rounded-md px-3 py-2",
                m.role === "user"
                  ? "bg-bg text-text"
                  : "bg-bg/50 border border-border",
              )}
            >
              <div className="mb-1 text-[10px] uppercase tracking-wider text-muted">
                {m.role}
              </div>
              {m.text || (m.role === "assistant" && streaming ? "…" : "")}
              {m.role === "assistant" && m.tools.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {m.tools.map((t, i) => (
                    <span
                      key={i}
                      className={cn(
                        "rounded border px-1.5 py-0.5 text-[10px]",
                        t.ok === undefined
                          ? "border-warn/40 text-warn"
                          : t.ok
                            ? "border-success/40 text-success"
                            : "border-danger/40 text-danger",
                      )}
                    >
                      {t.name}
                      {t.ok === undefined ? "…" : t.ok ? " ok" : " err"}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {m.role === "assistant" && m.proposal && m.runId && !m.proposalApplied && (
              <ProposalDiff
                proposal={m.proposal}
                onApprove={(indices) => handleApprove(m.runId!, indices)}
                onReject={() => handleReject(m.runId!)}
              />
            )}
            {m.role === "assistant" && m.proposalApplied && (
              <div className="text-xs text-success">Decision recorded.</div>
            )}
          </div>
        ))}
      </div>
      <div className="border-t border-border p-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          rows={2}
          placeholder="Ask the agent…"
          className="w-full resize-none rounded-md border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <div className="mt-2 flex justify-between text-xs">
          <span className="text-muted">
            {streaming ? "thinking…" : "Enter to send · Shift+Enter newline"}
          </span>
          <button
            disabled={streaming || !input.trim()}
            onClick={() => void send()}
            className="rounded-md bg-accent px-3 py-1 font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
