"use client";

import { useEffect, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiGetJson } from "@/lib/api";
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
  const id = params?.id as string;
  const [order, setOrder] = useState<PurchaseOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const run = async () => {
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
    };
    if (id) {
      run();
    }
  }, [id]);

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
                },
                {
                  label: "Datum",
                  value: formatDate(order.orderedAt, {
                    dateStyle: "short",
                    timeStyle: "short",
                  }),
                },
              ].map((card) => (
                <div
                  key={card.label}
                  className="rounded-2xl border border-black/15 bg-white/80 p-5 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur"
                >
                  <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                    {card.label}
                  </p>
                  <p className="mt-3 text-lg font-semibold">{card.value}</p>
                </div>
              ))}
            </section>

            <section className="rounded-3xl border border-black/15 bg-white/85 p-6 shadow-[0_26px_60px_rgba(10,10,10,0.2)] backdrop-blur">
              <h2 className={`${dmSerif.className} text-2xl`}>Stavke</h2>
              <div className="mt-4 space-y-3">
                {(order.items || []).map((item) => (
                  <div
                    key={item.id}
                    className="rounded-2xl border border-black/10 bg-white/70 px-4 py-3"
                  >
                    <p className="text-sm font-semibold">
                      {item.name}
                    </p>
                    <p className="text-xs text-black/60">
                      {item.quantity} {item.unitName || ""} ·{" "}
                      {formatEuro(item.price)}
                    </p>
                  </div>
                ))}
                {order.items && order.items.length === 0 ? (
                  <EmptyState message="Nema stavki u narudzbi." />
                ) : null}
              </div>
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
    </main>
  );
}
