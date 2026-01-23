"use client";

import { useEffect, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { useParams } from "next/navigation";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

type PurchaseOrderItem = {
  id: number;
  artikl_name?: string | null;
  quantity: string;
  unit_name?: string | null;
  price?: string | null;
};

type PurchaseOrder = {
  id: number;
  supplier_name?: string | null;
  status_display?: string | null;
  ordered_at: string;
  total_net: string;
  total_gross: string;
  total_deposit: string;
  items?: PurchaseOrderItem[];
};

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
      const response = await fetch(`/api/purchase-orders/${id}/`, {
        credentials: "include",
      });
      if (!response.ok) {
        setError("Ne mogu ucitati purchase order.");
        setLoading(false);
        return;
      }
      const data = await response.json();
      setOrder(data);
      setLoading(false);
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
              Purchase order
            </p>
            <h1 className={`${dmSerif.className} text-4xl`}>
              PO-{id}
            </h1>
          </div>
          <Link
            href="/"
            className="rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
          >
            Povratak
          </Link>
        </header>

        {loading ? (
          <div className="rounded-2xl border border-black/10 bg-white/70 p-4 text-sm text-black/60">
            Ucitavanje purchase ordera...
          </div>
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
                  value: order.supplier_name || "-",
                },
                {
                  label: "Status",
                  value: order.status_display || "-",
                },
                {
                  label: "Datum",
                  value: new Date(order.ordered_at).toLocaleString(),
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
                      {item.artikl_name || "Artikl"}
                    </p>
                    <p className="text-xs text-black/60">
                      {item.quantity} {item.unit_name || ""} ·{" "}
                      {item.price || "-"} EUR
                    </p>
                  </div>
                ))}
                {order.items && order.items.length === 0 ? (
                  <p className="text-sm text-black/60">
                    Nema stavki u narudzbi.
                  </p>
                ) : null}
              </div>
            </section>

            <section className="grid gap-4 md:grid-cols-3">
              {[
                {
                  label: "Total net",
                  value: `${order.total_net} EUR`,
                },
                {
                  label: "Total gross",
                  value: `${order.total_gross} EUR`,
                },
                {
                  label: "Povratna naknada",
                  value: `${order.total_deposit} EUR`,
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
