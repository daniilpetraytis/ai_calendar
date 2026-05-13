"use client";

import { fetchEventSource } from "@microsoft/fetch-event-source";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const DEV_USER_EMAIL =
  process.env.NEXT_PUBLIC_DEV_USER_EMAIL ?? "demo@example.com";

const AUTH_PROVIDER = process.env.NEXT_PUBLIC_AUTH_PROVIDER ?? "clerk";

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

type ClerkInstance = {
  loaded?: boolean;
  session?: { getToken: () => Promise<string | null> } | null;
};

async function waitForClerk(timeoutMs = 8000): Promise<ClerkInstance | null> {
  if (typeof window === "undefined") return null;
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const clerk = (window as unknown as { Clerk?: ClerkInstance }).Clerk;
    if (clerk?.loaded) return clerk;
    await new Promise((r) => setTimeout(r, 50));
  }
  return (window as unknown as { Clerk?: ClerkInstance }).Clerk ?? null;
}

async function clerkBearerToken(): Promise<string | null> {
  const clerk = await waitForClerk();
  if (!clerk?.session?.getToken) return null;
  try {
    return await clerk.session.getToken();
  } catch {
    return null;
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    "X-User-Timezone": browserTimezone(),
  };
  if (AUTH_PROVIDER === "clerk") {
    const token = await clerkBearerToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  } else {
    headers["X-Dev-User-Email"] = DEV_USER_EMAIL;
  }
  return headers;
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
      ...(init.headers as Record<string, string> | undefined),
    },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`API ${path} failed: ${resp.status} ${text}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export type EventDTO = {
  id: string;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string;
  all_day: boolean;
  source: "yandex" | "local";
  is_movable: boolean;
  priority: number;
  category: string | null;
  category_source: string | null;
};

export type Category = {
  name: string;
  color: string;
  emoji: string | null;
  goal_minutes_per_week: number | null;
  is_default: boolean;
};

export type CategoryStatItem = {
  category: string;
  minutes: number;
  color: string;
  emoji: string | null;
  goal_minutes_per_week: number | null;
};

export type StatsByCategory = {
  period_label: string;
  period_start: string;
  period_end: string;
  total_minutes: number;
  by_category: CategoryStatItem[];
};

export type HeatmapCell = {
  day: number;
  hour: number;
  minutes: number;
};

export type HeatmapData = {
  period_label: string;
  cells: HeatmapCell[];
};

export type TrendItem = {
  category: string;
  color: string;
  emoji: string | null;
  current_minutes: number;
  previous_minutes: number;
  delta_minutes: number;
  delta_pct: number | null;
};

export type TrendsData = {
  period_label: string;
  previous_label: string;
  items: TrendItem[];
};

export type IntegrationsStatus = Record<
  string,
  {
    connected: boolean;
    account_email?: string | null;
    expires_at?: string | null;
    telegram_user_id?: number | null;
  }
>;

export type ProposedChange = {
  op: "create" | "move" | "update" | "delete" | "skip";
  kind?: "event" | "task";
  id?: string | null;
  title: string;
  new_start_iso?: string | null;
  new_end_iso?: string | null;
  reason?: string | null;
};

export type Proposal = {
  summary: string;
  changes: ProposedChange[];
  unscheduled?: { id: string; kind: string; title: string }[];
};

export async function listEvents(start?: Date, end?: Date) {
  const params = new URLSearchParams();
  if (start) params.set("start", start.toISOString());
  if (end) params.set("end", end.toISOString());
  return api<EventDTO[]>(`/events?${params.toString()}`);
}

export async function syncCalendar() {
  return api<{ upserted: number }>("/events/sync", { method: "POST" });
}

export async function getIntegrationsStatus() {
  return api<IntegrationsStatus>("/integrations/status");
}

export type Me = {
  id: string;
  email: string;
  display_name: string | null;
  timezone: string;
  onboarded_at: string | null;
};

export async function getMe(): Promise<Me> {
  return api<Me>("/me");
}

export async function completeOnboarding(): Promise<Me> {
  return api<Me>("/me/onboarding/complete", { method: "POST" });
}

export async function connectYandex(email: string, appPassword: string) {
  return api<{ ok: boolean; calendar_url: string; sync_warning?: string }>(
    "/integrations/yandex/connect",
    {
      method: "POST",
      body: JSON.stringify({ email, app_password: appPassword }),
    },
  );
}

export async function disconnectYandex() {
  return api<{ ok: boolean }>("/integrations/yandex", { method: "DELETE" });
}

export async function startTelegramConnect() {
  return api<{ deeplink: string; expires_in_minutes: string }>(
    "/integrations/telegram/connect",
    { method: "POST" },
  );
}

export async function disconnectTelegram() {
  return api<{ ok: boolean }>("/integrations/telegram", { method: "DELETE" });
}

export async function startWhoopConnect() {
  return api<{ authorize_url: string }>("/integrations/whoop/connect");
}

export async function disconnectWhoop() {
  return api<{ ok: boolean }>("/integrations/whoop", { method: "DELETE" });
}

export type RecoveryBand = "red" | "yellow" | "green";

export type BiometricsTodayDTO = {
  available: boolean;
  date: string | null;
  recovery_score: number | null;
  recovery_band: RecoveryBand | null;
  hrv_rmssd_ms: number | null;
  resting_heart_rate: number | null;
  sleep_performance: number | null;
  sleep_hours: number | null;
  strain: number | null;
  last_synced_at: string | null;
};

export type BiometricsHistoryItem = {
  date: string;
  recovery_score: number | null;
  recovery_band: RecoveryBand | null;
  strain: number | null;
  sleep_hours: number | null;
};

export type WhoopWorkoutExtra = {
  workout_id: string;
  started_at: string;
  ended_at: string;
  actual_minutes: number;
  sport_id: number | null;
  sport: string;
  strain: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  kilojoule: number | null;
  zones_minutes: Record<string, number>;
  synced_at: string;
  auto_created?: boolean;
};

export type Insight = { title: string; detail: string };

export async function getBiometricsToday(): Promise<BiometricsTodayDTO | null> {
  try {
    return await api<BiometricsTodayDTO>("/biometrics/today");
  } catch (err) {
    // 404 = not connected → swallow so the widget can render gracefully.
    if (err instanceof Error && /\b404\b/.test(err.message)) return null;
    throw err;
  }
}

export async function getBiometricsHistory(days = 14): Promise<BiometricsHistoryItem[]> {
  return api<BiometricsHistoryItem[]>(`/biometrics/history?days=${days}`);
}

export async function postEveningFeedback(
  score: 1 | 2 | 3,
  text?: string,
): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>("/biometrics/evening-feedback", {
    method: "POST",
    body: JSON.stringify({ score, text: text ?? null }),
  });
}

export async function getBiometricsInsights(days = 30): Promise<Insight[]> {
  return api<Insight[]>(`/biometrics/insights?days=${days}`);
}

export type EventWorkoutResponse =
  | ({ available: true } & WhoopWorkoutExtra)
  | { available: false };

export async function getEventWorkout(
  eventId: string,
): Promise<EventWorkoutResponse> {
  return api<EventWorkoutResponse>(`/biometrics/event/${eventId}/workout`);
}

export async function applyProposal(
  runId: string,
  approve: boolean,
  acceptedIndices?: number[],
) {
  return api<{ status: string; applied: number; errors?: unknown[] }>(
    `/replan/${runId}/apply`,
    {
      method: "POST",
      body: JSON.stringify({ approve, accepted_indices: acceptedIndices ?? null }),
    },
  );
}

export async function patchEventCategory(
  id: string,
  category: string,
): Promise<EventDTO> {
  return api<EventDTO>(`/events/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ category }),
  });
}

export async function listCategories(): Promise<Category[]> {
  return api<Category[]>("/categories");
}

export async function updateCategory(
  name: string,
  body: { color?: string; emoji?: string; goal_minutes_per_week?: number | null },
): Promise<Category> {
  return api<Category>(`/categories/${name}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function createCategory(body: {
  name: string;
  color?: string;
  emoji?: string;
  goal_minutes_per_week?: number;
}): Promise<Category> {
  return api<Category>("/categories", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteCategory(name: string): Promise<void> {
  return api<void>(`/categories/${name}`, { method: "DELETE" });
}

export type Place = {
  id: string;
  name: string;
  address: string;
  is_default: boolean;
};

export async function listPlaces(): Promise<Place[]> {
  return api<Place[]>("/places");
}

export async function createPlace(body: {
  name: string;
  address: string;
  is_default?: boolean;
}): Promise<Place> {
  return api<Place>("/places", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updatePlace(
  id: string,
  body: { name?: string; address?: string; is_default?: boolean },
): Promise<Place> {
  return api<Place>(`/places/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deletePlace(id: string): Promise<void> {
  return api<void>(`/places/${id}`, { method: "DELETE" });
}

export type DayCategoryItem = {
  category: string;
  minutes: number;
  color: string;
  emoji: string | null;
};

export type DayStatItem = {
  date: string;
  day_label: string;
  total_minutes: number;
  by_category: DayCategoryItem[];
};

export async function getStatsByDay(
  period: "day" | "week" | "month" = "week",
  offset = 0,
): Promise<DayStatItem[]> {
  return api<DayStatItem[]>(`/stats/by-day?period=${period}&offset=${offset}`);
}

export async function getStatsByCategory(
  period: "day" | "week" | "month" = "week",
  offset = 0,
): Promise<StatsByCategory> {
  return api<StatsByCategory>(
    `/stats/by-category?period=${period}&offset=${offset}`,
  );
}

export async function getHeatmap(
  period: "day" | "week" | "month" = "week",
  offset = 0,
): Promise<HeatmapData> {
  return api<HeatmapData>(`/stats/heatmap?period=${period}&offset=${offset}`);
}

export async function getTrends(
  period: "day" | "week" | "month" = "week",
  offset = -1,
): Promise<TrendsData> {
  return api<TrendsData>(`/stats/trends?period=${period}&offset=${offset}`);
}

export type FocusKind = "deep" | "shallow" | "admin";
export type TaskStatus = "pending" | "scheduled" | "done" | "skipped";

export type TaskDTO = {
  id: string;
  title: string;
  description: string | null;
  duration_minutes: number;
  priority: number;
  deadline_at: string | null;
  earliest_at: string | null;
  status: TaskStatus;
  scheduled_event_id: string | null;
  tags: string[];
  focus_required: FocusKind;
  splittable: boolean;
  min_chunk_minutes: number;
  recurrence_rule: string | null;
  auto_scheduled: boolean;
  location: string | null;
  category: string | null;
  estimated_minutes: number | null;
  completed_at: string | null;
  dependencies: string[];
};

export type TaskCreateInput = {
  title: string;
  description?: string;
  duration_minutes?: number;
  priority?: number;
  deadline_at?: string | null;
  earliest_at?: string | null;
  tags?: string[];
  focus_required?: FocusKind;
  splittable?: boolean;
  min_chunk_minutes?: number;
  location?: string | null;
  category?: string | null;
  estimated_minutes?: number | null;
  auto_schedule?: boolean;
  dependencies?: string[];
};

export type TaskUpdateInput = Partial<TaskCreateInput> & {
  status?: TaskStatus;
};

export async function listTasks(status?: TaskStatus): Promise<TaskDTO[]> {
  const qs = status ? `?status_filter=${status}` : "";
  return api<TaskDTO[]>(`/tasks${qs}`);
}

export async function createTask(body: TaskCreateInput): Promise<TaskDTO> {
  return api<TaskDTO>("/tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateTask(
  id: string,
  body: TaskUpdateInput,
): Promise<TaskDTO> {
  return api<TaskDTO>(`/tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteTask(id: string): Promise<void> {
  return api<void>(`/tasks/${id}`, { method: "DELETE" });
}

export async function completeTask(
  id: string,
  actualDurationMinutes?: number,
): Promise<TaskDTO> {
  return api<TaskDTO>(`/tasks/${id}/complete`, {
    method: "POST",
    body: JSON.stringify({
      actual_duration_minutes: actualDurationMinutes ?? null,
    }),
  });
}

export async function deferTask(
  id: string,
  to?: Date,
  reason?: string,
): Promise<TaskDTO> {
  return api<TaskDTO>(`/tasks/${id}/defer`, {
    method: "POST",
    body: JSON.stringify({
      to_at: to ? to.toISOString() : null,
      reason: reason ?? null,
    }),
  });
}

export async function scheduleTask(
  id: string,
  at?: Date,
): Promise<TaskDTO> {
  return api<TaskDTO>(`/tasks/${id}/schedule`, {
    method: "POST",
    body: JSON.stringify({ at: at ? at.toISOString() : null }),
  });
}

export type WorkingHoursEntry = { start: string; end: string };
export type FocusWindowEntry = {
  start: string;
  end: string;
  kind: FocusKind;
};

export type Preferences = {
  working_hours: Record<string, WorkingHoursEntry | null>;
  focus_windows: FocusWindowEntry[];
  min_break_minutes: number;
  max_continuous_work_minutes: number;
  auto_schedule_enabled: boolean;
  buffer_after_meeting_minutes: number;
};

export async function getPreferences(): Promise<Preferences> {
  return api<Preferences>("/scheduler/preferences");
}

export async function updatePreferences(
  body: Partial<Preferences>,
): Promise<Preferences> {
  return api<Preferences>("/scheduler/preferences", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export type SchedulerChange = {
  op: "create" | "move";
  kind: "task";
  id: string;
  title: string;
  new_start_iso: string;
  new_end_iso: string;
  reason: string | null;
};

export type SchedulerProposalDTO = {
  summary: string;
  changes: SchedulerChange[];
  unscheduled: { id: string; kind: "task"; title: string; reason: string }[];
};

export type SchedulerRunResponse = {
  proposal: SchedulerProposalDTO;
  applied_count: number;
  run_id: string;
  horizon_days: number;
};

export async function runScheduler(
  horizonDays = 7,
  apply = false,
): Promise<SchedulerRunResponse> {
  return api<SchedulerRunResponse>("/scheduler/run", {
    method: "POST",
    body: JSON.stringify({ horizon_days: horizonDays, apply }),
  });
}

export type ChatEvent =
  | { type: "run_started"; payload: { run_id: string; thread_id: string } }
  | { type: "token"; payload: { text: string } }
  | { type: "tool_start"; payload: { name: string; args: Record<string, unknown> } }
  | { type: "tool_end"; payload: { name: string; ok: boolean } }
  | {
      type: "proposal";
      payload: { run_id: string; proposal: Proposal };
    }
  | {
      type: "final";
      payload: { run_id: string; thread_id: string; status: string; message: string };
    }
  | { type: "error"; payload: { message: string } };

export async function streamChat(
  message: string,
  threadId: string | null,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
) {
  const headers = {
    "Content-Type": "application/json",
    ...(await authHeaders()),
    Accept: "text/event-stream",
  };
  await fetchEventSource(`${API_BASE_URL}/api/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, thread_id: threadId }),
    signal,
    onmessage(ev) {
      if (!ev.event) return;
      try {
        onEvent({ type: ev.event as ChatEvent["type"], payload: JSON.parse(ev.data) } as ChatEvent);
      } catch (err) {
        console.error("Bad SSE payload", err, ev);
      }
    },
    onerror(err) {
      throw err;
    },
  });
}
