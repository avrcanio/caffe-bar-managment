"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { apiGetJson, apiPatchJson, apiPostJson } from "@/lib/api";
import { formatDate, formatEuro } from "@/lib/format";
import EmptyState from "@/components/EmptyState";
import LoadingCard from "@/components/LoadingCard";
import {
  mapPurchaseOrder,
  PurchaseOrder,
  PurchaseOrderDTO,
} from "@/lib/mappers";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

type WarehouseDTO = {
  rm_id: number;
  name: string;
};

type ReceiptLineState = {
  itemId: number;
  quantity: string;
  confirmed: boolean;
  expectedUnitPrice: string;
};

type PricePatchResponse = {
  purchase_order_item_id: number;
  old_price: string;
  new_price: string;
  audit: {
    changed_at: string;
    changed_by?: {
      full_name?: string;
      username?: string;
    };
    reason: string;
  };
};

type PriceAuditState = {
  oldPrice: string;
  newPrice: string;
  changedAt: string;
  changedBy: string;
  reason: string;
};

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
  const [showReceiptPrompt, setShowReceiptPrompt] = useState(false);
  const [warehouses, setWarehouses] = useState<WarehouseDTO[]>([]);
  const [loadingWarehouses, setLoadingWarehouses] = useState(false);
  const [creatingReceipt, setCreatingReceipt] = useState(false);
  const [receiptError, setReceiptError] = useState("");
  const [showPartialConfirmAlert, setShowPartialConfirmAlert] = useState(false);
  const [selectedWarehouseId, setSelectedWarehouseId] = useState("");
  const [receiptInvoiceCode, setReceiptInvoiceCode] = useState("");
  const [receiptDeliveryNote, setReceiptDeliveryNote] = useState("");
  const [receiptDocumentDate, setReceiptDocumentDate] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const [receiptLines, setReceiptLines] = useState<ReceiptLineState[]>([]);
  const [showPriceAuditModal, setShowPriceAuditModal] = useState(false);
  const [activePriceItemId, setActivePriceItemId] = useState<number | null>(null);
  const [modalPriceDraft, setModalPriceDraft] = useState("");
  const [modalReasonDraft, setModalReasonDraft] = useState("");
  const [modalPriceError, setModalPriceError] = useState("");
  const [modalPriceSaving, setModalPriceSaving] = useState(false);
  const [priceAuditByItemId, setPriceAuditByItemId] = useState<Record<number, PriceAuditState>>({});
  const [priceEditedItemId, setPriceEditedItemId] = useState<Record<number, boolean>>({});

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

  useEffect(() => {
    if (!showReceiptPrompt) {
      return;
    }
    const run = async () => {
      try {
        setLoadingWarehouses(true);
        const data = await apiGetJson<WarehouseDTO[]>("/api/warehouses/");
        setWarehouses(data || []);
      } catch (err) {
        setWarehouses([]);
      } finally {
        setLoadingWarehouses(false);
      }
    };
    run();
  }, [showReceiptPrompt]);

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
  const normalizedStatusCode = (order?.statusCode || "").trim().toLowerCase();
  const normalizedStatusLabel = (order?.statusLabel || "").trim().toLowerCase();
  const canSendOrder = normalizedStatusCode === "created";
  const canCreateReceipt =
    normalizedStatusCode === "confirmed" ||
    normalizedStatusCode === "received" ||
    normalizedStatusLabel === "potvrđena" ||
    normalizedStatusLabel === "djelomično zaprimljena";
  const isStatusActionEnabled = Boolean(canSendOrder || canCreateReceipt);
  const receiptTotalNet = useMemo(() => {
    const byId = new Map((order?.items || []).map((item) => [item.id, item]));
    return receiptLines.reduce((sum, line) => {
      if (!line.confirmed) {
        return sum;
      }
      const poItem = byId.get(line.itemId);
      if (!poItem) {
        return sum;
      }
      const qty = Number(line.quantity || 0);
      const price = Number(line.expectedUnitPrice || 0);
      if (Number.isNaN(qty) || Number.isNaN(price)) {
        return sum;
      }
      return sum + qty * price;
    }, 0);
  }, [receiptLines, order?.items]);
  const receiptEligibleItems = useMemo(
    () => (order?.items || []).filter((item) => item.remainingQuantity > 0),
    [order?.items]
  );

  const openPriceAuditModal = useCallback((itemId: number) => {
    const line = receiptLines.find((value) => value.itemId === itemId);
    setActivePriceItemId(itemId);
    setModalPriceDraft(line?.expectedUnitPrice || "0.00");
    setModalReasonDraft("");
    setModalPriceError("");
    setShowPriceAuditModal(true);
  }, [receiptLines]);

  const savePriceFromModal = useCallback(async () => {
    if (!activePriceItemId) {
      return;
    }
    const activeItem = receiptEligibleItems.find((item) => item.id === activePriceItemId);
    if (!activeItem) {
      setModalPriceError("Stavka više nije dostupna.");
      return;
    }

    const normalizedInput = modalPriceDraft.trim();
    const parsedPrice = Number(normalizedInput);
    if (!normalizedInput || Number.isNaN(parsedPrice) || parsedPrice < 0) {
      setModalPriceError("Unesi ispravnu cijenu (>= 0).");
      return;
    }
    const newPrice = parsedPrice.toFixed(2);
    const oldPrice = activeItem.price !== null ? Number(activeItem.price).toFixed(2) : "0.00";
    if (newPrice === oldPrice) {
      setReceiptLines((prev) =>
        prev.map((row) =>
          row.itemId === activePriceItemId
            ? { ...row, expectedUnitPrice: newPrice }
            : row
        )
      );
      setShowPriceAuditModal(false);
      setActivePriceItemId(null);
      return;
    }

    const customReason = modalReasonDraft.trim();
    const reason = customReason
      ? `Korekcija ulazne cijene - ${customReason}`
      : "Korekcija ulazne cijene";

    setModalPriceSaving(true);
    setModalPriceError("");
    try {
      const payload = await apiPatchJson<PricePatchResponse>(
        `/api/purchase-order-items/${activePriceItemId}/price/`,
        {
          price: newPrice,
          currency: "EUR",
          reason,
        },
        { csrf: true }
      );
      const by = (
        payload.audit?.changed_by?.full_name ||
        payload.audit?.changed_by?.username ||
        "Korisnik"
      ).trim();
      setPriceAuditByItemId((prev) => ({
        ...prev,
        [activePriceItemId]: {
          oldPrice: payload.old_price,
          newPrice: payload.new_price,
          changedAt: payload.audit.changed_at,
          changedBy: by,
          reason: payload.audit.reason,
        },
      }));
      setPriceEditedItemId((prev) => ({
        ...prev,
        [activePriceItemId]: true,
      }));
      setReceiptLines((prev) =>
        prev.map((row) =>
          row.itemId === activePriceItemId
            ? { ...row, expectedUnitPrice: payload.new_price }
            : row
        )
      );
      await loadOrder();
      setShowPriceAuditModal(false);
      setActivePriceItemId(null);
    } catch (err) {
      setModalPriceError(
        err instanceof Error ? err.message : "Promjena cijene nije uspjela."
      );
    } finally {
      setModalPriceSaving(false);
    }
  }, [activePriceItemId, loadOrder, modalPriceDraft, modalReasonDraft, receiptEligibleItems]);

  const submitReceipt = useCallback(async () => {
    if (!order) {
      return;
    }
    setCreatingReceipt(true);
    setReceiptError("");
    try {
      await apiPostJson(
        `/api/purchase-orders/${order.id}/warehouse-inputs/`,
        {
          document_date: receiptDocumentDate,
          warehouse_id: Number(selectedWarehouseId),
          invoice_code: receiptInvoiceCode.trim(),
          delivery_note: receiptDeliveryNote.trim(),
          currency: "EUR",
          expected_total_net: receiptTotalNet.toFixed(2),
          items: receiptLines.map((line) => ({
            purchase_order_item_id: line.itemId,
            received_quantity: line.quantity || "0",
            confirmed: line.confirmed,
            expected_unit_price: line.expectedUnitPrice || "0.00",
          })),
        },
        { csrf: true }
      );
      setShowReceiptPrompt(false);
      setShowPartialConfirmAlert(false);
      await loadOrder();
    } catch (err) {
      setReceiptError(
        err instanceof Error ? err.message : "Kreiranje primke nije uspjelo."
      );
    } finally {
      setCreatingReceipt(false);
    }
  }, [
    loadOrder,
    order,
    receiptDeliveryNote,
    receiptDocumentDate,
    receiptInvoiceCode,
    receiptLines,
    receiptTotalNet,
    selectedWarehouseId,
  ]);
  const activePriceItem =
    activePriceItemId !== null
      ? receiptEligibleItems.find((item) => item.id === activePriceItemId) || null
      : null;
  const activePriceAudit =
    activePriceItemId !== null ? priceAuditByItemId[activePriceItemId] : null;

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
            <section className="grid gap-4 md:grid-cols-4">
              {[
                {
                  label: "Dobavljac",
                  value: order.supplierName,
                },
                {
                  label: "Status",
                  value: order.statusLabel,
                  hint: canCreateReceipt ? "Kreiraj primku" : "",
                  clickable: isStatusActionEnabled,
                },
                {
                  label: "Tip placanja",
                  value: order.paymentTypeName || "-",
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
                      if (card.label === "Status" && canCreateReceipt && order) {
                        if (receiptEligibleItems.length === 0) {
                          setError("Nema preostalih količina za novu primku.");
                          return;
                        }
                        setError("");
                        setReceiptError("");
                        setSelectedWarehouseId("");
                        setReceiptInvoiceCode("");
                        setReceiptDeliveryNote("");
                        setReceiptDocumentDate(new Date().toISOString().slice(0, 10));
                        setShowPriceAuditModal(false);
                        setActivePriceItemId(null);
                        setModalPriceDraft("");
                        setModalReasonDraft("");
                        setModalPriceError("");
                        setModalPriceSaving(false);
                        setReceiptLines(
                          receiptEligibleItems.map((item) => ({
                            itemId: item.id,
                            quantity: String(item.remainingQuantity),
                            confirmed: false,
                            expectedUnitPrice: item.price !== null ? item.price.toFixed(2) : "0.00",
                          }))
                        );
                        setShowPartialConfirmAlert(false);
                        setShowReceiptPrompt(true);
                        return;
                      }
                      if (isClickable && canSendOrder) {
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
                    {"hint" in card && card.hint ? (
                      <p className="mt-1 text-[10px] uppercase tracking-[0.2em] text-[#f27323]">
                        {card.hint}
                      </p>
                    ) : null}
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
                          className={`rounded-2xl border border-black/10 px-4 py-3 ${
                            priceEditedItemId[item.id] ? "bg-red-50/80" : "bg-white/70"
                          }`}
                        >
                          <p className="text-sm font-semibold">{item.name}</p>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-black/60">
                            <span>
                              {item.quantity} {item.unitName || ""}
                            </span>
                            <span>·</span>
                            <span>{formatEuro(item.price)}</span>
                            {priceAuditByItemId[item.id] ? (
                              <span
                                title={`Stara: ${priceAuditByItemId[item.id].oldPrice} | Nova: ${priceAuditByItemId[item.id].newPrice} | Tko: ${priceAuditByItemId[item.id].changedBy} | Kada: ${new Date(priceAuditByItemId[item.id].changedAt).toLocaleString("hr-HR")} | Razlog: ${priceAuditByItemId[item.id].reason}`}
                                className="rounded-full border border-black/20 px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-black/70"
                              >
                                Audit
                              </span>
                            ) : null}
                          </div>
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
      {showReceiptPrompt && order ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-6 py-6">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-3xl border border-black/15 bg-white p-6 shadow-[0_30px_60px_rgba(10,10,10,0.3)]">
            <h3 className={`${dmSerif.className} text-2xl`}>Kreiraj primku</h3>
            <p className="mt-2 text-sm text-black/60">
              Prikazuju se samo stavke s preostalom količinom. Manja količina ostavlja razliku za kasniju primku, a veća količina proširuje narudžbu na stvarno zaprimljeno.
            </p>
            {receiptError ? (
              <p className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
                {receiptError}
              </p>
            ) : null}
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <input
                type="date"
                value={receiptDocumentDate}
                onChange={(event) => setReceiptDocumentDate(event.target.value)}
                className="rounded-full border border-black/20 bg-white px-4 py-2 text-xs uppercase tracking-[0.15em] text-black/70"
              />
              <select
                value={selectedWarehouseId}
                onChange={(event) => setSelectedWarehouseId(event.target.value)}
                className="rounded-full border border-black/20 bg-white px-4 py-2 text-xs uppercase tracking-[0.15em] text-black/70"
              >
                <option value="">Odaberi skladište</option>
                {warehouses.map((warehouse) => (
                  <option key={warehouse.rm_id} value={warehouse.rm_id}>
                    {warehouse.name}
                  </option>
                ))}
              </select>
              <input
                value={receiptInvoiceCode}
                onChange={(event) => setReceiptInvoiceCode(event.target.value)}
                placeholder="Broj računa"
                className="rounded-full border border-black/20 bg-white px-4 py-2 text-xs uppercase tracking-[0.15em] text-black/70"
              />
              <input
                value={receiptDeliveryNote}
                onChange={(event) => setReceiptDeliveryNote(event.target.value)}
                placeholder="Broj otpremnice"
                className="rounded-full border border-black/20 bg-white px-4 py-2 text-xs uppercase tracking-[0.15em] text-black/70"
              />
            </div>
            {loadingWarehouses ? (
              <p className="mt-3 text-xs text-black/60">Učitavam skladišta...</p>
            ) : null}
            <div className="mt-4 space-y-2">
              {receiptEligibleItems.map((item) => {
                const line = receiptLines.find((value) => value.itemId === item.id);
                return (
                  <div
                    key={item.id}
                    className="grid grid-cols-1 gap-2 rounded-2xl border border-black/10 bg-white/70 px-3 py-3 md:grid-cols-[1.2fr_0.7fr_0.9fr_0.7fr_auto]"
                  >
                    <p className="text-sm font-semibold">{item.name}</p>
                    <input
                      type="number"
                      step="0.0001"
                      value={line?.quantity || "0"}
                      onChange={(event) => {
                        const value = event.target.value;
                        setReceiptLines((prev) =>
                          prev.map((row) =>
                            row.itemId === item.id ? { ...row, quantity: value } : row
                          )
                        );
                      }}
                      className="rounded-full border border-black/20 bg-white px-3 py-1 text-xs text-black/70"
                    />
                    <input
                      type="text"
                      readOnly
                      value={line?.expectedUnitPrice || "0.00"}
                      onClick={() => {
                        openPriceAuditModal(item.id);
                      }}
                      className="cursor-pointer rounded-full border border-black/20 bg-white px-3 py-1 text-xs text-black/70"
                    />
                    <label className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.12em] text-black/60">
                      <input
                        type="checkbox"
                        checked={Boolean(line?.confirmed)}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setReceiptLines((prev) =>
                            prev.map((row) =>
                              row.itemId === item.id ? { ...row, confirmed: checked } : row
                            )
                          );
                        }}
                      />
                      Confirmed
                    </label>
                    <p className="text-xs text-black/60 md:text-right">
                      PO: {formatEuro(item.price)} • Naručeno: {item.quantity} • Preostalo: {item.remainingQuantity}
                    </p>
                  </div>
                );
              })}
            </div>
            <p className="mt-4 text-sm font-semibold">
              Neto (stavke): {formatEuro(receiptTotalNet)}
            </p>
            <p className="text-xs text-black/60">
              Neto (narudžba): {formatEuro(order.totalNet)}
            </p>
            <p className="mt-1 text-xs text-black/60">
              Potvrđene stavke s količinom većom od naručene bit će spremljene s novom količinom na narudžbi.
            </p>
            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <button
                onClick={() => setShowReceiptPrompt(false)}
                className="flex-1 rounded-full border border-black/20 px-4 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
              >
                Zatvori
              </button>
              <button
                onClick={async () => {
                  if (receiptEligibleItems.length === 0) {
                    setReceiptError("Nema preostalih količina za zaprimanje.");
                    return;
                  }
                  const confirmedWithQty = receiptLines.filter(
                    (line) => line.confirmed && Number(line.quantity || 0) > 0
                  );
                  if (!confirmedWithQty.length) {
                    setReceiptError(
                      "Potvrdi barem jednu stavku s količinom većom od 0."
                    );
                    return;
                  }
                  const hasUnconfirmed = receiptLines.some(
                    (line) =>
                      !line.confirmed && Number(line.quantity || 0) > 0
                  );
                  if (hasUnconfirmed) {
                    setShowPartialConfirmAlert(true);
                    return;
                  }
                  await submitReceipt();
                }}
                disabled={creatingReceipt}
                className="flex-1 rounded-full bg-[#f27323] px-4 py-2 text-xs uppercase tracking-[0.2em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] disabled:opacity-60"
              >
                {creatingReceipt ? "Kreiram..." : "Kreiraj primku"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {showPriceAuditModal && activePriceItem ? (
        <div className="fixed inset-0 z-[75] flex items-center justify-center bg-black/55 px-6">
          <div className="w-full max-w-xl rounded-3xl border border-black/15 bg-white p-6 shadow-[0_30px_60px_rgba(10,10,10,0.3)]">
            <h4 className={`${dmSerif.className} text-xl`}>Audit promjene cijene</h4>
            <p className="mt-2 text-sm text-black/70">{activePriceItem.name}</p>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <input
                type="number"
                step="0.01"
                value={modalPriceDraft}
                onChange={(event) => setModalPriceDraft(event.target.value)}
                disabled={modalPriceSaving}
                className="rounded-full border border-black/20 bg-white px-4 py-2 text-sm text-black/80"
              />
              <input
                value={modalReasonDraft}
                onChange={(event) => setModalReasonDraft(event.target.value)}
                placeholder="Custom razlog (opcionalno)"
                disabled={modalPriceSaving}
                className="rounded-full border border-black/20 bg-white px-4 py-2 text-sm text-black/80"
              />
            </div>
            <div className="mt-4 rounded-2xl border border-black/10 bg-[#f6f2ea] p-4 text-sm text-black/75">
              {activePriceAudit ? (
                <p>
                  Zadnji audit: {activePriceAudit.oldPrice} → {activePriceAudit.newPrice}
                  {" • "}Tko: {activePriceAudit.changedBy}
                  {" • "}Kada: {new Date(activePriceAudit.changedAt).toLocaleString("hr-HR")}
                  {" • "}Razlog: {activePriceAudit.reason}
                </p>
              ) : (
                <p>Nema prethodnog audita za ovu stavku.</p>
              )}
            </div>
            {modalPriceError ? (
              <p className="mt-3 text-sm text-red-600">{modalPriceError}</p>
            ) : null}
            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <button
                type="button"
                onClick={() => {
                  if (modalPriceSaving) {
                    return;
                  }
                  setShowPriceAuditModal(false);
                  setActivePriceItemId(null);
                  setModalPriceError("");
                }}
                className="flex-1 rounded-full border border-black/20 px-4 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
              >
                Odustani
              </button>
              <button
                type="button"
                onClick={savePriceFromModal}
                disabled={modalPriceSaving}
                className="flex-1 rounded-full bg-[#f27323] px-4 py-2 text-xs uppercase tracking-[0.2em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] disabled:opacity-60"
              >
                {modalPriceSaving ? "Spremam..." : "Spremi"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {showPartialConfirmAlert ? (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/55 px-6">
          <div className="w-full max-w-md rounded-3xl border border-black/15 bg-white p-6 shadow-[0_30px_60px_rgba(10,10,10,0.3)]">
            <h4 className={`${dmSerif.className} text-xl`}>Upozorenje</h4>
            <p className="mt-2 text-sm text-black/70">
              Nisu potvrđene sve stavke. Kreirat će se primka samo za potvrđene
              stavke, a ostatak će ostati otvoren na narudžbi.
            </p>
            <div className="mt-5 flex flex-col gap-3 sm:flex-row">
              <button
                type="button"
                onClick={() => setShowPartialConfirmAlert(false)}
                className="flex-1 rounded-full border border-black/20 px-4 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
              >
                Vrati nazad
              </button>
              <button
                type="button"
                onClick={async () => {
                  setShowPartialConfirmAlert(false);
                  await submitReceipt();
                }}
                className="flex-1 rounded-full bg-[#f27323] px-4 py-2 text-xs uppercase tracking-[0.2em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)]"
              >
                Prihvati
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
