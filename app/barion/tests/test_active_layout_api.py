import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from artikli.models import Artikl, DrinkCategory
from barion.models import (
    Check,
    CheckItem,
    Layout,
    LayoutTable,
    ProductPopularitySnapshot,
    Table,
    TableState,
    UserLayoutAccess,
    Zone,
)
from configuration.models import TaxGroup
from pos.models import PosProfile, PosReceipt
from sales.models import SalesPriceItem, SalesPriceList


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
                "note": "hladno",
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
            quantity="1.5000",
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
        self.assertEqual(float(payload["quantity"]), 1.5)
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
        self.assertEqual(float(item.quantity), 3.0)
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
            data={"quantity": "0.0001"},
            format="json",
            secure=True,
        )
        self.assertEqual(too_much.status_code, 409, too_much.content)

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
        self.assertEqual(float(item.quantity), 4.0)
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

    def test_rolls_back_item_flags_on_printer_error(self):
        with patch.dict(os.environ, {"BARION_BAR_PRINTER_FAIL": "1"}, clear=False):
            response = self.client.post(
                f"/api/pos/checks/{self.check.id}/send-to-bar/",
                data={},
                format="json",
                secure=True,
            )
        self.assertEqual(response.status_code, 503, response.content)
        self.assertIn("Greška pri slanju", response.json()["detail"])

        self.item_1.refresh_from_db()
        self.item_2.refresh_from_db()
        self.assertFalse(self.item_1.sent_to_bar)
        self.assertFalse(self.item_2.sent_to_bar)
        self.assertIsNone(self.item_1.round_number)
        self.assertIsNone(self.item_2.round_number)
        self.assertIsNone(self.item_1.sent_at)
        self.assertIsNone(self.item_2.sent_at)

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
        self.assertIsNotNone(self.check.pos_receipt_id)

        receipt = PosReceipt.objects.get(id=self.check.pos_receipt_id)
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
