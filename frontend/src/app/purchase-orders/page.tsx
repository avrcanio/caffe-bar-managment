"use client";

import { useEffect, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { apiGetJson } from "@/lib/api";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

type PurchaseOrder = {
  id: number;
  supplier_name?: string | null;
  status_display?: string | null;
  ordered_at: string;
  total_gross: string;
};

type PurchaseOrderResponse = {
  results: PurchaseOrder[];
};

type Supplier = {
  id: number;
  name: string;
  rm_id: number;
};

const STATUS_OPTIONS = [
  { value: "", label: "Svi statusi" },
  { value: "created", label: "Kreirana" },
  { value: "sent", label: "Poslana" },
  { value: "confirmed", label: "Potvrđena" },
  { value: "received", label: "Primljena" },
  { value: "canceled", label: "Otkazana" },
];

export default function PurchaseOrdersPage() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [supplierFilter, setSupplierFilter] = useState("");
  const [orderedFrom, setOrderedFrom] = useState("");
  const [orderedTo, setOrderedTo] = useState("");
  const [loadingDetailId, setLoadingDetailId] = useState<number | null>(null);

  useEffect(() => {
    const run = async () => {
      try {
        setLoading(true);
        setError("");
        const params = new URLSearchParams({ page_size: "20" });
        if (statusFilter) {
          params.set("status", statusFilter);
        }
        if (supplierFilter) {
          params.set("supplier", supplierFilter);
        }
        if (orderedFrom) {
          params.set("ordered_from", orderedFrom);
        }
        if (orderedTo) {
          params.set("ordered_to", orderedTo);
        }
        const payload = await apiGetJson<PurchaseOrderResponse>(
          `/api/purchase-orders/?${params.toString()}`
        );
        setOrders(payload.results || []);
      } catch (err) {
        setError("Neuspjesno ucitavanje podataka.");
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [statusFilter, supplierFilter, orderedFrom, orderedTo]);

  useEffect(() => {
    const run = async () => {
      try {
        const data = await apiGetJson<Supplier[]>("/api/suppliers/");
        setSuppliers(data || []);
      } catch (err) {
        setSuppliers([]);
      }
    };
    run();
  }, []);

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-6 py-12">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-sm uppercase tracking-[0.3em] text-black/60">
              Purchase orders
            </p>
            <h1 className={`${dmSerif.className} text-4xl`}>Narudžbe</h1>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/"
              className="rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
            >
              Povratak
            </Link>
            <Link
              href="/purchase-orders/new"
              className="rounded-full bg-[#f27323] px-6 py-2 text-xs uppercase tracking-[0.25em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)]"
            >
              Nova
            </Link>
          </div>
        </header>

        <section className="rounded-3xl border border-black/15 bg-white/85 p-6 shadow-[0_26px_60px_rgba(10,10,10,0.2)] backdrop-blur">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                className="w-full max-w-[250px] rounded-full border border-black/20 bg-white px-3 py-1 text-xs uppercase tracking-[0.2em] text-black/70 sm:w-auto"
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <select
                value={supplierFilter}
                onChange={(event) => setSupplierFilter(event.target.value)}
                className="w-full max-w-[250px] rounded-full border border-black/20 bg-white px-3 py-1 text-xs uppercase tracking-[0.2em] text-black/70 sm:w-auto"
              >
                <option value="">Svi dobavljači</option>
                {suppliers.map((supplier) => (
                  <option key={supplier.id} value={supplier.id}>
                    {supplier.name}
                  </option>
                ))}
              </select>
              <input
                type="date"
                value={orderedFrom}
                onChange={(event) => setOrderedFrom(event.target.value)}
                className="w-full max-w-[250px] rounded-full border border-black/20 bg-white px-3 py-1 text-xs uppercase tracking-[0.2em] text-black/70 sm:w-auto"
              />
              <input
                type="date"
                value={orderedTo}
                onChange={(event) => setOrderedTo(event.target.value)}
                className="w-full max-w-[250px] rounded-full border border-black/20 bg-white px-3 py-1 text-xs uppercase tracking-[0.2em] text-black/70 sm:w-auto"
              />
              <button
                onClick={() => {
                  setOrderedFrom("");
                  setOrderedTo("");
                }}
                className="w-full max-w-[250px] rounded-full border border-black/20 bg-white px-3 py-1 text-xs uppercase tracking-[0.2em] text-black/70 sm:w-auto"
              >
                Ocisti datume
              </button>
            </div>
          </div>
          <div className="mt-6 space-y-4">
            {loading ? (
              <div className="rounded-2xl border border-black/10 bg-white/70 px-4 py-4 text-sm text-black/60">
                Ucitavanje purchase ordera...
              </div>
            ) : null}
            {error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
                {error}
              </div>
            ) : null}
            {!loading && !error && orders.length === 0 ? (
              <div className="rounded-2xl border border-black/10 bg-white/70 px-4 py-4 text-sm text-black/60">
                Nema purchase ordera.
              </div>
            ) : null}
            {orders.map((po) => (
              <div
                key={po.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-black/10 bg-white/70 px-4 py-3"
              >
                <div>
                  <p className="text-sm font-semibold">PO-{po.id}</p>
                  <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                    {po.supplier_name || "Dobavljac"}
                  </p>
                </div>
                <p className="text-sm text-black/70">
                  {po.status_display || "Status"}
                </p>
                <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                  {new Date(po.ordered_at).toLocaleDateString()}
                </p>
                <p className="text-sm font-semibold">{po.total_gross} EUR</p>
                <Link
                  href={`/purchase-orders/${po.id}`}
                  onClick={() => setLoadingDetailId(po.id)}
                  className="flex items-center gap-2 rounded-full border border-black/20 px-4 py-1 text-xs uppercase tracking-[0.2em] text-black/70"
                >
                  {loadingDetailId === po.id ? (
                    <span className="inline-flex h-3 w-3 animate-spin rounded-full border border-black/50 border-t-transparent" />
                  ) : null}
                  Detalji
                </Link>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
