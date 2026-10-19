from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from decimal import Decimal
from unittest.mock import patch
from django.db.models import ProtectedError
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.core import mail
from app.models import (
    Customer, Product, Cart, CartItem, Order, OrderItem, Payment, StockAdjustment,
    OrderStatusHistory, Notification
)
from app.services.inventory import (
    adjust_stock,
    deduct_order_stock,
    restore_order_stock,
    InsufficientStockError,
)



class RegistrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.registration_url = reverse('customerregistration')
        self.login_url = reverse('login')
        self.profile_url = reverse('profile')

    def test_get_registration_page(self):
        response = self.client.get(self.registration_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'app/customerregistration.html')

    def test_valid_registration_creates_user_and_redirects(self):
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'password1': 'StrongPass123!@#',
            'password2': 'StrongPass123!@#',
        }
        response = self.client.post(self.registration_url, data)
        self.assertRedirects(response, self.login_url)
        self.assertTrue(User.objects.filter(username='newuser').exists())
        user = User.objects.get(username='newuser')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertTrue(user.check_password('StrongPass123!@#'))

    def test_invalid_registration_does_not_create_user(self):
        initial_count = User.objects.count()
        data = {
            'username': 'mismatcheduser',
            'email': 'bad@example.com',
            'first_name': 'Bad',
            'last_name': 'User',
            'password1': 'Password123!',
            'password2': 'DifferentPassword456!',
        }
        response = self.client.post(self.registration_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), initial_count)
        self.assertFalse(User.objects.filter(username='mismatcheduser').exists())

    def test_authenticated_user_visiting_registration_redirects_to_profile(self):
        user = User.objects.create_user(username='authuser', password='Password123!')
        self.client.login(username='authuser', password='Password123!')
        response = self.client.get(self.registration_url)
        self.assertRedirects(response, self.profile_url)


class LoginTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.login_url = reverse('login')
        self.profile_url = reverse('profile')
        self.user = User.objects.create_user(username='testloginuser', password='SecretPassword123!')

    def test_successful_login_redirects_to_profile(self):
        data = {
            'username': 'testloginuser',
            'password': 'SecretPassword123!',
        }
        response = self.client.post(self.login_url, data)
        self.assertRedirects(response, self.profile_url)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_wrong_credentials_fails(self):
        data = {
            'username': 'testloginuser',
            'password': 'WrongPassword!',
        }
        response = self.client.post(self.login_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_authenticated_user_visiting_login_redirects_to_profile(self):
        self.client.login(username='testloginuser', password='SecretPassword123!')
        response = self.client.get(self.login_url)
        self.assertRedirects(response, self.profile_url)


class RememberMeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.login_url = reverse('login')
        self.user = User.objects.create_user(username='rememberuser', password='RememberPassword123!')

    def test_remember_me_checked_sets_expiry_to_two_weeks(self):
        data = {
            'username': 'rememberuser',
            'password': 'RememberPassword123!',
            'remember_me': True,
        }
        response = self.client.post(self.login_url, data)
        self.assertRedirects(response, reverse('profile'))
        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertEqual(session.get_expiry_age(), 1209600)

    def test_remember_me_unchecked_expires_on_browser_close(self):
        data = {
            'username': 'rememberuser',
            'password': 'RememberPassword123!',
        }
        response = self.client.post(self.login_url, data)
        self.assertRedirects(response, reverse('profile'))
        session = self.client.session
        self.assertTrue(session.get_expire_at_browser_close())


class NextParameterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='nextuser', password='NextPassword123!')

    def test_anonymous_user_visiting_profile_redirects_with_next(self):
        response = self.client.get(reverse('profile'))
        expected_url = f"{reverse('login')}?next={reverse('profile')}"
        self.assertRedirects(response, expected_url)

    def test_login_with_next_returns_user_to_next(self):
        login_url_with_next = f"{reverse('login')}?next={reverse('profile')}"
        data = {
            'username': 'nextuser',
            'password': 'NextPassword123!',
            'next': reverse('profile'),
        }
        response = self.client.post(login_url_with_next, data)
        self.assertRedirects(response, reverse('profile'))


class LogoutTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='logoutuser', password='LogoutPass123!')
        self.logout_url = reverse('logout')
        self.login_url = reverse('login')

    def test_logout_requires_post(self):
        self.client.login(username='logoutuser', password='LogoutPass123!')
        response = self.client.get(self.logout_url)
        self.assertEqual(response.status_code, 405)  # Method Not Allowed in Django 6.0

    def test_logout_clears_authentication_and_redirects(self):
        self.client.login(username='logoutuser', password='LogoutPass123!')
        self.assertIn('_auth_user_id', self.client.session)
        response = self.client.post(self.logout_url)
        self.assertRedirects(response, self.login_url)
        self.assertNotIn('_auth_user_id', self.client.session)


class CustomerProfileTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='profileuser', password='ProfilePassword123!')
        self.profile_url = reverse('profile')

    def test_profile_requires_login(self):
        response = self.client.get(self.profile_url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.profile_url}")

    def test_first_submission_creates_one_customer(self):
        self.client.login(username='profileuser', password='ProfilePassword123!')
        self.assertEqual(Customer.objects.filter(user=self.user).count(), 0)
        data = {
            'name': 'Test Profile Name',
            'locality': 'Dhanmondi 27',
            'city': 'Dhaka',
            'mobile': '01711223344',
            'zipcode': 1209,
            'state': 'Dhaka',
        }
        response = self.client.post(self.profile_url, data)
        self.assertRedirects(response, self.profile_url)
        self.assertEqual(Customer.objects.filter(user=self.user).count(), 1)
        customer = Customer.objects.get(user=self.user)
        self.assertEqual(customer.name, 'Test Profile Name')
        self.assertEqual(customer.mobile, '01711223344')

    def test_second_submission_updates_same_customer_no_duplicates(self):
        self.client.login(username='profileuser', password='ProfilePassword123!')
        initial_data = {
            'name': 'Initial Name',
            'locality': 'Gulshan 1',
            'city': 'Dhaka',
            'mobile': '01811223344',
            'zipcode': 1212,
            'state': 'Dhaka',
        }
        self.client.post(self.profile_url, initial_data)
        self.assertEqual(Customer.objects.filter(user=self.user).count(), 1)

        updated_data = {
            'name': 'Updated Name',
            'locality': 'Banani',
            'city': 'Dhaka',
            'mobile': '01911223344',
            'zipcode': 1213,
            'state': 'Dhaka',
        }
        response = self.client.post(self.profile_url, updated_data)
        self.assertRedirects(response, self.profile_url)

        # Customer count must remain exactly 1
        self.assertEqual(Customer.objects.filter(user=self.user).count(), 1)
        customer = Customer.objects.get(user=self.user)
        self.assertEqual(customer.name, 'Updated Name')
        self.assertEqual(customer.locality, 'Banani')
        self.assertEqual(customer.mobile, '01911223344')

    def test_profile_get_displays_existing_data(self):
        self.client.login(username='profileuser', password='ProfilePassword123!')
        Customer.objects.create(
            user=self.user,
            name='Saved Name',
            locality='Mirpur 10',
            city='Dhaka',
            mobile='01511223344',
            zipcode=1216,
            state='Dhaka',
        )
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Saved Name')
        self.assertContains(response, 'Mirpur 10')
        self.assertContains(response, '01511223344')


class AddressTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='addressuser', password='AddressPassword123!')
        self.address_url = reverse('address')
        self.profile_url = reverse('profile')

    def test_anonymous_user_cannot_access_address(self):
        response = self.client.get(self.address_url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.address_url}")

    def test_authenticated_user_can_access_address(self):
        self.client.login(username='addressuser', password='AddressPassword123!')
        response = self.client.get(self.address_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'app/address.html')

    def test_address_page_is_distinct_from_profile_page(self):
        self.client.login(username='addressuser', password='AddressPassword123!')
        address_resp = self.client.get(self.address_url)
        profile_resp = self.client.get(self.profile_url)
        self.assertTemplateUsed(address_resp, 'app/address.html')
        self.assertTemplateUsed(profile_resp, 'app/profile.html')
        self.assertNotEqual(address_resp.content, profile_resp.content)

    def test_address_displays_customer_data_when_exists(self):
        self.client.login(username='addressuser', password='AddressPassword123!')
        Customer.objects.create(
            user=self.user,
            name='Address Customer',
            locality='Uttara Sector 3',
            city='Dhaka',
            mobile='01311223344',
            zipcode=1230,
            state='Dhaka',
        )
        response = self.client.get(self.address_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Address Customer')
        self.assertContains(response, 'Uttara Sector 3')
        self.assertContains(response, '01311223344')

    def test_address_displays_helpful_message_when_no_customer(self):
        self.client.login(username='addressuser', password='AddressPassword123!')
        response = self.client.get(self.address_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No Address Found')
        self.assertContains(response, reverse('profile'))


class CatalogTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.p1 = Product.objects.create(
            title="Fresh Cow Milk",
            selling_price=100.0,
            discounted_price=85.0,
            description="Pure cow milk",
            category="ML"
        )
        self.p2 = Product.objects.create(
            title="Premium Curd",
            selling_price=80.0,
            discounted_price=70.0,
            description="Healthy curd",
            category="CR"
        )

    def test_category_view(self):
        response = self.client.get(reverse('category', args=['ML']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fresh Cow Milk")

    def test_category_title_view(self):
        response = self.client.get(reverse('category-title', args=['Fresh Cow Milk']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fresh Cow Milk")

    def test_product_detail(self):
        response = self.client.get(reverse('product-detail', args=[self.p1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fresh Cow Milk")
        self.assertContains(response, "85.0")

    def test_invalid_product_returns_404(self):
        response = self.client.get(reverse('product-detail', args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_invalid_category_title_does_not_crash(self):
        response = self.client.get(reverse('category-title', args=['Nonexistent Product Title']))
        self.assertEqual(response.status_code, 200)


class CartAuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.product = Product.objects.create(
            title="Test Milk",
            selling_price=100.0,
            discounted_price=90.0,
            category="ML"
        )

    def test_anonymous_cart_access_is_blocked(self):
        response = self.client.get(reverse('show-cart'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('show-cart')}")

    def test_anonymous_add_to_cart_is_blocked(self):
        response = self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 1})
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('add-to-cart')}")

    def test_anonymous_plus_cart_is_blocked(self):
        response = self.client.post(reverse('plus-cart'), {'prod_id': self.product.id})
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('plus-cart')}")

    def test_anonymous_minus_cart_is_blocked(self):
        response = self.client.post(reverse('minus-cart'), {'prod_id': self.product.id})
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('minus-cart')}")

    def test_anonymous_remove_cart_is_blocked(self):
        response = self.client.post(reverse('remove-cart'), {'prod_id': self.product.id})
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('remove-cart')}")


class CartOperationsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='cartuser', password='CartPassword123!')
        self.client.login(username='cartuser', password='CartPassword123!')
        self.product = Product.objects.create(
            title="Butter Milk",
            selling_price=60.0,
            discounted_price=50.0,
            category="ML"
        )

    def test_authenticated_cart_can_be_created(self):
        response = self.client.get(reverse('show-cart'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'app/cart.html')

    def test_add_product_to_cart(self):
        response = self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 2})
        self.assertRedirects(response, reverse('show-cart'))
        cart = Cart.objects.get(user=self.user)
        self.assertEqual(cart.items.count(), 1)
        item = cart.items.first()
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.quantity, 2)

    def test_adding_same_product_increments_quantity(self):
        self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 2})
        self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 3})
        cart = Cart.objects.get(user=self.user)
        self.assertEqual(cart.items.count(), 1)
        item = cart.items.first()
        self.assertEqual(item.quantity, 5)

    def test_duplicate_cart_item_is_prevented(self):
        cart, _ = Cart.objects.get_or_create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        with self.assertRaises(Exception):
            CartItem.objects.create(cart=cart, product=self.product, quantity=1)

    def test_plus_quantity(self):
        self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 1})
        cart = Cart.objects.get(user=self.user)
        item = cart.items.first()
        response = self.client.post(reverse('plus-cart'), {'item_id': item.id})
        self.assertRedirects(response, reverse('show-cart'))
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)

    def test_minus_quantity(self):
        self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 3})
        cart = Cart.objects.get(user=self.user)
        item = cart.items.first()
        response = self.client.post(reverse('minus-cart'), {'item_id': item.id})
        self.assertRedirects(response, reverse('show-cart'))
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)

    def test_minus_at_quantity_1_removes_item(self):
        self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 1})
        cart = Cart.objects.get(user=self.user)
        item = cart.items.first()
        response = self.client.post(reverse('minus-cart'), {'item_id': item.id})
        self.assertRedirects(response, reverse('show-cart'))
        self.assertEqual(cart.items.count(), 0)

    def test_remove_item(self):
        self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 5})
        cart = Cart.objects.get(user=self.user)
        item = cart.items.first()
        response = self.client.post(reverse('remove-cart'), {'item_id': item.id})
        self.assertRedirects(response, reverse('show-cart'))
        self.assertEqual(cart.items.count(), 0)

    def test_empty_cart(self):
        response = self.client.get(reverse('show-cart'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your Cart is Empty")


class CartSecurityAndProtectionTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='u1', password='Password123!')
        self.user2 = User.objects.create_user(username='u2', password='Password123!')
        self.p1 = Product.objects.create(title="P1", selling_price=100.0, discounted_price=80.0, category="ML")
        self.p2 = Product.objects.create(title="P2", selling_price=50.0, discounted_price=40.0, category="CR")

        self.cart1 = Cart.objects.create(user=self.user1)
        self.cart2 = Cart.objects.create(user=self.user2)

        self.item1 = CartItem.objects.create(cart=self.cart1, product=self.p1, quantity=2)
        self.item2 = CartItem.objects.create(cart=self.cart2, product=self.p2, quantity=4)

    def test_user_cannot_modify_another_users_cart(self):
        client = Client()
        client.login(username='u1', password='Password123!')
        client.post(reverse('plus-cart'), {'item_id': self.item2.id})
        self.item2.refresh_from_db()
        self.assertEqual(self.item2.quantity, 4)

        client.post(reverse('minus-cart'), {'item_id': self.item2.id})
        self.item2.refresh_from_db()
        self.assertEqual(self.item2.quantity, 4)

        client.post(reverse('remove-cart'), {'item_id': self.item2.id})
        self.assertTrue(CartItem.objects.filter(id=self.item2.id).exists())

    def test_user_cannot_see_another_users_cart(self):
        client = Client()
        client.login(username='u1', password='Password123!')
        response = client.get(reverse('show-cart'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "P1")
        self.assertNotContains(response, "P2")

    def test_cart_mutations_require_post(self):
        client = Client()
        client.login(username='u1', password='Password123!')
        response = client.get(reverse('plus-cart'), {'item_id': self.item1.id})
        self.assertEqual(response.status_code, 405)
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.quantity, 2)

    def test_csrf_protection_remains_enabled(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username='u1', password='Password123!')
        response = csrf_client.post(reverse('plus-cart'), {'item_id': self.item1.id})
        self.assertEqual(response.status_code, 403)


class CartCalculationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='calcuser', password='Password123!')
        self.client.login(username='calcuser', password='Password123!')
        self.p1 = Product.objects.create(title="Product 1", selling_price=100.0, discounted_price=80.0, category="ML")
        self.p2 = Product.objects.create(title="Product 2", selling_price=50.0, discounted_price=45.0, category="CR")

    def test_item_subtotal(self):
        cart = Cart.objects.create(user=self.user)
        item = CartItem.objects.create(cart=cart, product=self.p1, quantity=3)
        self.assertEqual(item.item_subtotal, 80.0 * 3)

    def test_cart_subtotal(self):
        self.client.post(reverse('add-to-cart'), {'prod_id': self.p1.id, 'quantity': 2})
        self.client.post(reverse('add-to-cart'), {'prod_id': self.p2.id, 'quantity': 3})
        response = self.client.get(reverse('show-cart'))
        expected_subtotal = (80.0 * 2) + (45.0 * 3)
        self.assertEqual(response.context['cart_subtotal'], expected_subtotal)

    def test_total_discount(self):
        self.client.post(reverse('add-to-cart'), {'prod_id': self.p1.id, 'quantity': 2})
        self.client.post(reverse('add-to-cart'), {'prod_id': self.p2.id, 'quantity': 3})
        response = self.client.get(reverse('show-cart'))
        expected_discount = ((100.0 - 80.0) * 2) + ((50.0 - 45.0) * 3)
        self.assertEqual(response.context['total_discount'], expected_discount)

    def test_delivery_charge_not_included_in_subtotal(self):
        self.client.post(reverse('add-to-cart'), {'prod_id': self.p1.id, 'quantity': 1})
        response = self.client.get(reverse('show-cart'))
        self.assertEqual(response.context['cart_subtotal'], 80.0)

    def test_frontend_submitted_price_cannot_manipulate_backend_calculations(self):
        self.client.post(reverse('add-to-cart'), {
            'prod_id': self.p1.id,
            'quantity': 1,
            'price': 1.0,
            'discounted_price': 1.0,
            'selling_price': 1.0
        })
        response = self.client.get(reverse('show-cart'))
        self.assertEqual(response.context['cart_subtotal'], 80.0)

    def test_adding_to_cart_does_not_alter_product_data(self):
        initial_sp = self.p1.selling_price
        initial_dp = self.p1.discounted_price
        initial_title = self.p1.title
        self.client.post(reverse('add-to-cart'), {'prod_id': self.p1.id, 'quantity': 5})
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.selling_price, initial_sp)
        self.assertEqual(self.p1.discounted_price, initial_dp)
        self.assertEqual(self.p1.title, initial_title)


# ==========================================
# PHASE 3 TESTS: CHECKOUT & ORDER CREATION
# ==========================================

class CheckoutTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='buyer1', password='Password123!')
        self.product = Product.objects.create(
            title="Ghee Jar",
            selling_price=600.0,
            discounted_price=550.0,
            description="Pure ghee",
            category="GH"
        )
        self.customer = Customer.objects.create(
            user=self.user,
            name="Rahim Uddin",
            locality="Dhanmondi 27",
            city="Dhaka",
            mobile="01711000000",
            zipcode=1209,
            state="Dhaka"
        )
        self.checkout_url = reverse('checkout')

    def test_anonymous_user_redirected_to_login_from_checkout(self):
        response = self.client.get(self.checkout_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_authenticated_user_with_empty_cart_redirected_to_cart(self):
        self.client.login(username='buyer1', password='Password123!')
        response = self.client.get(self.checkout_url)
        self.assertRedirects(response, reverse('show-cart'))

    def test_authenticated_user_without_customer_profile_redirected_to_profile(self):
        user_no_profile = User.objects.create_user(username='noprofile', password='Password123!')
        cart = Cart.objects.create(user=user_no_profile)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        self.client.login(username='noprofile', password='Password123!')
        response = self.client.get(self.checkout_url)
        self.assertRedirects(response, reverse('profile'))

    def test_authenticated_user_with_incomplete_address_redirected_to_profile(self):
        user_inc = User.objects.create_user(username='incomplete', password='Password123!')
        Customer.objects.create(
            user=user_inc,
            name="Test Name",
            locality="",  # incomplete
            city="Dhaka",
            mobile="01700000000",
            state="Dhaka"
        )
        cart = Cart.objects.create(user=user_inc)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        self.client.login(username='incomplete', password='Password123!')
        response = self.client.get(self.checkout_url)
        self.assertRedirects(response, reverse('profile'))

    def test_authenticated_user_with_valid_cart_and_address_accesses_checkout(self):
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        self.client.login(username='buyer1', password='Password123!')
        response = self.client.get(self.checkout_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'app/checkout.html')

    def test_checkout_displays_customer_shipping_address(self):
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        self.client.login(username='buyer1', password='Password123!')
        response = self.client.get(self.checkout_url)
        self.assertEqual(response.context['customer'], self.customer)
        self.assertContains(response, "Rahim Uddin")
        self.assertContains(response, "Dhanmondi 27")
        self.assertContains(response, "01711000000")

    def test_checkout_displays_cart_items_and_financial_summary(self):
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        self.client.login(username='buyer1', password='Password123!')
        response = self.client.get(self.checkout_url)
        self.assertEqual(response.context['subtotal'], Decimal('1100.00'))
        self.assertEqual(response.context['delivery_charge'], Decimal('70.00'))
        self.assertEqual(response.context['grand_total'], Decimal('1170.00'))
        self.assertEqual(response.context['total_discount'], Decimal('100.00'))


class OrderCreationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='buyer2', password='Password123!')
        self.customer = Customer.objects.create(
            user=self.user,
            name="Fatima Begum",
            locality="Mirpur 10",
            city="Dhaka",
            mobile="01811223344",
            zipcode=1216,
            state="Dhaka"
        )
        self.product1 = Product.objects.create(
            title="Cow Milk 1L",
            selling_price=100.0,
            discounted_price=85.0,
            description="Pure cow milk",
            category="ML"
        )
        self.product2 = Product.objects.create(
            title="Curd Sweet",
            selling_price=250.0,
            discounted_price=220.0,
            description="Sweet curd",
            category="CR"
        )
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product1, quantity=2)
        CartItem.objects.create(cart=self.cart, product=self.product2, quantity=1)
        self.client.login(username='buyer2', password='Password123!')
        self.place_order_url = reverse('place-order')

    def test_order_created_successfully(self):
        response = self.client.post(self.place_order_url)
        self.assertEqual(Order.objects.filter(user=self.user).count(), 1)
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order-confirmation', kwargs={'pk': order.pk}))

    def test_order_item_created_with_correct_product_and_order(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.items.count(), 2)
        p_ids = set(order.items.values_list('product_id', flat=True))
        self.assertEqual(p_ids, {self.product1.id, self.product2.id})

    def test_order_item_stores_correct_quantity(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        item1 = order.items.get(product=self.product1)
        item2 = order.items.get(product=self.product2)
        self.assertEqual(item1.quantity, 2)
        self.assertEqual(item2.quantity, 1)

    def test_order_item_stores_correct_historical_unit_price(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        item1 = order.items.get(product=self.product1)
        item2 = order.items.get(product=self.product2)
        self.assertEqual(item1.unit_price, Decimal('85.00'))
        self.assertEqual(item2.unit_price, Decimal('220.00'))

    def test_order_item_stores_correct_item_subtotal(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        item1 = order.items.get(product=self.product1)
        item2 = order.items.get(product=self.product2)
        self.assertEqual(item1.subtotal, Decimal('170.00'))
        self.assertEqual(item2.subtotal, Decimal('220.00'))

    def test_order_stores_correct_subtotal(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        expected_subtotal = Decimal('170.00') + Decimal('220.00')
        self.assertEqual(order.subtotal, expected_subtotal)

    def test_order_stores_correct_delivery_charge(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.delivery_charge, Decimal('70.00'))

    def test_order_stores_correct_grand_total(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        expected_grand_total = Decimal('390.00') + Decimal('70.00')
        self.assertEqual(order.grand_total, expected_grand_total)

    def test_order_stores_correct_total_discount(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        # discount: ((100-85)*2) + ((250-220)*1) = 30 + 30 = 60.00
        self.assertEqual(order.total_discount, Decimal('60.00'))

    def test_cart_cleared_after_successful_order(self):
        self.assertEqual(self.cart.items.count(), 2)
        self.client.post(self.place_order_url)
        self.assertEqual(self.cart.items.count(), 0)

    def test_order_status_default_is_pending(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.status, 'PENDING')

    def test_payment_status_default_is_pending(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.payment_status, 'PENDING')

    def test_order_number_is_unique_and_generated(self):
        self.client.post(self.place_order_url)
        order = Order.objects.get(user=self.user)
        self.assertTrue(order.order_number.startswith('ORD-'))
        self.assertGreater(len(order.order_number), 10)


class HistoricalSnapshotTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='snapshot_user', password='Password123!')
        self.customer = Customer.objects.create(
            user=self.user,
            name="Original Customer",
            locality="Banani Block B",
            city="Dhaka",
            mobile="01799887766",
            zipcode=1213,
            state="Dhaka"
        )
        self.product = Product.objects.create(
            title="Premium Paneer",
            selling_price=500.0,
            discounted_price=450.0,
            description="Paneer",
            category="PN"
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        self.client.login(username='snapshot_user', password='Password123!')
        self.client.post(reverse('place-order'))
        self.order = Order.objects.get(user=self.user)
        self.order_item = self.order.items.get(product=self.product)

    def test_order_item_unit_price_snapshot_preserved_when_product_price_changes(self):
        # Product price changes after order
        self.product.discounted_price = 550.0
        self.product.selling_price = 600.0
        self.product.save()

        self.order_item.refresh_from_db()
        self.assertEqual(self.order_item.unit_price, Decimal('450.00'))
        self.assertEqual(self.order_item.subtotal, Decimal('900.00'))

    def test_order_item_product_name_snapshot_preserved_when_product_title_changes(self):
        # Product title changes after order
        self.product.title = "Updated Paneer Brand"
        self.product.save()

        self.order_item.refresh_from_db()
        self.assertEqual(self.order_item.product_name, "Premium Paneer")

    def test_order_shipping_address_snapshot_preserved_when_customer_profile_changes(self):
        # Customer updates address in profile
        self.customer.name = "New Name"
        self.customer.locality = "Gulshan 2"
        self.customer.city = "Dhaka"
        self.customer.mobile = "01700112233"
        self.customer.zipcode = 1212
        self.customer.state = "Dhaka"
        self.customer.save()

        self.order.refresh_from_db()
        self.assertEqual(self.order.shipping_name, "Original Customer")
        self.assertEqual(self.order.shipping_locality, "Banani Block B")
        self.assertEqual(self.order.shipping_mobile, "01799887766")
        self.assertEqual(self.order.shipping_zipcode, "1213")


class OrderSecurityTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='sec_user1', password='Password123!')
        self.user2 = User.objects.create_user(username='sec_user2', password='Password123!')
        self.customer1 = Customer.objects.create(
            user=self.user1,
            name="User One",
            locality="Uttara Sector 3",
            city="Dhaka",
            mobile="01711111111",
            zipcode=1230,
            state="Dhaka"
        )
        self.product = Product.objects.create(
            title="Lassi Sweet",
            selling_price=80.0,
            discounted_price=70.0,
            description="Lassi",
            category="LS"
        )
        cart1 = Cart.objects.create(user=self.user1)
        CartItem.objects.create(cart=cart1, product=self.product, quantity=1)

        client1 = Client()
        client1.login(username='sec_user1', password='Password123!')
        client1.post(reverse('place-order'))
        self.order1 = Order.objects.get(user=self.user1)

    def test_get_request_to_place_order_does_not_create_order(self):
        client = Client()
        client.login(username='sec_user1', password='Password123!')
        cart = Cart.objects.get(user=self.user1)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        initial_order_count = Order.objects.count()
        response = client.get(reverse('place-order'))
        self.assertRedirects(response, reverse('checkout'))
        self.assertEqual(Order.objects.count(), initial_order_count)

    def test_place_order_csrf_protection_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username='sec_user1', password='Password123!')
        # Post without CSRF token
        response = client.post(reverse('place-order'))
        self.assertEqual(response.status_code, 403)

    def test_user_cannot_view_another_users_order_detail(self):
        client2 = Client()
        client2.login(username='sec_user2', password='Password123!')
        response = client2.get(reverse('order-detail', kwargs={'pk': self.order1.pk}))
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_view_another_users_order_confirmation(self):
        client2 = Client()
        client2.login(username='sec_user2', password='Password123!')
        response = client2.get(reverse('order-confirmation', kwargs={'pk': self.order1.pk}))
        self.assertEqual(response.status_code, 404)

    def test_client_submitted_price_ignored(self):
        client = Client()
        user3 = User.objects.create_user(username='tamperer', password='Password123!')
        Customer.objects.create(
            user=user3,
            name="Tamperer",
            locality="Road 1",
            city="Dhaka",
            mobile="01722334455",
            zipcode=1200,
            state="Dhaka"
        )
        cart = Cart.objects.create(user=user3)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        client.login(username='tamperer', password='Password123!')

        client.post(reverse('place-order'), {
            'price': '1.00',
            'discounted_price': '1.00',
            'subtotal': '1.00',
            'delivery_charge': '0.00',
            'grand_total': '1.00',
        })
        order = Order.objects.get(user=user3)
        self.assertEqual(order.subtotal, Decimal('70.00'))
        self.assertEqual(order.delivery_charge, Decimal('70.00'))
        self.assertEqual(order.grand_total, Decimal('140.00'))

    def test_client_submitted_subtotal_ignored(self):
        order = self.order1
        self.assertEqual(order.subtotal, Decimal('70.00'))

    def test_client_submitted_delivery_charge_ignored(self):
        order = self.order1
        self.assertEqual(order.delivery_charge, Decimal('70.00'))

    def test_client_submitted_grand_total_ignored(self):
        order = self.order1
        self.assertEqual(order.grand_total, Decimal('140.00'))


class OrderEdgeCasesAndIntegrityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='edge_user', password='Password123!')
        self.customer = Customer.objects.create(
            user=self.user,
            name="Edge User",
            locality="Chawkbazar",
            city="Chattogram",
            mobile="01800112233",
            zipcode=4000,
            state="Chattogram"
        )
        self.p1 = Product.objects.create(
            title="Curd Pot",
            selling_price=120.0,
            discounted_price=100.0,
            description="Curd",
            category="CR"
        )
        self.p2 = Product.objects.create(
            title="Cheese Block",
            selling_price=350.0,
            discounted_price=300.0,
            description="Cheese",
            category="CZ"
        )
        self.cart = Cart.objects.create(user=self.user)
        self.client.login(username='edge_user', password='Password123!')

    def test_place_order_with_empty_cart_fails(self):
        response = self.client.post(reverse('place-order'))
        self.assertRedirects(response, reverse('show-cart'))
        self.assertEqual(Order.objects.filter(user=self.user).count(), 0)

    def test_place_order_without_customer_profile_fails(self):
        user_no_cust = User.objects.create_user(username='nocust', password='Password123!')
        cart = Cart.objects.create(user=user_no_cust)
        CartItem.objects.create(cart=cart, product=self.p1, quantity=1)
        client = Client()
        client.login(username='nocust', password='Password123!')
        response = client.post(reverse('place-order'))
        self.assertRedirects(response, reverse('profile'))
        self.assertEqual(Order.objects.filter(user=user_no_cust).count(), 0)

    def test_place_order_with_incomplete_address_fails(self):
        user_inc = User.objects.create_user(username='inc_cust', password='Password123!')
        Customer.objects.create(
            user=user_inc,
            name="Incomplete",
            locality="",
            city="Dhaka",
            mobile="01711223344",
            state="Dhaka"
        )
        cart = Cart.objects.create(user=user_inc)
        CartItem.objects.create(cart=cart, product=self.p1, quantity=1)
        client = Client()
        client.login(username='inc_cust', password='Password123!')
        response = client.post(reverse('place-order'))
        self.assertRedirects(response, reverse('profile'))
        self.assertEqual(Order.objects.filter(user=user_inc).count(), 0)

    def test_place_order_with_multiple_items_and_varying_quantities(self):
        CartItem.objects.create(cart=self.cart, product=self.p1, quantity=3)
        CartItem.objects.create(cart=self.cart, product=self.p2, quantity=2)
        response = self.client.post(reverse('place-order'))
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.items.count(), 2)
        # p1: 100 * 3 = 300, p2: 300 * 2 = 600 => subtotal 900
        self.assertEqual(order.subtotal, Decimal('900.00'))
        self.assertEqual(order.delivery_charge, Decimal('70.00'))
        self.assertEqual(order.grand_total, Decimal('970.00'))

    def test_product_deletion_is_protected_when_referenced_in_order_item(self):
        CartItem.objects.create(cart=self.cart, product=self.p1, quantity=1)
        self.client.post(reverse('place-order'))
        order = Order.objects.get(user=self.user)
        self.assertTrue(order.items.filter(product=self.p1).exists())
        # Deleting p1 must raise ProtectedError
        with self.assertRaises(ProtectedError):
            self.p1.delete()

    def test_orders_list_shows_only_current_users_orders(self):
        CartItem.objects.create(cart=self.cart, product=self.p1, quantity=1)
        self.client.post(reverse('place-order'))
        order1 = Order.objects.get(user=self.user)

        other_user = User.objects.create_user(username='other_orders_user', password='Password123!')
        other_order = Order.objects.create(
            user=other_user,
            shipping_name="Other",
            shipping_mobile="01711111111",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('100.00'),
            grand_total=Decimal('170.00')
        )

        response = self.client.get(reverse('orders'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(order1, response.context['orders'])
        self.assertNotIn(other_order, response.context['orders'])

    def test_orders_list_orders_by_newest_first(self):
        o1 = Order.objects.create(
            user=self.user,
            shipping_name="User",
            shipping_mobile="01700000000",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('100.00'),
            grand_total=Decimal('170.00')
        )
        o2 = Order.objects.create(
            user=self.user,
            shipping_name="User",
            shipping_mobile="01700000000",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('200.00'),
            grand_total=Decimal('270.00')
        )
        response = self.client.get(reverse('orders'))
        orders = list(response.context['orders'])
        self.assertEqual(orders[0], o2)
        self.assertEqual(orders[1], o1)


class OrderTransactionSafetyAndIdempotencyTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='tx_user', password='Password123!')
        self.customer = Customer.objects.create(
            user=self.user,
            name="Tx User",
            locality="Kazir Dewri",
            city="Chattogram",
            mobile="01900112233",
            zipcode=4000,
            state="Chattogram"
        )
        self.product = Product.objects.create(
            title="Milkshake Bottle",
            selling_price=150.0,
            discounted_price=130.0,
            description="Milkshake",
            category="MS"
        )
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        self.client.login(username='tx_user', password='Password123!')

    def test_failure_during_order_item_creation_rolls_back_order(self):
        initial_order_count = Order.objects.count()
        initial_cart_item_count = CartItem.objects.count()

        with patch('app.views.OrderItem.objects.create', side_effect=RuntimeError("Simulated DB failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('place-order'))

        # Both the Order and Cart deletion must have rolled back
        self.assertEqual(Order.objects.count(), initial_order_count)
        self.assertEqual(CartItem.objects.count(), initial_cart_item_count)

    def test_failed_order_creation_does_not_clear_cart(self):
        self.assertEqual(self.cart.items.count(), 1)
        with patch('app.views.OrderItem.objects.create', side_effect=RuntimeError("Simulated DB failure")):
            try:
                self.client.post(reverse('place-order'))
            except RuntimeError:
                pass
        self.cart.refresh_from_db()
        self.assertEqual(self.cart.items.count(), 1)

    def test_duplicate_place_order_does_not_create_duplicate_orders(self):
        # First submission
        response1 = self.client.post(reverse('place-order'))
        self.assertEqual(Order.objects.filter(user=self.user).count(), 1)
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response1, reverse('order-confirmation', kwargs={'pk': order.pk}))
        # Immediate second submission (e.g., duplicate click/retry with empty cart)
        response2 = self.client.post(reverse('place-order'))
        # Must redirect to show-cart because cart is now empty
        self.assertRedirects(response2, reverse('show-cart'))
        # Only 1 order created in total
        self.assertEqual(Order.objects.filter(user=self.user).count(), 1)


# ==========================================================
# PHASE 4 TESTS: PAYMENT SYSTEM & SSLCOMMERZ SANDBOX
# ==========================================================

class PaymentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pay_user1', password='Password123!')
        self.order = Order.objects.create(
            user=self.user,
            shipping_name="Test Customer",
            shipping_mobile="01711223344",
            shipping_locality="Dhanmondi",
            shipping_city="Dhaka",
            shipping_zipcode="1209",
            shipping_state="Dhaka",
            subtotal=Decimal('500.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('570.00')
        )

    def test_payment_creation_and_defaults(self):
        payment = Payment.objects.create(
            order=self.order,
            payment_method='COD',
            amount=self.order.grand_total,
            currency='BDT'
        )
        self.assertEqual(payment.status, 'PENDING')
        self.assertEqual(payment.amount, Decimal('570.00'))
        self.assertEqual(payment.currency, 'BDT')
        self.assertTrue(payment.transaction_id.startswith('TX'))
        self.assertLessEqual(len(payment.transaction_id), 30)

    def test_payment_order_relationship(self):
        p1 = Payment.objects.create(order=self.order, payment_method='COD', amount=Decimal('570.00'))
        self.assertIn(p1, self.order.payments.all())
        self.assertEqual(p1.order, self.order)

    def test_payment_amount_and_currency(self):
        payment = Payment.objects.create(
            order=self.order,
            payment_method='SSLCOMMERZ',
            amount=Decimal('570.00'),
            currency='BDT'
        )
        self.assertEqual(payment.amount, Decimal('570.00'))
        self.assertEqual(payment.currency, 'BDT')

    def test_payment_transaction_id_uniqueness_and_length(self):
        p1 = Payment.objects.create(order=self.order, amount=Decimal('570.00'))
        p2 = Payment.objects.create(order=self.order, amount=Decimal('570.00'))
        self.assertNotEqual(p1.transaction_id, p2.transaction_id)
        self.assertLessEqual(len(p1.transaction_id), 30)
        self.assertLessEqual(len(p2.transaction_id), 30)

    def test_payment_status_choices(self):
        payment = Payment.objects.create(order=self.order, amount=Decimal('570.00'))
        valid_statuses = ['PENDING', 'PAID', 'FAILED', 'CANCELLED', 'REFUNDED']
        for s in valid_statuses:
            payment.status = s
            payment.save()
            payment.refresh_from_db()
            self.assertEqual(payment.status, s)

    def test_payment_method_choices(self):
        p_cod = Payment.objects.create(order=self.order, payment_method='COD', amount=Decimal('570.00'))
        p_ssl = Payment.objects.create(order=self.order, payment_method='SSLCOMMERZ', amount=Decimal('570.00'))
        self.assertEqual(p_cod.payment_method, 'COD')
        self.assertEqual(p_ssl.payment_method, 'SSLCOMMERZ')


class CODPaymentTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='cod_user', password='Password123!')
        self.customer = Customer.objects.create(
            user=self.user,
            name="COD Customer",
            locality="Mirpur",
            city="Dhaka",
            mobile="01711223344",
            zipcode=1216,
            state="Dhaka"
        )
        self.product = Product.objects.create(
            title="Curd Sweet",
            selling_price=150.0,
            discounted_price=120.0,
            description="Sweet Curd",
            category="CR"
        )
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        self.client.login(username='cod_user', password='Password123!')

    def test_place_order_with_cod_creates_pending_payment(self):
        response = self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        self.assertEqual(Order.objects.filter(user=self.user).count(), 1)
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order-confirmation', kwargs={'pk': order.pk}))

        self.assertEqual(order.payments.count(), 1)
        payment = order.payments.first()
        self.assertEqual(payment.payment_method, 'COD')
        self.assertEqual(payment.status, 'PENDING')

    def test_cod_payment_amount_equals_order_grand_total(self):
        self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        order = Order.objects.get(user=self.user)
        payment = order.payments.first()
        # subtotal: 120 * 2 = 240, delivery: 70 => 310
        self.assertEqual(payment.amount, Decimal('310.00'))
        self.assertEqual(payment.amount, order.grand_total)

    def test_cod_order_payment_status_remains_pending(self):
        self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.payment_status, 'PENDING')

    def test_cod_order_fulfillment_status_remains_pending(self):
        self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.status, 'PENDING')

    @patch('app.services.sslcommerz.requests.post')
    def test_cod_does_not_trigger_sslcommerz_request(self, mock_post):
        self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        mock_post.assert_not_called()


class SSLCommerzInitiationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='ssl_user', password='Password123!')
        self.customer = Customer.objects.create(
            user=self.user,
            name="SSL Customer",
            locality="Gulshan 1",
            city="Dhaka",
            mobile="01799887766",
            zipcode=1212,
            state="Dhaka"
        )
        self.product = Product.objects.create(
            title="Ghee Pure",
            selling_price=500.0,
            discounted_price=450.0,
            description="Pure Ghee",
            category="GH"
        )
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        self.client.login(username='ssl_user', password='Password123!')

    @patch('app.services.sslcommerz.requests.post')
    def test_place_order_with_sslcommerz_initiates_and_redirects_to_gateway(self, mock_post):
        gateway_target = "https://sandbox.sslcommerz.com/gwprocess/v4/gw.php?Q=testsession"
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': 'SUCCESS',
            'GatewayPageURL': gateway_target,
            'sessionkey': 'SESSION12345'
        }

        response = self.client.post(reverse('place-order'), {'payment_method': 'SSLCOMMERZ'})
        self.assertRedirects(response, gateway_target, fetch_redirect_response=False)

        order = Order.objects.get(user=self.user)
        self.assertEqual(order.payments.count(), 1)
        payment = order.payments.first()
        self.assertEqual(payment.payment_method, 'SSLCOMMERZ')
        self.assertEqual(payment.gateway_session_key, 'SESSION12345')

    def test_sslcommerz_initiate_requires_authentication(self):
        client = Client()
        order = Order.objects.create(
            user=self.user,
            shipping_name="Test",
            shipping_mobile="01700000000",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('450.00'),
            grand_total=Decimal('520.00')
        )
        response = client.post(reverse('sslcommerz-initiate', kwargs={'order_id': order.id}))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_sslcommerz_initiate_get_rejected(self):
        order = Order.objects.create(
            user=self.user,
            shipping_name="Test",
            shipping_mobile="01700000000",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('450.00'),
            grand_total=Decimal('520.00')
        )
        response = self.client.get(reverse('sslcommerz-initiate', kwargs={'order_id': order.id}))
        self.assertEqual(response.status_code, 405)

    @patch('app.services.sslcommerz.requests.post')
    def test_sslcommerz_initiate_for_own_order(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/gwprocess/v4/gw.php?Q=test',
            'sessionkey': 'SESSION_OWN'
        }
        order = Order.objects.create(
            user=self.user,
            shipping_name="Test",
            shipping_mobile="01700000000",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('450.00'),
            grand_total=Decimal('520.00')
        )
        response = self.client.post(reverse('sslcommerz-initiate', kwargs={'order_id': order.id}))
        self.assertEqual(response.status_code, 302)
        self.assertIn('GatewayPageURL', mock_post.return_value.json.return_value)

    def test_sslcommerz_initiate_cannot_access_another_users_order(self):
        other_user = User.objects.create_user(username='other_payer', password='Password123!')
        order = Order.objects.create(
            user=other_user,
            shipping_name="Other",
            shipping_mobile="01700000000",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('450.00'),
            grand_total=Decimal('520.00')
        )
        response = self.client.post(reverse('sslcommerz-initiate', kwargs={'order_id': order.id}))
        self.assertEqual(response.status_code, 404)

    def test_sslcommerz_initiate_rejects_already_paid_order(self):
        order = Order.objects.create(
            user=self.user,
            shipping_name="Paid Order",
            shipping_mobile="01700000000",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('450.00'),
            grand_total=Decimal('520.00'),
            payment_status='PAID'
        )
        response = self.client.post(reverse('sslcommerz-initiate', kwargs={'order_id': order.id}))
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': order.id}))

    def test_sslcommerz_initiate_nonexistent_order_returns_404(self):
        response = self.client.post(reverse('sslcommerz-initiate', kwargs={'order_id': 999999}))
        self.assertEqual(response.status_code, 404)

    @patch('app.services.sslcommerz.requests.post')
    def test_sslcommerz_initiate_uses_server_order_grand_total(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/gw',
            'sessionkey': 'SES123'
        }
        self.client.post(reverse('place-order'), {'payment_method': 'SSLCOMMERZ'})
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs['data']
        # subtotal: 450.00 + 70.00 delivery = 520.00
        self.assertEqual(payload['total_amount'], '520.00')
        self.assertEqual(payload['currency'], 'BDT')

    @patch('app.services.sslcommerz.requests.post')
    def test_sslcommerz_gateway_failure_handled_gracefully(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': 'FAILED',
            'failedreason': 'Store credential invalid'
        }
        response = self.client.post(reverse('place-order'), {'payment_method': 'SSLCOMMERZ'})
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': order.pk}))
        payment = order.payments.first()
        self.assertEqual(payment.status, 'FAILED')
        self.assertEqual(order.payment_status, 'FAILED')

    @patch('app.services.sslcommerz.requests.post', side_effect=Exception("Connection timeout"))
    def test_sslcommerz_network_timeout_handled_gracefully(self, mock_post):
        response = self.client.post(reverse('place-order'), {'payment_method': 'SSLCOMMERZ'})
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': order.pk}))
        payment = order.payments.first()
        self.assertEqual(payment.status, 'FAILED')

    @patch('app.services.sslcommerz.requests.post')
    def test_client_tampered_amount_ignored_during_sslcommerz_checkout(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/gw',
            'sessionkey': 'SES999'
        }
        self.client.post(reverse('place-order'), {
            'payment_method': 'SSLCOMMERZ',
            'amount': '1.00',
            'total_amount': '0.00',
            'grand_total': '9999.00'
        })
        payload = mock_post.call_args[1]['data']
        self.assertEqual(payload['total_amount'], '520.00')


class SSLCommerzCallbackTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='cb_user', password='Password123!')
        self.order = Order.objects.create(
            user=self.user,
            shipping_name="Callback Customer",
            shipping_mobile="01711223344",
            shipping_locality="Dhanmondi",
            shipping_city="Dhaka",
            shipping_zipcode="1209",
            shipping_state="Dhaka",
            subtotal=Decimal('300.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('370.00'),
            payment_status='PENDING'
        )
        self.payment = Payment.objects.create(
            order=self.order,
            payment_method='SSLCOMMERZ',
            status='PENDING',
            amount=Decimal('370.00'),
            currency='BDT'
        )
        self.client.login(username='cb_user', password='Password123!')

    @patch('app.services.sslcommerz.requests.get')
    def test_sslcommerz_success_callback_validates_and_marks_paid(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': self.payment.transaction_id,
            'val_id': 'VALID12345',
            'amount': '370.00',
            'currency': 'BDT',
            'bank_tran_id': 'BANK987',
            'card_type': 'VISA',
            'card_brand': 'VISA',
            'card_issuer': 'BRAC Bank'
        }

        response = self.client.post(reverse('sslcommerz-success'), {
            'val_id': 'VALID12345',
            'tran_id': self.payment.transaction_id,
        })
        self.assertRedirects(response, reverse('order-confirmation', kwargs={'pk': self.order.pk}))

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')
        self.assertEqual(self.order.payment_status, 'PAID')
        self.assertEqual(self.payment.validation_id, 'VALID12345')
        self.assertEqual(self.payment.bank_transaction_id, 'BANK987')

    def test_sslcommerz_success_callback_missing_val_id_fails(self):
        response = self.client.post(reverse('sslcommerz-success'), {})
        self.assertRedirects(response, reverse('orders'))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'PENDING')

    @patch('app.services.sslcommerz.requests.get')
    def test_sslcommerz_success_wrong_amount_fails_validation(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': self.payment.transaction_id,
            'val_id': 'VAL_BAD_AMT',
            'amount': '10.00',  # Wrong amount!
            'currency': 'BDT'
        }

        response = self.client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_BAD_AMT',
            'tran_id': self.payment.transaction_id,
        })
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': self.order.pk}))
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertNotEqual(self.payment.status, 'PAID')
        self.assertNotEqual(self.order.payment_status, 'PAID')

    @patch('app.services.sslcommerz.requests.get')
    def test_sslcommerz_success_wrong_currency_fails_validation(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': self.payment.transaction_id,
            'val_id': 'VAL_BAD_CURR',
            'amount': '370.00',
            'currency': 'USD'  # Wrong currency!
        }

        self.client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_BAD_CURR',
            'tran_id': self.payment.transaction_id,
        })
        self.payment.refresh_from_db()
        self.assertNotEqual(self.payment.status, 'PAID')

    @patch('app.services.sslcommerz.requests.get')
    def test_sslcommerz_success_invalid_status_fails_validation(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'FAILED',
            'tran_id': self.payment.transaction_id,
            'val_id': 'VAL_STATUS_FAILED',
            'amount': '370.00',
            'currency': 'BDT'
        }

        self.client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_STATUS_FAILED',
            'tran_id': self.payment.transaction_id,
        })
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'FAILED')
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.payment_status, 'PAID')

    def test_sslcommerz_fail_callback_marks_payment_and_order_failed(self):
        response = self.client.post(reverse('sslcommerz-fail'), {
            'tran_id': self.payment.transaction_id,
            'failedreason': 'Insufficient funds'
        })
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': self.order.pk}))
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'FAILED')
        self.assertEqual(self.order.payment_status, 'FAILED')

    def test_sslcommerz_cancel_callback_marks_payment_cancelled(self):
        response = self.client.post(reverse('sslcommerz-cancel'), {
            'tran_id': self.payment.transaction_id
        })
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': self.order.pk}))
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'CANCELLED')
        self.assertEqual(self.order.payment_status, 'PENDING')


class SSLCommerzIPNTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='ipn_user', password='Password123!')
        self.order = Order.objects.create(
            user=self.user,
            shipping_name="IPN Customer",
            shipping_mobile="01711223344",
            shipping_locality="Banani",
            shipping_city="Dhaka",
            shipping_zipcode="1213",
            shipping_state="Dhaka",
            subtotal=Decimal('800.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('870.00'),
            payment_status='PENDING'
        )
        self.payment = Payment.objects.create(
            order=self.order,
            payment_method='SSLCOMMERZ',
            status='PENDING',
            amount=Decimal('870.00'),
            currency='BDT'
        )

    @patch('app.services.sslcommerz.requests.get')
    def test_ipn_valid_payload_marks_payment_and_order_paid(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALIDATED',
            'tran_id': self.payment.transaction_id,
            'val_id': 'IPN_VAL_100',
            'amount': '870.00',
            'currency': 'BDT',
            'bank_tran_id': 'BANK_IPN_55'
        }

        response = self.client.post(reverse('sslcommerz-ipn'), {
            'val_id': 'IPN_VAL_100',
            'tran_id': self.payment.transaction_id,
        })
        self.assertEqual(response.status_code, 200)

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')
        self.assertEqual(self.order.payment_status, 'PAID')

    def test_ipn_missing_val_id_returns_400(self):
        response = self.client.post(reverse('sslcommerz-ipn'), {})
        self.assertEqual(response.status_code, 400)

    @patch('app.services.sslcommerz.requests.get')
    def test_ipn_wrong_amount_returns_400_and_does_not_mark_paid(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': self.payment.transaction_id,
            'val_id': 'IPN_VAL_WRONG',
            'amount': '1.00',
            'currency': 'BDT'
        }

        response = self.client.post(reverse('sslcommerz-ipn'), {
            'val_id': 'IPN_VAL_WRONG',
            'tran_id': self.payment.transaction_id,
        })
        self.assertEqual(response.status_code, 400)
        self.payment.refresh_from_db()
        self.assertNotEqual(self.payment.status, 'PAID')

    @patch('app.services.sslcommerz.requests.get')
    def test_ipn_wrong_currency_returns_400(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': self.payment.transaction_id,
            'val_id': 'IPN_VAL_CURR',
            'amount': '870.00',
            'currency': 'EUR'
        }

        response = self.client.post(reverse('sslcommerz-ipn'), {
            'val_id': 'IPN_VAL_CURR',
            'tran_id': self.payment.transaction_id,
        })
        self.assertEqual(response.status_code, 400)
        self.payment.refresh_from_db()
        self.assertNotEqual(self.payment.status, 'PAID')

    def test_ipn_get_rejected_with_405(self):
        response = self.client.get(reverse('sslcommerz-ipn'))
        self.assertEqual(response.status_code, 405)

    @patch('app.services.sslcommerz.requests.get')
    def test_ipn_repeated_callback_is_idempotent(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': self.payment.transaction_id,
            'val_id': 'IPN_DUP',
            'amount': '870.00',
            'currency': 'BDT'
        }

        # First call
        r1 = self.client.post(reverse('sslcommerz-ipn'), {
            'val_id': 'IPN_DUP',
            'tran_id': self.payment.transaction_id
        })
        self.assertEqual(r1.status_code, 200)

        # Second call
        r2 = self.client.post(reverse('sslcommerz-ipn'), {
            'val_id': 'IPN_DUP',
            'tran_id': self.payment.transaction_id
        })
        self.assertEqual(r2.status_code, 200)

        self.assertEqual(self.order.payments.count(), 1)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')


class PaymentRetryAndHistoryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='retry_user', password='Password123!')
        self.order = Order.objects.create(
            user=self.user,
            shipping_name="Retry Customer",
            shipping_mobile="01711223344",
            shipping_locality="Uttara",
            shipping_city="Dhaka",
            shipping_zipcode="1230",
            shipping_state="Dhaka",
            subtotal=Decimal('600.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('670.00'),
            payment_status='FAILED'
        )
        self.p1 = Payment.objects.create(
            order=self.order,
            payment_method='SSLCOMMERZ',
            status='FAILED',
            amount=Decimal('670.00'),
            currency='BDT'
        )
        self.client.login(username='retry_user', password='Password123!')

    @patch('app.services.sslcommerz.requests.post')
    def test_failed_payment_can_be_retried_creating_new_payment_attempt(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/retry',
            'sessionkey': 'SES_RETRY'
        }

        response = self.client.post(reverse('sslcommerz-initiate', kwargs={'order_id': self.order.id}))
        self.assertEqual(response.status_code, 302)

        # There should now be 2 payment records: 1 FAILED, 1 PENDING
        self.assertEqual(self.order.payments.count(), 2)
        statuses = list(self.order.payments.values_list('status', flat=True))
        self.assertIn('FAILED', statuses)
        self.assertIn('PENDING', statuses)

    def test_payment_history_preserved_on_order(self):
        Payment.objects.create(
            order=self.order,
            payment_method='SSLCOMMERZ',
            status='CANCELLED',
            amount=Decimal('670.00'),
            currency='BDT'
        )
        Payment.objects.create(
            order=self.order,
            payment_method='SSLCOMMERZ',
            status='PAID',
            amount=Decimal('670.00'),
            currency='BDT'
        )
        self.assertEqual(self.order.payments.count(), 3)

    def test_order_detail_shows_payment_history(self):
        response = self.client.get(reverse('order-detail', kwargs={'pk': self.order.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.p1.transaction_id)
        self.assertContains(response, "Payment History")

    def test_order_confirmation_shows_payment_details(self):
        response = self.client.get(reverse('order-confirmation', kwargs={'pk': self.order.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.p1.transaction_id)

    @patch('app.services.sslcommerz.requests.get')
    def test_idempotent_duplicate_success_does_not_create_duplicate_payment(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': self.p1.transaction_id,
            'val_id': 'VAL_IDEMPOTENT',
            'amount': '670.00',
            'currency': 'BDT'
        }

        self.client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_IDEMPOTENT',
            'tran_id': self.p1.transaction_id
        })
        self.client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_IDEMPOTENT',
            'tran_id': self.p1.transaction_id
        })
        self.assertEqual(self.order.payments.count(), 1)


class PaymentSecurityTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='sec_p_user1', password='Password123!')
        self.user2 = User.objects.create_user(username='sec_p_user2', password='Password123!')
        self.order1 = Order.objects.create(
            user=self.user1,
            shipping_name="Sec User",
            shipping_mobile="01711223344",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('200.00'),
            grand_total=Decimal('270.00')
        )

    def test_sslcommerz_initiate_csrf_protection_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username='sec_p_user1', password='Password123!')
        response = client.post(reverse('sslcommerz-initiate', kwargs={'order_id': self.order1.id}))
        self.assertEqual(response.status_code, 403)

    def test_cross_user_payment_initiation_rejected(self):
        client2 = Client()
        client2.login(username='sec_p_user2', password='Password123!')
        response = client2.post(reverse('sslcommerz-initiate', kwargs={'order_id': self.order1.id}))
        self.assertEqual(response.status_code, 404)

    def test_credentials_not_exposed_in_templates_or_responses(self):
        client = Client()
        client.login(username='sec_p_user1', password='Password123!')
        response = client.get(reverse('order-detail', kwargs={'pk': self.order1.pk}))
        self.assertNotContains(response, "qwerty")
        self.assertNotContains(response, "testbox")


class PaymentSecurityReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sec_audit_user', password='Password123!')
        self.customer = Customer.objects.create(
            user=self.user,
            name="Audit Customer",
            locality="Dhanmondi 27",
            city="Dhaka",
            mobile="01711223344",
            zipcode=1209,
            state="Dhaka"
        )
        self.order = Order.objects.create(
            user=self.user,
            shipping_name="Audit Customer",
            shipping_mobile="01711223344",
            shipping_locality="Dhanmondi 27",
            shipping_city="Dhaka",
            shipping_zipcode="1209",
            shipping_state="Dhaka",
            subtotal=Decimal('500.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('570.00'),
            payment_status='PENDING'
        )
        self.payment = Payment.objects.create(
            order=self.order,
            payment_method='SSLCOMMERZ',
            status='PENDING',
            amount=Decimal('570.00'),
            currency='BDT'
        )

    def test_cancelled_payment_preserves_order_pending_and_retryable(self):
        """
        When user cancels payment, Payment is CANCELLED but Order remains PENDING
        so that the user can retry payment without creating a duplicate order.
        """
        client = Client()
        client.login(username='sec_audit_user', password='Password123!')
        response = client.post(reverse('sslcommerz-cancel'), {
            'tran_id': self.payment.transaction_id
        })
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': self.order.pk}))
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'CANCELLED')
        self.assertEqual(self.order.payment_status, 'PENDING')

        # Retry payment initiation on the same order succeeds
        with patch('app.services.sslcommerz.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                'status': 'SUCCESS',
                'GatewayPageURL': 'https://sandbox.sslcommerz.com/gwprocess/v4/gw.php?Q=retry',
                'sessionkey': 'SES_RETRY_123'
            }
            retry_resp = client.post(reverse('sslcommerz-initiate', kwargs={'order_id': self.order.pk}))
            self.assertEqual(retry_resp.status_code, 302)
            self.assertIn('gwprocess/v4/gw.php?Q=retry', retry_resp.url)

            # Order has 2 payments: the cancelled one and the new pending one
            self.assertEqual(self.order.payments.count(), 2)
            statuses = list(self.order.payments.values_list('status', flat=True))
            self.assertIn('CANCELLED', statuses)
            self.assertIn('PENDING', statuses)

    @patch('app.services.sslcommerz.requests.get')
    def test_validation_status_validated_accepted_and_marks_paid(self, mock_get):
        """
        SSLCommerz validator returning 'VALIDATED' (e.g. via IPN/settlement) is accepted as PAID.
        """
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALIDATED',
            'tran_id': self.payment.transaction_id,
            'val_id': 'VAL_AUDIT_01',
            'amount': '570.00',
            'currency': 'BDT',
            'bank_tran_id': 'BANK_AUDIT_01',
            'risk_level': '0',
            'risk_title': 'Safe'
        }
        client = Client()
        client.login(username='sec_audit_user', password='Password123!')
        response = client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_AUDIT_01',
            'tran_id': self.payment.transaction_id
        })
        self.assertRedirects(response, reverse('order-confirmation', kwargs={'pk': self.order.pk}))
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')
        self.assertEqual(self.order.payment_status, 'PAID')
        self.assertEqual(self.payment.risk_level, '0')
        self.assertEqual(self.payment.risk_title, 'Safe')

    @patch('app.services.sslcommerz.requests.get')
    def test_validation_status_invalid_transaction_rejected(self, mock_get):
        """
        SSLCommerz validator returning 'INVALID_TRANSACTION' is rejected and marks payment FAILED.
        """
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'INVALID_TRANSACTION',
            'tran_id': self.payment.transaction_id,
            'val_id': 'VAL_INVALID',
            'amount': '570.00',
            'currency': 'BDT'
        }
        client = Client()
        client.login(username='sec_audit_user', password='Password123!')
        response = client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_INVALID',
            'tran_id': self.payment.transaction_id
        })
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': self.order.pk}))
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'FAILED')
        self.assertEqual(self.order.payment_status, 'PENDING')

    @patch('app.services.sslcommerz.requests.get')
    def test_callback_tran_id_mismatch_rejected(self, mock_get):
        """
        If client posts a mismatched tran_id compared to the gateway validation payload,
        the callback rejects it and does not mark the payment as PAID.
        """
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': 'TX_DIFFERENT_TRANSACTION',
            'val_id': 'VAL_MISMATCH',
            'amount': '570.00',
            'currency': 'BDT'
        }
        client = Client()
        client.login(username='sec_audit_user', password='Password123!')
        response = client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_MISMATCH',
            'tran_id': self.payment.transaction_id
        })
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': self.order.pk}))
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertNotEqual(self.payment.status, 'PAID')
        self.assertNotEqual(self.order.payment_status, 'PAID')

    @patch('app.services.sslcommerz.requests.get')
    def test_ipn_tran_id_mismatch_rejected(self, mock_get):
        """
        If IPN receives a mismatched tran_id compared to gateway val_data, returns 400.
        """
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': 'TX_ACTUAL_ID',
            'val_id': 'VAL_IPN_MISMATCH',
            'amount': '570.00',
            'currency': 'BDT'
        }
        client = Client()
        response = client.post(reverse('sslcommerz-ipn'), {
            'val_id': 'VAL_IPN_MISMATCH',
            'tran_id': 'TX_FAKE_ID'
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Transaction ID mismatch", response.content)

    def test_ipn_accessible_via_post_without_csrf_token(self):
        """
        IPN endpoint is server-to-server and must accept POST without CSRF token.
        """
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse('sslcommerz-ipn'), {})
        # Should return 400 (missing val_id), NOT 403 (CSRF failure)
        self.assertEqual(response.status_code, 400)

    def test_browser_callbacks_accessible_without_csrf_token(self):
        """
        Browser return callbacks accept POST from gateway redirect without CSRF token.
        """
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse('sslcommerz-cancel'), {
            'tran_id': self.payment.transaction_id
        })
        # Should redirect, NOT 403 CSRF failure
        self.assertEqual(response.status_code, 302)

    def test_place_order_enforces_csrf_protection(self):
        """
        Customer checkout place-order form MUST enforce CSRF checks.
        """
        client = Client(enforce_csrf_checks=True)
        client.login(username='sec_audit_user', password='Password123!')
        response = client.post(reverse('place-order'), {'payment_method': 'SSLCOMMERZ'})
        self.assertEqual(response.status_code, 403)

    @patch('app.services.sslcommerz.requests.get')
    def test_risk_level_stored_and_high_risk_logged(self, mock_get):
        """
        Risk level and risk title from gateway are safely recorded on the Payment record.
        """
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'VALID',
            'tran_id': self.payment.transaction_id,
            'val_id': 'VAL_RISK_CHECK',
            'amount': '570.00',
            'currency': 'BDT',
            'risk_level': '1',
            'risk_title': 'Suspicious Activity'
        }
        client = Client()
        client.login(username='sec_audit_user', password='Password123!')
        client.post(reverse('sslcommerz-success'), {
            'val_id': 'VAL_RISK_CHECK',
            'tran_id': self.payment.transaction_id
        })
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')
        self.assertEqual(self.payment.risk_level, '1')
        self.assertEqual(self.payment.risk_title, 'Suspicious Activity')


class InventoryAndStockManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='inv_user', password='Password123!')
        self.staff_user = User.objects.create_user(username='staff_inv', password='Password123!', is_staff=True)
        self.other_user = User.objects.create_user(username='other_inv', password='Password123!')
        self.customer = Customer.objects.create(
            user=self.user,
            name="Inventory Customer",
            locality="Banani Road 11",
            city="Dhaka",
            mobile="01711223344",
            zipcode=1213,
            state="Dhaka"
        )
        self.product = Product.objects.create(
            title="Organic Milk",
            selling_price=120.0,
            discounted_price=100.0,
            description="Fresh organic milk",
            category="ML",
            stock=10,
            low_stock_threshold=3
        )
        self.client.login(username='inv_user', password='Password123!')

    def test_initial_stock_and_valid_inventory_adjustments(self):
        """1. Verify initial stock and valid staff adjustments with audit logs."""
        self.assertEqual(self.product.stock, 10)
        self.assertTrue(self.product.is_in_stock)
        self.assertFalse(self.product.is_low_stock)
        self.assertFalse(self.product.is_out_of_stock)

        # Restock +5 items
        adjust_stock(
            product=self.product,
            quantity_change=5,
            reason='RESTOCK',
            user=self.staff_user,
            notes='Shipment received'
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 15)

        # Verify audit log entry
        adjustment = StockAdjustment.objects.filter(product=self.product).latest('timestamp')
        self.assertEqual(adjustment.quantity_change, 5)
        self.assertEqual(adjustment.resulting_stock, 15)
        self.assertEqual(adjustment.reason, 'RESTOCK')
        self.assertEqual(adjustment.user, self.staff_user)
        self.assertEqual(adjustment.notes, 'Shipment received')

    def test_negative_stock_rejection_python_validation(self):
        """2a. adjust_stock rejects quantity change driving stock negative."""
        with self.assertRaises(ValidationError):
            adjust_stock(self.product, -15, reason='DAMAGED')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_negative_stock_rejection_db_constraint(self):
        """2b. Database CheckConstraint rejects negative stock at DB level."""
        self.product.stock = -1
        with self.assertRaises(IntegrityError):
            self.product.save()

    def test_adding_in_stock_product_to_cart_does_not_deduct_inventory(self):
        """3. Adding in-stock product to cart succeeds without deducting inventory."""
        response = self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 2})
        self.assertRedirects(response, reverse('show-cart'))

        cart = Cart.objects.get(user=self.user)
        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.first().quantity, 2)

        # Stock must remain unchanged
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_reject_out_of_stock_product_addition_to_cart(self):
        """4. Reject adding an out-of-stock product (stock=0) to cart."""
        self.product.stock = 0
        self.product.save()

        response = self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 1})
        self.assertRedirects(response, reverse('product-detail', kwargs={'pk': self.product.id}))

        cart = Cart.objects.filter(user=self.user).first()
        if cart:
            self.assertEqual(cart.items.count(), 0)

    def test_reject_cart_quantity_greater_than_available_stock(self):
        """5. Reject requested quantity greater than available stock on add and plus-cart."""
        self.product.stock = 3
        self.product.save()

        # Add 5 items when only 3 in stock
        response = self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 5})
        self.assertRedirects(response, reverse('product-detail', kwargs={'pk': self.product.id}))

        cart = Cart.objects.filter(user=self.user).first()
        self.assertTrue(cart is None or cart.items.count() == 0)

        # Add 2 items (valid)
        self.client.post(reverse('add-to-cart'), {'prod_id': self.product.id, 'quantity': 2})
        cart = Cart.objects.get(user=self.user)
        item = cart.items.first()
        self.assertEqual(item.quantity, 2)

        # Plus cart to 3 (valid, equals stock)
        self.client.post(reverse('plus-cart'), {'item_id': item.id})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 3)

        # Plus cart to 4 (exceeds stock of 3) -> rejected
        self.client.post(reverse('plus-cart'), {'item_id': item.id})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 3)

    def test_reject_checkout_when_cart_item_stock_becomes_insufficient(self):
        """6. Reject checkout when stock becomes insufficient after item was added to cart."""
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=5)

        # Stock is reduced by another order / admin to 3
        self.product.stock = 3
        self.product.save()

        response = self.client.get(reverse('checkout'))
        self.assertRedirects(response, reverse('show-cart'))

    def test_successful_order_creation_deducts_stock_and_records_audit(self):
        """7. Successful order placement deducts stock and logs audit trail."""
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=4)

        response = self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order-confirmation', kwargs={'pk': order.pk}))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 6)
        self.assertTrue(order.stock_deducted)
        self.assertFalse(order.stock_restored)

        # Verify StockAdjustment
        adjustment = StockAdjustment.objects.filter(order=order, product=self.product).first()
        self.assertIsNotNone(adjustment)
        self.assertEqual(adjustment.quantity_change, -4)
        self.assertEqual(adjustment.resulting_stock, 6)
        self.assertEqual(adjustment.reason, 'ORDER_PLACED')

    @patch('app.views.OrderItem.objects.create')
    def test_order_creation_rollback_on_failure_preserves_stock(self, mock_create):
        """8. If order placement encounters an exception, stock changes roll back completely."""
        mock_create.side_effect = RuntimeError("Database crash during order items save")
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=3)

        with self.assertRaises(RuntimeError):
            self.client.post(reverse('place-order'), {'payment_method': 'COD'})

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)  # Stock untouched
        self.assertEqual(Order.objects.filter(user=self.user).count(), 0)
        self.assertEqual(StockAdjustment.objects.count(), 0)

    def test_multiple_cart_items_with_one_insufficient_stock_rolls_back_all(self):
        """9. Multiple items where one is out of stock aborts entire checkout without stock changes."""
        p2 = Product.objects.create(
            title="Cheese",
            selling_price=200.0,
            discounted_price=180.0,
            category="CZ",
            stock=1
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        CartItem.objects.create(cart=cart, product=p2, quantity=3)  # Exceeds p2 stock of 1

        response = self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        self.assertRedirects(response, reverse('show-cart'))

        # No order created, neither product's stock modified
        self.assertEqual(Order.objects.filter(user=self.user).count(), 0)
        self.product.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        self.assertEqual(p2.stock, 1)

    def test_stock_restoration_after_order_cancellation(self):
        """10. Eligible order cancellation restores stock and logs audit record."""
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=3)
        self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        order = Order.objects.get(user=self.user)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)

        # Cancel the order
        response = self.client.post(reverse('order-cancel', kwargs={'pk': order.pk}))
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': order.pk}))

        order.refresh_from_db()
        self.assertEqual(order.status, 'CANCELLED')
        self.assertTrue(order.stock_restored)

        # Stock restored
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

        # Adjustment record
        adjustment = StockAdjustment.objects.filter(order=order, product=self.product, reason='ORDER_CANCELLED').first()
        self.assertIsNotNone(adjustment)
        self.assertEqual(adjustment.quantity_change, 3)
        self.assertEqual(adjustment.resulting_stock, 10)

    def test_duplicate_order_cancellation_does_not_restore_stock_twice(self):
        """11. Duplicate cancellation is idempotent and does not restore stock twice."""
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=4)
        self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        order = Order.objects.get(user=self.user)

        # First cancellation
        self.client.post(reverse('order-cancel', kwargs={'pk': order.pk}))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

        # Second cancellation attempt
        self.client.post(reverse('order-cancel', kwargs={'pk': order.pk}))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)  # Still 10, not 14

    @patch('app.services.sslcommerz.requests.post')
    def test_payment_cancellation_does_not_restore_stock_while_order_active(self, mock_post):
        """12. Payment cancellation on gateway leaves order active/pending and does NOT restore stock."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/gw',
            'sessionkey': 'SES_INV_1'
        }
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=3)

        self.client.post(reverse('place-order'), {'payment_method': 'SSLCOMMERZ'})
        order = Order.objects.get(user=self.user)
        payment = order.payments.first()

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)

        # Gateway cancellation callback
        self.client.post(reverse('sslcommerz-cancel'), {'tran_id': payment.transaction_id})
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, 'CANCELLED')
        self.assertEqual(order.payment_status, 'PENDING')
        self.assertEqual(order.status, 'PENDING')

        # Stock must remain deducted (not restored) because order is still active
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)

    @patch('app.services.sslcommerz.requests.post')
    def test_sslcommerz_payment_retry_does_not_deduct_stock_again(self, mock_post):
        """13. Retrying payment on an active order creates a new payment attempt without deducting stock again."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/gw_retry',
            'sessionkey': 'SES_INV_RETRY'
        }
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)

        self.client.post(reverse('place-order'), {'payment_method': 'SSLCOMMERZ'})
        order = Order.objects.get(user=self.user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)

        # Retry payment
        self.client.post(reverse('sslcommerz-initiate', kwargs={'order_id': order.pk}))
        self.assertEqual(order.payments.count(), 2)

        # Stock must remain 8 (NOT deducted again to 6)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)

    def test_unauthenticated_and_unauthorized_cancellation_prevented(self):
        """14. Unauthenticated or non-owner users cannot cancel an order."""
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        order = Order.objects.get(user=self.user)

        # Anonymous request -> 302 to login
        anon_client = Client()
        anon_resp = anon_client.post(reverse('order-cancel', kwargs={'pk': order.pk}))
        self.assertEqual(anon_resp.status_code, 302)
        self.assertIn(reverse('login'), anon_resp.url)

        # Other authenticated user -> 404
        other_client = Client()
        other_client.login(username='other_inv', password='Password123!')
        other_resp = other_client.post(reverse('order-cancel', kwargs={'pk': order.pk}))
        self.assertEqual(other_resp.status_code, 404)

        # Paid order cannot be cancelled by customer
        order.payment_status = 'PAID'
        order.save()
        resp = self.client.post(reverse('order-cancel', kwargs={'pk': order.pk}))
        self.assertRedirects(resp, reverse('order-detail', kwargs={'pk': order.pk}))
        order.refresh_from_db()
        self.assertNotEqual(order.status, 'CANCELLED')

    def test_stock_adjustment_admin_immutability(self):
        """15. StockAdjustmentAdmin disallows delete and change operations in admin."""
        from django.contrib.admin.sites import site
        from app.admin import StockAdjustmentAdmin
        adjustment_admin = StockAdjustmentAdmin(StockAdjustment, site)

        request = type('Request', (), {'user': self.staff_user})()
        self.assertFalse(adjustment_admin.has_delete_permission(request))
        self.assertFalse(adjustment_admin.has_change_permission(request))

    def test_admin_staff_cancellation_guards_fulfilled_and_paid_orders(self):
        """16. Staff cancellation action in admin skips fulfilled (SHIPPED, DELIVERED) and paid orders."""
        from django.contrib.admin.sites import site
        from app.admin import OrderAdmin
        order_admin = OrderAdmin(Order, site)

        # Create 3 orders: 1 pending unpaid, 1 paid, 1 shipped
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        self.client.post(reverse('place-order'), {'payment_method': 'COD'})
        pending_order = Order.objects.get(user=self.user)

        paid_order = Order.objects.create(
            user=self.user,
            shipping_name="Cust",
            shipping_mobile="01711223344",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('100.00'),
            grand_total=Decimal('170.00'),
            status='PENDING',
            payment_status='PAID',
            stock_deducted=True
        )

        shipped_order = Order.objects.create(
            user=self.user,
            shipping_name="Cust",
            shipping_mobile="01711223344",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1200",
            shipping_state="Dhaka",
            subtotal=Decimal('100.00'),
            grand_total=Decimal('170.00'),
            status='SHIPPED',
            payment_status='PENDING',
            stock_deducted=True
        )

        # Run admin action
        request = type('Request', (), {'user': self.staff_user, '_messages': []})()
        messages_sent = []
        order_admin.message_user = lambda req, msg: messages_sent.append(msg)

        qs = Order.objects.filter(pk__in=[pending_order.pk, paid_order.pk, shipped_order.pk])
        order_admin.cancel_selected_orders(request, qs)

        pending_order.refresh_from_db()
        paid_order.refresh_from_db()
        shipped_order.refresh_from_db()

        self.assertEqual(pending_order.status, 'CANCELLED')
        self.assertTrue(pending_order.stock_restored)

        # Paid and shipped orders were NOT cancelled
        self.assertEqual(paid_order.status, 'PENDING')
        self.assertFalse(paid_order.stock_restored)

        self.assertEqual(shipped_order.status, 'SHIPPED')
        self.assertFalse(shipped_order.stock_restored)
        self.assertTrue(any('skipped' in m for m in messages_sent))


class OrderFulfillmentAndDeliveryTests(TestCase):
    def setUp(self):
        self.customer_user = User.objects.create_user(username='ful_cust', password='Password123!')
        self.staff_user = User.objects.create_user(username='ful_staff', password='Password123!', is_staff=True)
        self.other_user = User.objects.create_user(username='ful_other', password='Password123!')

        self.customer = Customer.objects.create(
            user=self.customer_user,
            name="Fulfillment Customer",
            locality="Dhanmondi 32",
            city="Dhaka",
            mobile="01799887766",
            zipcode=1209,
            state="Dhaka"
        )
        self.product = Product.objects.create(
            title="Full Cream Milk",
            selling_price=100.0,
            discounted_price=90.0,
            category="ML",
            stock=10
        )
        self.order = Order.objects.create(
            user=self.customer_user,
            shipping_name="Fulfillment Customer",
            shipping_mobile="01799887766",
            shipping_locality="Dhanmondi 32",
            shipping_city="Dhaka",
            shipping_zipcode="1209",
            shipping_state="Dhaka",
            subtotal=Decimal('90.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('160.00'),
            status='PENDING',
            payment_status='PENDING',
            stock_deducted=True,
            stock_restored=False
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.title,
            unit_price=Decimal('90.00'),
            quantity=2,
            subtotal=Decimal('180.00')
        )
        self.product.stock = 8
        self.product.save()

    def test_full_lifecycle_progression(self):
        """1. Order progresses through full valid lifecycle: PENDING -> ACCEPTED -> PROCESSING -> READY -> SHIPPED -> DELIVERED."""
        from app.services.fulfillment import transition_order_status
        transition_order_status(self.order, 'ACCEPTED', user=self.staff_user, notes='Order accepted')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'ACCEPTED')

        transition_order_status(self.order, 'PROCESSING', user=self.staff_user, notes='Packing started')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PROCESSING')

        transition_order_status(self.order, 'READY', user=self.staff_user, notes='Ready for courier')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'READY')

        transition_order_status(
            self.order,
            'SHIPPED',
            user=self.staff_user,
            notes='Dispatched via Pathao',
            courier_name='Pathao Express',
            tracking_number='PTH-12345'
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'SHIPPED')
        self.assertEqual(self.order.courier_name, 'Pathao Express')
        self.assertEqual(self.order.tracking_number, 'PTH-12345')
        self.assertIsNotNone(self.order.shipped_at)

        transition_order_status(self.order, 'DELIVERED', user=self.staff_user, notes='Delivered safely')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'DELIVERED')
        self.assertIsNotNone(self.order.delivered_at)

        # Stock must remain unchanged (8) throughout the progression
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)
        self.assertEqual(self.order.status_history.count(), 5)

    def test_invalid_transitions_rejected(self):
        """2. Skipping intermediate states or backwards transitions are rejected."""
        from app.services.fulfillment import transition_order_status, FulfillmentTransitionError
        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(self.order, 'SHIPPED', user=self.staff_user)

        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(self.order, 'DELIVERED', user=self.staff_user)

        transition_order_status(self.order, 'ACCEPTED', user=self.staff_user)

        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(self.order, 'PENDING', user=self.staff_user)

        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(self.order, 'READY', user=self.staff_user)

    def test_terminal_states_immutable(self):
        """3. Terminal states DELIVERED and CANCELLED cannot transition to any other status."""
        from app.services.fulfillment import transition_order_status, FulfillmentTransitionError
        transition_order_status(self.order, 'ACCEPTED', user=self.staff_user)
        transition_order_status(self.order, 'PROCESSING', user=self.staff_user)
        transition_order_status(self.order, 'READY', user=self.staff_user)
        transition_order_status(self.order, 'SHIPPED', user=self.staff_user)
        transition_order_status(self.order, 'DELIVERED', user=self.staff_user)

        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(self.order, 'CANCELLED', user=self.staff_user)

        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(self.order, 'SHIPPED', user=self.staff_user)

        cancelled_order = Order.objects.create(
            user=self.customer_user,
            shipping_name="Cust",
            shipping_mobile="01799887766",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1209",
            shipping_state="Dhaka",
            subtotal=Decimal('50.00'),
            grand_total=Decimal('120.00'),
            status='PENDING'
        )
        transition_order_status(cancelled_order, 'CANCELLED', user=self.staff_user)
        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(cancelled_order, 'ACCEPTED', user=self.staff_user)

    def test_paid_orders_cannot_be_cancelled_without_refund(self):
        """4. Paid orders cannot be cancelled through regular fulfillment transition."""
        from app.services.fulfillment import transition_order_status, FulfillmentTransitionError
        self.order.payment_status = 'PAID'
        self.order.save()

        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(self.order, 'CANCELLED', user=self.staff_user)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, 'CANCELLED')

    def test_shipped_order_cannot_be_cancelled(self):
        """5. In-transit/shipped orders cannot be cancelled."""
        from app.services.fulfillment import transition_order_status, FulfillmentTransitionError
        transition_order_status(self.order, 'ACCEPTED', user=self.staff_user)
        transition_order_status(self.order, 'PROCESSING', user=self.staff_user)
        transition_order_status(self.order, 'READY', user=self.staff_user)
        transition_order_status(self.order, 'SHIPPED', user=self.staff_user)

        with self.assertRaises(FulfillmentTransitionError):
            transition_order_status(self.order, 'CANCELLED', user=self.staff_user)

    def test_customer_cannot_cancel_processing_or_later_order(self):
        """6. Customer attempting to POST cancel an order that has moved beyond PENDING is rejected."""
        from app.services.fulfillment import transition_order_status
        transition_order_status(self.order, 'ACCEPTED', user=self.staff_user)

        client = Client()
        client.login(username='ful_cust', password='Password123!')
        response = client.post(reverse('order-cancel', kwargs={'pk': self.order.pk}))
        self.assertRedirects(response, reverse('order-detail', kwargs={'pk': self.order.pk}))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'ACCEPTED')

    def test_regular_customer_cannot_access_staff_queue_or_transition(self):
        """7. Regular customers are forbidden from accessing staff queue or making transitions."""
        client = Client()
        client.login(username='ful_cust', password='Password123!')

        queue_resp = client.get(reverse('staff-orders'))
        self.assertRedirects(queue_resp, reverse('orders'))

        trans_resp = client.post(
            reverse('staff-order-transition', kwargs={'pk': self.order.pk}),
            {'target_status': 'ACCEPTED'}
        )
        self.assertRedirects(trans_resp, reverse('orders'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PENDING')

    def test_anonymous_user_cannot_access_staff_portal(self):
        """8. Anonymous requests to staff portal redirect to login."""
        anon_client = Client()
        resp = anon_client.get(reverse('staff-orders'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp.url)

    def test_staff_order_queue_and_transition_view(self):
        """9. Staff user can view order queue and transition orders via POST."""
        client = Client()
        client.login(username='ful_staff', password='Password123!')

        response = client.get(reverse('staff-orders'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)

        post_resp = client.post(
            reverse('staff-order-transition', kwargs={'pk': self.order.pk}),
            {'target_status': 'ACCEPTED', 'notes': 'Accepted by staff'}
        )
        self.assertRedirects(post_resp, reverse('staff-order-detail', kwargs={'pk': self.order.pk}))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'ACCEPTED')

    def test_payment_status_and_fulfillment_status_separation(self):
        """10. Advancing fulfillment status leaves payment_status completely independent."""
        from app.services.fulfillment import transition_order_status
        self.assertEqual(self.order.payment_status, 'PENDING')
        transition_order_status(self.order, 'ACCEPTED', user=self.staff_user)
        transition_order_status(self.order, 'PROCESSING', user=self.staff_user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'PENDING')

        self.order.payment_status = 'PAID'
        self.order.save()
        transition_order_status(self.order, 'READY', user=self.staff_user)
        transition_order_status(self.order, 'SHIPPED', user=self.staff_user)
        transition_order_status(self.order, 'DELIVERED', user=self.staff_user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'PAID')
        self.assertEqual(self.order.status, 'DELIVERED')

    def test_cancellation_restores_inventory_and_logs_audit(self):
        """11. Cancelling an eligible order restores stock and records audit history."""
        from app.services.fulfillment import transition_order_status
        self.product.refresh_from_db()
        initial_stock = self.product.stock

        transition_order_status(self.order, 'CANCELLED', user=self.staff_user, notes='Out of stock')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'CANCELLED')
        self.assertTrue(self.order.stock_restored)
        self.assertIsNotNone(self.order.cancelled_at)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, initial_stock + 2)

        history = self.order.status_history.filter(to_status='CANCELLED').first()
        self.assertIsNotNone(history)
        self.assertEqual(history.notes, 'Out of stock')

    def test_admin_actions_transition_eligible_orders(self):
        """12. Admin actions advance eligible orders and skip invalid ones."""
        from django.contrib.admin.sites import site
        from app.admin import OrderAdmin
        admin_obj = OrderAdmin(Order, site)

        request = type('Request', (), {'user': self.staff_user, '_messages': []})()
        messages_sent = []
        admin_obj.message_user = lambda req, msg: messages_sent.append(msg)

        qs = Order.objects.filter(pk=self.order.pk)
        admin_obj.accept_selected_orders(request, qs)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'ACCEPTED')

        admin_obj.process_selected_orders(request, qs)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PROCESSING')

        admin_obj.deliver_selected_orders(request, qs)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PROCESSING')  # Skipped!

    @patch('app.services.fulfillment.OrderStatusHistory.objects.create')
    def test_cancellation_atomic_rollback_on_simulated_failure(self, mock_history):
        """13. Simulated failure during cancellation rolls back status, stock restoration, and audit records."""
        from app.services.fulfillment import transition_order_status
        mock_history.side_effect = RuntimeError("Simulated database failure during audit trail creation")

        with self.assertRaises(RuntimeError):
            transition_order_status(self.order, 'CANCELLED', user=self.staff_user)

        # Entire transaction must have rolled back
        self.order.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(self.order.status, 'PENDING')
        self.assertFalse(self.order.stock_restored)
        self.assertIsNone(self.order.cancelled_at)
        self.assertEqual(self.product.stock, 8)  # Stock untouched
        self.assertEqual(StockAdjustment.objects.filter(order=self.order, reason='ORDER_CANCELLED').count(), 0)
        self.assertEqual(self.order.status_history.count(), 0)

    def test_legacy_order_without_history_renders_cleanly(self):
        """14. Legacy orders without OrderStatusHistory render cleanly across customer and staff views."""
        legacy_order = Order.objects.create(
            user=self.customer_user,
            shipping_name="Legacy Cust",
            shipping_mobile="01799887766",
            shipping_locality="Loc",
            shipping_city="City",
            shipping_zipcode="1209",
            shipping_state="Dhaka",
            subtotal=Decimal('50.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('120.00'),
            status='PENDING'
        )
        self.assertEqual(legacy_order.status_history.count(), 0)

        # Customer view
        client = Client()
        client.login(username='ful_cust', password='Password123!')
        resp = client.get(reverse('order-detail', kwargs={'pk': legacy_order.pk}))
        self.assertEqual(resp.status_code, 200)

        # Staff detail view
        staff_client = Client()
        staff_client.login(username='ful_staff', password='Password123!')
        staff_resp = staff_client.get(reverse('staff-order-detail', kwargs={'pk': legacy_order.pk}))
        self.assertEqual(staff_resp.status_code, 200)
        self.assertContains(staff_resp, "No historical transition records found.")

        # Staff queue
        queue_resp = staff_client.get(reverse('staff-orders'))
        self.assertEqual(queue_resp.status_code, 200)

    def test_terminal_state_cannot_be_reopened_via_crafted_post(self):
        """15. Crafted POST to staff transition endpoint cannot reopen DELIVERED or CANCELLED order."""
        from app.services.fulfillment import transition_order_status
        transition_order_status(self.order, 'ACCEPTED', user=self.staff_user)
        transition_order_status(self.order, 'PROCESSING', user=self.staff_user)
        transition_order_status(self.order, 'READY', user=self.staff_user)
        transition_order_status(self.order, 'SHIPPED', user=self.staff_user)
        transition_order_status(self.order, 'DELIVERED', user=self.staff_user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'DELIVERED')

        staff_client = Client()
        staff_client.login(username='ful_staff', password='Password123!')

        # Attempt to reopen to PENDING
        post_resp = staff_client.post(
            reverse('staff-order-transition', kwargs={'pk': self.order.pk}),
            {'target_status': 'PENDING'}
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'DELIVERED')

        # Attempt to reopen to PROCESSING
        post_resp = staff_client.post(
            reverse('staff-order-transition', kwargs={'pk': self.order.pk}),
            {'target_status': 'PROCESSING'}
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'DELIVERED')


class NotificationAndEmailTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = 'TestPass123!@#'
        self.user = User.objects.create_user(
            username='notif_customer',
            email='customer@example.com',
            password=self.password
        )
        self.other_user = User.objects.create_user(
            username='other_customer',
            email='other@example.com',
            password=self.password
        )
        self.staff_user = User.objects.create_user(
            username='staff_user',
            email='staff@example.com',
            password=self.password,
            is_staff=True,
            is_superuser=True
        )

        self.customer_profile = Customer.objects.create(
            user=self.user,
            name='Test Customer',
            locality='Dhanmondi 27',
            city='Dhaka',
            mobile='01711000000',
            zipcode=1209,
            state='Dhaka'
        )

        self.product = Product.objects.create(
            title='Pasteurized Cow Milk',
            selling_price=100.00,
            discounted_price=85.00,
            description='Fresh and chilled milk',
            composition='100% pure cow milk',
            prodapp='Dairy',
            category='ML',
            stock=50,
            low_stock_threshold=5,
        )

        self.order = Order.objects.create(
            user=self.user,
            shipping_name=self.customer_profile.name,
            shipping_mobile=self.customer_profile.mobile,
            shipping_locality=self.customer_profile.locality,
            shipping_city=self.customer_profile.city,
            shipping_zipcode=str(self.customer_profile.zipcode),
            shipping_state=self.customer_profile.state,
            subtotal=Decimal('170.00'),
            total_discount=Decimal('30.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('240.00'),
            status='PENDING',
            payment_status='PENDING',
            stock_deducted=True,
            stock_restored=False,
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.title,
            unit_price=Decimal('85.00'),
            quantity=2,
            subtotal=Decimal('170.00')
        )

        # Clear mailbox before each test
        mail.outbox = []

    def test_notification_creation_and_attributes(self):
        """1. In-app notification creation with proper fields and default states."""
        notif = Notification.objects.create(
            recipient=self.user,
            title='Order Received',
            message='Your order has been received.',
            notification_type='ORDER_PLACED',
            order=self.order,
            event_key=f'test_event_{self.order.id}'
        )
        self.assertEqual(notif.recipient, self.user)
        self.assertEqual(notif.title, 'Order Received')
        self.assertEqual(notif.notification_type, 'ORDER_PLACED')
        self.assertEqual(notif.order, self.order)
        self.assertFalse(notif.is_read)
        self.assertIsNone(notif.read_at)
        self.assertIsNotNone(notif.created_at)
        self.assertIn('Unread', str(notif))

    def test_mark_as_read_method_and_service(self):
        """2. Marking notification as read updates is_read and read_at timestamp."""
        from app.services.notification import mark_notification_as_read
        notif = Notification.objects.create(
            recipient=self.user,
            title='Test Alert',
            message='Sample message',
            notification_type='SYSTEM'
        )
        self.assertFalse(notif.is_read)
        self.assertIsNone(notif.read_at)

        # Other user cannot mark it as read
        success_other = mark_notification_as_read(notif.pk, self.other_user)
        self.assertFalse(success_other)
        notif.refresh_from_db()
        self.assertFalse(notif.is_read)

        # Recipient marks it as read
        success = mark_notification_as_read(notif.pk, self.user)
        self.assertTrue(success)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertIsNotNone(notif.read_at)
        self.assertIn('Read', str(notif))

    def test_mark_all_notifications_as_read(self):
        """3. mark_all_notifications_as_read updates only the recipient's unread records."""
        from app.services.notification import mark_all_notifications_as_read
        for i in range(3):
            Notification.objects.create(
                recipient=self.user,
                title=f'Customer Note {i}',
                message='Message',
                is_read=False
            )
        for i in range(2):
            Notification.objects.create(
                recipient=self.other_user,
                title=f'Other Note {i}',
                message='Message',
                is_read=False
            )

        updated_count = mark_all_notifications_as_read(self.user)
        self.assertEqual(updated_count, 3)
        self.assertEqual(Notification.objects.filter(recipient=self.user, is_read=False).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.other_user, is_read=False).count(), 2)

    def test_get_unread_notifications_count(self):
        """4. get_unread_notifications_count returns accurate counts."""
        from app.services.notification import get_unread_notifications_count
        self.assertEqual(get_unread_notifications_count(self.user), 0)

        n1 = Notification.objects.create(recipient=self.user, title='N1', message='M1')
        n2 = Notification.objects.create(recipient=self.user, title='N2', message='M2')
        self.assertEqual(get_unread_notifications_count(self.user), 2)

        n1.mark_as_read()
        self.assertEqual(get_unread_notifications_count(self.user), 1)

    def test_context_processor_unread_count(self):
        """5. unread_notifications_count context processor provides accurate context."""
        from app.context_processors import unread_notifications_count
        from django.test.client import RequestFactory
        factory = RequestFactory()

        request = factory.get('/')
        request.user = self.user
        self.assertEqual(unread_notifications_count(request)['unread_notifications_count'], 0)

        Notification.objects.create(recipient=self.user, title='N1', message='M1')
        self.assertEqual(unread_notifications_count(request)['unread_notifications_count'], 1)

        # Anonymous user
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        self.assertEqual(unread_notifications_count(request)['unread_notifications_count'], 0)

    def test_notification_list_view_authenticated(self):
        """6. Customer accesses /notifications/, sees own notifications with filters."""
        Notification.objects.create(recipient=self.user, title='My Unread Note', message='Unread', is_read=False)
        Notification.objects.create(recipient=self.user, title='My Read Note', message='Read', is_read=True)
        Notification.objects.create(recipient=self.other_user, title='Secret Other Note', message='Other', is_read=False)

        self.client.login(username=self.user.username, password=self.password)

        # All filter
        response = self.client.get(reverse('notifications'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'My Unread Note')
        self.assertContains(response, 'My Read Note')
        self.assertNotContains(response, 'Secret Other Note')

        # Unread filter
        response_unread = self.client.get(reverse('notifications') + '?filter=unread')
        self.assertEqual(response_unread.status_code, 200)
        self.assertContains(response_unread, 'My Unread Note')
        self.assertNotContains(response_unread, 'My Read Note')

    def test_notification_list_view_unauthenticated_redirects(self):
        """7. Anonymous user cannot access /notifications/ and is redirected to login."""
        response = self.client.get(reverse('notifications'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_mark_read_view_post_and_get(self):
        """8. NotificationMarkReadView accepts POST, rejects GET, rejects unauthorized user."""
        notif = Notification.objects.create(recipient=self.user, title='Sample', message='Sample')

        # Anonymous cannot mark read
        post_anon = self.client.post(reverse('notification-mark-read', kwargs={'pk': notif.pk}))
        self.assertEqual(post_anon.status_code, 302)

        # Other user cannot mark read
        self.client.login(username=self.other_user.username, password=self.password)
        post_other = self.client.post(reverse('notification-mark-read', kwargs={'pk': notif.pk}))
        self.assertEqual(post_other.status_code, 302)
        notif.refresh_from_db()
        self.assertFalse(notif.is_read)

        # Owner marks read
        self.client.login(username=self.user.username, password=self.password)
        post_owner = self.client.post(reverse('notification-mark-read', kwargs={'pk': notif.pk}))
        self.assertRedirects(post_owner, reverse('notifications'))
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

        # GET request returns 405 Method Not Allowed
        get_owner = self.client.get(reverse('notification-mark-read', kwargs={'pk': notif.pk}))
        self.assertEqual(get_owner.status_code, 405)

    def test_mark_all_read_view_post_and_get(self):
        """9. NotificationMarkAllReadView marks all user notifications as read via POST."""
        for i in range(2):
            Notification.objects.create(recipient=self.user, title=f'Note {i}', message='M')

        self.client.login(username=self.user.username, password=self.password)

        get_resp = self.client.get(reverse('notification-mark-all-read'))
        self.assertEqual(get_resp.status_code, 405)

        post_resp = self.client.post(reverse('notification-mark-all-read'))
        self.assertRedirects(post_resp, reverse('notifications'))
        self.assertEqual(Notification.objects.filter(recipient=self.user, is_read=False).count(), 0)

    def test_order_placed_notification_and_email(self):
        """10. Placing an order dispatches in-app notification and confirmation email."""
        from app.services.notification import notify_order_placed
        notif = notify_order_placed(self.order)

        self.assertIsNotNone(notif)
        self.assertEqual(notif.recipient, self.user)
        self.assertEqual(notif.notification_type, 'ORDER_PLACED')
        self.assertIn(self.order.order_number, notif.title)

        # Verify email in outbox
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn(self.order.order_number, sent_email.subject)
        self.assertEqual(sent_email.to, [self.user.email])
        self.assertIn('Order Confirmation', sent_email.subject)
        self.assertIn(self.order.shipping_name, sent_email.body)

    def test_order_fulfillment_transition_notifications_and_emails(self):
        """11. Advancing fulfillment status generates notifications and status emails."""
        from app.services.fulfillment import transition_order_status
        with self.captureOnCommitCallbacks(execute=True):
            transition_order_status(self.order, 'ACCEPTED', user=self.staff_user, notes='Order confirmed by kitchen')

        notif = Notification.objects.filter(order=self.order, notification_type='ORDER_ACCEPTED').first()
        self.assertIsNotNone(notif)
        self.assertIn('Accepted', notif.title)
        self.assertIn('Order confirmed by kitchen', notif.message)

        # Email sent
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn(self.order.order_number, sent_email.subject)
        self.assertIn('Accepted', sent_email.subject)
        self.assertEqual(sent_email.to, [self.user.email])

    def test_payment_confirmed_notification_and_email(self):
        """12. Process validated payment creates payment confirmed notification and receipt email."""
        from app.services.payment import create_payment, process_validated_payment
        payment = create_payment(self.order, payment_method='SSLCOMMERZ')

        val_data = {
            'status': 'VALID',
            'tran_id': payment.transaction_id,
            'amount': str(payment.amount),
            'currency': 'BDT',
            'val_id': 'VAL_12345678',
            'bank_tran_id': 'BANK_TX_999',
            'card_type': 'VISA-City Bank',
        }
        with self.captureOnCommitCallbacks(execute=True):
            success, result = process_validated_payment(val_data)
        self.assertTrue(success)

        notif = Notification.objects.filter(order=self.order, notification_type='PAYMENT_CONFIRMED').first()
        self.assertIsNotNone(notif)
        self.assertIn('Payment Received', notif.title)

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn('Payment Confirmed', sent_email.subject)
        self.assertIn(payment.transaction_id, sent_email.body)
        self.assertEqual(sent_email.to, [self.user.email])

    def test_payment_failed_notification_and_email(self):
        """13. Process failed payment creates payment failed notification and failure email."""
        from app.services.payment import create_payment, process_failed_payment
        payment = create_payment(self.order, payment_method='SSLCOMMERZ')

        with self.captureOnCommitCallbacks(execute=True):
            process_failed_payment(payment.transaction_id, reason='Insufficient balance in account')

        notif = Notification.objects.filter(order=self.order, notification_type='PAYMENT_FAILED').first()
        self.assertIsNotNone(notif)
        self.assertIn('Payment Failed', notif.title)
        self.assertIn('Insufficient balance', notif.message)

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn('Payment Failed', sent_email.subject)
        self.assertIn('Insufficient balance in account', sent_email.body)
        self.assertEqual(sent_email.to, [self.user.email])

    def test_duplicate_event_key_idempotency(self):
        """14. Repeated notifications for the same event key are deduplicated."""
        from app.services.notification import notify_order_placed
        notif1 = notify_order_placed(self.order)
        self.assertEqual(len(mail.outbox), 1)

        # Repeat call with identical event key
        notif2 = notify_order_placed(self.order)
        self.assertEqual(notif1.pk, notif2.pk)
        self.assertEqual(Notification.objects.filter(order=self.order, notification_type='ORDER_PLACED').count(), 1)
        # Email outbox remains at 1, no duplicate email sent
        self.assertEqual(len(mail.outbox), 1)

    def test_missing_recipient_email_gracefully_skipped(self):
        """15. User without an email gets in-app notification without email crash."""
        user_no_email = User.objects.create_user(username='no_email_user', password='Password123!', email='')
        order_no_email = Order.objects.create(
            user=user_no_email,
            shipping_name='No Email User',
            shipping_mobile='01700000000',
            shipping_locality='Locality',
            shipping_city='City',
            shipping_zipcode='1200',
            shipping_state='State',
            subtotal=Decimal('100.00'),
            total_discount=Decimal('0.00'),
            delivery_charge=Decimal('70.00'),
            grand_total=Decimal('170.00'),
        )
        from app.services.notification import notify_order_placed
        notif = notify_order_placed(order_no_email)
        self.assertIsNotNone(notif)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_exception_resilience(self):
        """16. Email transport failures are caught gracefully and do not crash workflows."""
        from app.services.notification import notify_order_placed
        with patch('django.core.mail.EmailMultiAlternatives.send') as mock_send:
            mock_send.side_effect = Exception("SMTP connection refused")
            # Should not raise exception
            notif = notify_order_placed(self.order)
            self.assertIsNotNone(notif)
            self.assertTrue(Notification.objects.filter(pk=notif.pk).exists())

    def test_admin_notification_list_and_actions(self):
        """17. Admin can view notification changelist and trigger mark read/unread actions."""
        notif = Notification.objects.create(
            recipient=self.user,
            title='Admin Action Test',
            message='Content',
            is_read=False
        )
        self.client.login(username=self.staff_user.username, password=self.password)

        # Admin changelist view
        resp = self.client.get('/admin/app/notification/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Admin Action Test')

        # Admin mark read action
        post_data = {
            'action': 'mark_as_read',
            '_selected_action': [str(notif.pk)],
        }
        action_resp = self.client.post('/admin/app/notification/', post_data)
        self.assertEqual(action_resp.status_code, 302)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertIsNotNone(notif.read_at)

        # Admin mark unread action
        post_unread = {
            'action': 'mark_as_unread',
            '_selected_action': [str(notif.pk)],
        }
        action_unread_resp = self.client.post('/admin/app/notification/', post_unread)
        self.assertEqual(action_unread_resp.status_code, 302)
        notif.refresh_from_db()
        self.assertFalse(notif.is_read)
        self.assertIsNone(notif.read_at)







