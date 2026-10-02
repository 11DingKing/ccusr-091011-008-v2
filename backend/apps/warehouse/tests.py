from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .models import (
    Approval, Category, Goods, Investigation, StockIn, StockLedgerEntry,
    StockOut, Unit, Variety, Warning,
)
from .services import (
    WorkflowError, add_record, approve_investigation, issue_goods,
    open_investigation, receive_goods, reject_investigation, reverse_investigation,
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


# ==================== 库存流水与收发 ====================

class StockLedgerServiceTest(WarehouseFixture):
    def test_receive_posts_ledger_and_updates_quantity(self):
        stock_in, entry = receive_goods(
            self.goods.id, Decimal("8"), operator=self.user, supplier="供应商甲"
        )
        self.goods.refresh_from_db()
        self.assertEqual(entry.entry_type, "stock_in")
        self.assertEqual(entry.quantity_change, Decimal("8"))
        self.assertEqual(entry.balance_after, Decimal("20"))
        self.assertEqual(self.goods.quantity, Decimal("20"))
        self.assertEqual(entry.ref_type, "stock_in")
        self.assertEqual(entry.ref_id, stock_in.id)

    def test_issue_posts_signed_entry_and_chain_balance(self):
        receive_goods(self.goods.id, Decimal("8"), operator=self.user)
        _, out_entry = issue_goods(
            self.goods.id, Decimal("5"), operator=self.user, receiver="领用人甲"
        )
        self.goods.refresh_from_db()
        self.assertEqual(out_entry.quantity_change, Decimal("-5"))
        self.assertEqual(out_entry.balance_after, Decimal("15"))
        self.assertEqual(self.goods.quantity, Decimal("15"))
        balances = list(
            StockLedgerEntry.objects.filter(goods=self.goods)
            .order_by("id")
            .values_list("balance_after", flat=True)
        )
        self.assertEqual(balances, [Decimal("20"), Decimal("15")])

    def test_issue_rejects_oversell_and_nonpositive(self):
        with self.assertRaises(WorkflowError):
            issue_goods(self.goods.id, Decimal("999"), operator=self.user, receiver="X")
        with self.assertRaises(WorkflowError):
            receive_goods(self.goods.id, Decimal("0"), operator=self.user)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))
        self.assertEqual(StockLedgerEntry.objects.count(), 0)


# ==================== 调查单工作流 ====================

class InvestigationWorkflowTest(WarehouseFixture):
    def _open(self, counted=Decimal("10")):
        return open_investigation(
            goods_id=self.goods.id,
            counted_quantity=counted,
            responsibility_scope="一号库全部受控器材",
            user=self.user,
            responsible_person="保管员A",
            location_scope="A区货架3",
        )

    def _collect(self, inv):
        add_record(investigation_id=inv.id, kind="reason",
                   content="出入库登记漏记一笔", user=self.user)
        add_record(investigation_id=inv.id, kind="evidence",
                   content="监控录像与签认单", user=self.user,
                   attachment_ref="media/evidence-001.zip")
        add_record(investigation_id=inv.id, kind="review",
                   content="复核属实，同意调整", user=self.user)

    def test_open_freezes_snapshot_and_baseline(self):
        _, entry = receive_goods(self.goods.id, Decimal("3"), operator=self.user)
        inv = self._open(counted=Decimal("14"))
        self.assertEqual(inv.snapshot_counted_qty, Decimal("14"))
        self.assertEqual(inv.snapshot_system_qty, Decimal("15"))
        self.assertEqual(inv.snapshot_diff, Decimal("-1"))
        self.assertEqual(inv.baseline_ledger_id, entry.id)
        self.assertEqual(inv.status, "investigating")

    def test_open_requires_responsibility_scope(self):
        with self.assertRaises(WorkflowError):
            open_investigation(
                goods_id=self.goods.id, counted_quantity=Decimal("10"),
                responsibility_scope=" ", user=self.user,
            )

    def test_approve_requires_reason_and_review(self):
        inv = self._open()
        add_record(investigation_id=inv.id, kind="evidence",
                   content="只有证据", user=self.user)
        with self.assertRaises(WorkflowError):
            approve_investigation(investigation_id=inv.id, approver=self.user)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "investigating")

    def test_approve_posts_independent_adjustment_entry(self):
        inv = self._open(counted=Decimal("10"))  # 系统12，盘亏2
        self._collect(inv)
        approve_investigation(investigation_id=inv.id, approver=self.user,
                              opinion="同意按盘亏处理")
        inv.refresh_from_db()
        self.goods.refresh_from_db()

        self.assertEqual(inv.status, "approved")
        self.assertFalse(inv.baseline_changed)
        self.assertEqual(inv.recalculated_diff, Decimal("-2"))
        self.assertEqual(inv.closed_system_qty, Decimal("12"))
        self.assertEqual(inv.adjustment_entry.entry_type, "adjustment")
        self.assertEqual(inv.adjustment_entry.quantity_change, Decimal("-2"))
        self.assertEqual(inv.adjustment_entry.ref_type, "investigation")
        self.assertEqual(inv.adjustment_entry.ref_id, inv.id)
        self.assertEqual(self.goods.quantity, Decimal("10"))

    def test_goods_keep_moving_during_investigation_and_diff_recalculated(self):
        # 立案：系统12，发现10，初始差额-2
        inv = self._open(counted=Decimal("10"))
        # 调查期间正常收发：入库8、出库5，净+3，系统值变为15
        receive_goods(self.goods.id, Decimal("8"), operator=self.user)
        issue_goods(self.goods.id, Decimal("5"), operator=self.user, receiver="使用人")

        self._collect(inv)
        approve_investigation(investigation_id=inv.id, approver=self.user)
        inv.refresh_from_db()
        self.goods.refresh_from_db()

        self.assertTrue(inv.baseline_changed)
        # 重算差额 = 发现值10 - 结案时系统值15 = -5（而非立案时的-2）
        self.assertEqual(inv.closed_system_qty, Decimal("15"))
        self.assertEqual(inv.recalculated_diff, Decimal("-5"))
        self.assertEqual(inv.adjustment_entry.quantity_change, Decimal("-5"))
        self.assertEqual(self.goods.quantity, Decimal("10"))

        recon = inv.reconstruction()
        self.assertEqual(recon["interim_movement"], Decimal("3"))
        self.assertTrue(recon["identity_check"]["system_plus_interim_equals_close"])
        self.assertTrue(recon["identity_check"]["close_plus_adjustment_equals_counted"])

    def test_zero_recalculated_diff_approves_without_adjustment(self):
        inv = self._open(counted=Decimal("10"))  # 初始差额-2
        # 调查期间出库2，系统值恰好变为10
        issue_goods(self.goods.id, Decimal("2"), operator=self.user, receiver="使用人")
        self._collect(inv)
        approve_investigation(investigation_id=inv.id, approver=self.user)
        inv.refresh_from_db()
        self.goods.refresh_from_db()

        self.assertEqual(inv.status, "approved")
        self.assertTrue(inv.baseline_changed)
        self.assertEqual(inv.recalculated_diff, Decimal("0"))
        self.assertIsNone(inv.adjustment_entry_id)
        self.assertEqual(self.goods.quantity, Decimal("10"))
        recon = inv.reconstruction()
        self.assertTrue(recon["identity_check"]["system_plus_interim_equals_close"])

    def test_records_are_append_only_after_close(self):
        inv = self._open()
        self._collect(inv)
        approve_investigation(investigation_id=inv.id, approver=self.user)
        with self.assertRaises(WorkflowError):
            add_record(investigation_id=inv.id, kind="reason",
                       content="结案后试图补记", user=self.user)

    def test_reject_needs_opinion_and_changes_nothing(self):
        inv = self._open()
        with self.assertRaises(WorkflowError):
            reject_investigation(investigation_id=inv.id, approver=self.user, opinion="  ")
        reject_investigation(investigation_id=inv.id, approver=self.user,
                             opinion="证据不足")
        inv.refresh_from_db()
        self.goods.refresh_from_db()
        self.assertEqual(inv.status, "rejected")
        self.assertEqual(self.goods.quantity, Decimal("12"))
        self.assertEqual(StockLedgerEntry.objects.count(), 0)

    def test_reverse_appends_reversal_without_overwriting_history(self):
        inv = self._open(counted=Decimal("10"))
        self._collect(inv)
        approve_investigation(investigation_id=inv.id, approver=self.user, opinion="同意")
        inv.refresh_from_db()
        original_entry_id = inv.adjustment_entry_id
        original_change = inv.adjustment_entry.quantity_change
        original_opinion = inv.approval_opinion
        original_approved_at = inv.approved_at
        original_records = list(
            inv.records.values_list("kind", "content").order_by("id")
        )

        # 结案后又有正常收发
        receive_goods(self.goods.id, Decimal("4"), operator=self.user)

        reverse_investigation(investigation_id=inv.id, user=self.user,
                              reason="发现新证据，原结论依据错误")
        inv.refresh_from_db()
        self.goods.refresh_from_db()

        self.assertEqual(inv.status, "reversed")
        # 旧记录未被覆盖
        self.assertEqual(inv.adjustment_entry_id, original_entry_id)
        self.assertEqual(inv.adjustment_entry.quantity_change, original_change)
        self.assertEqual(inv.approval_opinion, original_opinion)
        self.assertEqual(inv.approved_at, original_approved_at)
        self.assertEqual(
            list(inv.records.values_list("kind", "content").order_by("id"))[:3],
            original_records,
        )
        # 追加了反向分录与撤销留痕
        self.assertIsNotNone(inv.reversal_entry_id)
        self.assertEqual(inv.reversal_entry.entry_type, "adjustment_reversal")
        self.assertEqual(inv.reversal_entry.quantity_change, Decimal("2"))
        self.assertTrue(
            inv.records.filter(content__contains="撤销原批准结论").exists()
        )
        # 库存 = 结案前12 + 结案后入库4（调整被冲回）
        self.assertEqual(self.goods.quantity, Decimal("16"))
        # 流水只追加，共 调整-2、入库+4、冲回+2 三条
        changes = list(
            StockLedgerEntry.objects.filter(goods=self.goods)
            .order_by("id").values_list("entry_type", "quantity_change")
        )
        self.assertEqual(changes, [
            ("adjustment", Decimal("-2")),
            ("stock_in", Decimal("4")),
            ("adjustment_reversal", Decimal("2")),
        ])

        recon = inv.reconstruction()
        self.assertEqual(recon["net_adjustment_quantity"], Decimal("0"))
        self.assertEqual(recon["post_close_movement"], Decimal("4"))
        self.assertTrue(all(recon["identity_check"].values()))

        # 不可重复撤销
        with self.assertRaises(WorkflowError):
            reverse_investigation(investigation_id=inv.id, user=self.user, reason="再次撤销")

    def test_cannot_approve_twice(self):
        inv = self._open()
        self._collect(inv)
        approve_investigation(investigation_id=inv.id, approver=self.user)
        with self.assertRaises(WorkflowError):
            approve_investigation(investigation_id=inv.id, approver=self.user)


class InvestigationAPITest(WarehouseFixture):
    def _open_via_api(self, counted="10"):
        return self.client.post(
            "/api/investigations/",
            {
                "goods": self.goods.id,
                "counted_quantity": counted,
                "responsibility_scope": "一号库全部受控器材",
                "responsible_person": "保管员A",
            },
            format="json",
        )

    def test_full_workflow_and_reconstruction_endpoint(self):
        resp = self._open_via_api("10")
        self.assertEqual(resp.status_code, 200)
        inv_id = resp.json()["data"]["id"]

        # 调查期间物资正常收发
        r_in = self.client.post(
            "/api/stock-in/", {"goods": self.goods.id, "quantity": "8"}, format="json"
        )
        self.assertEqual(r_in.status_code, 200)
        r_out = self.client.post(
            "/api/stock-out/",
            {"goods": self.goods.id, "quantity": "5", "receiver": "使用人甲"},
            format="json",
        )
        self.assertEqual(r_out.status_code, 200)

        for kind, content in [
            ("reason", "漏记出库"),
            ("evidence", "监控录像"),
            ("review", "复核属实"),
        ]:
            rec = self.client.post(
                f"/api/investigations/{inv_id}/records/",
                {"kind": kind, "content": content},
                format="json",
            )
            self.assertEqual(rec.status_code, 200, rec.content)

        approved = self.client.post(
            f"/api/investigations/{inv_id}/approve/", {"opinion": "同意"}, format="json"
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        data = approved.json()["data"]
        self.assertTrue(data["baseline_changed"])
        self.assertEqual(data["recalculated_diff"], "-5.00")
        self.assertEqual(data["closed_system_qty"], "15.00")

        recon = self.client.get(f"/api/investigations/{inv_id}/reconstruction/")
        self.assertEqual(recon.status_code, 200)
        rdata = recon.json()["data"]
        self.assertEqual(float(rdata["counted_qty_snapshot"]), 10.0)
        self.assertEqual(float(rdata["system_qty_snapshot"]), 12.0)
        self.assertEqual(float(rdata["interim_movement"]), 3.0)
        self.assertEqual(float(rdata["adjustment_quantity"]), -5.0)
        self.assertTrue(all(rdata["identity_check"].values()))
        self.assertEqual(len(rdata["interim_entries"]), 2)

    def test_open_validates_goods_and_scope(self):
        bad_goods = self.client.post(
            "/api/investigations/",
            {"goods": 99999, "counted_quantity": "10",
             "responsibility_scope": "X"},
            format="json",
        )
        self.assertEqual(bad_goods.status_code, 400)
        no_scope = self.client.post(
            "/api/investigations/",
            {"goods": self.goods.id, "counted_quantity": "10"},
            format="json",
        )
        self.assertEqual(no_scope.status_code, 400)

    def test_record_after_close_rejected_and_reverse_flow(self):
        inv_id = self._open_via_api("10").json()["data"]["id"]
        for kind, content in [("reason", "原因"), ("review", "复核通过")]:
            self.client.post(
                f"/api/investigations/{inv_id}/records/",
                {"kind": kind, "content": content}, format="json",
            )
        self.client.post(
            f"/api/investigations/{inv_id}/approve/", {}, format="json"
        )
        late = self.client.post(
            f"/api/investigations/{inv_id}/records/",
            {"kind": "reason", "content": "结案后补记"}, format="json",
        )
        self.assertEqual(late.status_code, 400)

        no_reason = self.client.post(
            f"/api/investigations/{inv_id}/reverse/", {}, format="json"
        )
        self.assertEqual(no_reason.status_code, 400)
        reversed_resp = self.client.post(
            f"/api/investigations/{inv_id}/reverse/",
            {"reason": "依据错误"}, format="json",
        )
        self.assertEqual(reversed_resp.status_code, 200)
        self.assertEqual(reversed_resp.json()["data"]["status"], "reversed")

    def test_missing_investigation_returns_404(self):
        self.assertEqual(
            self.client.get("/api/investigations/99999/reconstruction/").status_code, 404
        )

    def test_ledger_endpoint_lists_entries(self):
        self.client.post(
            "/api/stock-in/", {"goods": self.goods.id, "quantity": "3"}, format="json"
        )
        resp = self.client.get(f"/api/goods/{self.goods.id}/ledger/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["total"], 1)
        self.assertEqual(resp.json()["data"]["list"][0]["balance_after"], "15.00")

    def test_stock_out_rejects_insufficient_stock(self):
        resp = self.client.post(
            "/api/stock-out/",
            {"goods": self.goods.id, "quantity": "999", "receiver": "X"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
