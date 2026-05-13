"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type Example = {
  text: string;
};

type Slide = {
  title: string;
  body: React.ReactNode;
  examples?: Example[];
};

const SLIDES: Slide[] = [
  {
    title: "Привет 👋 Это AI Calendar",
    body: (
      <p>
        Я помогаю планировать день: создаю и двигаю события, перетасовываю
        расписание под форс-мажоры и не делаю ничего деструктивного без твоего
        подтверждения. Команды можно давать в свободной форме — на русском или
        английском, как тебе удобно.
      </p>
    ),
  },
  {
    title: "Создавай и меняй события",
    body: (
      <p>
        Опиши, что нужно — я сам разберусь со временем и поставлю событие
        (опционально синхронизируется с Яндекс Календарём, если он подключён в
        Settings).
      </p>
    ),
    examples: [
      { text: "запланируй обед в 13:00 на час" },
      { text: "поставь работу с 9 до 19 пн-пт на этой неделе" },
      { text: "перенеси встречу с 15:00 на 16:00" },
    ],
  },
  {
    title: "Перепланируй день под форс-мажор",
    body: (
      <p>
        Когда что-то внезапно вклинивается, я предложу новый план целиком — ты
        видишь diff и подтверждаешь или отклоняешь каждое изменение.
      </p>
    ),
    examples: [
      { text: "у меня встреча с 15 до 17, перепланируй остаток дня" },
      { text: "только закончил тренировку, подвинь все дела на сегодня" },
      { text: "сдвинь все будущие дела на 15 минут вперёд" },
    ],
  },
  {
    title: "Задачи и focus-блоки",
    body: (
      <p>
        Добавляй задачи с дедлайном — я найду подходящий слот в твоём
        расписании с учётом focus-окон (deep / shallow / admin). Все настройки
        окон и рабочих часов — в Settings.
      </p>
    ),
    examples: [
      { text: "добавь таску починить дверь, час, дедлайн пятница" },
      { text: "найди мне час deep work до завтра" },
      { text: "перепланируй все pending задачи на эту неделю" },
    ],
  },
  {
    title: "Категории и статистика",
    body: (
      <p>
        События автоматически попадают в категории (работа / спорт / семья…) —
        вкладка <b>Stats</b> покажет, на что реально уходит время за день,
        неделю и месяц. Категории можно переименовывать и переназначать прямо
        из чата.
      </p>
    ),
    examples: [
      { text: "сколько времени я потратил на работу за неделю?" },
      { text: "покажи, на что ушёл вчерашний день" },
      { text: "помечай встречи с дантистом как health" },
    ],
  },
  {
    title: "Telegram-бот — агент в кармане",
    body: (
      <p>
        В <b>Settings → Telegram</b> нажми «Connect» — откроется чат с ботом,
        который уже привязан к твоему аккаунту. Можно писать ему текстом или
        отправлять голосовые (Yandex SpeechKit расшифрует) — те же команды, что
        и тут в чате, плюс утренний/вечерний дайджест прямо в мессенджер.
      </p>
    ),
    examples: [
      { text: "(в Telegram) что у меня сегодня?" },
      { text: "(голосом) перенеси встречу с 15 на 16" },
      { text: "(в Telegram) подытожь день" },
    ],
  },
  {
    title: "Whoop — биометрия и адаптация плана",
    body: (
      <p>
        Подключи Whoop в <b>Settings → Whoop</b> — каждое утро будет приходить
        дайджест: recovery, HRV, сон. Агент учитывает recovery-band при
        планировании: на «красном» утре сам предложит передвинуть тяжёлые
        задачи, а интенсивные тренировки автоматически появляются в календаре
        со страйном.
      </p>
    ),
    examples: [
      { text: "как у меня recovery сегодня?" },
      { text: "перепланируй день — я плохо спал" },
      { text: "покажи мой strain за неделю" },
    ],
  },
];

export function OnboardingTour({
  onClose,
  onComplete,
}: {
  onClose: () => void;
  onComplete: () => void;
}) {
  const [step, setStep] = useState(0);
  const [mounted, setMounted] = useState(false);
  const slide = SLIDES[step];
  const isLast = step === SLIDES.length - 1;

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "Enter") {
        if (isLast) onComplete();
        else setStep((s) => Math.min(SLIDES.length - 1, s + 1));
      } else if (e.key === "ArrowLeft") {
        setStep((s) => Math.max(0, s - 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isLast, onClose, onComplete]);

  if (!mounted) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center overflow-y-auto bg-black/70 px-4 py-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tour-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="my-auto w-full max-w-xl max-h-[calc(100vh-3rem)] overflow-y-auto rounded-xl border border-border bg-panel p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <h2 id="tour-title" className="text-lg font-semibold text-text">
            {slide.title}
          </h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-text"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>

        <div className="mt-3 text-sm leading-relaxed text-muted">
          {slide.body}
        </div>

        {slide.examples && slide.examples.length > 0 && (
          <ul className="mt-4 space-y-1.5">
            {slide.examples.map((ex, i) => (
              <li
                key={i}
                className="rounded-md border border-border bg-bg/60 px-3 py-2 text-xs text-muted"
              >
                <span className="mr-2 text-accent">›</span>
                {ex.text}
              </li>
            ))}
          </ul>
        )}

        <div className="mt-6 flex items-center justify-between">
          <div className="flex gap-1.5">
            {SLIDES.map((_, i) => (
              <button
                key={i}
                onClick={() => setStep(i)}
                aria-label={`Шаг ${i + 1}`}
                className={
                  "h-1.5 w-6 rounded-full transition-colors " +
                  (i === step ? "bg-accent" : "bg-border hover:bg-muted/40")
                }
              />
            ))}
          </div>

          <div className="flex gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm text-muted hover:text-text"
              >
                Назад
              </button>
            )}
            {!isLast ? (
              <button
                onClick={() => setStep((s) => Math.min(SLIDES.length - 1, s + 1))}
                className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
              >
                Дальше
              </button>
            ) : (
              <button
                onClick={onComplete}
                className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
              >
                Поехали
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
