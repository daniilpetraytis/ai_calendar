import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

import { ClerkProvider, Show, UserButton } from "@clerk/nextjs";
import { ruRU } from "@clerk/localizations";
import { dark } from "@clerk/themes";

import { OnboardingGate } from "@/components/onboarding-gate";

export const metadata: Metadata = {
  title: "AI Calendar",
  description: "Intelligent calendar optimizer with biometric-aware scheduling",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider
      localization={ruRU}
      appearance={{
        baseTheme: dark,
        variables: {
          colorPrimary: "#7c5cff",
          colorBackground: "#0f1115",
        },
      }}
    >
      <html lang="ru" className="dark">
        <body className="font-sans antialiased">
          <div className="flex min-h-screen flex-col">
            <header className="border-b border-border bg-panel/60 backdrop-blur">
              <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
                <Link href="/" className="font-semibold tracking-tight">
                  <span className="text-accent">●</span> AI Calendar
                </Link>
                <div className="flex items-center gap-4">
                  <Show when="signed-in">
                    <nav className="flex gap-4 text-sm text-muted">
                      <Link href="/calendar" className="hover:text-text">Calendar</Link>
                      <Link href="/chat" className="hover:text-text">Chat</Link>
                      <Link href="/stats" className="hover:text-text">Stats</Link>
                      <Link href="/settings" className="hover:text-text">Settings</Link>
                    </nav>
                    <OnboardingGate />
                    <UserButton />
                  </Show>
                  <Show when="signed-out">
                    <div className="flex gap-3 text-sm">
                      <Link
                        href="/sign-in"
                        className="text-muted hover:text-text"
                      >
                        Войти
                      </Link>
                      <Link
                        href="/sign-up"
                        className="rounded-md bg-accent px-3 py-1 text-white"
                      >
                        Регистрация
                      </Link>
                    </div>
                  </Show>
                </div>
              </div>
            </header>
            <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">{children}</main>
          </div>
        </body>
      </html>
    </ClerkProvider>
  );
}
