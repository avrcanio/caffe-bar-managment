"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiGetJson, apiPostJson } from "@/lib/api";
import { formatEuro } from "@/lib/format";
import SendPromptModal from "@/components/SendPromptModal";
import ToastBanner from "@/components/ToastBanner";
import {
  mapSupplierArtikli,
  mapSuppliers,
  mapPaymentTypes,
  Supplier,
  SupplierArtikl,
  SupplierArtiklDTO,
  SupplierDTO,
  PaymentType,
  PaymentTypeDTO,
} from "@/lib/mappers";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

type CartItem = SupplierArtikl & { key: string; quantity: string };

export default function NewPurchaseOrderPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [paymentTypes, setPaymentTypes] = useState<PaymentType[]>([]);
  const [paymentTypeId, setPaymentTypeId] = useState("");
  const [artikli, setArtikli] = useState<SupplierArtikl[]>([]);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [cart, setCart] = useState<CartItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [showSendPrompt, setShowSendPrompt] = useState(false);
  const [toast, setToast] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const groupRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const itemRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const quantityRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const [activeGroupIndex, setActiveGroupIndex] = useState(0);
  const pageEndRef = useRef<HTMLDivElement | null>(null);
  const router = useRouter();

  useEffect(() => {
    const run = async () => {
      try {
        const data = await apiGetJson<SupplierDTO[]>("/api/suppliers/");
        setSuppliers(mapSuppliers(data || []));
      } catch (err) {
        setError("Ne mogu ucitati dobavljace.");
      }
    };
    run();
  }, []);

  useEffect(() => {
    const run = async () => {
      try {
        const data = await apiGetJson<PaymentTypeDTO[]>(
          "/api/payment-types/"
        );
        setPaymentTypes(mapPaymentTypes(data || []));
      } catch (err) {
        setPaymentTypes([]);
      }
    };
    run();
  }, []);

  useEffect(() => {
    const run = async () => {
      if (!supplierId) {
        setArtikli([]);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const data = await apiGetJson<{ results?: SupplierArtiklDTO[] }>(
          `/api/suppliers/${supplierId}/artikli/`
        );
        setArtikli(mapSupplierArtikli(data.results || []));
      } catch (err) {
        setError("Ne mogu ucitati artikle za dobavljaca.");
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [supplierId]);

  const addToCart = (item: SupplierArtikl) => {
    const key = `${item.id}-${item.unitId ?? "none"}`;
    const qty = quantities[key];
    if (!item.unitId) {
      setSaveError("Artikl nema jedinicu mjere.");
      return;
    }
    if (!qty || Number(qty) <= 0) {
      return;
    }
    setCart((prev) => {
      const existing = prev.find((entry) => entry.key === key);
      if (existing) {
        return prev.map((entry) =>
          entry.key === key ? { ...entry, quantity: qty } : entry
        );
      }
      return [...prev, { ...item, key, quantity: qty }];
    });
    setToast({ type: "success", message: "Artikl dodan." });
    setTimeout(() => setToast(null), 2000);
  };

  const removeFromCart = (key: string) => {
    setCart((prev) => prev.filter((entry) => entry.key !== key));
    setQuantities((prev) => {
      if (!(key in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setToast({ type: "success", message: "Artikl dodan." });
    setTimeout(() => setToast(null), 2000);
  };

  const handleCreate = async () => {
    if (!supplierId) {
      setSaveError("Odaberi dobavljaca prije spremanja.");
      return;
    }
    if (!paymentTypeId) {
      setSaveError("Odaberi tip placanja prije spremanja.");
      return;
    }
    if (cart.length === 0) {
      setSaveError("Dodaj barem jednu stavku.");
      return;
    }
    setSaveError("");
    setSaving(true);
    try {
      const payload = await apiPostJson<{ id?: number }>(
        "/api/purchase-orders/",
        {
          supplier: Number(supplierId),
          payment_type: paymentTypeId ? Number(paymentTypeId) : null,
          items: cart.map((item) => ({
            artikl: item.id,
            unit_of_measure: item.unitId,
            quantity: item.quantity,
            price: item.price ?? null,
          })),
        },
        { csrf: true }
      );
      setSavedId(payload?.id || null);
      setCart([]);
      setShowSendPrompt(true);
    } catch (err) {
      const data =
        err && typeof err === "object" && "data" in err
          ? (err as { data?: unknown }).data
          : null;
      if (data && typeof data === "object") {
        const detail =
          "detail" in data &&
          typeof (data as { detail?: unknown }).detail === "string"
            ? (data as { detail?: string }).detail
            : Object.entries(data)
                .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
                .join("; ");
        setSaveError(detail || "Neuspjesno spremanje purchase ordera.");
      } else if (err instanceof Error) {
        setSaveError(err.message || "Neuspjesno spremanje purchase ordera.");
      } else {
        setSaveError("Neuspjesno spremanje purchase ordera.");
      }
    } finally {
      setSaving(false);
    }
  };

  const cartTotal = useMemo(() => {
    return cart.reduce((sum, item) => {
      if (!item.price) {
        return sum;
      }
      return sum + Number(item.price) * Number(item.quantity || 0);
    }, 0);
  }, [cart]);

  const groupedArtikli = useMemo(() => {
    const groups: Record<string, SupplierArtikl[]> = {};
    for (const item of artikli) {
      const key = item.baseGroup || "Ostalo";
      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(item);
    }
    return Object.entries(groups)
      .map(([group, items]) => [
        group,
        items
          .slice()
          .sort((a, b) => a.name.localeCompare(b.name, "hr", { sensitivity: "base" })),
      ])
      .sort(([a], [b]) => (a as string).localeCompare(b as string, "hr", { sensitivity: "base" }));
  }, [artikli]);

  useEffect(() => {
    if (!groupedArtikli.length) {
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

    groupedArtikli.forEach(([group], index) => {
      const groupKey = group as string;
      const node = groupRefs.current[groupKey];
      if (node) {
        node.setAttribute("data-index", String(index));
        observer.observe(node);
      }
    });

    return () => observer.disconnect();
  }, [groupedArtikli]);

  const activeGroupLabel =
    (groupedArtikli[activeGroupIndex]?.[0] as string) || "Ostalo";

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <ToastBanner toast={toast} />
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-6 py-12">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-sm uppercase tracking-[0.3em] text-black/60">
              Nova Narudžba
            </p>
            
          </div>
          <Link
            href="/purchase-orders"
            className="rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
          >
            Povratak
          </Link>
        </header>

        <section className="rounded-3xl border border-black/15 bg-white/85 p-6 shadow-[0_26px_60px_rgba(10,10,10,0.2)] backdrop-blur">
          <label className="text-xs uppercase tracking-[0.2em] text-black/50">
            Dobavljac
          </label>
          <select
            value={supplierId}
            onChange={(event) => setSupplierId(event.target.value)}
            className="mt-2 w-full rounded-xl border border-black/20 bg-white px-4 py-3 text-sm"
          >
            <option value="">Odaberi dobavljaca...</option>
            {suppliers.map((supplier) => (
              <option key={supplier.id} value={supplier.id}>
                {supplier.name}
              </option>
            ))}
          </select>
          {error ? (
            <p className="mt-3 text-sm text-red-600">{error}</p>
          ) : null}
        </section>

        <section className="grid gap-6 lg:grid-cols-[1.3fr_0.7fr]">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className={`${dmSerif.className} text-2xl`}>Artikli</h2>
              <span className="text-xs uppercase tracking-[0.3em] text-black/50">
                {loading ? "Ucitavanje" : `${artikli.length} dostupno`}
              </span>
            </div>
            {groupedArtikli.length ? (
              <div className="sticky top-4 z-10 flex items-center justify-between rounded-full border border-black/15 bg-white/90 px-4 py-2 text-xs uppercase tracking-[0.25em] text-black/60 shadow-[0_12px_30px_rgba(10,10,10,0.1)]">
                <button
                  onClick={() => {
                    const next = Math.max(activeGroupIndex - 1, 0);
                    const label = groupedArtikli[next]?.[0] as string;
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
                      groupedArtikli.length - 1
                    );
                    const label = groupedArtikli[next]?.[0] as string;
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
            ) : null}
            <div className="space-y-4">
              {groupedArtikli.map(([group, items]) => (
                <div
                  key={group as string}
                  ref={(node) => {
                    groupRefs.current[group as string] = node;
                  }}
                  className="space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <p className="text-xs uppercase tracking-[0.25em] text-black/50">
                      {group as string}
                    </p>
                    <span className="text-xs text-black/50">
                      {items.length} artikala
                    </span>
                  </div>
                  {(items as SupplierArtikl[]).map((item) => {
                    const key = `${item.id}-${item.unitId ?? "none"}`;
                    return (
                      <div
                        key={key}
                        ref={(node) => {
                          itemRefs.current[key] = node;
                        }}
                        className="rounded-2xl border border-black/10 bg-white/70 p-4"
                      >
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div className="flex items-center gap-4">
                            <div className="h-[77px] w-[48px] overflow-hidden rounded-xl border border-black/10 bg-white">
                              {item.image46x75 ? (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img
                                  src={item.image46x75}
                                  alt={item.name}
                                  className="h-full w-full object-cover"
                                />
                              ) : (
                                <div className="flex h-full w-full items-center justify-center text-xs text-black/40">
                                  no image
                                </div>
                              )}
                            </div>
                            <div>
                              <p className="text-sm font-semibold">{item.name}</p>
                              <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                                {item.code || "code"} ·{" "}
                                {item.baseGroup || "base group"}
                              </p>
                              <p className="text-xs text-black/60">
                                JM: {item.unitName || "?"} · Cijena:{" "}
                                {formatEuro(item.price)}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-3">
                            <input
                              type="number"
                              min="0"
                              step="1"
                              inputMode="numeric"
                              pattern="[0-9]*"
                              value={quantities[key] || ""}
                              ref={(node) => {
                                quantityRefs.current[key] = node;
                              }}
                              onChange={(event) =>
                                setQuantities((prev) => ({
                                  ...prev,
                                  [key]: event.target.value.replace(/\D/g, ""),
                                }))
                              }
                              className="w-24 rounded-lg border border-black/15 bg-white px-3 py-2 text-sm"
                              placeholder="Kolicina"
                            />
                            <button
                              onClick={() => addToCart(item)}
                              className="rounded-full bg-[#f27323] px-4 py-2 text-xs uppercase tracking-[0.2em] text-black"
                            >
                              Dodaj
                            </button>
                          </div>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2 text-xs text-black/60">
                          {(item.stocks || []).map((stock) => (
                            <span
                              key={`${stock.warehouseId}-${item.id}`}
                              className="rounded-full border border-black/10 bg-white/60 px-3 py-1"
                            >
                              {stock.warehouseName}: {stock.quantity}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
              {!loading && artikli.length === 0 ? (
                <div className="rounded-2xl border border-black/10 bg-white/70 p-4 text-sm text-black/60">
                  Nema artikala za odabranog dobavljaca.
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-3xl border border-black/15 bg-white/85 p-6 shadow-[0_26px_60px_rgba(10,10,10,0.2)]">
            <h2 className={`${dmSerif.className} text-2xl`}>Stavke</h2>
            <p className="mt-2 text-sm text-black/60">
              Dodane stavke na novi purchase order.
            </p>
            <div className="mt-4 space-y-3">
              {cart.map((item) => (
                <div
                  key={item.key}
                  onClick={() => {
                    const target = itemRefs.current[item.key];
                    if (target) {
                      target.scrollIntoView({
                        behavior: "smooth",
                        block: "center",
                      });
                    }
                    const input = quantityRefs.current[item.key];
                    if (input) {
                      input.focus();
                      input.select();
                    }
                  }}
                  className="cursor-pointer rounded-2xl border border-black/10 bg-white/70 px-4 py-3 transition hover:border-black/30"
                >
                  <p className="text-sm font-semibold">{item.name}</p>
                  <p className="text-xs text-black/60">
                    {item.quantity} {item.unitName || ""} ·{" "}
                    {formatEuro(item.price)}
                  </p>
                  <p className="mt-1 text-xs text-black/60">
                    Ukupno:{" "}
                    {item.price !== null
                      ? formatEuro(
                          Number(item.quantity || 0) * Number(item.price || 0)
                        )
                      : "-"}
                  </p>
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      removeFromCart(item.key);
                    }}
                    className="mt-2 rounded-full border border-black/15 bg-white/70 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-black/60"
                  >
                    Ukloni
                  </button>
                </div>
              ))}
              {cart.length === 0 ? (
                <p className="text-sm text-black/60">
                  Jos nema dodanih stavki.
                </p>
              ) : null}
            </div>
            <div className="mt-6 rounded-2xl border border-black/10 bg-black px-4 py-3 text-sm text-white">
              Procijenjeni total: {formatEuro(cartTotal)}
            </div>
            <div className="mt-4">
              <label className="text-xs uppercase tracking-[0.2em] text-black/50">
                Tip placanja
              </label>
              <select
                value={paymentTypeId}
                onChange={(event) => setPaymentTypeId(event.target.value)}
                className="mt-2 w-full rounded-xl border border-black/20 bg-white px-4 py-3 text-sm"
              >
                <option value="">Odaberi tip placanja</option>
                {paymentTypes.map((type) => (
                  <option key={type.id} value={type.id}>
                    {type.name}
                  </option>
                ))}
              </select>
            </div>
            {saveError ? (
              <p className="mt-3 text-sm text-red-600">{saveError}</p>
            ) : null}
            {savedId ? (
              <p className="mt-3 text-sm text-green-700">
                Purchase order kreiran: PO-{savedId}
              </p>
            ) : null}
            <button
              onClick={handleCreate}
              disabled={saving}
              className="mt-4 w-full rounded-full bg-[#f27323] px-4 py-3 text-xs uppercase tracking-[0.3em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] disabled:opacity-60"
            >
              {saving ? "Spremanje..." : "Spremi Narudžbu"}
            </button>
          </div>
        </section>
      </div>
      {artikli.length > 0 ? (
        <button
          type="button"
          onClick={() =>
            pageEndRef.current?.scrollIntoView({ behavior: "smooth" })
          }
          className="fixed bottom-6 right-6 z-40 rounded-full border border-black/20 bg-white/80 px-4 py-3 text-[10px] uppercase tracking-[0.2em] text-black/70 shadow-[0_12px_24px_rgba(10,10,10,0.2)]"
        >
          Na kraj
        </button>
      ) : null}
      <div ref={pageEndRef} />
      <SendPromptModal
        open={showSendPrompt}
        orderId={savedId}
        onClose={() => {
          setShowSendPrompt(false);
          router.push("/purchase-orders");
        }}
        onSent={() => router.push("/purchase-orders")}
        showStatusInModal={false}
      />
    </main>
  );
}
