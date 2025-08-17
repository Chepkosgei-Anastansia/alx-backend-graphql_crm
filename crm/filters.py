# crm/filters.py
import django_filters as filters
from django.db.models import Q
from .models import Customer, Product, Order


class CustomerFilter(filters.FilterSet):
    # Simple fields
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    email = filters.CharFilter(field_name="email", lookup_expr="icontains")
    # Date range
    created_at__gte = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at__lte = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")
    # Challenge: phone pattern (e.g., starts with +1)
    phone_pattern = filters.CharFilter(method="filter_phone_pattern")

    def filter_phone_pattern(self, queryset, name, value):
        # e.g., "+1"  -> numbers that start with +1
        if value:
            return queryset.filter(phone__startswith=value)
        return queryset

    class Meta:
        model = Customer
        fields = [
            "name",
            "email",
            "created_at__gte",
            "created_at__lte",
            "phone_pattern",
        ]


class ProductFilter(filters.FilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")
    price__gte = filters.NumberFilter(field_name="price", lookup_expr="gte")
    price__lte = filters.NumberFilter(field_name="price", lookup_expr="lte")
    stock__gte = filters.NumberFilter(field_name="stock", lookup_expr="gte")
    stock__lte = filters.NumberFilter(field_name="stock", lookup_expr="lte")
    # Think: low stock (stock < 10) -> use stock__lte=9 in queries, already supported

    class Meta:
        model = Product
        fields = ["name", "price__gte", "price__lte", "stock__gte", "stock__lte"]


class OrderFilter(filters.FilterSet):
    total_amount__gte = filters.NumberFilter(field_name="total_amount", lookup_expr="gte")
    total_amount__lte = filters.NumberFilter(field_name="total_amount", lookup_expr="lte")
    order_date__gte = filters.IsoDateTimeFilter(field_name="order_date", lookup_expr="gte")
    order_date__lte = filters.IsoDateTimeFilter(field_name="order_date", lookup_expr="lte")
    # Related lookups
    customer_name = filters.CharFilter(field_name="customer__name", lookup_expr="icontains")
    product_name = filters.CharFilter(field_name="products__name", lookup_expr="icontains")
    # Challenge: specific product id
    product_id = filters.NumberFilter(method="filter_product_id")

    def filter_product_id(self, queryset, name, value):
        if value is not None:
            return queryset.filter(products__id=value).distinct()
        return queryset

    class Meta:
        model = Order
        fields = [
            "total_amount__gte",
            "total_amount__lte",
            "order_date__gte",
            "order_date__lte",
            "customer_name",
            "product_name",
            "product_id",
        ]
