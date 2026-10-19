import logging
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from app.models import Order, OrderStatusHistory, ORDER_STATUS_CHOICES
from app.services.inventory import restore_order_stock

logger = logging.getLogger(__name__)


class FulfillmentTransitionError(ValidationError):
    """Raised when an invalid order fulfillment transition is requested."""
    pass


# Explicit valid state transition matrix
# Terminal states: DELIVERED, CANCELLED
VALID_TRANSITIONS = {
    'PENDING': {'ACCEPTED', 'CANCELLED'},
    'ACCEPTED': {'PROCESSING', 'CANCELLED'},
    'PROCESSING': {'READY'},
    'READY': {'SHIPPED'},
    'SHIPPED': {'DELIVERED'},
    'DELIVERED': set(),
    'CANCELLED': set(),
}


def can_transition_order(order, target_status, user=None):
    """
    Validates whether an order is eligible to transition to target_status.
    Returns (allowed: bool, reason: str).
    """
    current_status = order.status

    if current_status == target_status:
        return False, f"Order #{order.order_number} is already in '{order.get_status_display()}' status."

    if current_status in ('DELIVERED', 'CANCELLED'):
        return False, f"Order #{order.order_number} is in terminal status '{order.get_status_display()}' and cannot be modified."

    allowed_targets = VALID_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        target_display = dict(ORDER_STATUS_CHOICES).get(target_status, target_status)
        return False, f"Invalid status transition from '{order.get_status_display()}' to '{target_display}'."

    # Guardrails for cancellation
    if target_status == 'CANCELLED':
        if order.payment_status == 'PAID':
            return False, "Paid orders cannot be cancelled without an explicit refund workflow."
        if current_status in ('SHIPPED', 'DELIVERED'):
            return False, "Orders that are already shipped or delivered cannot be cancelled."

    return True, "Transition allowed."


def transition_order_status(order, target_status, user=None, notes='', courier_name='', tracking_number=''):
    """
    Atomically transitions an order to target_status.
    
    Guarantees:
    - Atomicity and serialized row lock via select_for_update() inside transaction.atomic().
    - Validates against explicit valid transitions matrix.
    - Updates relevant delivery timestamps (shipped_at, delivered_at, cancelled_at).
    - Records courier_name and tracking_number when shipping.
    - Restores inventory safely and idempotently if transitioning to CANCELLED.
    - Never re-deducts inventory when advancing fulfillment stages.
    - Keeps payment_status completely separate from fulfillment status.
    - Creates an OrderStatusHistory audit entry.
    """
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)

        allowed, reason = can_transition_order(locked_order, target_status, user=user)
        if not allowed:
            logger.warning(
                f"Fulfillment transition rejected for Order #{locked_order.order_number}: {reason}"
            )
            raise FulfillmentTransitionError(reason)

        old_status = locked_order.status
        now = timezone.now()

        update_fields = ['status', 'updated_at']

        if target_status == 'SHIPPED':
            locked_order.shipped_at = now
            update_fields.append('shipped_at')
            if courier_name:
                locked_order.courier_name = courier_name.strip()
                update_fields.append('courier_name')
            if tracking_number:
                locked_order.tracking_number = tracking_number.strip()
                update_fields.append('tracking_number')

        elif target_status == 'DELIVERED':
            locked_order.delivered_at = now
            update_fields.append('delivered_at')

        elif target_status == 'CANCELLED':
            locked_order.cancelled_at = now
            update_fields.append('cancelled_at')
            if notes:
                locked_order.cancellation_reason = notes.strip()
                update_fields.append('cancellation_reason')
            # Restore inventory using existing inventory service
            restore_order_stock(
                locked_order,
                user=user,
                reason='ORDER_CANCELLED',
                notes=notes or f"Order #{locked_order.order_number} cancelled"
            )

        locked_order.status = target_status
        locked_order.save(update_fields=list(set(update_fields)))

        # Create audit trail entry
        OrderStatusHistory.objects.create(
            order=locked_order,
            from_status=old_status,
            to_status=target_status,
            changed_by=user,
            notes=notes
        )

        from app.services.notification import notify_order_status_change
        order_to_notify = locked_order
        status_to_notify = target_status
        notes_to_notify = notes
        user_to_notify = user
        transaction.on_commit(
            lambda: notify_order_status_change(
                order_to_notify,
                status_to_notify,
                notes=notes_to_notify,
                user=user_to_notify
            )
        )

        logger.info(
            f"Order #{locked_order.order_number} successfully transitioned: "
            f"{old_status} -> {target_status} by {user.username if user else 'System'}."
        )
        return locked_order

