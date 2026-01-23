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
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from .api_views import CsrfView, LoginView, LogoutView, MeView
from mailbox_app.api_views import MailboxSyncView
from mailbox_app.api import MailMessageDetailView, MailMessageListView
from contacts.api import SupplierListView
from orders.api import (
    PurchaseOrderDetailView,
    PurchaseOrderItemDetailView,
    PurchaseOrderItemListCreateView,
    PurchaseOrderListCreateView,
    PurchaseOrderSendView,
    SupplierArtiklListView,
)
from artikli.api import ArtiklDetailView, ArtiklListView, UnitOfMeasureListView, ArtiklImage46x75View
from stock.api import (
    InventoryDetailView,
    InventoryItemDetailView,
    InventoryItemListCreateView,
    InventoryListCreateView,
    WarehouseIdListView,
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
    path('api/token/', obtain_auth_token, name='api-token'),
    path('api/me/', MeView.as_view(), name='api-me'),
    path('api/artikli/', ArtiklListView.as_view(), name='api-artikl-list'),
    path('api/artikli/<int:rm_id>/', ArtiklDetailView.as_view(), name='api-artikl-detail'),
    path('api/artikli/<int:rm_id>/image-46x75/', ArtiklImage46x75View.as_view(), name='api-artikl-image-46x75'),
    path('api/units/', UnitOfMeasureListView.as_view(), name='api-unit-list'),
    path('api/inventories/', InventoryListCreateView.as_view(), name='api-inventory-list'),
    path('api/inventories/<int:pk>/', InventoryDetailView.as_view(), name='api-inventory-detail'),
    path('api/warehouses/', WarehouseIdListView.as_view(), name='api-warehouse-list'),
    path('api/inventory-items/', InventoryItemListCreateView.as_view(), name='api-inventory-item-list'),
    path('api/inventory-items/<int:pk>/', InventoryItemDetailView.as_view(), name='api-inventory-item-detail'),
    path('api/purchase-orders/', PurchaseOrderListCreateView.as_view(), name='api-purchase-order-list'),
    path('api/purchase-orders/<int:pk>/', PurchaseOrderDetailView.as_view(), name='api-purchase-order-detail'),
    path('api/purchase-orders/<int:pk>/send/', PurchaseOrderSendView.as_view(), name='api-purchase-order-send'),
    path('api/purchase-orders/<int:order_id>/items/', PurchaseOrderItemListCreateView.as_view(), name='api-purchase-order-item-list'),
    path('api/purchase-order-items/<int:pk>/', PurchaseOrderItemDetailView.as_view(), name='api-purchase-order-item-detail'),
    path('api/suppliers/', SupplierListView.as_view(), name='api-supplier-list'),
    path('api/suppliers/<int:supplier_id>/artikli/', SupplierArtiklListView.as_view(), name='api-supplier-artikl-list'),
    path("api/mailbox/sync/", MailboxSyncView.as_view(), name="api-mailbox-sync"),
    path("api/mailbox/messages/", MailMessageListView.as_view(), name="api-mailbox-messages"),
    path("api/mailbox/messages/<int:pk>/", MailMessageDetailView.as_view(), name="api-mailbox-message-detail"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
