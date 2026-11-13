"""Decode and parse the PDF417 barcode on the back of US/Canadian IDs (AAMVA format)."""
import re
from datetime import date

import numpy as np
import zxingcpp

# AAMVA element IDs we care about.
FIELDS = {
    "DCS": "last_name",
    "DAC": "first_name",
    "DCT": "first_name",  # older card versions
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


def read_barcode(img: np.ndarray) -> str | None:
    """Return the raw text of the first PDF417 barcode in the image, or None."""
    results = zxingcpp.read_barcodes(
        img, formats=zxingcpp.BarcodeFormat.PDF417, text_mode=zxingcpp.TextMode.Plain
    )
    return results[0].text if results else None


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

    country = out.get("country")
    for key in DATE_FIELDS & out.keys():
        out[key] = _parse_date(out[key], country)
    if "sex" in out:
        out["sex"] = SEX.get(out["sex"], out["sex"])

    parts = [out.get("first_name"), out.get("middle_name"), out.get("last_name")]
    name = " ".join(p for p in parts if p and p.upper() not in ("NONE", "UNAVL"))
    out["name"] = name or None
    return out
