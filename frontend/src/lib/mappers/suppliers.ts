export type SupplierDTO = {
  id: number;
  name: string;
  rm_id: number;
  default_payment_type?: number | null;
};

export type Supplier = {
  id: number;
  name: string;
  rmId: number;
  defaultPaymentTypeId: number | null;
};

export type StockRowDTO = {
  warehouse_id: number | null;
  warehouse_name: string;
  quantity: string;
};

export type SupplierArtiklDTO = {
  artikl_id: number;
  artikl_rm_id: number | null;
  name: string;
  code: string | null;
  image: string | null;
  image_50x75?: string | null;
  base_group: string | null;
  category_id?: number | null;
  category_name?: string | null;
  category_path?: string[] | null;
  unit_of_measure: number | null;
  unit_name: string | null;
  price: string | null;
  stocks: StockRowDTO[];
};

export type StockRow = {
  warehouseId: number | null;
  warehouseName: string;
  quantity: string;
};

export type SupplierArtikl = {
  id: number;
  rmId: number | null;
  name: string;
  code: string | null;
  image: string | null;
  image50x75?: string | null;
  baseGroup: string | null;
  categoryId: number | null;
  categoryName: string | null;
  categoryPath: string[];
  unitId: number | null;
  unitName: string | null;
  price: number | null;
  stocks: StockRow[];
};

const toNumberOrNull = (value: string | null): number | null => {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isNaN(numeric) ? null : numeric;
};

export const mapSuppliers = (items: SupplierDTO[]): Supplier[] =>
  (items || []).map((supplier) => ({
    id: supplier.id,
    name: supplier.name,
    rmId: supplier.rm_id,
    defaultPaymentTypeId: supplier.default_payment_type ?? null,
  }));

export const mapSupplierArtikli = (
  items: SupplierArtiklDTO[]
): SupplierArtikl[] =>
  (items || []).map((item) => ({
    id: item.artikl_id,
    rmId: item.artikl_rm_id,
    name: item.name,
    code: item.code,
    image: item.image,
    image50x75: item.image_50x75 ?? null,
    baseGroup: item.base_group,
    categoryId: item.category_id ?? null,
    categoryName: item.category_name ?? null,
    categoryPath: item.category_path || [],
    unitId: item.unit_of_measure,
    unitName: item.unit_name,
    price: toNumberOrNull(item.price),
    stocks: (item.stocks || []).map((stock) => ({
      warehouseId: stock.warehouse_id,
      warehouseName: stock.warehouse_name,
      quantity: stock.quantity,
    })),
  }));
