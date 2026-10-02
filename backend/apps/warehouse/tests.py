from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .models import (
    Approval, Category, Goods, StockAdjustment, StockIn, StockOut,
    StocktakeInvestigation, Unit, Variety, Warning,
)


class WarehouseFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("warehouse-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(name="记录终端", category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety,
            name="执法记录终端",
            code="DEV-001",
            quantity=Decimal("12"),
            warning_threshold=Decimal("5"),
        )


class WarehouseModelTest(WarehouseFixture):
    def test_relationship_flags(self):
        self.assertTrue(self.unit.is_linked)
        self.assertTrue(self.category.is_linked)
        self.assertTrue(self.variety.is_in_stock)
        self.assertFalse(self.goods.is_warning)

    def test_unique_unit_name(self):
        with self.assertRaises(IntegrityError):
            Unit.objects.create(name="件", created_by=self.user)

    def test_stock_records_and_approval(self):
        inbound = StockIn.objects.create(goods=self.goods, operator=self.user, quantity=Decimal("3"))
        outbound = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="保管员", quantity=Decimal("2")
        )
        approval = Approval.objects.create(stock_out=outbound, approver=self.user)
        self.assertEqual(inbound.goods_id, self.goods.id)
        self.assertEqual(approval.status, "pending")

    def test_warning_record(self):
        warning = Warning.objects.create(goods=self.goods, type="low_stock", message="库存不足")
        self.assertFalse(warning.is_read)
        self.assertIn("执法记录终端", str(warning))


class WarehouseAPITest(WarehouseFixture):
    def test_list_units(self):
        response = self.client.get("/api/units/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 1)

    def test_create_unit_and_reject_duplicate(self):
        created = self.client.post("/api/units/", {"name": "箱"}, format="json")
        duplicate = self.client.post("/api/units/", {"name": "箱"}, format="json")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(duplicate.status_code, 400)

    def test_update_linked_unit(self):
        response = self.client.put(f"/api/units/{self.unit.id}/", {"name": "台"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.name, "台")

    def test_refuse_delete_linked_unit(self):
        response = self.client.delete(f"/api/units/{self.unit.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Unit.objects.filter(pk=self.unit.id).exists())

    def test_create_category_validates_unit(self):
        ok = self.client.post("/api/categories/", {"name": "封存介质", "unit": self.unit.id}, format="json")
        bad = self.client.post("/api/categories/", {"name": "无效分类", "unit": 99999}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(bad.status_code, 400)

    def test_create_variety_and_duplicate_boundary(self):
        ok = self.client.post("/api/varieties/", {"name": "封存硬盘", "category": self.category.id}, format="json")
        duplicate = self.client.post("/api/varieties/", {"name": "封存硬盘", "category": self.category.id}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(duplicate.status_code, 400)

    def test_requires_authentication(self):
        anonymous = APIClient().get("/api/units/")
        self.assertEqual(anonymous.status_code, 401)


class InvestigationFixture(WarehouseFixture):
    """盘点差异调查测试基类：额外提供批准人与常用辅助方法"""

    def setUp(self):
        super().setUp()
        self.approver = User.objects.create_user("investigation-approver", "testpass123", role="admin")
        self.viewer = User.objects.create_user("investigation-viewer", "testpass123", role="user")

    def auth_as(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(user)}")

    def create_investigation(self, counted="10.00", **extra):
        payload = {"goods_id": self.goods.id, "counted_quantity": counted}
        payload.update(extra)
        return self.client.post("/api/investigations/", payload, format="json")

    def add_note(self, investigation_id, note_type, content="记录内容"):
        return self.client.post(
            f"/api/investigations/{investigation_id}/notes/",
            {"type": note_type, "content": content},
            format="json",
        )

    def fill_required_notes(self, investigation_id):
        self.add_note(investigation_id, "reason", "原因：领用登记漏记")
        self.add_note(investigation_id, "evidence", "证据：监控录像与领用台账")
        self.add_note(investigation_id, "review", "复核：情况属实")

    def close_investigation(self, investigation_id, conclusion="确认盘亏，按差异调整"):
        return self.client.post(
            f"/api/investigations/{investigation_id}/close/",
            {"conclusion": conclusion},
            format="json",
        )

    def simulate_stock_in(self, quantity):
        """模拟调查期间的正常入库"""
        StockIn.objects.create(goods=self.goods, operator=self.user, quantity=Decimal(str(quantity)))
        self.goods.refresh_from_db()
        self.goods.quantity += Decimal(str(quantity))
        self.goods.save(update_fields=["quantity"])

    def simulate_stock_out(self, quantity):
        """模拟调查期间的正常出库（已完成）"""
        StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="领用人",
            quantity=Decimal(str(quantity)), status="completed",
            stock_out_time=timezone.now(),
        )
        self.goods.refresh_from_db()
        self.goods.quantity -= Decimal(str(quantity))
        self.goods.save(update_fields=["quantity"])


class InvestigationCreateTest(InvestigationFixture):
    def test_create_records_snapshot_and_responsibility_scope(self):
        response = self.create_investigation(
            responsible_user_id=self.approver.id,
            responsible_dept="仓储科",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["order_no"].startswith("INV"))
        self.assertEqual(data["snapshot_quantity"], "12.00")
        self.assertEqual(data["counted_quantity"], "10.00")
        self.assertEqual(data["difference"], "-2.00")
        self.assertEqual(data["status"], "investigating")
        self.assertEqual(data["responsible_user"], self.approver.id)
        self.assertEqual(data["responsible_dept"], "仓储科")
        self.assertEqual(data["created_by"], self.user.id)
        # 创建调查单不改变库存
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))

    def test_create_rejects_balanced_count(self):
        response = self.create_investigation(counted="12.00")
        self.assertEqual(response.status_code, 400)
        self.assertIn("账实相符", response.json()["message"])

    def test_create_rejects_duplicate_active_investigation(self):
        first = self.create_investigation()
        self.assertEqual(first.status_code, 200)
        duplicate = self.create_investigation(counted="9.00")
        self.assertEqual(duplicate.status_code, 400)

        # 作废后可以重新发起
        investigation_id = first.json()["data"]["id"]
        self.client.post(f"/api/investigations/{investigation_id}/cancel/", {}, format="json")
        again = self.create_investigation(counted="9.00")
        self.assertEqual(again.status_code, 200)

    def test_create_rejects_unknown_goods(self):
        response = self.create_investigation(goods_id=99999)
        self.assertEqual(response.status_code, 400)

    def test_order_no_increments_within_day(self):
        first = self.create_investigation().json()["data"]["order_no"]
        second_goods = Goods.objects.create(
            variety=self.variety, name="备用终端", code="DEV-002", quantity=Decimal("3")
        )
        second = self.create_investigation(goods_id=second_goods.id, counted="1").json()["data"]["order_no"]
        self.assertEqual(int(second[-4:]), int(first[-4:]) + 1)


class InvestigationNoteTest(InvestigationFixture):
    def setUp(self):
        super().setUp()
        self.investigation_id = self.create_investigation().json()["data"]["id"]

    def test_notes_are_collected_by_type(self):
        self.fill_required_notes(self.investigation_id)
        detail = self.client.get(f"/api/investigations/{self.investigation_id}/").json()["data"]
        self.assertEqual([n["type"] for n in detail["notes"]], ["reason", "evidence", "review"])
        self.assertEqual(detail["notes"][0]["created_by"], self.user.id)

    def test_note_rejects_invalid_type_and_blank_content(self):
        bad_type = self.add_note(self.investigation_id, "other")
        self.assertEqual(bad_type.status_code, 400)
        blank = self.client.post(
            f"/api/investigations/{self.investigation_id}/notes/",
            {"type": "reason", "content": ""},
            format="json",
        )
        self.assertEqual(blank.status_code, 400)

    def test_notes_rejected_after_leaving_investigating(self):
        self.client.post(f"/api/investigations/{self.investigation_id}/cancel/", {}, format="json")
        response = self.add_note(self.investigation_id, "reason")
        self.assertEqual(response.status_code, 400)


class InvestigationCloseTest(InvestigationFixture):
    def setUp(self):
        super().setUp()
        self.investigation_id = self.create_investigation().json()["data"]["id"]

    def test_close_requires_all_note_types(self):
        self.add_note(self.investigation_id, "reason")
        self.auth_as(self.approver)
        response = self.close_investigation(self.investigation_id)
        self.assertEqual(response.status_code, 400)
        message = response.json()["message"]
        self.assertIn("证据材料", message)
        self.assertIn("复核意见", message)

    def test_close_requires_conclusion(self):
        self.fill_required_notes(self.investigation_id)
        self.auth_as(self.approver)
        response = self.client.post(
            f"/api/investigations/{self.investigation_id}/close/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_close_requires_admin(self):
        self.fill_required_notes(self.investigation_id)
        self.auth_as(self.viewer)
        response = self.close_investigation(self.investigation_id)
        self.assertEqual(response.status_code, 403)

    def test_close_rejected_for_creator(self):
        self.fill_required_notes(self.investigation_id)
        # self.user 是创建人，即使是管理员也不能批准自己的调查单
        response = self.close_investigation(self.investigation_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("创建人", response.json()["message"])

    def test_close_applies_independent_adjustment_entry(self):
        self.fill_required_notes(self.investigation_id)
        self.auth_as(self.approver)
        response = self.close_investigation(self.investigation_id)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "closed")
        self.assertEqual(data["conclusion"], "确认盘亏，按差异调整")
        self.assertEqual(data["closed_by"], self.approver.id)
        self.assertEqual(data["close_baseline_quantity"], "12.00")
        self.assertFalse(data["baseline_changed"])

        adjustments = data["adjustments"]
        self.assertEqual(len(adjustments), 1)
        self.assertEqual(adjustments[0]["type"], "stocktake")
        self.assertEqual(adjustments[0]["quantity"], "-2.00")
        self.assertEqual(adjustments[0]["before_quantity"], "12.00")
        self.assertEqual(adjustments[0]["after_quantity"], "10.00")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("10"))

    def test_close_detects_baseline_change_and_recalculates(self):
        # 调查期间物资继续正常收发：入 5、出 3，账面 12 -> 14
        self.simulate_stock_in(5)
        self.simulate_stock_out(3)

        self.fill_required_notes(self.investigation_id)
        self.auth_as(self.approver)
        response = self.close_investigation(self.investigation_id)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["baseline_changed"])
        self.assertEqual(data["close_baseline_quantity"], "14.00")

        # 差额按快照重算（10 - 12 = -2），应用到当前账面 14
        adjustment = data["adjustments"][0]
        self.assertEqual(adjustment["quantity"], "-2.00")
        self.assertEqual(adjustment["before_quantity"], "14.00")
        self.assertEqual(adjustment["after_quantity"], "12.00")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))

    def test_close_rejects_negative_resulting_quantity(self):
        # 实盘 0，调查期间全部出库，按差额调整会得到负库存
        self.client.post(f"/api/investigations/{self.investigation_id}/cancel/", {}, format="json")
        investigation_id = self.create_investigation(counted="0").json()["data"]["id"]
        self.simulate_stock_out(12)

        self.fill_required_notes(investigation_id)
        self.auth_as(self.approver)
        response = self.close_investigation(investigation_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能为负", response.json()["message"])

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("0"))

    def test_close_rejected_when_not_investigating(self):
        self.fill_required_notes(self.investigation_id)
        self.auth_as(self.approver)
        self.close_investigation(self.investigation_id)
        again = self.close_investigation(self.investigation_id)
        self.assertEqual(again.status_code, 400)


class InvestigationCancelTest(InvestigationFixture):
    def test_cancel_investigating_only(self):
        investigation_id = self.create_investigation().json()["data"]["id"]
        response = self.client.post(
            f"/api/investigations/{investigation_id}/cancel/",
            {"reason": "复盘后确认账实相符"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "cancelled")
        self.assertEqual(data["cancel_reason"], "复盘后确认账实相符")
        self.assertEqual(data["adjustments"], [])

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))

        again = self.client.post(f"/api/investigations/{investigation_id}/cancel/", {}, format="json")
        self.assertEqual(again.status_code, 400)


class InvestigationRevokeTest(InvestigationFixture):
    def setUp(self):
        super().setUp()
        self.investigation_id = self.create_investigation().json()["data"]["id"]
        self.fill_required_notes(self.investigation_id)
        self.auth_as(self.approver)
        self.close_investigation(self.investigation_id)

    def revoke(self, investigation_id, reason="结论有误，重新盘点"):
        return self.client.post(
            f"/api/investigations/{investigation_id}/revoke/",
            {"reason": reason},
            format="json",
        )

    def test_revoke_creates_reversal_without_overwriting_records(self):
        # 结案后又有正常入库 3，账面 10 -> 13
        self.simulate_stock_in(3)

        response = self.revoke(self.investigation_id)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "revoked")
        self.assertEqual(data["revoke_reason"], "结论有误，重新盘点")
        self.assertEqual(data["revoked_by"], self.approver.id)
        # 原结论与原因记录不被覆盖
        self.assertEqual(data["conclusion"], "确认盘亏，按差异调整")
        self.assertEqual(len(data["notes"]), 3)

        adjustments = data["adjustments"]
        self.assertEqual(len(adjustments), 2)
        original, reversal = adjustments
        # 原分录保持原样
        self.assertEqual(original["type"], "stocktake")
        self.assertEqual(original["quantity"], "-2.00")
        self.assertEqual(original["after_quantity"], "10.00")
        # 冲回分录指向原分录，并基于当前账面反向修正
        self.assertEqual(reversal["type"], "reversal")
        self.assertEqual(reversal["quantity"], "2.00")
        self.assertEqual(reversal["before_quantity"], "13.00")
        self.assertEqual(reversal["after_quantity"], "15.00")
        self.assertEqual(reversal["reverses"], original["id"])

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("15"))

    def test_revoke_requires_reason(self):
        response = self.client.post(
            f"/api/investigations/{self.investigation_id}/revoke/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_revoke_requires_closed_status(self):
        # 调查中的单子不能撤销
        investigation_id = self.create_investigation_for_goods()
        response = self.revoke(investigation_id)
        self.assertEqual(response.status_code, 400)

    def create_investigation_for_goods(self):
        goods = Goods.objects.create(
            variety=self.variety, name="备查终端", code="DEV-900", quantity=Decimal("8")
        )
        return self.create_investigation(goods_id=goods.id, counted="5").json()["data"]["id"]

    def test_revoke_twice_rejected(self):
        self.revoke(self.investigation_id)
        again = self.revoke(self.investigation_id)
        self.assertEqual(again.status_code, 400)

    def test_revoke_requires_admin(self):
        self.auth_as(self.viewer)
        response = self.revoke(self.investigation_id)
        self.assertEqual(response.status_code, 403)


class InvestigationReconciliationTest(InvestigationFixture):
    def test_reconciliation_reconstructs_full_chain(self):
        investigation_id = self.create_investigation().json()["data"]["id"]

        # 调查期间正常收发：入 5、出 3
        self.simulate_stock_in(5)
        self.simulate_stock_out(3)

        self.fill_required_notes(investigation_id)
        self.auth_as(self.approver)
        self.close_investigation(investigation_id)

        # 结案后又有入库 1
        self.simulate_stock_in(1)

        response = self.client.get(f"/api/investigations/{investigation_id}/reconciliation/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]

        def dec(key):
            return Decimal(str(data[key]))

        # 发现值 / 系统值 / 盘点差异
        self.assertEqual(dec("snapshot_quantity"), Decimal("12"))
        self.assertEqual(dec("counted_quantity"), Decimal("10"))
        self.assertEqual(dec("difference"), Decimal("-2"))

        # 后续变动
        movements = data["subsequent_movements"]
        self.assertEqual(Decimal(str(movements["stock_in_total"])), Decimal("6"))
        self.assertEqual(Decimal(str(movements["stock_out_total"])), Decimal("3"))
        self.assertEqual(Decimal(str(movements["net_change"])), Decimal("3"))
        self.assertEqual(len(movements["records"]), 3)
        self.assertEqual(
            [item["type"] for item in movements["records"]], ["in", "out", "in"]
        )

        # 结案基线变化与实际调整
        self.assertTrue(data["baseline_changed"])
        self.assertEqual(dec("close_baseline_quantity"), Decimal("14"))
        self.assertEqual(len(data["adjustments"]), 1)
        self.assertEqual(dec("adjustment_total"), Decimal("-2"))

        # 勾稽：系统值 + 后续变动 + 实际调整 = 当前库存
        self.assertEqual(dec("current_quantity"), Decimal("13"))
        self.assertEqual(dec("expected_quantity"), Decimal("13"))
        self.assertTrue(data["is_balanced"])

    def test_reconciliation_includes_reversal_entries(self):
        investigation_id = self.create_investigation().json()["data"]["id"]
        self.fill_required_notes(investigation_id)
        self.auth_as(self.approver)
        self.close_investigation(investigation_id)
        self.client.post(
            f"/api/investigations/{investigation_id}/revoke/",
            {"reason": "结论有误"},
            format="json",
        )

        data = self.client.get(f"/api/investigations/{investigation_id}/reconciliation/").json()["data"]
        self.assertEqual([a["type"] for a in data["adjustments"]], ["stocktake", "reversal"])
        # 调整与冲回相互抵销，当前库存回到系统值
        self.assertEqual(Decimal(str(data["adjustment_total"])), Decimal("0"))
        self.assertEqual(Decimal(str(data["current_quantity"])), Decimal("12"))
        self.assertTrue(data["is_balanced"])


class InvestigationQueryTest(InvestigationFixture):
    def test_list_filters_by_status_and_order_no(self):
        first_id = self.create_investigation().json()["data"]["id"]
        other_goods = Goods.objects.create(
            variety=self.variety, name="另一终端", code="DEV-003", quantity=Decimal("4")
        )
        second = self.create_investigation(goods_id=other_goods.id, counted="6").json()["data"]
        self.client.post(f"/api/investigations/{second['id']}/cancel/", {}, format="json")

        investigating = self.client.get("/api/investigations/?status=investigating").json()["data"]
        self.assertEqual(investigating["total"], 1)
        self.assertEqual(investigating["list"][0]["id"], first_id)

        cancelled = self.client.get("/api/investigations/?status=cancelled").json()["data"]
        self.assertEqual(cancelled["total"], 1)

        by_no = self.client.get(f"/api/investigations/?order_no={second['order_no']}").json()["data"]
        self.assertEqual(by_no["total"], 1)
        self.assertEqual(by_no["list"][0]["order_no"], second["order_no"])

    def test_detail_contains_notes_and_adjustments(self):
        investigation_id = self.create_investigation().json()["data"]["id"]
        self.fill_required_notes(investigation_id)
        self.auth_as(self.approver)
        self.close_investigation(investigation_id)

        detail = self.client.get(f"/api/investigations/{investigation_id}/").json()["data"]
        self.assertEqual(len(detail["notes"]), 3)
        self.assertEqual(len(detail["adjustments"]), 1)
        self.assertEqual(detail["goods_name"], "执法记录终端")

    def test_detail_not_found(self):
        response = self.client.get("/api/investigations/99999/")
        self.assertEqual(response.status_code, 404)

    def test_requires_authentication(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get("/api/investigations/").status_code, 401)
        self.assertEqual(anonymous.post("/api/investigations/", {}, format="json").status_code, 401)
