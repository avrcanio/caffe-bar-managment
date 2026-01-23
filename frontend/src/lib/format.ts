const euroFormatter = new Intl.NumberFormat("hr-HR", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatEuro(value?: number | string | null): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const numeric =
    typeof value === "number" ? value : Number(value);
  if (Number.isNaN(numeric)) {
    return "-";
  }
  return euroFormatter.format(numeric);
}

export function formatDate(
  value?: string | Date | null,
  options?: Intl.DateTimeFormatOptions
): string {
  if (!value) {
    return "-";
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  if (options) {
    return new Intl.DateTimeFormat("hr-HR", options).format(date);
  }
  return date.toLocaleDateString("hr-HR");
}

export function formatDateTime(value?: string | Date | null): string {
  return formatDate(value, { dateStyle: "short", timeStyle: "short" });
}
