"use client";

import { useEffect, useState } from "react";

import {
  FocusKind,
  FocusWindowEntry,
  getPreferences,
  Preferences,
  updatePreferences,
  WorkingHoursEntry,
} from "@/lib/api";

const DAY_LABELS: Array<{ key: string; label: string }> = [
  { key: "mon", label: "Пн" },
  { key: "tue", label: "Вт" },
  { key: "wed", label: "Ср" },
  { key: "thu", label: "Чт" },
  { key: "fri", label: "Пт" },
  { key: "sat", label: "Сб" },
  { key: "sun", label: "Вс" },
];

const FOCUS_KIND_LABELS: Record<FocusKind, string> = {
  deep: "Deep work",
  shallow: "Shallow work",
  admin: "Admin",
};

export function PreferencesCard() {
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setPrefs(await getPreferences());
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, []);

  if (!prefs) {
    return (
      <section className="rounded-lg border border-border bg-panel p-4 text-sm">
        <h2 className="mb-2 font-medium">Расписание</h2>
        <p className="text-xs text-muted">
          {error ?? "Загружаем…"}
        </p>
      </section>
    );
  }

  const setDayHours = (
    day: string,
    entry: WorkingHoursEntry | null,
  ) => {
    setPrefs({
      ...prefs,
      working_hours: { ...prefs.working_hours, [day]: entry },
    });
  };

  const setFocusWindow = (idx: number, patch: Partial<FocusWindowEntry>) => {
    const next = [...prefs.focus_windows];
    next[idx] = { ...next[idx], ...patch };
    setPrefs({ ...prefs, focus_windows: next });
  };

  const addFocusWindow = () => {
    setPrefs({
      ...prefs,
      focus_windows: [
        ...prefs.focus_windows,
        { start: "13:00", end: "14:00", kind: "shallow" },
      ],
    });
  };

  const removeFocusWindow = (idx: number) => {
    setPrefs({
      ...prefs,
      focus_windows: prefs.focus_windows.filter((_, i) => i !== idx),
    });
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePreferences(prefs);
      setPrefs(updated);
      setSavedAt(Date.now());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="space-y-4 rounded-lg border border-border bg-panel p-4 text-sm">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="font-medium">Расписание</h2>
          <p className="text-xs text-muted">
            Где автопланировщик может ставить твои задачи
          </p>
        </div>
        <label className="flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={prefs.auto_schedule_enabled}
            onChange={(e) =>
              setPrefs({
                ...prefs,
                auto_schedule_enabled: e.target.checked,
              })
            }
          />
          Auto-schedule
        </label>
      </header>

      <div>
        <h3 className="mb-1.5 text-xs font-medium text-muted uppercase tracking-wider">
          Working hours
        </h3>
        <div className="space-y-1">
          {DAY_LABELS.map(({ key, label }) => {
            const entry = prefs.working_hours[key];
            const enabled = entry != null;
            return (
              <div
                key={key}
                className="grid grid-cols-[3rem_3rem_1fr_1fr] items-center gap-2 text-xs"
              >
                <span>{label}</span>
                <label className="flex items-center gap-1 text-[11px] text-muted">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) =>
                      setDayHours(
                        key,
                        e.target.checked
                          ? entry ?? { start: "09:00", end: "18:00" }
                          : null,
                      )
                    }
                  />
                </label>
                <input
                  type="time"
                  value={entry?.start ?? ""}
                  disabled={!enabled}
                  onChange={(e) =>
                    setDayHours(key, {
                      start: e.target.value,
                      end: entry?.end ?? "18:00",
                    })
                  }
                  className="rounded border border-border bg-bg px-2 py-1 disabled:opacity-50"
                />
                <input
                  type="time"
                  value={entry?.end ?? ""}
                  disabled={!enabled}
                  onChange={(e) =>
                    setDayHours(key, {
                      start: entry?.start ?? "09:00",
                      end: e.target.value,
                    })
                  }
                  className="rounded border border-border bg-bg px-2 py-1 disabled:opacity-50"
                />
              </div>
            );
          })}
        </div>
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider">
            Focus windows
          </h3>
          <button
            onClick={addFocusWindow}
            className="rounded border border-dashed border-border px-1.5 py-0.5 text-[10px] text-muted hover:border-accent hover:text-accent"
          >
            + add window
          </button>
        </div>
        <div className="space-y-1">
          {prefs.focus_windows.map((w, i) => (
            <div
              key={i}
              className="grid grid-cols-[1fr_1fr_1fr_1.5rem] items-center gap-2 text-xs"
            >
              <input
                type="time"
                value={w.start}
                onChange={(e) =>
                  setFocusWindow(i, { start: e.target.value })
                }
                className="rounded border border-border bg-bg px-2 py-1"
              />
              <input
                type="time"
                value={w.end}
                onChange={(e) => setFocusWindow(i, { end: e.target.value })}
                className="rounded border border-border bg-bg px-2 py-1"
              />
              <select
                value={w.kind}
                onChange={(e) =>
                  setFocusWindow(i, { kind: e.target.value as FocusKind })
                }
                className="rounded border border-border bg-bg px-2 py-1"
              >
                {(Object.keys(FOCUS_KIND_LABELS) as FocusKind[]).map((k) => (
                  <option key={k} value={k}>
                    {FOCUS_KIND_LABELS[k]}
                  </option>
                ))}
              </select>
              <button
                onClick={() => removeFocusWindow(i)}
                className="text-muted hover:text-danger"
                aria-label="remove"
              >
                ×
              </button>
            </div>
          ))}
          {prefs.focus_windows.length === 0 && (
            <p className="text-[11px] text-muted">
              Без focus-окон планировщик ставит задачи где угодно в working
              hours.
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted">Перерыв (мин)</span>
          <input
            type="number"
            min="0"
            max="120"
            value={prefs.min_break_minutes}
            onChange={(e) =>
              setPrefs({
                ...prefs,
                min_break_minutes: Number(e.target.value) || 0,
              })
            }
            className="rounded border border-border bg-bg px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted">Макс непрерывно</span>
          <input
            type="number"
            min="30"
            max="600"
            value={prefs.max_continuous_work_minutes}
            onChange={(e) =>
              setPrefs({
                ...prefs,
                max_continuous_work_minutes: Number(e.target.value) || 60,
              })
            }
            className="rounded border border-border bg-bg px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted">После встречи</span>
          <input
            type="number"
            min="0"
            max="120"
            value={prefs.buffer_after_meeting_minutes}
            onChange={(e) =>
              setPrefs({
                ...prefs,
                buffer_after_meeting_minutes: Number(e.target.value) || 0,
              })
            }
            className="rounded border border-border bg-bg px-2 py-1"
          />
        </label>
      </div>

      {error && <p className="text-xs text-danger">{error}</p>}
      <div className="flex items-center justify-end gap-2">
        {savedAt && Date.now() - savedAt < 3000 && (
          <span className="text-[11px] text-success">Сохранено</span>
        )}
        <button
          onClick={save}
          disabled={saving}
          className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
        >
          {saving ? "…" : "Сохранить"}
        </button>
      </div>
    </section>
  );
}
