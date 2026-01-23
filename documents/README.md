# Dokumentacija (mozzart)

Ovaj dokument opisuje dodane funkcionalnosti vezane uz narudzbe, primke, cjenike, PDF mailer i konfiguracije.

## Narudzbe (purchase orders)

### Modeli
- `orders.PurchaseOrder`
  - `supplier` (FK -> `contacts.Supplier`)
  - `ordered_at`
  - `email_sent`
  - `total_net`, `total_gross` (racunaju se iz stavki)
  - `payment_type` (FK -> `configuration.PaymentType`)
- `orders.PurchaseOrderItem`
  - `purchase_order` (FK)
  - `artikl` (FK -> `artikli.Artikl`)
  - `quantity`, `unit_of_measure`
  - `price` (auto iz cjenika ako nije rucno unesena)
  - `unit_of_measure` (FK -> `artikli.UnitOfMeasureData`)
  - `order` (FK -> `orders.PurchaseOrder`) ako postoji legacy polje

### Auto cijene
- Ako `PurchaseOrderItem.price` nije unesena, sustav trazi cijenu u aktivnom cjeniku dobavljaca:
  - filtrira po `SupplierPriceList` (dobavljac, aktivno, datum unutar `valid_from/valid_to`)
  - prvo pokusava tocnu `unit_of_measure`, zatim fallback bez JM

### Ukupni iznosi
- `PurchaseOrder.save()` poziva `recalculate_totals()`.
- `PurchaseOrderItem.save()` i `PurchaseOrderItem.delete()` takoder pozivaju recalculation.
- Bruto se racuna preko `artikl.tax_group.rate`.

### Admin
- Autocomplete za dobavljaca i artikl/JM.
- Prikaz `total_net`, `total_gross`, `payment_type` u listi.
- Admin action: `Create warehouse input from purchase order` kreira primku iz narudzbe.
- `primka_created` se postavlja na `True` nakon kreiranja primke.

## Primke (WarehouseInput)

### Modeli
- `orders.WarehouseInput`
  - `supplier`, `payment_type`, `warehouse`, `date`, `total`
  - `purchase_order` (FK -> `orders.PurchaseOrder`)
  - `remaris_id` (ID primke u Remarisu)
- `orders.WarehouseInputItem`
  - `warehouse_input` (FK)
  - `artikl`, `quantity`, `unit_of_measure`, `price`, `total`, `tax_rate`

### Slanje u Remaris
- Admin action: `Send to Remaris`.
- Uspjesno slanje vraca HTML s `KeyId` koji se sprema u `WarehouseInput.remaris_id`.
- Payload je uskladen s Remaris formatom (stringovi u headeru, `Guid` po stavci na create, `AppContext` bez `PaymentMethodId/WarehouseId`).

## Cjenici dobavljaca

### Modeli
- `orders.SupplierPriceList` (zaglavlje)
  - `supplier`, `created_at`, `valid_from`, `valid_to`, `currency`, `is_active`
- `orders.SupplierPriceItem` (stavke)
  - `price_list`, `artikl`, `unit_of_measure`, `price`

### Admin
- `SupplierPriceList` ima inline stavke (tabular).
- Cijene se unose s decimalnim zarezom.
- Cijena je na 2 decimale, valuta je `EUR`.

## Porezne grupe

### Modeli
- `configuration.TaxGroup`
  - `name`, `rate`, `code`, `is_active`
- `artikli.Artikl.tax_group` (FK -> `TaxGroup`)

### Admin
- Porezne grupe se unose kroz admin.
- Dodijeli `tax_group` artiklima da bi se bruto racunao ispravno.

## Tipovi placanja

### Modeli
- `configuration.PaymentType`
  - `rm_id`, `name`, `code`, `is_active`

### Remaris import
- Admin akcija i Sync gumb za uvoz iz Remarisa.
- Endpoint: `PaymentMethod/GetPaymentMethods`
- `rm_id` mapiran na `Id` iz Remarisa.

### Sync gumb u adminu
- Na listi `Tipovi placanja` postoji gumb `Sync`.
- Sync se **ne** pokrece automatski.

## PDF narudzbe (mailer)

### Funkcionalnost
- Admin action na `PurchaseOrder` salje PDF na `supplier.orders_email`.
- PDF koristi DejaVuSans za hrvatske znakove.
- Sadrzi:
  - podatke tvrtke (logo, adresa, OIB, kontakt)
  - broj i datum narudzbe
  - dobavljaca i tip placanja
  - tablicu stavki (kolicina, JM, cijena, PDV, iznos)
  - ukupno: netto, PDV, bruto

### Konfiguracija
- `configuration.CompanyProfile` (podaci tvrtke + logo)
- `configuration.OrderEmailTemplate` (subject/body)

## SMTP postavke

- SMTP parametri su u `.env`:
  - `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
  - `EMAIL_USE_TLS=True` (587) ili `EMAIL_USE_SSL=True` (465)
- U `settings.py` se citaju iz environmenta.

## Napomene
- Language je postavljen na `hr` (decimalni zarez u adminu).
- Ako se lista `Tipovi placanja` rusi, provjeri da template postoji u `app/templates/admin/configuration/paymenttype/change_list.html`.
- `UnitOfMeasureData` ima Sync gumb u admin listi.

## Kako testirati
1) Unesi `CompanyProfile` i `OrderEmailTemplate` u adminu.
2) Napravi `SupplierPriceList` i stavke.
3) Kreiraj narudzbu i spremi stavke bez cijene.
4) Provjeri da su `price`, `total_net` i `total_gross` popunjeni.
5) Pokreni admin action `Send order email` i provjeri PDF.
6) Pokreni admin action `Create warehouse input from purchase order` i provjeri primku.
7) Pokreni admin action `Send to Remaris` i provjeri `remaris_id`.
