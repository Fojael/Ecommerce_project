from django.db import models
from django.contrib.auth.models import User
import uuid
from django.utils import timezone
from decimal import Decimal


STATE_CHOICES = (
    ('Dhaka', 'Dhaka'),
    ('Chattogram', 'Chattogram'),
    ('Rajshahi', 'Rajshahi'),
    ('Khulna', 'Khulna'),
    ('Barishal', 'Barishal'),
    ('Sylhet', 'Sylhet'),
    ('Rangpur', 'Rangpur'),
    ('Mymensingh', 'Mymensingh'),
)

CATEGORY_CHOICES = (
    ('CR', 'Curd'),
    ('ML', 'Milk'),
    ('LS', 'Lassi'),
    ('MS', 'Milkshake'),
    ('PN', 'Paneer'),
    ('GH', 'Ghee'),
    ('CZ', 'Cheese'),
    ('IC', 'Ice-Creams'),
)

class Product(models.Model):
    title = models.CharField(max_length=100)
    selling_price = models.FloatField()
    discounted_price = models.FloatField()
    description = models.TextField()
    composition = models.TextField(default='')
    prodapp = models.TextField(default='')
    category = models.CharField(choices=CATEGORY_CHOICES, max_length=2)
    product_image = models.ImageField(upload_to='product')
    stock = models.IntegerField(
        default=10,
        help_text="Available inventory count. Must be non-negative."
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        help_text="Threshold below which the product is flagged as low stock."
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock__gte=0),
                name='product_stock_non_negative'
            )
        ]

    @property
    def is_in_stock(self):
        return self.stock > 0

    @property
    def is_out_of_stock(self):
        return self.stock <= 0

    @property
    def is_low_stock(self):
        return 0 < self.stock <= self.low_stock_threshold

    def __str__(self):
        return self.title

class Customer(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='customer'
    )
    name = models.CharField(max_length=200)
    locality = models.CharField(max_length=200)
    city = models.CharField(max_length=50)
    mobile = models.CharField(max_length=15, default='')
    zipcode = models.IntegerField(default=0)
    state = models.CharField(choices=STATE_CHOICES, max_length=100)

    def __str__(self):
        return self.name


class Cart(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="cart"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.user.username}"


class CartItem(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cart', 'product'], name='unique_cart_product')
        ]

    def __str__(self):
        return f"{self.product.title} (x{self.quantity})"

    @property
    def item_subtotal(self):
        return self.product.discounted_price * self.quantity

    @property
    def item_discount(self):
        return (self.product.selling_price - self.product.discounted_price) * self.quantity


ORDER_STATUS_CHOICES = (
    ('PENDING', 'Pending'),
    ('ACCEPTED', 'Accepted'),
    ('PROCESSING', 'Processing'),
    ('READY', 'Ready'),
    ('SHIPPED', 'Shipped'),
    ('DELIVERED', 'Delivered'),
    ('CANCELLED', 'Cancelled'),
)

PAYMENT_STATUS_CHOICES = (
    ('PENDING', 'Pending'),
    ('PAID', 'Paid'),
    ('FAILED', 'Failed'),
    ('REFUNDED', 'Refunded'),
)


def generate_order_number():
    date_str = timezone.now().strftime('%Y%m%d')
    for _ in range(10):
        rand_suffix = uuid.uuid4().hex[:8].upper()
        candidate = f"ORD-{date_str}-{rand_suffix}"
        if not Order.objects.filter(order_number=candidate).exists():
            return candidate
    return f"ORD-{date_str}-{uuid.uuid4().hex[:12].upper()}"


class Order(models.Model):
    ORDER_STATUS_CHOICES = ORDER_STATUS_CHOICES
    PAYMENT_STATUS_CHOICES = PAYMENT_STATUS_CHOICES

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    order_number = models.CharField(
        max_length=32,
        unique=True,
        editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Historical shipping snapshot
    shipping_name = models.CharField(max_length=200)
    shipping_mobile = models.CharField(max_length=15)
    shipping_locality = models.CharField(max_length=200)
    shipping_city = models.CharField(max_length=50)
    shipping_zipcode = models.CharField(max_length=20)
    shipping_state = models.CharField(max_length=100)

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )
    total_discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )
    delivery_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('70.00')
    )
    grand_total = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    status = models.CharField(
        max_length=20,
        choices=ORDER_STATUS_CHOICES,
        default='PENDING'
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='PENDING'
    )
    stock_deducted = models.BooleanField(
        default=False,
        help_text="Tracks whether inventory was deducted for this order upon creation."
    )
    stock_restored = models.BooleanField(
        default=False,
        help_text="Tracks whether inventory was restored upon order cancellation."
    )

    # Fulfillment and Delivery fields
    courier_name = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Courier / Delivery partner name (e.g. Pathao, RedX, Steadfast, In-house)."
    )
    tracking_number = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Consignment / tracking reference number."
    )
    shipped_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when order was handed over to courier / shipped."
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when order was confirmed delivered to customer."
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when order was cancelled."
    )
    cancellation_reason = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Reason for cancellation."
    )

    class Meta:
        ordering = ['-created_at']

    @property
    def is_cancellable(self):
        return self.status == 'PENDING' and self.payment_status != 'PAID'

    @property
    def is_delivered(self):
        return self.status == 'DELIVERED'

    @property
    def is_shipped(self):
        return self.status == 'SHIPPED'

    @property
    def total_amount(self):
        return self.grand_total

    @property
    def shipping_cost(self):
        return self.delivery_charge

    @property
    def shipping_address_line(self):
        return self.shipping_locality

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = generate_order_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_number} - {self.user.username}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='status_history'
    )
    from_status = models.CharField(
        max_length=20,
        choices=ORDER_STATUS_CHOICES
    )
    to_status = models.CharField(
        max_length=20,
        choices=ORDER_STATUS_CHOICES
    )
    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_status_history',
        help_text="User (staff or customer) who triggered the status transition."
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        default=''
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']
        verbose_name_plural = 'Order status histories'

    def __str__(self):
        return f"{self.order.order_number}: {self.from_status} -> {self.to_status} ({self.timestamp:%Y-%m-%d %H:%M})"



class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT
    )
    product_name = models.CharField(max_length=100)
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    quantity = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    def __str__(self):
        return f"{self.product_name} (x{self.quantity}) - {self.order.order_number}"


PAYMENT_METHOD_CHOICES = (
    ('COD', 'Cash on Delivery'),
    ('SSLCOMMERZ', 'SSLCommerz'),
)

PAYMENT_TRANSACTION_STATUS_CHOICES = (
    ('PENDING', 'Pending'),
    ('PAID', 'Paid'),
    ('FAILED', 'Failed'),
    ('CANCELLED', 'Cancelled'),
    ('REFUNDED', 'Refunded'),
)


def generate_transaction_id():
    # SSLCommerz tran_id max length is 30 characters
    date_str = timezone.now().strftime('%y%m%d%H%M%S')
    for _ in range(10):
        suffix = uuid.uuid4().hex[:10].upper()
        candidate = f"TX{date_str}{suffix}"
        if not Payment.objects.filter(transaction_id=candidate).exists():
            return candidate
    return f"TX{date_str}{uuid.uuid4().hex[:12].upper()}"[:30]


class Payment(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="payments"
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='COD'
    )
    status = models.CharField(
        max_length=20,
        choices=PAYMENT_TRANSACTION_STATUS_CHOICES,
        default='PENDING'
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )
    currency = models.CharField(
        max_length=10,
        default='BDT'
    )
    transaction_id = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
        db_index=True
    )
    gateway_transaction_id = models.CharField(
        max_length=100,
        blank=True,
        default=''
    )
    validation_id = models.CharField(
        max_length=100,
        blank=True,
        default=''
    )
    bank_transaction_id = models.CharField(
        max_length=100,
        blank=True,
        default=''
    )
    gateway_session_key = models.CharField(
        max_length=100,
        blank=True,
        default=''
    )
    card_type = models.CharField(
        max_length=50,
        blank=True,
        default=''
    )
    card_brand = models.CharField(
        max_length=50,
        blank=True,
        default=''
    )
    card_issuer = models.CharField(
        max_length=100,
        blank=True,
        default=''
    )
    risk_level = models.CharField(
        max_length=20,
        blank=True,
        default=''
    )
    risk_title = models.CharField(
        max_length=100,
        blank=True,
        default=''
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = generate_transaction_id()
        super().save(*args, **kwargs)

    @property
    def tran_id(self):
        return self.transaction_id

    def __str__(self):
        return f"{self.transaction_id} - {self.order.order_number} ({self.status})"


STOCK_ADJUSTMENT_REASON_CHOICES = (
    ('INITIAL', 'Initial Stock'),
    ('RESTOCK', 'Restock / Purchase'),
    ('ORDER_PLACED', 'Order Placed (Stock Deducted)'),
    ('ORDER_CANCELLED', 'Order Cancelled (Stock Restored)'),
    ('MANUAL_CORRECTION', 'Manual Adjustment / Audit'),
    ('DAMAGED', 'Damaged / Lost Stock'),
    ('RETURN', 'Customer Return'),
)


class StockAdjustment(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stock_adjustments'
    )
    quantity_change = models.IntegerField(
        help_text="Quantity change: positive for stock added, negative for stock removed."
    )
    resulting_stock = models.IntegerField(
        help_text="Stock level of the product immediately after this adjustment."
    )
    reason = models.CharField(
        max_length=50,
        choices=STOCK_ADJUSTMENT_REASON_CHOICES,
        default='MANUAL_CORRECTION'
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        default=''
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_adjustments',
        help_text="Staff or authenticated user who made or authorized the adjustment."
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_adjustments',
        help_text="Associated order for order-related deductions or restorations."
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        sign = "+" if self.quantity_change > 0 else ""
        return f"{self.product.title}: {sign}{self.quantity_change} ({self.get_reason_display()})"


NOTIFICATION_TYPE_CHOICES = (
    ('ORDER_PLACED', 'Order Placed'),
    ('ORDER_ACCEPTED', 'Order Confirmed/Accepted'),
    ('ORDER_PROCESSING', 'Order Processing'),
    ('ORDER_READY', 'Order Ready for Dispatch'),
    ('ORDER_SHIPPED', 'Order Dispatched / Shipped'),
    ('ORDER_DELIVERED', 'Order Delivered'),
    ('ORDER_CANCELLED', 'Order Cancelled'),
    ('PAYMENT_CONFIRMED', 'Payment Received'),
    ('PAYMENT_FAILED', 'Payment Failed'),
    ('PAYMENT_CANCELLED', 'Payment Cancelled'),
    ('SYSTEM', 'System Alert'),
)


class Notification(models.Model):
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        help_text="User who receives the notification."
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPE_CHOICES,
        default='SYSTEM'
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
        help_text="Associated order for order-related notifications."
    )
    is_read = models.BooleanField(
        default=False,
        help_text="Whether the recipient has marked this notification as read."
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the notification was marked as read."
    )
    event_key = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        unique=True,
        help_text="Idempotency key to prevent duplicate notifications for the same event."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['event_key']),
        ]

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def __str__(self):
        status_flag = "Read" if self.is_read else "Unread"
        return f"[{status_flag}] {self.recipient.username}: {self.title} ({self.created_at:%Y-%m-%d %H:%M})"


