"use client";

type ToastBannerProps = {
  toast:
    | {
        type: "success" | "error";
        message: string;
      }
    | null;
};

export default function ToastBanner({ toast }: ToastBannerProps) {
  if (!toast) return null;

  return (
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
  );
}
