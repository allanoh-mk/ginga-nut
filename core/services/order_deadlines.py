from datetime import timedelta

from orders.models import Order

DRAFT_FUNDING_LIFETIME = timedelta(minutes=30)
FUNDED_VENDOR_RESPONSE_LIFETIME = timedelta(hours=12)
FINALIZATION_LIFETIMES = {
    Order.DeliveryLane.DIGITAL: timedelta(hours=2),
    Order.DeliveryLane.CITY: timedelta(hours=24),
    Order.DeliveryLane.DOMESTIC: timedelta(days=7),
    Order.DeliveryLane.CROSS_BORDER: timedelta(days=14),
}
