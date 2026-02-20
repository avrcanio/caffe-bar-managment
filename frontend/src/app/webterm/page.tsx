export default function WebtermPage() {
  return (
    <main className="h-screen w-screen">
      <iframe
        title="Web Terminal"
        src="/api/webterm"
        className="h-full w-full border-0"
        allow="clipboard-read; clipboard-write"
      />
    </main>
  );
}

