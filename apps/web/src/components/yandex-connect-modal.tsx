"use client";

import { useState } from "react";

import { connectYandex } from "@/lib/api";

type Props = {
  open: boolean;
  onClose: () => void;
  onConnected: () => void;
};

export function YandexConnectModal({ open, onClose, onConnected }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await connectYandex(email.trim(), password.trim());
      onConnected();
      onClose();
      setEmail("");
      setPassword("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-lg border border-border bg-panel p-5 shadow-xl">
        <header className="mb-3">
          <h2 className="text-base font-semibold">Подключить Яндекс Календарь</h2>
          <p className="mt-1 text-xs text-muted">
            Нужен{" "}
            <a
              className="text-accent hover:underline"
              href="https://id.yandex.ru/security/app-passwords"
              target="_blank"
              rel="noreferrer"
            >
              пароль приложения
            </a>{" "}
            со scope «Календарь и контакты (CardDAV/CalDAV)». Обычный пароль не подойдёт.
          </p>
        </header>

        <form className="space-y-3 text-sm" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-1 block text-xs text-muted">Email Яндекса</span>
            <input
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="alice@yandex.ru"
              className="w-full rounded-md border border-border bg-bg px-3 py-2 outline-none focus:border-accent"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-muted">Пароль приложения</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="xxxxxxxxxxxxxxxx"
              className="w-full rounded-md border border-border bg-bg px-3 py-2 font-mono outline-none focus:border-accent"
            />
          </label>

          {error && (
            <div className="rounded-md border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-border bg-bg px-3 py-1.5 text-xs hover:bg-border"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-60"
            >
              {loading ? "Проверяем…" : "Подключить"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
