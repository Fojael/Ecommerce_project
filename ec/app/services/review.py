import logging
from django.db import models
from app.models import OrderItem, ProductReview

logger = logging.getLogger(__name__)


def can_user_review_product(user, product):
    """
    Determines whether a user is eligible to review a product.
    A user is eligible ONLY IF they have at least one delivered order containing the product.
    Returns (eligible: bool, reason: str).
    """
    if not user or not user.is_authenticated:
        return False, "You must be logged in to review this product."

    has_delivered_order = OrderItem.objects.filter(
        order__user=user,
        order__status='DELIVERED',
        product=product
    ).exists()

    if not has_delivered_order:
        return (
            False,
            "Only verified purchasers who have received delivery of this product can write a review."
        )

    return True, "Eligible to review."


def get_product_review_summary(product):
    """
    Computes review count and average rating for a product using APPROVED reviews only.
    Returns dict: {'count': int, 'average_rating': float}.
    """
    approved_reviews = ProductReview.objects.filter(product=product, status='APPROVED')
    count = approved_reviews.count()
    avg_data = approved_reviews.aggregate(models.Avg('rating'))
    avg_val = avg_data.get('rating__avg') or 0.0
    return {
        'count': count,
        'average_rating': round(float(avg_val), 1)
    }

