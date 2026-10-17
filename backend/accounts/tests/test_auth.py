from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from profiles.models import HealthProfile

User = get_user_model()
STRONG = "Str0ng-Pass!2026"


class AuthTestBase(APITestCase):
    def signup(self, **overrides):
        data = {"name": "Sara Khan", "email": "sara@example.com", "password": STRONG}
        data.update(overrides)
        return self.client.post(reverse("signup"), data, format="json")

    def make_user(self, email="sara@example.com", password=STRONG):
        return User.objects.create_user(email=email, name="Sara Khan", password=password)

    def login(self, email="sara@example.com", password=STRONG):
        return self.client.post(
            reverse("user-login"), {"email": email, "password": password}, format="json"
        )


class SignupTests(AuthTestBase):
    def test_s1_valid_signup_creates_user_and_profile(self):
        response = self.signup()
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.data)
        user = User.objects.get(email="sara@example.com")
        self.assertEqual(user.role, "user")
        self.assertTrue(HealthProfile.objects.filter(user=user).exists())
        self.assertNotEqual(user.password, STRONG)  # stored as a hash
        self.assertTrue(user.check_password(STRONG))

    def test_s2_duplicate_email_in_any_case_is_rejected(self):
        self.signup()
        response = self.signup(email="SARA@Example.com")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
        self.assertEqual(User.objects.count(), 1)

    def test_s3_weak_passwords_are_rejected(self):
        for bad in ("12345678", "abc", "password"):
            response = self.signup(password=bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("password", response.data)
        self.assertEqual(User.objects.count(), 0)

    def test_s4_invalid_fields_are_rejected(self):
        self.assertIn("email", self.signup(email="not-an-email").data)
        self.assertIn("name", self.signup(name="").data)
        self.assertIn("name", self.signup(name="x" * 151).data)
        self.assertEqual(User.objects.count(), 0)

    def test_s5_email_is_trimmed_and_lowercased(self):
        response = self.signup(email="  Sara@Example.COM  ")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(email="sara@example.com").exists())

    def test_s6_role_in_request_is_ignored(self):
        response = self.signup(role="admin")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.get(email="sara@example.com").role, "user")


class LoginTests(AuthTestBase):
    def test_l1_login_sets_httponly_cookies_and_no_tokens_in_body(self):
        self.make_user()
        response = self.login()
        self.assertEqual(response.status_code, 200)
        for name in (settings.JWT_ACCESS_COOKIE, settings.JWT_REFRESH_COOKIE):
            morsel = response.cookies[name]
            self.assertTrue(morsel["httponly"])
            self.assertEqual(morsel["samesite"], "Lax")
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertNotIn("password", response.data["user"])
        self.assertIsNotNone(User.objects.get(email="sara@example.com").last_login)

    def test_l1_login_is_case_insensitive(self):
        self.make_user()
        self.assertEqual(self.login(email="SARA@EXAMPLE.COM").status_code, 200)

    def test_l2_wrong_password_and_unknown_email_give_the_same_error(self):
        self.make_user()
        wrong = self.login(password="Wrong-Pass-1")
        unknown = self.login(email="nobody@example.com")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.data, unknown.data)

    def test_l6_deactivated_user_cannot_log_in(self):
        user = self.make_user()
        user.is_active = False
        user.save()
        self.assertEqual(self.login().status_code, 401)

    def test_l7_admin_cannot_use_the_user_login(self):
        User.objects.create_admin(email="boss@example.com", name="Boss", password=STRONG)
        self.assertEqual(self.login(email="boss@example.com").status_code, 401)


class TokenTests(AuthTestBase):
    def test_me_without_cookie_is_401(self):
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)

    def test_me_works_after_login(self):
        self.make_user()
        self.login()
        response = self.client.get(reverse("me"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "sara@example.com")

    def test_l3_expired_access_token_is_rejected_and_refresh_fixes_it(self):
        user = self.make_user()
        self.login()
        expired = AccessToken.for_user(user)
        expired.set_exp(lifetime=timedelta(seconds=-10))
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = str(expired)
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)
        self.assertEqual(self.client.post(reverse("refresh")).status_code, 200)
        self.assertEqual(self.client.get(reverse("me")).status_code, 200)

    def test_l4_tampered_access_token_is_rejected(self):
        self.make_user()
        token = self.login().cookies[settings.JWT_ACCESS_COOKIE].value
        bad = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = bad
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)

    def test_l4_garbage_or_missing_refresh_token_is_rejected(self):
        self.assertEqual(self.client.post(reverse("refresh")).status_code, 401)
        self.client.cookies[settings.JWT_REFRESH_COOKIE] = "garbage"
        self.assertEqual(self.client.post(reverse("refresh")).status_code, 401)

    def test_refresh_token_cannot_be_used_as_access_token(self):
        user = self.make_user()
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = str(RefreshToken.for_user(user))
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)

    def test_r1_admin_token_is_rejected_on_user_endpoints(self):
        admin = User.objects.create_admin(email="boss@example.com", name="Boss", password=STRONG)
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = str(AccessToken.for_user(admin))
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)

    def test_l6_deactivated_user_loses_access_and_refresh(self):
        user = self.make_user()
        self.login()
        user.is_active = False
        user.save()
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)
        self.assertEqual(self.client.post(reverse("refresh")).status_code, 401)


class LogoutTests(AuthTestBase):
    def test_l5_logout_clears_cookies_and_blocks_access(self):
        self.make_user()
        self.login()
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 200)
        for name in (settings.JWT_ACCESS_COOKIE, settings.JWT_REFRESH_COOKIE):
            self.assertEqual(response.cookies[name].value, "")
            self.assertEqual(response.cookies[name]["max-age"], 0)
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)
        self.assertEqual(self.client.post(reverse("refresh")).status_code, 401)

    def test_logout_without_login_is_fine(self):
        self.assertEqual(self.client.post(reverse("logout")).status_code, 200)

    def test_logout_rejects_get(self):
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)