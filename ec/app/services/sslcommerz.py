import logging
import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)

SANDBOX_INIT_URL = "https://sandbox-gw.sslcommerz.com/gwprocess/v4/api.php"
SANDBOX_VALIDATION_URL = "https://sandbox.sslcommerz.com/validator/api/validationserverAPI.php"

PROD_INIT_URL = "https://securepay.sslcommerz.com/gwprocess/v4/api.php"
PROD_VALIDATION_URL = "https://securepay.sslcommerz.com/validator/api/validationserverAPI.php"


def get_sslcommerz_config():
    store_id = getattr(settings, 'SSLCOMMERZ_STORE_ID', 'testbox')
    store_passwd = getattr(settings, 'SSLCOMMERZ_STORE_PASSWORD', 'qwerty')
    is_sandbox = getattr(settings, 'SSLCOMMERZ_IS_SANDBOX', True)

    init_url = SANDBOX_INIT_URL if is_sandbox else PROD_INIT_URL
    val_url = SANDBOX_VALIDATION_URL if is_sandbox else PROD_VALIDATION_URL

    return {
        'store_id': store_id,
        'store_passwd': store_passwd,
        'is_sandbox': is_sandbox,
        'init_url': init_url,
        'val_url': val_url,
    }


def initiate_sslcommerz_payment(payment, request):
    """
    Server-side SSLCommerz hosted payment initiation.
    Constructs the request payload and retrieves GatewayPageURL.
    """
    config = get_sslcommerz_config()
    order = payment.order

    success_url = request.build_absolute_uri(reverse('sslcommerz-success'))
    fail_url = request.build_absolute_uri(reverse('sslcommerz-fail'))
    cancel_url = request.build_absolute_uri(reverse('sslcommerz-cancel'))
    ipn_url = request.build_absolute_uri(reverse('sslcommerz-ipn'))

    payload = {
        'store_id': config['store_id'],
        'store_passwd': config['store_passwd'],
        'total_amount': str(payment.amount),
        'currency': payment.currency,
        'tran_id': payment.transaction_id,
        'success_url': success_url,
        'fail_url': fail_url,
        'cancel_url': cancel_url,
        'ipn_url': ipn_url,
        # Customer Information
        'cus_name': order.shipping_name or order.user.username,
        'cus_email': order.user.email or "customer@example.com",
        'cus_add1': order.shipping_locality or "Dhaka",
        'cus_city': order.shipping_city or "Dhaka",
        'cus_state': order.shipping_state or "Dhaka",
        'cus_postcode': order.shipping_zipcode or "1000",
        'cus_country': "Bangladesh",
        'cus_phone': order.shipping_mobile or "01700000000",
        # Shipping Details
        'shipping_method': "NO",
        'num_of_item': order.items.count() or 1,
        # Product Details
        'product_name': f"Order #{order.order_number}",
        'product_category': "General",
        'product_profile': "general",
    }

    try:
        response = requests.post(config['init_url'], data=payload, timeout=15)
        response_data = response.json()
    except Exception as exc:
        logger.error(
            f"SSLCommerz initiation network exception for tran_id {payment.transaction_id}: {str(exc)}"
        )
        return {
            'success': False,
            'error': "Network error communicating with payment gateway."
        }

    status = response_data.get('status')
    if status == 'SUCCESS':
        gateway_url = response_data.get('GatewayPageURL')
        session_key = response_data.get('sessionkey', '')
        if session_key:
            payment.gateway_session_key = session_key
            payment.save(update_fields=['gateway_session_key', 'updated_at'])
        return {
            'success': True,
            'gateway_url': gateway_url,
            'sessionkey': session_key,
        }
    else:
        failed_reason = response_data.get('failedreason', 'Unknown gateway error')
        logger.warning(
            f"SSLCommerz initiation rejected for tran_id {payment.transaction_id}: {failed_reason}"
        )
        return {
            'success': False,
            'error': failed_reason,
        }


def validate_sslcommerz_transaction(val_id):
    """
    Server-side SSLCommerz Order Validation API query.
    Queries the validator endpoint using val_id.
    """
    config = get_sslcommerz_config()
    params = {
        'val_id': val_id,
        'store_id': config['store_id'],
        'store_passwd': config['store_passwd'],
        'format': 'json',
    }

    try:
        response = requests.get(config['val_url'], params=params, timeout=15)
        return response.json()
    except Exception as exc:
        logger.error(f"SSLCommerz validation error for val_id {val_id}: {str(exc)}")
        return {'status': 'FAILED', 'error': str(exc)}
