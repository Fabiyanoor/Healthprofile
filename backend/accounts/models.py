from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    """Creates users and admins. Emails are always stored in lowercase."""

    def create_user(self, email, name, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        if not password:
            raise ValueError("Password is required")
        user = self.model(email=email, name=name, **extra_fields)
        user.set_password(password)  # stores a hash, never the plain password
        user.save(using=self._db)
        return user

    def create_admin(self, email, name, password):
        """Admins are created only through this method (management command), never by public signup."""
        return self.create_user(email, name, password, role=User.Role.ADMIN)

    def get_by_natural_key(self, email):
        """Used by Django's login. Makes login case-insensitive."""
        return self.get(email__iexact=email)


class User(AbstractBaseUser):
    class Role(models.TextChoices):
        USER = "user", "User"
        ADMIN = "admin", "Admin"

    email = models.EmailField(max_length=254, unique=True)
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # password and last_login come from AbstractBaseUser

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    class Meta:
        constraints = [
            # Blocks A@x.com and a@x.com even if some code path forgets to lowercase
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
        ]
        indexes = [
            models.Index(fields=["role"], name="user_role_idx"),
        ]

    def save(self, *args, **kwargs):
        # Guarantees lowercase, trimmed email on every save path
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    def __str__(self):
        return self.email