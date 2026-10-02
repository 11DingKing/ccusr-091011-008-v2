"""
库房管理模型
"""
from decimal import Decimal

from django.db import models
from apps.authentication.models import User


class Unit(models.Model):
    """单位模型"""
    name = models.CharField('单位名称', max_length=5, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_units', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_unit'
        verbose_name = '单位'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品类"""
        return self.categories.exists()


class Category(models.Model):
    """品类模型"""
    name = models.CharField('品类名称', max_length=10, unique=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT,
        related_name='categories', verbose_name='单位'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_categories', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_category'
        verbose_name = '品类'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品种"""
        return self.varieties.exists()


class Variety(models.Model):
    """品种模型"""
    name = models.CharField('品种名称', max_length=20)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='varieties', verbose_name='所属品类'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_varieties', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_variety'
        verbose_name = '品种'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        unique_together = ['category', 'name']
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    @property
    def is_in_stock(self):
        """是否已入库"""
        return self.goods.exists()
    
    @property
    def unit_name(self):
        """获取单位名称"""
        return self.category.unit.name if self.category and self.category.unit else ''


class Goods(models.Model):
    """货物模型"""
    variety = models.ForeignKey(
        Variety, on_delete=models.CASCADE,
        related_name='goods', verbose_name='所属品种'
    )
    name = models.CharField('货物名称', max_length=200)
    code = models.CharField('货物编码', max_length=50, unique=True)
    specification = models.CharField('规格型号', max_length=200, blank=True)
    quantity = models.DecimalField('库存数量', max_digits=12, decimal_places=2, default=0)
    warning_threshold = models.DecimalField('预警阈值', max_digits=12, decimal_places=2, default=10)
    location = models.CharField('存放位置', max_length=100, blank=True)
    remark = models.TextField('备注', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_goods'
        verbose_name = '货物'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_warning(self):
        """是否预警"""
        return self.quantity <= self.warning_threshold


class StockIn(models.Model):
    """入库记录模型"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_ins', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_in_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('入库数量', max_digits=12, decimal_places=2)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    supplier = models.CharField('供应商', max_length=200, blank=True)
    stock_in_time = models.DateTimeField('入库时间', auto_now_add=True)
    remark = models.TextField('备注', blank=True)
    
    class Meta:
        db_table = 'wh_stock_in'
        verbose_name = '入库记录'
        verbose_name_plural = verbose_name
        ordering = ['-stock_in_time']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class StockOut(models.Model):
    """出库记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_outs', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_out_operations', verbose_name='操作人'
    )
    receiver = models.CharField('领用人', max_length=100)
    receiver_dept = models.CharField('领用部门', max_length=100, blank=True)
    quantity = models.DecimalField('出库数量', max_digits=12, decimal_places=2)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    stock_out_time = models.DateTimeField('出库时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_stock_out'
        verbose_name = '出库记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class Warning(models.Model):
    """预警记录模型"""
    TYPE_CHOICES = [
        ('low_stock', '库存不足'),
        ('expiring', '即将过期'),
        ('expired', '已过期'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='warnings', verbose_name='货物'
    )
    type = models.CharField('预警类型', max_length=20, choices=TYPE_CHOICES)
    message = models.TextField('预警信息')
    is_read = models.BooleanField('是否已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_warning'
        verbose_name = '预警记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.get_type_display()}"


class Approval(models.Model):
    """审批记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    
    stock_out = models.ForeignKey(
        StockOut, on_delete=models.CASCADE,
        related_name='approvals', verbose_name='出库记录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approvals', verbose_name='审批人'
    )
    status = models.CharField('审批状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    remark = models.TextField('审批意见', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_approval'
        verbose_name = '审批记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.stock_out} - {self.get_status_display()}"


class StockLedgerEntry(models.Model):
    """库存流水（独立会计分录）

    所有库存数量变动都以一条带符号的分录登记，结案调整也不例外。
    分录一经写入不可修改；撤销调整时再追加一条反向分录，绝不覆盖旧记录。
    """
    TYPE_CHOICES = [
        ('stock_in', '入库'),
        ('stock_out', '出库'),
        ('adjustment', '盘点调整'),
        ('adjustment_reversal', '调整冲回'),
    ]

    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='ledger_entries', verbose_name='货物'
    )
    entry_type = models.CharField('分录类型', max_length=20, choices=TYPE_CHOICES)
    quantity_change = models.DecimalField(
        '数量变动', max_digits=12, decimal_places=2,
        help_text='带符号：入库/盘盈为正，出库/盘亏为负'
    )
    balance_after = models.DecimalField('变动后结余', max_digits=12, decimal_places=2)
    ref_type = models.CharField('来源单据类型', max_length=30, blank=True)
    ref_id = models.BigIntegerField('来源单据ID', null=True, blank=True)
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='ledger_entries', verbose_name='操作人'
    )
    remark = models.TextField('摘要', blank=True)
    created_at = models.DateTimeField('记账时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_stock_ledger_entry'
        verbose_name = '库存流水分录'
        verbose_name_plural = verbose_name
        ordering = ['id']
        indexes = [
            models.Index(fields=['goods', 'id']),
            models.Index(fields=['ref_type', 'ref_id']),
        ]

    def __str__(self):
        return f"{self.goods.name} {self.get_entry_type_display()} {self.quantity_change}"

    @classmethod
    def last_balance(cls, goods_id, before_id=None):
        """取某货物（可选：某分录之前）的最近结余；无流水时返回 None。"""
        qs = cls.objects.filter(goods_id=goods_id)
        if before_id is not None:
            qs = qs.filter(id__lt=before_id)
        last = qs.order_by('-id').values_list('balance_after', flat=True).first()
        return last

    @classmethod
    def post(cls, goods, entry_type, change, operator=None, ref_type='', ref_id=None, remark=''):
        """追加一条分录并按最新结余回填 balance_after，不改写任何旧分录。"""
        change = Decimal(str(change))
        previous = cls.objects.filter(goods=goods).order_by('-id').values_list(
            'balance_after', flat=True
        ).first()
        if previous is None:
            # 无历史流水（期初库存尚未入账），当前库存即变动前结余
            previous = Decimal(str(goods.quantity))
        entry = cls.objects.create(
            goods=goods,
            entry_type=entry_type,
            quantity_change=change,
            balance_after=previous + change,
            ref_type=ref_type,
            ref_id=ref_id,
            operator=operator,
            remark=remark,
        )
        return entry


class Investigation(models.Model):
    """盘点差异调查单

    生命周期：
      investigating 调查中（物资正常收发，不锁库存）
      approved      已批准（已按结案时点系统值重算差额并过调整分录）
      rejected      已驳回（不作调整）
      reversed      已撤销（追加冲回分录，原批准记录保留）
    """
    STATUS_CHOICES = [
        ('investigating', '调查中'),
        ('approved', '已批准'),
        ('rejected', '已驳回'),
        ('reversed', '已撤销'),
    ]

    code = models.CharField('调查单号', max_length=40, unique=True)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='investigations', verbose_name='货物'
    )

    # —— 立案基线（盘点快照，永不变更）——
    snapshot_counted_qty = models.DecimalField(
        '盘点发现值（快照）', max_digits=12, decimal_places=2
    )
    snapshot_system_qty = models.DecimalField(
        '系统库存值（快照）', max_digits=12, decimal_places=2
    )
    snapshot_diff = models.DecimalField(
        '初始差额（发现值-系统值，快照）', max_digits=12, decimal_places=2
    )
    baseline_ledger_id = models.BigIntegerField(
        '基线流水ID', null=True, blank=True,
        help_text='立案时该货物最新流水；结案据此检测基线是否被后续收发推进'
    )
    responsibility_scope = models.CharField('责任范围', max_length=200)
    responsible_person = models.CharField('责任人', max_length=100, blank=True)
    location_scope = models.CharField('盘点责任区域', max_length=100, blank=True)

    # —— 结案字段（仅在结案时写入一次）——
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='investigating')
    closed_system_qty = models.DecimalField(
        '结案时系统值', max_digits=12, decimal_places=2, null=True, blank=True
    )
    recalculated_diff = models.DecimalField(
        '结案重算差额', max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='发现值快照 - 结案时系统值（含调查期间收发）'
    )
    baseline_changed = models.BooleanField(
        '基线是否已变化', null=True, blank=True,
        help_text='调查期间是否发生过影响库存的收发'
    )
    adjustment_entry = models.ForeignKey(
        StockLedgerEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name='investigation_adjustments', verbose_name='调整分录'
    )
    reversal_entry = models.ForeignKey(
        StockLedgerEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name='investigation_reversals', verbose_name='冲回分录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_investigations', verbose_name='批准人'
    )
    approval_opinion = models.TextField('批准/驳回意见', blank=True)
    approved_at = models.DateTimeField('结案时间', null=True, blank=True)
    reversed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reversed_investigations', verbose_name='撤销人'
    )
    reversed_at = models.DateTimeField('撤销时间', null=True, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_investigations', verbose_name='立案人'
    )
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_investigation'
        verbose_name = '盘点差异调查单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} - {self.goods.name}"

    # —— 期间流水（调查期间的后续变动）——
    def interim_entries(self):
        """立案基线之后、结案之前发生的流水（调查期间的收发与其他变动）。"""
        qs = self.goods.ledger_entries.all()
        if self.baseline_ledger_id is not None:
            qs = qs.filter(id__gt=self.baseline_ledger_id)
        if self.adjustment_entry_id:
            # 调整分录本身即结案边界
            qs = qs.filter(id__lt=self.adjustment_entry_id)
        elif self.approved_at:
            # 结案差额为0、无调整分录时，以结案时间为界
            qs = qs.filter(created_at__lt=self.approved_at)
        return qs.select_related('operator')

    def interim_movement(self):
        """调查期间后续变动净额（入库为正、出库为负）。"""
        total = self.interim_entries().aggregate(total=models.Sum('quantity_change'))['total']
        return total or Decimal('0')

    def post_close_movement(self):
        """结案之后的其他收发净额（不含本单自己的冲回分录），用于推算当前系统值。"""
        if self.adjustment_entry_id:
            qs = self.goods.ledger_entries.filter(id__gt=self.adjustment_entry_id)
        elif self.approved_at:
            qs = self.goods.ledger_entries.filter(created_at__gte=self.approved_at)
        else:
            return Decimal('0')
        qs = qs.exclude(
            entry_type='adjustment_reversal', ref_type='investigation', ref_id=self.id
        )
        total = qs.aggregate(total=models.Sum('quantity_change'))['total']
        return total or Decimal('0')

    def reconstruction(self):
        """还原 发现值 / 系统值 / 后续变动 / 实际调整 之间的关系。"""
        from django.utils import timezone

        counted = self.snapshot_counted_qty
        snap_system = self.snapshot_system_qty
        interim = self.interim_movement()
        adjustment_qty = (
            self.adjustment_entry.quantity_change if self.adjustment_entry_id else Decimal('0')
        )
        reversal_qty = (
            self.reversal_entry.quantity_change if self.reversal_entry_id else Decimal('0')
        )
        net_adjustment = adjustment_qty + reversal_qty
        post_close = self.post_close_movement()
        closed_system = self.closed_system_qty
        if closed_system is None:
            # 未结案：以当前库存扣减净调整，推算结案前系统值
            closed_system = Decimal(str(self.goods.quantity)) - net_adjustment
        return {
            'code': self.code,
            'status': self.status,
            'goods_id': self.goods_id,
            'counted_qty_snapshot': counted,
            'system_qty_snapshot': snap_system,
            'initial_diff_snapshot': self.snapshot_diff,
            'baseline_ledger_id': self.baseline_ledger_id,
            'interim_movement': interim,
            'system_qty_at_close': closed_system,
            'baseline_changed': self.baseline_changed,
            'recalculated_diff': self.recalculated_diff,
            'adjustment_quantity': adjustment_qty,
            'adjustment_entry_id': self.adjustment_entry_id,
            'reversal_quantity': reversal_qty,
            'reversal_entry_id': self.reversal_entry_id,
            'net_adjustment_quantity': net_adjustment,
            'post_close_movement': post_close,
            'current_system_qty': Decimal(str(self.goods.quantity)),
            'reconstructed_at': timezone.now(),
            'identity_check': {
                # 系统快照 + 期间净变动 = 结案前系统值
                'system_plus_interim_equals_close': (
                    snap_system + interim == closed_system
                ),
                # 结案前系统值 + 原始调整 = 盘点发现值
                'close_plus_adjustment_equals_counted': (
                    closed_system + adjustment_qty == counted
                ),
                # 结案前系统值 + 净调整 + 结案后收发 = 当前系统值
                'close_to_current': (
                    closed_system + net_adjustment + post_close
                    == Decimal(str(self.goods.quantity))
                ),
            },
        }


class InvestigationRecord(models.Model):
    """调查记录：原因、证据、复核意见（只追加，不可编辑/删除）。"""
    KIND_CHOICES = [
        ('reason', '差异原因'),
        ('evidence', '证据'),
        ('review', '复核意见'),
    ]

    investigation = models.ForeignKey(
        Investigation, on_delete=models.CASCADE,
        related_name='records', verbose_name='调查单'
    )
    kind = models.CharField('记录类型', max_length=20, choices=KIND_CHOICES)
    content = models.TextField('内容')
    attachment_ref = models.CharField('证据附件引用', max_length=200, blank=True)
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='investigation_records', verbose_name='记录人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_investigation_record'
        verbose_name = '调查记录'
        verbose_name_plural = verbose_name
        ordering = ['created_at', 'id']

    def __str__(self):
        return f"{self.investigation.code} - {self.get_kind_display()}"
