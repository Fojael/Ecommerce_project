from django.contrib import admin
from .models import Customer, Product, Cart, CartItem

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