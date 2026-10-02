"""
仓库管理序列化器
"""
from decimal import Decimal

from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    StockLedgerEntry, Investigation, InvestigationRecord,
)


class UnitSerializer(serializers.ModelSerializer):
    """单位序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Unit
        fields = [
            'id', 'name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitCreateSerializer(serializers.Serializer):
    """单位创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=5, required=True, error_messages={
        'required': '请输入单位名称',
        'blank': '单位名称不能为空',
        'min_length': '单位名称至少1个字',
        'max_length': '单位名称最多5个字',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Unit.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('单位名称已存在')
        else:
            if Unit.objects.filter(name=value).exists():
                raise serializers.ValidationError('单位名称已存在')
        return value


class CategorySerializer(serializers.ModelSerializer):
    """品类序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'unit', 'unit_name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryCreateSerializer(serializers.Serializer):
    """品类创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=10, required=True, error_messages={
        'required': '请输入品类名称',
        'blank': '品类名称不能为空',
        'min_length': '品类名称至少1个字',
        'max_length': '品类名称最多10个字',
    })
    unit = serializers.IntegerField(required=True, error_messages={
        'required': '请选择单位',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Category.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('品类名称已存在')
        else:
            if Category.objects.filter(name=value).exists():
                raise serializers.ValidationError('品类名称已存在')
        return value
    
    def validate_unit(self, value):
        if not Unit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('单位不存在')
        return value


class VarietySerializer(serializers.ModelSerializer):
    """品种序列化器"""
    is_in_stock = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Variety
        fields = [
            'id', 'name', 'category', 'category_name', 'unit_name',
            'is_in_stock', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class VarietyCreateSerializer(serializers.Serializer):
    """品种创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入品种名称',
        'blank': '品种名称不能为空',
        'min_length': '品种名称至少1个字',
        'max_length': '品种名称最多20个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品类',
    })
    
    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value
    
    def validate(self, data):
        instance = self.context.get('instance')
        name = data['name']
        category_id = data['category']
        
        if instance:
            if Variety.objects.filter(name=name, category_id=category_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        else:
            if Variety.objects.filter(name=name, category_id=category_id).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        return data


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'warning_threshold', 'location',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    
    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'batch_no', 'supplier', 'stock_in_time', 'remark'
        ]


class StockOutSerializer(serializers.ModelSerializer):
    """出库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockOut
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'receiver', 'receiver_dept', 'quantity', 'status', 'status_display',
            'stock_out_time', 'remark', 'created_at'
        ]


class WarningSerializer(serializers.ModelSerializer):
    """预警记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Warning
        fields = [
            'id', 'goods', 'goods_name', 'type', 'type_display',
            'message', 'is_read', 'created_at'
        ]


class ApprovalSerializer(serializers.ModelSerializer):
    """审批记录序列化器"""
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'stock_out', 'approver', 'approver_name',
            'status', 'status_display', 'remark', 'created_at', 'updated_at'
        ]


# ==================== 库存流水 ====================

class StockLedgerEntrySerializer(serializers.ModelSerializer):
    """库存流水分录序列化器"""
    entry_type_display = serializers.CharField(source='get_entry_type_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = StockLedgerEntry
        fields = [
            'id', 'goods', 'entry_type', 'entry_type_display',
            'quantity_change', 'balance_after',
            'ref_type', 'ref_id', 'operator', 'operator_name',
            'remark', 'created_at'
        ]


# ==================== 盘点差异调查单 ====================

class InvestigationOpenSerializer(serializers.Serializer):
    """立案序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    counted_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True, min_value=0,
        error_messages={'required': '请输入盘点发现值', 'min_value': '盘点发现值不能为负'}
    )
    responsibility_scope = serializers.CharField(
        min_length=1, max_length=200, required=True,
        error_messages={'required': '请填写责任范围', 'blank': '责任范围不能为空'}
    )
    responsible_person = serializers.CharField(max_length=100, required=False, allow_blank=True)
    location_scope = serializers.CharField(max_length=100, required=False, allow_blank=True)
    remark = serializers.CharField(required=False, allow_blank=True)

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value


class InvestigationRecordSerializer(serializers.ModelSerializer):
    """调查记录序列化器"""
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = InvestigationRecord
        fields = [
            'id', 'investigation', 'kind', 'kind_display', 'content',
            'attachment_ref', 'author', 'author_name', 'created_at'
        ]
        read_only_fields = ['id', 'investigation', 'author', 'created_at']


class InvestigationSerializer(serializers.ModelSerializer):
    """调查单序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    reversed_by_name = serializers.CharField(source='reversed_by.username', read_only=True)
    records = InvestigationRecordSerializer(many=True, read_only=True)
    interim_movement = serializers.SerializerMethodField()

    class Meta:
        model = Investigation
        fields = [
            'id', 'code', 'goods', 'goods_name', 'goods_code',
            'snapshot_counted_qty', 'snapshot_system_qty', 'snapshot_diff',
            'baseline_ledger_id',
            'responsibility_scope', 'responsible_person', 'location_scope',
            'status', 'status_display',
            'closed_system_qty', 'recalculated_diff', 'baseline_changed',
            'adjustment_entry', 'reversal_entry',
            'approver', 'approver_name', 'approval_opinion',
            'approved_at', 'reversed_by', 'reversed_by_name', 'reversed_at',
            'created_by', 'created_by_name', 'remark',
            'created_at', 'updated_at', 'records', 'interim_movement'
        ]

    def get_interim_movement(self, obj):
        return obj.interim_movement()


class InvestigationDecisionSerializer(serializers.Serializer):
    """批准/驳回序列化器"""
    opinion = serializers.CharField(required=False, allow_blank=True)


class InvestigationReverseSerializer(serializers.Serializer):
    """撤销序列化器"""
    reason = serializers.CharField(
        min_length=1, required=True,
        error_messages={'required': '请填写撤销原因', 'blank': '撤销原因不能为空'}
    )


class StockMovementSerializer(serializers.Serializer):
    """入库/出库请求序列化器"""
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True, min_value=Decimal('0.01'),
        error_messages={'required': '请输入数量', 'min_value': '数量必须大于0'}
    )
    batch_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    supplier = serializers.CharField(max_length=200, required=False, allow_blank=True)
    receiver = serializers.CharField(max_length=100, required=False, allow_blank=True)
    receiver_dept = serializers.CharField(max_length=100, required=False, allow_blank=True)
    remark = serializers.CharField(required=False, allow_blank=True)
