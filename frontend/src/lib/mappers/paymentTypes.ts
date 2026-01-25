export type PaymentTypeDTO = {
  id: number;
  name?: string | null;
};

export type PaymentType = {
  id: number;
  name: string;
};

export const mapPaymentTypes = (items: PaymentTypeDTO[]): PaymentType[] =>
  (items || []).map((item) => ({
    id: item.id,
    name: item.name || "Tip placanja",
  }));
