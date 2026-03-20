import os
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from artikli.models import Artikl, DrinkCategory, Normativ, NormativItem
from barion.models import (
    BarionRuntimeMode,
    Check,
    CheckItem,
    CheckItemModifierSelection,
    ItemModifierDefaultSelection,
    ItemModifierGroup,
    ItemBundleOption,
    ItemModifierGroupAssignment,
    ItemModifierOption,
    Layout,
    LayoutTable,
    ProductPopularitySnapshot,
    SettlementPart,
    Table,
    TableState,
    UserLayoutAccess,
    Zone,
)
from configuration.models import TaxGroup
from pos.models import PosProfile, PosReceipt
from sales.models import SalesPriceItem, SalesPriceList
from stock.models import StockLot, StockMove, WarehouseId


class PosActiveLayoutApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-api-user",
            email="barion@example.com",
            password="pass1234",
        )

    def test_requires_authentication(self):
        response = self.client.get("/api/pos/active-layout/", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_returns_409_when_user_has_no_layout_access(self):
        self.client.force_authenticate(user=self.user)
        Layout.objects.create(name="Main", is_active=True)

        response = self.client.get("/api/pos/active-layout/", secure=True)
        self.assertEqual(response.status_code, 409, response.json())

    def test_returns_active_layout_zones_and_tables_from_layout_table(self):
        self.client.force_authenticate(user=self.user)

        inactive_layout = Layout.objects.create(name="Old", is_active=False)
        active_layout = Layout.objects.create(name="Main", is_active=True)

        z_lounge = Zone.objects.create(layout=active_layout, name="Lounge", order=20)
        z_bar = Zone.objects.create(layout=active_layout, name="Bar", order=10)
        Zone.objects.create(layout=inactive_layout, name="Old zone", order=1)

        t1 = Table.objects.create(label="T1", capacity=4, shape=Table.Shape.ROUND, is_vip=False)
        t2 = Table.objects.create(label="VIP-2", capacity=6, shape=Table.Shape.RECTANGLE, is_vip=True)
        Table.objects.create(label="Unplaced", capacity=2, shape=Table.Shape.SQUARE, is_vip=False)

        LayoutTable.objects.create(
            layout=active_layout,
            table=t1,
            zone=z_bar,
            x=100,
            y=200,
            w=90,
            h=90,
            rotation=0,
            z_index=2,
            is_enabled=True,
        )
        LayoutTable.objects.create(
            layout=active_layout,
            table=t2,
            zone=z_lounge,
            x=300,
            y=400,
            w=120,
            h=80,
            rotation=15,
            z_index=1,
            is_enabled=True,
        )
        LayoutTable.objects.create(
            layout=inactive_layout,
            table=t1,
            zone=Zone.objects.create(layout=inactive_layout, name="Ignored", order=1),
            x=1,
            y=1,
            w=1,
            h=1,
            rotation=0,
            z_index=1,
            is_enabled=True,
        )
        UserLayoutAccess.objects.create(user=self.user, layout=active_layout, is_default=True, is_active=True)

        response = self.client.get("/api/pos/active-layout/", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("ETag", response)
        self.assertEqual(response["Cache-Control"], "private, max-age=30")

        data = response.json()
        self.assertEqual(data["layout"]["id"], active_layout.id)
        self.assertEqual(data["layout"]["name"], "Main")
        self.assertIn("updated_at", data["layout"])

        zones = data["zones"]
        self.assertEqual([z["name"] for z in zones], ["Bar", "Lounge"])
        self.assertEqual([z["order"] for z in zones], [10, 20])
        self.assertEqual([z["id"] for z in zones], [z_bar.id, z_lounge.id])

        tables = data["tables"]
        self.assertEqual(len(tables), 2)
        self.assertEqual(
            set(tables[0].keys()),
            {"table_id", "label", "shape", "capacity", "is_vip", "x", "y", "w", "h", "rotation", "zone_id"},
        )
        by_id = {row["table_id"]: row for row in tables}
        self.assertEqual(by_id[t1.id]["zone_id"], z_bar.id)
        self.assertEqual(by_id[t1.id]["shape"], Table.Shape.ROUND)
        self.assertEqual(by_id[t2.id]["zone_id"], z_lounge.id)
        self.assertEqual(by_id[t2.id]["rotation"], 15)

    def test_returns_304_for_matching_etag(self):
        self.client.force_authenticate(user=self.user)
        layout = Layout.objects.create(name="Main", is_active=True)
        zone = Zone.objects.create(layout=layout, name="Main zone", order=1)
        table = Table.objects.create(label="T1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        LayoutTable.objects.create(layout=layout, table=table, zone=zone, x=0, y=0, w=90, h=90, rotation=0, z_index=0)
        UserLayoutAccess.objects.create(user=self.user, layout=layout, is_default=True, is_active=True)

        first = self.client.get("/api/pos/active-layout/", secure=True)
        self.assertEqual(first.status_code, 200, first.content)
        etag = first["ETag"]

        second = self.client.get(
            "/api/pos/active-layout/",
            secure=True,
            HTTP_IF_NONE_MATCH=etag,
        )
        self.assertEqual(second.status_code, 304, second.content)
        self.assertEqual(second["ETag"], etag)

    def test_can_switch_to_allowed_layout(self):
        self.client.force_authenticate(user=self.user)
        layout_a = Layout.objects.create(name="Main", is_active=True)
        layout_b = Layout.objects.create(name="Terrace", is_active=True)
        zone_a = Zone.objects.create(layout=layout_a, name="Main zone", order=1)
        zone_b = Zone.objects.create(layout=layout_b, name="Terrace zone", order=1)
        table_a = Table.objects.create(label="A1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        table_b = Table.objects.create(label="B1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        LayoutTable.objects.create(layout=layout_a, table=table_a, zone=zone_a)
        LayoutTable.objects.create(layout=layout_b, table=table_b, zone=zone_b)
        UserLayoutAccess.objects.create(user=self.user, layout=layout_a, is_default=True, is_active=True)
        UserLayoutAccess.objects.create(user=self.user, layout=layout_b, is_default=False, is_active=True)

        response = self.client.get(f"/api/pos/active-layout/?layout_id={layout_b.id}", secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["layout"]["id"], layout_b.id)
        self.assertEqual(data["resolved_by"], "selected")

    def test_rejects_unassigned_layout(self):
        self.client.force_authenticate(user=self.user)
        layout_a = Layout.objects.create(name="Main", is_active=True)
        layout_b = Layout.objects.create(name="Terrace", is_active=True)
        UserLayoutAccess.objects.create(user=self.user, layout=layout_a, is_default=True, is_active=True)

        response = self.client.get(f"/api/pos/active-layout/?layout_id={layout_b.id}", secure=True)
        self.assertEqual(response.status_code, 403, response.content)

    def test_allowed_layouts_endpoint(self):
        self.client.force_authenticate(user=self.user)
        layout_a = Layout.objects.create(name="Main", is_active=True)
        layout_b = Layout.objects.create(name="Terrace", is_active=True)
        UserLayoutAccess.objects.create(user=self.user, layout=layout_a, is_default=True, is_active=True)
        UserLayoutAccess.objects.create(user=self.user, layout=layout_b, is_default=False, is_active=True)

        response = self.client.get("/api/pos/layouts/allowed/", secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()["layouts"]
        self.assertEqual([row["id"] for row in payload], [layout_a.id, layout_b.id])
        self.assertEqual(payload[0]["is_default"], True)
        self.assertEqual(payload[1]["is_default"], False)

    def test_active_layout_can_include_allowed_layouts(self):
        self.client.force_authenticate(user=self.user)
        layout_a = Layout.objects.create(name="Main", is_active=True)
        layout_b = Layout.objects.create(name="Terrace", is_active=True)
        zone_a = Zone.objects.create(layout=layout_a, name="Main zone", order=1)
        table_a = Table.objects.create(label="A1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        LayoutTable.objects.create(layout=layout_a, table=table_a, zone=zone_a)
        UserLayoutAccess.objects.create(user=self.user, layout=layout_a, is_default=True, is_active=True)
        UserLayoutAccess.objects.create(user=self.user, layout=layout_b, is_default=False, is_active=True)

        response = self.client.get("/api/pos/active-layout/?include_allowed=1", secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertIn("allowed_layouts", payload)
        self.assertEqual([row["id"] for row in payload["allowed_layouts"]], [layout_a.id, layout_b.id])


class PosTableStatusApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-status-user",
            email="barion-status@example.com",
            password="pass1234",
        )

    def test_requires_authentication(self):
        response = self.client.get("/api/pos/table-status/?layout_id=1", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_requires_layout_id(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/table-status/", secure=True)
        self.assertEqual(response.status_code, 400, response.json())

    def test_returns_404_for_unknown_layout(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/table-status/?layout_id=99999", secure=True)
        self.assertEqual(response.status_code, 404, response.json())

    def test_returns_statuses_with_free_fallback(self):
        self.client.force_authenticate(user=self.user)

        layout = Layout.objects.create(name="Main", is_active=True)
        zone = Zone.objects.create(layout=layout, name="Main zone", order=1)
        other_layout = Layout.objects.create(name="Other", is_active=False)
        other_zone = Zone.objects.create(layout=other_layout, name="Other zone", order=1)

        table_1 = Table.objects.create(label="T1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        table_2 = Table.objects.create(label="T2", capacity=6, shape=Table.Shape.ROUND, is_vip=False)
        table_3 = Table.objects.create(label="T3", capacity=2, shape=Table.Shape.RECTANGLE, is_vip=False)

        lt_1 = LayoutTable.objects.create(
            layout=layout,
            table=table_1,
            zone=zone,
            x=10,
            y=20,
            w=90,
            h=90,
            rotation=0,
            z_index=2,
            is_enabled=True,
        )
        LayoutTable.objects.create(
            layout=layout,
            table=table_2,
            zone=zone,
            x=20,
            y=30,
            w=90,
            h=90,
            rotation=0,
            z_index=1,
            is_enabled=True,
        )
        lt_3_disabled = LayoutTable.objects.create(
            layout=layout,
            table=table_3,
            zone=zone,
            x=30,
            y=40,
            w=90,
            h=90,
            rotation=0,
            z_index=3,
            is_enabled=False,
        )
        lt_other = LayoutTable.objects.create(
            layout=other_layout,
            table=table_3,
            zone=other_zone,
            x=1,
            y=1,
            w=1,
            h=1,
            rotation=0,
            z_index=1,
            is_enabled=True,
        )
        UserLayoutAccess.objects.create(user=self.user, layout=layout, is_default=True, is_active=True)

        TableState.objects.create(
            layout_table=lt_1,
            state=TableState.State.OPEN,
            open_check_id=555,
            updated_by=self.user,
        )
        TableState.objects.create(
            layout_table=lt_other,
            state=TableState.State.BLOCKED,
            open_check_id=None,
            updated_by=self.user,
        )

        response = self.client.get(f"/api/pos/table-status/?layout_id={layout.id}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()

        # sorted by layout placement order (z_index asc)
        self.assertEqual([row["table_id"] for row in data], [table_2.id, table_1.id])
        by_table_id = {row["table_id"]: row for row in data}

        self.assertEqual(by_table_id[table_1.id]["status"], TableState.State.OPEN)
        self.assertEqual(by_table_id[table_1.id]["open_check_id"], 555)

        self.assertEqual(by_table_id[table_2.id]["status"], TableState.State.FREE)
        self.assertIsNone(by_table_id[table_2.id]["open_check_id"])

        # disabled/other-layout placements are excluded
        self.assertNotIn(table_3.id, by_table_id)
        self.assertNotIn(lt_3_disabled.table_id, [row["table_id"] for row in data])

    def test_returns_403_for_layout_without_access(self):
        self.client.force_authenticate(user=self.user)
        layout = Layout.objects.create(name="Main", is_active=True)
        other_layout = Layout.objects.create(name="Other", is_active=True)
        UserLayoutAccess.objects.create(user=self.user, layout=layout, is_default=True, is_active=True)

        response = self.client.get(f"/api/pos/table-status/?layout_id={other_layout.id}", secure=True)
        self.assertEqual(response.status_code, 403, response.content)


class TableStateModelTests(TestCase):
    def test_consistency_rules(self):
        layout = Layout.objects.create(name="Main", is_active=True)
        zone = Zone.objects.create(layout=layout, name="Main zone", order=1)
        table = Table.objects.create(label="T1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        placement = LayoutTable.objects.create(
            layout=layout,
            table=table,
            zone=zone,
            x=10,
            y=20,
            w=90,
            h=90,
            rotation=0,
            z_index=1,
            is_enabled=True,
        )

        with self.assertRaises(ValidationError):
            TableState.objects.create(
                layout_table=placement,
                state=TableState.State.OPEN,
                open_check_id=None,
            )

        with self.assertRaises(ValidationError):
            TableState.objects.create(
                layout_table=placement,
                state=TableState.State.FREE,
                open_check_id=123,
            )


class UserLayoutAccessModelTests(TestCase):
    def test_allows_single_default_per_user(self):
        User = get_user_model()
        user = User.objects.create_user(username="layout-user", email="layout-user@example.com", password="pass1234")
        layout_a = Layout.objects.create(name="Main", is_active=True)
        layout_b = Layout.objects.create(name="Terrace", is_active=True)

        UserLayoutAccess.objects.create(user=user, layout=layout_a, is_default=True, is_active=True)
        with self.assertRaises(IntegrityError):
            UserLayoutAccess.objects.create(user=user, layout=layout_b, is_default=True, is_active=True)

    def test_allows_second_default_when_first_is_inactive(self):
        User = get_user_model()
        user = User.objects.create_user(username="layout-user-2", email="layout-user-2@example.com", password="pass1234")
        layout_a = Layout.objects.create(name="Main", is_active=True)
        layout_b = Layout.objects.create(name="Terrace", is_active=True)

        UserLayoutAccess.objects.create(user=user, layout=layout_a, is_default=True, is_active=False)
        UserLayoutAccess.objects.create(user=user, layout=layout_b, is_default=True, is_active=True)


class PosChecksApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-check-user",
            email="barion-check@example.com",
            password="pass1234",
        )

        self.layout = Layout.objects.create(name="Main", is_active=True)
        self.zone = Zone.objects.create(layout=self.layout, name="Main", order=1)
        self.table = Table.objects.create(label="T1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        self.other_table = Table.objects.create(label="T2", capacity=2, shape=Table.Shape.ROUND, is_vip=False)
        self.placement = LayoutTable.objects.create(
            layout=self.layout,
            table=self.table,
            zone=self.zone,
            x=10,
            y=10,
            w=90,
            h=90,
            rotation=0,
            z_index=1,
            is_enabled=True,
        )

    def test_post_checks_requires_auth(self):
        response = self.client.post("/api/pos/checks/", data={"table_id": self.table.id}, format="json", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_post_checks_creates_check_and_keeps_table_state_free(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post("/api/pos/checks/", data={"table_id": self.table.id}, format="json", secure=True)
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertTrue(data["created"])
        check_id = data["check"]["id"]
        self.assertEqual(data["check"]["table_id"], self.table.id)
        self.assertEqual(data["check"]["status"], Check.Status.OPEN)

        state = TableState.objects.get(layout_table=self.placement)
        self.assertEqual(state.state, TableState.State.FREE)
        self.assertIsNone(state.open_check_id)

    def test_first_check_item_switches_table_state_to_open(self):
        self.client.force_authenticate(user=self.user)
        create = self.client.post("/api/pos/checks/", data={"table_id": self.table.id}, format="json", secure=True)
        self.assertEqual(create.status_code, 201, create.content)
        check_id = create.json()["check"]["id"]

        tax_group = TaxGroup.objects.create(name="PDV 25 pos-check", code="PDV25CHK", rate="0.2500")
        artikl = Artikl.objects.create(
            name="Test artikl",
            code="CHK-OPEN-1",
            is_sellable=True,
            is_stock_item=False,
            tax_group=tax_group,
        )
        add_item = self.client.post(
            f"/api/pos/checks/{check_id}/items/",
            data={
                "artikl_id": artikl.id,
                "quantity": "1.0000",
                "unit_price": "3.0000",
                "vat_rate": "0.2500",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(add_item.status_code, 201, add_item.content)

        state = TableState.objects.get(layout_table=self.placement)
        self.assertEqual(state.state, TableState.State.OPEN)
        self.assertEqual(state.open_check_id, check_id)

    def test_post_checks_returns_existing_open_check(self):
        self.client.force_authenticate(user=self.user)
        check = Check.objects.create(table=self.table, status=Check.Status.OPEN, opened_by=self.user)

        response = self.client.post("/api/pos/checks/", data={"table_id": self.table.id}, format="json", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertFalse(data["created"])
        self.assertEqual(data["check"]["id"], check.id)
        self.assertEqual(Check.objects.filter(table=self.table, status=Check.Status.OPEN).count(), 1)

    def test_get_checks_by_table(self):
        self.client.force_authenticate(user=self.user)
        check = Check.objects.create(table=self.table, status=Check.Status.OPEN, opened_by=self.user)

        response = self.client.get(f"/api/pos/checks/?table_id={self.table.id}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["id"], check.id)

    def test_get_checks_returns_404_when_missing(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/pos/checks/?table_id={self.table.id}", secure=True)
        self.assertEqual(response.status_code, 404, response.content)

    def test_close_check_sets_table_state_free(self):
        self.client.force_authenticate(user=self.user)
        check = Check.objects.create(table=self.table, status=Check.Status.OPEN, opened_by=self.user)
        TableState.objects.create(
            layout_table=self.placement,
            state=TableState.State.OPEN,
            open_check_id=check.id,
            updated_by=self.user,
        )

        response = self.client.post(f"/api/pos/checks/{check.id}/close/", data={}, format="json", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Check.Status.CLOSED)

        check.refresh_from_db()
        self.assertEqual(check.status, Check.Status.CLOSED)
        self.assertIsNotNone(check.closed_at)

        state = TableState.objects.get(layout_table=self.placement)
        self.assertEqual(state.state, TableState.State.FREE)
        self.assertIsNone(state.open_check_id)

    def test_close_check_conflict_when_already_closed(self):
        self.client.force_authenticate(user=self.user)
        check = Check.objects.create(table=self.table, status=Check.Status.CLOSED, opened_by=self.user)
        response = self.client.post(f"/api/pos/checks/{check.id}/close/", data={}, format="json", secure=True)
        self.assertEqual(response.status_code, 409, response.content)


class CheckModelTests(TestCase):
    def test_allows_only_one_open_check_per_table(self):
        table = Table.objects.create(label="T100", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        Check.objects.create(table=table, status=Check.Status.OPEN)
        with self.assertRaises(IntegrityError):
            Check.objects.create(table=table, status=Check.Status.OPEN)


class CheckItemModelTests(TestCase):
    def test_amounts_are_computed_on_save(self):
        table = Table.objects.create(label="T200", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        check = Check.objects.create(table=table, status=Check.Status.OPEN)
        tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        artikl = Artikl.objects.create(
            name="Cedevita",
            code="CED01",
            is_sellable=True,
            is_stock_item=False,
            tax_group=tax_group,
        )
        item = CheckItem.objects.create(
            barion_check=check,
            artikl=artikl,
            quantity="2.0000",
            unit_price="3.5000",
            vat_rate="0.2500",
        )
        self.assertEqual(str(item.total_amount), "7.00")
        self.assertEqual(str(item.net_amount), "5.60")
        self.assertEqual(str(item.vat_amount), "1.40")


class LayoutEditorAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="barion-admin",
            email="barion-admin@example.com",
            password="pass1234",
        )
        self.client.force_login(self.admin_user)

        self.layout = Layout.objects.create(name="Editor layout", is_active=True)
        self.zone_main = Zone.objects.create(layout=self.layout, name="Main", order=1)
        self.zone_vip = Zone.objects.create(layout=self.layout, name="VIP", order=2)
        self.table_1 = Table.objects.create(label="A1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        self.table_2 = Table.objects.create(label="A2", capacity=4, shape=Table.Shape.RECTANGLE, is_vip=True)
        self.layout_table = LayoutTable.objects.create(
            layout=self.layout,
            table=self.table_1,
            zone=self.zone_main,
            x=100,
            y=200,
            w=90,
            h=90,
            rotation=0,
            is_enabled=True,
            z_index=1,
        )

    def test_editor_data_endpoint(self):
        url = reverse("admin:barion_layout_editor_data", args=[self.layout.id])
        response = self.client.get(url, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["layout"]["id"], self.layout.id)
        self.assertEqual([z["name"] for z in data["zones"]], ["Main", "VIP"])
        self.assertEqual(len(data["placements"]), 1)
        self.assertEqual(data["placements"][0]["zone_id"], self.zone_main.id)
        self.assertEqual(len(data["available_tables"]), 1)
        self.assertEqual(data["available_tables"][0]["id"], self.table_2.id)

    def test_editor_save_updates_and_creates(self):
        url = reverse("admin:barion_layout_editor_save", args=[self.layout.id])
        payload = {
            "placements": [
                {
                    "layout_table_id": self.layout_table.id,
                    "x": 150,
                    "y": 250,
                    "w": 110,
                    "h": 95,
                    "rotation": 15,
                    "is_enabled": True,
                    "zone_id": self.zone_vip.id,
                    "z_index": 3,
                },
                {
                    "layout_table_id": None,
                    "table_id": self.table_2.id,
                    "zone_id": self.zone_main.id,
                    "x": 40,
                    "y": 60,
                    "w": 120,
                    "h": 80,
                    "rotation": 0,
                    "is_enabled": True,
                    "z_index": 4,
                },
            ]
        }
        response = self.client.post(
            url,
            data=payload,
            content_type="application/json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["ok"], True)

        self.layout_table.refresh_from_db()
        self.assertEqual(self.layout_table.x, 150)
        self.assertEqual(self.layout_table.zone_id, self.zone_vip.id)
        self.assertEqual(
            LayoutTable.objects.filter(layout=self.layout, table=self.table_2).count(),
            1,
        )

    def test_editor_data_creates_default_zone_when_missing(self):
        no_zone_layout = Layout.objects.create(name="No zone layout", is_active=False)
        url = reverse("admin:barion_layout_editor_data", args=[no_zone_layout.id])

        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(len(data["zones"]), 1)
        self.assertEqual(data["zones"][0]["name"], "Main")
        self.assertTrue(Zone.objects.filter(layout=no_zone_layout, name="Main").exists())

    def test_editor_data_maps_invalid_zone_to_fallback_zone(self):
        other_layout = Layout.objects.create(name="Other layout", is_active=False)
        other_zone = Zone.objects.create(layout=other_layout, name="Other", order=1)
        self.layout_table.zone = other_zone
        self.layout_table.save(update_fields=["zone", "updated_at"])

        url = reverse("admin:barion_layout_editor_data", args=[self.layout.id])
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(len(data["placements"]), 1)
        self.assertEqual(data["placements"][0]["zone_id"], self.zone_main.id)


class PosCheckItemsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-check-item-user",
            email="barion-check-item@example.com",
            password="pass1234",
        )
        self.table = Table.objects.create(label="T300", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        self.check = Check.objects.create(table=self.table, status=Check.Status.OPEN, opened_by=self.user)
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.artikl_kava = Artikl.objects.create(
            name="Kava",
            code="KAV300",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        self.artikl_sok = Artikl.objects.create(
            name="Sok",
            code="SOK300",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        self.coffee_group = ItemModifierGroup.objects.create(
            name="Coffee edits",
            code="coffee-edits",
            selection_mode=ItemModifierGroup.SelectionMode.MULTIPLE,
            min_select=0,
            max_select=3,
            allow_note=True,
            sort_order=10,
        )
        self.opt_natren = ItemModifierOption.objects.create(
            group=self.coffee_group,
            name="Natren",
            code="natren",
            sort_order=10,
        )
        self.opt_cold_milk = ItemModifierOption.objects.create(
            group=self.coffee_group,
            name="Hladno mlijeko",
            code="cold-milk",
            sort_order=20,
        )
        ItemModifierGroupAssignment.objects.create(
            artikl=self.artikl_kava,
            group=self.coffee_group,
            is_active=True,
            is_required=False,
        )
        self.artikl_boca = Artikl.objects.create(
            name="Grey Goose Vodka 0.7l",
            code="GG700",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        self.artikl_mixer_juice = Artikl.objects.create(
            name="Orange Juice",
            code="MIXJ01",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        self.artikl_mixer_rb = Artikl.objects.create(
            name="Red Bull",
            code="MIXRB01",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        self.bundle_group = ItemModifierGroup.objects.create(
            name="Bottle mixers",
            code="bottle-mixers",
            type=ItemModifierGroup.Type.BUNDLE,
            selection_mode=ItemModifierGroup.SelectionMode.MULTIPLE,
            min_select=4,
            max_select=4,
            allow_note=True,
            sort_order=20,
        )
        self.bundle_opt_juice = ItemBundleOption.objects.create(
            group=self.bundle_group,
            artikl=self.artikl_mixer_juice,
            price_delta="2.5000",
            sort_order=10,
        )
        self.bundle_opt_rb = ItemBundleOption.objects.create(
            group=self.bundle_group,
            artikl=self.artikl_mixer_rb,
            price_delta="5.0000",
            sort_order=20,
        )
        ItemModifierGroupAssignment.objects.create(
            artikl=self.artikl_boca,
            group=self.bundle_group,
            is_active=True,
            is_required=True,
        )
        self.bundle_price_list = SalesPriceList.objects.create(
            name="Bundle test cjenik",
            is_active=True,
            is_default=False,
            valid_from=timezone.now() + timezone.timedelta(minutes=-2),
        )
        SalesPriceItem.objects.create(
            price_list=self.bundle_price_list,
            artikl=self.artikl_boca,
            unit_price_gross="150.00",
            is_active=True,
        )

    def test_list_items_returns_totals(self):
        self.client.force_authenticate(user=self.user)
        CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="1.0000",
            unit_price="2.0000",
            vat_rate="0.2500",
        )
        CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_sok,
            quantity="2.0000",
            unit_price="3.0000",
            vat_rate="0.2500",
        )

        response = self.client.get(f"/api/pos/checks/{self.check.id}/items/", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["check_id"], self.check.id)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["totals"]["items_count"], 2)
        self.assertEqual(float(data["totals"]["total_amount"]), 8.0)

    def test_create_patch_delete_item(self):
        self.client.force_authenticate(user=self.user)
        create_response = self.client.post(
            f"/api/pos/checks/{self.check.id}/items/",
            data={
                "artikl_id": self.artikl_sok.id,
                "quantity": "2.0000",
                "unit_price": "2.5000",
                "vat_rate": "0.2500",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(create_response.status_code, 201, create_response.content)
        item_id = create_response.json()["id"]

        patch_response = self.client.patch(
            f"/api/pos/check-items/{item_id}/",
            data={"quantity": "3.0000"},
            format="json",
            secure=True,
        )
        self.assertEqual(patch_response.status_code, 200, patch_response.content)
        self.assertEqual(float(patch_response.json()["total_amount"]), 7.5)

        delete_response = self.client.delete(
            f"/api/pos/check-items/{item_id}/",
            secure=True,
        )
        self.assertEqual(delete_response.status_code, 204, delete_response.content)

    def test_add_item_reopens_closed_check(self):
        self.client.force_authenticate(user=self.user)
        self.check.status = Check.Status.CLOSED
        self.check.closed_by = self.user
        self.check.closed_at = timezone.now()
        self.check.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])

        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/items/",
            data={
                "artikl_id": self.artikl_sok.id,
                "quantity": "1.0000",
                "unit_price": "2.5000",
                "vat_rate": "0.2500",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.content)

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, Check.Status.OPEN)
        self.assertIsNone(self.check.closed_at)
        self.assertIsNone(self.check.closed_by)

    def test_rejects_fractional_quantity_on_create_and_patch(self):
        self.client.force_authenticate(user=self.user)
        create_response = self.client.post(
            f"/api/pos/checks/{self.check.id}/items/",
            data={
                "artikl_id": self.artikl_sok.id,
                "quantity": "1.5000",
                "unit_price": "2.5000",
                "vat_rate": "0.2500",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(create_response.status_code, 400, create_response.content)
        self.assertIn("quantity", create_response.json())

        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="2.0000",
            unit_price="3.0000",
            vat_rate="0.2500",
        )
        patch_response = self.client.patch(
            f"/api/pos/check-items/{item.id}/",
            data={"quantity": "2.5000"},
            format="json",
            secure=True,
        )
        self.assertEqual(patch_response.status_code, 400, patch_response.content)
        self.assertIn("quantity", patch_response.json())

    def test_storno_creates_negative_item_on_same_check(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="2.0000",
            unit_price="3.0000",
            vat_rate="0.2500",
        )

        response = self.client.post(
            f"/api/pos/check-items/{item.id}/storno/",
            data={"reason": "krivi unos"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["line_type"], CheckItem.LineType.STORNO)
        self.assertEqual(payload["check_id"], self.check.id)
        self.assertEqual(float(payload["quantity"]), -2.0)
        self.assertEqual(float(payload["unit_price"]), 3.0)

        duplicate = self.client.post(
            f"/api/pos/check-items/{item.id}/storno/",
            data={"reason": "ponovo"},
            format="json",
            secure=True,
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.content)
        self.assertEqual(
            CheckItem.objects.filter(
                barion_check=self.check,
                line_type=CheckItem.LineType.STORNO,
            ).count(),
            1,
        )

    def test_storno_supports_partial_quantity(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="5.0000",
            unit_price="4.0000",
            vat_rate="0.2500",
            round_number=7,
        )

        response = self.client.post(
            f"/api/pos/check-items/{item.id}/storno/",
            data={"quantity": "2.0000", "reason": "parcijalno"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(float(payload["quantity"]), -2.0)
        self.assertEqual(payload["line_type"], CheckItem.LineType.STORNO)
        self.assertEqual(payload["round_number"], 7)

        over = self.client.post(
            f"/api/pos/check-items/{item.id}/storno/",
            data={"quantity": "4.0000"},
            format="json",
            secure=True,
        )
        self.assertEqual(over.status_code, 400, over.content)

    def test_gratis_keeps_quantity_and_sets_price_to_zero(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_sok,
            quantity="2.0000",
            unit_price="4.0000",
            vat_rate="0.2500",
        )

        response = self.client.post(
            f"/api/pos/check-items/{item.id}/gratis/",
            data={"reason": "kuća časti"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["line_type"], CheckItem.LineType.GRATIS)
        self.assertEqual(float(payload["quantity"]), 2.0)
        self.assertEqual(float(payload["unit_price"]), 0.0)
        self.assertEqual(float(payload["total_amount"]), 0.0)

    def test_gratis_supports_partial_quantity_split(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_sok,
            quantity="5.0000",
            unit_price="4.0000",
            vat_rate="0.2500",
            round_number=9,
        )

        response = self.client.post(
            f"/api/pos/check-items/{item.id}/gratis/",
            data={"quantity": "2.0000", "reason": "parcijalno"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["line_type"], CheckItem.LineType.GRATIS)
        self.assertEqual(float(payload["quantity"]), 2.0)
        self.assertEqual(float(payload["unit_price"]), 0.0)
        self.assertEqual(payload["round_number"], 9)

        item.refresh_from_db()
        self.assertEqual(float(item.quantity), 5.0)
        self.assertEqual(item.line_type, CheckItem.LineType.NORMAL)

    def test_gratis_after_storno_is_limited_to_remaining_quantity(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="7.0000",
            unit_price="5.0000",
            vat_rate="0.2500",
            round_number=3,
        )
        storno = self.client.post(
            f"/api/pos/check-items/{item.id}/storno/",
            data={"quantity": "2.0000"},
            format="json",
            secure=True,
        )
        self.assertEqual(storno.status_code, 201, storno.content)

        gratis = self.client.post(
            f"/api/pos/check-items/{item.id}/gratis/",
            data={"quantity": "5.0000", "reason": "naknadno"},
            format="json",
            secure=True,
        )
        self.assertEqual(gratis.status_code, 200, gratis.content)
        gratis_payload = gratis.json()
        self.assertEqual(gratis_payload["line_type"], CheckItem.LineType.GRATIS)
        self.assertEqual(float(gratis_payload["quantity"]), 5.0)
        self.assertEqual(gratis_payload["round_number"], 3)

        too_much = self.client.post(
            f"/api/pos/check-items/{item.id}/gratis/",
            data={"quantity": "1.5000"},
            format="json",
            secure=True,
        )
        self.assertEqual(too_much.status_code, 400, too_much.content)

    def test_otpis_supports_partial_quantity_split(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_sok,
            quantity="6.0000",
            unit_price="5.0000",
            vat_rate="0.2500",
            round_number=4,
        )

        response = self.client.post(
            f"/api/pos/check-items/{item.id}/otpis/",
            data={"quantity": "2.0000", "reason": "lom"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["line_type"], CheckItem.LineType.OTPIS)
        self.assertEqual(float(payload["quantity"]), 2.0)
        self.assertEqual(float(payload["unit_price"]), 0.0)
        self.assertEqual(payload["round_number"], 4)

        item.refresh_from_db()
        self.assertEqual(float(item.quantity), 6.0)
        self.assertEqual(item.line_type, CheckItem.LineType.NORMAL)

    def test_otpis_rejects_non_normal_lines(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="1.0000",
            unit_price="3.0000",
            vat_rate="0.2500",
            line_type=CheckItem.LineType.GRATIS,
        )
        response = self.client.post(
            f"/api/pos/check-items/{item.id}/otpis/",
            data={"quantity": "1.0000"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 409, response.content)

    def test_cannot_storno_item_that_is_gratis(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_sok,
            quantity="1.0000",
            unit_price="4.0000",
            vat_rate="0.2500",
        )
        gratis = self.client.post(
            f"/api/pos/check-items/{item.id}/gratis/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(gratis.status_code, 200, gratis.content)

        storno = self.client.post(
            f"/api/pos/check-items/{item.id}/storno/",
            data={"reason": "undo"},
            format="json",
            secure=True,
        )
        self.assertEqual(storno.status_code, 409, storno.content)

    def test_settlement_state_remaining_excludes_paid_and_storno_for_normal_item(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="10.0000",
            unit_price="2.2000",
            vat_rate="0.2500",
            round_number=1,
            sent_to_bar=True,
        )

        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "22.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)
        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
            data={"amount": "2.20", "items": [{"id": item.id, "quantity": "1.0000"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 200, pay.content)

        storno = self.client.post(
            f"/api/pos/check-items/{item.id}/storno/",
            data={"quantity": "1.0000"},
            format="json",
            secure=True,
        )
        self.assertEqual(storno.status_code, 201, storno.content)

        state = self.client.get(f"/api/pos/checks/{self.check.id}/settlement-state/", secure=True)
        self.assertEqual(state.status_code, 200, state.content)
        rows = [row for row in state.json().get("items", []) if row["id"] == item.id]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["remaining_quantity"], "8.0000")
        self.assertEqual(row["remaining_amount"], "17.60")

    def test_settlement_state_remaining_after_paid_storno_gratis_otpis_sequence(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="10.0000",
            unit_price="2.2000",
            vat_rate="0.2500",
            round_number=1,
            sent_to_bar=True,
        )
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "22.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)
        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
            data={"amount": "2.20", "items": [{"id": item.id, "quantity": "1.0000"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 200, pay.content)

        self.assertEqual(
            self.client.post(
                f"/api/pos/check-items/{item.id}/storno/",
                data={"quantity": "1.0000"},
                format="json",
                secure=True,
            ).status_code,
            201,
        )
        self.assertEqual(
            self.client.post(
                f"/api/pos/check-items/{item.id}/gratis/",
                data={"quantity": "1.0000"},
                format="json",
                secure=True,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/pos/check-items/{item.id}/otpis/",
                data={"quantity": "1.0000"},
                format="json",
                secure=True,
            ).status_code,
            200,
        )

        state = self.client.get(f"/api/pos/checks/{self.check.id}/settlement-state/", secure=True)
        self.assertEqual(state.status_code, 200, state.content)
        rows = [row for row in state.json().get("items", []) if row["id"] == item.id]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["remaining_quantity"], "6.0000")
        self.assertEqual(row["remaining_amount"], "13.20")

    def test_round_state_exposes_paid_line_and_strike_main_only_at_zero_remaining(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="10.0000",
            unit_price="2.2000",
            vat_rate="0.2500",
            round_number=1,
            sent_to_bar=True,
        )

        prepare_1 = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "22.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare_1.status_code, 200, prepare_1.content)
        part_1 = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)
        pay_1 = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{part_1.id}/pay-cash/",
            data={"amount": "6.60", "items": [{"id": item.id, "quantity": "3.0000"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(pay_1.status_code, 200, pay_1.content)

        round_state_1 = self.client.get(f"/api/pos/checks/{self.check.id}/round-state/", secure=True)
        self.assertEqual(round_state_1.status_code, 200, round_state_1.content)
        rows_1 = [row for row in round_state_1.json()["items"] if row["item_id"] == item.id]
        self.assertEqual(len(rows_1), 1)
        row_1 = rows_1[0]
        self.assertEqual(row_1["source_quantity"], "10.0000")
        self.assertEqual(row_1["sold_quantity"], "3.0000")
        self.assertEqual(row_1["remaining_quantity"], "7.0000")
        self.assertFalse(row_1["strike_main"])
        self.assertIsNotNone(row_1["paid_line"])
        self.assertEqual(row_1["paid_line"]["line_type"], "PAID")
        self.assertEqual(row_1["paid_line"]["quantity"], "3.0000")
        self.assertEqual(row_1["paid_line"]["ui_color"], "light_blue")

        part_2 = (
            SettlementPart.objects.filter(barion_check=self.check, status=SettlementPart.Status.PREPARED)
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(part_2)
        pay_2 = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{part_2.id}/pay-cash/",
            data={"amount": "15.40", "items": [{"id": item.id, "quantity": "7.0000"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(pay_2.status_code, 200, pay_2.content)

        round_state_2 = self.client.get(f"/api/pos/checks/{self.check.id}/round-state/", secure=True)
        self.assertEqual(round_state_2.status_code, 200, round_state_2.content)
        rows_2 = [row for row in round_state_2.json()["items"] if row["item_id"] == item.id]
        self.assertEqual(len(rows_2), 1)
        row_2 = rows_2[0]
        self.assertEqual(row_2["sold_quantity"], "10.0000")
        self.assertEqual(row_2["remaining_quantity"], "0.0000")
        self.assertTrue(row_2["strike_main"])

    def test_cannot_change_items_on_closed_check(self):
        self.client.force_authenticate(user=self.user)
        closed_check = Check.objects.create(table=Table.objects.create(label="T301"), status=Check.Status.CLOSED)
        artikl = Artikl.objects.create(
            name="Voda",
            code="VOD301",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        item = CheckItem.objects.create(
            barion_check=closed_check,
            artikl=artikl,
            quantity="1.0000",
            unit_price="2.0000",
            vat_rate="0.2500",
        )

        response = self.client.patch(
            f"/api/pos/check-items/{item.id}/",
            data={"quantity": "2.0000"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 409, response.content)

    def test_create_item_with_modifiers_requires_quantity_one(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/items/",
            data={
                "artikl_id": self.artikl_kava.id,
                "quantity": "2.0000",
                "unit_price": "2.5000",
                "vat_rate": "0.2500",
                "modifiers": [self.opt_natren.id],
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("quantity mora biti 1", response.json()["detail"])

    def test_create_item_with_modifier_persists_selection_and_display_lines(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/items/",
            data={
                "artikl_id": self.artikl_kava.id,
                "quantity": "1.0000",
                "unit_price": "2.5000",
                "vat_rate": "0.2500",
                "note": "bez pjene",
                "modifiers": [self.opt_natren.id, self.opt_cold_milk.id],
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(len(payload["modifiers"]), 2)
        self.assertTrue(any("Natren" in line for line in payload["display_lines"]))
        self.assertTrue(any("Napomena: bez pjene" in line for line in payload["display_lines"]))
        self.assertEqual(
            CheckItemModifierSelection.objects.filter(check_item_id=payload["id"]).count(),
            2,
        )

    def test_patch_item_modifiers_revalidates_quantity(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="2.0000",
            unit_price="3.0000",
            vat_rate="0.2500",
        )
        response = self.client.patch(
            f"/api/pos/check-items/{item.id}/",
            data={"modifiers": [self.opt_natren.id]},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("quantity mora biti 1", response.json()["detail"])

    def test_patch_item_can_update_modifiers_when_quantity_is_one(self):
        self.client.force_authenticate(user=self.user)
        item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_kava,
            quantity="1.0000",
            unit_price="3.0000",
            vat_rate="0.2500",
        )
        response = self.client.patch(
            f"/api/pos/check-items/{item.id}/",
            data={"modifiers": [self.opt_natren.id]},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(len(payload["modifiers"]), 1)
        self.assertEqual(payload["modifiers"][0]["option_id"], self.opt_natren.id)
        self.assertEqual(
            CheckItemModifierSelection.objects.filter(check_item=item, option=self.opt_natren).count(),
            1,
        )

    def test_create_bundle_item_applies_price_delta(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/items/",
            data={
                "artikl_id": self.artikl_boca.id,
                "quantity": "1.0000",
                "unit_price": "999.0000",
                "vat_rate": "0.2500",
                "modifiers": [
                    {"type": "bundle", "id": self.bundle_opt_rb.id, "quantity": 2},
                    {"type": "bundle", "id": self.bundle_opt_juice.id, "quantity": 2},
                ],
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(float(payload["unit_price"]), 165.0)
        self.assertTrue(any(row["option_type"] == "bundle" for row in payload["modifiers"]))

    def test_create_item_without_modifiers_applies_assignment_defaults(self):
        assignment = ItemModifierGroupAssignment.objects.get(artikl=self.artikl_boca, group=self.bundle_group)
        ItemModifierDefaultSelection.objects.create(
            assignment=assignment,
            bundle_option=self.bundle_opt_rb,
            quantity=2,
        )
        ItemModifierDefaultSelection.objects.create(
            assignment=assignment,
            bundle_option=self.bundle_opt_juice,
            quantity=2,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/items/",
            data={
                "artikl_id": self.artikl_boca.id,
                "quantity": "1.0000",
                "unit_price": "1.0000",
                "vat_rate": "0.2500",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(float(payload["unit_price"]), 165.0)
        self.assertEqual(payload.get("modifiers_auto_applied"), True)
        by_id = {row["option_id"]: row for row in payload["modifiers"]}
        self.assertEqual(by_id[self.bundle_opt_rb.id]["quantity"], 2)
        self.assertEqual(by_id[self.bundle_opt_juice.id]["quantity"], 2)

    def test_create_item_with_explicit_modifiers_overrides_defaults(self):
        assignment = ItemModifierGroupAssignment.objects.get(artikl=self.artikl_kava, group=self.coffee_group)
        ItemModifierDefaultSelection.objects.create(
            assignment=assignment,
            option=self.opt_natren,
            quantity=1,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/items/",
            data={
                "artikl_id": self.artikl_kava.id,
                "quantity": "1.0000",
                "unit_price": "2.5000",
                "vat_rate": "0.2500",
                "modifiers": [self.opt_cold_milk.id],
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload.get("modifiers_auto_applied"), False)
        self.assertEqual(len(payload["modifiers"]), 1)
        self.assertEqual(payload["modifiers"][0]["option_id"], self.opt_cold_milk.id)

    def test_product_modifiers_endpoint_includes_default_flags(self):
        assignment = ItemModifierGroupAssignment.objects.get(artikl=self.artikl_boca, group=self.bundle_group)
        ItemModifierDefaultSelection.objects.create(
            assignment=assignment,
            bundle_option=self.bundle_opt_rb,
            quantity=2,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f"/api/pos/products/{self.artikl_boca.id}/modifiers/",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(len(payload["modifier_groups"]), 1)
        options = payload["modifier_groups"][0]["options"]
        rb = next(row for row in options if row["id"] == self.bundle_opt_rb.id)
        juice = next(row for row in options if row["id"] == self.bundle_opt_juice.id)
        self.assertEqual(rb["is_default"], True)
        self.assertEqual(rb["default_quantity"], 2)
        self.assertEqual(juice["is_default"], False)
        self.assertIsNone(juice["default_quantity"])

    def test_product_bundle_price_endpoint_returns_server_calculation(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            f"/api/pos/products/{self.artikl_boca.id}/bundle-price/",
            data={
                "modifiers": [
                    {"type": "bundle", "id": self.bundle_opt_rb.id, "quantity": 2},
                    {"type": "bundle", "id": self.bundle_opt_juice.id, "quantity": 2},
                ]
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(float(payload["base_unit_price"]), 150.0)
        self.assertEqual(float(payload["mixers_delta"]), 15.0)
        self.assertEqual(float(payload["final_unit_price"]), 165.0)
        self.assertEqual(len(payload["mixers"]), 2)


class PosProductSearchApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-product-search-user",
            email="barion-product-search@example.com",
            password="pass1234",
        )
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.cat_hot = DrinkCategory.objects.create(name="Topli napitci")
        self.cat_soft = DrinkCategory.objects.create(name="Sokovi")
        self.price_list = SalesPriceList.objects.create(
            name="POS test cjenik",
            is_active=True,
            is_default=True,
            valid_from=timezone.now(),
        )

        self.espresso = Artikl.objects.create(
            name="Espresso",
            code="KAVA01",
            is_sellable=True,
            is_stock_item=False,
            drink_category=self.cat_hot,
            tax_group=self.tax_group,
        )
        self.cola = Artikl.objects.create(
            name="Coca Cola",
            code="SOK01",
            is_sellable=True,
            is_stock_item=False,
            drink_category=self.cat_soft,
            tax_group=self.tax_group,
        )
        self.water = Artikl.objects.create(
            name="Voda negazirana",
            code="VODA01",
            is_sellable=True,
            is_stock_item=True,
            drink_category=self.cat_soft,
            tax_group=self.tax_group,
        )
        Artikl.objects.create(
            name="Interni artikl",
            code="INT01",
            is_sellable=False,
            is_stock_item=False,
            drink_category=self.cat_hot,
            tax_group=self.tax_group,
        )
        SalesPriceItem.objects.create(price_list=self.price_list, artikl=self.espresso, unit_price_gross="2.50", is_active=True)
        SalesPriceItem.objects.create(price_list=self.price_list, artikl=self.cola, unit_price_gross="3.00", is_active=True)
        SalesPriceItem.objects.create(price_list=self.price_list, artikl=self.water, unit_price_gross="2.00", is_active=True)
        runtime = BarionRuntimeMode.get_solo()
        runtime.active_mode = BarionRuntimeMode.Mode.DAY
        runtime.save()

    def test_requires_authentication(self):
        response = self.client.get("/api/pos/products/search/?q=co", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_returns_only_sellable_items(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/products/search/?q=INT01", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), [])

    def test_search_by_query_ranks_code_exact_first(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/products/search/?q=SOK01", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]["id"], self.cola.id)
        self.assertEqual(data[0]["code"], "SOK01")
        self.assertIn("image_46x75", data[0])

    def test_filters_by_drink_category(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f"/api/pos/products/search/?drink_category_id={self.cat_hot.id}",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        returned_ids = {item["id"] for item in response.json()}
        self.assertIn(self.espresso.id, returned_ids)
        self.assertNotIn(self.cola.id, returned_ids)
        self.assertNotIn(self.water.id, returned_ids)

    def test_filters_by_parent_category_includes_descendants(self):
        parent_lvl2 = DrinkCategory.objects.create(name="Zestoka")
        child_lvl3 = DrinkCategory.objects.create(name="Vodke", parent=parent_lvl2)
        nested_artikl = Artikl.objects.create(
            name="Belvedere vodka 0,03l",
            code="BELV03",
            is_sellable=True,
            is_stock_item=False,
            drink_category=child_lvl3,
            tax_group=self.tax_group,
        )
        SalesPriceItem.objects.create(
            price_list=self.price_list,
            artikl=nested_artikl,
            unit_price_gross="9.50",
            is_active=True,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f"/api/pos/products/search/?drink_category_id={parent_lvl2.id}",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        returned_ids = {item["id"] for item in response.json()}
        self.assertIn(nested_artikl.id, returned_ids)

    def test_limit_is_applied(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/products/search/?limit=1", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()), 1)

    def test_default_sort_uses_popularity_desc(self):
        ProductPopularitySnapshot.objects.create(artikl=self.espresso, sold_qty_30d="50.0000")
        ProductPopularitySnapshot.objects.create(artikl=self.cola, sold_qty_30d="500.0000")
        ProductPopularitySnapshot.objects.create(artikl=self.water, sold_qty_30d="150.0000")

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/products/search/", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual([row["id"] for row in payload[:3]], [self.cola.id, self.water.id, self.espresso.id])
        self.assertEqual(float(payload[0]["popularity_score"]), 500.0)

    def test_invalid_sort_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/products/search/?sort=bad", secure=True)
        self.assertEqual(response.status_code, 400, response.content)

    def test_invalid_mode_query_is_ignored(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/products/search/?mode=bad", secure=True)
        self.assertEqual(response.status_code, 200, response.content)

    def test_night_mode_uses_backend_active_mode(self):
        ProductPopularitySnapshot.objects.create(
            artikl=self.espresso,
            sold_qty_30d="500.0000",
            sold_qty_night_weekend="50.0000",
        )
        ProductPopularitySnapshot.objects.create(
            artikl=self.cola,
            sold_qty_30d="10.0000",
            sold_qty_night_weekend="500.0000",
        )
        ProductPopularitySnapshot.objects.create(
            artikl=self.water,
            sold_qty_30d="1000.0000",
            sold_qty_night_weekend="5.0000",
        )

        self.client.force_authenticate(user=self.user)
        runtime = BarionRuntimeMode.get_solo()
        runtime.active_mode = BarionRuntimeMode.Mode.NIGHT
        runtime.save()
        response = self.client.get("/api/pos/products/search/?mode=day&sort=popular", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual([row["id"] for row in payload[:3]], [self.cola.id, self.espresso.id, self.water.id])
        self.assertEqual(float(payload[0]["popularity_score"]), 500.0)

    def test_backend_day_mode_ignores_query_night(self):
        ProductPopularitySnapshot.objects.create(
            artikl=self.espresso,
            sold_qty_30d="10.0000",
            sold_qty_night_weekend="500.0000",
        )
        ProductPopularitySnapshot.objects.create(
            artikl=self.cola,
            sold_qty_30d="300.0000",
            sold_qty_night_weekend="5.0000",
        )
        runtime = BarionRuntimeMode.get_solo()
        runtime.active_mode = BarionRuntimeMode.Mode.DAY
        runtime.save()

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/products/search/?mode=night&sort=popular", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        # Backend day mode should always win.
        self.assertEqual(payload[0]["id"], self.cola.id)

    def test_excludes_products_without_active_sales_price(self):
        no_price = Artikl.objects.create(
            name="Bez cijene",
            code="NOPRICE01",
            is_sellable=True,
            is_stock_item=False,
            drink_category=self.cat_hot,
            tax_group=self.tax_group,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/pos/products/search/?q={no_price.code}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), [])

    def test_uses_price_from_newer_valid_from_when_multiple_lists_are_valid(self):
        self.price_list.valid_from = timezone.now() + timezone.timedelta(days=-2)
        self.price_list.save(update_fields=["valid_from"])
        newer_list = SalesPriceList.objects.create(
            name="Noviji cjenik",
            is_active=True,
            is_default=False,
            valid_from=timezone.now() + timezone.timedelta(minutes=-1),
        )
        SalesPriceItem.objects.create(
            price_list=newer_list,
            artikl=self.espresso,
            unit_price_gross="3.30",
            is_active=True,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/pos/products/search/?q={self.espresso.code}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload[0]["id"], self.espresso.id)
        self.assertEqual(float(payload[0]["unit_price"]), 3.30)

    def test_ignores_expired_valid_to_and_falls_back_to_open_ended_list(self):
        expired_list = SalesPriceList.objects.create(
            name="Istekao cjenik",
            is_active=True,
            is_default=False,
            valid_from=timezone.now() + timezone.timedelta(days=-5),
            valid_to=timezone.now() + timezone.timedelta(days=-1),
        )
        SalesPriceItem.objects.create(
            price_list=expired_list,
            artikl=self.cola,
            unit_price_gross="9.99",
            is_active=True,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/pos/products/search/?q={self.cola.code}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload[0]["id"], self.cola.id)
        self.assertEqual(float(payload[0]["unit_price"]), 3.00)

    def test_product_modifiers_endpoint_returns_configured_groups(self):
        group = ItemModifierGroup.objects.create(
            name="Coffee edits",
            code="coffee-edits-search",
            selection_mode=ItemModifierGroup.SelectionMode.MULTIPLE,
            min_select=0,
            max_select=3,
            allow_note=True,
            sort_order=5,
        )
        option = ItemModifierOption.objects.create(
            group=group,
            name="Natren",
            code="natren-search",
            sort_order=10,
        )
        ItemModifierGroupAssignment.objects.create(
            artikl=self.espresso,
            group=group,
            is_active=True,
            is_required=False,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f"/api/pos/products/{self.espresso.id}/modifiers/",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["artikl_id"], self.espresso.id)
        self.assertEqual(len(payload["modifier_groups"]), 1)
        self.assertEqual(payload["modifier_groups"][0]["name"], "Coffee edits")
        self.assertEqual(payload["modifier_groups"][0]["options"][0]["id"], option.id)


class PosRuntimeModeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-runtime-user",
            email="barion-runtime@example.com",
            password="pass1234",
        )
        self.staff = User.objects.create_user(
            username="barion-runtime-staff",
            email="barion-runtime-staff@example.com",
            password="pass1234",
            is_staff=True,
        )
        runtime = BarionRuntimeMode.get_solo()
        runtime.active_mode = BarionRuntimeMode.Mode.DAY
        runtime.updated_by = None
        runtime.save()

    def test_runtime_mode_get_requires_authentication(self):
        response = self.client.get("/api/pos/runtime-mode/", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_runtime_mode_get_returns_singleton(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/pos/runtime-mode/", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["active_mode"], "day")

    def test_runtime_mode_patch_requires_staff(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/pos/runtime-mode/",
            data={"active_mode": "night"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_runtime_mode_patch_updates_mode_for_staff(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.patch(
            "/api/pos/runtime-mode/",
            data={"active_mode": "night"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["active_mode"], "night")
        self.assertEqual(payload["updated_by_id"], self.staff.id)


class PosCheckSendToBarApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-send-user",
            email="barion-send@example.com",
            password="pass1234",
        )
        self.client.force_authenticate(user=self.user)
        self.table = Table.objects.create(label="TSEND", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        self.check = Check.objects.create(table=self.table, status=Check.Status.OPEN, opened_by=self.user)
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.artikl_1 = Artikl.objects.create(
            name="Gin tonic",
            code="GINSEND",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        self.artikl_2 = Artikl.objects.create(
            name="Vodka juice",
            code="VODSEND",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )

        self.item_1 = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_1,
            quantity="1.0000",
            unit_price="8.0000",
            vat_rate="0.2500",
        )
        self.item_2 = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_2,
            quantity="2.0000",
            unit_price="7.0000",
            vat_rate="0.2500",
        )

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(f"/api/pos/checks/{self.check.id}/send-to-bar/", data={}, format="json", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_sends_unsent_items_as_first_round(self):
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/send-to-bar/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["check_id"], self.check.id)
        self.assertEqual(payload["round_number"], 1)
        self.assertEqual(payload["sent_items_count"], 2)
        self.assertEqual(payload["ticket"]["round_number"], 1)
        self.assertEqual(len(payload["ticket"]["items"]), 2)

        self.item_1.refresh_from_db()
        self.item_2.refresh_from_db()
        self.assertEqual(self.item_1.round_number, 1)
        self.assertEqual(self.item_2.round_number, 1)
        self.assertTrue(self.item_1.sent_to_bar)
        self.assertTrue(self.item_2.sent_to_bar)
        self.assertIsNotNone(self.item_1.sent_at)
        self.assertIsNotNone(self.item_2.sent_at)

    def test_only_new_items_are_sent_in_next_round(self):
        first = self.client.post(
            f"/api/pos/checks/{self.check.id}/send-to-bar/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(first.status_code, 200, first.content)

        new_item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=Artikl.objects.create(
                name="Rum cola",
                code="RUMSEND",
                is_sellable=True,
                is_stock_item=False,
                tax_group=self.tax_group,
            ),
            quantity="1.0000",
            unit_price="8.5000",
            vat_rate="0.2500",
        )

        second = self.client.post(
            f"/api/pos/checks/{self.check.id}/send-to-bar/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(second.status_code, 200, second.content)
        payload = second.json()
        self.assertEqual(payload["round_number"], 2)
        self.assertEqual(payload["sent_items_count"], 1)
        self.assertEqual(payload["ticket"]["items"][0]["id"], new_item.id)

        new_item.refresh_from_db()
        self.assertEqual(new_item.round_number, 2)
        self.assertTrue(new_item.sent_to_bar)

    def test_returns_business_error_when_no_new_items(self):
        first = self.client.post(
            f"/api/pos/checks/{self.check.id}/send-to-bar/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(first.status_code, 200, first.content)

        second = self.client.post(
            f"/api/pos/checks/{self.check.id}/send-to-bar/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(second.status_code, 409, second.content)
        self.assertEqual(second.json()["detail"], "Nema novih stavki za slanje na šank.")

    def test_keeps_item_flags_and_returns_warning_on_printer_error(self):
        with patch.dict(os.environ, {"BARION_BAR_PRINTER_FAIL": "1"}, clear=False):
            response = self.client.post(
                f"/api/pos/checks/{self.check.id}/send-to-bar/",
                data={},
                format="json",
                secure=True,
            )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertFalse(payload["printed"])
        self.assertIn("Greška pri slanju", payload["print_error"])
        self.assertEqual(payload["sent_items_count"], 2)

        self.item_1.refresh_from_db()
        self.item_2.refresh_from_db()
        self.assertTrue(self.item_1.sent_to_bar)
        self.assertTrue(self.item_2.sent_to_bar)
        self.assertEqual(self.item_1.round_number, 1)
        self.assertEqual(self.item_2.round_number, 1)
        self.assertIsNotNone(self.item_1.sent_at)
        self.assertIsNotNone(self.item_2.sent_at)

    def test_ignores_non_normal_lines_for_send_to_bar(self):
        CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_1,
            quantity="1.0000",
            unit_price="0.0000",
            vat_rate="0.2500",
            line_type=CheckItem.LineType.GRATIS,
            sent_to_bar=False,
        )
        CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_2,
            quantity="-1.0000",
            unit_price="7.0000",
            vat_rate="0.2500",
            line_type=CheckItem.LineType.STORNO,
            sent_to_bar=False,
        )
        CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl_1,
            quantity="1.0000",
            unit_price="0.0000",
            vat_rate="0.2500",
            line_type=CheckItem.LineType.OTPIS,
            sent_to_bar=False,
        )

        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/send-to-bar/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["sent_items_count"], 2)
        sent_ids = {row["id"] for row in payload["ticket"]["items"]}
        self.assertEqual(sent_ids, {self.item_1.id, self.item_2.id})


class PosDrinkCategoriesDisplayApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-cats-user",
            email="barion-cats@example.com",
            password="pass1234",
        )
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.price_list = SalesPriceList.objects.create(
            name="Display cjenik",
            is_active=True,
            is_default=True,
            valid_from=timezone.now(),
        )
        runtime = BarionRuntimeMode.get_solo()
        runtime.active_mode = BarionRuntimeMode.Mode.DAY
        runtime.save()

    def _priced_artikl(self, *, category: DrinkCategory, code: str):
        artikl = Artikl.objects.create(
            name=f"Artikl {code}",
            code=code,
            is_sellable=True,
            is_stock_item=False,
            drink_category=category,
            tax_group=self.tax_group,
        )
        SalesPriceItem.objects.create(
            price_list=self.price_list,
            artikl=artikl,
            unit_price_gross="4.00",
            is_active=True,
        )
        return artikl

    def test_requires_authentication(self):
        response = self.client.get("/api/pos/drink-categories/display/?root_id=1", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_prefers_deepest_level_with_priced_products(self):
        root = DrinkCategory.objects.create(name="Alkoholna")
        lvl2 = DrinkCategory.objects.create(name="Zestoka", parent=root)
        lvl3_likeri = DrinkCategory.objects.create(name="Likeri", parent=lvl2, sort_order=10)
        lvl3_rakije = DrinkCategory.objects.create(name="Rakije", parent=lvl2, sort_order=20)
        DrinkCategory.objects.create(name="Skrivena", parent=lvl2, is_active=False)

        self._priced_artikl(category=lvl3_likeri, code="LIK01")
        self._priced_artikl(category=lvl3_rakije, code="RAK01")

        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/pos/drink-categories/display/?root_id={root.id}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["display_level"], 3)
        names = [row["name"] for row in payload["categories"]]
        self.assertEqual(names, ["Likeri", "Rakije"])

    def test_falls_back_to_level_two_when_no_level_three(self):
        root = DrinkCategory.objects.create(name="Napitci")
        lvl2_hot = DrinkCategory.objects.create(name="Topli", parent=root, sort_order=10)
        lvl2_soft = DrinkCategory.objects.create(name="Sokovi", parent=root, sort_order=20)

        self._priced_artikl(category=lvl2_hot, code="TOP01")
        self._priced_artikl(category=lvl2_soft, code="SOK01")

        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/pos/drink-categories/display/?root_id={root.id}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["display_level"], 2)
        names = [row["name"] for row in payload["categories"]]
        self.assertEqual(names, ["Topli", "Sokovi"])

    def test_sorts_display_categories_by_day_popularity_desc(self):
        root = DrinkCategory.objects.create(name="Napitci")
        lvl2_hot = DrinkCategory.objects.create(name="Topli", parent=root, sort_order=10)
        lvl2_soft = DrinkCategory.objects.create(name="Sokovi", parent=root, sort_order=20)

        hot_artikl = self._priced_artikl(category=lvl2_hot, code="TOP01")
        soft_artikl = self._priced_artikl(category=lvl2_soft, code="SOK01")
        ProductPopularitySnapshot.objects.create(artikl=hot_artikl, sold_qty_30d="10.0000")
        ProductPopularitySnapshot.objects.create(artikl=soft_artikl, sold_qty_30d="200.0000")

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f"/api/pos/drink-categories/display/?root_id={root.id}&mode=day",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["display_level"], 2)
        rows = payload["categories"]
        self.assertEqual([row["id"] for row in rows], [lvl2_soft.id, lvl2_hot.id])
        self.assertEqual(float(rows[0]["popularity_score"]), 200.0)

    def test_sorts_display_categories_by_night_popularity_desc_when_backend_mode_is_night(self):
        root = DrinkCategory.objects.create(name="Napitci")
        lvl2_hot = DrinkCategory.objects.create(name="Topli", parent=root, sort_order=10)
        lvl2_soft = DrinkCategory.objects.create(name="Sokovi", parent=root, sort_order=20)

        hot_artikl = self._priced_artikl(category=lvl2_hot, code="TOP01")
        soft_artikl = self._priced_artikl(category=lvl2_soft, code="SOK01")
        ProductPopularitySnapshot.objects.create(
            artikl=hot_artikl,
            sold_qty_30d="500.0000",
            sold_qty_night_weekend="5.0000",
        )
        ProductPopularitySnapshot.objects.create(
            artikl=soft_artikl,
            sold_qty_30d="10.0000",
            sold_qty_night_weekend="300.0000",
        )

        self.client.force_authenticate(user=self.user)
        runtime = BarionRuntimeMode.get_solo()
        runtime.active_mode = BarionRuntimeMode.Mode.NIGHT
        runtime.save()
        response = self.client.get(
            f"/api/pos/drink-categories/display/?root_id={root.id}&mode=day",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["categories"]
        self.assertEqual([row["id"] for row in rows], [lvl2_soft.id, lvl2_hot.id])
        self.assertEqual(float(rows[0]["popularity_score"]), 300.0)

    def test_display_categories_invalid_mode_query_is_ignored(self):
        root = DrinkCategory.objects.create(name="Napitci")
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f"/api/pos/drink-categories/display/?root_id={root.id}&mode=bad",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)

class PosCheckIssueReceiptApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-issue-user",
            email="barion-issue@example.com",
            password="pass1234",
        )
        self.profile = PosProfile.objects.create(user=self.user)
        self.profile.set_pin("1234")
        self.profile.save(update_fields=["pin_hash"])
        self.client.force_authenticate(user=self.user)
        self.table = Table.objects.create(label="TR1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        self.layout = Layout.objects.create(name="Main", is_active=True)
        self.zone = Zone.objects.create(layout=self.layout, name="Main", order=1)
        self.layout_table = LayoutTable.objects.create(
            layout=self.layout,
            table=self.table,
            zone=self.zone,
            x=0,
            y=0,
            w=90,
            h=90,
            rotation=0,
            z_index=1,
            is_enabled=True,
        )
        self.check = Check.objects.create(table=self.table, status=Check.Status.OPEN, opened_by=self.user)
        TableState.objects.create(
            layout_table=self.layout_table,
            state=TableState.State.OPEN,
            open_check_id=self.check.id,
            updated_by=self.user,
        )
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.artikl = Artikl.objects.create(
            name="Coca Cola",
            code="CC01",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl,
            quantity="2.0000",
            unit_price="3.0000",
            vat_rate="0.2500",
        )

    def _verify_pin(self):
        response = self.client.post(
            "/api/pos/pin/verify/",
            data={"pin": "1234"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_requires_recent_pin_verify(self):
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 428, response.content)
        self.assertEqual(response.json()["pin_verify_required"], True)

    def test_issues_pos_receipt_and_closes_check(self):
        self._verify_pin()
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["check_id"], self.check.id)
        self.assertEqual(payload["status"], PosReceipt.Status.ISSUED)

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, Check.Status.CLOSED)
        paid_part = SettlementPart.objects.filter(barion_check=self.check, status=SettlementPart.Status.PAID).first()
        self.assertIsNotNone(paid_part)
        self.assertIsNotNone(paid_part.confirmed_receipt_id)

        receipt = PosReceipt.objects.get(id=paid_part.confirmed_receipt_id)
        self.assertEqual(receipt.items.count(), 1)
        self.assertEqual(receipt.items.first().artikl_id, self.artikl.id)

        state = TableState.objects.get(layout_table=self.layout_table)
        self.assertEqual(state.state, TableState.State.FREE)
        self.assertIsNone(state.open_check_id)

    def test_is_idempotent_when_receipt_already_issued(self):
        self._verify_pin()
        first = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False},
            format="json",
            secure=True,
        )
        self.assertEqual(first.status_code, 200, first.content)
        first_receipt_id = first.json()["receipt_id"]

        second = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False},
            format="json",
            secure=True,
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["receipt_id"], first_receipt_id)
        self.assertEqual(PosReceipt.objects.count(), 1)

    def test_issue_receipt_supports_negative_storno_lines(self):
        source_item = self.check.items.first()
        storno_response = self.client.post(
            f"/api/pos/check-items/{source_item.id}/storno/",
            data={"reason": "krivi unos"},
            format="json",
            secure=True,
        )
        self.assertEqual(storno_response.status_code, 201, storno_response.content)

        self._verify_pin()
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)

        receipt = PosReceipt.objects.get(id=response.json()["receipt_id"])
        receipt_quantities = sorted([str(row.quantity) for row in receipt.items.order_by("id")])
        self.assertEqual(receipt_quantities, ["-2.0000", "2.0000"])


class PosCheckIssueReceiptStockEffectsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-issue-stock-user",
            email="barion-issue-stock@example.com",
            password="pass1234",
        )
        self.profile = PosProfile.objects.create(user=self.user)
        self.profile.set_pin("1234")
        self.profile.save(update_fields=["pin_hash"])
        self.client.force_authenticate(user=self.user)

        self.tax_group = TaxGroup.objects.create(name="PDV 25 stock", code="PDV25ST", rate="0.2500")
        self.warehouse = WarehouseId.objects.create(rm_id=901, name="Sank")
        self.table = Table.objects.create(label="TR-STOCK", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        self.layout = Layout.objects.create(name="Main stock", is_active=True)
        self.zone = Zone.objects.create(layout=self.layout, name="Main", order=1)
        self.layout_table = LayoutTable.objects.create(
            layout=self.layout,
            table=self.table,
            zone=self.zone,
            x=0,
            y=0,
            w=90,
            h=90,
            rotation=0,
            z_index=1,
            is_enabled=True,
        )
        self.check = Check.objects.create(table=self.table, status=Check.Status.OPEN, opened_by=self.user)
        TableState.objects.create(
            layout_table=self.layout_table,
            state=TableState.State.OPEN,
            open_check_id=self.check.id,
            updated_by=self.user,
        )

        self.product = Artikl.objects.create(
            rm_id=3001,
            name="Bulk drink",
            code="BLKDRINK",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        self.base_ingredient = Artikl.objects.create(
            rm_id=3002,
            name="Bulk powder stock",
            code="BLKPOW",
            is_sellable=False,
            is_stock_item=True,
            tax_group=self.tax_group,
        )
        self.milk_ingredient = Artikl.objects.create(
            rm_id=3003,
            name="Milk stock",
            code="MILKST",
            is_sellable=False,
            is_stock_item=True,
            tax_group=self.tax_group,
        )

        normativ = Normativ.objects.create(product=self.product, is_active=True)
        NormativItem.objects.create(normativ=normativ, ingredient=self.base_ingredient, qty="0.0500")

        self.bundle_group = ItemModifierGroup.objects.create(
            name="Bulk addon stock",
            code="bulk-addon-stock",
            type=ItemModifierGroup.Type.BUNDLE,
            selection_mode=ItemModifierGroup.SelectionMode.MULTIPLE,
            min_select=0,
            max_select=5,
            allow_note=False,
        )
        assignment = ItemModifierGroupAssignment.objects.create(
            artikl=self.product,
            group=self.bundle_group,
            is_active=True,
            is_required=False,
        )
        self.milk_bundle = ItemBundleOption.objects.create(
            group=self.bundle_group,
            artikl=self.milk_ingredient,
            price_delta="1.0000",
            affects_stock=True,
            stock_ratio="0.4000",
            is_active=True,
        )
        ItemModifierDefaultSelection.objects.create(
            assignment=assignment,
            bundle_option=self.milk_bundle,
            quantity=1,
        )

        self.item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.product,
            quantity="1.0000",
            unit_price="10.0000",
            vat_rate="0.2500",
        )
        CheckItemModifierSelection.objects.create(
            check_item=self.item,
            group=self.bundle_group,
            bundle_option=self.milk_bundle,
            quantity=2,
        )

        StockLot.objects.create(
            warehouse=self.warehouse,
            artikl=self.base_ingredient,
            received_at=timezone.now(),
            unit_cost="1.0000",
            qty_in="5.0000",
            qty_remaining="5.0000",
        )
        StockLot.objects.create(
            warehouse=self.warehouse,
            artikl=self.milk_ingredient,
            received_at=timezone.now(),
            unit_cost="1.0000",
            qty_in="5.0000",
            qty_remaining="5.0000",
        )

    def _verify_pin(self):
        response = self.client.post(
            "/api/pos/pin/verify/",
            data={"pin": "1234"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_issue_receipt_posts_stock_from_normativ_and_modifier_effect(self):
        self._verify_pin()
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False, "payment_type": "cash", "warehouse_id": self.warehouse.rm_id},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        receipt_id = response.json()["receipt_id"]
        stock_ref = f"Barion check {self.check.id} receipt {receipt_id}"
        move = StockMove.objects.get(
            move_type=StockMove.MoveType.OUT,
            purpose=StockMove.Purpose.SALE,
            reference=stock_ref,
        )
        by_artikl = {line.artikl_id: line for line in move.lines.all()}
        self.assertEqual(str(by_artikl[self.base_ingredient.rm_id].quantity), "0.0500")
        self.assertEqual(str(by_artikl[self.milk_ingredient.rm_id].quantity), "0.8000")

    def test_issue_receipt_stock_posting_is_idempotent(self):
        self._verify_pin()
        first = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False, "payment_type": "cash", "warehouse_id": self.warehouse.rm_id},
            format="json",
            secure=True,
        )
        self.assertEqual(first.status_code, 200, first.content)
        first_receipt = first.json()["receipt_id"]
        self.assertEqual(
            StockMove.objects.filter(reference=f"Barion check {self.check.id} receipt {first_receipt}").count(),
            1,
        )

        second = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False, "payment_type": "cash", "warehouse_id": self.warehouse.rm_id},
            format="json",
            secure=True,
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["receipt_id"], first_receipt)
        self.assertEqual(
            StockMove.objects.filter(reference=f"Barion check {self.check.id} receipt {first_receipt}").count(),
            1,
        )


class PosSplitSettlementApiContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="barion-split-user",
            email="barion-split@example.com",
            password="pass1234",
        )
        self.client.force_authenticate(user=self.user)
        self.profile = PosProfile.objects.create(user=self.user)
        self.profile.set_pin("1234")
        self.profile.save(update_fields=["pin_hash"])

        self.table = Table.objects.create(label="SPLIT-1", capacity=4, shape=Table.Shape.SQUARE, is_vip=False)
        self.layout = Layout.objects.create(name="Split layout", is_active=True)
        self.zone = Zone.objects.create(layout=self.layout, name="Main", order=1)
        self.layout_table = LayoutTable.objects.create(
            layout=self.layout,
            table=self.table,
            zone=self.zone,
            x=0,
            y=0,
            w=90,
            h=90,
            rotation=0,
            z_index=1,
            is_enabled=True,
        )
        self.check = Check.objects.create(table=self.table, status=Check.Status.OPEN, opened_by=self.user)
        TableState.objects.create(
            layout_table=self.layout_table,
            state=TableState.State.OPEN,
            open_check_id=self.check.id,
            updated_by=self.user,
        )
        self.tax_group = TaxGroup.objects.create(name="PDV 25 split", code="PDV25S", rate="0.2500")
        self.artikl = Artikl.objects.create(
            name="Split test item",
            code="SPLIT-ITEM-1",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl,
            quantity="1.0000",
            unit_price="50.0000",
            vat_rate="0.2500",
        )

    def _verify_pin(self):
        response = self.client.post(
            "/api/pos/pin/verify/",
            data={"pin": "1234"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)

    def _assert_absolute_url_or_null(self, value):
        if value is None:
            return
        self.assertIsInstance(value, str)
        self.assertTrue(value.startswith("http://") or value.startswith("https://"), value)

    def _assert_money_string(self, value):
        self.assertIsInstance(value, str)
        self.assertRegex(value, r"^-?\d+\.\d{2}$")

    def test_prepare_settlement_persists_parts_and_returns_contract_shape(self):
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={
                "parts": [
                    {"method": "CASH", "amount": "30.00"},
                    {"method": "CARD", "amount": "20.00", "tip_amount": "2.00"},
                ]
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["check_id"], self.check.id)
        self.assertEqual(payload["settlement_status"], Check.SettlementStatus.PREPARED)
        self.assertEqual(payload["payment_status"], Check.PaymentStatus.UNPAID)
        self.assertEqual(float(payload["totals"]["check_total"]), 50.00)
        self.assertEqual(float(payload["totals"]["allocated_total"]), 50.00)
        self.assertEqual(float(payload["totals"]["confirmed_total"]), 0.00)
        self.assertEqual(float(payload["totals"]["remaining_total"]), 50.00)
        self.assertEqual(payload["actions"]["can_confirm_card"], True)
        self.assertEqual(payload["actions"]["can_issue_receipt"], False)
        self.assertEqual(payload["actions"]["can_close_check"], False)
        self.assertEqual(len(payload["parts"]), 2)

        cash = next(row for row in payload["parts"] if row["method"] == "CASH")
        card = next(row for row in payload["parts"] if row["method"] == "CARD")
        self.assertEqual(cash["method_display"], "Gotovina")
        self.assertEqual(card["method_display"], "Kartica")
        self.assertEqual(cash["provider"], "")
        self.assertEqual(float(cash["tip_amount"]), 0.00)
        self.assertEqual(float(cash["fiscal_amount"]), 30.00)
        self.assertEqual(float(cash["total_charged"]), 30.00)
        self.assertEqual(card["provider"], "")
        self.assertEqual(float(card["tip_amount"]), 2.00)
        self.assertEqual(float(card["fiscal_amount"]), 22.00)
        self.assertEqual(float(card["total_charged"]), 22.00)

        self.assertEqual(SettlementPart.objects.filter(barion_check=self.check).count(), 2)

    def test_prepare_settlement_rejects_invalid_sum(self):
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "49.99"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("allocated_total", response.json())

    def test_prepare_settlement_is_idempotent_for_same_payload(self):
        payload = {"parts": [{"method": "CASH", "amount": "50.00"}]}
        first = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data=payload,
            format="json",
            secure=True,
        )
        self.assertEqual(first.status_code, 200, first.content)
        ids_first = list(SettlementPart.objects.filter(barion_check=self.check).values_list("id", flat=True))

        second = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data=payload,
            format="json",
            secure=True,
        )
        self.assertEqual(second.status_code, 200, second.content)
        ids_second = list(SettlementPart.objects.filter(barion_check=self.check).values_list("id", flat=True))
        self.assertEqual(ids_first, ids_second)

    def test_prepare_settlement_rejects_cash_tip(self):
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00", "tip_amount": "1.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_prepare_settlement_allows_reprepare_after_paid_when_no_prepared_parts(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        initial_cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)

        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{initial_cash_part.id}/pay-cash/",
            data={"amount": "20.00"},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 200, pay.content)

        # Simulate item mutation sync removing stale PREPARED parts.
        SettlementPart.objects.filter(barion_check=self.check, status=SettlementPart.Status.PREPARED).delete()

        reprepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "30.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(reprepare.status_code, 200, reprepare.content)

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, Check.Status.OPEN)
        self.assertEqual(self.check.payment_status, Check.PaymentStatus.PARTIAL)
        self.assertEqual(
            SettlementPart.objects.filter(barion_check=self.check, status=SettlementPart.Status.PAID).count(),
            1,
        )
        self.assertEqual(
            SettlementPart.objects.filter(barion_check=self.check, status=SettlementPart.Status.PREPARED).count(),
            1,
        )

    def test_prepare_settlement_allows_switching_remaining_prepared_from_cash_to_card(self):
        initial_prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(initial_prepare.status_code, 200, initial_prepare.content)
        initial_cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)

        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{initial_cash_part.id}/pay-cash/",
            data={"amount": "20.00"},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 200, pay.content)

        switch_prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CARD", "amount": "30.00", "tip_amount": "3.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(switch_prepare.status_code, 200, switch_prepare.content)
        payload = switch_prepare.json()
        self.assertEqual(float(payload["totals"]["remaining_total"]), 30.00)
        card_rows = [row for row in payload["parts"] if row["status"] == SettlementPart.Status.PREPARED]
        self.assertEqual(len(card_rows), 1)
        self.assertEqual(card_rows[0]["method"], SettlementPart.Method.CARD)
        self.assertEqual(float(card_rows[0]["amount"]), 30.00)
        self.assertEqual(float(card_rows[0]["tip_amount"]), 3.00)

    def test_prepare_settlement_normalizes_single_card_amount_to_remaining(self):
        initial_prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(initial_prepare.status_code, 200, initial_prepare.content)
        initial_cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)

        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{initial_cash_part.id}/pay-cash/",
            data={"amount": "20.00"},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 200, pay.content)

        # Sent amount is stale/full check total from Android "full target".
        switch_prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CARD", "amount": "50.00", "tip_amount": "0.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(switch_prepare.status_code, 200, switch_prepare.content)
        payload = switch_prepare.json()
        card_rows = [row for row in payload["parts"] if row["status"] == SettlementPart.Status.PREPARED]
        self.assertEqual(len(card_rows), 1)
        self.assertEqual(card_rows[0]["method"], SettlementPart.Method.CARD)
        self.assertEqual(float(card_rows[0]["amount"]), 30.00)

    def test_pay_card_confirm_marks_partial_and_is_idempotent_by_external_txn(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={
                "parts": [
                    {"method": "CARD", "amount": "20.00", "tip_amount": "2.00"},
                    {"method": "CASH", "amount": "30.00"},
                ]
            },
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)

        first = self.client.post(
            f"/api/pos/checks/{self.check.id}/pay-card/confirm/",
            data={"amount": "20.00", "external_txn_id": "TXN-001"},
            format="json",
            secure=True,
        )
        self.assertEqual(first.status_code, 200, first.content)
        first_payload = first.json()
        self.assertEqual(first_payload["payment_status"], Check.PaymentStatus.PARTIAL)
        self.assertEqual(float(first_payload["remaining_total"]), 30.00)
        self.assertEqual(first_payload["check_closed"], False)
        self.assertEqual(first_payload["action"], "card_confirmed")
        self.assertIn("parts", first_payload)
        self.assertIn("totals", first_payload)
        self.assertIn("actions", first_payload)
        self.assertIn("receipt_pdf_url", first_payload)
        self.assertIn("issued_receipt_id", first_payload)
        self.assertIn("pos_receipt_ids", first_payload)
        self.assertIsInstance(first_payload["pos_receipt_ids"], list)
        self._assert_absolute_url_or_null(first_payload["receipt_pdf_url"])
        self.assertEqual(float(first_payload["totals"]["confirmed_total"]), 20.00)
        self.assertEqual(first_payload["actions"]["can_confirm_card"], False)
        self.assertEqual(first_payload["actions"]["can_issue_receipt"], False)

        second = self.client.post(
            f"/api/pos/checks/{self.check.id}/pay-card/confirm/",
            data={"amount": "20.00", "external_txn_id": "TXN-001"},
            format="json",
            secure=True,
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["action"], "idempotent")

    def test_pay_card_confirm_rejects_missing_prepare(self):
        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/pay-card/confirm/",
            data={"amount": "20.00", "external_txn_id": "TXN-002"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 409, response.content)

    def test_split_e2e_prepare_card_cash_confirm_then_final_issue(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={
                "parts": [
                    {"method": "CARD", "amount": "20.00", "tip_amount": "2.00"},
                    {"method": "CASH", "amount": "30.00"},
                ]
            },
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)

        confirm = self.client.post(
            f"/api/pos/checks/{self.check.id}/pay-card/confirm/",
            data={"amount": "20.00", "external_txn_id": "TXN-E2E-001"},
            format="json",
            secure=True,
        )
        self.assertEqual(confirm.status_code, 200, confirm.content)
        self.assertEqual(confirm.json()["payment_status"], Check.PaymentStatus.PARTIAL)
        self.assertEqual(float(confirm.json()["totals"]["remaining_total"]), 30.00)

        self._verify_pin()
        issue = self.client.post(
            f"/api/pos/checks/{self.check.id}/issue-receipt/",
            data={"fiscalize": False, "payment_type": "cash"},
            format="json",
            secure=True,
        )
        self.assertEqual(issue.status_code, 200, issue.content)
        payload = issue.json()
        self.assertEqual(payload["check_id"], self.check.id)
        self.assertEqual(payload["check_status"], Check.Status.CLOSED)
        self.assertEqual(payload["settlement_status"], Check.SettlementStatus.COMPLETE)
        self.assertEqual(payload["payment_status"], Check.PaymentStatus.PAID)
        self.assertEqual(float(payload["totals"]["remaining_total"]), 0.00)
        self.assertEqual(payload["actions"]["can_issue_receipt"], False)
        self.assertEqual(payload["actions"]["can_close_check"], False)

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, Check.Status.CLOSED)
        self.assertEqual(self.check.payment_status, Check.PaymentStatus.PAID)
        self.assertEqual(self.check.settlement_status, Check.SettlementStatus.COMPLETE)

        state = TableState.objects.get(layout_table=self.layout_table)
        self.assertEqual(state.state, TableState.State.FREE)
        self.assertIsNone(state.open_check_id)

    def test_settlement_state_returns_snapshot_for_polling(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={
                "parts": [
                    {"method": "CARD", "amount": "20.00", "tip_amount": "2.00"},
                    {"method": "CASH", "amount": "30.00"},
                ]
            },
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)

        response = self.client.get(
            f"/api/pos/checks/{self.check.id}/settlement-state/",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["check_id"], self.check.id)
        self.assertEqual(payload["check_status"], Check.Status.OPEN)
        self.assertEqual(payload["settlement_status"], Check.SettlementStatus.PREPARED)
        self.assertEqual(payload["payment_status"], Check.PaymentStatus.UNPAID)
        self.assertIsNone(payload["pos_receipt_id"])
        self.assertIn("pos_receipt_ids", payload)
        self.assertEqual(payload["pos_receipt_ids"], [])
        self.assertIsNone(payload["issued_receipt_id"])
        self.assertIsNone(payload["receipt_pdf_url"])
        self.assertEqual(len(payload["parts"]), 2)
        self.assertEqual(float(payload["totals"]["check_total"]), 50.00)
        self.assertEqual(float(payload["totals"]["allocated_total"]), 50.00)
        self.assertEqual(float(payload["totals"]["confirmed_total"]), 0.00)
        self.assertEqual(float(payload["totals"]["remaining_total"]), 50.00)
        self._assert_money_string(payload["totals"]["check_total"])
        self._assert_money_string(payload["totals"]["allocated_total"])
        self._assert_money_string(payload["totals"]["confirmed_total"])
        self._assert_money_string(payload["totals"]["remaining_total"])
        self.assertEqual(payload["actions"]["can_confirm_card"], True)
        self.assertEqual(payload["actions"]["can_issue_receipt"], False)
        self.assertEqual(payload["actions"]["can_close_check"], False)
        self.assertIn("items", payload)
        self.assertGreaterEqual(len(payload["items"]), 1)
        first_item = payload["items"][0]
        self.assertIn("round_number", first_item)
        self.assertIn("sent_to_bar", first_item)
        if first_item["round_number"] is not None:
            self.assertIsInstance(first_item["round_number"], int)
        self.assertIsInstance(first_item["sent_to_bar"], bool)
        self.assertIn("updated_at", payload)

    def test_settlement_state_returns_404_for_unknown_check(self):
        response = self.client.get("/api/pos/checks/999999/settlement-state/", secure=True)
        self.assertEqual(response.status_code, 404, response.content)

    def test_part_level_pay_cash_endpoint(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)

        with patch.dict(
            os.environ,
            {"FISCAL_MOCK": "true", "FISCAL_OIB": "12345678901", "FISCAL_SEND_ENABLED": "false"},
            clear=False,
        ):
            pay = self.client.post(
                f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
                data={"amount": "50.00"},
                format="json",
                secure=True,
            )
        self.assertEqual(pay.status_code, 200, pay.content)
        self.assertEqual(pay.json()["part_status"], SettlementPart.Status.PAID)
        self.assertEqual(pay.json()["action"], "paid")
        self.assertEqual(float(pay.json()["totals"]["remaining_total"]), 0.00)
        self.assertEqual(pay.json()["actions"]["can_close_check"], True)
        self.assertIn("receipt_pdf_url", pay.json())
        self.assertIn("issued_receipt_id", pay.json())
        self.assertIn("pos_receipt_ids", pay.json())
        self.assertIsInstance(pay.json()["pos_receipt_ids"], list)
        self._assert_absolute_url_or_null(pay.json()["receipt_pdf_url"])
        self.check.refresh_from_db()
        self.assertEqual(self.check.status, Check.Status.OPEN)

    def test_part_pay_cash_allows_partial_and_keeps_remaining(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)

        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)
        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
            data={"amount": "20.00"},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 200, pay.content)
        payload = pay.json()
        self.assertEqual(float(payload["totals"]["confirmed_total"]), 20.00)
        self.assertEqual(float(payload["totals"]["remaining_total"]), 30.00)
        self.assertIsNotNone(payload["issued_receipt_id"])
        self.assertIn("pos_receipt_ids", payload)
        self.assertGreaterEqual(len(payload["pos_receipt_ids"]), 1)
        self._assert_absolute_url_or_null(payload["receipt_pdf_url"])

        state = self.client.get(
            f"/api/pos/checks/{self.check.id}/settlement-state/",
            secure=True,
        )
        self.assertEqual(state.status_code, 200, state.content)
        item_rows = state.json().get("items") or []
        self.assertGreaterEqual(len(item_rows), 1)
        row = item_rows[0]
        self.assertEqual(float(row["paid_amount"]), 20.00)
        self.assertEqual(float(row["remaining_amount"]), 30.00)

        self.check.refresh_from_db()
        self.assertEqual(self.check.status, Check.Status.OPEN)
        self.assertEqual(self.check.payment_status, Check.PaymentStatus.PARTIAL)

    def test_part_pay_cash_supports_strict_item_selection(self):
        second_artikl = Artikl.objects.create(
            name="Strict target item",
            code="STRICT-TARGET-1",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        second_item = CheckItem.objects.create(
            barion_check=self.check,
            artikl=second_artikl,
            quantity="2.0000",
            unit_price="5.0000",
            vat_rate="0.2500",
        )

        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "60.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)

        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)
        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
            data={"items": [{"id": second_item.id, "quantity": "1.0000"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 200, pay.content)
        payload = pay.json()
        self.assertEqual(float(payload["totals"]["confirmed_total"]), 5.00)
        self.assertEqual(float(payload["totals"]["remaining_total"]), 55.00)

        self.check.refresh_from_db()
        first_item = self.check.items.get(artikl=self.artikl)
        second_item.refresh_from_db()
        self.assertEqual(float(first_item.paid_amount), 0.00)
        self.assertEqual(float(second_item.paid_amount), 5.00)
        self.assertEqual(float(second_item.paid_quantity), 1.00)

    def test_prepare_and_state_prioritize_prepared_parts_over_paid_for_same_amount(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)

        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
            data={"amount": "20.00"},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 200, pay.content)
        SettlementPart.objects.filter(
            barion_check=self.check,
            status=SettlementPart.Status.PREPARED,
        ).delete()

        reprepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "20.00"}, {"method": "CASH", "amount": "10.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(reprepare.status_code, 200, reprepare.content)
        reprepare_payload = reprepare.json()

        twenty_parts = [row for row in reprepare_payload["parts"] if row["method"] == "CASH" and row["amount"] == "20.00"]
        self.assertGreaterEqual(len(twenty_parts), 2)
        self.assertEqual(twenty_parts[0]["status"], SettlementPart.Status.PREPARED)

        state = self.client.get(f"/api/pos/checks/{self.check.id}/settlement-state/", secure=True)
        self.assertEqual(state.status_code, 200, state.content)
        state_payload = state.json()
        state_twenty_parts = [
            row for row in state_payload["parts"] if row["method"] == "CASH" and row["amount"] == "20.00"
        ]
        self.assertGreaterEqual(len(state_twenty_parts), 2)
        self.assertEqual(state_twenty_parts[0]["status"], SettlementPart.Status.PREPARED)

    def test_prepare_preserves_order_within_prepared_cash_parts(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "2.20"}, {"method": "CASH", "amount": "47.80"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        payload = prepare.json()
        cash_parts = [row for row in payload["parts"] if row["method"] == "CASH"]
        self.assertEqual(cash_parts[0]["amount"], "2.20")
        self.assertEqual(cash_parts[1]["amount"], "47.80")

        state = self.client.get(f"/api/pos/checks/{self.check.id}/settlement-state/", secure=True)
        self.assertEqual(state.status_code, 200, state.content)
        state_payload = state.json()
        state_cash_parts = [row for row in state_payload["parts"] if row["method"] == "CASH"]
        self.assertEqual(state_cash_parts[0]["amount"], "2.20")
        self.assertEqual(state_cash_parts[1]["amount"], "47.80")

    def test_part_pay_cash_rejects_non_normal_item_selection(self):
        source_item = self.check.items.get(artikl=self.artikl)
        # Keep check payable/open after otpis so we can test pay-cash rejection path.
        CheckItem.objects.create(
            barion_check=self.check,
            artikl=self.artikl,
            quantity="1.0000",
            unit_price="10.0000",
            vat_rate="0.2500",
        )
        otpis = self.client.post(
            f"/api/pos/check-items/{source_item.id}/otpis/",
            data={"quantity": "1.0000", "reason": "test"},
            format="json",
            secure=True,
        )
        self.assertEqual(otpis.status_code, 200, otpis.content)
        otpis_item_id = otpis.json()["id"]
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "10.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)

        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
            data={"amount": "0.00", "items": [{"id": otpis_item_id, "quantity": "1.0000"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 400, pay.content)
        self.assertIn("nije naplativ", pay.json()["detail"])

    def test_item_action_clears_prepared_parts_and_recalculates_state(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        self.assertEqual(
            SettlementPart.objects.filter(barion_check=self.check, status=SettlementPart.Status.PREPARED).count(),
            1,
        )

        source_item = self.check.items.get(artikl=self.artikl)
        otpis = self.client.post(
            f"/api/pos/check-items/{source_item.id}/otpis/",
            data={"quantity": "1.0000", "reason": "lom"},
            format="json",
            secure=True,
        )
        self.assertEqual(otpis.status_code, 200, otpis.content)

        self.assertEqual(
            SettlementPart.objects.filter(barion_check=self.check, status=SettlementPart.Status.PREPARED).count(),
            0,
        )
        self.check.refresh_from_db()
        self.assertEqual(self.check.status, Check.Status.CLOSED)
        self.assertEqual(self.check.settlement_status, Check.SettlementStatus.COMPLETE)
        self.assertEqual(self.check.payment_status, Check.PaymentStatus.PAID)

    def test_part_pay_cash_without_prepare_returns_not_found(self):
        pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/0/pay-cash/",
            data={"amount": "20.00"},
            format="json",
            secure=True,
        )
        self.assertEqual(pay.status_code, 404, pay.content)

    def test_prepare_legacy_endpoint_removed(self):
        first_pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(first_pay.status_code, 200, first_pay.content)

        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)
        second_pay = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
            data={"amount": "20.00"},
            format="json",
            secure=True,
        )
        self.assertEqual(second_pay.status_code, 200, second_pay.content)

        prepare_again = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/prepare/",
            data={"parts": [{"method": "CASH", "amount": "30.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare_again.status_code, 404, prepare_again.content)

    def test_receipt_pdf_url_is_absolute_when_present_for_cash_and_state(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)

        with patch.dict(
            os.environ,
            {"FISCAL_MOCK": "true", "FISCAL_OIB": "12345678901", "FISCAL_SEND_ENABLED": "false"},
            clear=False,
        ):
            pay = self.client.post(
                f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-cash/",
                data={"amount": "50.00"},
                format="json",
                secure=True,
            )
        self.assertEqual(pay.status_code, 200, pay.content)
        payload = pay.json()
        self.assertIn("issued_receipt_id", payload)
        self.assertIn("receipt_pdf_url", payload)
        if payload["receipt_pdf_url"] is not None:
            self.assertTrue(payload["receipt_pdf_url"].startswith("https://"), payload["receipt_pdf_url"])

        state = self.client.get(
            f"/api/pos/checks/{self.check.id}/settlement-state/",
            secure=True,
        )
        self.assertEqual(state.status_code, 200, state.content)
        state_payload = state.json()
        self.assertIn("issued_receipt_id", state_payload)
        self.assertIn("receipt_pdf_url", state_payload)
        self.assertIn("pos_receipt_ids", state_payload)
        self.assertIn("receipts", state_payload)
        self.assertIsInstance(state_payload["receipts"], list)
        if state_payload["issued_receipt_id"] is not None:
            self.assertIn(state_payload["issued_receipt_id"], state_payload["pos_receipt_ids"])
        for receipt in state_payload["receipts"]:
            self.assertIn("id", receipt)
            self.assertIn(receipt["id"], state_payload["pos_receipt_ids"])
            self._assert_absolute_url_or_null(receipt.get("pdf_url"))
        self._assert_absolute_url_or_null(state_payload["receipt_pdf_url"])

    def test_receipt_pdf_url_is_absolute_when_present_for_pay_card_confirm(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CARD", "amount": "50.00", "tip_amount": "0.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)

        confirm = self.client.post(
            f"/api/pos/checks/{self.check.id}/pay-card/confirm/",
            data={"amount": "50.00", "external_txn_id": "TXN-CARD-ABS-001", "issue_receipt": True},
            format="json",
            secure=True,
        )
        self.assertEqual(confirm.status_code, 200, confirm.content)
        payload = confirm.json()
        self.assertIn("receipt_pdf_url", payload)
        self.assertIn("issued_receipt_id", payload)
        self.assertIn("pos_receipt_ids", payload)
        self.assertIsInstance(payload["pos_receipt_ids"], list)
        self._assert_absolute_url_or_null(payload["receipt_pdf_url"])

    def test_part_level_card_confirm_failed_then_retry_paid(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={
                "parts": [
                    {"method": "CARD", "amount": "20.00", "tip_amount": "2.00"},
                    {"method": "CASH", "amount": "30.00"},
                ]
            },
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        card_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CARD)

        failed = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{card_part.id}/pay-card/confirm/",
            data={
                "approved": False,
                "amount": "20.00",
                "tip_amount": "2.00",
                "provider": "VIVA",
                "external_txn_id": "TXN-FAIL-01",
                "provider_ref": "VIVA-DECLINED-01",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(failed.status_code, 200, failed.content)
        self.assertEqual(failed.json()["part_status"], SettlementPart.Status.FAILED)
        self.assertEqual(failed.json()["action"], "failed")
        failed_card = next(row for row in failed.json()["parts"] if row["id"] == card_part.id)
        self.assertEqual(failed_card["provider"], SettlementPart.Provider.VIVA)

        retry = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{card_part.id}/pay-card/confirm/",
            data={
                "approved": True,
                "amount": "20.00",
                "tip_amount": "2.00",
                "provider": "VIVA",
                "external_txn_id": "TXN-OK-01",
                "provider_ref": "VIVA-APPROVED-01",
                "card_masked_pan": "**** **** **** 4242",
                "card_brand": "VISA",
                "card_type": "DEBIT",
                "card_auth_code": "AUTH123",
                "card_rrn": "RRN123456",
                "card_bank_id": "BANK-01",
                "card_aid": "A0000000031010",
                "card_application_label": "VISA DEBIT",
                "rrn": "RRN-VIVA-ALT-01",
                "reference_number": "REF-778899",
                "authorisation_code": "AUTH-778899",
                "tid": "TID-16014031",
                "order_code": "6058152276014031",
                "short_order_code": "6058152276",
                "transaction_date": "2026-02-27T16:03:53.7167+02:00",
                "payment_method": "CARD_PRESENT",
                "account_number": "539982******9303",
                "verification_method": "CONTACTLESS - ONLINE PIN",
                "aid": "A0000000041010",
                "bank_id": "NET_MASTER",
                "transaction_type_id": 5,
                "transaction_event_id": 0,
                "surcharge_amount": "0.00",
                "customer_trns": "tip-test",
                "provider_status": "success",
                "provider_action": "sale",
                "provider_message": "Transaction successful",
                "provider_payload": {"raw": "callback", "status": "success"},
            },
            format="json",
            secure=True,
        )
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json()["part_status"], SettlementPart.Status.PAID)
        self.assertEqual(retry.json()["action"], "paid")
        retry_card = next(row for row in retry.json()["parts"] if row["id"] == card_part.id)
        self.assertEqual(retry_card["provider"], SettlementPart.Provider.VIVA)
        self.assertEqual(retry_card["method_display"], "VISA: **** **** **** 4242")
        self.assertEqual(retry_card["card_masked_pan"], "**** **** **** 4242")
        self.assertEqual(retry_card["card_brand"], "VISA")
        self.assertEqual(retry_card["card_type"], "DEBIT")
        self.assertEqual(retry_card["card_auth_code"], "AUTH-778899")
        self.assertEqual(retry_card["card_rrn"], "RRN-VIVA-ALT-01")
        self.assertEqual(retry_card["card_bank_id"], "NET_MASTER")
        self.assertEqual(retry_card["card_aid"], "A0000000041010")
        self.assertEqual(retry_card["card_application_label"], "VISA DEBIT")
        self.assertEqual(retry_card["provider_reference_number"], "REF-778899")
        self.assertEqual(retry_card["provider_tid"], "TID-16014031")
        self.assertEqual(retry_card["provider_order_code"], "6058152276014031")
        self.assertEqual(retry_card["provider_short_order_code"], "6058152276")
        self.assertEqual(retry_card["provider_transaction_date"], "2026-02-27T16:03:53.7167+02:00")
        self.assertEqual(retry_card["provider_payment_method"], "CARD_PRESENT")
        self.assertEqual(retry_card["provider_account_number"], "539982******9303")
        self.assertEqual(retry_card["provider_verification_method"], "CONTACTLESS - ONLINE PIN")
        self.assertEqual(retry_card["provider_transaction_type_id"], 5)
        self.assertEqual(retry_card["provider_transaction_event_id"], 0)
        self.assertEqual(float(retry_card["provider_surcharge_amount"]), 0.00)
        self.assertEqual(retry_card["provider_customer_trns"], "tip-test")
        self.assertEqual(retry_card["provider_status"], "success")
        self.assertEqual(retry_card["provider_action"], "sale")
        self.assertEqual(retry_card["provider_message"], "Transaction successful")
        self.assertEqual(retry_card["provider_payload"], {"raw": "callback", "status": "success"})
        card_part.refresh_from_db()
        self.assertEqual(card_part.provider, SettlementPart.Provider.VIVA)
        self.assertEqual(card_part.provider_ref, "VIVA-APPROVED-01")
        self.assertEqual(card_part.card_masked_pan, "**** **** **** 4242")
        self.assertEqual(card_part.card_brand, "VISA")
        self.assertEqual(card_part.card_type, "DEBIT")
        self.assertEqual(card_part.card_auth_code, "AUTH-778899")
        self.assertEqual(card_part.card_rrn, "RRN-VIVA-ALT-01")
        self.assertEqual(card_part.card_bank_id, "NET_MASTER")
        self.assertEqual(card_part.card_aid, "A0000000041010")
        self.assertEqual(card_part.card_application_label, "VISA DEBIT")
        self.assertEqual(card_part.provider_reference_number, "REF-778899")
        self.assertEqual(card_part.provider_tid, "TID-16014031")
        self.assertEqual(card_part.provider_order_code, "6058152276014031")
        self.assertEqual(card_part.provider_short_order_code, "6058152276")
        self.assertEqual(card_part.provider_transaction_date, "2026-02-27T16:03:53.7167+02:00")
        self.assertEqual(card_part.provider_payment_method, "CARD_PRESENT")
        self.assertEqual(card_part.provider_account_number, "539982******9303")
        self.assertEqual(card_part.provider_verification_method, "CONTACTLESS - ONLINE PIN")
        self.assertEqual(card_part.provider_transaction_type_id, 5)
        self.assertEqual(card_part.provider_transaction_event_id, 0)
        self.assertEqual(float(card_part.provider_surcharge_amount), 0.00)
        self.assertEqual(card_part.provider_customer_trns, "tip-test")
        self.assertEqual(card_part.provider_status, "success")
        self.assertEqual(card_part.provider_action, "sale")
        self.assertEqual(card_part.provider_message, "Transaction successful")
        self.assertEqual(card_part.provider_payload, {"raw": "callback", "status": "success"})

    def test_part_level_card_confirm_rejects_unknown_provider(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CARD", "amount": "50.00", "tip_amount": "0.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        card_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CARD)

        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{card_part.id}/pay-card/confirm/",
            data={
                "approved": True,
                "amount": "50.00",
                "tip_amount": "0.00",
                "provider": "OTHER",
                "external_txn_id": "TXN-BAD-PROVIDER-01",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("provider", response.json())

    def test_part_level_card_confirm_returns_actual_method_for_non_card_part(self):
        prepare = self.client.post(
            f"/api/pos/checks/{self.check.id}/prepare-settlement/",
            data={"parts": [{"method": "CASH", "amount": "50.00"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(prepare.status_code, 200, prepare.content)
        cash_part = SettlementPart.objects.get(barion_check=self.check, method=SettlementPart.Method.CASH)

        response = self.client.post(
            f"/api/pos/checks/{self.check.id}/settlements/parts/{cash_part.id}/pay-card/confirm/",
            data={
                "approved": True,
                "amount": "50.00",
                "tip_amount": "0.00",
                "provider": "VIVA",
                "external_txn_id": "TXN-WRONG-METHOD-01",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 409, response.content)
        payload = response.json()
        self.assertEqual(payload.get("detail"), "Part nije CARD.")
        self.assertEqual(payload.get("check_id"), self.check.id)
        self.assertEqual(payload.get("part_id"), cash_part.id)
        self.assertEqual(payload.get("actual_method"), SettlementPart.Method.CASH)
        self.assertEqual(payload.get("expected_method"), SettlementPart.Method.CARD)
