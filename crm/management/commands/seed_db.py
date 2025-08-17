import os
import django
from decimal import Decimal

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.models import Customer, Product, Order


class Command(BaseCommand):
    help = "Seed the database with sample CRM data (customers, products, and optional sample order)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Create entries even if some exist (idempotent get_or_create is still used).",
        )
        parser.add_argument(
            "--with-order",
            action="store_true",
            help="Also create a demo order linking a customer and products.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing data in CRM models before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        force = options["force"]
        with_order = options["with_order"]
        reset = options["reset"]

        if reset:
            self.stdout.write(self.style.WARNING("Resetting CRM data…"))
            # Order depends on relations: clear Order first, then Product/Customer
            Order.objects.all().delete()
            Product.objects.all().delete()
            Customer.objects.all().delete()

        # Seed Customers (idempotent via get_or_create)
        customers_data = [
            {"name": "Alice", "email": "alice@example.com", "phone": "+1234567890"},
            {"name": "Bob", "email": "bob@example.com", "phone": "123-456-7890"},
            {"name": "Carol", "email": "carol@example.com", "phone": None},
        ]

        created_customers = []
        for data in customers_data:
            obj, created = Customer.objects.get_or_create(
                email=data["email"],
                defaults={"name": data["name"], "phone": data["phone"]},
            )
            if not created and force:
                obj.name = data["name"]
                obj.phone = data["phone"]
                obj.save(update_fields=["name", "phone"])
                created = True  # treat as updated
            created_customers.append(obj)

        # Seed Products
        products_data = [
            {"name": "Laptop", "price": Decimal("999.99"), "stock": 10},
            {"name": "Mouse", "price": Decimal("19.99"), "stock": 100},
            {"name": "Keyboard", "price": Decimal("49.99"), "stock": 50},
        ]

        created_products = []
        for data in products_data:
            obj, created = Product.objects.get_or_create(
                name=data["name"],
                defaults={"price": data["price"], "stock": data["stock"]},
            )
            if not created and force:
                obj.price = data["price"]
                obj.stock = data["stock"]
                obj.save(update_fields=["price", "stock"])
                created = True
            created_products.append(obj)

        self.stdout.write(self.style.SUCCESS(f"Customers ready: {len(created_customers)}"))
        self.stdout.write(self.style.SUCCESS(f"Products ready: {len(created_products)}"))

        if with_order:
            # Create a demo order for the first customer with first two products
            if not created_customers or len(created_products) < 2:
                raise CommandError("Not enough data to create demo order.")
            customer = created_customers[0]
            products = created_products[:2]

            order = Order.objects.create(customer=customer)
            order.products.set(products)
            # Compute total_amount precisely
            total = sum((p.price for p in products), start=Decimal("0.00"))
            order.total_amount = total
            order.save(update_fields=["total_amount"])

            self.stdout.write(
                self.style.SUCCESS(
                    f"Demo order created: #{order.id} for {customer.name} "
                    f"({len(products)} products, total={order.total_amount})"
                )
            )

        self.stdout.write(self.style.SUCCESS("Seeding complete."))


# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "graphql_crm.settings")
# django.setup()

# from crm.models import Customer, Product  # noqa

# def run():
#     # Customers
#     Customer.objects.get_or_create(name="Alice", email="alice@example.com", defaults={"phone": "+1234567890"})
#     Customer.objects.get_or_create(name="Bob", email="bob@example.com", defaults={"phone": "123-456-7890"})

#     # Products
#     Product.objects.get_or_create(name="Laptop", defaults={"price": Decimal("999.99"), "stock": 10})
#     Product.objects.get_or_create(name="Mouse", defaults={"price": Decimal("19.99"), "stock": 100})
#     Product.objects.get_or_create(name="Keyboard", defaults={"price": Decimal("49.99"), "stock": 50})

#     print("Seeded customers and products.")

# if __name__ == "__main__":
#     run()
