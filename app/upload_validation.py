import io
import warnings

from django.conf import settings
from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from app.exceptions import BadRequestError

ALLOWED_LOGO_FORMATS = {
    "JPEG": {"image/jpeg"},
    "PNG": {"image/png"},
    "WEBP": {"image/webp"},
}


def validate_logo_upload(uploaded_file) -> bytes:
    """Return verified image bytes without trusting filename or MIME alone."""
    declared_size = getattr(uploaded_file, "size", None)
    if declared_size is not None and declared_size > settings.MAX_UPLOAD_SIZE:
        raise BadRequestError("Logo file must be under 5MB.")

    declared_type = (getattr(uploaded_file, "content_type", "") or "").split(";", 1)[0].lower()
    allowed_types = {mime for types in ALLOWED_LOGO_FORMATS.values() for mime in types}
    if declared_type and declared_type not in allowed_types:
        raise BadRequestError("Logo must be a PNG, JPEG, or WebP image.")

    contents = uploaded_file.read(settings.MAX_UPLOAD_SIZE + 1)
    if not contents:
        raise BadRequestError("Logo file is empty.")
    if len(contents) > settings.MAX_UPLOAD_SIZE:
        raise BadRequestError("Logo file must be under 5MB.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
            with PILImage.open(io.BytesIO(contents)) as image:
                image_format = image.format
                width, height = image.size

                if image_format not in ALLOWED_LOGO_FORMATS:
                    raise BadRequestError("Logo must be a PNG, JPEG, or WebP image.")
                if declared_type and declared_type not in ALLOWED_LOGO_FORMATS[image_format]:
                    raise BadRequestError("Logo content does not match its declared file type.")
                if width <= 0 or height <= 0:
                    raise BadRequestError("Logo has invalid dimensions.")
                if width > settings.MAX_LOGO_DIMENSION or height > settings.MAX_LOGO_DIMENSION:
                    raise BadRequestError(
                        f"Logo dimensions must not exceed {settings.MAX_LOGO_DIMENSION}px per side."
                    )
                if width * height > settings.MAX_LOGO_PIXELS:
                    raise BadRequestError("Logo image dimensions are too large.")
                if getattr(image, "n_frames", 1) != 1:
                    raise BadRequestError("Animated images are not supported for company logos.")

                image.verify()
    except BadRequestError:
        raise
    except (UnidentifiedImageError, PILImage.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise BadRequestError("Logo file is not a valid image.")

    return contents
