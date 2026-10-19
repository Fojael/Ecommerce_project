import logging
from django.db import transaction
from django.core.exceptions import ValidationError
from app.models import Product, StockAdjustment, Order

logger = logging.getLogger(__name__)


class InsufficientStockError(Exception):
    def __init__(self, product, requested, available):
        self.product = product
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for '{product.title}'. Requested: {requested}, Available: {available}"
        )


def adjust_stock(product, quantity_change, reason='MANUAL_CORRECTION', user=None, notes='', order=None):
    """
    Atomically adjusts a product's stock and creates a StockAdjustment audit record.
    Rejects any adjustment that would result in negative stock.
    
    Note on Concurrency:
    Uses select_for_update() inside transaction.atomic(). On PostgreSQL, this acquires
    an exclusive row-level lock on the Product row. On SQLite, concurrency is managed
    via database-level transaction locking (SQLite does not support row-level locking).
    """
    if quantity_change == 0:
        return product

    with transaction.atomic():
        locked_product = Product.objects.select_for_update().get(pk=product.pk)
        new_stock = locked_product.stock + quantity_change
        if new_stock < 0:
            raise ValidationError(
                f"Cannot adjust stock by {quantity_change}: resulting stock would be negative ({new_stock}). Current: {locked_product.stock}."
            )

        locked_product.stock = new_stock
        locked_product.save(update_fields=['stock'])

        StockAdjustment.objects.create(
            product=locked_product,
            quantity_change=quantity_change,
            resulting_stock=new_stock,
            reason=reason,
            notes=notes,
            user=user,
            order=order
        )

        logger.info(
            f"Stock adjusted for '{locked_product.title}' (ID {locked_product.id}): "
            f"change={quantity_change}, resulting_stock={new_stock}, reason={reason}"
        )
        return locked_product


def deduct_order_stock(order, user=None):
    """
    Atomically validates and deducts stock for all items in an Order.
    Pre-validates every item to prevent partial stock changes if one item is out of stock.
    Sets order.stock_deducted = True.
    Idempotent: if stock was already deducted for this order, does nothing.
    """
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        if locked_order.stock_deducted:
            logger.info(f"Order #{locked_order.order_number} stock already deducted; skipping.")
            return

        items = list(locked_order.items.select_related('product').all())

        # Pre-validation phase: verify sufficient stock for ALL items
        for item in items:
            product = Product.objects.select_for_update().get(pk=item.product.pk)
            if product.stock < item.quantity:
                logger.warning(
                    f"Order #{locked_order.order_number} failed stock check: "
                    f"'{product.title}' requested={item.quantity}, available={product.stock}"
                )
                raise InsufficientStockError(product, item.quantity, product.stock)

        # Deduction phase: apply adjustments
        for item in items:
            adjust_stock(
                product=item.product,
                quantity_change=-item.quantity,
                reason='ORDER_PLACED',
                user=user,
                notes=f"Order #{locked_order.order_number}",
                order=locked_order
            )

        locked_order.stock_deducted = True
        locked_order.save(update_fields=['stock_deducted', 'updated_at'])
        logger.info(f"Stock successfully deducted for Order #{locked_order.order_number}")


def restore_order_stock(order, user=None, reason='ORDER_CANCELLED', notes=''):
    """
    Restores stock for an Order whose stock was previously deducted upon cancellation.
    Sets order.status = 'CANCELLED' and order.stock_restored = True.
    Idempotent: if stock was already restored for this order, does nothing.
    """
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)

        # Idempotency check
        if locked_order.stock_restored:
            logger.warning(
                f"Stock for Order #{locked_order.order_number} has already been restored; skipping duplicate restoration."
            )
            return False, "Stock has already been restored for this order."

        if not locked_order.stock_deducted:
            # Order stock was never deducted
            locked_order.status = 'CANCELLED'
            locked_order.save(update_fields=['status', 'updated_at'])
            logger.info(f"Order #{locked_order.order_number} marked CANCELLED (no stock had been deducted).")
            return True, "Order marked as cancelled (no stock had been deducted)."

        items = list(locked_order.items.select_related('product').all())
        for item in items:
            adjust_stock(
                product=item.product,
                quantity_change=item.quantity,
                reason=reason,
                user=user,
                notes=notes or f"Restored from cancelled Order #{locked_order.order_number}",
                order=locked_order
            )

        locked_order.status = 'CANCELLED'
        locked_order.stock_restored = True
        locked_order.save(update_fields=['status', 'stock_restored', 'updated_at'])
        logger.info(f"Stock successfully restored for Order #{locked_order.order_number}")
        return True, "Order cancelled and stock restored successfully."

