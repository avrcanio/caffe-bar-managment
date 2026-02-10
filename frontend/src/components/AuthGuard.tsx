"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";

type AuthGuardProps = {
  children: React.ReactNode;
};

export default function AuthGuard({ children }: AuthGuardProps) {
  // null: not decided yet; true: show overlay; false: no overlay
  const [checking, setChecking] = useState<boolean | null>(null);

  useEffect(() => {
    const path = window.location.pathname;
    if (path === "/login" || path === "/download" || path.startsWith("/inventory")) {
      setChecking(false);
      return;
    }
    setChecking(true);
    const run = async () => {
      try {
        const response = await apiRequest("/api/me/");
        if (response.status === 401 || response.status === 403) {
          return;
        }
      } catch {
        // apiRequest already handles redirect on 401
      } finally {
        setChecking(false);
      }
    };
    run();
  }, []);

  return (
    <>
      {children}
      {checking === true ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="rounded-2xl border border-black/10 bg-white/90 px-6 py-4 text-sm text-black/70 shadow-[0_18px_40px_rgba(10,10,10,0.2)]">
            Provjera prijave...
          </div>
        </div>
      ) : null}
    </>
  );
}
