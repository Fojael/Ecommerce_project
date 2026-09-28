from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from app.models import Customer


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
