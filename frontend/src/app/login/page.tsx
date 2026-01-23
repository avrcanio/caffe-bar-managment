"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { DM_Serif_Display } from "next/font/google";
import Image from "next/image";
import { apiPostJson } from "@/lib/api";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await apiPostJson(
        "/api/login/",
        { username, password },
        { csrf: true }
      );
      window.location.href = "/";
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Login failed. Try again.";
      setError(message || "Login failed. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const themeVars = {
    "--paper": "242 235 224",
    "--ink": "18 18 18",
    "--accent": "242 115 35",
    "--accent-2": "255 197 122",
    "--shadow": "10 10 10",
  } as React.CSSProperties;

  return (
    <main
      style={themeVars}
      className="relative min-h-screen overflow-hidden bg-[rgb(var(--paper))] text-[rgb(var(--ink))]"
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(255,197,122,0.35),transparent_60%),radial-gradient(circle_at_15%_80%,_rgba(242,115,35,0.2),transparent_55%)]" />
      <div className="pointer-events-none absolute -left-24 top-10 h-72 w-72 rounded-full bg-[radial-gradient(circle_at_center,rgba(242,115,35,0.35),transparent_65%)] blur-2xl" />
      <div className="pointer-events-none absolute -right-28 top-1/3 h-80 w-80 rounded-full bg-[radial-gradient(circle_at_center,rgba(18,18,18,0.25),transparent_70%)] blur-2xl" />
      <div className="pointer-events-none absolute bottom-8 left-1/2 h-56 w-56 -translate-x-1/2 rounded-full bg-[radial-gradient(circle_at_center,rgba(242,115,35,0.2),transparent_70%)] blur-3xl" />

      <div className="relative mx-auto flex min-h-screen max-w-6xl flex-col gap-10 px-6 py-16 lg:grid lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
        <section className="space-y-6">
          <div className="flex items-center gap-4">
            <div className="rounded-2xl border border-black/15 bg-black/95 p-3 shadow-[0_16px_30px_rgba(var(--shadow),0.3)]">
              <Image
                src="/mozart-logo.png"
                alt="Mozart caffe bar"
                width={220}
                height={90}
                priority
                className="h-auto w-40"
              />
            </div>
            <p className="text-sm uppercase tracking-[0.3em] text-black/60">
              Mozart Admin
            </p>
          </div>
          <h1
            className={`${dmSerif.className} text-4xl leading-tight sm:text-5xl`}
          >
            Dobro došli natrag.
          </h1>
          <p className="max-w-lg text-base text-black/70 sm:text-lg">
            Pristupite upravljanju narudžbama, zalihama i konfiguracijama.
          </p>

         
        </section>

        <section className="rounded-3xl border border-black/15 bg-white/85 p-8 shadow-[0_24px_60px_rgba(var(--shadow),0.25)] backdrop-blur">
          <div className="flex items-center justify-between">
            <h2 className={`${dmSerif.className} text-2xl`}>
              Prijava korisnika
            </h2>
            <span className="rounded-full bg-black px-3 py-1 text-xs uppercase tracking-[0.3em] text-white">
              Secure
            </span>
          </div>

          <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
            <label className="block text-sm">
              <span className="text-black/70">Korisnicko ime</span>
              <input
                className="mt-2 w-full rounded-xl border border-black/15 bg-white px-4 py-3 text-sm outline-none transition focus:border-black/40"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </label>
            <label className="block text-sm">
              <span className="text-black/70">Lozinka</span>
              <input
                className="mt-2 w-full rounded-xl border border-black/15 bg-white px-4 py-3 text-sm outline-none transition focus:border-black/40"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>

            {error ? (
              <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </p>
            ) : null}

            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center rounded-xl bg-[rgb(var(--accent))] px-4 py-3 text-sm font-semibold uppercase tracking-[0.2em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? "Prijava..." : "Prijavi se"}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
