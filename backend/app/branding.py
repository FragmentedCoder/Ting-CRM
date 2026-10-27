"""The site's look: its name, tag line, logo and colours, set by Administrators.

Shown on the sign-in page too, so reading them needs no sign-in; none of it is
secret. Changing them is in the admin panel (app/admin.py).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import DB
from app.colours import DEFAULT_ACCENT, DEFAULT_PRIMARY, SiteAccent, SitePrimary
from app.images import IMAGE_HEADERS, image_version, load_image
from app.policy import Setting
from app.setup import company_name

BRANDING_KEY = "branding"
LOGO_KEY = "branding/logo"
DEFAULT_SITE_NAME = "Þing"
DEFAULT_TAGLINE = "Gather. Agree. Remember."

router = APIRouter(prefix="/branding")


class Branding(BaseModel):
    site_name: str
    tagline: str
    company_name: str | None
    logo_url: str | None
    # The site's colours, which people may change for themselves unless enforced.
    primary_colour: SitePrimary
    accent_colour: SiteAccent
    enforce_colours: bool


def _stored(db: Session) -> dict[str, Any]:
    stored = db.get(Setting, BRANDING_KEY)
    return json.loads(stored.value) if stored else {}


def save_branding(
    db: Session, *, site_name: str, tagline: str, primary_colour: str,
    accent_colour: str, enforce_colours: bool,
) -> None:
    db.merge(Setting(key=BRANDING_KEY, value=json.dumps({
        "site_name": site_name.strip(), "tagline": tagline.strip(),
        "primary_colour": primary_colour, "accent_colour": accent_colour,
        "enforce_colours": enforce_colours,
    })))


def branding(db: Session) -> Branding:
    stored = _stored(db)
    version = image_version(db, LOGO_KEY)
    return Branding(
        site_name=stored.get("site_name") or DEFAULT_SITE_NAME,
        tagline=stored.get("tagline", DEFAULT_TAGLINE),
        company_name=company_name(db),
        logo_url=f"/api/branding/logo?v={version}" if version else None,
        primary_colour=stored.get("primary_colour", DEFAULT_PRIMARY),
        accent_colour=stored.get("accent_colour", DEFAULT_ACCENT),
        enforce_colours=bool(stored.get("enforce_colours", False)),
    )


@router.get("")
def get_branding(db: DB) -> Branding:
    return branding(db)


@router.get("/logo")
def get_logo(db: DB) -> Response:
    image = load_image(db, LOGO_KEY)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo is set.")
    return Response(image.data, media_type=image.content_type, headers=IMAGE_HEADERS)
