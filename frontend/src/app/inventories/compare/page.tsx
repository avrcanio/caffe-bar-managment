"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { DM_Serif_Display } from "next/font/google";
import { apiGetJson } from "@/lib/api";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

type InventoryDTO = {
  id: number;
  name: string;
  note: string;
  warehouse: number | null;
  warehouse_name: string | null;
  date: string;
  created_by: string | null;
  counted_by: number | null;
  counted_by_name: string | null;
};

type InventoryItemDTO = {
  id: number;
  inventory: number;
  artikl: number | null; // rm_id
  artikl_name: string | null;
  quantity: string | null;
  unit: number | null; // rm_id
  unit_name: string | null;
  note: string;
};

type Qty = bigint | null; // scaled by 10^4

function parseQty(raw: string | null): Qty {
  if (!raw) return null;
  const s = raw.trim().replace(",", ".");
  if (!s) return null;

  let sign: bigint = 1n;
  let t = s;
  if (t.startsWith("-")) {
    sign = -1n;
    t = t.slice(1);
  }

  const parts = t.split(".");
  const intPart = parts[0] || "0";
  const fracPart = (parts[1] || "").slice(0, 4).padEnd(4, "0");

  if (!/^\d+$/.test(intPart) || (parts.length > 1 && !/^\d*$/.test(parts[1] || ""))) {
    return null;
  }

  const scaled = BigInt(intPart) * 10000n + BigInt(fracPart || "0");
  return sign * scaled;
}

function fmtQty(q: Qty): string {
  if (q == null) return "NULL";
  const sign = q < 0n ? "-" : "";
  const abs = q < 0n ? -q : q;
  const intPart = abs / 10000n;
  const frac = abs % 10000n;
  if (frac === 0n) return `${sign}${intPart.toString()}`;
  const fracStr = frac.toString().padStart(4, "0").replace(/0+$/, "");
  return `${sign}${intPart.toString()}.${fracStr}`;
}

function sumQty(a: Qty, b: Qty): Qty {
  if (a == null || b == null) return null;
  return a + b;
}

type Row = {
  artiklId: number;
  artiklName: string;
  unitName: string | null;
  qtyA: Qty;
  qtyB: Qty;
  diff: Qty;
};

function InventoryCompareInner() {
  const router = useRouter();
  const sp = useSearchParams();

  const initialA = sp?.get("a") || "";
  const initialB = sp?.get("b") || "";

  const [a, setA] = useState(initialA);
  const [b, setB] = useState(initialB);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invA, setInvA] = useState<InventoryDTO | null>(null);
  const [invB, setInvB] = useState<InventoryDTO | null>(null);
  const [itemsA, setItemsA] = useState<InventoryItemDTO[]>([]);
  const [itemsB, setItemsB] = useState<InventoryItemDTO[]>([]);
  const [showSame, setShowSame] = useState(false);

  useEffect(() => {
    // Keep inputs in sync if user edits query in URL.
    setA(initialA);
    setB(initialB);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialA, initialB]);

  useEffect(() => {
    const aId = Number(initialA);
    const bId = Number(initialB);
    if (!Number.isFinite(aId) || !Number.isFinite(bId) || aId <= 0 || bId <= 0) {
      setInvA(null);
      setInvB(null);
      setItemsA([]);
      setItemsB([]);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const [invAData, invBData, itA, itB] = await Promise.all([
          apiGetJson<InventoryDTO>(`/api/inventories/${aId}/`),
          apiGetJson<InventoryDTO>(`/api/inventories/${bId}/`),
          apiGetJson<InventoryItemDTO[]>(`/api/inventory-items/?inventory=${aId}`),
          apiGetJson<InventoryItemDTO[]>(`/api/inventory-items/?inventory=${bId}`),
        ]);
        if (cancelled) return;
        setInvA(invAData);
        setInvB(invBData);
        setItemsA(Array.isArray(itA) ? itA : []);
        setItemsB(Array.isArray(itB) ? itB : []);
      } catch (e) {
        if (cancelled) return;
        setInvA(null);
        setInvB(null);
        setItemsA([]);
        setItemsB([]);
        setError(e instanceof Error ? e.message : "Ne mogu ucitati inventure.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [initialA, initialB]);

  const rows = useMemo((): Row[] => {
    const aggA = new Map<number, { name: string; unitName: string | null; qty: Qty }>();
    const aggB = new Map<number, { name: string; unitName: string | null; qty: Qty }>();

    const add = (
      m: Map<number, { name: string; unitName: string | null; qty: Qty }>,
      it: InventoryItemDTO
    ) => {
      if (it.artikl == null) return;
      const id = it.artikl;
      const q = parseQty(it.quantity);
      const prev = m.get(id);
      const name = (it.artikl_name || "").trim() || `artikl ${id}`;
      const unitName = it.unit_name || null;
      if (!prev) {
        m.set(id, { name, unitName, qty: q });
        return;
      }
      m.set(id, {
        name: prev.name || name,
        unitName: prev.unitName || unitName,
        qty: prev.qty == null ? null : q == null ? null : sumQty(prev.qty, q),
      });
    };

    for (const it of itemsA) add(aggA, it);
    for (const it of itemsB) add(aggB, it);

    const allIds = new Set<number>();
    for (const id of aggA.keys()) allIds.add(id);
    for (const id of aggB.keys()) allIds.add(id);

    const out: Row[] = [];
    for (const id of allIds) {
      const a0 = aggA.get(id);
      const b0 = aggB.get(id);
      const qtyA = a0 ? a0.qty : 0n;
      const qtyB = b0 ? b0.qty : 0n;
      const anyNull = (a0 && a0.qty == null) || (b0 && b0.qty == null);
      const finalA: Qty = a0 ? a0.qty : 0n;
      const finalB: Qty = b0 ? b0.qty : 0n;
      const diff: Qty = anyNull ? null : (finalB ?? 0n) - (finalA ?? 0n);
      const artiklName = (a0?.name || b0?.name || `artikl ${id}`).trim() || `artikl ${id}`;
      const unitName = a0?.unitName || b0?.unitName || null;
      out.push({
        artiklId: id,
        artiklName,
        unitName,
        qtyA: a0 ? a0.qty : 0n,
        qtyB: b0 ? b0.qty : 0n,
        diff,
      });
    }

    out.sort((x, y) => x.artiklName.localeCompare(y.artiklName, "hr"));
    return out;
  }, [itemsA, itemsB]);

  const filteredRows = useMemo(() => {
    if (showSame) return rows;
    return rows.filter((r) => r.diff == null || r.diff !== 0n);
  }, [rows, showSame]);

  const title = useMemo(() => {
    const aId = initialA || "?";
    const bId = initialB || "?";
    return `Usporedba inventura ${aId} vs ${bId}`;
  }, [initialA, initialB]);

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-10">
        <header className="space-y-2">
          <p className="text-xs uppercase tracking-[0.3em] text-black/50">Inventure</p>
          <h1 className={`${dmSerif.className} text-3xl sm:text-4xl`}>{title}</h1>
          <p className="text-sm text-black/60">
            Ucitava stavke preko <span className="font-mono">/api/inventory-items/?inventory=ID</span> i usporeduje po{" "}
            <span className="font-mono">artikl</span> (rm_id).
          </p>
        </header>

        <section className="rounded-2xl border border-black/15 bg-white/80 p-5 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1">
                <div className="text-xs uppercase tracking-[0.2em] text-black/50">Inventory A (id)</div>
                <input
                  value={a}
                  onChange={(e) => setA(e.target.value)}
                  inputMode="numeric"
                  className="w-full rounded-xl border border-black/15 bg-white px-3 py-2 text-sm outline-none focus:border-black/40"
                  placeholder="26"
                />
              </label>
              <label className="space-y-1">
                <div className="text-xs uppercase tracking-[0.2em] text-black/50">Inventory B (id)</div>
                <input
                  value={b}
                  onChange={(e) => setB(e.target.value)}
                  inputMode="numeric"
                  className="w-full rounded-xl border border-black/15 bg-white px-3 py-2 text-sm outline-none focus:border-black/40"
                  placeholder="32"
                />
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <label className="flex select-none items-center gap-2 text-sm text-black/70">
                <input
                  type="checkbox"
                  checked={showSame}
                  onChange={(e) => setShowSame(e.target.checked)}
                />
                Prikazi i iste
              </label>
              <button
                onClick={() => {
                  const aId = String(a || "").trim();
                  const bId = String(b || "").trim();
                  const params = new URLSearchParams();
                  if (aId) params.set("a", aId);
                  if (bId) params.set("b", bId);
                  router.push(`/inventories/compare?${params.toString()}`);
                }}
                className="rounded-full border border-black/20 bg-black px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Usporedi
              </button>
            </div>
          </div>

          {error ? (
            <div className="mt-4 rounded-xl border border-red-600/30 bg-red-50 px-4 py-3 text-sm text-red-800">
              {error}
            </div>
          ) : null}

          {loading ? (
            <div className="mt-4 text-sm text-black/60">Ucitavanje...</div>
          ) : null}

          {!loading && invA && invB ? (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded-2xl border border-black/10 bg-white/70 p-4">
                <div className="text-xs uppercase tracking-[0.2em] text-black/50">A</div>
                <div className="mt-1 text-lg font-semibold">
                  #{invA.id} {invA.name ? `- ${invA.name}` : ""}
                </div>
                <div className="mt-1 text-sm text-black/60">
                  {invA.warehouse_name || "Skladiste ?"} | {new Date(invA.date).toLocaleString("hr-HR")}
                </div>
                <div className="mt-1 text-sm text-black/60">Stavki: {itemsA.length}</div>
              </div>
              <div className="rounded-2xl border border-black/10 bg-white/70 p-4">
                <div className="text-xs uppercase tracking-[0.2em] text-black/50">B</div>
                <div className="mt-1 text-lg font-semibold">
                  #{invB.id} {invB.name ? `- ${invB.name}` : ""}
                </div>
                <div className="mt-1 text-sm text-black/60">
                  {invB.warehouse_name || "Skladiste ?"} | {new Date(invB.date).toLocaleString("hr-HR")}
                </div>
                <div className="mt-1 text-sm text-black/60">Stavki: {itemsB.length}</div>
              </div>
            </div>
          ) : null}
        </section>

        <section className="rounded-2xl border border-black/15 bg-white/80 p-5 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-[0.2em] text-black/50">Rezultati</div>
              <div className="text-sm text-black/60">
                Redova: {filteredRows.length} (ukupno: {rows.length})
              </div>
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="min-w-[720px] w-full border-separate border-spacing-y-2">
              <thead>
                <tr className="text-left text-xs uppercase tracking-[0.2em] text-black/50">
                  <th className="px-3 py-2">Artikl</th>
                  <th className="px-3 py-2">Unit</th>
                  <th className="px-3 py-2">Qty A</th>
                  <th className="px-3 py-2">Qty B</th>
                  <th className="px-3 py-2">Diff (B-A)</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((r) => {
                  const isChanged = r.diff == null ? true : r.diff !== 0n;
                  return (
                    <tr
                      key={r.artiklId}
                      className={`rounded-xl border border-black/10 bg-white/70 text-sm ${
                        isChanged ? "" : "opacity-70"
                      }`}
                    >
                      <td className="px-3 py-3">
                        <div className="font-semibold">{r.artiklName}</div>
                        <div className="mt-0.5 font-mono text-xs text-black/50">{r.artiklId}</div>
                      </td>
                      <td className="px-3 py-3 text-black/70">{r.unitName || "-"}</td>
                      <td className="px-3 py-3 font-mono">{fmtQty(r.qtyA)}</td>
                      <td className="px-3 py-3 font-mono">{fmtQty(r.qtyB)}</td>
                      <td className="px-3 py-3 font-mono">{fmtQty(r.diff)}</td>
                    </tr>
                  );
                })}
                {filteredRows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-sm text-black/60">
                      Nema razlika (ili nisu ucitane inventure).
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}

export default function InventoryComparePage() {
  // Next requires a Suspense boundary for pages that use `useSearchParams`.
  // This avoids prerender errors during `next build`.
  return (
    <Suspense fallback={<main className="min-h-screen bg-[#f2ebe0] text-[#121212] p-6">Loading...</main>}>
      <InventoryCompareInner />
    </Suspense>
  );
}
