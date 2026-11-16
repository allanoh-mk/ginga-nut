from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps
from PIL.ImageSequence import Iterator

PACK_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
EVIDENCE_EXTENSIONS = PACK_PHOTO_EXTENSIONS | {".pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def validate_upload_size(upload) -> None:
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("File must be no larger than 10 MB.")


def validate_pack_photo_extension(upload) -> None:
    extension = PurePosixPath(upload.name).suffix.lower()
    if extension not in PACK_PHOTO_EXTENSIONS:
        raise ValidationError("Pack photos must be JPG, PNG, or WebP images.")


def validate_evidence_extension(upload) -> None:
    extension = PurePosixPath(upload.name).suffix.lower()
    if extension not in EVIDENCE_EXTENSIONS:
        raise ValidationError("Evidence must be a PDF, JPG, PNG, or WebP file.")


def strip_image_metadata(upload):
    extension = PurePosixPath(upload.name).suffix.lower()
    if extension not in PACK_PHOTO_EXTENSIONS:
        return upload

    upload.seek(0)
    with Image.open(upload) as source:
        if source.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValidationError("Image content must be JPEG, PNG, or WebP.")
        frames = [ImageOps.exif_transpose(frame.copy()) for frame in Iterator(source)]
        for frame in frames:
            frame.load()
        if source.format == "JPEG" and frames[0].mode not in {"L", "RGB"}:
            frames[0] = frames[0].convert("RGB")
        output = BytesIO()
        save_options = {}
        if len(frames) > 1:
            save_options["save_all"] = True
            save_options["append_images"] = frames[1:]
            for key in ("duration", "loop", "background"):
                if key in source.info:
                    save_options[key] = source.info[key]
        frames[0].save(output, format=source.format, **save_options)

    content = output.getvalue()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValidationError("Processed image must be no larger than 10 MB.")
    return ContentFile(content, name=upload.name)


def pack_photo_upload_to(instance, filename: str) -> str:
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in PACK_PHOTO_EXTENSIONS:
        raise ValidationError("Unsupported pack photo extension.")
    return f"orders/private/pack/{uuid4().hex}{extension}"


def evidence_upload_to(instance, filename: str) -> str:
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in EVIDENCE_EXTENSIONS:
        raise ValidationError("Unsupported evidence attachment extension.")
    return f"orders/private/evidence/{uuid4().hex}{extension}"
