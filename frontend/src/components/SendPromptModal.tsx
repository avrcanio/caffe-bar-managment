"use client";

import { useEffect, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import { apiPostJson } from "@/lib/api";
import ToastBanner from "@/components/ToastBanner";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

export const sendPurchaseOrderEmail = async (orderId: string | number) =>
  apiPostJson(`/api/purchase-orders/${orderId}/send/`, undefined, {
    csrf: true,
  });

type SendPromptModalProps = {
  open: boolean;
  orderId?: string | number | null;
  onClose: () => void;
  onSent?: () => void;
  showStatusInModal?: boolean;
  successMessage?: string;
  errorMessage?: string;
};

type ToastState = { type: "success" | "error"; message: string } | null;

export default function SendPromptModal({
  open,
  orderId,
  onClose,
  onSent,
  showStatusInModal = true,
  successMessage = "Narudzba je poslana dobavljacu.",
  errorMessage = "Slanje narudzbe nije uspjelo.",
}: SendPromptModalProps) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [toast, setToast] = useState<ToastState>(null);

  useEffect(() => {
    if (!open) return;
    setError("");
    setSuccess("");
  }, [open, orderId]);

  const handleSend = async () => {
    if (!orderId || sending) return;
    setSending(true);
    setError("");
    setSuccess("");
    try {
      await sendPurchaseOrderEmail(orderId);
      setSuccess(successMessage);
      setToast({ type: "success", message: successMessage });
      onClose();
      setTimeout(() => {
        onSent?.();
      }, 1200);
    } catch (err) {
      const detail = err instanceof Error ? err.message : errorMessage;
      setError(detail);
      setToast({ type: "error", message: detail });
    } finally {
      setSending(false);
    }
  };

  const handleCancel = () => {
    if (sending) return;
    onClose();
  };

  return (
    <>
      <ToastBanner toast={toast} />
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-6">
          <div className="w-full max-w-md rounded-3xl border border-black/15 bg-white p-6 shadow-[0_30px_60px_rgba(10,10,10,0.3)]">
            <h3 className={`${dmSerif.className} text-2xl`}>
              Poslati narudzbu?
            </h3>
            <p className="mt-2 text-sm text-black/60">
              Zelis li odmah poslati narudzbu dobavljacu emailom?
            </p>
            {showStatusInModal && error ? (
              <p className="mt-3 text-sm text-red-600">{error}</p>
            ) : null}
            {showStatusInModal && success ? (
              <p className="mt-3 text-sm text-green-700">{success}</p>
            ) : null}
            <div className="mt-6 flex gap-3">
              <button
                onClick={handleCancel}
                className="flex-1 rounded-full border border-black/20 px-4 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
              >
                Ne
              </button>
              <button
                onClick={handleSend}
                disabled={sending || !orderId}
                className="flex-1 rounded-full bg-[#f27323] px-4 py-2 text-xs uppercase tracking-[0.2em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] disabled:opacity-60"
              >
                {sending ? "Slanje..." : "Da, posalji"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
