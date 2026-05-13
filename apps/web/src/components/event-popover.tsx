"use client";

import { useEffect, useRef, useState } from "react";
import {
  Category,
  EventDTO,
  EventWorkoutResponse,
  getEventWorkout,
} from "@/lib/api";

interface Props {
  event: EventDTO;
  position: { x: number; y: number };
  categories: Category[];
  onCategoryChange: (eventId: string, category: string) => void;
  onClose: () => void;
}

export function EventPopover({
  event,
  position,
  categories,
  onCategoryChange,
  onClose,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [workout, setWorkout] = useState<EventWorkoutResponse | null>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const now = new Date();
      if (new Date(event.end_at) > now) return;
      try {
        const resp = await getEventWorkout(event.id);
        if (!cancelled && resp.available) setWorkout(resp);
      } catch {
        // Whoop not connected / 404 — silently skip.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [event.id, event.end_at]);

  // Keep popover inside viewport
  const viewportWidth = typeof window !== "undefined" ? window.innerWidth : 1200;
  const viewportHeight = typeof window !== "undefined" ? window.innerHeight : 800;
  const popoverWidth = 240;
  const left = Math.min(position.x, viewportWidth - popoverWidth - 16);
  const top = Math.min(position.y + 8, viewportHeight - 320);

  const start = new Date(event.start_at);
  const end = new Date(event.end_at);
  const duration = Math.round((end.getTime() - start.getTime()) / 60000);
  const durationLabel =
    duration >= 60
      ? `${Math.floor(duration / 60)}h ${duration % 60 > 0 ? (duration % 60) + "m" : ""}`.trim()
      : `${duration}m`;

  const routeRegex = /^(?:Маршрут: )?(https?:\/\/\S+)$/m;
  const routeMatch = event.description?.match(routeRegex);
  const routeUrl = routeMatch?.[1] ?? null;
  const descriptionWithoutRoute = event.description
    ?.split("\n")
    .filter((line) => !line.match(routeRegex))
    .join("\n")
    .trim();

  return (
    <div
      ref={ref}
      className="fixed z-50 w-60 rounded-lg border border-border bg-panel shadow-xl"
      style={{ left, top }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 border-b border-border px-3 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{event.title}</p>
          <p className="mt-0.5 text-xs text-muted">
            {start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            {" – "}
            {end.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            {" · "}
            {durationLabel}
          </p>
        </div>
        <button
          onClick={onClose}
          className="mt-0.5 shrink-0 text-muted hover:text-text"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      {/* Location + route link */}
      {(event.location || routeUrl) && (
        <div className="border-b border-border px-3 py-2 text-xs">
          {event.location && (
            <p className="text-muted">
              <span className="mr-1">📍</span>
              {event.location}
            </p>
          )}
          {routeUrl && (
            <a
              href={routeUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-accent hover:underline"
            >
              🗺️ Маршрут в Яндекс.Картах
            </a>
          )}
          {descriptionWithoutRoute && (
            <p className="mt-1 whitespace-pre-line text-muted">
              {descriptionWithoutRoute}
            </p>
          )}
        </div>
      )}
      {/* Description without location/route (when no location block above) */}
      {!event.location && !routeUrl && descriptionWithoutRoute && (
        <div className="border-b border-border px-3 py-2 text-xs whitespace-pre-line text-muted">
          {descriptionWithoutRoute}
        </div>
      )}

      {workout && workout.available && (
        <div className="border-b border-border px-3 py-2 text-xs">
          <p className="mb-1 flex items-center gap-1.5 font-medium text-text">
            <span>🏋️</span> Whoop workout · {workout.sport}
            {workout.auto_created && (
              <span
                className="rounded-full bg-border px-1.5 py-0.5 text-[10px] font-normal uppercase tracking-wide text-muted"
                title="Событие создано автоматически по записи в Whoop, потому что в календаре не было запланированной тренировки в это время"
              >
                авто
              </span>
            )}
          </p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-muted">
            {workout.strain != null && (
              <span>
                Strain <span className="text-text">{workout.strain.toFixed(1)}</span>
              </span>
            )}
            {workout.actual_minutes != null && (
              <span>
                Длит. <span className="text-text">{workout.actual_minutes}m</span>
              </span>
            )}
            {workout.avg_hr != null && (
              <span>
                Avg HR <span className="text-text">{workout.avg_hr}</span>
              </span>
            )}
            {workout.max_hr != null && (
              <span>
                Max HR <span className="text-text">{workout.max_hr}</span>
              </span>
            )}
            {workout.kilojoule != null && (
              <span>
                kJ <span className="text-text">{Math.round(workout.kilojoule)}</span>
              </span>
            )}
          </div>
        </div>
      )}

      {/* Current category badge */}
      {event.category && (
        <div className="px-3 pt-2 text-xs text-muted">
          Current:{" "}
          {(() => {
            const cat = categories.find((c) => c.name === event.category);
            return (
              <span
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
                style={{ backgroundColor: (cat?.color ?? "#9ca3af") + "33", color: cat?.color ?? "#9ca3af" }}
              >
                {cat?.emoji} {event.category}
              </span>
            );
          })()}
        </div>
      )}

      {/* Category grid */}
      <div className="p-2">
        <p className="mb-1.5 px-1 text-[11px] font-medium uppercase tracking-wider text-muted">
          Set category
        </p>
        <div className="grid grid-cols-2 gap-1">
          {categories.map((cat) => {
            const active = event.category === cat.name;
            return (
              <button
                key={cat.name}
                onClick={() => {
                  onCategoryChange(event.id, cat.name);
                  onClose();
                }}
                className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-border"
                style={
                  active
                    ? { backgroundColor: cat.color + "33", color: cat.color }
                    : {}
                }
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: cat.color }}
                />
                <span className="truncate">
                  {cat.emoji} {cat.name}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
