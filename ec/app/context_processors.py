from .models import Cart, Notification, WishlistItem


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


def unread_notifications_count(request):
    """Context processor returning the number of unread notifications for the authenticated user."""
    if request.user.is_authenticated:
        try:
            count = Notification.objects.filter(recipient=request.user, is_read=False).count()
            return {'unread_notifications_count': count}
        except Exception:
            return {'unread_notifications_count': 0}
    return {'unread_notifications_count': 0}


def wishlist_item_count(request):
    """Context processor returning the number of items in the authenticated user's wishlist."""
    if request.user.is_authenticated:
        try:
            count = WishlistItem.objects.filter(user=request.user).count()
            return {'wishlist_item_count': count}
        except Exception:
            return {'wishlist_item_count': 0}
    return {'wishlist_item_count': 0}
