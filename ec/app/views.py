import logging
from decimal import Decimal
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View

logger = logging.getLogger(__name__)
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, HttpResponseNotAllowed
from .models import Product, Customer, Cart, CartItem, Order, OrderItem, Payment
from .forms import CustomerRegistrationForm, CustomerProfileForm, LoginForm
from .services.sslcommerz import initiate_sslcommerz_payment, validate_sslcommerz_transaction
from .services.payment import (
    create_payment,
    process_validated_payment,
    process_failed_payment,
    process_cancelled_payment,
)



def home(request):
    return render(request, 'app/home.html')
def about(request):
    return render(request, 'app/about.html')
def contact(request):
    return render(request, 'app/contact.html')

class CategoryView(View):
    def get(self, request, val):
        product = Product.objects.filter(category=val)
        title = Product.objects.filter(category=val).values('title')
        return render(request, 'app/category.html', {'product': product, 'title': title})

class CategoryTitle(View):
    def get(self, request, val):
        product = Product.objects.filter(title=val)
        if product.exists():
            title = Product.objects.filter(category=product[0].category).values('title')
        else:
            title = []
        return render(request, 'app/category.html', {'product': product, 'title': title})    
    
class ProductDetail(View):
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        return render(request, 'app/productdetail.html', {'product': product})    
    
    
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

        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)
        if not created:
            cart_item.quantity += qty
            cart_item.save()
        else:
            cart_item.quantity = qty
            cart_item.save()
        return redirect('show-cart')

    def get(self, request):
        return redirect('show-cart')


class ShowCartView(LoginRequiredMixin, View):
    def get(self, request):
        cart = Cart.objects.filter(user=request.user).first()
        cart_items = cart.items.all().select_related('product') if cart else []
        cart_subtotal = 0.0
        total_discount = 0.0
        for item in cart_items:
            cart_subtotal += item.product.discounted_price * item.quantity
            total_discount += (item.product.selling_price - item.product.discounted_price) * item.quantity

        return render(request, 'app/cart.html', {
            'cart': cart,
            'cart_items': cart_items,
            'cart_subtotal': round(cart_subtotal, 2),
            'total_discount': round(total_discount, 2),
        })


class PlusCartView(LoginRequiredMixin, View):
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
                cart_item.quantity += 1
                cart_item.save()
        return redirect('show-cart')


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

        with transaction.atomic():
            cart = Cart.objects.select_for_update().filter(user=request.user).first()
            cart_items = list(cart.items.select_related('product').all()) if cart else []
            if not cart_items:
                messages.warning(request, "Your cart is empty.")
                return redirect('show-cart')

            subtotal = Decimal('0.00')
            total_discount = Decimal('0.00')
            delivery_charge = Decimal('70.00')
            order_items_data = []

            for item in cart_items:
                if item.quantity <= 0:
                    messages.error(request, "Invalid item quantity in cart.")
                    return redirect('show-cart')
                product = Product.objects.get(id=item.product.id)
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

            order = Order.objects.create(
                user=request.user,
                shipping_name=customer.name,
                shipping_mobile=customer.mobile,
                shipping_locality=customer.locality,
                shipping_city=customer.city,
                shipping_zipcode=str(customer.zipcode),
                shipping_state=customer.state,
                subtotal=subtotal,
                total_discount=total_discount,
                delivery_charge=delivery_charge,
                grand_total=grand_total,
                status='PENDING',
                payment_status='PENDING',
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

            # Create payment record (COD or SSLCOMMERZ)
            payment_method = request.POST.get('payment_method', 'COD').upper()
            if payment_method not in ('COD', 'SSLCOMMERZ'):
                payment_method = 'COD'
            payment = create_payment(order, payment_method=payment_method)

            # Clear cart only after successful order and order items creation
            cart.items.all().delete()

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
        return render(request, 'app/order_detail.html', {
            'order': order,
            'order_items': order_items,
            'payments': payments,
        })


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

