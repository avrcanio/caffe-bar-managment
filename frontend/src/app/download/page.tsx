import { DM_Serif_Display } from "next/font/google";

const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400" });

const steps = [
  {
    title: "Korak 1: Instaliraj certifikat",
    description:
      "Preuzmi i instaliraj certifikat da bi Windows vjerovao aplikaciji.",
    primaryLabel: "Preuzmi certifikat",
    primaryHref:
      "https://mozart.sibenik1983.hr/download/TouchScreenPOS-Company-Signing.cer",
    secondaryLabel: "",
    secondaryHref: "",
    note: "Napomena: bez ovoga MSIX instalacija nece proci.",
    details: [
      "Dvoklik na preuzeti .cer",
      "Install Certificate -> Local Machine (ili Current User ako nema admin prava)",
      "Odaberi \"Trusted Root Certification Authorities\"",
      "Ponovi i instaliraj u \"Trusted Publishers\"",
    ],
    badge: "Obavezno",
  },
  {
    title: "Korak 2: Instaliraj aplikaciju (Blagajna)",
    description:
      "Instalacija se pokrece nakon klika na gumb. Ako se pojavi prompt, potvrdi otvaranje App Installer-a.",
    primaryLabel: "Instaliraj Blagajna",
    primaryHref: "/download/Blagajna.appinstaller",
    secondaryLabel: "Preuzmi MSIX",
    secondaryHref:
      "https://mozart.sibenik1983.hr/download/Blagajna_1.0.0.0_x64.msix",
    note: "",
    details: [
      "Ako nemas App Installer, preuzmi ga iz Microsoft Store.",
    ],
    badge: "Aplikacija",
  },
];

const faq = [
  {
    question: "Sto ako MSIX javlja gresku o certifikatu?",
    answer: "Certifikat nije trustan. Instaliraj ga u Trusted Root i Trusted Publishers.",
  },
  {
    question: "Sto ako nema App Installer?",
    answer: "Preuzmi App Installer iz Microsoft Store.",
  },
];

export default function DownloadPage() {
  return (
    <main className="min-h-screen bg-[#f2ebe0] text-[#121212]">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col gap-10 px-6 py-16">
        <header className="space-y-4">
          <p className="text-xs uppercase tracking-[0.3em] text-black/60">
            Mozart Downloads
          </p>
          <h1 className={`${dmSerif.className} text-4xl sm:text-5xl`}>
            Instalacija Blagajne
          </h1>
          <p className="max-w-2xl text-base text-black/70">
            Slijedi korake redom: prvo instaliraj certifikat, zatim aplikaciju.
          </p>
        </header>

        <section className="grid gap-6 lg:grid-cols-2">
          {steps.map((step, index) => (
            <article
              key={step.title}
              className="rounded-3xl border border-black/15 bg-white/85 p-6 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur"
            >
              <div className="flex items-center justify-between">
                <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                  {`Korak ${index + 1}`}
                </p>
                {step.badge ? (
                  <span className="rounded-full border border-black/20 px-3 py-1 text-[10px] uppercase tracking-[0.3em] text-black/60">
                    {step.badge}
                  </span>
                ) : null}
              </div>
              <h2 className={`${dmSerif.className} mt-4 text-2xl`}>
                {step.title}
              </h2>
              <p className="mt-2 text-sm text-black/70">{step.description}</p>

              <div className="mt-5 flex flex-wrap gap-3">
                <a
                  className="inline-flex items-center justify-center rounded-full border border-black/20 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/80 transition hover:border-black/40"
                  href={step.primaryHref}
                  download
                >
                  {step.primaryLabel}
                </a>
                {step.secondaryLabel ? (
                  <a
                    className="inline-flex items-center justify-center rounded-full border border-black/15 px-5 py-2 text-xs uppercase tracking-[0.2em] text-black/60 transition hover:border-black/40"
                    href={step.secondaryHref}
                    download
                  >
                    {step.secondaryLabel}
                  </a>
                ) : null}
              </div>

              <ul className="mt-5 space-y-2 text-sm text-black/70">
                {step.details.map((detail) => (
                  <li key={detail} className="flex gap-2">
                    <span className="mt-[2px] inline-block h-1.5 w-1.5 rounded-full bg-black/50" />
                    <span>{detail}</span>
                  </li>
                ))}
              </ul>

              {step.note ? (
                <p className="mt-5 rounded-2xl border border-black/10 bg-black/5 px-4 py-3 text-xs uppercase tracking-[0.18em] text-black/60">
                  {step.note}
                </p>
              ) : null}
            </article>
          ))}
        </section>

        <section className="rounded-3xl border border-black/15 bg-white/80 p-6 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur">
          <h3 className={`${dmSerif.className} text-2xl`}>Mini FAQ</h3>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {faq.map((item) => (
              <div
                key={item.question}
                className="rounded-2xl border border-black/10 bg-white/70 p-4"
              >
                <p className="text-xs uppercase tracking-[0.2em] text-black/50">
                  {item.question}
                </p>
                <p className="mt-2 text-sm text-black/70">{item.answer}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-black/15 bg-white/80 p-6 text-sm text-black/70 shadow-[0_18px_40px_rgba(10,10,10,0.18)] backdrop-blur">
          <p>
            Instalacija se pokrece nakon klika na gumb (ne moze se automatski iz
            browsera). Ako se pojavi prompt, potvrdi otvaranje App Installer-a.
          </p>
        </section>
      </div>
    </main>
  );
}
