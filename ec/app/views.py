import logging
from decimal import Decimal
from django.db import transaction, IntegrityError, OperationalError
from django.utils import timezone
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View

logger = logging.getLogger(__name__)
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse
from django.db import models
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from .models import (
    Product, Customer, Cart, CartItem, Order, OrderItem, Payment, StockAdjustment, OrderStatusHistory,
    ORDER_STATUS_CHOICES, Notification, WishlistItem, ProductReview
)
from .services.notification import (
    mark_notification_as_read,
    mark_all_notifications_as_read,
    get_unread_notifications_count,
)
from .forms import CustomerRegistrationForm, CustomerProfileForm, LoginForm, ProductReviewForm
from .services.review import can_user_review_product, get_product_review_summary
from .services.catalog import (
    clean_catalog_params,
    get_catalog_queryset,
    paginate_catalog,
    build_preserved_query_params,
    get_active_filters,
    SORT_OPTIONS,
    CATEGORY_CHOICES,
    CATEGORY_MAP,
)
from .services.sslcommerz import initiate_sslcommerz_payment, validate_sslcommerz_transaction
from .services.payment import (
    create_payment,
    process_validated_payment,
    process_failed_payment,
    process_cancelled_payment,
)
from .services.inventory import (
    adjust_stock,
    deduct_order_stock,
    restore_order_stock,
    InsufficientStockError,
)
from .services.fulfillment import (
    transition_order_status,
    can_transition_order,
    FulfillmentTransitionError,
    VALID_TRANSITIONS,
)



def home(request):
    return render(request, 'app/home.html')
def about(request):
    return render(request, 'app/about.html')
def contact(request):
    return render(request, 'app/contact.html')

class ProductCatalogView(View):
    def get(self, request, val=None):
        cleaned_params = clean_catalog_params(request.GET, base_category=val)
        queryset = get_catalog_queryset(cleaned_params)
        page_obj, paginator = paginate_catalog(queryset, cleaned_params['page'])
        preserved_query = build_preserved_query_params(request.GET)
        active_filters = get_active_filters(cleaned_params)

        cat_code = cleaned_params.get('category')
        if cat_code:
            title = Product.objects.filter(category=cat_code).values('title')
            category_title_display = CATEGORY_MAP.get(cat_code, cat_code)
        else:
            title = Product.objects.all().values('title')[:20]
            category_title_display = 'All Products'

        context = {
            'product': page_obj,
            'products': page_obj,
            'page_obj': page_obj,
            'paginator': paginator,
            'is_paginated': paginator.num_pages > 1,
            'title': title,
            'categories': CATEGORY_CHOICES,
            'cleaned_params': cleaned_params,
            'search_query': cleaned_params['q'],
            'selected_category': cleaned_params['category'],
            'min_price': cleaned_params['min_price'],
            'max_price': cleaned_params['max_price'],
            'in_stock': cleaned_params['in_stock'],
            'selected_rating': cleaned_params['rating'],
            'selected_sort': cleaned_params['sort'],
            'sort_options': SORT_OPTIONS,
            'preserved_query_params': preserved_query,
            'active_filters': active_filters,
            'total_count': paginator.count,
            'filter_errors': cleaned_params.get('errors', []),
            'category_title_display': category_title_display,
        }
        return render(request, 'app/category.html', context)


class CategoryView(ProductCatalogView):
    pass


class CategoryTitle(View):
    def get(self, request, val):
        product = Product.objects.filter(title=val)
        if product.exists():
            title = Product.objects.filter(category=product[0].category).values('title')
        else:
            title = []
        return render(request, 'app/category.html', {
            'product': product,
            'products': product,
            'title': title,
            'categories': CATEGORY_CHOICES,
            'category_title_display': val,
            'total_count': product.count(),
            'cleaned_params': {'q': '', 'category': '', 'min_price': None, 'max_price': None, 'in_stock': False, 'rating': None, 'sort': 'newest'},
            'sort_options': SORT_OPTIONS,
            'preserved_query_params': '',
            'active_filters': [],
            'filter_errors': [],
        })    
    
class ProductDetail(View):
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        approved_reviews = product.reviews.filter(status='APPROVED').select_related('user').order_by('-created_at')

        review_summary = get_product_review_summary(product)
        reviews_count = review_summary['count']
        avg_rating = review_summary['average_rating']

        paginator = Paginator(approved_reviews, 5)
        page_number = request.GET.get('page')
        reviews_page = paginator.get_page(page_number)

        user_review = None
        can_review = False
        ineligible_reason = ''
        review_form = None
        in_wishlist = False

        if request.user.is_authenticated:
            user_review = product.reviews.filter(user=request.user).first()
            can_review, ineligible_reason = can_user_review_product(request.user, product)
            if user_review:
                review_form = ProductReviewForm(instance=user_review)
            elif can_review:
                review_form = ProductReviewForm()
            in_wishlist = WishlistItem.objects.filter(user=request.user, product=product).exists()
        else:
            ineligible_reason = "Please log in to write a review."

        return render(request, 'app/productdetail.html', {
            'product': product,
            'reviews': reviews_page,
            'reviews_count': reviews_count,
            'avg_rating': avg_rating,
            'can_review': can_review,
            'ineligible_reason': ineligible_reason,
            'user_review': user_review,
            'review_form': review_form,
            'in_wishlist': in_wishlist,
        })



class CustomerRegistrationView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('profile')
        form = CustomerRegistrationForm()
        return render(request, 'app/customerregistration.html', {'form': form})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('profile')
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Registration successful! You can now log in.")
            return redirect('login')
        return render(request, 'app/customerregistration.html', {'form': form})


class CustomLoginView(auth_views.LoginView):
    template_name = 'app/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        remember_me = form.cleaned_data.get('remember_me')
        if remember_me:
            self.request.session.set_expiry(1209600)  # 2 weeks
        else:
            self.request.session.set_expiry(0)  # Expire on browser close
        return super().form_valid(form)


class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        customer = Customer.objects.filter(user=request.user).first()
        form = CustomerProfileForm(instance=customer)
        return render(request, 'app/profile.html', {'form': form})

    def post(self, request):
        customer = Customer.objects.filter(user=request.user).first()
        form = CustomerProfileForm(request.POST, instance=customer)
        if form.is_valid():
            cust = form.save(commit=False)
            cust.user = request.user
            cust.save()
            messages.success(request, "Profile updated successfully")
            return redirect('profile')
        return render(request, 'app/profile.html', {'form': form})


class AddressView(LoginRequiredMixin, View):
    def get(self, request):
        customer = Customer.objects.filter(user=request.user).first()
        return render(request, 'app/address.html', {'customer': customer})


class AddToCartView(LoginRequiredMixin, View):
    def post(self, request):
        prod_id = request.POST.get('prod_id')
        product = get_object_or_404(Product, id=prod_id)
        try:
            qty = int(request.POST.get('quantity', 1))
            if qty <= 0:
                qty = 1
        except (TypeError, ValueError):
            qty = 1

        if product.stock <= 0:
            messages.error(request, f"'{product.title}' is currently out of stock.")
            return redirect('product-detail', pk=product.id)

        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart_item = CartItem.objects.filter(cart=cart, product=product).first()
        current_qty = cart_item.quantity if cart_item else 0
        new_total_qty = current_qty + qty

        if new_total_qty > product.stock:
            messages.error(
                request,
                f"Cannot add {qty} item(s). Only {product.stock} available in stock (you already have {current_qty} in your cart)."
            )
            return redirect('product-detail', pk=product.id)

        if not cart_item:
            CartItem.objects.create(cart=cart, product=product, quantity=qty)
        else:
            cart_item.quantity = new_total_qty
            cart_item.save()
        return redirect('show-cart')

    def get(self, request):
        return redirect('show-cart')


class ShowCartView(LoginRequiredMixin, View):
    def get(self, request):
        cart = Cart.objects.filter(user=request.user).first()
        cart_items = list(cart.items.all().select_related('product')) if cart else []
        cart_subtotal = 0.0
        total_discount = 0.0
        has_stock_error = False

        for item in cart_items:
            cart_subtotal += item.product.discounted_price * item.quantity
            total_discount += (item.product.selling_price - item.product.discounted_price) * item.quantity
            if item.quantity > item.product.stock or item.product.stock <= 0:
                item.stock_error = True
                has_stock_error = True
            else:
                item.stock_error = False

        if has_stock_error:
            messages.warning(
                request,
                "Some items in your cart exceed available stock. Please adjust quantities before proceeding to checkout."
            )

        delivery_charge = 70.00 if cart_items else 0.00
        estimated_total = round(cart_subtotal + delivery_charge, 2) if cart_items else 0.00

        return render(request, 'app/cart.html', {
            'cart': cart,
            'cart_items': cart_items,
            'cart_subtotal': round(cart_subtotal, 2),
            'total_discount': round(total_discount, 2),
            'delivery_charge': round(delivery_charge, 2),
            'estimated_total': estimated_total,
            'has_stock_error': has_stock_error,
        })


class PlusCartView(LoginRequiredMixin, View):
    def post(self, request):
        item_id = request.POST.get('item_id')
        prod_id = request.POST.get('prod_id')
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            if item_id:
                cart_item = CartItem.objects.select_related('product').filter(id=item_id, cart=cart).first()
            elif prod_id:
                cart_item = CartItem.objects.select_related('product').filter(product_id=prod_id, cart=cart).first()
            else:
                cart_item = None

            if cart_item:
                if cart_item.quantity + 1 > cart_item.product.stock:
                    messages.warning(
                        request,
                        f"Cannot increase quantity. Only {cart_item.product.stock} available in stock for '{cart_item.product.title}'."
                    )
                else:
                    cart_item.quantity += 1
                    cart_item.save()
        return redirect('show-cart')

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])


class MinusCartView(LoginRequiredMixin, View):
    def post(self, request):
        item_id = request.POST.get('item_id')
        prod_id = request.POST.get('prod_id')
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            if item_id:
                cart_item = CartItem.objects.filter(id=item_id, cart=cart).first()
            elif prod_id:
                cart_item = CartItem.objects.filter(product_id=prod_id, cart=cart).first()
            else:
                cart_item = None

            if cart_item:
                if cart_item.quantity > 1:
                    cart_item.quantity -= 1
                    cart_item.save()
                else:
                    cart_item.delete()
        return redirect('show-cart')

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])


class RemoveCartView(LoginRequiredMixin, View):
    def post(self, request):
        item_id = request.POST.get('item_id')
        prod_id = request.POST.get('prod_id')
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            if item_id:
                cart_item = CartItem.objects.filter(id=item_id, cart=cart).first()
            elif prod_id:
                cart_item = CartItem.objects.filter(product_id=prod_id, cart=cart).first()
            else:
                cart_item = None

            if cart_item:
                cart_item.delete()
        return redirect('show-cart')

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])


class UpdateCartView(LoginRequiredMixin, View):
    def post(self, request):
        item_id = request.POST.get('item_id')
        prod_id = request.POST.get('prod_id')
        raw_qty = request.POST.get('quantity')
        cart = Cart.objects.filter(user=request.user).first()
        if not cart:
            return redirect('show-cart')

        if item_id:
            cart_item = CartItem.objects.select_related('product').filter(id=item_id, cart=cart).first()
        elif prod_id:
            cart_item = CartItem.objects.select_related('product').filter(product_id=prod_id, cart=cart).first()
        else:
            cart_item = None

        if not cart_item:
            messages.error(request, "Item not found in your cart.")
            return redirect('show-cart')

        try:
            new_qty = int(raw_qty)
        except (ValueError, TypeError):
            messages.error(request, "Quantity must be a valid whole number.")
            return redirect('show-cart')

        if new_qty < 0:
            messages.error(request, "Quantity cannot be negative.")
            return redirect('show-cart')
        elif new_qty == 0:
            title = cart_item.product.title
            cart_item.delete()
            messages.info(request, f"'{title}' was removed from your cart.")
            return redirect('show-cart')

        if new_qty > cart_item.product.stock:
            messages.warning(
                request,
                f"Cannot set quantity to {new_qty}. Only {cart_item.product.stock} available in stock for '{cart_item.product.title}'."
            )
            return redirect('show-cart')

        cart_item.quantity = new_qty
        cart_item.save()
        messages.success(request, f"Updated quantity for '{cart_item.product.title}' to {new_qty}.")
        return redirect('show-cart')

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])


class CheckoutView(LoginRequiredMixin, View):
    def get(self, request):
        customer = Customer.objects.filter(user=request.user).first()
        if not customer or not customer.name or not customer.locality or not customer.city or not customer.mobile or not customer.state:
            messages.warning(request, "Please complete your shipping address before proceeding to checkout.")
            return redirect('profile')

        cart = Cart.objects.filter(user=request.user).first()
        cart_items = list(cart.items.select_related('product').all()) if cart else []
        if not cart_items:
            messages.warning(request, "Your cart is empty. Please add items before checking out.")
            return redirect('show-cart')

        # Stock pre-check: block proceeding to checkout if any item exceeds available stock
        for item in cart_items:
            if item.product.stock < item.quantity or item.product.stock <= 0:
                messages.error(
                    request,
                    f"'{item.product.title}' has insufficient stock (Requested: {item.quantity}, Available: {item.product.stock}). Please update your cart before checking out."
                )
                return redirect('show-cart')

        subtotal = Decimal('0.00')
        total_discount = Decimal('0.00')
        delivery_charge = Decimal('70.00')

        for item in cart_items:
            sp = Decimal(str(item.product.selling_price))
            dp = Decimal(str(item.product.discounted_price))
            subtotal += dp * item.quantity
            total_discount += (sp - dp) * item.quantity

        grand_total = subtotal + delivery_charge

        return render(request, 'app/checkout.html', {
            'cart': cart,
            'cart_items': cart_items,
            'customer': customer,
            'subtotal': subtotal,
            'total_discount': total_discount,
            'delivery_charge': delivery_charge,
            'grand_total': grand_total,
        })


class PlaceOrderView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect('checkout')

    def post(self, request):
        customer = Customer.objects.filter(user=request.user).first()
        if not customer or not customer.name or not customer.locality or not customer.city or not customer.mobile or not customer.state:
            messages.warning(request, "Incomplete shipping address. Please update your profile.")
            return redirect('profile')

        try:
            with transaction.atomic():
                cart = Cart.objects.select_for_update().filter(user=request.user).first()
                if not cart:
                    messages.warning(request, "Your cart is empty.")
                    return redirect('show-cart')

                # Force immediate write lock in SQLite & row lock in PostgreSQL
                Cart.objects.filter(id=cart.id).update(updated_at=timezone.now())

                # Re-read cart items freshly after acquiring transaction write lock
                cart_items = list(CartItem.objects.select_for_update().filter(cart=cart).select_related('product'))
                if not cart_items:
                    messages.warning(request, "Your cart is empty.")
                    return redirect('show-cart')

                # Pre-validate stock for every item before creating the order
                for item in cart_items:
                    if item.quantity <= 0:
                        messages.error(request, "Invalid item quantity in cart.")
                        return redirect('show-cart')
                    product = Product.objects.select_for_update().get(id=item.product.id)
                    if product.stock < item.quantity or product.stock <= 0:
                        messages.error(
                            request,
                            f"Cannot place order: '{product.title}' only has {product.stock} available in stock, but your cart has {item.quantity}."
                        )
                        return redirect('show-cart')

                subtotal = Decimal('0.00')
                total_discount = Decimal('0.00')
                delivery_charge = Decimal('70.00')
                order_items_data = []

                for item in cart_items:
                    product = Product.objects.select_for_update().get(id=item.product.id)
                    sp = Decimal(str(product.selling_price))
                    dp = Decimal(str(product.discounted_price))
                    item_subtotal = dp * item.quantity
                    item_discount = (sp - dp) * item.quantity
                    subtotal += item_subtotal
                    total_discount += item_discount
                    order_items_data.append({
                        'product': product,
                        'product_name': product.title,
                        'unit_price': dp,
                        'quantity': item.quantity,
                        'subtotal': item_subtotal,
                    })

                grand_total = subtotal + delivery_charge

                # Support custom shipping snapshot from checkout form or fallback to customer profile
                shipping_name = (request.POST.get('shipping_name') or '').strip() or customer.name
                shipping_mobile = (request.POST.get('shipping_mobile') or '').strip() or customer.mobile
                shipping_locality = (request.POST.get('shipping_locality') or '').strip() or customer.locality
                shipping_city = (request.POST.get('shipping_city') or '').strip() or customer.city
                shipping_state = (request.POST.get('shipping_state') or '').strip() or customer.state
                shipping_zipcode = (request.POST.get('shipping_zipcode') or '').strip() or str(customer.zipcode)

                if not shipping_name or not shipping_mobile or not shipping_locality or not shipping_city or not shipping_state:
                    messages.error(request, "All shipping address fields are required.")
                    return redirect('checkout')

                order = Order.objects.create(
                    user=request.user,
                    shipping_name=shipping_name,
                    shipping_mobile=shipping_mobile,
                    shipping_locality=shipping_locality,
                    shipping_city=shipping_city,
                    shipping_zipcode=shipping_zipcode,
                    shipping_state=shipping_state,
                    subtotal=subtotal,
                    total_discount=total_discount,
                    delivery_charge=delivery_charge,
                    grand_total=grand_total,
                    status='PENDING',
                    payment_status='PENDING',
                    stock_deducted=False,
                    stock_restored=False,
                )

                for oi in order_items_data:
                    OrderItem.objects.create(
                        order=order,
                        product=oi['product'],
                        product_name=oi['product_name'],
                        unit_price=oi['unit_price'],
                        quantity=oi['quantity'],
                        subtotal=oi['subtotal'],
                    )

                # Deduct stock atomically and record audit adjustment
                deduct_order_stock(order, user=request.user)

                # Create payment record (COD or SSLCOMMERZ)
                payment_method = request.POST.get('payment_method', 'COD').upper()
                if payment_method not in ('COD', 'SSLCOMMERZ'):
                    payment_method = 'COD'
                payment = create_payment(order, payment_method=payment_method)

                # Clear cart only after successful order and order items creation
                cart.items.all().delete()

                # Record initial order status history
                OrderStatusHistory.objects.create(
                    order=order,
                    from_status='PENDING',
                    to_status='PENDING',
                    changed_by=request.user,
                    notes='Order placed'
                )

                from app.services.notification import notify_order_placed
                order_to_notify = order
                transaction.on_commit(lambda: notify_order_placed(order_to_notify))

        except OperationalError:
            # Handle SQLite / database concurrency locks gracefully
            messages.warning(request, "A temporary database lock occurred. Please check your order history.")
            return redirect('show-cart')

        if payment_method == 'SSLCOMMERZ':
            initiate_result = initiate_sslcommerz_payment(payment, request)
            if initiate_result.get('success'):
                return redirect(initiate_result['gateway_url'])
            else:
                process_failed_payment(payment.transaction_id, reason=initiate_result.get('error'))
                messages.error(
                    request,
                    f"Order #{order.order_number} created, but online payment initiation failed: {initiate_result.get('error')}. You can retry payment from order details."
                )
                return redirect('order-detail', pk=order.pk)

        # COD flow
        messages.success(request, f"Order #{order.order_number} placed successfully with Cash on Delivery!")
        return redirect('order-confirmation', pk=order.pk)


class OrderConfirmationView(LoginRequiredMixin, View):
    def get(self, request, pk):
        order = get_object_or_404(Order, pk=pk, user=request.user)
        order_items = order.items.select_related('product').all()
        payment = order.payments.order_by('-created_at').first()
        return render(request, 'app/order_confirmation.html', {
            'order': order,
            'order_items': order_items,
            'payment': payment,
        })


class OrderListView(LoginRequiredMixin, View):
    def get(self, request):
        orders = Order.objects.filter(user=request.user).order_by('-created_at')
        return render(request, 'app/orders.html', {
            'orders': orders,
        })


class OrderDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        order = get_object_or_404(Order, pk=pk, user=request.user)
        order_items = order.items.select_related('product').all()
        payments = order.payments.all().order_by('-created_at')
        status_history = order.status_history.all().order_by('timestamp')
        return render(request, 'app/order_detail.html', {
            'order': order,
            'order_items': order_items,
            'payments': payments,
            'status_history': status_history,
        })


class OrderCancelView(LoginRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, user=request.user)
        if order.status == 'CANCELLED':
            messages.info(request, f"Order #{order.order_number} is already cancelled.")
            return redirect('order-detail', pk=order.pk)

        if order.payment_status == 'PAID':
            messages.error(request, "Paid orders cannot be cancelled directly. Please contact support.")
            return redirect('order-detail', pk=order.pk)

        if order.status != 'PENDING':
            messages.error(request, f"Cannot cancel order with status '{order.get_status_display()}'.")
            return redirect('order-detail', pk=order.pk)

        try:
            transition_order_status(
                order,
                'CANCELLED',
                user=request.user,
                notes='Cancelled by customer via My Orders'
            )
            messages.success(request, f"Order #{order.order_number} has been cancelled and stock has been restored.")
        except FulfillmentTransitionError as e:
            messages.error(request, str(e))

        return redirect('order-detail', pk=order.pk)

    def get(self, request, pk):
        return HttpResponseNotAllowed(['POST'])


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, "You do not have staff permissions to access fulfillment management.")
        return redirect('orders')


class StaffOrderQueueView(StaffRequiredMixin, View):
    def get(self, request):
        status_filter = request.GET.get('status', 'ACTIVE')
        search_query = request.GET.get('q', '').strip()

        orders = Order.objects.all().select_related('user').prefetch_related('items')

        if status_filter == 'ACTIVE':
            orders = orders.filter(status__in=['PENDING', 'ACCEPTED', 'PROCESSING', 'READY', 'SHIPPED'])
        elif status_filter in dict(ORDER_STATUS_CHOICES):
            orders = orders.filter(status=status_filter)

        if search_query:
            orders = orders.filter(
                models.Q(order_number__icontains=search_query) |
                models.Q(shipping_name__icontains=search_query) |
                models.Q(shipping_mobile__icontains=search_query) |
                models.Q(user__username__icontains=search_query)
            )

        orders = orders.order_by('-created_at')

        counts = {
            'ACTIVE': Order.objects.filter(status__in=['PENDING', 'ACCEPTED', 'PROCESSING', 'READY', 'SHIPPED']).count(),
            'PENDING': Order.objects.filter(status='PENDING').count(),
            'ACCEPTED': Order.objects.filter(status='ACCEPTED').count(),
            'PROCESSING': Order.objects.filter(status='PROCESSING').count(),
            'READY': Order.objects.filter(status='READY').count(),
            'SHIPPED': Order.objects.filter(status='SHIPPED').count(),
            'DELIVERED': Order.objects.filter(status='DELIVERED').count(),
            'CANCELLED': Order.objects.filter(status='CANCELLED').count(),
        }

        return render(request, 'app/staff_orders.html', {
            'orders': orders,
            'current_status': status_filter,
            'search_query': search_query,
            'counts': counts,
            'status_choices': ORDER_STATUS_CHOICES,
        })


class StaffOrderDetailView(StaffRequiredMixin, View):
    def get(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        order_items = order.items.select_related('product').all()
        payments = order.payments.all().order_by('-created_at')
        status_history = order.status_history.all().order_by('timestamp')
        next_statuses = list(VALID_TRANSITIONS.get(order.status, set()))

        return render(request, 'app/staff_order_detail.html', {
            'order': order,
            'order_items': order_items,
            'payments': payments,
            'status_history': status_history,
            'next_statuses': next_statuses,
        })


class StaffOrderTransitionView(StaffRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        target_status = request.POST.get('target_status', '').strip().upper()
        notes = request.POST.get('notes', '').strip()
        courier_name = request.POST.get('courier_name', '').strip()
        tracking_number = request.POST.get('tracking_number', '').strip()

        try:
            transition_order_status(
                order=order,
                target_status=target_status,
                user=request.user,
                notes=notes,
                courier_name=courier_name,
                tracking_number=tracking_number
            )
            messages.success(
                request,
                f"Order #{order.order_number} successfully updated to '{order.get_status_display()}'."
            )
        except FulfillmentTransitionError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.exception(f"Unexpected error transitioning order #{order.order_number}")
            messages.error(request, f"Error updating order: {str(e)}")

        redirect_to = request.POST.get('next') or reverse('staff-order-detail', kwargs={'pk': order.pk})
        return redirect(redirect_to)

    def get(self, request, pk):
        return HttpResponseNotAllowed(['POST'])


class SSLCommerzInitiateView(LoginRequiredMixin, View):
    def post(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id, user=request.user)
        if order.payment_status == 'PAID':
            messages.info(request, "This order is already paid.")
            return redirect('order-detail', pk=order.pk)

        payment = create_payment(order, payment_method='SSLCOMMERZ')
        initiate_result = initiate_sslcommerz_payment(payment, request)

        if initiate_result.get('success'):
            return redirect(initiate_result['gateway_url'])
        else:
            process_failed_payment(payment.transaction_id, reason=initiate_result.get('error'))
            messages.error(
                request,
                f"Online payment initiation failed: {initiate_result.get('error')}. Please try again."
            )
            return redirect('order-detail', pk=order.pk)

    def get(self, request, order_id):
        return HttpResponseNotAllowed(['POST'])


@method_decorator(csrf_exempt, name='dispatch')
class SSLCommerzSuccessView(View):
    def post(self, request):
        val_id = request.POST.get('val_id') or request.GET.get('val_id')
        tran_id = request.POST.get('tran_id') or request.GET.get('tran_id')

        if not val_id:
            messages.error(request, "Invalid payment response: missing validation ID.")
            return redirect('orders')

        val_data = validate_sslcommerz_transaction(val_id)
        val_tran_id = val_data.get('tran_id')

        # Defensive consistency check: verify request tran_id matches gateway-validated tran_id
        if tran_id and val_tran_id and tran_id != val_tran_id:
            logger.warning(
                f"Tran_id mismatch in success callback: request={tran_id}, validated={val_tran_id}"
            )
            messages.error(request, "Transaction validation verification failed.")
            payment = Payment.objects.filter(transaction_id=tran_id).first()
            if payment:
                return redirect('order-detail', pk=payment.order.pk)
            return redirect('orders')

        success, result = process_validated_payment(val_data)

        if success:
            order = result.order
            messages.success(request, f"Payment successful for Order #{order.order_number}!")
            return redirect('order-confirmation', pk=order.pk)
        else:
            payment = Payment.objects.filter(transaction_id=tran_id or val_tran_id).first()
            messages.error(request, f"Payment validation failed: {result}")
            if payment:
                return redirect('order-detail', pk=payment.order.pk)
            return redirect('orders')

    def get(self, request):
        return self.post(request)


@method_decorator(csrf_exempt, name='dispatch')
class SSLCommerzFailView(View):
    def post(self, request):
        tran_id = request.POST.get('tran_id') or request.GET.get('tran_id')
        reason = request.POST.get('error') or request.POST.get('failedreason', 'Payment failed')
        payment = process_failed_payment(tran_id, reason=reason)
        messages.error(request, f"Payment failed: {reason}. You can retry paying online.")
        if payment:
            return redirect('order-detail', pk=payment.order.pk)
        return redirect('orders')

    def get(self, request):
        return self.post(request)


@method_decorator(csrf_exempt, name='dispatch')
class SSLCommerzCancelView(View):
    def post(self, request):
        tran_id = request.POST.get('tran_id') or request.GET.get('tran_id')
        payment = process_cancelled_payment(tran_id)
        messages.warning(request, "Payment was cancelled. You can retry paying online anytime.")
        if payment:
            return redirect('order-detail', pk=payment.order.pk)
        return redirect('orders')

    def get(self, request):
        return self.post(request)


@method_decorator(csrf_exempt, name='dispatch')
class SSLCommerzIPNView(View):
    def post(self, request):
        val_id = request.POST.get('val_id')
        tran_id = request.POST.get('tran_id')

        if not val_id:
            return HttpResponse("Missing val_id parameter", status=400)

        val_data = validate_sslcommerz_transaction(val_id)
        val_tran_id = val_data.get('tran_id')

        if tran_id and val_tran_id and tran_id != val_tran_id:
            logger.warning(
                f"IPN tran_id mismatch: request={tran_id}, validated={val_tran_id}"
            )
            return HttpResponse("Transaction ID mismatch", status=400)

        success, result = process_validated_payment(val_data)

        if success:
            return HttpResponse("IPN Processed Successfully", status=200)
        else:
            return HttpResponse(f"Validation failed: {result}", status=400)

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])


class NotificationListView(LoginRequiredMixin, View):
    def get(self, request):
        filter_type = request.GET.get('filter', 'all')
        notifications = Notification.objects.filter(recipient=request.user).select_related('order')

        if filter_type == 'unread':
            notifications = notifications.filter(is_read=False)

        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()

        return render(request, 'app/notifications.html', {
            'notifications': notifications,
            'unread_count': unread_count,
            'filter_type': filter_type,
        })


class NotificationMarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        success = mark_notification_as_read(pk, request.user)
        unread_count = get_unread_notifications_count(request.user)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': success, 'unread_count': unread_count})

        if success:
            messages.success(request, "Notification marked as read.")
        return redirect('notifications')

    def get(self, request, pk):
        return HttpResponseNotAllowed(['POST'])


class NotificationMarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        count = mark_all_notifications_as_read(request.user)
        unread_count = get_unread_notifications_count(request.user)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'count': count, 'unread_count': unread_count})

        messages.success(request, f"{count} notifications marked as read." if count else "No unread notifications.")
        return redirect('notifications')

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])



# ================= WISHLIST VIEWS =================
class WishlistListView(LoginRequiredMixin, View):
    def get(self, request):
        wishlist_items = WishlistItem.objects.filter(user=request.user).select_related('product')
        return render(request, 'app/wishlist.html', {
            'wishlist_items': wishlist_items
        })


class AddToWishlistView(LoginRequiredMixin, View):
    def post(self, request):
        prod_id = request.POST.get('prod_id')
        if not prod_id:
            messages.error(request, "Invalid product specified.")
            return redirect('home')

        product = get_object_or_404(Product, id=prod_id)

        try:
            with transaction.atomic():
                item, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
            if created:
                messages.success(request, f"'{product.title}' has been added to your wishlist.")
            else:
                messages.info(request, f"'{product.title}' is already in your wishlist.")
        except IntegrityError:
            messages.info(request, f"'{product.title}' is already in your wishlist.")

        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('wishlist')
        return redirect(next_url)

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])


class RemoveFromWishlistView(LoginRequiredMixin, View):
    def post(self, request, pk=None):
        item_id = request.POST.get('item_id')
        prod_id = request.POST.get('prod_id')

        # Strictly enforce user ownership - only delete rows belonging to request.user
        deleted_count = 0
        if pk:
            deleted_count, _ = WishlistItem.objects.filter(pk=pk, user=request.user).delete()
        elif item_id:
            deleted_count, _ = WishlistItem.objects.filter(id=item_id, user=request.user).delete()
        elif prod_id:
            deleted_count, _ = WishlistItem.objects.filter(product_id=prod_id, user=request.user).delete()

        if deleted_count > 0:
            messages.success(request, "Item removed from your wishlist.")
        else:
            messages.info(request, "Item not found in your wishlist.")

        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('wishlist')
        return redirect(next_url)

    def get(self, request, pk=None):
        return HttpResponseNotAllowed(['POST'])


# ================= PRODUCT REVIEW VIEWS =================
class SubmitReviewView(LoginRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        can_review, reason = can_user_review_product(request.user, product)
        if not can_review:
            messages.error(request, reason)
            return redirect('product-detail', pk=product.pk)

        existing_review = ProductReview.objects.filter(user=request.user, product=product).first()
        if existing_review:
            form = ProductReviewForm(request.POST, instance=existing_review)
            if form.is_valid():
                review = form.save(commit=False)
                # Security: Author, product, and status cannot be overridden by client
                review.user = request.user
                review.product = product
                review.status = 'PENDING'
                review.save()
                messages.success(request, "Your review has been updated and submitted for moderation.")
            else:
                for error_list in form.errors.values():
                    for err in error_list:
                        messages.error(request, err)
        else:
            form = ProductReviewForm(request.POST)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        review = form.save(commit=False)
                        review.user = request.user
                        review.product = product
                        review.status = 'PENDING'
                        review.save()
                    messages.success(request, "Thank you! Your review has been submitted for moderation.")
                except IntegrityError:
                    messages.warning(request, "You have already submitted a review for this product.")
            else:
                for error_list in form.errors.values():
                    for err in error_list:
                        messages.error(request, err)

        return redirect('product-detail', pk=product.pk)

    def get(self, request, pk):
        return HttpResponseNotAllowed(['POST'])


class DeleteReviewView(LoginRequiredMixin, View):
    def post(self, request, pk):
        review = get_object_or_404(ProductReview, pk=pk, user=request.user)
        product_pk = review.product.pk
        review.delete()
        messages.success(request, "Your review has been deleted.")
        return redirect('product-detail', pk=product_pk)

    def get(self, request, pk):
        return HttpResponseNotAllowed(['POST'])
