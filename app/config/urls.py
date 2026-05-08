"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from .api_views import CsrfView, LoginView, LogoutView, MeView, UserDetailView, TokenView
from mailbox_app.api_views import MailboxSyncView
from mailbox_app.api import MailMessageDetailView, MailMessageListView
from contacts.api import SupplierListView
from configuration.api import PaymentTypeListView
from accounting.api import CashLedgerView
from orders.api import (
    PurchaseOrderDetailView,
    PurchaseOrderItemDetailView,
    PurchaseOrderItemPriceUpdateView,
    PurchaseOrderItemListCreateView,
    PurchaseOrderListCreateView,
    PurchaseOrderWarehouseInputCreateView,
    PurchaseOrderSendView,
    SupplierInvoicePostView,
    SupplierArtiklListView,
    WarehouseInputCreateSupplierInvoiceView,
)
from artikli.api import (
    ArtiklDetailView,
    ArtiklListView,
    UnitOfMeasureListView,
    ArtiklImage46x75View,
    ArtiklImage125x200View,
    DrinkCategoryListView,
    DrinkCategoryDetailView,
)
from sales.api import (
    RepresentationDetailView,
    RepresentationListView,
    RepresentationReasonDetailView,
    RepresentationReasonListView,
    RemarisImportView,
)
from stock.api import (
    InventoryDetailView,
    InventoryItemDetailView,
    InventoryItemListCreateView,
    InventoryListCreateView,
    InventoryPublicDetailView,
    InventoryPublicSubmitView,
    SupplierReturnDetailView,
    SupplierReturnItemDetailView,
    SupplierReturnItemListCreateView,
    SupplierReturnListCreateView,
    SupplierReturnPostView,
    WarehouseStockSyncView,
    WarehouseIdListView,
)
from pos.api import (
    PosPinVerifyView,
    PosPinLoginView,
    PosFiscalizeInvoiceView,
    PosListCreateView,
    PosDetailView,
    PosReceiptCreateView,
    PosReceiptFiscalizeView,
    PosReceiptPrintView,
    PosReceiptStornoView,
    PosShiftCloseView,
    PosShiftExpenseView,
    PosShiftTurnoverView,
    PosInvoicePaymentFlagView,
    PosShiftCashExpectedView,
    PosShiftCashHandoverView,
    PosPrinterListView,
    PosPrinterSyncView,
    PosDevicePrinterSelectionView,
)
from ai.api import AIQueryView
from ai.views import AiSearchView
from operations.api import (
    ShiftCashCountCreateView,
    ShiftCashSummaryView,
    ShiftListCreateView,
)
from barion.api import (
    PosActiveLayoutView,
    PosAllowedLayoutsView,
    PosCheckCloseView,
    PosCheckItemDetailView,
    PosCheckItemGratisView,
    PosCheckItemOtpisView,
    PosCheckItemStornoView,
    PosCheckIssueReceiptView,
    PosCheckReceiptFiscalizeView,
    PosCheckPayCardConfirmView,
    PosCheckPrepareSettlementView,
    PosCheckRoundStateView,
    PosCheckSettlementStateView,
    PosSettlementPartPayCardConfirmView,
    PosSettlementPartPayCashView,
    PosProductBundlePriceView,
    PosCheckItemsView,
    PosCheckSendToBarView,
    PosChecksView,
    PosDrinkCategoriesDisplayView,
    PosProductModifiersView,
    PosProductSearchView,
    PosRuntimeModeView,
    PosTableStatusView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path("orders/", include("orders.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", staff_member_required(SpectacularSwaggerView.as_view(url_name="api-schema")), name="api-docs"),
    path("api/redoc/", staff_member_required(SpectacularRedocView.as_view(url_name="api-schema")), name="api-redoc"),
    path("api/csrf/", CsrfView.as_view(), name="api-csrf"),
    path("api/login/", LoginView.as_view(), name="api-login"),
    path("api/logout/", LogoutView.as_view(), name="api-logout"),
    path('api/token/', TokenView.as_view(), name='api-token'),
    path('api/me/', MeView.as_view(), name='api-me'),
    path('api/users/<int:user_id>/', UserDetailView.as_view(), name='api-user-detail'),
    path('api/artikli/', ArtiklListView.as_view(), name='api-artikl-list'),
    path('api/artikli/<int:rm_id>/', ArtiklDetailView.as_view(), name='api-artikl-detail'),
    path('api/artikli/<int:rm_id>/image-46x75/', ArtiklImage46x75View.as_view(), name='api-artikl-image-46x75'),
    path('api/artikli/<int:rm_id>/image-125x200/', ArtiklImage125x200View.as_view(), name='api-artikl-image-125x200'),
    path('api/drink-categories/', DrinkCategoryListView.as_view(), name='api-drink-category-list'),
    path('api/drink-categories/<int:pk>/', DrinkCategoryDetailView.as_view(), name='api-drink-category-detail'),
    path('api/representations/', RepresentationListView.as_view(), name='api-representation-list'),
    path('api/representations/<int:pk>/', RepresentationDetailView.as_view(), name='api-representation-detail'),
    path('api/representation-reasons/', RepresentationReasonListView.as_view(), name='api-representation-reason-list'),
    path('api/representation-reasons/<int:pk>/', RepresentationReasonDetailView.as_view(), name='api-representation-reason-detail'),
    path('api/sales/import-remaris/', RemarisImportView.as_view(), name='api-sales-import-remaris'),
    path('api/units/', UnitOfMeasureListView.as_view(), name='api-unit-list'),
    path('api/inventories/', InventoryListCreateView.as_view(), name='api-inventory-list'),
    path('api/inventories/<int:pk>/', InventoryDetailView.as_view(), name='api-inventory-detail'),
    path('api/inventories/public/<str:token>/', InventoryPublicDetailView.as_view(), name='api-inventory-public-detail'),
    path('api/inventories/public/<str:token>/submit/', InventoryPublicSubmitView.as_view(), name='api-inventory-public-submit'),
    path('api/warehouses/', WarehouseIdListView.as_view(), name='api-warehouse-list'),
    path('api/warehouses/sync/', WarehouseStockSyncView.as_view(), name='api-warehouse-sync'),
    path("api/supplier-returns/", SupplierReturnListCreateView.as_view(), name="api-supplier-return-list"),
    path("api/supplier-returns/<int:pk>/", SupplierReturnDetailView.as_view(), name="api-supplier-return-detail"),
    path("api/supplier-returns/<int:pk>/post/", SupplierReturnPostView.as_view(), name="api-supplier-return-post"),
    path("api/supplier-return-items/", SupplierReturnItemListCreateView.as_view(), name="api-supplier-return-item-list"),
    path("api/supplier-return-items/<int:pk>/", SupplierReturnItemDetailView.as_view(), name="api-supplier-return-item-detail"),
    path('api/inventory-items/', InventoryItemListCreateView.as_view(), name='api-inventory-item-list'),
    path('api/inventory-items/<int:pk>/', InventoryItemDetailView.as_view(), name='api-inventory-item-detail'),
    path('api/purchase-orders/', PurchaseOrderListCreateView.as_view(), name='api-purchase-order-list'),
    path('api/purchase-orders/<int:pk>/', PurchaseOrderDetailView.as_view(), name='api-purchase-order-detail'),
    path('api/purchase-orders/<int:pk>/send/', PurchaseOrderSendView.as_view(), name='api-purchase-order-send'),
    path('api/purchase-orders/<int:pk>/warehouse-inputs/', PurchaseOrderWarehouseInputCreateView.as_view(), name='api-purchase-order-warehouse-input-create'),
    path('api/purchase-orders/<int:order_id>/items/', PurchaseOrderItemListCreateView.as_view(), name='api-purchase-order-item-list'),
    path('api/warehouse-inputs/<int:pk>/create-supplier-invoice/', WarehouseInputCreateSupplierInvoiceView.as_view(), name='api-warehouse-input-create-supplier-invoice'),
    path('api/supplier-invoices/<int:pk>/post/', SupplierInvoicePostView.as_view(), name='api-supplier-invoice-post'),
    path('api/purchase-order-items/<int:pk>/', PurchaseOrderItemDetailView.as_view(), name='api-purchase-order-item-detail'),
    path('api/purchase-order-items/<int:pk>/price/', PurchaseOrderItemPriceUpdateView.as_view(), name='api-purchase-order-item-price-update'),
    path('api/suppliers/', SupplierListView.as_view(), name='api-supplier-list'),
    path('api/payment-types/', PaymentTypeListView.as_view(), name='api-payment-type-list'),
    path('api/suppliers/<int:supplier_id>/artikli/', SupplierArtiklListView.as_view(), name='api-supplier-artikl-list'),
    path("api/accounting/cash-ledger/", CashLedgerView.as_view(), name="api-cash-ledger"),
    path("api/operations/shifts/", ShiftListCreateView.as_view(), name="api-shift-list-create"),
    path("api/operations/shifts/<int:shift_id>/cash-count/", ShiftCashCountCreateView.as_view(), name="api-shift-cash-count"),
    path("api/operations/shifts/<int:shift_id>/cash-summary/", ShiftCashSummaryView.as_view(), name="api-shift-cash-summary"),
    path("api/pos/pin/verify/", PosPinVerifyView.as_view(), name="api-pos-pin-verify"),
    path("api/pos/pin/login/", PosPinLoginView.as_view(), name="api-pos-pin-login"),
    path("api/pos/fiscalize-invoice/", PosFiscalizeInvoiceView.as_view(), name="api-pos-fiscalize-invoice"),
    path("api/pos/receipts/", PosReceiptCreateView.as_view(), name="api-pos-receipt-create"),
    path("api/pos/receipts/<int:receipt_id>/fiscalize/", PosReceiptFiscalizeView.as_view(), name="api-pos-receipt-fiscalize"),
    path("api/pos/receipts/<int:receipt_id>/storno/", PosReceiptStornoView.as_view(), name="api-pos-receipt-storno"),
    path("api/pos/receipts/<int:receipt_id>/print/", PosReceiptPrintView.as_view(), name="api-pos-receipt-print"),
    path("api/pos/devices/", PosListCreateView.as_view(), name="api-pos-list"),
    path("api/pos/devices/<int:pos_id>/", PosDetailView.as_view(), name="api-pos-detail"),
    path("api/pos/shift/turnover/", PosShiftTurnoverView.as_view(), name="api-pos-shift-turnover"),
    path("api/pos/shift/close/", PosShiftCloseView.as_view(), name="api-pos-shift-close"),
    path("api/pos/shift/expense/", PosShiftExpenseView.as_view(), name="api-pos-shift-expense"),
    path("api/pos/shift/cash-expected/", PosShiftCashExpectedView.as_view(), name="api-pos-shift-cash-expected"),
    path("api/pos/shift/cash-handover/", PosShiftCashHandoverView.as_view(), name="api-pos-shift-cash-handover"),
    path("api/pos/invoices/payment-flags/", PosInvoicePaymentFlagView.as_view(), name="api-pos-invoices-payment-flags"),
    path("api/pos/printers/sync/", PosPrinterSyncView.as_view(), name="api-pos-printers-sync"),
    path("api/pos/printers/", PosPrinterListView.as_view(), name="api-pos-printers-list"),
    path(
        "api/pos/devices/<str:device_id>/printer-selection/",
        PosDevicePrinterSelectionView.as_view(),
        name="api-pos-device-printer-selection",
    ),
    path("api/pos/active-layout/", PosActiveLayoutView.as_view(), name="api-pos-active-layout"),
    path("api/pos/layouts/allowed/", PosAllowedLayoutsView.as_view(), name="api-pos-allowed-layouts"),
    path("api/pos/table-status/", PosTableStatusView.as_view(), name="api-pos-table-status"),
    path("api/pos/checks/", PosChecksView.as_view(), name="api-pos-checks"),
    path("api/pos/checks/<int:check_id>/close/", PosCheckCloseView.as_view(), name="api-pos-check-close"),
    path("api/pos/checks/<int:check_id>/send-to-bar/", PosCheckSendToBarView.as_view(), name="api-pos-check-send-to-bar"),
    path("api/pos/checks/<int:check_id>/prepare-settlement/", PosCheckPrepareSettlementView.as_view(), name="api-pos-check-prepare-settlement"),
    path("api/pos/checks/<int:check_id>/settlement-state/", PosCheckSettlementStateView.as_view(), name="api-pos-check-settlement-state"),
    path("api/pos/checks/<int:check_id>/round-state/", PosCheckRoundStateView.as_view(), name="api-pos-check-round-state"),
    path("api/pos/checks/<int:check_id>/pay-card/confirm/", PosCheckPayCardConfirmView.as_view(), name="api-pos-check-pay-card-confirm"),
    path("api/pos/checks/<int:check_id>/settlements/parts/<int:part_id>/pay-cash/", PosSettlementPartPayCashView.as_view(), name="api-pos-settlement-part-pay-cash"),
    path("api/pos/checks/<int:check_id>/settlements/parts/<int:part_id>/pay-card/confirm/", PosSettlementPartPayCardConfirmView.as_view(), name="api-pos-settlement-part-pay-card-confirm"),
    path("api/pos/checks/<int:check_id>/items/", PosCheckItemsView.as_view(), name="api-pos-check-items"),
    path("api/pos/checks/<int:check_id>/issue-receipt/", PosCheckIssueReceiptView.as_view(), name="api-pos-check-issue-receipt"),
    path(
        "api/pos/checks/<int:check_id>/receipts/<int:receipt_id>/fiscalize/",
        PosCheckReceiptFiscalizeView.as_view(),
        name="api-pos-check-receipt-fiscalize",
    ),
    path("api/pos/check-items/<int:item_id>/", PosCheckItemDetailView.as_view(), name="api-pos-check-item-detail"),
    path("api/pos/check-items/<int:item_id>/storno/", PosCheckItemStornoView.as_view(), name="api-pos-check-item-storno"),
    path("api/pos/check-items/<int:item_id>/gratis/", PosCheckItemGratisView.as_view(), name="api-pos-check-item-gratis"),
    path("api/pos/check-items/<int:item_id>/otpis/", PosCheckItemOtpisView.as_view(), name="api-pos-check-item-otpis"),
    path("api/pos/runtime-mode/", PosRuntimeModeView.as_view(), name="api-pos-runtime-mode"),
    path("api/pos/products/search/", PosProductSearchView.as_view(), name="api-pos-product-search"),
    path("api/pos/products/<int:artikl_id>/modifiers/", PosProductModifiersView.as_view(), name="api-pos-product-modifiers"),
    path("api/pos/products/<int:artikl_id>/bundle-price/", PosProductBundlePriceView.as_view(), name="api-pos-product-bundle-price"),
    path("api/pos/drink-categories/display/", PosDrinkCategoriesDisplayView.as_view(), name="api-pos-drink-categories-display"),
    path("api/ai/query/", AIQueryView.as_view(), name="api-ai-query"),
    path("ai/", AiSearchView.as_view(), name="ai-search"),
    path("api/mailbox/sync/", MailboxSyncView.as_view(), name="api-mailbox-sync"),
    path("api/mailbox/messages/", MailMessageListView.as_view(), name="api-mailbox-messages"),
    path("api/mailbox/messages/<int:pk>/", MailMessageDetailView.as_view(), name="api-mailbox-message-detail"),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()

# Serve uploaded media via Django when no separate media server is configured.
if settings.MEDIA_ROOT:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
