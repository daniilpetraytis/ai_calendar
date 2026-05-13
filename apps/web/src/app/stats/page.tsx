"use client";

import { useCallback, useEffect, useState } from "react";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

import {
  Category,
  DayStatItem,
  getHeatmap,
  getStatsByCategory,
  getStatsByDay,
  getTrends,
  HeatmapCell,
  HeatmapData,
  listCategories,
  StatsByCategory,
  TrendsData,
} from "@/lib/api";

type Period = "day" | "week" | "month";

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOUR_LABELS = Array.from({ length: 24 }, (_, i) =>
  i % 6 === 0 ? `${i}:00` : "",
);

function fmtMins(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function DeltaBadge({ delta, pct }: { delta: number; pct: number | null }) {
  if (delta === 0) return <span className="text-xs text-muted">—</span>;
  const up = delta > 0;
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-xs font-medium ${up ? "text-success" : "text-danger"}`}
    >
      {up ? "▲" : "▼"} {fmtMins(Math.abs(delta))}
      {pct !== null && (
        <span className="text-[10px] opacity-70">
          {" "}
          ({up ? "+" : ""}
          {pct}%)
        </span>
      )}
    </span>
  );
}

export default function StatsPage() {
  const [period, setPeriod] = useState<Period>("week");
  const [offset, setOffset] = useState(0);

  const [stats, setStats] = useState<StatsByCategory | null>(null);
  const [byDay, setByDay] = useState<DayStatItem[]>([]);
  const [heatmap, setHeatmap] = useState<HeatmapData | null>(null);
  const [trends, setTrends] = useState<TrendsData | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, bd, h, t, cats] = await Promise.all([
        getStatsByCategory(period, offset),
        getStatsByDay(period, offset),
        getHeatmap(period, offset),
        getTrends(period, offset === 0 ? -1 : offset - 1),
        listCategories(),
      ]);
      setStats(s);
      setByDay(bd);
      setHeatmap(h);
      setTrends(t);
      setCategories(cats);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [period, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  // Build heatmap grid: {day → {hour → minutes}}
  const heatGrid = new Map<number, Map<number, number>>();
  (heatmap?.cells ?? []).forEach((c: HeatmapCell) => {
    if (!heatGrid.has(c.day)) heatGrid.set(c.day, new Map());
    heatGrid.get(c.day)!.set(c.hour, c.minutes);
  });
  const maxHeatMins = Math.max(
    1,
    ...(heatmap?.cells.map((c) => c.minutes) ?? [1]),
  );

  const allDayCats = Array.from(
    new Set(byDay.flatMap((d) => d.by_category.map((c) => c.category)))
  );
  const dayCatColors = new Map<string, string>();
  byDay.forEach((d) =>
    d.by_category.forEach((c) => dayCatColors.set(c.category, c.color))
  );
  const barData = byDay.map((d) => {
    const row: Record<string, number | string> = { day: d.day_label };
    d.by_category.forEach((c) => {
      row[c.category] = c.minutes;
    });
    return row;
  });

  return (
    <div className="space-y-6">
      {/* Header + period switcher */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Stats</h1>
          <p className="text-xs text-muted">
            {stats?.period_label ?? "—"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border border-border overflow-hidden text-sm">
            {(["day", "week", "month"] as Period[]).map((p) => (
              <button
                key={p}
                onClick={() => { setPeriod(p); setOffset(0); }}
                className={`px-3 py-1.5 capitalize transition-colors ${period === p ? "bg-accent text-white" : "bg-bg text-muted hover:bg-border"}`}
              >
                {p}
              </button>
            ))}
          </div>
          <div className="flex rounded-md border border-border overflow-hidden text-sm">
            <button
              onClick={() => setOffset((o) => o - 1)}
              disabled={offset <= -52}
              className="px-2 py-1.5 bg-bg text-muted hover:bg-border disabled:opacity-40"
            >
              ‹
            </button>
            <span className="flex items-center px-2 py-1.5 text-xs bg-bg text-muted">
              {offset === 0 ? "Current" : offset}
            </span>
            <button
              onClick={() => setOffset((o) => Math.min(0, o + 1))}
              disabled={offset >= 0}
              className="px-2 py-1.5 bg-bg text-muted hover:bg-border disabled:opacity-40"
            >
              ›
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </div>
      )}

      {loading && (
        <div className="text-xs text-muted">Loading…</div>
      )}

      {stats && (
        <div className="grid gap-4 lg:grid-cols-2">
          {/* Pie chart */}
          <div className="rounded-lg border border-border bg-panel p-4">
            <h2 className="mb-3 text-sm font-medium">By category</h2>
            <div className="flex items-center gap-4">
              <ResponsiveContainer width={160} height={160}>
                <PieChart>
                  <Pie
                    data={stats.by_category}
                    dataKey="minutes"
                    nameKey="category"
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={75}
                  >
                    {stats.by_category.map((entry) => (
                      <Cell key={entry.category} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(v) => fmtMins(Number(v ?? 0))}
                    contentStyle={{ background: "#11151c", border: "1px solid #1c2230", borderRadius: 6, fontSize: 12 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex-1 space-y-1.5">
                {stats.by_category.slice(0, 8).map((item) => (
                  <div key={item.category} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: item.color }}
                      />
                      <span className="text-muted">{item.emoji} {item.category}</span>
                    </div>
                    <span className="font-medium">{fmtMins(item.minutes)}</span>
                  </div>
                ))}
                <div className="border-t border-border pt-1 flex justify-between text-xs">
                  <span className="text-muted">Total</span>
                  <span className="font-semibold">{fmtMins(stats.total_minutes)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Goals progress */}
          <div className="rounded-lg border border-border bg-panel p-4">
            <h2 className="mb-3 text-sm font-medium">Goals</h2>
            {stats.by_category.filter((c) => c.goal_minutes_per_week != null).length === 0 ? (
              <p className="text-xs text-muted">
                No goals set. Add weekly goals in{" "}
                <a href="/settings" className="text-accent hover:underline">Settings</a>.
              </p>
            ) : (
              <div className="space-y-3">
                {stats.by_category
                  .filter((c) => c.goal_minutes_per_week != null)
                  .map((item) => {
                    const goal = item.goal_minutes_per_week!;
                    const pct = Math.min(100, Math.round((item.minutes / goal) * 100));
                    return (
                      <div key={item.category}>
                        <div className="mb-1 flex items-center justify-between text-xs">
                          <span className="text-muted">{item.emoji} {item.category}</span>
                          <span>
                            <span className="font-medium">{fmtMins(item.minutes)}</span>
                            <span className="text-muted"> / {fmtMins(goal)}</span>
                          </span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-border">
                          <div
                            className="h-full rounded-full transition-all"
                            style={{ width: `${pct}%`, backgroundColor: item.color }}
                          />
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Bar chart: days of week */}
      {byDay.length > 0 && (
        <div className="rounded-lg border border-border bg-panel p-4">
          <h2 className="mb-3 text-sm font-medium">By day of week</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={barData} margin={{ top: 0, right: 8, bottom: 0, left: -16 }}>
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#8a93a6" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "#8a93a6" }} axisLine={false} tickLine={false} tickFormatter={(v) => v > 0 ? `${Math.round(v / 60)}h` : ""} />
              <Tooltip
                formatter={(v, name) => [fmtMins(Number(v ?? 0)), name]}
                contentStyle={{ background: "#11151c", border: "1px solid #1c2230", borderRadius: 6, fontSize: 12 }}
              />
              {allDayCats.map((cat, i) => (
                <Bar
                  key={cat}
                  dataKey={cat}
                  stackId="a"
                  fill={dayCatColors.get(cat) ?? "#9ca3af"}
                  radius={i === allDayCats.length - 1 ? [3, 3, 0, 0] : undefined}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Heatmap */}
      {heatmap && (
        <div className="rounded-lg border border-border bg-panel p-4">
          <h2 className="mb-3 text-sm font-medium">Activity heatmap</h2>
          <div className="overflow-x-auto">
            <div className="inline-grid min-w-[560px]" style={{ gridTemplateColumns: "32px repeat(24, 1fr)", gap: 2 }}>
              {/* Hour headers */}
              <div />
              {HOUR_LABELS.map((label, h) => (
                <div key={h} className="text-center text-[9px] text-muted leading-none pb-1">
                  {label}
                </div>
              ))}
              {/* Rows */}
              {DAY_LABELS.map((dayLabel, dayIdx) => (
                <>
                  <div key={`label-${dayIdx}`} className="flex items-center text-[10px] text-muted pr-1">
                    {dayLabel}
                  </div>
                  {Array.from({ length: 24 }, (_, h) => {
                    const mins = heatGrid.get(dayIdx)?.get(h) ?? 0;
                    const opacity = mins === 0 ? 0.06 : 0.15 + (mins / maxHeatMins) * 0.85;
                    return (
                      <div
                        key={`${dayIdx}-${h}`}
                        title={mins > 0 ? `${dayLabel} ${h}:00 — ${fmtMins(mins)}` : undefined}
                        className="aspect-square rounded-sm"
                        style={{ backgroundColor: `rgba(124, 92, 255, ${opacity})` }}
                      />
                    );
                  })}
                </>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Trends */}
      {trends && trends.items.length > 0 && (
        <div className="rounded-lg border border-border bg-panel p-4">
          <h2 className="mb-1 text-sm font-medium">Trends</h2>
          <p className="mb-3 text-xs text-muted">
            {trends.period_label} vs {trends.previous_label}
          </p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {trends.items.slice(0, 9).map((item) => (
              <div
                key={item.category}
                className="flex items-center justify-between rounded-md border border-border bg-bg px-3 py-2"
              >
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: item.color }}
                  />
                  <span className="text-muted">{item.emoji} {item.category}</span>
                </div>
                <div className="text-right">
                  <div className="text-xs font-medium">{fmtMins(item.current_minutes)}</div>
                  <DeltaBadge delta={item.delta_minutes} pct={item.delta_pct} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
