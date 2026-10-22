from django.contrib import admin
from django.db import models
from django.utils import timezone
from .models import (
    Customer, Product, Cart, CartItem, Order, OrderItem, Payment, StockAdjustment, OrderStatusHistory,
    Notification, WishlistItem, ProductReview
)
from .services.inventory import adjust_stock, restore_order_stock
from .services.fulfillment import (
    transition_order_status,
    can_transition_order,
    FulfillmentTransitionError,
)


class StockStatusFilter(admin.SimpleListFilter):
    title = 'Stock Status'
    parameter_name = 'stock_status'

    def lookups(self, request, model_admin):
        return (
            ('in_stock', 'In Stock'),
            ('low_stock', 'Low Stock (<= Threshold)'),
            ('out_of_stock', 'Out of Stock (0)'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'in_stock':
            return queryset.filter(stock__gt=0)
        elif self.value() == 'low_stock':
            return queryset.filter(stock__gt=0, stock__lte=models.F('low_stock_threshold'))
        elif self.value() == 'out_of_stock':
            return queryset.filter(stock__lte=0)
        return queryset


class StockAdjustmentInline(admin.TabularInline):
    model = StockAdjustment
    extra = 0
    can_delete = False
    readonly_fields = ('timestamp', 'quantity_change', 'resulting_stock', 'reason', 'notes', 'user', 'order')
    ordering = ('-timestamp',)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductModelAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'category',
        'selling_price',
        'discounted_price',
        'stock',
        'low_stock_threshold',
        'stock_status',
    )
    list_filter = ('category', StockStatusFilter)
    search_fields = ('title', 'description', 'composition')
    inlines = [StockAdjustmentInline]

    @admin.display(description='Availability')
    def stock_status(self, obj):
        if obj.stock <= 0:
            return 'Out of Stock'
        elif obj.stock <= obj.low_stock_threshold:
            return f'Low Stock ({obj.stock})'
        return f'In Stock ({obj.stock})'


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'product',
        'quantity_change',
        'resulting_stock',
        'reason',
        'notes',
        'user',
        'order',
        'timestamp',
    )
    list_filter = ('reason', 'timestamp')
    search_fields = (
        'product__title',
        'reason',
        'notes',
        'user__username',
        'order__order_number',
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            adjust_stock(
                product=obj.product,
                quantity_change=obj.quantity_change,
                reason=obj.reason,
                user=request.user,
                notes=obj.notes,
                order=obj.order
            )
        else:
            super().save_model(request, obj, form, change)

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


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ('from_status', 'to_status', 'changed_by', 'notes', 'timestamp')
    ordering = ('timestamp',)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number',
        'user',
        'status',
        'payment_status',
        'courier_name',
        'tracking_number',
        'stock_deducted',
        'grand_total',
        'created_at'
    )
    list_filter = ('status', 'payment_status', 'stock_deducted', 'stock_restored', 'created_at')
    search_fields = (
        'order_number', 'user__username', 'shipping_name', 'shipping_mobile',
        'courier_name', 'tracking_number'
    )
    readonly_fields = (
        'order_number', 'created_at', 'updated_at', 'stock_deducted', 'stock_restored',
        'shipped_at', 'delivered_at', 'cancelled_at'
    )
    inlines = [OrderItemInline, PaymentInline, OrderStatusHistoryInline]
    actions = [
        'accept_selected_orders',
        'process_selected_orders',
        'ready_selected_orders',
        'deliver_selected_orders',
        'cancel_selected_orders',
    ]

    @admin.action(description="Confirm/Accept selected orders (PENDING -> ACCEPTED)")
    def accept_selected_orders(self, request, queryset):
        success_count, skip_count = 0, 0
        for order in queryset:
            order.refresh_from_db()
            allowed, _ = can_transition_order(order, 'ACCEPTED', user=request.user)
            if allowed:
                transition_order_status(order, 'ACCEPTED', user=request.user, notes='Accepted by staff via Django Admin')
                success_count += 1
            else:
                skip_count += 1
        msg = f"{success_count} order(s) accepted."
        if skip_count:
            msg += f" {skip_count} order(s) skipped (not in PENDING status)."
        self.message_user(request, msg)

    @admin.action(description="Start processing selected orders (ACCEPTED -> PROCESSING)")
    def process_selected_orders(self, request, queryset):
        success_count, skip_count = 0, 0
        for order in queryset:
            order.refresh_from_db()
            allowed, _ = can_transition_order(order, 'PROCESSING', user=request.user)
            if allowed:
                transition_order_status(order, 'PROCESSING', user=request.user, notes='Processing started via Django Admin')
                success_count += 1
            else:
                skip_count += 1
        msg = f"{success_count} order(s) marked as Processing."
        if skip_count:
            msg += f" {skip_count} order(s) skipped (not in ACCEPTED status)."
        self.message_user(request, msg)

    @admin.action(description="Mark selected orders Ready for Dispatch (PROCESSING -> READY)")
    def ready_selected_orders(self, request, queryset):
        success_count, skip_count = 0, 0
        for order in queryset:
            order.refresh_from_db()
            allowed, _ = can_transition_order(order, 'READY', user=request.user)
            if allowed:
                transition_order_status(order, 'READY', user=request.user, notes='Marked ready for dispatch via Django Admin')
                success_count += 1
            else:
                skip_count += 1
        msg = f"{success_count} order(s) marked Ready for Dispatch."
        if skip_count:
            msg += f" {skip_count} order(s) skipped (not in PROCESSING status)."
        self.message_user(request, msg)

    @admin.action(description="Mark dispatched orders as Delivered (SHIPPED -> DELIVERED)")
    def deliver_selected_orders(self, request, queryset):
        success_count, skip_count = 0, 0
        for order in queryset:
            order.refresh_from_db()
            allowed, _ = can_transition_order(order, 'DELIVERED', user=request.user)
            if allowed:
                transition_order_status(order, 'DELIVERED', user=request.user, notes='Confirmed delivered via Django Admin')
                success_count += 1
            else:
                skip_count += 1
        msg = f"{success_count} order(s) marked as Delivered."
        if skip_count:
            msg += f" {skip_count} order(s) skipped (not in SHIPPED status)."
        self.message_user(request, msg)

    @admin.action(description="Cancel selected orders and restore inventory")
    def cancel_selected_orders(self, request, queryset):
        restored_count = 0
        skipped_count = 0
        for order in queryset:
            order.refresh_from_db()
            allowed, _ = can_transition_order(order, 'CANCELLED', user=request.user)
            if not allowed:
                skipped_count += 1
                continue
            try:
                transition_order_status(
                    order,
                    'CANCELLED',
                    user=request.user,
                    notes='Cancelled by staff via Django Admin'
                )
                restored_count += 1
            except Exception:
                skipped_count += 1
        msg = f"{restored_count} order(s) cancelled and stock restored successfully."
        if skipped_count:
            msg += f" {skipped_count} order(s) skipped (already cancelled, paid, or fulfilled)."
        self.message_user(request, msg)


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'from_status', 'to_status', 'changed_by', 'notes', 'timestamp')
    list_filter = ('from_status', 'to_status', 'timestamp')
    search_fields = ('order__order_number', 'notes', 'changed_by__username')
    readonly_fields = ('order', 'from_status', 'to_status', 'changed_by', 'notes', 'timestamp')

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False



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


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'recipient',
        'title',
        'notification_type',
        'order',
        'is_read',
        'read_at',
        'created_at',
    )
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = (
        'recipient__username',
        'recipient__email',
        'title',
        'message',
        'order__order_number',
        'event_key'
    )
    readonly_fields = (
        'recipient',
        'title',
        'message',
        'notification_type',
        'order',
        'event_key',
        'created_at',
        'read_at',
    )
    actions = ['mark_as_read', 'mark_as_unread']

    @admin.action(description="Mark selected notifications as Read")
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True, read_at=timezone.now())

    @admin.action(description="Mark selected notifications as Unread")
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False, read_at=None)




@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'product', 'created_at')
    search_fields = ('user__username', 'product__title')
    list_filter = ('created_at',)
    readonly_fields = ('user', 'product', 'created_at')

    def has_add_permission(self, request):
        return False


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'user', 'rating', 'title', 'status', 'created_at')
    list_filter = ('status', 'rating', 'created_at')
    search_fields = ('product__title', 'user__username', 'title', 'comment')
    readonly_fields = ('user', 'product', 'created_at', 'updated_at')
    actions = ['approve_reviews', 'reject_reviews', 'mark_pending']

    @admin.action(description="Approve selected reviews")
    def approve_reviews(self, request, queryset):
        queryset.update(status='APPROVED')

    @admin.action(description="Reject selected reviews")
    def reject_reviews(self, request, queryset):
        queryset.update(status='REJECTED')

    @admin.action(description="Mark selected reviews as Pending")
    def mark_pending(self, request, queryset):
        queryset.update(status='PENDING')
