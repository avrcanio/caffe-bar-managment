"use client";

import { useEffect, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiGetJson } from "@/lib/api";
import { formatDate, formatEuro } from "@/lib/format";
import EmptyState from "@/components/EmptyState";
import FilterSelect from "@/components/FilterSelect";
import LoadingCard from "@/components/LoadingCard";
import SendPromptModal from "@/components/SendPromptModal";
import {
  mapPurchaseOrderList,
  PurchaseOrder,
  PurchaseOrderListDTO,
  mapSuppliers,
  Supplier,
  SupplierDTO,
} from "@/lib/mappers";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

const STATUS_OPTIONS = [
  { value: "", label: "Svi statusi" },
  { value: "created", label: "Kreirana" },
  { value: "sent", label: "Poslana" },
  { value: "confirmed", label: "Potvrđena" },
  { value: "received", label: "Zaprimljena" },
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
  const [showSendPrompt, setShowSendPrompt] = useState(false);
  const [sendOrderId, setSendOrderId] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const router = useRouter();

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
        const payload = await apiGetJson<PurchaseOrderListDTO>(
          `/api/purchase-orders/?${params.toString()}`
        );
        setOrders(mapPurchaseOrderList(payload).orders);
      } catch (err) {
        setError("Neuspjesno ucitavanje podataka.");
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [statusFilter, supplierFilter, orderedFrom, orderedTo, refreshKey]);

  useEffect(() => {
    const run = async () => {
      try {
        const data = await apiGetJson<SupplierDTO[]>("/api/suppliers/");
        setSuppliers(mapSuppliers(data || []));
      } catch (err) {
        setSuppliers([]);
      }
    };
    run();
  }, []);

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-6 py-12">
        <header className="flex flex-col gap-6">
          <div className="space-y-2">
            <p className="text-sm uppercase tracking-[0.3em] text-black/60">
              Narudžbe
            </p>            
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
          <div className="rounded-3xl border border-black/15 bg-white/85 p-5 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur">
            <div className="flex flex-col gap-2">
              <FilterSelect
                value={statusFilter}
                onChange={setStatusFilter}
                options={STATUS_OPTIONS}
              />
              <FilterSelect
                value={supplierFilter}
                onChange={setSupplierFilter}
                options={[
                  { value: "", label: "Svi dobavljači" },
                  ...suppliers.map((supplier) => ({
                    value: String(supplier.id),
                    label: supplier.name,
                  })),
                ]}
              />
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
        </header>

        <section className="rounded-3xl border border-black/15 bg-white/85 p-6 shadow-[0_26px_60px_rgba(10,10,10,0.2)] backdrop-blur">
          <div className="mt-6 space-y-4">
            {loading ? (
              <LoadingCard message="Ucitavanje purchase ordera..." />
            ) : null}
            {error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
                {error}
              </div>
            ) : null}
            {!loading && !error && orders.length === 0 ? (
              <EmptyState message="Nema purchase ordera." />
            ) : null}
            {orders.map((po) => (
              <div
                key={po.id}
                onClick={() => {
                  setLoadingDetailId(po.id);
                  router.push(`/purchase-orders/${po.id}`);
                }}
                className="grid cursor-pointer grid-cols-1 gap-3 rounded-2xl border border-black/10 bg-white/70 px-4 py-3 transition hover:border-black/30 md:grid-cols-[1.4fr_0.9fr_0.7fr_0.7fr_0.7fr_auto] md:items-center"
              >
                <div>
                  <p className="text-sm font-semibold">PO-{po.id}</p>
                  <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                  {po.supplierName}
                </p>
              </div>
              <p className="text-sm text-black/70 md:text-center">
                {po.statusLabel}
              </p>
              <p className="text-xs uppercase tracking-[0.2em] text-black/50 md:text-center">
                {po.paymentTypeName || "-"}
              </p>
              <p className="text-xs uppercase tracking-[0.2em] text-black/50 md:text-center">
                {formatDate(po.orderedAt)}
              </p>
              <p className="text-sm font-semibold md:text-right">
                {formatEuro(po.totalGross)}
              </p>
                {po.statusCode === "created" ? (
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      setSendOrderId(po.id);
                      setShowSendPrompt(true);
                    }}
                    className="w-full rounded-full border border-black/20 bg-white/80 px-3 py-2 text-[10px] uppercase tracking-[0.2em] text-black/70 md:w-auto"
                  >
                    Posalji
                  </button>
                ) : null}
                {loadingDetailId === po.id ? (
                  <span className="inline-flex h-3 w-3 animate-spin rounded-full border border-black/50 border-t-transparent md:justify-self-end" />
                ) : null}
              </div>
            ))}
          </div>
        </section>
      </div>
      <SendPromptModal
        open={showSendPrompt}
        orderId={sendOrderId}
        onClose={() => {
          setShowSendPrompt(false);
          setSendOrderId(null);
        }}
        onSent={() => setRefreshKey((value) => value + 1)}
      />
    </main>
  );
}
