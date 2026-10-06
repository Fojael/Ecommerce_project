import logging
from decimal import Decimal
from django.db import transaction
from app.models import Payment, Order

logger = logging.getLogger(__name__)


def create_payment(order, payment_method='COD'):
    """
    Creates a new Payment record tied to an Order.
    Authoritative amount is always order.grand_total.
    """
    payment = Payment.objects.create(
        order=order,
        payment_method=payment_method,
        status='PENDING',
        amount=order.grand_total,
        currency='BDT',
    )
    return payment


def process_validated_payment(val_data):
    """
    Validates transaction data against database payment record inside atomic transaction.
    Enforces amount, currency, tran_id, and validation status checks.
    Thread-safe and idempotent.
    """
    val_status = val_data.get('status')
    tran_id = val_data.get('tran_id')
    amount_str = val_data.get('amount')
    currency = val_data.get('currency', 'BDT')

    if not tran_id:
        return False, "Missing transaction ID in validation response."

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(transaction_id=tran_id).first()
        if not payment:
            logger.warning(f"Payment record not found for tran_id: {tran_id}")
            return False, f"Payment record not found for tran_id {tran_id}"

        # Idempotency check: if already paid, do not re-process
        if payment.status == 'PAID':
            logger.info(f"Payment {tran_id} already marked as PAID (idempotent)")
            return True, payment

        # Status check
        if val_status not in ('VALID', 'VALIDATED'):
            payment.status = 'FAILED'
            payment.save(update_fields=['status', 'updated_at'])
            return False, f"Gateway validation status was not VALID: {val_status}"

        # Amount check (Decimal-safe)
        try:
            val_amount = Decimal(str(amount_str)).quantize(Decimal('0.01'))
        except (ValueError, TypeError):
            return False, "Invalid amount received in validation data."

        if val_amount != payment.amount.quantize(Decimal('0.01')):
            logger.error(
                f"Payment amount mismatch for tran_id {tran_id}: expected {payment.amount}, got {val_amount}"
            )
            return False, f"Amount mismatch: expected {payment.amount}, received {val_amount}"

        # Currency check
        if currency != payment.currency:
            logger.error(
                f"Currency mismatch for tran_id {tran_id}: expected {payment.currency}, got {currency}"
            )
            return False, f"Currency mismatch: expected {payment.currency}, received {currency}"

        # Update payment attributes
        payment.status = 'PAID'
        payment.gateway_transaction_id = val_data.get('bank_tran_id', '') or val_data.get('tran_id', '')
        payment.validation_id = val_data.get('val_id', '')
        payment.bank_transaction_id = val_data.get('bank_tran_id', '')
        payment.card_type = val_data.get('card_type', '')
        payment.card_brand = val_data.get('card_brand', '')
        payment.card_issuer = val_data.get('card_issuer', '')
        payment.risk_level = str(val_data.get('risk_level', ''))
        payment.risk_title = str(val_data.get('risk_title', ''))
        payment.save()

        if payment.risk_level and payment.risk_level != '0':
            logger.warning(
                f"Elevated risk transaction detected for tran_id {tran_id}: risk_level={payment.risk_level}, risk_title={payment.risk_title}"
            )

        # Update order payment status
        order = payment.order
        order.payment_status = 'PAID'
        order.save(update_fields=['payment_status', 'updated_at'])

        logger.info(f"Payment {tran_id} and Order {order.order_number} marked as PAID")
        return True, payment


def process_failed_payment(tran_id, reason=''):
    """
    Marks a payment as FAILED unless it has already succeeded.
    """
    if not tran_id:
        return None
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(transaction_id=tran_id).first()
        if payment and payment.status != 'PAID':
            payment.status = 'FAILED'
            payment.save(update_fields=['status', 'updated_at'])
            order = payment.order
            if order.payment_status != 'PAID':
                order.payment_status = 'FAILED'
                order.save(update_fields=['payment_status', 'updated_at'])
        return payment


def process_cancelled_payment(tran_id):
    """
    Marks a payment as CANCELLED unless it has already succeeded.
    Preserves Order payment_status as PENDING so customer can retry payment.
    """
    if not tran_id:
        return None
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(transaction_id=tran_id).first()
        if payment and payment.status != 'PAID':
            payment.status = 'CANCELLED'
            payment.save(update_fields=['status', 'updated_at'])
            order = payment.order
            if order.payment_status != 'PAID':
                order.payment_status = 'PENDING'
                order.save(update_fields=['payment_status', 'updated_at'])
        return payment
