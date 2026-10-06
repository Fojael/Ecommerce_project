from django.contrib import admin
from .models import Customer, Product, Cart, CartItem, Order, OrderItem, Payment

@admin.register(Product)
class ProductModelAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'selling_price',
        'discounted_price',
        'category',
        'product_image'
    )

@admin.register(Customer)
class CustomerModelAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'name',
        'locality',
        'city',
        'mobile',
        'zipcode',
        'state'
    )

@admin.register(Cart)
class CartModelAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at', 'updated_at')

@admin.register(CartItem)
class CartItemModelAdmin(admin.ModelAdmin):
    list_display = ('id', 'cart', 'product', 'quantity')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    readonly_fields = ('product', 'product_name', 'unit_price', 'quantity', 'subtotal')
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    readonly_fields = ('transaction_id', 'payment_method', 'status', 'amount', 'currency', 'gateway_transaction_id', 'validation_id', 'risk_level', 'risk_title', 'created_at')
    extra = 0
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number',
        'user',
        'status',
        'payment_status',
        'grand_total',
        'created_at'
    )
    list_filter = ('status', 'payment_status', 'created_at')
    search_fields = ('order_number', 'user__username', 'shipping_name', 'shipping_mobile')
    inlines = [OrderItemInline, PaymentInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        'order',
        'product',
        'product_name',
        'unit_price',
        'quantity',
        'subtotal'
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_id',
        'order',
        'payment_method',
        'status',
        'amount',
        'currency',
        'risk_level',
        'created_at'
    )
    list_filter = ('status', 'payment_method', 'currency', 'risk_level', 'created_at')
    search_fields = (
        'transaction_id',
        'order__order_number',
        'gateway_transaction_id',
        'validation_id'
    )
    readonly_fields = (
        'transaction_id',
        'gateway_transaction_id',
        'validation_id',
        'bank_transaction_id',
        'gateway_session_key',
        'risk_level',
        'risk_title',
        'created_at',
        'updated_at'
    )

