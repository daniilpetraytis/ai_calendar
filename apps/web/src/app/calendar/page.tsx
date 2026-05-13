"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import { EventClickArg, EventContentArg } from "@fullcalendar/core";
import { useSearchParams } from "next/navigation";

import {
  Category,
  disconnectYandex,
  EventDTO,
  getIntegrationsStatus,
  IntegrationsStatus,
  listCategories,
  listEvents,
  listTasks,
  patchEventCategory,
  scheduleTask,
  syncCalendar,
} from "@/lib/api";
import { ChatPanel } from "@/components/chat-panel";
import { TasksDrawer } from "@/components/tasks-drawer";
import { YandexConnectModal } from "@/components/yandex-connect-modal";
import { EventPopover } from "@/components/event-popover";
import { RecoveryWidget } from "@/components/recovery-widget";

interface PopoverState {
  event: EventDTO;
  position: { x: number; y: number };
}

function CalendarPageInner() {
  const search = useSearchParams();
  const justConnected = search.get("connected");

  const [events, setEvents] = useState<EventDTO[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationsStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [yandexOpen, setYandexOpen] = useState(false);
  const [popover, setPopover] = useState<PopoverState | null>(null);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const calendarRef = useRef<FullCalendar | null>(null);

  const [viewRange, setViewRange] = useState<{ start: Date; end: Date } | null>(
    null,
  );

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [eventsResp, status, cats, pendingTasks] = await Promise.all([
        viewRange
          ? listEvents(viewRange.start, viewRange.end)
          : listEvents(),
        getIntegrationsStatus(),
        listCategories(),
        listTasks("pending").catch(() => []),
      ]);
      setEvents(eventsResp);
      setIntegrations(status);
      setCategories(cats);
      setPendingCount(pendingTasks.length);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [viewRange]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Build a fast color lookup map from category name → color
  const categoryColorMap = useMemo(
    () => new Map(categories.map((c) => [c.name, c.color])),
    [categories],
  );

  const fcEvents = useMemo(
    () =>
      events.map((e) => {
        const color = categoryColorMap.get(e.category ?? "") ?? "#7c5cff";
        return {
          id: e.id,
          title: e.title,
          start: e.start_at,
          end: e.end_at,
          allDay: e.all_day,
          backgroundColor: color + "cc",
          borderColor: color,
          extendedProps: { source: e.source, priority: e.priority, eventData: e },
        };
      }),
    [events, categoryColorMap],
  );

  const renderEvent = (arg: EventContentArg) => {
    const isTimeGrid = arg.view.type.startsWith("timeGrid");
    if (!isTimeGrid || arg.event.allDay) return undefined;
    return (
      <div className="flex h-full w-full flex-col overflow-hidden leading-tight">
        <div className="text-[10px] font-semibold opacity-80">{arg.timeText}</div>
        <div className="text-[11px] font-medium" style={{ overflowWrap: "anywhere" }}>
          {arg.event.title}
        </div>
      </div>
    );
  };

  const handleEventClick = (arg: EventClickArg) => {
    const eventData = arg.event.extendedProps.eventData as EventDTO;
    const rect = arg.el.getBoundingClientRect();
    setPopover({
      event: eventData,
      position: { x: rect.left, y: rect.bottom },
    });
  };

  const handleCategoryChange = async (eventId: string, category: string) => {
    try {
      const updated = await patchEventCategory(eventId, category);
      setEvents((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const yandexConnected = integrations?.yandex_calendar?.connected ?? false;
  const anyConnected = yandexConnected;

  const connectionLabel = () => {
    if (yandexConnected) {
      return `Яндекс: ${integrations?.yandex_calendar?.account_email ?? "—"}`;
    }
    return "Внешний календарь не подключён — события создаются локально.";
  };

  const handleExternalDrop = useCallback(
    async (info: { date: Date; draggedEl: HTMLElement }) => {
      const taskId = info.draggedEl.getAttribute("data-task-id");
      if (!taskId) return;
      try {
        await scheduleTask(taskId, info.date);
        await reload();
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [reload],
  );

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <section className="rounded-lg border border-border bg-panel p-4">
        <header className="mb-3 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Calendar</h1>
            <p className="text-xs text-muted">
              {connectionLabel()}
              {justConnected && (
                <span className="ml-2 text-success">
                  Подключено ({justConnected}) — синкаем.
                </span>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setTasksOpen(true)}
              className="relative rounded-md border border-border bg-bg px-3 py-1.5 text-sm hover:bg-border"
              title="Открыть задачи (drag-and-drop на календарь)"
            >
              Tasks
              {pendingCount > 0 && (
                <span className="ml-1.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white">
                  {pendingCount}
                </span>
              )}
            </button>
            {anyConnected ? (
              <>
                <button
                  className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm hover:bg-border"
                  onClick={async () => {
                    setLoading(true);
                    try {
                      await syncCalendar();
                      await reload();
                    } catch (err) {
                      setError((err as Error).message);
                    } finally {
                      setLoading(false);
                    }
                  }}
                >
                  Sync
                </button>
                {yandexConnected && (
                  <button
                    className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm text-muted hover:text-danger"
                    onClick={async () => {
                      if (!confirm("Отключить Яндекс?")) return;
                      await disconnectYandex();
                      await reload();
                    }}
                  >
                    Отключить Яндекс
                  </button>
                )}
              </>
            ) : (
              <button
                className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
                onClick={() => setYandexOpen(true)}
              >
                Подключить Яндекс Календарь
              </button>
            )}
          </div>
        </header>

        {error && (
          <div className="mb-3 rounded-md border border-danger/40 bg-danger/10 p-2 text-sm text-danger">
            {error}
          </div>
        )}

        <RecoveryWidget />

        <FullCalendar
          ref={calendarRef}
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView="timeGridWeek"
          headerToolbar={{
            left: "prev,next today",
            center: "title",
            right: "dayGridMonth,timeGridWeek,timeGridDay",
          }}
          events={fcEvents}
          height="calc(100vh - 11rem)"
          editable={false}
          droppable={true}
          drop={(info) => {
            void handleExternalDrop(info);
          }}
          nowIndicator
          slotMinTime="00:00:00"
          slotMaxTime="24:00:00"
          scrollTime="07:00:00"
          slotDuration="00:30:00"
          slotLabelInterval="01:00:00"
          slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          dayMaxEvents
          eventContent={renderEvent}
          eventClick={handleEventClick}
          datesSet={(arg) => {
            setViewRange((prev) => {
              if (
                prev &&
                prev.start.getTime() === arg.start.getTime() &&
                prev.end.getTime() === arg.end.getTime()
              ) {
                return prev;
              }
              return { start: arg.start, end: arg.end };
            });
          }}
        />
        {loading && <div className="mt-2 text-xs text-muted">Loading…</div>}
      </section>

      <aside className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)]">
        <ChatPanel onApplied={reload} />
      </aside>

      <TasksDrawer
        open={tasksOpen}
        onClose={() => setTasksOpen(false)}
        onAfterChange={reload}
      />

      <YandexConnectModal
        open={yandexOpen}
        onClose={() => setYandexOpen(false)}
        onConnected={reload}
      />

      {popover && (
        <EventPopover
          event={popover.event}
          position={popover.position}
          categories={categories}
          onCategoryChange={handleCategoryChange}
          onClose={() => setPopover(null)}
        />
      )}
    </div>
  );
}

export default function CalendarPage() {
  return (
    <Suspense>
      <CalendarPageInner />
    </Suspense>
  );
}
