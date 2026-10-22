from django.urls import path

from .forms import LoginForm
from . import views
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static 
from .forms import LoginForm, MyPasswordResetForm, MySetPasswordForm    



urlpatterns = [
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('search/', views.ProductCatalogView.as_view(), name='search'),
    path('products/', views.ProductCatalogView.as_view(), name='products'),
    path('category/<slug:val>', views.CategoryView.as_view(), name='category'),
    path('product-detail/<int:pk>', views.ProductDetail.as_view(), name='product-detail'),
    path('category-title/<val>', views.CategoryTitle.as_view(), name='category-title'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('address/', views.AddressView.as_view(), name='address'),
    
    # Cart URLs
    path('add-to-cart/', views.AddToCartView.as_view(), name='add-to-cart'),
    path('cart/', views.ShowCartView.as_view(), name='show-cart'),
    path('plus-cart/', views.PlusCartView.as_view(), name='plus-cart'),
    path('minus-cart/', views.MinusCartView.as_view(), name='minus-cart'),
    path('remove-cart/', views.RemoveCartView.as_view(), name='remove-cart'),
    path('update-cart/', views.UpdateCartView.as_view(), name='update-cart'),
    
    # Checkout & Order URLs
    path('checkout/', views.CheckoutView.as_view(), name='checkout'),
    path('place-order/', views.PlaceOrderView.as_view(), name='place-order'),
    path('orders/', views.OrderListView.as_view(), name='orders'),
    path('orders/<int:pk>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('orders/<int:pk>/cancel/', views.OrderCancelView.as_view(), name='order-cancel'),
    path('orders/<int:pk>/confirmation/', views.OrderConfirmationView.as_view(), name='order-confirmation'),

    # Staff Fulfillment URLs
    path('staff/orders/', views.StaffOrderQueueView.as_view(), name='staff-orders'),
    path('staff/orders/<int:pk>/', views.StaffOrderDetailView.as_view(), name='staff-order-detail'),
    path('staff/orders/<int:pk>/transition/', views.StaffOrderTransitionView.as_view(), name='staff-order-transition'),

    # Payment URLs
    path('payments/sslcommerz/initiate/<int:order_id>/', views.SSLCommerzInitiateView.as_view(), name='sslcommerz-initiate'),
    path('payments/sslcommerz/success/', views.SSLCommerzSuccessView.as_view(), name='sslcommerz-success'),
    path('payments/sslcommerz/fail/', views.SSLCommerzFailView.as_view(), name='sslcommerz-fail'),
    path('payments/sslcommerz/cancel/', views.SSLCommerzCancelView.as_view(), name='sslcommerz-cancel'),
    path('payments/sslcommerz/ipn/', views.SSLCommerzIPNView.as_view(), name='sslcommerz-ipn'),

    # Customer Notification URLs
    path('notifications/', views.NotificationListView.as_view(), name='notifications'),
    path('notifications/<int:pk>/read/', views.NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('notifications/mark-all-read/', views.NotificationMarkAllReadView.as_view(), name='notification-mark-all-read'),

    # Wishlist URLs
    path('wishlist/', views.WishlistListView.as_view(), name='wishlist'),
    path('wishlist/add/', views.AddToWishlistView.as_view(), name='add-to-wishlist'),
    path('wishlist/remove/', views.RemoveFromWishlistView.as_view(), name='remove-from-wishlist'),
    path('wishlist/remove/<int:pk>/', views.RemoveFromWishlistView.as_view(), name='remove-from-wishlist-pk'),

    # Product Review URLs
    path('product/<int:pk>/review/', views.SubmitReviewView.as_view(), name='submit-review'),
    path('review/<int:pk>/delete/', views.DeleteReviewView.as_view(), name='delete-review'),
    
    # login authentication
    path('customerregistration/', views.CustomerRegistrationView.as_view(), name='customerregistration'),
    path('accounts/login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='app/password_reset.html'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='app/password_reset_done.html'), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='app/password_reset_confirm.html'), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(template_name='app/password_reset_complete.html'), name='password_reset_complete'),
]
