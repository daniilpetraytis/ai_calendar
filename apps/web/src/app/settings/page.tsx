"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Category,
  createPlace,
  deletePlace,
  disconnectTelegram,
  disconnectWhoop,
  disconnectYandex,
  getIntegrationsStatus,
  IntegrationsStatus,
  listCategories,
  listPlaces,
  Place,
  startTelegramConnect,
  startWhoopConnect,
  updateCategory,
  updatePlace,
} from "@/lib/api";
import { PreferencesCard } from "@/components/preferences-card";
import { YandexConnectModal } from "@/components/yandex-connect-modal";

function fmtGoal(mins: number | null): string {
  if (mins == null) return "";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

export default function SettingsPage() {
  const whoopError = useMemo(() => {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("whoop_error");
  }, []);
  const [status, setStatus] = useState<IntegrationsStatus | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [places, setPlaces] = useState<Place[]>([]);
  const [loading, setLoading] = useState(false);
  const [yandexOpen, setYandexOpen] = useState(false);
  const [tgConnecting, setTgConnecting] = useState(false);
  const [tgError, setTgError] = useState<string | null>(null);
  // Per-category edit state: name → {color, goalHours}
  const [editGoals, setEditGoals] = useState<Record<string, string>>({});
  const [editColors, setEditColors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  // New-place form state.
  const [newPlaceName, setNewPlaceName] = useState("");
  const [newPlaceAddress, setNewPlaceAddress] = useState("");
  const [newPlaceDefault, setNewPlaceDefault] = useState(false);
  const [placeError, setPlaceError] = useState<string | null>(null);
  const [placeBusy, setPlaceBusy] = useState(false);

  const reload = async () => {
    setLoading(true);
    try {
      const [s, cats, pls] = await Promise.all([
        getIntegrationsStatus(),
        listCategories(),
        listPlaces(),
      ]);
      setStatus(s);
      setCategories(cats);
      setPlaces(pls);
      // Init edit state
      const goals: Record<string, string> = {};
      const colors: Record<string, string> = {};
      cats.forEach((c) => {
        goals[c.name] = c.goal_minutes_per_week
          ? String(Math.round(c.goal_minutes_per_week / 60))
          : "";
        colors[c.name] = c.color;
      });
      setEditGoals(goals);
      setEditColors(colors);
    } finally {
      setLoading(false);
    }
  };

  const handleCreatePlace = async () => {
    setPlaceError(null);
    const name = newPlaceName.trim();
    const address = newPlaceAddress.trim();
    if (!name || !address) {
      setPlaceError("Введи и название, и адрес");
      return;
    }
    setPlaceBusy(true);
    try {
      await createPlace({
        name,
        address,
        is_default: newPlaceDefault || places.length === 0,
      });
      setNewPlaceName("");
      setNewPlaceAddress("");
      setNewPlaceDefault(false);
      await reload();
    } catch (err) {
      setPlaceError(err instanceof Error ? err.message : String(err));
    } finally {
      setPlaceBusy(false);
    }
  };

  const handleSetDefaultPlace = async (place: Place) => {
    setPlaceError(null);
    try {
      await updatePlace(place.id, { is_default: true });
      await reload();
    } catch (err) {
      setPlaceError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDeletePlace = async (place: Place) => {
    setPlaceError(null);
    if (!window.confirm(`Удалить место «${place.name}»?`)) return;
    try {
      await deletePlace(place.id);
      await reload();
    } catch (err) {
      setPlaceError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  const handleSaveCategory = async (cat: Category) => {
    setSaving(cat.name);
    try {
      const goalHours = parseFloat(editGoals[cat.name] ?? "");
      const goal = isNaN(goalHours) || goalHours <= 0
        ? null
        : Math.round(goalHours * 60);
      const color = editColors[cat.name] ?? cat.color;
      await updateCategory(cat.name, { color, goal_minutes_per_week: goal });
      await reload();
    } finally {
      setSaving(null);
    }
  };

  const yandexConnected = status?.yandex_calendar?.connected ?? false;
  const telegramConnected = status?.telegram?.connected ?? false;
  const telegramUserId = status?.telegram?.telegram_user_id ?? null;
  const whoopConnected = status?.whoop?.connected ?? false;
  const whoopEmail = status?.whoop?.account_email ?? null;

  const handleConnectTelegram = async () => {
    setTgConnecting(true);
    setTgError(null);
    try {
      const { deeplink } = await startTelegramConnect();
      window.open(deeplink, "_blank", "noopener");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // Surface the most informative bit of the FastAPI detail.
      const detailMatch = msg.match(/"detail":"([^"]+)"/);
      setTgError(detailMatch ? detailMatch[1] : msg);
    } finally {
      setTgConnecting(false);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Settings</h1>

      {/* Integrations */}
      <section className="space-y-3 rounded-lg border border-border bg-panel p-4">
        <h2 className="text-sm font-medium">Integrations</h2>
        {whoopError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
            Whoop не подключился: {whoopError}
          </div>
        )}
        <ul className="space-y-2 text-sm">
          <li className="flex items-center justify-between">
            <div>
              <div>Яндекс Календарь</div>
              <div className="text-xs text-muted">
                {yandexConnected
                  ? `Connected as ${status?.yandex_calendar?.account_email ?? "—"}`
                  : "Через CalDAV (нужен пароль приложения)"}
              </div>
            </div>
            {yandexConnected ? (
              <button
                onClick={async () => { await disconnectYandex(); await reload(); }}
                className="rounded-md border border-border bg-bg px-3 py-1 text-xs text-muted hover:text-danger"
              >
                Disconnect
              </button>
            ) : (
              <button
                onClick={() => setYandexOpen(true)}
                className="rounded-md bg-accent px-3 py-1 text-xs text-white"
              >
                Connect
              </button>
            )}
          </li>

          <li className="flex items-center justify-between">
            <div>
              <div>Telegram</div>
              <div className="text-xs text-muted">
                {telegramConnected
                  ? `Connected (tg id ${telegramUserId ?? "?"})`
                  : "Связать аккаунт с ботом — общайся с агентом из Telegram"}
              </div>
              {tgError && (
                <div className="mt-1 text-xs text-danger">{tgError}</div>
              )}
            </div>
            {telegramConnected ? (
              <button
                onClick={async () => {
                  await disconnectTelegram();
                  await reload();
                }}
                className="rounded-md border border-border bg-bg px-3 py-1 text-xs text-muted hover:text-danger"
              >
                Disconnect
              </button>
            ) : (
              <button
                onClick={handleConnectTelegram}
                disabled={tgConnecting}
                className="rounded-md bg-accent px-3 py-1 text-xs text-white disabled:opacity-50"
              >
                {tgConnecting ? "…" : "Connect"}
              </button>
            )}
          </li>

          <li className="flex items-center justify-between">
            <div>
              <div>Whoop</div>
              <div className="text-xs text-muted">
                {whoopConnected
                  ? `Connected${whoopEmail ? ` as ${whoopEmail}` : ""}`
                  : "Recovery, sleep, strain — утренний пуш и стата тренировок"}
              </div>
            </div>
            {whoopConnected ? (
              <button
                onClick={async () => {
                  if (!confirm("Отключить Whoop?")) return;
                  await disconnectWhoop();
                  await reload();
                }}
                className="rounded-md border border-border bg-bg px-3 py-1 text-xs text-muted hover:text-danger"
              >
                Disconnect
              </button>
            ) : (
              <button
                onClick={async () => {
                  const { authorize_url } = await startWhoopConnect();
                  window.location.href = authorize_url;
                }}
                className="rounded-md bg-accent px-3 py-1 text-xs text-white"
              >
                Connect
              </button>
            )}
          </li>
        </ul>
        {loading && <div className="text-xs text-muted">Loading…</div>}
      </section>

      {/* Scheduler preferences (Phase G) */}
      <PreferencesCard />

      {/* Places (saved addresses) */}
      <section className="rounded-lg border border-border bg-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium">Места</h2>
          <p className="text-xs text-muted">
            Агент использует их как «откуда / куда» и строит ссылку на маршрут
          </p>
        </div>

        <div className="space-y-1">
          {places.length > 0 && (
            <div className="grid grid-cols-[1fr_2fr_5rem_4rem] items-center gap-2 px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted">
              <span>Название</span>
              <span>Адрес</span>
              <span>По умолч.</span>
              <span />
            </div>
          )}
          {places.map((place) => (
            <div
              key={place.id}
              className="grid grid-cols-[1fr_2fr_5rem_4rem] items-center gap-2 rounded-md px-2 py-1.5 hover:bg-border/40"
            >
              <div className="text-sm">
                {place.name}
                {place.is_default && (
                  <span className="ml-1.5 text-[10px] text-muted opacity-60">
                    default
                  </span>
                )}
              </div>
              <div className="truncate text-xs text-muted" title={place.address}>
                {place.address}
              </div>
              <div>
                <input
                  type="radio"
                  name="default-place"
                  checked={place.is_default}
                  onChange={() => handleSetDefaultPlace(place)}
                  className="cursor-pointer"
                  aria-label={`Сделать «${place.name}» местом по умолчанию`}
                />
              </div>
              <button
                onClick={() => handleDeletePlace(place)}
                className="rounded-md border border-border bg-bg px-2 py-1 text-xs text-muted hover:text-danger"
              >
                Удалить
              </button>
            </div>
          ))}
        </div>

        {/* Add new */}
        <div className="mt-3 grid grid-cols-[1fr_2fr_5rem_5rem] items-end gap-2 border-t border-border pt-3">
          <input
            type="text"
            placeholder="дом / офис / парикмахерская"
            value={newPlaceName}
            onChange={(e) => setNewPlaceName(e.target.value)}
            className="rounded border border-border bg-bg px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <input
            type="text"
            placeholder="Город, улица, дом"
            value={newPlaceAddress}
            onChange={(e) => setNewPlaceAddress(e.target.value)}
            className="rounded border border-border bg-bg px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <label className="flex items-center gap-1 text-[11px] text-muted">
            <input
              type="checkbox"
              checked={newPlaceDefault || places.length === 0}
              disabled={places.length === 0}
              onChange={(e) => setNewPlaceDefault(e.target.checked)}
            />
            default
          </label>
          <button
            onClick={handleCreatePlace}
            disabled={placeBusy}
            className="rounded-md bg-accent px-2 py-1 text-xs text-white disabled:opacity-50"
          >
            {placeBusy ? "…" : "Добавить"}
          </button>
        </div>
        {placeError && (
          <div className="mt-2 text-xs text-danger">{placeError}</div>
        )}
        {places.length === 0 && (
          <p className="mt-2 text-xs text-muted">
            Пока пусто. Добавь хотя бы «дом» — он будет «откуда» по умолчанию.
          </p>
        )}
      </section>

      {/* Categories */}
      <section className="rounded-lg border border-border bg-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium">Categories</h2>
          <p className="text-xs text-muted">Set weekly goals and colors</p>
        </div>

        <div className="space-y-1">
          {/* Header row */}
          <div className="grid grid-cols-[2rem_1fr_5rem_6rem_4rem] items-center gap-2 px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted">
            <span />
            <span>Category</span>
            <span>Color</span>
            <span>Goal / week</span>
            <span />
          </div>

          {categories.map((cat) => (
            <div
              key={cat.name}
              className="grid grid-cols-[2rem_1fr_5rem_6rem_4rem] items-center gap-2 rounded-md px-2 py-1.5 hover:bg-border/40"
            >
              {/* Emoji */}
              <span className="text-base text-center">{cat.emoji ?? "📌"}</span>

              {/* Name */}
              <div>
                <span className="text-sm">{cat.name}</span>
                {cat.is_default && (
                  <span className="ml-1.5 text-[10px] text-muted opacity-60">default</span>
                )}
              </div>

              {/* Color picker */}
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="color"
                  value={editColors[cat.name] ?? cat.color}
                  onChange={(e) =>
                    setEditColors((prev) => ({ ...prev, [cat.name]: e.target.value }))
                  }
                  className="h-6 w-8 cursor-pointer rounded border border-border bg-transparent p-0"
                />
                <span className="text-[10px] text-muted font-mono">
                  {(editColors[cat.name] ?? cat.color).toUpperCase()}
                </span>
              </label>

              {/* Goal input */}
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  min="0"
                  max="168"
                  step="0.5"
                  placeholder="—"
                  value={editGoals[cat.name] ?? ""}
                  onChange={(e) =>
                    setEditGoals((prev) => ({ ...prev, [cat.name]: e.target.value }))
                  }
                  className="w-14 rounded border border-border bg-bg px-2 py-1 text-xs text-right focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <span className="text-[10px] text-muted">h</span>
              </div>

              {/* Save button */}
              <button
                onClick={() => handleSaveCategory(cat)}
                disabled={saving === cat.name}
                className="rounded-md bg-accent/20 px-2 py-1 text-xs text-accent hover:bg-accent hover:text-white disabled:opacity-50 transition-colors"
              >
                {saving === cat.name ? "…" : "Save"}
              </button>
            </div>
          ))}
        </div>

        {categories.length === 0 && !loading && (
          <p className="text-xs text-muted py-2">
            No categories yet. Visit{" "}
            <a href="/calendar" className="text-accent hover:underline">Calendar</a>{" "}
            to trigger auto-seeding.
          </p>
        )}
      </section>

      {/* Auth info */}
      <section className="space-y-2 rounded-lg border border-border bg-panel p-4 text-sm">
        <h2 className="font-medium">Аккаунт</h2>
        <p className="text-xs text-muted">
          Авторизация через{" "}
          <a
            href="https://clerk.com/docs"
            target="_blank"
            rel="noreferrer"
            className="text-accent hover:underline"
          >
            Clerk
          </a>
          . Сменить email, пароль или подключённые соцсети — иконка профиля в
          правом верхнем углу. Гайд по продукту — кнопка «?» рядом с профилем.
        </p>
      </section>

      <YandexConnectModal
        open={yandexOpen}
        onClose={() => setYandexOpen(false)}
        onConnected={reload}
      />
    </div>
  );
}
