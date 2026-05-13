"use client";

import { useEffect, useState } from "react";

import {
  BiometricsTodayDTO,
  getBiometricsToday,
  RecoveryBand,
} from "@/lib/api";

const BAND_BG: Record<RecoveryBand, string> = {
  red: "bg-red-500/15 border-red-500/40 text-red-200",
  yellow: "bg-amber-400/15 border-amber-400/40 text-amber-100",
  green: "bg-emerald-500/15 border-emerald-500/40 text-emerald-100",
};

const BAND_DOT: Record<RecoveryBand, string> = {
  red: "bg-red-500",
  yellow: "bg-amber-400",
  green: "bg-emerald-500",
};

function formatSleep(hours: number | null): string | null {
  if (hours == null || hours <= 0) return null;
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  return m > 0 ? `${h}h${String(m).padStart(2, "0")}m` : `${h}h`;
}

export function RecoveryWidget() {
  const [data, setData] = useState<BiometricsTodayDTO | null | "loading" | "off">(
    "loading",
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const resp = await getBiometricsToday();
        if (cancelled) return;
        setData(resp ?? "off");
      } catch {
        if (!cancelled) setData("off");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (data === "loading" || data === "off" || data === null) return null;

  const band = data.recovery_band;
  const bandClass = band ? BAND_BG[band] : "bg-panel border-border text-muted";
  const dotClass = band ? BAND_DOT[band] : "bg-muted";

  const sleepStr = formatSleep(data.sleep_hours);
  const hasAnything =
    data.recovery_score != null ||
    sleepStr != null ||
    data.strain != null ||
    data.hrv_rmssd_ms != null ||
    data.resting_heart_rate != null;
  if (!hasAnything && !data.available) return null;

  return (
    <div
      className={`mb-3 flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-sm ${bandClass}`}
    >
      <span className="flex items-center gap-1.5 font-medium">
        <span className={`h-2 w-2 rounded-full ${dotClass}`} />
        Recovery{" "}
        {data.recovery_score != null ? `${data.recovery_score}%` : "—"}
      </span>
      {sleepStr && (
        <span className="text-xs opacity-90">
          Sleep <span className="font-medium">{sleepStr}</span>
        </span>
      )}
      {data.strain != null && (
        <span className="text-xs opacity-90">
          Strain <span className="font-medium">{data.strain.toFixed(1)}</span>
        </span>
      )}
      {data.hrv_rmssd_ms != null && (
        <span className="text-xs opacity-90">
          HRV <span className="font-medium">{Math.round(data.hrv_rmssd_ms)}ms</span>
        </span>
      )}
      {data.resting_heart_rate != null && (
        <span className="text-xs opacity-90">
          RHR <span className="font-medium">{data.resting_heart_rate}</span>
        </span>
      )}
      {!data.available && (
        <span className="text-xs italic opacity-70">recovery ещё не пришёл</span>
      )}
    </div>
  );
}
