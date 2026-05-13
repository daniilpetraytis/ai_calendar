"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@clerk/nextjs";

import { completeOnboarding, getMe } from "@/lib/api";

import { OnboardingTour } from "./onboarding-tour";

function useOnboardingState() {
  const { isLoaded, isSignedIn } = useAuth();
  const [checked, setChecked] = useState(false);
  const [needsTour, setNeedsTour] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || checked) return;
    let cancelled = false;
    (async () => {
      try {
        const me = await getMe();
        if (cancelled) return;
        if (me.onboarded_at == null) {
          setNeedsTour(true);
          setOpen(true);
        }
      } catch {
      } finally {
        if (!cancelled) setChecked(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, checked]);

  return {
    isSignedIn: !!isSignedIn,
    open,
    needsTour,
    show: () => setOpen(true),
    close: () => setOpen(false),
    markComplete: async () => {
      setOpen(false);
      setNeedsTour(false);
      try {
        await completeOnboarding();
      } catch {
        console.warn("Failed to mark onboarding complete");
      }
    },
  };
}

export function OnboardingGate() {
  const { isSignedIn, open, show, close, markComplete } = useOnboardingState();

  if (!isSignedIn) return null;

  return (
    <>
      <button
        onClick={show}
        title="Открыть гайд"
        aria-label="Открыть гайд"
        className="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-bg text-sm text-muted hover:text-text"
      >
        ?
      </button>
      {open && <OnboardingTour onClose={close} onComplete={markComplete} />}
    </>
  );
}
