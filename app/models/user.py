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
        return self.create_user(email, password, **extra_fields)


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
    phone = models.CharField(max_length=20, null=True, blank=True)
    auth_provider = models.CharField(max_length=20, default="local")
    google_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

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

    def set_unusable_password(self):
        self.password = None

    def has_usable_password(self):
        return bool(self.password)

    @property
    def is_staff(self):
        return self.role == UserRole.admin or self.role == "admin"

    @property
    def is_superuser(self):
        return self.role == UserRole.admin or self.role == "admin"

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

