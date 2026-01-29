# Blagajnički dnevnik (Cash Ledger)

Blagajnički dnevnik je glavna i jedina vjerodostojna evidencija gotovine u sustavu.
Ne predstavlja poseban modul niti tablicu, već je izvještaj nad glavnom knjigom
(account ledger) filtriran na blagajnički konto.

Tehnički:
Cash Ledger = `account_ledger(default_cash_account, date_from, date_to)`

---

## Svrha

Blagajnički dnevnik služi za:
- svakodnevnu operativnu kontrolu gotovine
- primopredaju smjena
- utvrđivanje manjka/viška u blagajni
- usklađenje blagajne s bankom i knjigovodstvom
- porezni i revizijski trag

---

## Osnovno pravilo

Svi gotovinski događaji **moraju** biti evidentirani kroz `JournalEntry`
koje zahvaćaju blagajnički konto.

Nije dopušteno:
- voditi paralelne tablice gotovine
- ručno korigirati stanje blagajne izvan glavne knjige
- imati “operativno stanje” koje se ne može rekonstruirati iz ledger-a

---

## Tipovi gotovinskih događaja i knjiženja

### 1. ULAZ — gotovinska prodaja (gosti)

Gotovinska naplata računa iz POS-a.

Knjiženje:
- **D** Blagajna (cash)
- **P** Prihod od prodaje
- **P** PDV (ako je primjenjivo)

Napomena:
POS mora generirati JournalEntry za svaki gotovinski račun.

---

### 2. IZLAZ — isplata iz blagajne

Isplate iz blagajne (sitni troškovi, povrati gostima i sl.).

Knjiženje:
- **D** Trošak / potraživanje
- **P** Blagajna (cash)

Napomena:
Svaka isplata mora imati razlog i odgovornu osobu.

---

### 3. PLAĆANJE ROBE / USLUGA GOTOVINOM

Posebna podvrsta izlaza, koristi se radi jasne evidencije dobavljača.

Knjiženje:
- **D** Obveze prema dobavljaču ili trošak
- **P** Blagajna (cash)

Napomena:
Knjigovodstveno je isto kao izlaz, ali se semantički razlikuje.

---

### 4. POLOG NA BANKU

Predaja gotovine iz blagajne na bankovni račun.

Knjiženje:
- **D** Banka
- **P** Blagajna (cash)

Napomena:
Ovim događajem se smanjuje stanje blagajne, ali se ne radi o trošku.

---

### 5. POČETNI PLOG / PROMJENA

Početni iznos gotovine u blagajni (promjena) na početku rada ili smjene.

Knjiženje (primjer):
- **D** Blagajna (cash)
- **P** Kapital / interni konto

Napomena:
Ovaj događaj se koristi rijetko i mora biti jasno označen.

---

## Smjene i kontrola blagajne

Blagajnički dnevnik je temelj za kontrolu po smjenama.

Za svaku smjenu:
- sustav izračunava **očekivano stanje gotovine**
- konobar unosi **stvarno prebrojano stanje**
- razlika se evidentira kao:
  - manjak blagajne (rashod)
  - višak blagajne (prihod)

Ova razlika mora biti vidljiva u Cash Ledgeru.

---

## Odnos prema drugim evidencijama

- POS → generira gotovinske ulaze
- Smjene → operativna kontrola, ne zamjena za ledger
- Z dnevno → ide kroz `SalesZPosting`, a u ledger ulazi tek nakon “Post Z u Journal” (vidi [Prodajni tijek rada](../workflows/sales-workflow.md))
- Izvještaji → svi se temelje na account ledgeru

Cash Ledger je uvijek izvor istine.

---

## Sažetak

- Cash Ledger nije poseban servis
- Cash Ledger = account ledger nad blagajničkim kontom
- Svi gotovinski događaji prolaze kroz JournalEntry
- Operativa i knjigovodstvo gledaju isti podatak
