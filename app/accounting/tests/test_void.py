from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import Ledger, JournalEntry


class VoidEntryTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")

    def test_can_void_draft(self):
        e = JournalEntry.objects.create(
            ledger=self.ledger,
            number=1,
            date=date(2026, 6, 3),
            status=JournalEntry.Status.DRAFT,
        )
        e.void()
        e.refresh_from_db()
        self.assertEqual(e.status, JournalEntry.Status.VOID)

    def test_cannot_void_posted(self):
        e = JournalEntry.objects.create(
            ledger=self.ledger,
            number=2,
            date=date(2026, 6, 3),
            status=JournalEntry.Status.POSTED,
        )
        with self.assertRaises(ValidationError):
            e.void()
