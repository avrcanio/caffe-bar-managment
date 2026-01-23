type StatusCountsDTO = Record<string, { count: number; total_gross: number }>;

export type PurchaseOrderSummaryDTO = {
  count: number;
  total_net: number;
  total_gross: number;
  total_deposit: number;
  status_counts?: StatusCountsDTO;
};

export type PurchaseOrderItemDTO = {
  id: number;
  artikl_name?: string | null;
  quantity: string;
  unit_name?: string | null;
  price?: string | null;
};

export type PurchaseOrderDTO = {
  id: number;
  supplier_name?: string | null;
  status_display?: string | null;
  ordered_at: string;
  total_net?: string;
  total_gross: string;
  total_deposit?: string;
  items?: PurchaseOrderItemDTO[];
};

export type PurchaseOrderListDTO = {
  summary: PurchaseOrderSummaryDTO;
  results: PurchaseOrderDTO[];
};

export type PurchaseOrderSummary = {
  count: number;
  totalNet: number;
  totalGross: number;
  totalDeposit: number;
  statusCounts: Record<string, { count: number; totalGross: number }>;
};

export type PurchaseOrderItem = {
  id: number;
  name: string;
  quantity: number;
  unitName: string;
  price: number | null;
};

export type PurchaseOrder = {
  id: number;
  supplierName: string;
  statusLabel: string;
  orderedAt: Date;
  totalNet: number;
  totalGross: number;
  totalDeposit: number;
  items: PurchaseOrderItem[];
};

const toNumber = (value: unknown, fallback = 0): number => {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  const numeric = Number(value);
  return Number.isNaN(numeric) ? fallback : numeric;
};

export const mapPurchaseOrderItem = (
  item: PurchaseOrderItemDTO
): PurchaseOrderItem => ({
  id: item.id,
  name: item.artikl_name || "Artikl",
  quantity: toNumber(item.quantity, 0),
  unitName: item.unit_name || "",
  price: item.price === null || item.price === undefined ? null : toNumber(item.price, 0),
});

export const mapPurchaseOrder = (order: PurchaseOrderDTO): PurchaseOrder => ({
  id: order.id,
  supplierName: order.supplier_name || "Dobavljac",
  statusLabel: order.status_display || "Status",
  orderedAt: new Date(order.ordered_at),
  totalNet: toNumber(order.total_net, 0),
  totalGross: toNumber(order.total_gross, 0),
  totalDeposit: toNumber(order.total_deposit, 0),
  items: (order.items || []).map(mapPurchaseOrderItem),
});

export const mapPurchaseOrderSummary = (
  summary: PurchaseOrderSummaryDTO
): PurchaseOrderSummary => ({
  count: summary.count,
  totalNet: toNumber(summary.total_net, 0),
  totalGross: toNumber(summary.total_gross, 0),
  totalDeposit: toNumber(summary.total_deposit, 0),
  statusCounts: Object.entries(summary.status_counts || {}).reduce(
    (acc, [key, value]) => {
      acc[key] = {
        count: value.count,
        totalGross: toNumber(value.total_gross, 0),
      };
      return acc;
    },
    {} as Record<string, { count: number; totalGross: number }>
  ),
});

export const mapPurchaseOrderList = (
  response: PurchaseOrderListDTO
): { summary: PurchaseOrderSummary; orders: PurchaseOrder[] } => ({
  summary: mapPurchaseOrderSummary(response.summary),
  orders: (response.results || []).map(mapPurchaseOrder),
});
