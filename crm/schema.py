import re
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

import graphene
from graphene_django import DjangoObjectType

from .models import Customer, Product, Order


# ============ GraphQL Types ============
class CustomerType(DjangoObjectType):
    class Meta:
        model = Customer
        fields = ("id", "name", "email", "phone")


class ProductType(DjangoObjectType):
    class Meta:
        model = Product
        fields = ("id", "name", "price", "stock")


class OrderType(DjangoObjectType):
    class Meta:
        model = Order
        fields = ("id", "customer", "products", "total_amount", "order_date")


# ============ Inputs ============
class CustomerInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    email = graphene.String(required=True)
    phone = graphene.String()


class ProductInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    price = graphene.Float(required=True)  # parsed to Decimal server-side
    stock = graphene.Int()  # default handled in mutation


class OrderInput(graphene.InputObjectType):
    customer_id = graphene.ID(required=True)          # GraphQL: customerId
    product_ids = graphene.List(graphene.ID, required=True)  # GraphQL: productIds
    order_date = graphene.DateTime()                  # optional


# ============ Helpers ============
PHONE_RE = re.compile(r'^(\+\d{7,15}|\d{3}-\d{3}-\d{4})$')


def _valid_phone(phone: str) -> bool:
    if not phone:
        return True
    return bool(PHONE_RE.match(phone))


# ============ Query ============
class Query(graphene.ObjectType):
    hello = graphene.String(default_value="Hello, GraphQL!")

    # Optional convenience queries (nice for sanity checks)
    customers = graphene.List(CustomerType)
    products = graphene.List(ProductType)
    orders = graphene.List(OrderType)

    def resolve_customers(self, info):
        return Customer.objects.all()

    def resolve_products(self, info):
        return Product.objects.all()

    def resolve_orders(self, info):
        return Order.objects.select_related("customer").prefetch_related("products").all()


# ============ Mutations ============
class CreateCustomer(graphene.Mutation):
    class Arguments:
        input = CustomerInput(required=True)

    customer = graphene.Field(CustomerType)
    message = graphene.String()
    errors = graphene.List(graphene.String)

    @staticmethod
    def mutate(root, info, input: CustomerInput):
        errors = []

        # Email unique
        if Customer.objects.filter(email=input.email).exists():
            errors.append("Email already exists.")

        # Phone format
        if not _valid_phone(input.phone or ""):
            errors.append("Invalid phone format. Use +1234567890 or 123-456-7890.")

        if errors:
            return CreateCustomer(customer=None, message="Failed", errors=errors)

        customer = Customer.objects.create(
            name=input.name,
            email=input.email,
            phone=input.phone or None,
        )
        return CreateCustomer(customer=customer, message="Customer created successfully.", errors=[])


class BulkCreateCustomers(graphene.Mutation):
    class Arguments:
        input = graphene.List(CustomerInput, required=True)

    customers = graphene.List(CustomerType)        # successfully created
    errors = graphene.List(graphene.String)        # row-scoped errors (partial success)

    @staticmethod
    def mutate(root, info, input):
        created = []
        errors = []

        # Single outer transaction + savepoints per row for partial success
        with transaction.atomic():
            for idx, data in enumerate(input):
                sp = transaction.savepoint()
                try:
                    row_errs = []
                    if not data.name:
                        row_errs.append(f"Row {idx}: Name is required.")
                    if not data.email:
                        row_errs.append(f"Row {idx}: Email is required.")
                    elif Customer.objects.filter(email=data.email).exists():
                        row_errs.append(f"Row {idx}: Email already exists ({data.email}).")
                    if not _valid_phone(data.phone or ""):
                        row_errs.append(f"Row {idx}: Invalid phone format ({data.phone}).")

                    if row_errs:
                        errors.extend(row_errs)
                        transaction.savepoint_rollback(sp)
                        continue

                    c = Customer.objects.create(
                        name=data.name,
                        email=data.email,
                        phone=data.phone or None,
                    )
                    created.append(c)
                    transaction.savepoint_commit(sp)
                except Exception as e:
                    errors.append(f"Row {idx}: {str(e)}")
                    transaction.savepoint_rollback(sp)

        return BulkCreateCustomers(customers=created, errors=errors)


class CreateProduct(graphene.Mutation):
    class Arguments:
        input = ProductInput(required=True)

    product = graphene.Field(ProductType)
    errors = graphene.List(graphene.String)

    @staticmethod
    def mutate(root, info, input: ProductInput):
        errs = []

        # Validate name
        if not input.name:
            errs.append("Name is required.")

        # Validate price as Decimal
        price = None
        try:
            price = Decimal(str(input.price))
            if price <= Decimal("0"):
                errs.append("Price must be positive.")
        except Exception:
            errs.append("Price must be a valid decimal.")

        # Validate stock
        stock = input.stock if input.stock is not None else 0
        if stock < 0:
            errs.append("Stock cannot be negative.")

        if errs:
            return CreateProduct(product=None, errors=errs)

        product = Product.objects.create(name=input.name, price=price, stock=stock)
        return CreateProduct(product=product, errors=[])


class CreateOrder(graphene.Mutation):
    class Arguments:
        input = OrderInput(required=True)

    order = graphene.Field(OrderType)
    errors = graphene.List(graphene.String)

    @staticmethod
    def mutate(root, info, input: OrderInput):
        # Validate customer exists
        try:
            customer = Customer.objects.get(pk=input.customer_id)
        except Customer.DoesNotExist:
            return CreateOrder(order=None, errors=[f"Invalid customer ID: {input.customer_id}"])

        # Validate product list
        if not input.product_ids:
            return CreateOrder(order=None, errors=["At least one product must be selected."])

        products_qs = Product.objects.filter(id__in=input.product_ids)
        found_ids = set(str(p.id) for p in products_qs)
        missing = [pid for pid in input.product_ids if str(pid) not in found_ids]
        if missing:
            return CreateOrder(order=None, errors=[f"Invalid product ID(s): {', '.join(map(str, missing))}"])

        # Create order atomically and compute total with Decimal-safe aggregation
        odt = input.order_date or timezone.now()
        with transaction.atomic():
            order = Order.objects.create(customer=customer, order_date=odt)
            order.products.set(products_qs)
            total = products_qs.aggregate(s=Sum("price"))["s"] or Decimal("0.00")
            order.total_amount = total
            order.save(update_fields=["total_amount"])

        return CreateOrder(order=order, errors=[])
    
# crm/schema.py
import graphene
from graphene import relay
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField

from .models import Customer, Product, Order
from .filters import CustomerFilter, ProductFilter, OrderFilter


# ---------- Node Types ----------
class CustomerNode(DjangoObjectType):
    class Meta:
        model = Customer
        interfaces = (relay.Node,)
        fields = ("id", "name", "email", "phone", "created_at")


class ProductNode(DjangoObjectType):
    class Meta:
        model = Product
        interfaces = (relay.Node,)
        fields = ("id", "name", "price", "stock")


class OrderNode(DjangoObjectType):
    class Meta:
        model = Order
        interfaces = (relay.Node,)
        fields = ("id", "customer", "products", "total_amount", "order_date")


# ---------- Optional "filter" input wrappers (for nicer API) ----------
class CustomerFilterInput(graphene.InputObjectType):
    nameIcontains = graphene.String()
    emailIcontains = graphene.String()
    createdAtGte = graphene.DateTime()
    createdAtLte = graphene.DateTime()
    phonePattern = graphene.String()  # e.g., "+1"


class ProductFilterInput(graphene.InputObjectType):
    nameIcontains = graphene.String()
    priceGte = graphene.Float()
    priceLte = graphene.Float()
    stockGte = graphene.Int()
    stockLte = graphene.Int()


class OrderFilterInput(graphene.InputObjectType):
    totalAmountGte = graphene.Float()
    totalAmountLte = graphene.Float()
    orderDateGte = graphene.DateTime()
    orderDateLte = graphene.DateTime()
    customerName = graphene.String()
    productName = graphene.String()
    productId = graphene.ID()


def _apply_ordering(qs, order_by_list):
    if order_by_list:
        # Support multiple comma-separated or list values
        if isinstance(order_by_list, str):
            order_by_list = [order_by_list]
        qs = qs.order_by(*order_by_list)
    return qs


# ---------- Query ----------
class Query(graphene.ObjectType):
    # Filtered, paginated connections (auto-args from FilterSets)
    all_customers = DjangoFilterConnectionField(
        CustomerNode,
        filterset_class=CustomerFilter,
        order_by=graphene.List(graphene.String),     # e.g., ["-created_at", "name"]
        filter=CustomerFilterInput()                 # Optional convenience input
    )
    all_products = DjangoFilterConnectionField(
        ProductNode,
        filterset_class=ProductFilter,
        order_by=graphene.List(graphene.String),
        filter=ProductFilterInput()
    )
    all_orders = DjangoFilterConnectionField(
        OrderNode,
        filterset_class=OrderFilter,
        order_by=graphene.List(graphene.String),
        filter=OrderFilterInput()
    )

    # Keep your simple hello field (and any other fields you already had)
    hello = graphene.String(default_value="Hello, GraphQL!")

    # Resolvers: allow either (1) auto-generated filter args or (2) our "filter" input wrapper,
    # plus apply custom ordering.
    def resolve_all_customers(self, info, **kwargs):
        qs = Customer.objects.all()
        # Apply "filter" input if provided (map to FilterSet keys)
        filt = kwargs.pop("filter", None)
        if filt:
            data = {}
            if filt.get("nameIcontains"): data["name"] = filt["nameIcontains"]
            if filt.get("emailIcontains"): data["email"] = filt["emailIcontains"]
            if filt.get("createdAtGte"): data["created_at__gte"] = filt["createdAtGte"]
            if filt.get("createdAtLte"): data["created_at__lte"] = filt["createdAtLte"]
            if filt.get("phonePattern"): data["phone_pattern"] = filt["phonePattern"]
            from .filters import CustomerFilter
            qs = CustomerFilter(data=data, queryset=qs).qs
        # Custom ordering
        qs = _apply_ordering(qs, kwargs.get("order_by"))
        return qs

    def resolve_all_products(self, info, **kwargs):
        qs = Product.objects.all()
        filt = kwargs.pop("filter", None)
        if filt:
            data = {}
            if filt.get("nameIcontains"): data["name"] = filt["nameIcontains"]
            if filt.get("priceGte") is not None: data["price__gte"] = filt["priceGte"]
            if filt.get("priceLte") is not None: data["price__lte"] = filt["priceLte"]
            if filt.get("stockGte") is not None: data["stock__gte"] = filt["stockGte"]
            if filt.get("stockLte") is not None: data["stock__lte"] = filt["stockLte"]
            from .filters import ProductFilter
            qs = ProductFilter(data=data, queryset=qs).qs
        qs = _apply_ordering(qs, kwargs.get("order_by"))
        return qs

    def resolve_all_orders(self, info, **kwargs):
        qs = Order.objects.select_related("customer").prefetch_related("products").all()
        filt = kwargs.pop("filter", None)
        if filt:
            data = {}
            if filt.get("totalAmountGte") is not None: data["total_amount__gte"] = filt["totalAmountGte"]
            if filt.get("totalAmountLte") is not None: data["total_amount__lte"] = filt["totalAmountLte"]
            if filt.get("orderDateGte"): data["order_date__gte"] = filt["orderDateGte"]
            if filt.get("orderDateLte"): data["order_date__lte"] = filt["orderDateLte"]
            if filt.get("customerName"): data["customer_name"] = filt["customerName"]
            if filt.get("productName"): data["product_name"] = filt["productName"]
            if filt.get("productId"): data["product_id"] = filt["productId"]
            from .filters import OrderFilter
            qs = OrderFilter(data=data, queryset=qs).qs
        qs = _apply_ordering(qs, kwargs.get("order_by"))
        return qs


class Mutation(graphene.ObjectType):
    create_customer = CreateCustomer.Field()
    bulk_create_customers = BulkCreateCustomers.Field()
    create_product = CreateProduct.Field()
    create_order = CreateOrder.Field()

schema = graphene.Schema(query=Query, mutation=Mutation)

