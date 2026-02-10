"use client";

import { useEffect, useRef, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { apiPostJson } from "@/lib/api";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: Array<{ name: string; arguments: Record<string, unknown>; result: unknown }>;
};

type AiResponse = {
  answer?: string;
  tools?: Array<{ name: string; arguments: Record<string, unknown>; result: unknown }>;
  error?: string;
  details?: string;
};

export default function AiChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const canSend = input.trim().length > 0 && !loading;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  const handleSend = async () => {
    if (!canSend) return;
    const question = input.trim();
    const userMessage: ChatMessage = {
      id: `${Date.now()}-user`,
      role: "user",
      content: question,
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);
    setError(null);
    try {
      const payload = await apiPostJson<AiResponse>(
        "/api/ai/query/",
        { question },
        { csrf: true }
      );
      if (payload.error) {
        throw new Error(payload.details || payload.error);
      }
      const assistantMessage: ChatMessage = {
        id: `${Date.now()}-assistant`,
        role: "assistant",
        content: payload.answer || "(Nema odgovora)",
        tools: payload.tools || [],
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI upit nije uspio.");
    } finally {
      setLoading(false);
    }
  };

  const renderMessageContent = (content: string) => {
    const lines = content.split("\n");
    const linkPattern = /\[([^\]]+)\]\(([^)]+)\)/g;

    return (
      <div className="space-y-1">
        {lines.map((line, lineIndex) => {
          if (line.trim() === "") {
            return <div key={`line-${lineIndex}`} className="h-3" />;
          }
          if (!line.includes("](")) {
            const listMatch = line.match(/^-\s+(.+?)\s+\((id|ID)\s*[:]*\s*\d+[^)]*\)/i);
            if (listMatch) {
              const name = listMatch[1].trim();
              const nameStart = line.indexOf(name);
              const nameEnd = nameStart + name.length;
              return (
                <div key={`line-${lineIndex}`} className="whitespace-pre-wrap">
                  {line.slice(0, nameStart)}
                  <button
                    type="button"
                    onClick={() => {
                      setInput(name);
                      inputRef.current?.focus();
                    }}
                    className="underline underline-offset-2"
                  >
                    {name}
                  </button>
                  {line.slice(nameEnd)}
                </div>
              );
            }
          }
          const parts: Array<string | JSX.Element> = [];
          let lastIndex = 0;
          let match: RegExpExecArray | null;
          while ((match = linkPattern.exec(line)) !== null) {
            if (match.index > lastIndex) {
              parts.push(line.slice(lastIndex, match.index));
            }
            const text = match[1];
            const href = match[2];
            if (href.startsWith("fill:")) {
              const value = href.slice("fill:".length);
              parts.push(
                <button
                  key={`link-${lineIndex}-${match.index}`}
                  type="button"
                  onClick={() => {
                    setInput(value);
                    inputRef.current?.focus();
                  }}
                  className="underline underline-offset-2"
                >
                  {text}
                </button>
              );
            } else if (href.startsWith("/")) {
              parts.push(
                <Link
                  key={`link-${lineIndex}-${match.index}`}
                  href={href}
                  className="underline underline-offset-2"
                >
                  {text}
                </Link>
              );
            } else {
              parts.push(
                <a
                  key={`link-${lineIndex}-${match.index}`}
                  href={href}
                  className="underline underline-offset-2"
                  rel="noreferrer"
                  target="_blank"
                >
                  {text}
                </a>
              );
            }
            lastIndex = match.index + match[0].length;
          }
          if (lastIndex < line.length) {
            parts.push(line.slice(lastIndex));
          }
          return (
            <div key={`line-${lineIndex}`} className="whitespace-pre-wrap">
              {parts}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-6 py-10">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-[0.3em] text-black/60">
              Mozart AI
            </p>
            <h1 className={`${dmSerif.className} text-4xl`}>ERP chat asistent</h1>
            <p className="text-sm text-black/60">
              Brzi uvid u zalihe, prodaju i narudzbe.
            </p>
          </div>
          <Link
            href="/"
            className="rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
          >
            Nazad
          </Link>
        </header>

        <section className="flex flex-col gap-6">
          <div className="flex flex-col rounded-3xl border border-black/15 bg-white/80 shadow-[0_18px_40px_rgba(10,10,10,0.18)]">
            <div
              ref={containerRef}
              className="flex-1 space-y-4 overflow-y-auto px-6 py-6"
            >
              {messages.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-black/20 bg-white/70 p-6 text-sm text-black/50">
                  Postavi pitanje o zalihama, prodaji ili narudzbama.
                </div>
              ) : null}
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${
                    message.role === "user" ? "justify-end" : "justify-start"
                  }`}
                >
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm shadow-sm ${
                      message.role === "user"
                        ? "bg-[#121212] text-white"
                        : "bg-white text-black/80"
                    }`}
                  >
                    {message.role === "assistant"
                      ? renderMessageContent(message.content)
                      : message.content}
                  </div>
                </div>
              ))}
              {loading ? (
                <div className="flex justify-start">
                  <div className="rounded-2xl bg-white px-4 py-3 text-sm text-black/60">
                    Razmisljam...
                  </div>
                </div>
              ) : null}
            </div>

            <div className="border-t border-black/10 px-6 py-4">
              {error ? (
                <p className="mb-3 text-xs text-red-600">{error}</p>
              ) : null}
              <div className="flex flex-col gap-3 sm:flex-row">
                <input
                  ref={inputRef}
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder="Upisi pitanje..."
                  className="flex-1 rounded-full border border-black/20 bg-white/80 px-4 py-3 text-sm text-black/80 outline-none focus:border-black/40"
                />
                <button
                  onClick={handleSend}
                  disabled={!canSend}
                  className="rounded-full bg-[#f27323] px-6 py-3 text-xs uppercase tracking-[0.2em] text-black shadow-[0_12px_24px_rgba(242,115,35,0.35)] disabled:opacity-60"
                >
                  {loading ? "Saljem..." : "Posalji"}
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
