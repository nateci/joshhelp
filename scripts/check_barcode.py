"""Diagnose why the back of an ID fails, WITHOUT printing personal data.

    python scripts/check_barcode.py path/to/id_back.jpg

Prints whether a barcode was found, which processing step found it, the AAMVA version,
which field codes are present, and whether name / DOB / expiration parsed (yes/no only)."""
import re
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import aamva  # noqa: E402
import zxingcpp  # noqa: E402

img = cv2.imread(sys.argv[1], cv2.IMREAD_COLOR)
if img is None:
    sys.exit("could not open image")
print(f"image size: {img.shape[1]}x{img.shape[0]}")

text = None
for i, variant in enumerate(aamva._variants(img)):
    res = zxingcpp.read_barcodes(variant, formats=zxingcpp.BarcodeFormat.PDF417, text_mode=zxingcpp.TextMode.Plain)
    if res:
        text = res[0].text
        print(f"barcode found on processing step {i} (size {variant.shape[1]}x{variant.shape[0]})")
        break
if text is None:
    text = aamva.read_barcode(img)
    print("barcode found with alternate binarizer" if text else "NO BARCODE FOUND in any processing step")
if not text:
    print("-> retake: barcode filling most of the frame, in focus, no glare across it")
    sys.exit(1)

v = re.search(r"ANSI ?\d{6}(\d{2})", text)
print(f"AAMVA version: {v.group(1) if v else 'unknown'}   text length: {len(text)}")
codes = sorted(set(re.findall(r"(?:^|[\r\n\x1e]|DL|ID)(D[A-Z]{2})", text)))
print(f"field codes present: {' '.join(codes)}")
out = aamva.parse_aamva(text)
for key in ("first_name", "last_name", "date_of_birth", "expiration", "document_number", "country"):
    print(f"  {key:16} {'yes' if out.get(key) else 'NO'}")
