from .models import Cart


def cart_item_count(request):
    """Context processor returning the number of distinct cart items for the authenticated user."""
    if request.user.is_authenticated:
        try:
            cart = Cart.objects.filter(user=request.user).first()
            if cart:
                return {'cart_item_count': cart.items.count()}
        except Exception:
            return {'cart_item_count': 0}
    return {'cart_item_count': 0}
