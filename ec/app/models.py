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

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = generate_order_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_number} - {self.user.username}"


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

    def __str__(self):
        return f"{self.transaction_id} - {self.order.order_number} ({self.status})"

