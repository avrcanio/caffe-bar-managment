# Kontrola blagajne po smjenama (Shift Cash Control)

Ovaj dokument definira kako se gotovina kontrolira po smjenama koristeći
Blagajnički dnevnik (Cash Ledger) kao jedini izvor istine.

---

## Svrha

Shift Cash Control služi za:
- primopredaju gotovine između smjena
- utvrđivanje manjka/viška po smjeni
- povezivanje odgovornosti s konkretnim konobarom
- osiguranje da se svi gotovinski događaji reflektiraju u Cash Ledgeru

---

## Osnovno pravilo

Smjene ne vode vlastitu blagajnu.
Smjene koriste Cash Ledger za izračun očekivanog stanja.

Sva gotovina se evidentira isključivo kroz JournalEntry
koje zahvaćaju blagajnički konto.

---

## Definicije

- Početak smjene – trenutak kada se konobar logira u POS
- Kraj smjene – trenutak primopredaje ili odjave
- Očekivano stanje – iznos koji POS izračuna iz Cash Ledgera
- Stvarno stanje – iznos koji konobar fizički prebroji

---

## Izračun očekivanog stanja gotovine

POS mora izračunati očekivano stanje gotovine na početku i kraju smjene:

očekivano_stanje
= saldo_blagajne_u_ledgeru_u_trenutku_primopredaje

> Nema ručnog unosa očekivanog iznosa.

---

## Početak smjene (preuzimanje)

- Konobar se logira u POS
- POS prikazuje modal:
  - očekivani iznos gotovine
- Konobar:
  - fizički prebroji blagajnu
  - unosi stvarno stanje
- Sustav izračunava razliku:
  - razlika = stvarno − očekivano

Pravila:
- ako je razlika ≠ 0 → obavezna napomena
- smjena se ne može započeti bez potvrde

---

## Tijekom smjene

Tijekom smjene mogu se događati:
- gotovinske naplate (POS računi)
- gotovinske isplate
- plaćanja robe/usluga gotovinom

> Sve navedeno mora generirati JournalEntry
> koji zahvaća blagajnički konto.

Smjena nema pravo:
- ručno korigirati stanje blagajne
- unositi “ispravke” bez knjiženja

---

## Kraj smjene (predaja)

- Konobar bira “Završi smjenu”
- POS:
  - izračuna očekivano stanje gotovine
- Konobar:
  - fizički prebroji blagajnu
  - unosi stvarno stanje
- Sustav računa razliku

Ako je:
- razlika < 0 → manjak blagajne
- razlika > 0 → višak blagajne

Razlika se mora potvrditi i evidentirati.

---

## Evidencija manjka / viška

Razlika se evidentira kao poseban događaj:

Manjak blagajne
- operativno: vezan uz smjenu i konobara
- knjigovodstveno:
  - D Manjak u blagajni
  - P Blagajna

Višak blagajne
- knjigovodstveno:
  - D Blagajna
  - P Višak u blagajni

> Knjiženje se može napraviti:
> - odmah
> - ili agregirano na kraju dana (po pravilima sustava)

---

## Primopredaja između smjena

Ako smjena predaje drugoj smjeni:
- predavatelj:
  - zaključuje smjenu
- preuzimatelj:
  - potvrđuje očekivano stanje
  - unosi stvarno stanje

Obje strane ostavljaju trag u sustavu.

---

## Odnos prema Cash Ledgeru

Shift Cash Control ne zamjenjuje Cash Ledger.
Shift Cash Control koristi Cash Ledger.

Cash Ledger je uvijek:
- referenca za očekivano stanje
- osnova za reviziju
- izvor istine za računovodstvo

---

## Sažetak

- Smjene kontroliraju, ali ne vode gotovinu
- Cash Ledger je jedina evidencija
- Razlika se uvijek vidi, nikad ne skriva
- Odgovornost je jasna i sljediva

---

## Preporuke iz prakse

- uvesti toleranciju (npr. ±0,50 €)
- obavezna napomena za svaku razliku
- zaključavanje smjene bez unosa stanja
