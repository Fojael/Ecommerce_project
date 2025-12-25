from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('category/<slug:val>', views.CategoryView.as_view(), name='category'),
    path('product-detail/<int:pk>', views.ProductDetail.as_view(), name='product-detail'),
    path('category-title/<val>', views.CategoryTitle.as_view(), name='category-title'),
    
    #login authentication
    path('customerregistration/', views.CustomerRegistrationView.as_view(), name='customerregistration'),
]
