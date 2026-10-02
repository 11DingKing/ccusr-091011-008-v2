"""
盘点差异调查工作流

立案 -> 收集原因/证据/复核意见 -> 批准(基线检测+重算差额+独立调整分录) / 驳回
     -> 撤销(只追加冲回分录，不覆盖旧记录)

所有库存数量变动统一走库存流水（StockLedgerEntry），调查期间不锁定物资收发。
"""
from decimal import Decimal
import uuid

from django.db import transaction
from django.utils import timezone

from .models import (
    Goods, Investigation, InvestigationRecord, StockIn, StockLedgerEntry, StockOut,
)


class WorkflowError(Exception):
    """调查工作流业务错误"""


# ==================== 正常收发（调查期间同样可用）====================

@transaction.atomic
def receive_goods(goods_id, quantity, *, operator=None, batch_no='', supplier='', remark=''):
    """入库：登记入库记录 + 流水分录 + 更新库存，行锁保证结余连续。"""
    goods = Goods.objects.select_for_update().get(pk=goods_id)
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise WorkflowError('入库数量必须大于0')
    stock_in = StockIn.objects.create(
        goods=goods, operator=operator, quantity=quantity,
        batch_no=batch_no, supplier=supplier, remark=remark,
    )
    entry = StockLedgerEntry.post(
        goods, 'stock_in', quantity, operator=operator,
        ref_type='stock_in', ref_id=stock_in.id,
        remark=remark or f'入库单 {stock_in.id}',
    )
    goods.quantity = entry.balance_after
    goods.save(update_fields=['quantity', 'updated_at'])
    return stock_in, entry


@transaction.atomic
def issue_goods(goods_id, quantity, *, operator=None, receiver='', receiver_dept='', remark=''):
    """出库：登记出库记录（直接完成态）+ 流水分录 + 更新库存。"""
    goods = Goods.objects.select_for_update().get(pk=goods_id)
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise WorkflowError('出库数量必须大于0')
    if goods.quantity < quantity:
        raise WorkflowError('库存不足，无法出库')
    stock_out = StockOut.objects.create(
        goods=goods, operator=operator, quantity=quantity,
        receiver=receiver, receiver_dept=receiver_dept,
        status='completed', stock_out_time=timezone.now(), remark=remark,
    )
    entry = StockLedgerEntry.post(
        goods, 'stock_out', -quantity, operator=operator,
        ref_type='stock_out', ref_id=stock_out.id,
        remark=remark or f'出库单 {stock_out.id}',
    )
    goods.quantity = entry.balance_after
    goods.save(update_fields=['quantity', 'updated_at'])
    return stock_out, entry


# ==================== 调查单 ====================

def _generate_code():
    return f"PD-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"


@transaction.atomic
def open_investigation(*, goods_id, counted_quantity, responsibility_scope,
                       user, responsible_person='', location_scope='', remark=''):
    """立案：冻结盘点快照（发现值/系统值/初始差额/流水基线）与责任范围。"""
    goods = Goods.objects.select_for_update().get(pk=goods_id)
    counted_quantity = Decimal(str(counted_quantity))
    if counted_quantity < 0:
        raise WorkflowError('盘点发现值不能为负')
    if not responsibility_scope or not responsibility_scope.strip():
        raise WorkflowError('必须记录责任范围')

    system_qty = Decimal(str(goods.quantity))
    latest_ledger_id = (
        StockLedgerEntry.objects.filter(goods=goods)
        .order_by('-id').values_list('id', flat=True).first()
    )
    investigation = Investigation.objects.create(
        code=_generate_code(),
        goods=goods,
        snapshot_counted_qty=counted_quantity,
        snapshot_system_qty=system_qty,
        snapshot_diff=counted_quantity - system_qty,
        baseline_ledger_id=latest_ledger_id,
        responsibility_scope=responsibility_scope,
        responsible_person=responsible_person,
        location_scope=location_scope,
        created_by=user,
        remark=remark,
    )
    return investigation


@transaction.atomic
def add_record(*, investigation_id, kind, content, user, attachment_ref=''):
    """追加原因/证据/复核意见。记录只追加，不提供编辑与删除。"""
    if kind not in dict(InvestigationRecord.KIND_CHOICES):
        raise WorkflowError('无效的记录类型')
    if not content or not content.strip():
        raise WorkflowError('记录内容不能为空')
    investigation = Investigation.objects.select_for_update().get(pk=investigation_id)
    if investigation.status != 'investigating':
        raise WorkflowError('调查单已结案，不能再追加记录')
    return InvestigationRecord.objects.create(
        investigation=investigation,
        kind=kind,
        content=content,
        attachment_ref=attachment_ref,
        author=user,
    )


def _require_records(investigation):
    kinds = set(investigation.records.values_list('kind', flat=True))
    missing = []
    if 'reason' not in kinds:
        missing.append('差异原因')
    if 'review' not in kinds:
        missing.append('复核意见')
    if missing:
        raise WorkflowError(f"批准前还缺少：{'、'.join(missing)}")


@transaction.atomic
def approve_investigation(*, investigation_id, approver, opinion=''):
    """批准结案：

    1. 锁定货物行；
    2. 检测流水基线是否已被调查期间的收发推进；
    3. 按结案时点系统值重新计算差额（不直接采用立案时的初始差额）；
    4. 以独立调整分录修正库存，旧流水一律不动。
    """
    investigation = Investigation.objects.select_for_update().get(pk=investigation_id)
    if investigation.status != 'investigating':
        raise WorkflowError('只有调查中的单据可以批准结案')
    _require_records(investigation)

    goods = Goods.objects.select_for_update().get(pk=investigation.goods_id)

    latest_ledger_id = (
        StockLedgerEntry.objects.filter(goods=goods)
        .order_by('-id').values_list('id', flat=True).first()
    )
    baseline_changed = latest_ledger_id != investigation.baseline_ledger_id

    current_system_qty = Decimal(str(goods.quantity))
    recalculated_diff = investigation.snapshot_counted_qty - current_system_qty

    investigation.closed_system_qty = current_system_qty
    investigation.recalculated_diff = recalculated_diff
    investigation.baseline_changed = baseline_changed
    investigation.approver = approver
    investigation.approval_opinion = opinion
    investigation.approved_at = timezone.now()

    adjustment_entry = None
    if recalculated_diff != 0:
        adjustment_entry = StockLedgerEntry.post(
            goods, 'adjustment', recalculated_diff, operator=approver,
            ref_type='investigation', ref_id=investigation.id,
            remark=f'盘点差异调整 {investigation.code}',
        )
        goods.quantity = adjustment_entry.balance_after
        goods.save(update_fields=['quantity', 'updated_at'])
        investigation.adjustment_entry = adjustment_entry

    investigation.status = 'approved'
    investigation.save()
    return investigation


@transaction.atomic
def reject_investigation(*, investigation_id, approver, opinion=''):
    """驳回结案：记录驳回意见，不作任何库存调整。"""
    investigation = Investigation.objects.select_for_update().get(pk=investigation_id)
    if investigation.status != 'investigating':
        raise WorkflowError('只有调查中的单据可以驳回')
    if not opinion.strip():
        raise WorkflowError('驳回必须填写意见')
    investigation.status = 'rejected'
    investigation.approver = approver
    investigation.approval_opinion = opinion
    investigation.approved_at = timezone.now()
    investigation.closed_system_qty = Decimal(str(investigation.goods.quantity))
    investigation.save()
    return investigation


@transaction.atomic
def reverse_investigation(*, investigation_id, user, reason=''):
    """撤销已批准结论：

    追加一条与原调整相反的冲回分录并回退库存；原批准意见、原调整分录全部保留，
    状态以外的历史字段不被覆盖。
    """
    if not reason or not reason.strip():
        raise WorkflowError('撤销必须说明原因')
    investigation = Investigation.objects.select_for_update().get(pk=investigation_id)
    if investigation.status != 'approved':
        raise WorkflowError('只有已批准的调查单可以撤销')

    goods = Goods.objects.select_for_update().get(pk=investigation.goods_id)

    if investigation.adjustment_entry_id:
        original_change = investigation.adjustment_entry.quantity_change
        reversal_entry = StockLedgerEntry.post(
            goods, 'adjustment_reversal', -original_change, operator=user,
            ref_type='investigation', ref_id=investigation.id,
            remark=f'撤销调查单 {investigation.code}：{reason}',
        )
        goods.quantity = reversal_entry.balance_after
        goods.save(update_fields=['quantity', 'updated_at'])
        investigation.reversal_entry = reversal_entry

    investigation.status = 'reversed'
    investigation.reversed_by = user
    investigation.reversed_at = timezone.now()
    investigation.save()

    # 撤销原因以追加记录形式留痕，不改写任何旧记录
    InvestigationRecord.objects.create(
        investigation=investigation,
        kind='review',
        content=f'撤销原批准结论：{reason}',
        author=user,
    )
    return investigation
