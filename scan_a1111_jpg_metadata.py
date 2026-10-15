#!/usr/bin/env python3
"""Read-only JPEG scanner and single-file metadata inspector.

Directory scans classify A1111-style metadata as FULL, PARTIAL, or NONE. Use
--inspect FILE.jpg to print all readable metadata (EXIF, XMP, IPTC, JPEG
comments, other APP segments) including text not recognized as A1111.
Requires only the Python standard library; never modifies image files.
"""

import argparse
import csv
import os
from pathlib import Path
import re
import struct
import sys

VERSION = "1.00"
JPEG_SUFFIXES = {".jpg", ".jpeg"}

# A1111 generation infotext has a prompt, followed by settings including
# Steps, Sampler, and Seed. These checks distinguish it from ordinary EXIF.
_STEPS = re.compile(r"\bSteps\s*:\s*\d+\b", re.IGNORECASE)
_SAMPLER = re.compile(r"\bSampler\s*:\s*[^,\r\n]+", re.IGNORECASE)
_SEED = re.compile(r"\bSeed\s*:\s*-?\d+\b", re.IGNORECASE)


def looks_like_a1111(text):
    """Detect the FULL-generation signature (Steps, Sampler, and Seed)."""
    return bool(_STEPS.search(text) and _SAMPLER.search(text) and _SEED.search(text))


# Postprocessing-only EXIF UserComment text from A1111's Extras tab can be
# as short as "Postprocess upscale by: 4, Postprocess upscaler: 4x-UltraSharp".
# Unlike regular EXIF descriptions, those field names specifically identify
# A1111-style processing information.  They do NOT prove that the original
# image generation workflow can be reconstructed.
_POSTPROCESS_FIELDS = re.compile(
    r"(?:^|[,;\r\n])\s*(Postprocess\s+[A-Za-z][A-Za-z0-9 /+_.-]{0,60})\s*:\s*([^,;\r\n]+)",
    re.IGNORECASE,
)

# Fields characteristic of A1111 / A1111 extensions. A single recognizable
# non-generic field is enough to report PARTIAL metadata.
_DISTINCT_FIELDS = re.compile(
    r"(?:^|[,;\r\n])\s*("
    r"Hires (?:upscale|upscaler|steps|resize(?:-[12])?|checkpoint)|"
    r"ADetailer [A-Za-z][A-Za-z0-9 _/-]*|"
    r"(?:Lora|LoRA|TI) hashes|"
    r"(?:Variation seed(?: strength)?|Seed resize from(?:-[hw])?|"
    r"Clip skip|CFG scale|Denoising strength|Model hash|VAE hash|"
    r"Face restoration|Schedule type|Eta noise seed delta|ENSD)"
    r")\s*:\s*([^,;\r\n]+)",
    re.IGNORECASE,
)

# Single generic terms (e.g. "Model" or "Steps") are not enough to identify
# A1111: many unrelated tools use them. Two separate A1111-style generation
# fields provide reasonable evidence of incomplete generation parameters.
_GENERAL_FIELDS = {
    "steps": re.compile(r"\bSteps\s*:\s*\d+\b", re.IGNORECASE),
    "sampler": _SAMPLER,
    "seed": _SEED,
    "model": re.compile(r"(?:^|[,;\r\n])\s*Model\s*:\s*[^,;\r\n]+", re.IGNORECASE),
    "size": re.compile(r"\bSize\s*:\s*\d+\s*[xX]\s*\d+\b", re.IGNORECASE),
}


def classify_a1111(text):
    """Return (FULL/PARTIAL/NONE, explanation) for one metadata text field.

    FULL requires Steps, Sampler, and Seed, but does not guarantee a complete
    or reproducible workflow. PARTIAL means recognizable
    A1111-style settings remain but the FULL signature is absent.
    """
    if looks_like_a1111(text):
        return "FULL", "A1111-style Steps, Sampler, and Seed found"

    postprocess = list(dict.fromkeys(
        " ".join(match.group(1).split()) for match in _POSTPROCESS_FIELDS.finditer(text)
        if match.group(2).strip()
    ))
    if postprocess:
        return "PARTIAL", "A1111-style postprocessing fields: " + ", ".join(postprocess)

    distinct = list(dict.fromkeys(
        " ".join(match.group(1).split()) for match in _DISTINCT_FIELDS.finditer(text)
        if match.group(2).strip()
    ))
    if distinct:
        return "PARTIAL", "A1111-style parameter fields: " + ", ".join(distinct)

    common = [name for name, pattern in _GENERAL_FIELDS.items() if pattern.search(text)]
    if len(common) >= 2:
        return "PARTIAL", "Incomplete A1111-style generation settings: " + ", ".join(common)

    return "NONE", "No recognizable A1111 generation or postprocessing settings"


def decode_bytes(data):
    """Best-effort text decoding, including piexif's EXIF UserComment."""
    if data.startswith(b"UNICODE\x00"):
        raw = data[8:]
        if raw.startswith((b"\xfe\xff", b"\xff\xfe")):
            return raw.decode("utf-16", errors="replace").strip("\x00 \t\r\n")
        return raw.decode("utf-16-be", errors="replace").strip("\x00 \t\r\n")
    if data.startswith(b"ASCII\x00\x00\x00"):
        data = data[8:]
    elif data.startswith(b"JIS\x00\x00\x00\x00\x00"):
        return data[8:].decode("shift_jis", errors="replace").strip("\x00 \t\r\n")

    # Common for EXIF XPComment or non-standard UserComment encodings.
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace").strip("\x00 \t\r\n")
    if len(data) >= 8 and data.count(b"\x00") > len(data) // 4:
        even_zeros = data[::2].count(0)
        odd_zeros = data[1::2].count(0)
        encoding = "utf-16-be" if even_zeros > odd_zeros else "utf-16-le"
        try:
            return data.decode(encoding).strip("\x00 \t\r\n")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8").strip("\x00 \t\r\n")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace").strip("\x00 \t\r\n")


def extract_exif_text(app1_data):
    """Return potential generation-infotext fields from EXIF TIFF bytes."""
    if not app1_data.startswith(b"Exif\x00\x00"):
        return []
    tiff = app1_data[6:]
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        raise ValueError("invalid EXIF TIFF header")
    order = "<" if tiff[:2] == b"II" else ">"

    def u16(pos):
        if pos < 0 or pos + 2 > len(tiff):
            raise ValueError("truncated EXIF data")
        return struct.unpack_from(order + "H", tiff, pos)[0]

    def u32(pos):
        if pos < 0 or pos + 4 > len(tiff):
            raise ValueError("truncated EXIF data")
        return struct.unpack_from(order + "I", tiff, pos)[0]

    if u16(2) != 42:
        raise ValueError("unsupported EXIF TIFF format")

    type_widths = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1,
                   8: 2, 9: 4, 10: 8, 11: 4, 12: 8}

    def ifd(offset):
        count = u16(offset)
        if offset + 2 + count * 12 + 4 > len(tiff):
            raise ValueError("truncated EXIF IFD")
        tags = {}
        for idx in range(count):
            at = offset + 2 + idx * 12
            tag, kind = u16(at), u16(at + 2)
            n = u32(at + 4)
            unit = type_widths.get(kind)
            if unit is None:
                continue
            length = n * unit
            start = at + 8 if length <= 4 else u32(at + 8)
            if start > len(tiff) or length > len(tiff) - start:
                raise ValueError("EXIF tag points outside file")
            tags[tag] = (kind, tiff[start:start + length])
        return tags

    ifd0 = ifd(u32(4))
    texts = []
    if 0x010E in ifd0:  # ImageDescription (fallback)
        text = decode_bytes(ifd0[0x010E][1])
        if text:
            texts.append(("EXIF ImageDescription", text))
    if 0x9C9C in ifd0:  # Windows XPComment (fallback)
        raw = ifd0[0x9C9C][1]
        text = raw.decode("utf-16-le", errors="replace").strip("\x00 \t\r\n")
        if text:
            texts.append(("EXIF XPComment", text))

    if 0x8769 in ifd0:  # ExifIFDPointer
        kind, value = ifd0[0x8769]
        if kind == 4 and len(value) >= 4:
            exif_tags = ifd(struct.unpack(order + "I", value[:4])[0])
            if 0x9286 in exif_tags:  # UserComment: A1111's standard location
                text = decode_bytes(exif_tags[0x9286][1])
                if text:
                    texts.insert(0, ("EXIF UserComment", text))
    return texts


def scan_jpeg(path):
    """Return (FULL/PARTIAL/NONE/ERROR, location, explanation) read-only."""
    texts = []
    exif_errors = []
    try:
        with path.open("rb") as f:
            if f.read(2) != b"\xff\xd8":
                return "ERROR", "", "Not a valid JPEG (missing SOI marker)"

            # JPEG APP/COM markers precede the entropy-coded image data.
            while True:
                prefix = f.read(1)
                if not prefix:
                    return "ERROR", "", "Truncated JPEG header"
                if prefix != b"\xff":
                    return "ERROR", "", "Invalid JPEG marker sequence"
                marker = f.read(1)
                while marker == b"\xff":
                    marker = f.read(1)
                if not marker:
                    return "ERROR", "", "Truncated JPEG marker"
                code = marker[0]
                if code in (0xDA, 0xD9):  # Start of Scan or End of Image
                    break
                if code in (0x01, *range(0xD0, 0xD8)):
                    continue  # markers without payload

                length_bytes = f.read(2)
                if len(length_bytes) != 2:
                    return "ERROR", "", "Truncated JPEG segment length"
                length = struct.unpack(">H", length_bytes)[0]
                if length < 2:
                    return "ERROR", "", "Invalid JPEG segment length"
                payload = f.read(length - 2)
                if len(payload) != length - 2:
                    return "ERROR", "", "Truncated JPEG segment"
                if code == 0xE1 and payload.startswith(b"Exif\x00\x00"):
                    try:
                        texts.extend(extract_exif_text(payload))
                    except ValueError as exc:
                        exif_errors.append(str(exc))
                elif code == 0xFE:  # JPEG COM (nonstandard fallback)
                    text = decode_bytes(payload)
                    if text:
                        texts.append(("JPEG comment", text))
    except OSError as exc:
        return "ERROR", "", str(exc)

    first_partial = None
    for location, text in texts:
        category, explanation = classify_a1111(text)
        if category == "FULL":
            return "FULL", location, explanation
        if category == "PARTIAL" and first_partial is None:
            first_partial = ("PARTIAL", location, explanation)
    if first_partial is not None:
        return first_partial
    if exif_errors:
        return "ERROR", "EXIF", "; ".join(exif_errors)
    if texts:
        return "NONE", ", ".join(dict.fromkeys(location for location, _ in texts)), "Text metadata exists, but no recognizable A1111 settings found"
    return "NONE", "", "No recognizable A1111 metadata"


# Read-only single-file inspection (no third-party dependencies).
# These names are informational; unknown EXIF tags are still shown by hex ID.
_EXIF_NAMES = {
    0x0100: "ImageWidth", 0x0101: "ImageLength", 0x0102: "BitsPerSample",
    0x0103: "Compression", 0x0106: "PhotometricInterpretation",
    0x010E: "ImageDescription", 0x010F: "Make", 0x0110: "Model",
    0x02BC: "XMP", 0x83BB: "IPTC", 0x8649: "PhotoshopImageResources",
    0x0111: "StripOffsets", 0x0112: "Orientation", 0x0115: "SamplesPerPixel",
    0x011A: "XResolution", 0x011B: "YResolution", 0x0128: "ResolutionUnit",
    0x0131: "Software", 0x0132: "DateTime", 0x013B: "Artist",
    0x0201: "JPEGInterchangeFormat", 0x0202: "JPEGInterchangeFormatLength",
    0x0213: "YCbCrPositioning", 0x8298: "Copyright",
    0x829A: "ExposureTime", 0x829D: "FNumber",
    0x8769: "ExifIFDPointer", 0x8825: "GPSInfoIFDPointer",
    0x8822: "ExposureProgram", 0x8827: "ISOSpeedRatings",
    0x9000: "ExifVersion", 0x9003: "DateTimeOriginal",
    0x9004: "DateTimeDigitized", 0x9101: "ComponentsConfiguration",
    0x9201: "ShutterSpeedValue", 0x9202: "ApertureValue",
    0x9203: "BrightnessValue", 0x9204: "ExposureBiasValue",
    0x9207: "MeteringMode", 0x9209: "Flash", 0x920A: "FocalLength",
    0x927C: "MakerNote", 0x9286: "UserComment", 0x9290: "SubSecTime",
    0x9291: "SubSecTimeOriginal", 0x9292: "SubSecTimeDigitized",
    0x9C9B: "XPTitle", 0x9C9C: "XPComment", 0x9C9D: "XPAuthor",
    0x9C9E: "XPKeywords", 0x9C9F: "XPSubject",
    0xA000: "FlashpixVersion", 0xA001: "ColorSpace",
    0xA002: "PixelXDimension", 0xA003: "PixelYDimension",
    0xA005: "InteroperabilityIFDPointer", 0xA20E: "FocalPlaneXResolution",
    0xA20F: "FocalPlaneYResolution", 0xA217: "SensingMethod",
    0xA301: "SceneType", 0xA401: "CustomRendered",
    0xA402: "ExposureMode", 0xA403: "WhiteBalance",
    0xA406: "SceneCaptureType", 0xA420: "ImageUniqueID",
    0xA432: "LensSpecification", 0xA433: "LensMake",
    0xA434: "LensModel", 0xA435: "LensSerialNumber",
}
_GPS_NAMES = {
    0: "GPSVersionID", 1: "GPSLatitudeRef", 2: "GPSLatitude",
    3: "GPSLongitudeRef", 4: "GPSLongitude", 5: "GPSAltitudeRef",
    6: "GPSAltitude", 7: "GPSTimeStamp", 16: "GPSImgDirectionRef",
    17: "GPSImgDirection", 29: "GPSDateStamp",
}
_IPTC_NAMES = {
    (2, 5): "ObjectName", (2, 10): "Urgency", (2, 15): "Category",
    (2, 20): "SupplementalCategory", (2, 25): "Keywords",
    (2, 55): "DateCreated", (2, 60): "TimeCreated",
    (2, 80): "Byline", (2, 85): "BylineTitle", (2, 90): "City",
    (2, 95): "ProvinceState", (2, 101): "CountryCode",
    (2, 105): "Headline", (2, 110): "Credit", (2, 115): "Source",
    (2, 116): "CopyrightNotice", (2, 120): "CaptionAbstract",
    (2, 122): "CaptionWriter", (2, 135): "LanguageIdentifier",
}
_EXIF_WIDTHS = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1,
                7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8,
                13: 4}


def _read_jpeg_segments(path):
    """Yield header (marker, bytes) pairs without touching compressed pixels."""
    with path.open("rb") as f:
        if f.read(2) != b"\xff\xd8":
            raise ValueError("Not a valid JPEG (missing SOI marker)")
        while True:
            prefix = f.read(1)
            if not prefix:
                raise ValueError("Truncated JPEG header")
            if prefix != b"\xff":
                raise ValueError("Invalid JPEG marker sequence")
            marker = f.read(1)
            while marker == b"\xff":
                marker = f.read(1)
            if not marker:
                raise ValueError("Truncated JPEG marker")
            code = marker[0]
            if code in (0xDA, 0xD9):  # Image data starts at SOS.
                break
            if code in (0x01, *range(0xD0, 0xD8)):
                continue
            size = f.read(2)
            if len(size) != 2:
                raise ValueError("Truncated JPEG segment length")
            n = struct.unpack(">H", size)[0]
            if n < 2:
                raise ValueError("Invalid JPEG segment length")
            payload = f.read(n - 2)
            if len(payload) != n - 2:
                raise ValueError("Truncated JPEG segment")
            yield code, payload


def _binary_or_text(data, *, allow_text=True):
    """Show readable text in full; summarize non-text binary data."""
    if not data:
        return "(empty)"
    if allow_text:
        text = decode_bytes(data)
        controls = sum(ord(c) < 32 and c not in "\r\n\t" for c in text)
        replacements = text.count("\ufffd")
        if controls == 0 and replacements < max(1, len(text) // 10):
            return text or "(empty)"
    return f"<binary, {len(data)} bytes; first 32 bytes: {data[:32].hex(' ')}>"


def _exif_value(kind, count, raw, order, tag):
    if tag == 0x02BC:  # XMP may also be stored as EXIF tag 700.
        return _binary_or_text(raw)
    if tag == 0x9286:  # UserComment, including its encoding prefix.
        return decode_bytes(raw)
    if tag in (0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F):
        return raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    if kind == 2:  # ASCII
        return decode_bytes(raw.rstrip(b"\x00"))
    if kind == 7:
        if tag in (0x927C, 0x9101):  # MakerNote, binary components
            return _binary_or_text(raw, allow_text=False)
        return _binary_or_text(raw)
    if kind in (1, 6):
        vals = list(raw) if kind == 1 else list(struct.unpack(f"{len(raw)}b", raw))
    elif kind in (3, 8, 4, 9, 11, 12, 13):
        forms = {3: "H", 8: "h", 4: "I", 9: "i", 11: "f", 12: "d", 13: "I"}
        if count > 32:
            return f"<{count} numeric values, {len(raw)} bytes>"
        vals = list(struct.unpack(order + forms[kind] * count, raw))
    elif kind in (5, 10):
        if count > 32:
            return f"<{count} rational values, {len(raw)} bytes>"
        fmt = "I" if kind == 5 else "i"
        vals = []
        for a, b in struct.iter_unpack(order + fmt * 2, raw):
            vals.append(f"{a}/{b}" if b != 0 else f"{a}/0")
    else:
        return _binary_or_text(raw)
    if len(vals) > 32:
        return f"<{len(vals)} numeric values; first 16: {vals[:16]}>"
    return str(vals[0]) if len(vals) == 1 else str(vals)


def _inspect_exif(payload):
    """Enumerate EXIF tags, reporting broken references without losing good tags.

    It is common for otherwise usable EXIF to contain one invalid pointer,
    especially in thumbnail IFDs. Failures in one directory or entry must not
    prevent printing valid fields, including A1111's EXIF UserComment.
    """
    if not payload.startswith(b"Exif\x00\x00"):
        return []
    b = payload[6:]
    if len(b) < 8 or b[:2] not in (b"II", b"MM"):
        raise ValueError("Invalid EXIF TIFF header")
    order = "<" if b[:2] == b"II" else ">"

    def read(fmt, off):
        if off < 0 or off + struct.calcsize(fmt) > len(b):
            raise ValueError("EXIF offset outside segment")
        return struct.unpack_from(order + fmt, b, off)[0]

    if read("H", 2) != 42:
        raise ValueError("Unsupported EXIF TIFF format")
    seen = set()
    found = []

    def warning(label, error):
        found.append((f"{label} / Parse warning", f"<cannot parse: {error}>"))

    def walk(offset, label, depth=0):
        if not offset or offset in seen:
            return
        if depth > 8:
            warning(label, "EXIF IFD nesting too deep")
            return
        seen.add(offset)
        # The linked main TIFF IFD chain carries a 4-byte next-IFD offset.
        # EXIF/GPS/Interoperability sub-IFDs need not have that trailing field.
        # Some A1111 JPEGs place UserComment directly after the final EXIF
        # sub-IFD entry; reading the comment's first four bytes ("UNIC") as
        # a next-IFD pointer produces a spurious parse warning.
        is_main_chain = label.startswith("EXIF IFD0")
        try:
            count = read("H", offset)
            if offset + 2 + count * 12 + (4 if is_main_chain else 0) > len(b):
                raise ValueError("Truncated EXIF IFD or invalid IFD offset")
        except (ValueError, struct.error) as exc:
            warning(label, exc)
            return

        subdirs = []
        for idx in range(count):
            at = offset + 2 + idx * 12
            tag, kind, n = read("H", at), read("H", at + 2), read("I", at + 4)
            width = _EXIF_WIDTHS.get(kind)
            name = (_GPS_NAMES if label == "GPS IFD" else _EXIF_NAMES).get(tag, f"0x{tag:04X}")
            field_name = f"{label} / {name}"
            if width is None:
                found.append((field_name, f"<unsupported EXIF type {kind}, count {n}>"))
                continue
            length = n * width
            try:
                start = at + 8 if length <= 4 else read("I", at + 8)
                if start > len(b) or length > len(b) - start:
                    raise ValueError("Invalid EXIF tag data offset")
                raw = b[start:start + length]
                value = _exif_value(kind, n, raw, order, tag)
                found.append((field_name, value))
                if tag in (0x8769, 0x8825, 0xA005) and kind in (4, 13) and n == 1:
                    target = struct.unpack(order + "I", raw)[0]
                    subname = {0x8769: "EXIF IFD", 0x8825: "GPS IFD", 0xA005: "Interoperability IFD"}[tag]
                    subdirs.append((target, subname))
            except (ValueError, struct.error) as exc:
                found.append((field_name, f"<cannot parse: {exc}>"))
                continue

        # Only the main TIFF IFD chain has a defined next-IFD link.
        # Do not interpret the bytes after a nested EXIF/GPS IFD as a pointer.
        next_off = 0
        if is_main_chain:
            try:
                next_off = read("I", offset + 2 + count * 12)
            except (ValueError, struct.error) as exc:
                warning(label, exc)
        for target, subname in subdirs:
            walk(target, subname, depth + 1)
        if next_off:
            walk(next_off, label + " (next IFD)", depth + 1)

    walk(read("I", 4), "EXIF IFD0")
    return found

def _inspect_iptc(data):
    """Read IPTC-IIM records embedded in Photoshop's APP13 resources."""
    fields = []
    pos = 0
    while pos < len(data):
        if data[pos] != 0x1C or pos + 5 > len(data):
            break
        record, dataset = data[pos + 1], data[pos + 2]
        n = int.from_bytes(data[pos + 3:pos + 5], "big")
        pos += 5
        if n & 0x8000:  # extended-length IPTC dataset
            nbytes = n & 0x7FFF
            if nbytes == 0 or nbytes > 4 or pos + nbytes > len(data):
                raise ValueError("Invalid extended-length IPTC field")
            n = int.from_bytes(data[pos:pos + nbytes], "big")
            pos += nbytes
        if pos + n > len(data):
            raise ValueError("Truncated IPTC data")
        key = _IPTC_NAMES.get((record, dataset), f"{record}:{dataset}")
        fields.append((f"IPTC / {key}", _binary_or_text(data[pos:pos + n])))
        pos += n
    return fields


def _inspect_photoshop(data):
    items = []
    if not data.startswith(b"Photoshop 3.0\x00"):
        return [("APP13", _binary_or_text(data))]
    pos = len(b"Photoshop 3.0\x00")
    while pos < len(data):
        if data[pos:pos + 4] != b"8BIM" or pos + 7 > len(data):
            items.append(("Photoshop APP13", f"<unparsed resource data: {len(data) - pos} bytes>"))
            break
        resource_id = int.from_bytes(data[pos + 4:pos + 6], "big")
        pos += 6
        name_len = data[pos]
        pos += 1 + name_len
        if (name_len + 1) % 2:
            pos += 1
        if pos + 4 > len(data):
            raise ValueError("Truncated Photoshop resource header")
        n = int.from_bytes(data[pos:pos + 4], "big")
        pos += 4
        if pos + n > len(data):
            raise ValueError("Truncated Photoshop resource")
        block = data[pos:pos + n]
        pos += n + (n % 2)
        if resource_id == 0x0404:  # IPTC-NAA
            items.extend(_inspect_iptc(block))
            if not block:
                items.append(("IPTC", "(empty)"))
        else:
            items.append((f"Photoshop resource 0x{resource_id:04X}",
                          _binary_or_text(block, allow_text=False)))
    return items


def inspect_metadata(path):
    """Return (metadata entries, technical entries) for a single JPEG."""
    metadata = []
    technical = []
    xmp_extensions = {}
    for code, payload in _read_jpeg_segments(path):
        if code == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            try:
                fields = _inspect_exif(payload)
                metadata.extend(fields or [("EXIF", "EXIF block has no tags")])
            except (ValueError, struct.error) as exc:
                metadata.append(("EXIF", f"<cannot parse: {exc}; {len(payload)} bytes>"))
        elif code == 0xE1 and payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00"):
            xml = payload[len(b"http://ns.adobe.com/xap/1.0/\x00"):]
            metadata.append(("XMP", _binary_or_text(xml)))
        elif code == 0xE1 and payload.startswith(b"http://ns.adobe.com/xmp/extension/\x00"):
            data = payload[len(b"http://ns.adobe.com/xmp/extension/\x00"):]
            if len(data) >= 40:
                guid = data[:32].decode("ascii", errors="replace")
                total, offset = struct.unpack(">II", data[32:40])
                xmp_extensions.setdefault(guid, []).append((total, offset, data[40:]))
            else:
                metadata.append(("Extended XMP", f"<truncated: {len(data)} bytes>"))
        elif code == 0xE1:
            metadata.append(("APP1 (unrecognized)", _binary_or_text(payload)))
        elif code == 0xED:  # Photoshop / IPTC APP13
            try:
                metadata.extend(_inspect_photoshop(payload))
            except ValueError as exc:
                metadata.append(("APP13", f"<cannot parse: {exc}; {len(payload)} bytes>"))
        elif code == 0xFE:
            metadata.append(("JPEG comment (COM)", _binary_or_text(payload)))
        elif code == 0xE0 and payload.startswith(b"JFIF\x00"):
            if len(payload) >= 12:
                major, minor, units = payload[5], payload[6], payload[7]
                xd, yd = struct.unpack(">HH", payload[8:12])
                technical.append(("JFIF header", f"version {major}.{minor:02d}, units={units}, density={xd}x{yd}"))
            else:
                technical.append(("JFIF header", f"<{len(payload)} bytes>"))
        elif code == 0xE0 and payload.startswith(b"JFXX\x00"):
            technical.append(("JFIF extension", f"<binary, {len(payload)} bytes>"))
        elif code == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"):
            part = payload[len(b"ICC_PROFILE\x00"):]
            technical.append(("ICC color profile", f"chunk {part[0]}/{part[1]}, {max(0,len(part)-2)} bytes" if len(part) >= 2 else "<truncated>"))
        elif code == 0xEE and payload.startswith(b"Adobe"):
            technical.append(("Adobe APP14", f"<binary, {len(payload)} bytes>"))
        elif 0xE0 <= code <= 0xEF:  # Other application metadata
            metadata.append((f"APP{code - 0xE0} (unrecognized)", _binary_or_text(payload)))
    for guid, chunks in xmp_extensions.items():
        total = chunks[0][0]
        if total > 32 * 1024 * 1024:
            metadata.append((f"Extended XMP ({guid})", f"<declared size {total} bytes; too large to assemble>"))
            continue
        buf = bytearray(total)
        written = bytearray(total)
        valid = True
        for declared, offset, part in chunks:
            if declared != total or offset + len(part) > total:
                valid = False
                break
            buf[offset:offset + len(part)] = part
            written[offset:offset + len(part)] = b"\x01" * len(part)
        if valid and all(written):
            metadata.append((f"Extended XMP ({guid})", _binary_or_text(bytes(buf))))
        else:
            metadata.append((f"Extended XMP ({guid})", f"<incomplete/invalid, {len(chunks)} segment(s), declared {total} bytes>"))
    return metadata, technical


def print_inspection(path):
    if not path.is_file() or path.suffix.lower() not in JPEG_SUFFIXES:
        print("ERROR: --inspect requires an existing .jpg or .jpeg file", file=sys.stderr)
        return 2
    try:
        metadata, technical = inspect_metadata(path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot inspect {path}: {exc}", file=sys.stderr)
        return 2
    status, location, reason = scan_jpeg(path)
    print(f"File: {path}")
    if status in ("FULL", "PARTIAL"):
        print(f"A1111 metadata: {status} ({location}; {reason})")
    elif status == "ERROR":
        print(f"A1111 metadata: SCAN ERROR ({reason})")
    else:
        print(f"A1111 metadata: NONE ({reason})")
    if metadata:
        print(f"\nEmbedded metadata ({len(metadata)} field(s)):")
        for key, value in metadata:
            print(f"\n  {key}:")
            for line in str(value).splitlines() or [""]:
                print(f"    {line}")
    else:
        print("\nNo descriptive or generation metadata found.")
    if technical:
        print(f"\nTechnical JPEG metadata ({len(technical)} field(s)):")
        for key, value in technical:
            print(f"  {key}: {value}")
    elif not metadata:
        print("No embedded metadata found in JPEG header segments.")
    return 0


def iter_jpegs(path, recursive):
    if path.is_file():
        if path.suffix.lower() not in JPEG_SUFFIXES:
            raise ValueError("Input file must end in .jpg or .jpeg")
        yield path
    elif path.is_dir():
        if recursive:
            for folder, subdirs, names in os.walk(path):
                subdirs.sort(key=str.casefold)
                for name in sorted(names, key=str.casefold):
                    if Path(name).suffix.lower() in JPEG_SUFFIXES:
                        yield Path(folder) / name
        else:
            for item in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
                if item.is_file() and item.suffix.lower() in JPEG_SUFFIXES:
                    yield item
    else:
        raise ValueError("Input must be an existing directory or JPEG file")


def main():
    parser = argparse.ArgumentParser(
        description="Read-only scan: categorize JPG/JPEG metadata as FULL, PARTIAL or NONE."
    )
    parser.add_argument("directory", nargs="?", type=Path, default=Path("."),
                        help="Directory to scan (default: current directory), or one JPEG file")
    parser.add_argument("--inspect", type=Path, metavar="FILE.jpg",
                        help="Show all readable metadata in one JPEG (instead of scanning a directory)")
    parser.add_argument("--recursive", action="store_true", help="Also scan subdirectories")
    parser.add_argument("--report", type=Path, metavar="FILE.csv", help="Save per-file results to a CSV")
    parser.add_argument("--quiet", action="store_true", help="Only print totals (CSV still contains all results)")
    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    args = parser.parse_args()

    if args.inspect is not None:
        if args.report is not None or args.recursive or args.quiet:
            parser.error("--inspect cannot be combined with --report, --recursive, or --quiet")
        return print_inspection(args.inspect)

    try:
        targets = list(iter_jpegs(args.directory, args.recursive))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    counts = {"FULL": 0, "PARTIAL": 0, "NONE": 0, "ERROR": 0}
    report_file = None
    try:
        writer = None
        if args.report is not None:
            report_file = args.report.open("w", encoding="utf-8-sig", newline="")
            writer = csv.writer(report_file)
            writer.writerow(["file", "a1111_metadata", "location", "details"])
        for path in targets:
            status, location, details = scan_jpeg(path)
            counts[status] += 1
            if writer:
                writer.writerow([str(path), status, location, details])
            if not args.quiet:
                extra = f" ({location}; {details})" if status == "PARTIAL" else (
                    f" ({location})" if status == "FULL" else f" ({details})"
                )
                print(f"[{status:<7}] {path}{extra}")
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if report_file is not None:
            report_file.close()

    print(f"\nTotal JPEG files: {len(targets)} | A1111 FULL: {counts['FULL']} | "
          f"PARTIAL: {counts['PARTIAL']} | NONE: {counts['NONE']} | "
          f"ERRORS: {counts['ERROR']}")
    if args.report is not None:
        print(f"CSV report: {args.report}")
    return 1 if counts['ERROR'] else 0


if __name__ == "__main__":
    sys.exit(main())
