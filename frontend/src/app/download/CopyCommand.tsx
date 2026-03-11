"use client";

import { useState } from "react";

type CopyCommandProps = {
  command: string;
};

export default function CopyCommand({ command }: CopyCommandProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
      <code className="block w-full overflow-x-auto rounded-xl border border-black/15 bg-white px-4 py-3 text-xs text-black/80">
        {command}
      </code>
      <button
        type="button"
        onClick={handleCopy}
        className="inline-flex shrink-0 items-center justify-center rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/80 transition hover:border-black/40"
      >
        {copied ? "Kopirano" : "Kopiraj"}
      </button>
    </div>
  );
}
