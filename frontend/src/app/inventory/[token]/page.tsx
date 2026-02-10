"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

type PublicInventoryItem = {
  id: number;
  artikl_rm_id: number | null;
  artikl_name: string | null;
  artikl_code: string | null;
  image_46x75: string | null;
  quantity: string | null;
  unit_rm_id: number | null;
  unit_name: string | null;
  note: string;
};

type PublicInventory = {
  id: number;
  warehouse_rm_id: number | null;
  warehouse_name: string | null;
  date: string;
  opens_at: string | null;
  closes_at: string | null;
  status: "open" | "counted" | "closed";
  submitted_at: string | null;
  counted_by_name: string | null;
  readonly: boolean;
  items: PublicInventoryItem[];
};

function normalizeQtyInput(raw: string): string {
  return raw.replace(",", ".").trim();
}

export default function InventoryTokenPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token;

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inv, setInv] = useState<PublicInventory | null>(null);
  const [qtyByItemId, setQtyByItemId] = useState<Record<number, string>>({});
  const [noteByItemId, setNoteByItemId] = useState<Record<number, string>>({});
  const [selectedItemId, setSelectedItemId] = useState<number | null>(null);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    if (!token || typeof token !== "string") {
      return;
    }
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await fetch(`/api/inventories/public/${token}/`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        const data = await r.json().catch(() => null);
        if (!r.ok) {
          setInv(null);
          setError((data && (data.detail as string)) || "Ne mogu učitati inventuru.");
          return;
        }
        const parsed = data as PublicInventory;
        setInv(parsed);
        const initial: Record<number, string> = {};
        const initialNotes: Record<number, string> = {};
        for (const it of parsed.items || []) {
          initial[it.id] = it.quantity ?? "";
          initialNotes[it.id] = it.note ?? "";
        }
        setQtyByItemId(initial);
        setNoteByItemId(initialNotes);
      } catch (e) {
        setInv(null);
        setError(e instanceof Error ? e.message : "Ne mogu učitati inventuru.");
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [token]);

  const missingCount = useMemo(() => {
    if (!inv) {
      return 0;
    }
    let missing = 0;
    for (const it of inv.items) {
      const raw = qtyByItemId[it.id] ?? "";
      if (normalizeQtyInput(raw) === "") {
        missing += 1;
      }
    }
    return missing;
  }, [inv, qtyByItemId]);

  const readonly = Boolean(inv?.readonly);
  const selectedItem = useMemo(() => {
    if (!inv || selectedItemId == null) {
      return null;
    }
    return inv.items.find((x) => x.id === selectedItemId) || null;
  }, [inv, selectedItemId]);

  return (
    <main className="min-h-screen bg-[#0e0f12] text-[#f5f1e8]">
      {toast ? (
        <div className="fixed left-1/2 top-5 z-[60] w-[min(92vw,560px)] -translate-x-1/2">
          <div
            className={`rounded-2xl px-4 py-3 text-sm shadow-[0_20px_40px_rgba(0,0,0,0.45)] ${
              toast.type === "success" ? "bg-[#f27323] text-black" : "bg-[#e5484d] text-white"
            }`}
          >
            {toast.message}
          </div>
        </div>
      ) : null}

      <div className="mx-auto max-w-3xl px-4 pb-16 pt-8">
        <header className="sticky top-0 z-10 -mx-4 mb-6 border-b border-white/10 bg-[#0e0f12]/90 px-4 pb-4 pt-3 backdrop-blur">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-white/60">
                Inventura
              </p>
              <h1 className="mt-1 text-2xl font-semibold leading-tight">
                {inv?.warehouse_name || "Skladište"}
              </h1>
              <p className="mt-1 text-xs text-white/60">
                {inv ? `ID ${inv.id}` : null}
                {inv?.submitted_at ? ` · Predano` : null}
              </p>
            </div>
            {inv?.submitted_at ? (
              <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-white/70">
                Zaključano
              </span>
            ) : null}
          </div>

          {!readonly ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/70">
                {inv?.counted_by_name ? (
                  <>
                    <span className="text-xs uppercase tracking-[0.18em] text-white/50">Brojao</span>
                    <div className="mt-1 text-sm font-semibold text-white">{inv.counted_by_name}</div>
                  </>
                ) : (
                  <div className="text-xs text-white/60">Brojač nije postavljen (admin).</div>
                )}
              </div>
              <button
                type="button"
                disabled={submitting || loading || !inv || missingCount > 0}
                onClick={async () => {
                  if (!inv || !token || readonly) {
                    return;
                  }
                  if (missingCount > 0) {
                    setToast({ type: "error", message: "Unesi količinu za sve stavke." });
                    setTimeout(() => setToast(null), 2200);
                    return;
                  }
                  setSubmitting(true);
                  setError(null);
                  try {
                    const items = inv.items.map((it) => ({
                      id: it.id,
                      quantity: normalizeQtyInput(qtyByItemId[it.id] ?? ""),
                      note: (noteByItemId[it.id] ?? "").toString(),
                    }));
                    const r = await fetch(`/api/inventories/public/${token}/submit/`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json", Accept: "application/json" },
                      body: JSON.stringify({
                        items,
                      }),
                    });
                    const data = await r.json().catch(() => null);
                    if (!r.ok) {
                      setToast({
                        type: "error",
                        message: (data && (data.detail as string)) || "Submit nije uspio.",
                      });
                      setTimeout(() => setToast(null), 2500);
                      return;
                    }
                    // Re-fetch to get readonly/submitted_at.
                    const r2 = await fetch(`/api/inventories/public/${token}/`, {
                      cache: "no-store",
                      headers: { Accept: "application/json" },
                    });
                    const data2 = await r2.json().catch(() => null);
                    if (r2.ok && data2) {
                      const parsed = data2 as PublicInventory;
                      setInv(parsed);
                      const initial: Record<number, string> = {};
                      const initialNotes: Record<number, string> = {};
                      for (const it of parsed.items || []) {
                        initial[it.id] = it.quantity ?? "";
                        initialNotes[it.id] = it.note ?? "";
                      }
                      setQtyByItemId(initial);
                      setNoteByItemId(initialNotes);
                    }
                    setToast({ type: "success", message: "Predano. Hvala." });
                    setTimeout(() => setToast(null), 2500);
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "Submit nije uspio.");
                  } finally {
                    setSubmitting(false);
                  }
                }}
                className="h-[46px] rounded-2xl bg-[#f27323] px-5 text-sm font-semibold text-black shadow-[0_18px_40px_rgba(242,115,35,0.25)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? "Predajem..." : missingCount > 0 ? `Nedostaje: ${missingCount}` : "Submit"}
              </button>
            </div>
          ) : (
            <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/70">
              Inventura je predana. Za izmjene se javi administratoru.
            </div>
          )}
        </header>

        {loading ? (
          <div className="rounded-3xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
            Učitavanje...
          </div>
        ) : error ? (
          <div className="rounded-3xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
            {error}
          </div>
        ) : !inv ? (
          <div className="rounded-3xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
            Inventura nije pronađena.
          </div>
        ) : (
          <section className="space-y-3">
            {inv.items.map((it) => {
              const value = qtyByItemId[it.id] ?? "";
              const note = noteByItemId[it.id] ?? "";
              const hasNote = note.trim().length > 0;
              return (
                <div
                  key={it.id}
                  className="flex cursor-pointer items-center gap-4 rounded-3xl border border-white/10 bg-white/5 p-4 transition hover:border-white/20"
                  onClick={() => setSelectedItemId(it.id)}
                >
                  <div className="h-[60px] w-[46px] overflow-hidden rounded-xl border border-white/10 bg-black/20">
                    {it.image_46x75 ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={it.image_46x75}
                        alt={it.artikl_name || "Artikl"}
                        className="h-full w-full object-cover"
                        loading="lazy"
                      />
                    ) : null}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold leading-snug text-white/95">
                      {it.artikl_name || "Artikl"}
                    </p>
                    <p className="mt-1 text-xs text-white/55">
                      {it.artikl_code ? `Kod: ${it.artikl_code}` : null}
                      {it.unit_name ? ` · ${it.unit_name}` : null}
                    </p>
                    {note ? (
                      <p className="mt-1 line-clamp-1 text-xs text-white/55">
                        Napomena: {note}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    {readonly && hasNote ? (
                      <div
                        title="Ima napomenu"
                        className="mb-1 inline-flex items-center gap-1 rounded-full border border-[#f27323]/25 bg-[#f27323]/10 px-2 py-0.5 text-[11px] text-[#f7b98f]"
                      >
                        <span aria-hidden="true">📝</span>
                        <span>note</span>
                      </div>
                    ) : null}
                    <input
                      value={value}
                      onChange={(e) => {
                        const raw = e.target.value;
                        setQtyByItemId((prev) => ({ ...prev, [it.id]: raw }));
                      }}
                      onClick={(e) => e.stopPropagation()}
                      disabled={readonly}
                      inputMode="decimal"
                      placeholder="0"
                      className="w-[120px] rounded-2xl border border-white/10 bg-black/20 px-3 py-2 text-right text-sm text-white outline-none placeholder:text-white/35 focus:border-white/25 disabled:opacity-60"
                    />
                    {!readonly ? (
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            setQtyByItemId((prev) => ({ ...prev, [it.id]: "0" }))
                          }
                          onClickCapture={(e) => e.stopPropagation()}
                          className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70"
                        >
                          0
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const n = Number(normalizeQtyInput(value || "0") || "0");
                            const next = Number.isFinite(n) ? (n + 1).toString() : "1";
                            setQtyByItemId((prev) => ({ ...prev, [it.id]: next }));
                          }}
                          onClickCapture={(e) => e.stopPropagation()}
                          className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70"
                        >
                          +1
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </section>
        )}
      </div>

      {selectedItem ? (
        <div
          className="fixed inset-0 z-[80] flex items-end justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setSelectedItemId(null)}
        >
          <div
            className="w-full max-w-3xl rounded-t-[28px] border border-white/10 bg-[#111319] p-5 shadow-[0_-30px_80px_rgba(0,0,0,0.6)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="flex min-w-0 gap-4">
                <div className="h-[96px] w-[64px] overflow-hidden rounded-2xl border border-white/10 bg-black/20">
                  {selectedItem.image_46x75 ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={selectedItem.image_46x75}
                      alt={selectedItem.artikl_name || "Artikl"}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  ) : null}
                </div>
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-[0.22em] text-white/55">Artikl</p>
                  <h2 className="mt-1 break-words text-lg font-semibold leading-snug text-white">
                    {selectedItem.artikl_name || "Artikl"}
                  </h2>
                  <p className="mt-2 text-sm text-white/65">
                    {selectedItem.artikl_code ? `Kod: ${selectedItem.artikl_code}` : null}
                    {selectedItem.unit_name ? ` · ${selectedItem.unit_name}` : null}
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-xs text-white/70"
                onClick={() => setSelectedItemId(null)}
              >
                Zatvori
              </button>
            </div>

            <div className="grid gap-4 sm:grid-cols-[220px_1fr]">
              <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-white/50">Količina</p>
                <div className="mt-3 flex items-center gap-3">
                  <input
                    value={qtyByItemId[selectedItem.id] ?? ""}
                    onChange={(e) =>
                      setQtyByItemId((prev) => ({ ...prev, [selectedItem.id]: e.target.value }))
                    }
                    disabled={readonly}
                    inputMode="decimal"
                    placeholder="0"
                    className="w-full rounded-2xl border border-white/10 bg-black/25 px-4 py-3 text-right text-lg text-white outline-none placeholder:text-white/35 focus:border-white/25 disabled:opacity-60"
                  />
                </div>
                {!readonly ? (
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      className="flex-1 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/75"
                      onClick={() => setQtyByItemId((prev) => ({ ...prev, [selectedItem.id]: "0" }))}
                    >
                      Postavi 0
                    </button>
                    <button
                      type="button"
                      className="flex-1 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/75"
                      onClick={() => {
                        const cur = normalizeQtyInput(qtyByItemId[selectedItem.id] ?? "") || "0";
                        const n = Number(cur);
                        const next = Number.isFinite(n) ? (n + 1).toString() : "1";
                        setQtyByItemId((prev) => ({ ...prev, [selectedItem.id]: next }));
                      }}
                    >
                      +1
                    </button>
                  </div>
                ) : null}
              </div>

              <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-white/50">Napomena</p>
                <textarea
                  value={noteByItemId[selectedItem.id] ?? ""}
                  onChange={(e) =>
                    setNoteByItemId((prev) => ({ ...prev, [selectedItem.id]: e.target.value }))
                  }
                  disabled={readonly}
                  placeholder="npr. jedna boca je otvorena"
                  className="mt-3 h-[120px] w-full resize-none rounded-2xl border border-white/10 bg-black/25 px-4 py-3 text-sm text-white outline-none placeholder:text-white/35 focus:border-white/25 disabled:opacity-60"
                />
                {!readonly ? (
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      className="rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-xs text-white/70"
                      onClick={() => setNoteByItemId((prev) => ({ ...prev, [selectedItem.id]: "" }))}
                    >
                      Obriši napomenu
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
