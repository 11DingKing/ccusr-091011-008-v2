"""
仓库管理URL配置
"""
from django.urls import path
from .views import (
    UnitListView, UnitDetailView, UnitBatchDeleteView, UnitAllView,
    CategoryListView, CategoryDetailView, CategoryBatchDeleteView, CategoryAllView,
    VarietyListView, VarietyDetailView, VarietyBatchDeleteView,
    VarietyTemplateView, VarietyImportView,
    DashboardView, GoodsListView, StockInListView, StockOutListView,
    WarningListView, ApprovalListView, StockLedgerView,
    InvestigationListView, InvestigationDetailView, InvestigationRecordView,
    InvestigationApproveView, InvestigationRejectView, InvestigationReverseView,
    InvestigationReconstructionView,
)

urlpatterns = [
    # 仪表盘
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # 单位管理
    path('units/', UnitListView.as_view(), name='unit-list'),
    path('units/all/', UnitAllView.as_view(), name='unit-all'),
    path('units/batch-delete/', UnitBatchDeleteView.as_view(), name='unit-batch-delete'),
    path('units/<int:pk>/', UnitDetailView.as_view(), name='unit-detail'),

    # 品类管理
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/all/', CategoryAllView.as_view(), name='category-all'),
    path('categories/batch-delete/', CategoryBatchDeleteView.as_view(), name='category-batch-delete'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category-detail'),

    # 品种管理
    path('varieties/', VarietyListView.as_view(), name='variety-list'),
    path('varieties/batch-delete/', VarietyBatchDeleteView.as_view(), name='variety-batch-delete'),
    path('varieties/template/', VarietyTemplateView.as_view(), name='variety-template'),
    path('varieties/import/', VarietyImportView.as_view(), name='variety-import'),
    path('varieties/<int:pk>/', VarietyDetailView.as_view(), name='variety-detail'),

    # 货物管理
    path('goods/', GoodsListView.as_view(), name='goods-list'),

    # 入库 / 出库
    path('stock-in/', StockInListView.as_view(), name='stock-in-list'),
    path('stock-out/', StockOutListView.as_view(), name='stock-out-list'),

    # 库存流水分录
    path('goods/<int:goods_id>/ledger/', StockLedgerView.as_view(), name='stock-ledger'),

    # 预警管理
    path('warnings/', WarningListView.as_view(), name='warning-list'),

    # 审批管理
    path('approvals/', ApprovalListView.as_view(), name='approval-list'),

    # 盘点差异调查单
    path('investigations/', InvestigationListView.as_view(), name='investigation-list'),
    path('investigations/<int:pk>/', InvestigationDetailView.as_view(), name='investigation-detail'),
    path('investigations/<int:pk>/records/', InvestigationRecordView.as_view(), name='investigation-records'),
    path('investigations/<int:pk>/approve/', InvestigationApproveView.as_view(), name='investigation-approve'),
    path('investigations/<int:pk>/reject/', InvestigationRejectView.as_view(), name='investigation-reject'),
    path('investigations/<int:pk>/reverse/', InvestigationReverseView.as_view(), name='investigation-reverse'),
    path('investigations/<int:pk>/reconstruction/', InvestigationReconstructionView.as_view(), name='investigation-reconstruction'),
]
