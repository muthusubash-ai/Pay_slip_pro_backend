import io

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.settings import api_settings

from app.models.company import Company

UPLOAD_URL = "/api/v1/company/logo"


def _image_bytes(image_format="PNG", size=(32, 32), mode="RGB"):
    output = io.BytesIO()
    Image.new(mode, size, color=1).save(output, format=image_format)
    return output.getvalue()


def _upload(name, contents, content_type):
    return SimpleUploadedFile(name, contents, content_type=content_type)


def _animated_png_bytes():
    output = io.BytesIO()
    frames = [Image.new("RGB", (16, 16), color=color) for color in ("red", "blue")]
    frames[0].save(
        output,
        format="PNG",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return output.getvalue()


def test_valid_png_logo_is_normalized_and_saved(client, auth_headers):
    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("logo.png", _image_bytes(), "image/png")},
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["logo_data"].startswith("data:image/png;base64,")


def test_logo_upload_requires_authentication(client):
    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("logo.png", _image_bytes(), "image/png")},
        format="multipart",
    )

    assert response.status_code == 401


def test_rejects_non_image_payload_with_image_mime(client, auth_headers):
    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("logo.png", b"<script>alert(1)</script>", "image/png")},
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "valid image" in response.json()["detail"]


def test_rejects_empty_upload(client, auth_headers):
    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("empty.png", b"", "image/png")},
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_rejects_svg_upload(client, auth_headers):
    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml")},
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "PNG, JPEG, or WebP" in response.json()["detail"]


def test_rejects_mime_type_mismatch(client, auth_headers):
    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("logo.jpg", _image_bytes("PNG"), "image/jpeg")},
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]


def test_rejects_oversized_upload_before_processing(client, auth_headers):
    response = client.post(
        UPLOAD_URL,
        data={
            "file": _upload(
                "logo.png",
                b"x" * (settings.MAX_UPLOAD_SIZE + 1),
                "image/png",
            )
        },
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "under 5MB" in response.json()["detail"]


def test_rejects_excessive_image_dimensions(client, auth_headers):
    huge_but_compressed = _image_bytes(size=(settings.MAX_LOGO_DIMENSION + 1, 1), mode="1")
    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("wide.png", huge_but_compressed, "image/png")},
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "dimensions" in response.json()["detail"]


def test_rejects_animated_image(client, auth_headers):
    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("animated.png", _animated_png_bytes(), "image/png")},
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "Animated images" in response.json()["detail"]


def test_invalid_upload_does_not_replace_existing_logo(client, auth_headers):
    first_response = client.post(
        UPLOAD_URL,
        data={"file": _upload("logo.png", _image_bytes(), "image/png")},
        format="multipart",
        headers=auth_headers,
    )
    assert first_response.status_code == 200
    original_logo = first_response.json()["logo_data"]

    response = client.post(
        UPLOAD_URL,
        data={"file": _upload("bad.png", b"not-an-image", "image/png")},
        format="multipart",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert Company.objects.get(user__email="test@example.com").logo_data == original_logo


def test_logo_upload_is_rate_limited_per_user(client, auth_headers, monkeypatch):
    cache.clear()
    monkeypatch.setitem(api_settings.DEFAULT_THROTTLE_RATES, "logo_upload", "2/min")

    responses = [
        client.post(
            UPLOAD_URL,
            data={"file": _upload("logo.png", _image_bytes(), "image/png")},
            format="multipart",
            headers=auth_headers,
        )
        for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [200, 200, 429]
