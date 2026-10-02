from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from app.models.base import TimestampModel


class UserRole:
    admin = "admin"
    hr_manager = "hr_manager"

    CHOICES = [
        (admin, "admin"),
        (hr_manager, "hr_manager"),
    ]


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.admin)
        extra_fields.setdefault("is_platform_admin", True)
        extra_fields.setdefault("plan", "enterprise")
        if extra_fields["is_platform_admin"] is not True:
            raise ValueError("Superuser must have is_platform_admin=True")
        user = self.create_user(email, password, **extra_fields)
        if password:
            user.set_admin_password(password)
            user.save(using=self._db, update_fields=["admin_password"])
        return user


class User(AbstractBaseUser, TimestampModel):
    # Mapping password field to hashed_password column
    password = models.CharField(db_column="hashed_password", max_length=255, null=True, blank=True)
    last_login = None
    
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(
        max_length=20, 
        choices=UserRole.CHOICES, 
        default=UserRole.hr_manager
    )
    is_active = models.BooleanField(default=True)
    plan = models.CharField(max_length=20, default="starter")
    plan_expires_at = models.DateTimeField(null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    auth_provider = models.CharField(max_length=20, default="local")
    google_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    admin_password = models.CharField(max_length=255, null=True, blank=True)
    auth_version = models.PositiveIntegerField(default=0)
    is_platform_admin = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    @property
    def is_plan_expired(self) -> bool:
        """Check if paid subscription has expired."""
        if self.plan_expires_at:
            from django.utils import timezone
            return timezone.now() > self.plan_expires_at
        return False

    def check_and_update_plan_expiry(self) -> bool:
        """Check if paid subscription has expired."""
        return self.is_plan_expired

    class Meta:
        db_table = "users"

    def set_password(self, raw_password):
        if raw_password is None:
            self.password = None
        else:
            from app.auth.jwt_handler import hash_password
            self.password = hash_password(raw_password)

    def check_password(self, raw_password):
        if not self.password or not raw_password:
            return False
        from app.auth.jwt_handler import verify_password
        return verify_password(raw_password, self.password)

    def set_admin_password(self, raw_password):
        """Set separate password hash strictly used for Django Admin login."""
        if raw_password is None:
            self.admin_password = None
        else:
            from app.auth.jwt_handler import hash_password
            self.admin_password = hash_password(raw_password)

    def check_admin_password(self, raw_password):
        """Check against admin_password, falling back to password only if admin_password is not set."""
        if not raw_password:
            return False
        if self.admin_password:
            from app.auth.jwt_handler import verify_password
            return verify_password(raw_password, self.admin_password)
        return self.check_password(raw_password)

    def set_unusable_password(self):
        self.password = None

    def has_usable_password(self):
        return bool(self.password)

    @property
    def is_staff(self):
        return self.is_active and self.is_platform_admin

    @property
    def is_superuser(self):
        return self.is_active and self.is_platform_admin

    def has_perm(self, perm, obj=None):
        return self.is_staff

    def has_module_perms(self, app_label):
        return self.is_staff

    @property
    def company_name(self):
        company = getattr(self, "company", None)
        return company.company_name if company else "-"

    def __str__(self):
        return self.email
