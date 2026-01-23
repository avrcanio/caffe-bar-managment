"use client";

import { useEffect, useMemo, useState } from "react";
import { DM_Serif_Display } from "next/font/google";
import Link from "next/link";
import { apiGetJson } from "@/lib/api";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

type MailMessage = {
  id: number;
  mailbox: string;
  subject: string;
  from_email: string;
  to_emails: string;
  sent_at: string | null;
  attachments_count: number;
};

type MailAttachment = {
  id: number;
  filename: string;
  content_type: string;
  size: number;
  file_url: string | null;
};

type MailMessageDetail = {
  id: number;
  mailbox: string;
  subject: string;
  from_email: string;
  to_emails: string;
  cc_emails: string;
  sent_at: string | null;
  body_text: string;
  body_html: string;
  attachments: MailAttachment[];
};

type MailListResponse = {
  count: number;
  results: MailMessage[];
};

const euroDate = (value: string | null) => {
  if (!value) return "-";
  return new Date(value).toLocaleString();
};

export default function MailboxPage() {
  const [messages, setMessages] = useState<MailMessage[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<MailMessageDetail | null>(null);
  const [query, setQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);

  const loadMessages = async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ page_size: "20" });
    if (query) params.set("q", query);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    try {
      const data = await apiGetJson<MailListResponse>(
        `/api/mailbox/messages/?${params.toString()}`
      );
      setMessages(data.results || []);
      if (data.results?.length && !selectedId) {
        setSelectedId(data.results[0].id);
      }
    } catch (err) {
      setError("Ne mogu ucitati mailove.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMessages();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    const run = async () => {
      setDetailLoading(true);
      try {
        const data = await apiGetJson<MailMessageDetail>(
          `/api/mailbox/messages/${selectedId}/`
        );
        setSelected(data);
      } finally {
        setDetailLoading(false);
      }
    };
    run();
  }, [selectedId]);

  const emptyDetail = useMemo(
    () => !selected && !detailLoading,
    [selected, detailLoading]
  );

  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-6 py-12">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-sm uppercase tracking-[0.3em] text-black/60">
              Mailbox
            </p>
            <h1 className={`${dmSerif.className} text-4xl`}>
              E-mails
            </h1>
          </div>
          <Link
            href="/"
            className="rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/70"
          >
            Povratak
          </Link>
        </header>

        <section className="rounded-3xl border border-black/15 bg-white/85 p-5 shadow-[0_20px_50px_rgba(10,10,10,0.2)]">
          <div className="grid gap-3 sm:grid-cols-4">
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Pretrazi predmet ili posiljatelja"
              className="min-w-0 rounded-full border border-black/20 bg-white px-4 py-2 text-sm"
            />
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              className="min-w-0 rounded-full border border-black/20 bg-white px-4 py-2 text-sm"
            />
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              className="min-w-0 rounded-full border border-black/20 bg-white px-4 py-2 text-sm"
            />
            <button
              onClick={loadMessages}
              className="min-w-0 rounded-full bg-[#f27323] px-4 py-2 text-xs uppercase tracking-[0.2em] text-black"
            >
              Primijeni filtere
            </button>
          </div>
          {error ? (
            <p className="mt-3 text-sm text-red-600">{error}</p>
          ) : null}
        </section>

        <section className="grid min-w-0 gap-6 lg:grid-cols-[1.1fr_1.4fr]">
          <div className="min-w-0 rounded-3xl border border-black/15 bg-white/85 p-4 shadow-[0_20px_50px_rgba(10,10,10,0.2)]">
            <div className="flex items-center justify-between px-2 pb-3">
              <p className="text-xs uppercase tracking-[0.3em] text-black/50">
                Mailovi
              </p>
              <span className="text-xs text-black/50">
                {loading ? "Ucitavanje..." : `${messages.length} prikazano`}
              </span>
            </div>
            <div className="space-y-2">
              {messages.map((message) => (
                <button
                  key={message.id}
                  onClick={() => setSelectedId(message.id)}
                  className={`w-full min-w-0 max-w-full rounded-2xl border px-4 py-3 text-left transition ${
                    selectedId === message.id
                      ? "border-black/60 bg-white"
                      : "border-black/10 bg-white/70"
                  }`}
                >
                  <p className="truncate text-sm font-semibold">
                    {message.subject || "(bez predmeta)"}
                  </p>
                  <p className="truncate text-xs uppercase tracking-[0.2em] text-black/50">
                    {message.from_email}
                  </p>
                  <p className="mt-2 break-words text-xs text-black/60">
                    {euroDate(message.sent_at)}
                  </p>
                  <p className="text-xs text-black/60">
                    Privitci: {message.attachments_count}
                  </p>
                </button>
              ))}
              {!loading && messages.length === 0 ? (
                <p className="text-sm text-black/60">
                  Nema mailova prema filterima.
                </p>
              ) : null}
            </div>
          </div>

          <div className="min-w-0 rounded-3xl border border-black/15 bg-white/85 p-6 shadow-[0_20px_50px_rgba(10,10,10,0.2)] overflow-hidden">
            {detailLoading ? (
              <p className="text-sm text-black/60">Ucitavanje...</p>
            ) : null}
            {emptyDetail ? (
              <p className="text-sm text-black/60">
                Odaberi mail za prikaz.
              </p>
            ) : null}
            {selected ? (
              <div className="space-y-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                    Predmet
                  </p>
                  <p className="break-words text-lg font-semibold">
                    {selected.subject || "(bez predmeta)"}
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                      Od
                    </p>
                    <p className="break-all text-sm max-w-full">
                      {selected.from_email}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                      Poslano
                    </p>
                    <p className="text-sm">{euroDate(selected.sent_at)}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                      Za
                    </p>
                    <p className="break-all text-sm max-w-full">
                      {selected.to_emails}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                      CC
                    </p>
                    <p className="break-all text-sm max-w-full">
                      {selected.cc_emails || "-"}
                    </p>
                  </div>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                    Sadrzaj
                  </p>
                  <div className="mt-2 rounded-2xl border border-black/10 bg-white/70 p-4 text-sm text-black/70 break-words">
                    {selected.body_text || "Nema tekstualnog sadržaja."}
                  </div>
                </div>
                {selected.attachments.length ? (
                  <div>
                    <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                      Privitci
                    </p>
                    <div className="mt-2 grid gap-2">
                      {selected.attachments.map((att) => (
                        <a
                          key={att.id}
                          href={att.file_url || "#"}
                          className="rounded-xl border border-black/10 bg-white/70 px-4 py-2 text-sm text-black/70 break-all"
                        >
                          {att.filename || "attachment"} ({att.size} B)
                        </a>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
