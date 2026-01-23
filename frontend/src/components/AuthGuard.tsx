"use client";

import { useEffect } from "react";
import { apiRequest } from "@/lib/api";

type AuthGuardProps = {
  children: React.ReactNode;
};

export default function AuthGuard({ children }: AuthGuardProps) {
  useEffect(() => {
    const path = window.location.pathname;
    if (path === "/login") {
      return;
    }
    const run = async () => {
      try {
        const response = await apiRequest("/api/me/");
        if (response.status === 401) {
          return;
        }
      } catch {
        // apiRequest already handles redirect on 401
      }
    };
    run();
  }, []);

  return <>{children}</>;
}
