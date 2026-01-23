from django.urls import path

from .views import confirm_purchase_order

app_name = "orders"

urlpatterns = [
    path("confirm/<str:token>/", confirm_purchase_order, name="purchase-order-confirm"),
]
