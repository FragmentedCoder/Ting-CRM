"""Images people upload: profile pictures and the company logo.

Every upload is decoded and re-encoded as PNG with Pillow, which drops metadata
(EXIF location and the like) and anything hidden in the file, and scales it
down. SVG isn't accepted: it can carry scripts, and needs a sanitizer first.
"""

from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import LargeBinary, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import clock
from app.db import Base, UTCDateTime

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "GIF"})
AVATAR_SIZE = (256, 256)
LOGO_SIZE = (512, 512)
# Refuse decompression bombs: a small file that unpacks into a huge picture.
Image.MAX_IMAGE_PIXELS = 40_000_000


class ImageRejected(ValueError):
    """The upload isn't an image Þing will store; the message is fit to show."""


class StoredImage(Base):
    __tablename__ = "stored_images"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(50))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


def clean_image(raw: bytes, *, max_size: tuple[int, int]) -> bytes:
    """Decode, re-encode as PNG without metadata, and fit within max_size."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageRejected("The image is larger than 2 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            if opened.format not in ALLOWED_FORMATS:
                raise ImageRejected("Use a PNG, JPEG, WebP or GIF image.")
            opened.load()
            # Turn it the way the camera meant before the EXIF data is dropped.
            image = ImageOps.exif_transpose(opened).convert("RGBA")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ImageRejected("That file isn't an image Þing can use.") from exc
    image.thumbnail(max_size)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def store_image(db: Session, key: str, png: bytes) -> None:
    db.merge(StoredImage(key=key, content_type="image/png", data=png, updated_at=clock.utcnow()))


def load_image(db: Session, key: str) -> StoredImage | None:
    return db.get(StoredImage, key)


def remove_image(db: Session, key: str) -> bool:
    result = db.execute(delete(StoredImage).where(StoredImage.key == key))
    return bool(getattr(result, "rowcount", 0))


def image_version(db: Session, key: str) -> int | None:
    """A number that changes with the image, so browsers fetch a new one when it does."""
    updated = db.scalar(select(StoredImage.updated_at).where(StoredImage.key == key))
    return int(updated.timestamp()) if updated else None


def avatar_key(user_id: int) -> str:
    return f"avatar/{user_id}"


def avatar_url(db: Session, user_id: int) -> str | None:
    version = image_version(db, avatar_key(user_id))
    return f"/api/users/{user_id}/avatar?v={version}" if version else None


IMAGE_HEADERS = {
    "Cache-Control": "private, max-age=86400",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'",
}
