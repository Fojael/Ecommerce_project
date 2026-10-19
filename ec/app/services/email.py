import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_notification_email(recipient_email, subject, text_template, html_template, context):
    """
    Safely send a multipart (plaintext + HTML) email to the recipient.
    Validates recipient email and catches any transport errors without raising exceptions.
    Returns (success: bool, message: str).
    """
    if not recipient_email or not recipient_email.strip():
        logger.info("Email sending skipped: recipient email is empty.")
        return False, "Recipient email is not configured."

    recipient_email = recipient_email.strip()

    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@ecommerce.local')
        text_content = render_to_string(text_template, context)
        html_content = render_to_string(html_template, context)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[recipient_email]
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)

        logger.info(f"Notification email successfully sent to {recipient_email} (Subject: {subject})")
        return True, "Email sent successfully."
    except Exception as e:
        logger.warning(f"Failed to send email to {recipient_email}: {e}", exc_info=True)
        return False, str(e)


def send_order_placed_email(order):
    """Send order placed confirmation email to customer."""
    recipient_email = getattr(order.user, 'email', '')
    subject = f"Order Confirmation - #{order.order_number}"
    context = {'order': order}
    return send_notification_email(
        recipient_email=recipient_email,
        subject=subject,
        text_template='emails/order_placed.txt',
        html_template='emails/order_placed.html',
        context=context
    )


def send_order_status_update_email(order, new_status, notes=''):
    """Send order status change update email to customer."""
    recipient_email = getattr(order.user, 'email', '')
    subject = f"Order #{order.order_number} Update: {new_status}"
    context = {'order': order, 'new_status': new_status, 'notes': notes}
    return send_notification_email(
        recipient_email=recipient_email,
        subject=subject,
        text_template='emails/order_status_update.txt',
        html_template='emails/order_status_update.html',
        context=context
    )


def send_payment_confirmed_email(payment):
    """Send payment confirmed receipt email to customer."""
    order = payment.order
    recipient_email = getattr(order.user, 'email', '')
    subject = f"Payment Confirmed - Order #{order.order_number}"
    context = {'payment': payment, 'order': order}
    return send_notification_email(
        recipient_email=recipient_email,
        subject=subject,
        text_template='emails/payment_confirmed.txt',
        html_template='emails/payment_confirmed.html',
        context=context
    )


def send_payment_failed_email(payment, reason=''):
    """Send payment failed notice email to customer."""
    order = payment.order
    recipient_email = getattr(order.user, 'email', '')
    subject = f"Payment Failed - Order #{order.order_number}"
    context = {'payment': payment, 'order': order, 'reason': reason}
    return send_notification_email(
        recipient_email=recipient_email,
        subject=subject,
        text_template='emails/payment_failed.txt',
        html_template='emails/payment_failed.html',
        context=context
    )

