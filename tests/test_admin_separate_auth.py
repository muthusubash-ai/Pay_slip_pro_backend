import pytest
from django.contrib.auth import authenticate
from app.models.user import User
from app.services.auth_service import authenticate_user, generate_reset_code, reset_password_with_code


@pytest.mark.django_db
def test_separate_admin_and_web_passwords():
    email = "admin_isolated_test@example.com"
    user = User.objects.create_superuser(
        email=email,
        password="InitialAdminPass123!@#",
        full_name="Admin Test",
    )

    admin_pass = "DedicatedAdminSecret123!@#"
    web_pass = "DedicatedWebPass123!@#"

    user.set_admin_password(admin_pass)
    user.set_password(web_pass)
    user.save()

    # 1. Django admin authentication: MUST succeed with admin_pass, MUST fail with web_pass
    assert authenticate(username=email, password=admin_pass) is not None
    assert authenticate(username=email, password=web_pass) is None

    # 2. Web application authentication: MUST succeed with web_pass, MUST fail with admin_pass
    web_res = authenticate_user(None, email, web_pass)
    assert "access_token" in web_res

    with pytest.raises(Exception):
        authenticate_user(None, email, admin_pass)

    # 3. Web app Forgot Password Reset: resets ONLY web_pass; admin_pass MUST remain unchanged
    code = generate_reset_code(None, email)
    new_web_pass = "NewResetWebPassword999!@#"
    assert reset_password_with_code(None, email, code, new_web_pass) is True

    # Web login now works with the new web password
    new_web_res = authenticate_user(None, email, new_web_pass)
    assert "access_token" in new_web_res

    # Django admin is completely intact with original admin_pass
    assert authenticate(username=email, password=admin_pass) is not None

    # Django admin CANNOT be logged into with the new web password
    assert authenticate(username=email, password=new_web_pass) is None
