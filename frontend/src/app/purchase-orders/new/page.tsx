"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiGetJson, apiPostJson } from "@/lib/api";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

type Supplier = {
  id: number;
  name: string;
  rm_id: number;
};

type StockRow = {
  warehouse_id: number | null;
  warehouse_name: string;
  quantity: string;
};

type SupplierArtikl = {
  artikl_id: number;
  artikl_rm_id: number | null;
  name: string;
  code: string | null;
  image: string | null;
  base_group: string | null;
  unit_of_measure: number | null;
  unit_name: string | null;
  price: string | null;
  stocks: StockRow[];
};

type CartItem = SupplierArtikl & { key: string; quantity: string };

export default function NewPurchaseOrderPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [artikli, setArtikli] = useState<SupplierArtikl[]>([]);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [cart, setCart] = useState<CartItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [showSendPrompt, setShowSendPrompt] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [sendError, setSendError] = useState("");
  const [sendSuccess, setSendSuccess] = useState("");
  const [toast, setToast] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const router = useRouter();

  useEffect(() => {
    const run = async () => {
      try {
        const data = await apiGetJson<Supplier[]>("/api/suppliers/");
        setSuppliers(data || []);
      } catch (err) {
        setError("Ne mogu ucitati dobavljace.");
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
        const data = await apiGetJson<{ results?: SupplierArtikl[] }>(
          `/api/suppliers/${supplierId}/artikli/`
        );
        setArtikli(data.results || []);
      } catch (err) {
        setError("Ne mogu ucitati artikle za dobavljaca.");
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [supplierId]);

  const addToCart = (item: SupplierArtikl) => {
    const key = `${item.artikl_id}-${item.unit_of_measure ?? "none"}`;
    const qty = quantities[key];
    if (!item.unit_of_measure) {
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
  };

  const removeFromCart = (key: string) => {
    setCart((prev) => prev.filter((entry) => entry.key !== key));
  };

  const handleCreate = async () => {
    if (!supplierId) {
      setSaveError("Odaberi dobavljaca prije spremanja.");
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
          items: cart.map((item) => ({
            artikl: item.artikl_id,
            unit_of_measure: item.unit_of_measure,
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

  const handleSend = async () => {
    if (!savedId) {
      return;
    }
    setSendingEmail(true);
    setSendError("");
    setSendSuccess("");
    try {
      await apiPostJson(
        `/api/purchase-orders/${savedId}/send/`,
        undefined,
        { csrf: true }
      );
      const successMessage = "Narudzba je poslana dobavljacu.";
      setSendSuccess(successMessage);
      setToast({ type: "success", message: successMessage });
      setShowSendPrompt(false);
      setTimeout(() => {
        router.push(`/purchase-orders/${savedId}`);
      }, 1200);
    } catch (err) {
      const detail =
        err instanceof Error
          ? err.message
          : "Slanje narudzbe nije uspjelo.";
      setSendError(detail);
      setToast({ type: "error", message: detail });
    } finally {
      setSendingEmail(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      {toast ? (
        <div className="fixed left-1/2 top-6 z-50 w-[min(90vw,420px)] -translate-x-1/2">
          <div
            className={`rounded-2xl px-4 py-3 text-sm shadow-[0_20px_40px_rgba(10,10,10,0.25)] ${
              toast.type === "success"
                ? "bg-black text-white"
                : "bg-red-600 text-white"
            }`}
          >
            {toast.message}
          </div>
        </div>
      ) : null}
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-6 py-12">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-sm uppercase tracking-[0.3em] text-black/60">
              Novi purchase order
            </p>
            <h1 className={`${dmSerif.className} text-4xl`}>
              Odabir artikala po dobavljacu
            </h1>
          </div>
          <Link
            href="/"
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
            <div className="space-y-4">
              {artikli.map((item) => {
                const key = `${item.artikl_id}-${item.unit_of_measure ?? "none"}`;
                return (
                  <div
                    key={key}
                    className="rounded-2xl border border-black/10 bg-white/70 p-4"
                  >
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex items-center gap-4">
                        <div className="h-[77px] w-[48px] overflow-hidden rounded-xl border border-black/10 bg-white">
                          {item.image ? (
                            <img
                              src={item.image}
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
                            {item.base_group || "base group"}
                          </p>
                          <p className="text-xs text-black/60">
                            JM: {item.unit_name || "?"} · Cijena:{" "}
                            {item.price || "-"} EUR
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={quantities[key] || ""}
                          onChange={(event) =>
                            setQuantities((prev) => ({
                              ...prev,
                              [key]: event.target.value,
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
                          key={`${stock.warehouse_id}-${item.artikl_id}`}
                          className="rounded-full border border-black/10 bg-white/60 px-3 py-1"
                        >
                          {stock.warehouse_name}: {stock.quantity}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
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
                  className="rounded-2xl border border-black/10 bg-white/70 px-4 py-3"
                >
                  <p className="text-sm font-semibold">{item.name}</p>
                  <p className="text-xs text-black/60">
                    {item.quantity} {item.unit_name || ""} ·{" "}
                    {item.price || "-"} EUR
                  </p>
                  <button
                    onClick={() => removeFromCart(item.key)}
                    className="mt-2 text-xs uppercase tracking-[0.2em] text-black/60"
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
              Procijenjeni total: {cartTotal.toFixed(2)} EUR
            </div>
            {saveError ? (
              <p className="mt-3 text-sm text-red-600">{saveError}</p>
            ) : null}
            {savedId ? (
              <p className="mt-3 text-sm text-green-700">
                Purchase order kreiran: PO-{savedId}
              </p>
            ) : null}
            {sendError ? (
              <p className="mt-3 text-sm text-red-600">{sendError}</p>
            ) : null}
            {sendSuccess ? (
              <p className="mt-3 text-sm text-green-700">{sendSuccess}</p>
            ) : null}
            <button
              onClick={handleCreate}
              disabled={saving}
              className="mt-4 w-full rounded-full bg-[#f27323] px-4 py-3 text-xs uppercase tracking-[0.3em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] disabled:opacity-60"
            >
              {saving ? "Spremanje..." : "Spremi PO"}
            </button>
          </div>
        </section>
      </div>
      {showSendPrompt ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-6">
          <div className="w-full max-w-md rounded-3xl border border-black/15 bg-white p-6 shadow-[0_30px_60px_rgba(10,10,10,0.3)]">
            <h3 className={`${dmSerif.className} text-2xl`}>
              Poslati narudzbu?
            </h3>
            <p className="mt-2 text-sm text-black/60">
              Zelis li odmah poslati narudzbu dobavljacu emailom?
            </p>
            <div className="mt-6 flex gap-3">
              <button
                onClick={() => setShowSendPrompt(false)}
                className="flex-1 rounded-full border border-black/20 px-4 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
              >
                Ne
              </button>
              <button
                onClick={handleSend}
                disabled={sendingEmail}
                className="flex-1 rounded-full bg-[#f27323] px-4 py-2 text-xs uppercase tracking-[0.2em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] disabled:opacity-60"
              >
                {sendingEmail ? "Slanje..." : "Da, posalji"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
