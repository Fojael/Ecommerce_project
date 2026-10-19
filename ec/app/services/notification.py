import logging
from django.db import transaction, IntegrityError
from django.utils import timezone
from app.models import Notification, Order, ORDER_STATUS_CHOICES
from app.services.email import (
    send_order_placed_email,
    send_order_status_update_email,
    send_payment_confirmed_email,
    send_payment_failed_email,
)

logger = logging.getLogger(__name__)

STATUS_NOTIFICATION_TYPE_MAP = {
    'PENDING': 'ORDER_PLACED',
    'ACCEPTED': 'ORDER_ACCEPTED',
    'PROCESSING': 'ORDER_PROCESSING',
    'READY': 'ORDER_READY',
    'SHIPPED': 'ORDER_SHIPPED',
    'DELIVERED': 'ORDER_DELIVERED',
    'CANCELLED': 'ORDER_CANCELLED',
}


def create_notification(recipient, title, message, notification_type='SYSTEM', order=None, event_key=None):
    """
    Creates an in-app Notification record.
    If event_key is provided and already exists, returns (existing_notification, False).
    Returns (notification, created: bool).
    """
    if event_key:
        existing = Notification.objects.filter(event_key=event_key).first()
        if existing:
            logger.info(f"Notification with event_key '{event_key}' already exists; skipping duplicate.")
            return existing, False

    try:
        notification = Notification.objects.create(
            recipient=recipient,
            title=title,
            message=message,
            notification_type=notification_type,
            order=order,
            event_key=event_key,
        )
        return notification, True
    except IntegrityError:
        # Race condition defense for unique event_key
        existing = Notification.objects.filter(event_key=event_key).first()
        if existing:
            return existing, False
        raise


def notify_order_placed(order):
    """
    Notifies customer that their order has been placed.
    Dispatches both in-app notification and confirmation email idempotently.
    """
    event_key = f"order_placed:{order.id}"
    title = f"Order Placed: #{order.order_number}"
    payment = order.payments.first()
    pm_display = payment.get_payment_method_display() if payment else 'Pending'
    message = (
        f"Your order #{order.order_number} for ৳{order.total_amount} has been successfully placed. "
        f"Payment method: {pm_display}."
    )
    notification, created = create_notification(
        recipient=order.user,
        title=title,
        message=message,
        notification_type='ORDER_PLACED',
        order=order,
        event_key=event_key,
    )
    if created:
        send_order_placed_email(order)
    return notification


def notify_order_status_change(order, new_status, notes='', user=None):
    """
    Notifies customer that their order fulfillment status has transitioned.
    Dispatches in-app notification and update email idempotently per status step.
    """
    status_key = str(new_status).upper()
    status_display = dict(ORDER_STATUS_CHOICES).get(status_key, str(new_status))
    notification_type = STATUS_NOTIFICATION_TYPE_MAP.get(status_key, 'SYSTEM')

    event_key = f"order_status:{order.id}:{status_key.lower()}"
    title = f"Order #{order.order_number} Status: {status_display}"
    message = f"Your order #{order.order_number} status has been updated to '{status_display}'."
    if notes:
        message += f" Note: {notes}"

    notification, created = create_notification(
        recipient=order.user,
        title=title,
        message=message,
        notification_type=notification_type,
        order=order,
        event_key=event_key,
    )
    if created:
        send_order_status_update_email(order, status_display, notes=notes)
    return notification


def notify_payment_confirmed(payment):
    """
    Notifies customer that their payment was successfully validated and confirmed.
    """
    order = payment.order
    event_key = f"payment_confirmed:{payment.transaction_id}"
    title = f"Payment Received: Order #{order.order_number}"
    message = (
        f"Payment of ৳{payment.amount} {payment.currency} for order #{order.order_number} "
        f"was successfully received via {payment.payment_method}."
    )
    notification, created = create_notification(
        recipient=order.user,
        title=title,
        message=message,
        notification_type='PAYMENT_CONFIRMED',
        order=order,
        event_key=event_key,
    )
    if created:
        send_payment_confirmed_email(payment)
    return notification


def notify_payment_failed(payment, reason=''):
    """
    Notifies customer that a payment attempt failed.
    """
    order = payment.order
    event_key = f"payment_failed:{payment.transaction_id}"
    title = f"Payment Failed: Order #{order.order_number}"
    message = f"Payment attempt for order #{order.order_number} failed."
    if reason:
        message += f" Reason: {reason}"

    notification, created = create_notification(
        recipient=order.user,
        title=title,
        message=message,
        notification_type='PAYMENT_FAILED',
        order=order,
        event_key=event_key,
    )
    if created:
        send_payment_failed_email(payment, reason=reason)
    return notification


def notify_payment_cancelled(payment, reason=''):
    """
    Notifies customer that a payment attempt was cancelled.
    """
    order = payment.order
    event_key = f"payment_cancelled:{payment.transaction_id}"
    title = f"Payment Cancelled: Order #{order.order_number}"
    message = f"Payment attempt for order #{order.order_number} was cancelled."
    if reason:
        message += f" Reason: {reason}"

    notification, created = create_notification(
        recipient=order.user,
        title=title,
        message=message,
        notification_type='PAYMENT_CANCELLED',
        order=order,
        event_key=event_key,
    )
    return notification


def mark_notification_as_read(notification_id, user):
    """
    Marks a single notification as read for the authenticated recipient.
    Returns True if updated, False if not found or unauthorized.
    """
    notification = Notification.objects.filter(pk=notification_id, recipient=user).first()
    if notification:
        notification.mark_as_read()
        return True
    return False


def mark_all_notifications_as_read(user):
    """
    Marks all unread notifications as read for the authenticated recipient.
    Returns the count of updated notifications.
    """
    if not user.is_authenticated:
        return 0
    return Notification.objects.filter(
        recipient=user,
        is_read=False
    ).update(
        is_read=True,
        read_at=timezone.now()
    )


def get_unread_notifications_count(user):
    """
    Returns unread notification count for the given user.
    """
    if not user.is_authenticated:
        return 0
    return Notification.objects.filter(recipient=user, is_read=False).count()

