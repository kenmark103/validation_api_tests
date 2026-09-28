"""
Generates a synthetic 'orders' dataset for the mock API layer.
Deterministic (seeded) so the underlying truth is reproducible,
independent of the *runtime* flakiness/rate-limiting which is randomized per-request.
"""
import random
from datetime import datetime, timedelta

SEED = 42
TOTAL_ORDERS = 4200

STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled", "refunded"]
PRODUCTS = [
    ("SKU-1001", "Wireless Mouse", 19.99),
    ("SKU-1002", "Mechanical Keyboard", 79.50),
    ("SKU-1003", "USB-C Hub", 24.00),
    ("SKU-1004", "27in Monitor", 210.00),
    ("SKU-1005", "Laptop Stand", 34.90),
    ("SKU-1006", "Webcam 1080p", 45.00),
    ("SKU-1007", "Noise Cancelling Headset", 129.99),
    ("SKU-1008", "Desk Mat", 15.00),
    ("SKU-1009", "External SSD 1TB", 89.00),
    ("SKU-1010", "Ergonomic Chair", 310.00),
]
FIRST_NAMES = ["Amina", "Brian", "Wanjiru", "Kevin", "Njeri", "Otieno", "Mercy",
               "Kiptoo", "Faith", "Dennis", "Achieng", "Peter", "Grace", "Mutua"]
LAST_NAMES = ["Kamau", "Odhiambo", "Mwangi", "Chebet", "Njoroge", "Wanjala",
              "Kariuki", "Auma", "Rotich", "Nyambura"]


def generate_orders():
    rng = random.Random(SEED)
    base_time = datetime(2026, 1, 1)
    orders = []
    for i in range(1, TOTAL_ORDERS + 1):
        sku, name, price = rng.choice(PRODUCTS)
        qty = rng.randint(1, 6)
        created = base_time + timedelta(minutes=rng.randint(0, 60 * 24 * 200))
        # some orders updated later than created (normal lifecycle)
        updated = created + timedelta(hours=rng.randint(0, 96))
        order = {
            "order_id": i,
            "customer_id": rng.randint(1000, 1999),
            "customer_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "product_sku": sku,
            "product_name": name,
            "unit_price": price,
            "quantity": qty,
            "total_amount": round(price * qty, 2),
            "status": rng.choice(STATUSES),
            "created_at": created.isoformat() + "Z",
            "updated_at": updated.isoformat() + "Z",
        }
        orders.append(order)
    return orders


# Generated once at import time; the API layer treats this as the source of truth.
ORDERS = generate_orders()
ORDERS_BY_ID = {o["order_id"]: o for o in ORDERS}
