# A1111 JPG Metadata Scanner

**Version:** 1.00  
**Script:** `scan_a1111_jpg_metadata.py`

A **read-only Python utility** for finding and examining metadata in JPG/JPEG images, with emphasis on **AUTOMATIC1111 (A1111) Stable Diffusion WebUI** generation and postprocessing information.

It answers two questions:

1. **Which JPGs have recognizable A1111-related metadata?** Scan a folder and classify files as `FULL`, `PARTIAL`, or `NONE` (with `ERROR` for unreadable or malformed metadata).
2. **What metadata is actually stored in a JPG?** Use `--inspect` to display readable EXIF, XMP, IPTC, JPEG comments, and other header metadata for a single file.

> [!IMPORTANT]
> This is an **inspector, not a converter**. It does not modify JPGs, convert images to PNG, or create ComfyUI workflows.

## Requirements

- Python 3 (Python 3.8 or newer recommended).
- No additional Python packages: **standard library only**.
- Windows 10/11, macOS, or another platform with Python 3.

## Quick start

Save `scan_a1111_jpg_metadata.py` in the folder containing your JPEGs, open a terminal there, and run:

**Windows (Command Prompt or PowerShell):**

```cmd
py scan_a1111_jpg_metadata.py .
```

**macOS (Terminal):**

```bash
python3 scan_a1111_jpg_metadata.py .
```

`.` means the **current directory**. By default, subfolders are not scanned. The scanner recognizes `.jpg` and `.jpeg` extensions case-insensitively (including `.JPG` and `.JPEG`). Other file types, including PNGs, are ignored in folder scans.

## Examples

| Task | Windows command |
| --- | --- |
| Scan current folder | `py scan_a1111_jpg_metadata.py .` |
| Scan another folder | `py scan_a1111_jpg_metadata.py "C:\Images\My JPGs"` |
| Include subfolders | `py scan_a1111_jpg_metadata.py . --recursive` |
| Write results to CSV | `py scan_a1111_jpg_metadata.py . --report results.csv` |
| CSV plus summary only | `py scan_a1111_jpg_metadata.py . --quiet --report results.csv` |
| Classify a single JPEG | `py scan_a1111_jpg_metadata.py "image001.jpg"` |
| **Inspect** one JPEG's metadata | `py scan_a1111_jpg_metadata.py --inspect "image001.jpg"` |
| Show help | `py scan_a1111_jpg_metadata.py --help` |
| Show version | `py scan_a1111_jpg_metadata.py --version` |

On macOS, substitute `python3` for `py`. Quote file/folder paths that contain spaces.

### Sample scan output

```text
[FULL   ] image001.jpg (EXIF UserComment)
[PARTIAL] image002.jpg (EXIF UserComment; A1111-style postprocessing fields: Postprocess upscaler)
[NONE   ] image003.jpg (No recognizable A1111 metadata)

Total JPEG files: 3 | A1111 FULL: 1 | PARTIAL: 1 | NONE: 1 | ERRORS: 0
```

## What `FULL`, `PARTIAL`, `NONE`, and `ERROR` mean

| Result | Meaning | Example |
| --- | --- | --- |
| **FULL** | One recognized text field contains A1111-style **Steps**, **Sampler**, and **Seed** settings. This is *not* proof that the original generation workflow is complete or reproducible. | `Steps: 30, Sampler: Euler a, Seed: 12345` |
| **PARTIAL** | Recognizable A1111-style parameters exist, but the `FULL` signature is missing. Can include postprocessing or incomplete generation settings. | `Postprocess upscale by: 4, Postprocess upscaler: 4x-UltraSharp` |
| **NONE** | No recognizable A1111 parameters were detected by the scanner's current rules. **Other metadata may still be present.** | Camera EXIF or descriptive text only |
| **ERROR** | The file could not be scanned reliably because of a malformed JPEG, read error, or unparseable EXIF without usable recognized content. | Truncated JPEG metadata |

`PARTIAL` can also result from distinctive fields like `Hires upscaler`, `CFG scale`, or combinations of two common generation fields such as `Steps` plus `Sampler`.

**Important distinction:** these are **metadata recognition categories**, **not ComfyUI workflow feasibility categories**. `FULL` does not promise a complete graph, and `PARTIAL` can still preserve useful processing history. Detection is pattern-based: it cannot certify what program actually created a file, and unfamiliar A1111 metadata may be classified `NONE`.

## What metadata does the scanner recognize?

For directory classification, the scanner checks readable text in **JPEG header metadata**:

- **EXIF `UserComment`** — the usual location for A1111 generation information in JPGs.
- **EXIF `ImageDescription`**.
- **EXIF `XPComment`**.
- **JPEG `COM` (comment) segments**.

It examines header segments **without decoding the image pixels**, making it practical for large collections.

> [!NOTE]
> The classifier does **not** currently evaluate XMP or IPTC text for A1111 patterns. Those formats can still be displayed by the **single-file inspector** when readable.

## Inspect all readable metadata in a single JPG

To see *what* is actually stored, regardless of whether it matches A1111 patterns:

```cmd
py scan_a1111_jpg_metadata.py --inspect "image001.jpg"
```

You may also provide an absolute or relative path to the file. The inspector reports the A1111 detection category, then displays accessible metadata, including:

- **EXIF:** `UserComment`, `ImageDescription`, software, dates, orientation, GPS, and other known/unknown tag IDs.
- **XMP:** XML/text metadata; Extended XMP when all parts can be assembled.
- **IPTC:** IPTC-IIM fields in Photoshop APP13 resource blocks.
- **JPEG comments:** `COM` segments.
- **Other application segments:** recognized fields or a summary of unrecognized APP blocks.
- **Technical JPEG data:** JFIF headers, ICC color-profile segments, Adobe APP14, where present.

Readable text is printed in full. Binary data is **summarized**, not dumped in its entirety. If some EXIF references are malformed, the inspector attempts to preserve other readable fields and show parse warnings.

A file can have **no descriptive or generation metadata** while still containing technical headers such as JFIF or ICC. Conversely, a `NONE` scan result does **not** mean the file is metadata-free.

## CSV reports

To save an inventory suitable for Excel or another spreadsheet program:

```cmd
py scan_a1111_jpg_metadata.py . --report results.csv
```

The CSV contains one row per scanned JPEG and these columns:

| Column | Contents |
| --- | --- |
| `file` | JPEG file path |
| `a1111_metadata` | `FULL`, `PARTIAL`, `NONE`, or `ERROR` |
| `location` | EXIF field or comment location involved |
| `details` | Classification explanation or error |

The report uses UTF-8 with BOM (`utf-8-sig`) for spreadsheet compatibility. **The report file is created or overwritten if it already exists.** JPG source files are not modified.

For an inventory without per-file terminal output:

```cmd
py scan_a1111_jpg_metadata.py . --quiet --report results.csv
```

## Command-line reference

| Argument | Purpose |
| --- | --- |
| `[directory]` | Optional directory or single `.jpg`/`.jpeg` file to classify. Defaults to `.` (current directory). |
| `--inspect FILE.jpg` | Inspect one JPG and print its readable metadata rather than running a normal scan. |
| `--recursive` | Include subdirectories during a directory scan. |
| `--report FILE.csv` | Write per-file results to a CSV. |
| `--quiet` | Suppress per-file console results; show summary totals. CSV output is unaffected. |
| `--version` | Show internal script version and exit. |
| `-h`, `--help` | Print help and exit. |

`--inspect` **cannot** be combined with `--recursive`, `--report`, or `--quiet`. `--recursive` matters only when the scan target is a directory.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Completed without reported file-level errors. |
| `1` | Scan completed with at least one `ERROR` file. |
| `2` | Invalid usage, inspection failure, or output I/O error. |

## Limitations and privacy

- **Read-only JPEG access:** No recompression, pixel decoding, timestamp edits, metadata writes, or image conversion.
- **JPG/JPEG only:** PNG metadata is not scanned by this utility.
- **Heuristic classification:** `FULL` / `PARTIAL` identify characteristic field patterns, not proven software origin or guaranteed workflow reproducibility.
- **Incomplete coverage:** Nonstandard metadata formats or A1111 text outside the recognized classification fields can result in `NONE`. `--inspect` offers a wider look at metadata but cannot necessarily decode every proprietary/binary structure.
- **Malformed metadata:** A broken EXIF reference may produce an `ERROR` classification or an inspection warning.
- **Sensitive metadata:** Inspection may reveal prompts, EXIF GPS locations, and other personal details. Review output before sharing it publicly.

### Intended workflow

Use the scanner to inventory your JPEG collection, inspect representative `FULL` and `PARTIAL` examples, then decide separately whether to convert selected JPGs to PNGs. **This script is intentionally not a converter.**
