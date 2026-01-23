"use client";

import { useEffect, useMemo, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiGetJson, apiPostJson } from "@/lib/api";
import { formatEuro } from "@/lib/format";
import {
  mapPurchaseOrderList,
  mapUser,
  PurchaseOrderListDTO,
  PurchaseOrderSummary,
  UserDTO,
} from "@/lib/mappers";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

export default function Home() {
  const [summary, setSummary] = useState<PurchaseOrderSummary | null>(null);
  const [mailCount, setMailCount] = useState<number | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [userName, setUserName] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    const run = async () => {
      try {
        const params = new URLSearchParams({ page_size: "1" });
        const payload = await apiGetJson<PurchaseOrderListDTO>(
          `/api/purchase-orders/?${params.toString()}`
        );
        setSummary(mapPurchaseOrderList(payload).summary);
      } catch (err) {
        setSummary(null);
      }
    };
    run();
  }, []);

  useEffect(() => {
    const run = async () => {
      try {
        const data = await apiGetJson<UserDTO>("/api/me/");
        const user = mapUser(data);
        setUserName(user.fullName || user.username || null);
      } catch (err) {
        setUserName(null);
      }
    };
    run();
  }, []);

  useEffect(() => {
    const run = async () => {
      try {
        const data = await apiGetJson<{ count?: number }>(
          "/api/mailbox/messages/?page_size=1"
        );
        setMailCount(typeof data.count === "number" ? data.count : null);
      } catch (err) {
        setMailCount(null);
      }
    };
    run();
  }, []);

  const statusCounts = useMemo(() => {
    return summary?.statusCounts || {};
  }, [summary]);

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-6 py-12">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-3">
            <p className="text-sm uppercase tracking-[0.3em] text-black/60">
              Mozart Dashboard
            </p>
            <h1
              className={`${dmSerif.className} text-4xl sm:text-5xl`}
            >
              Dnevni pregled rada
            </h1>
            <p className="max-w-xl text-base text-black/70">
              Brz pristup narudzbama i zalihama.
            </p>
            {userName ? (
              <p className="text-sm uppercase tracking-[0.3em] text-black/50">
                {userName}
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button className="rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/70">
              Sync podatke
            </button>
            <button
              onClick={async () => {
                setLoggingOut(true);
                try {
                  await apiPostJson("/api/logout/", undefined, { csrf: true });
                } catch (err) {
                  // If session already expired, ignore and continue to login.
                } finally {
                  router.push("/login");
                }
              }}
              className="rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
              disabled={loggingOut}
            >
              {loggingOut ? "Odjava..." : "Logout"}
            </button>
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-[1.3fr_0.7fr]">
          <Link
            href="/purchase-orders"
            className="rounded-2xl border border-black/15 bg-white/80 p-5 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur transition hover:border-black/40"
          >
            <p className="text-xs uppercase tracking-[0.2em] text-black/50">
              Statusi narudžbi
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {[
                { key: "created", label: "KREIRANA" },
                { key: "sent", label: "POSLANA" },
                { key: "confirmed", label: "POTVRĐENA" },
              ].map((item) => (
                <div
                  key={item.key}
                  className="rounded-2xl border border-black/10 bg-white/70 px-4 py-3"
                >
                  <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                    {item.label}
                  </p>
                  <p className="mt-2 text-3xl font-semibold">
                    {summary ? statusCounts[item.key]?.count ?? 0 : "-"}
                  </p>
                  <p className="mt-1 text-xs uppercase tracking-[0.2em] text-black/50">
                    Bruto:{" "}
                    {summary
                      ? formatEuro(
                          statusCounts[item.key]?.totalGross ?? 0
                        )
                      : "-"}
                  </p>
                </div>
              ))}
            </div>
          </Link>
          <Link
            href="/mailbox"
            className="rounded-2xl border border-black/15 bg-white/80 p-5 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur transition hover:border-black/40"
          >
            <p className="text-xs uppercase tracking-[0.2em] text-black/50">
              E-mails
            </p>
            <p className="mt-3 text-3xl font-semibold">
              {mailCount ?? "-"}
            </p>
            <p className="mt-2 text-sm text-black/60">
              Otvori mailbox
            </p>
          </Link>
        </section>
      </div>
    </main>
  );
}
