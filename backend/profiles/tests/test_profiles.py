import io
import os
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from PIL import Image
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from profiles.models import EmergencyContact, HealthProfile

User = get_user_model()
STRONG = "Str0ng-Pass!2026"
ME = "profile-me"
CONTACTS = "contact-list"


def png_file(name="me.png", size=(10, 10)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def big_png_file(name="big.png"):
    buffer = io.BytesIO()
    Image.frombytes("RGB", (1000, 1000), os.urandom(3 * 1000 * 1000)).save(buffer, format="PNG")
    content = buffer.getvalue()
    assert len(content) > 2 * 1024 * 1024
    return SimpleUploadedFile(name, content, content_type="image/png")


class ProfileTestBase(APITestCase):
    def setUp(self):
        # Uploaded test pictures go to a temporary folder, not your real media folder
        self.media_dir = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_dir, True)
        self.user, self.client = self.make_user_client("sara@example.com")

    def make_user_client(self, email):
        user = User.objects.create_user(email=email, name="Test User", password=STRONG)
        HealthProfile.objects.create(user=user, full_name="Test User")
        client = APIClient()
        response = client.post(
            reverse("user-login"), {"email": email, "password": STRONG}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        return user, client

    def profile(self, user=None):
        return HealthProfile.objects.get(user=user or self.user)

    def add_contact(self, client, name="Ayesha", **extra):
        data = {"name": name, "relationship": "Sister", "phone": "+923001234567"}
        data.update(extra)
        return client.post(reverse(CONTACTS), data, format="json")


class ProfileTests(ProfileTestBase):
    def test_p1_get_own_profile_without_sensitive_fields(self):
        response = self.client.get(reverse(ME))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "sara@example.com")
        self.assertEqual(response.data["contacts"], [])
        for hidden in ("password", "token", "user", "role", "deactivated_at"):
            self.assertNotIn(hidden, response.data)

    def test_p2_partial_update_changes_only_the_sent_field(self):
        HealthProfile.objects.filter(user=self.user).update(wellness_goals="Walk daily")
        before = self.profile().updated_at
        response = self.client.patch(reverse(ME), {"full_name": "Sara K"}, format="json")
        self.assertEqual(response.status_code, 200)
        profile = self.profile()
        self.assertEqual(profile.full_name, "Sara K")
        self.assertEqual(profile.wellness_goals, "Walk daily")
        self.assertGreater(profile.updated_at, before)

    def test_p3_future_and_unrealistic_dates_are_rejected(self):
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        for bad in (future, "1850-01-01"):
            response = self.client.patch(reverse(ME), {"date_of_birth": bad}, format="json")
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("date_of_birth", response.data)

    def test_p4_date_of_birth_and_age_range_never_both(self):
        both = {"date_of_birth": "1995-05-01", "age_range": "25-34"}
        self.assertEqual(self.client.patch(reverse(ME), both, format="json").status_code, 400)

        self.assertEqual(
            self.client.patch(reverse(ME), {"date_of_birth": "1995-05-01"}, format="json").status_code,
            200,
        )
        # Stored date of birth + new age range sent alone must still be rejected
        response = self.client.patch(reverse(ME), {"age_range": "25-34"}, format="json")
        self.assertEqual(response.status_code, 400)

        # Switching clearly from one to the other is allowed
        switch = {"date_of_birth": None, "age_range": "25-34"}
        self.assertEqual(self.client.patch(reverse(ME), switch, format="json").status_code, 200)
        profile = self.profile()
        self.assertIsNone(profile.date_of_birth)
        self.assertEqual(profile.age_range, "25-34")

    def test_p5_phone_preference_needs_a_phone_number(self):
        url = reverse(ME)
        response = self.client.patch(url, {"contact_preference": "phone"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.data)

        ok = {"contact_preference": "phone", "phone": "+923001234567"}
        self.assertEqual(self.client.patch(url, ok, format="json").status_code, 200)
        # Clearing the phone while the preference is phone must fail
        self.assertEqual(self.client.patch(url, {"phone": ""}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"phone": "abc"}, format="json").status_code, 400)

    def test_p6_read_only_fields_cannot_be_changed(self):
        original_id = self.profile().id
        attack = {
            "status": "deactivated",
            "deactivated_at": "2020-01-01T00:00:00Z",
            "consent_accepted_at": "2020-01-01T00:00:00Z",
            "user": 9999,
            "email": "hacker@example.com",
            "id": 9999,
        }
        response = self.client.patch(reverse(ME), attack, format="json")
        self.assertEqual(response.status_code, 200)
        profile = self.profile()
        self.assertEqual(profile.id, original_id)
        self.assertEqual(profile.status, "active")
        self.assertIsNone(profile.deactivated_at)
        self.assertIsNone(profile.consent_accepted_at)
        self.assertEqual(profile.user_id, self.user.id)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "sara@example.com")

    def test_p7_no_login_means_401_everywhere(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get(reverse(ME)).status_code, 401)
        self.assertEqual(anonymous.patch(reverse(ME), {}, format="json").status_code, 401)
        self.assertEqual(anonymous.get(reverse(CONTACTS)).status_code, 401)
        self.assertEqual(anonymous.post(reverse(CONTACTS), {}, format="json").status_code, 401)

    def test_p8_users_only_ever_touch_their_own_profile(self):
        other, other_client = self.make_user_client("omar@example.com")
        self.client.patch(reverse(ME), {"full_name": "Sara Only"}, format="json")
        other_client.patch(reverse(ME), {"full_name": "Omar Only"}, format="json")
        self.assertEqual(self.profile().full_name, "Sara Only")
        self.assertEqual(self.profile(other).full_name, "Omar Only")
        self.assertEqual(self.client.get(reverse(ME)).data["email"], "sara@example.com")
        self.assertEqual(other_client.get(reverse(ME)).data["email"], "omar@example.com")

    def test_p9_empty_update_is_harmless(self):
        response = self.client.patch(reverse(ME), {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.profile().full_name, "Test User")

    def test_put_is_not_allowed(self):
        self.assertEqual(self.client.put(reverse(ME), {"full_name": "X"}, format="json").status_code, 405)

    def test_text_fields_have_a_length_limit(self):
        response = self.client.patch(reverse(ME), {"allergies": "x" * 2001}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_consent_is_recorded_once(self):
        self.client.patch(reverse(ME), {"consent": True}, format="json")
        first = self.profile().consent_accepted_at
        self.assertIsNotNone(first)
        self.client.patch(reverse(ME), {"consent": True}, format="json")
        self.client.patch(reverse(ME), {"consent": False}, format="json")
        self.assertEqual(self.profile().consent_accepted_at, first)

    def test_admin_token_is_rejected_on_profile_endpoints(self):
        admin = User.objects.create_admin(email="boss@example.com", name="Boss", password=STRONG)
        client = APIClient()
        client.cookies[settings.JWT_ACCESS_COOKIE] = str(AccessToken.for_user(admin))
        self.assertEqual(client.get(reverse(ME)).status_code, 401)

    def test_deactivation_blocks_access_and_login(self):
        self.profile().deactivate()
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(self.profile().status, "deactivated")
        self.assertEqual(self.client.get(reverse(ME)).status_code, 401)
        login = APIClient().post(
            reverse("user-login"),
            {"email": "sara@example.com", "password": STRONG},
            format="json",
        )
        self.assertEqual(login.status_code, 401)


class EmergencyContactTests(ProfileTestBase):
    def test_e1_first_contact_becomes_primary(self):
        response = self.add_contact(self.client, is_primary=False)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_primary"])

    def test_e2_second_and_third_contacts_are_allowed(self):
        flags = [self.add_contact(self.client, f"C{i}").data["is_primary"] for i in range(3)]
        self.assertEqual(flags, [True, False, False])

    def test_e3_fourth_contact_is_rejected(self):
        for i in range(3):
            self.add_contact(self.client, f"C{i}")
        response = self.add_contact(self.client, "C3")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(EmergencyContact.objects.filter(profile__user=self.user).count(), 3)

    def test_e4_new_primary_demotes_the_old_one(self):
        ids = [self.add_contact(self.client, f"C{i}").data["id"] for i in range(2)]
        response = self.client.patch(
            reverse("contact-detail", args=[ids[1]]), {"is_primary": True}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        primaries = EmergencyContact.objects.filter(profile__user=self.user, is_primary=True)
        self.assertEqual(primaries.count(), 1)
        self.assertEqual(primaries.get().id, ids[1])

    def test_primary_cannot_be_unset_directly(self):
        contact_id = self.add_contact(self.client).data["id"]
        response = self.client.patch(
            reverse("contact-detail", args=[contact_id]), {"is_primary": False}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_e5_deleting_the_primary_promotes_the_oldest_remaining(self):
        ids = [self.add_contact(self.client, f"C{i}").data["id"] for i in range(3)]
        response = self.client.delete(reverse("contact-detail", args=[ids[0]]))
        self.assertEqual(response.status_code, 204)
        remaining = list(
            EmergencyContact.objects.filter(profile__user=self.user).order_by("created_at", "id")
        )
        self.assertEqual([c.is_primary for c in remaining], [True, False])
        self.assertEqual(remaining[0].id, ids[1])

    def test_deleting_the_only_contact_is_allowed(self):
        contact_id = self.add_contact(self.client).data["id"]
        self.assertEqual(
            self.client.delete(reverse("contact-detail", args=[contact_id])).status_code, 204
        )
        self.assertEqual(EmergencyContact.objects.filter(profile__user=self.user).count(), 0)

    def test_e6_invalid_phone_or_name_is_rejected(self):
        self.assertEqual(self.add_contact(self.client, phone="abc").status_code, 400)
        self.assertEqual(self.add_contact(self.client, phone="").status_code, 400)
        self.assertEqual(self.add_contact(self.client, name="x" * 151).status_code, 400)
        self.assertEqual(self.add_contact(self.client, name="").status_code, 400)

    def test_e7_other_users_contacts_look_like_they_do_not_exist(self):
        other, other_client = self.make_user_client("omar@example.com")
        contact_id = self.add_contact(other_client, "Omar Contact").data["id"]
        url = reverse("contact-detail", args=[contact_id])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {"name": "Hacked"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(EmergencyContact.objects.get(id=contact_id).name, "Omar Contact")
        self.assertEqual(len(self.client.get(reverse(CONTACTS)).data), 0)

    def test_contact_cannot_be_moved_to_another_profile(self):
        other, _ = self.make_user_client("omar@example.com")
        other_profile = self.profile(other)
        contact_id = self.add_contact(self.client).data["id"]
        response = self.client.patch(
            reverse("contact-detail", args=[contact_id]),
            {"profile": other_profile.id, "name": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        contact = EmergencyContact.objects.get(id=contact_id)
        self.assertEqual(contact.profile.user_id, self.user.id)
        self.assertEqual(contact.name, "Renamed")

    def test_contacts_appear_inside_the_profile_with_primary_first(self):
        ids = [self.add_contact(self.client, f"C{i}").data["id"] for i in range(2)]
        self.client.patch(
            reverse("contact-detail", args=[ids[1]]), {"is_primary": True}, format="json"
        )
        contacts = self.client.get(reverse(ME)).data["contacts"]
        self.assertEqual([c["name"] for c in contacts], ["C1", "C0"])
        self.assertTrue(contacts[0]["is_primary"])


class PictureTests(ProfileTestBase):
    def upload(self, client, file):
        return client.patch(reverse(ME), {"profile_picture": file}, format="multipart")

    def test_f1_valid_picture_is_accepted_and_saved(self):
        response = self.upload(self.client, png_file())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["profile_picture"])
        self.assertTrue(os.path.exists(self.profile().profile_picture.path))

    def test_f2_wrong_type_or_fake_image_is_rejected(self):
        pdf = SimpleUploadedFile("a.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        fake = SimpleUploadedFile("fake.png", b"this is not an image", content_type="image/png")
        for bad in (pdf, fake):
            self.assertEqual(self.upload(self.client, bad).status_code, 400)
        self.assertFalse(self.profile().profile_picture)

    def test_f3_picture_over_2_mb_is_rejected(self):
        response = self.upload(self.client, big_png_file())
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.profile().profile_picture)

    def test_f4_same_file_name_does_not_overwrite(self):
        other, other_client = self.make_user_client("omar@example.com")
        self.upload(self.client, png_file("me.png"))
        self.upload(other_client, png_file("me.png"))
        first = self.profile().profile_picture.path
        second = self.profile(other).profile_picture.path
        self.assertNotEqual(first, second)
        self.assertTrue(os.path.exists(first))
        self.assertTrue(os.path.exists(second))

    def test_replacing_or_removing_the_picture_deletes_the_old_file(self):
        self.upload(self.client, png_file("one.png"))
        first = self.profile().profile_picture.path
        self.upload(self.client, png_file("two.png"))
        second = self.profile().profile_picture.path
        self.assertFalse(os.path.exists(first))
        self.assertTrue(os.path.exists(second))

        response = self.client.patch(reverse(ME), {"profile_picture": None}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.profile().profile_picture)
        self.assertFalse(os.path.exists(second))