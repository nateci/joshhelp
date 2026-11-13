"""Decode and parse the PDF417 barcode on the back of US/Canadian IDs (AAMVA format)."""
import re
from datetime import date

import cv2
import numpy as np
import zxingcpp

# AAMVA element IDs we care about.
FIELDS = {
    "DCS": "last_name",
    "DAB": "last_name",  # AAMVA 2000 (version 1) cards
    "DAC": "first_name",
    "DCT": "first_name",  # older card versions
    "DAA": "full_name",  # version 1: "LAST,FIRST,MIDDLE" in one field
    "DAD": "middle_name",
    "DBB": "date_of_birth",
    "DBA": "expiration",
    "DBD": "issue_date",
    "DAQ": "document_number",
    "DAJ": "state",
    "DBC": "sex",
    "DCG": "country",
}
DATE_FIELDS = {"date_of_birth", "expiration", "issue_date"}
SEX = {"1": "M", "2": "F", "9": "X"}


def _variants(img: np.ndarray):
    """Progressively more processed versions of a phone photo: as-is, then grayscale at a few
    sizes (the barcode is often small in a 12MP photo), then contrast-boosted to fight glare."""
    yield img
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    h, w = gray.shape
    sizes = (2000, 1400, 1000) if max(h, w) > 1000 else (max(h, w) * 2,)  # upscale small crops
    for side in sizes:
        scale = side / max(h, w)
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        g = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=interp) if scale != 1 else gray
        yield g
        yield clahe.apply(g)
        yield cv2.GaussianBlur(g, (0, 0), 1.0)  # smooths sensor noise / moire on the bars
        yield cv2.addWeighted(g, 1.6, cv2.GaussianBlur(g, (0, 0), 2.0), -0.6, 0)  # unsharp mask for soft focus


def read_barcode(img: np.ndarray) -> str | None:
    """Return the raw text of the first PDF417 barcode in the image, or None."""
    for variant in _variants(img):
        for binarizer in (zxingcpp.Binarizer.LocalAverage, zxingcpp.Binarizer.GlobalHistogram):
            results = zxingcpp.read_barcodes(
                variant, formats=zxingcpp.BarcodeFormat.PDF417,
                text_mode=zxingcpp.TextMode.Plain, binarizer=binarizer,
            )
            if results:
                return results[0].text
    return None


def _parse_date(value: str, country: str | None) -> date | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 8:
        return None
    mdy = (int(digits[4:]), int(digits[:2]), int(digits[2:4]))  # USA: MMDDCCYY
    ymd = (int(digits[:4]), int(digits[4:6]), int(digits[6:]))  # Canada: CCYYMMDD
    for y, m, d in (ymd, mdy) if country == "CAN" else (mdy, ymd):
        try:
            return date(y, m, d)
        except ValueError:
            continue
    return None


def parse_aamva(text: str) -> dict:
    """Parse AAMVA barcode text into a flat dict of the fields in FIELDS."""
    # Skip the header: the DL/ID subfile starts at "DL" or "ID" followed by an element ID.
    start = re.search(r"(?:DL|ID)(?=D[A-Z]{2})", text)
    body = text[start.end():] if start else text

    raw: dict[str, str] = {}
    for line in re.split(r"[\r\n\x1e\x1d]+", body):
        m = re.match(r"^(D[A-Z]{2})(.*)$", line.strip())
        if m and m.group(1) in FIELDS:
            raw.setdefault(m.group(1), m.group(2).strip())

    out: dict = {}
    for code, value in raw.items():
        out.setdefault(FIELDS[code], value)

    full = out.pop("full_name", None)
    if full and not (out.get("first_name") and out.get("last_name")):
        parts = [p.strip() for p in re.split(r"[,$]", full)] + ["", "", ""]
        out.setdefault("last_name", parts[0] or None)
        out.setdefault("first_name", parts[1] or None)
        out.setdefault("middle_name", parts[2] or None)
    # DCT sometimes holds "FIRST,MIDDLE"
    if out.get("first_name") and "," in out["first_name"]:
        first, _, middle = out["first_name"].partition(",")
        out["first_name"] = first.strip()
        out.setdefault("middle_name", middle.strip() or None)

    country = out.get("country")
    for key in DATE_FIELDS & out.keys():
        out[key] = _parse_date(out[key], country)
    if "sex" in out:
        out["sex"] = SEX.get(out["sex"], out["sex"])

    parts = [out.get("first_name"), out.get("middle_name"), out.get("last_name")]
    name = " ".join(p for p in parts if p and p.upper() not in ("NONE", "UNAVL"))
    out["name"] = name or None
    return out
