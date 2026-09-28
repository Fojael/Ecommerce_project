from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Product, Customer, Cart, CartItem
from .forms import CustomerRegistrationForm, CustomerProfileForm, LoginForm

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