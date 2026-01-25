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
  artikl: number;
  artikl_name?: string | null;
  base_group?: string | null;
  quantity: string;
  unit_name?: string | null;
  unit_of_measure: number;
  price?: string | null;
};

export type PurchaseOrderDTO = {
  id: number;
  supplier: number;
  supplier_name?: string | null;
  status: string;
  status_display?: string | null;
  payment_type?: number | null;
  payment_type_name?: string | null;
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
  artiklId: number;
  name: string;
  baseGroup: string | null;
  quantity: number;
  unitName: string;
  unitId: number;
  price: number | null;
};

export type PurchaseOrder = {
  id: number;
  supplierId: number;
  supplierName: string;
  statusCode: string;
  statusLabel: string;
  paymentTypeId: number | null;
  paymentTypeName: string | null;
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
  artiklId: item.artikl,
  name: item.artikl_name || "Artikl",
  baseGroup: item.base_group || null,
  quantity: toNumber(item.quantity, 0),
  unitName: item.unit_name || "",
  unitId: item.unit_of_measure,
  price: item.price === null || item.price === undefined ? null : toNumber(item.price, 0),
});

export const mapPurchaseOrder = (order: PurchaseOrderDTO): PurchaseOrder => ({
  id: order.id,
  supplierId: order.supplier,
  supplierName: order.supplier_name || "Dobavljac",
  statusCode: order.status,
  statusLabel: order.status_display || "Status",
  paymentTypeId:
    order.payment_type === undefined ? null : order.payment_type ?? null,
  paymentTypeName: order.payment_type_name || null,
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
