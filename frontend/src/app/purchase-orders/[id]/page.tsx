"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { apiGetJson, apiPostJson } from "@/lib/api";
import { formatDate, formatEuro } from "@/lib/format";
import EmptyState from "@/components/EmptyState";
import LoadingCard from "@/components/LoadingCard";
import {
  mapPurchaseOrder,
  PurchaseOrder,
  PurchaseOrderDTO,
} from "@/lib/mappers";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

export default function PurchaseOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;
  const [order, setOrder] = useState<PurchaseOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const groupRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [activeGroupIndex, setActiveGroupIndex] = useState(0);
  const [showStatusPrompt, setShowStatusPrompt] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");

  const loadOrder = useCallback(async () => {
    if (!id) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await apiGetJson<PurchaseOrderDTO>(
        `/api/purchase-orders/${id}/`
      );
      setOrder(mapPurchaseOrder(data));
    } catch (err) {
      setError("Ne mogu ucitati purchase order.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadOrder();
  }, [loadOrder]);

  const groupedItems = useMemo(() => {
    const items = order?.items || [];
    const groups: Record<string, PurchaseOrder["items"]> = {};
    items.forEach((item) => {
      const key = item.baseGroup || "Ostalo";
      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(item);
    });
    return Object.entries(groups)
      .map(([group, groupItems]) => [
        group,
        groupItems
          .slice()
          .sort((a, b) => a.name.localeCompare(b.name, "hr", { sensitivity: "base" })),
      ] as [string, PurchaseOrder["items"]])
      .sort(([a], [b]) => (a as string).localeCompare(b as string, "hr", { sensitivity: "base" }));
  }, [order]);

  useEffect(() => {
    if (!groupedItems.length) {
      setActiveGroupIndex(0);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => Number(entry.target.getAttribute("data-index")))
          .sort((a, b) => a - b);
        if (visible.length) {
          setActiveGroupIndex(visible[0]);
        }
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: [0, 1] }
    );

    groupedItems.forEach(([group], index) => {
      const groupName = group as string;
      const node = groupRefs.current[groupName];
      if (node) {
        node.setAttribute("data-index", String(index));
        observer.observe(node);
      }
    });

    return () => observer.disconnect();
  }, [groupedItems]);

  const activeGroupLabel =
    (groupedItems[activeGroupIndex]?.[0] as string) || "Ostalo";

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col gap-8 px-6 py-12">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-sm uppercase tracking-[0.3em] text-black/60">
              Narudžba {id}
            </p>           
          </div>
          <Link
            href="/purchase-orders"
            className="rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
          >
            Povratak
          </Link>
        </header>

        {loading ? (
          <LoadingCard message="Ucitavanje purchase ordera..." />
        ) : null}
        {error ? (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
            {error}
          </div>
        ) : null}

        {order ? (
          <>
            <section className="grid gap-4 md:grid-cols-3">
              {[
                {
                  label: "Dobavljac",
                  value: order.supplierName,
                },
                {
                  label: "Status",
                  value: order.statusLabel,
                  clickable: order.statusCode === "created",
                },
                {
                  label: "Datum",
                  value: formatDate(order.orderedAt, {
                    dateStyle: "short",
                    timeStyle: "short",
                  }),
                },
              ].map((card) => {
                const isClickable = Boolean(card.clickable);
                return (
                  <button
                    key={card.label}
                    type="button"
                    onClick={() => {
                      if (isClickable) {
                        setShowStatusPrompt(true);
                        setSendError("");
                      }
                    }}
                    className={`rounded-2xl border border-black/15 bg-white/80 p-5 text-left shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur transition ${
                      isClickable
                        ? "hover:border-black/40"
                        : "cursor-default"
                    }`}
                    disabled={!isClickable}
                  >
                    <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                      {card.label}
                    </p>
                    <p className="mt-3 text-lg font-semibold">{card.value}</p>
                  </button>
                );
              })}
            </section>

            <section className="rounded-3xl border border-black/15 bg-white/85 p-6 shadow-[0_26px_60px_rgba(10,10,10,0.2)] backdrop-blur">
              <h2 className={`${dmSerif.className} text-2xl`}>Stavke</h2>
              {groupedItems.length ? (
                <div className="mt-4 space-y-4">
                  <div className="sticky top-4 z-10 flex items-center justify-between rounded-full border border-black/15 bg-white/90 px-4 py-2 text-xs uppercase tracking-[0.25em] text-black/60 shadow-[0_12px_30px_rgba(10,10,10,0.1)]">
                    <button
                      onClick={() => {
                        const next = Math.max(activeGroupIndex - 1, 0);
                        const label = groupedItems[next]?.[0] as string;
                        if (label && groupRefs.current[label]) {
                          groupRefs.current[label]?.scrollIntoView({
                            behavior: "smooth",
                            block: "start",
                          });
                        }
                      }}
                      className="rounded-full border border-black/20 bg-white/5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-black/70"
                    >
                      ◀
                    </button>
                    <span className="text-[11px] uppercase tracking-[0.25em] text-black/70">
                      {activeGroupLabel}
                    </span>
                    <button
                      onClick={() => {
                        const next = Math.min(
                          activeGroupIndex + 1,
                          groupedItems.length - 1
                        );
                        const label = groupedItems[next]?.[0] as string;
                        if (label && groupRefs.current[label]) {
                          groupRefs.current[label]?.scrollIntoView({
                            behavior: "smooth",
                            block: "start",
                          });
                        }
                      }}
                      className="rounded-full border border-black/20 bg-white/5 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-black/70"
                    >
                      ▶
                    </button>
                  </div>
                  {groupedItems.map(([group, items]: [string, PurchaseOrder["items"]]) => (
                    <div
                      key={group}
                      ref={(node) => {
                        groupRefs.current[group] = node;
                      }}
                      className="space-y-3"
                    >
                      <div className="flex items-center justify-between">
                        <p className="text-xs uppercase tracking-[0.25em] text-black/50">
                          {group}
                        </p>
                        <span className="text-xs text-black/50">
                          {items.length} stavki
                        </span>
                      </div>
                      {items.map((item) => (
                        <div
                          key={item.id}
                          className="rounded-2xl border border-black/10 bg-white/70 px-4 py-3"
                        >
                          <p className="text-sm font-semibold">{item.name}</p>
                          <p className="text-xs text-black/60">
                            {item.quantity} {item.unitName || ""} ·{" "}
                            {formatEuro(item.price)}
                          </p>
                          <p className="mt-1 text-xs text-black/60">
                            Ukupno:{" "}
                            {item.price !== null
                              ? formatEuro(item.quantity * item.price)
                              : "-"}
                          </p>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-4">
                  <EmptyState message="Nema stavki u narudzbi." />
                </div>
              )}
            </section>

            <section className="grid gap-4 md:grid-cols-3">
              {[
                {
                  label: "Total net",
                  value: formatEuro(order.totalNet),
                },
                {
                  label: "Total gross",
                  value: formatEuro(order.totalGross),
                },
                {
                  label: "Povratna naknada",
                  value: formatEuro(order.totalDeposit),
                },
              ].map((card) => (
                <div
                  key={card.label}
                  className="rounded-2xl border border-black/15 bg-black px-5 py-4 text-white shadow-[0_18px_40px_rgba(10,10,10,0.28)]"
                >
                  <p className="text-xs uppercase tracking-[0.2em] text-white/60">
                    {card.label}
                  </p>
                  <p className="mt-2 text-lg font-semibold">{card.value}</p>
                </div>
              ))}
            </section>
          </>
        ) : null}
      </div>
      {showStatusPrompt && order ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-6">
          <div className="w-full max-w-md rounded-3xl border border-black/15 bg-white p-6 shadow-[0_30px_60px_rgba(10,10,10,0.3)]">
            <h3 className={`${dmSerif.className} text-2xl`}>
              Status narudžbe
            </h3>
            <p className="mt-2 text-sm text-black/60">
              Želiš li urediti narudžbu ili je poslati dobavljaču?
            </p>
            {sendError ? (
              <p className="mt-3 text-sm text-red-600">{sendError}</p>
            ) : null}
            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <button
                onClick={() => setShowStatusPrompt(false)}
                className="flex-1 rounded-full border border-black/20 px-4 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
              >
                Zatvori
              </button>
              <Link
                href={`/purchase-orders/${order.id}/edit`}
                className="flex-1 rounded-full border border-black/20 px-4 py-2 text-center text-xs uppercase tracking-[0.2em] text-black/70"
              >
                Uredi
              </Link>
              <button
                onClick={async () => {
                  setSending(true);
                  setSendError("");
                  try {
                    await apiPostJson(
                      `/api/purchase-orders/${order.id}/send/`,
                      undefined,
                      { csrf: true }
                    );
                    setShowStatusPrompt(false);
                    await loadOrder();
                  } catch (err) {
                    setSendError(
                      err instanceof Error
                        ? err.message
                        : "Slanje narudzbe nije uspjelo."
                    );
                  } finally {
                    setSending(false);
                  }
                }}
                disabled={sending}
                className="flex-1 rounded-full bg-[#f27323] px-4 py-2 text-xs uppercase tracking-[0.2em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] disabled:opacity-60"
              >
                {sending ? "Slanje..." : "Pošalji"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
