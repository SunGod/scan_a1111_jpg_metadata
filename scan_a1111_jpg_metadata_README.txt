A1111 JPG Metadata Scanner
=========================
Version 1.00
Script: scan_a1111_jpg_metadata.py

PURPOSE
-------
A read-only Python utility for finding and inspecting metadata in JPG/JPEG
images, with special attention to AUTOMATIC1111 (A1111) Stable Diffusion
WebUI generation and postprocessing information.

Use it to answer two questions:
  1. Which JPEGs have recognizable A1111-related metadata?
  2. What metadata is actually stored in a particular JPEG?

It does NOT modify images, convert JPGs to PNGs, produce ComfyUI workflows,
or transfer metadata between files. The source JPEGs remain unchanged.

REQUIREMENTS
------------
- Python 3 (recommended: Python 3.8 or newer).
- No third-party packages, Pillow, Node.js, or ComfyUI required.
- Runs on Windows 10/11 and macOS (and other platforms with Python 3).

GETTING STARTED
---------------
Copy scan_a1111_jpg_metadata.py to the folder of JPGs, open Command Prompt,
PowerShell, or Terminal in that folder, then run:

  Windows:   py scan_a1111_jpg_metadata.py .
  macOS:     python3 scan_a1111_jpg_metadata.py .

A dot (.) means the current directory. By default, subdirectories are NOT
searched. File extensions .jpg and .jpeg are matched case-insensitively.
Other file types (including PNG) are ignored during directory scans.

BASIC COMMANDS
--------------
Scan the current directory:
  py scan_a1111_jpg_metadata.py .

Scan a particular folder (quote paths containing spaces):
  py scan_a1111_jpg_metadata.py "C:\\Images\\My JPGs"

Include subfolders:
  py scan_a1111_jpg_metadata.py . --recursive

Save per-file classification results to CSV:
  py scan_a1111_jpg_metadata.py . --report results.csv

Show totals only, but still save all per-file results in the CSV:
  py scan_a1111_jpg_metadata.py . --quiet --report results.csv

Classify one JPEG (short result, not full inspection):
  py scan_a1111_jpg_metadata.py "image001.jpg"

Inspect every readable metadata field in one JPEG:
  py scan_a1111_jpg_metadata.py --inspect "image001.jpg"

Inspect a JPEG by full path:
  py scan_a1111_jpg_metadata.py --inspect "C:\\Images\\image001.jpg"

Show command-line help:
  py scan_a1111_jpg_metadata.py --help

Show script version:
  py scan_a1111_jpg_metadata.py --version

On macOS, replace "py" with "python3" in these examples.

CLASSIFICATION: FULL / PARTIAL / NONE / ERROR
---------------------------------------------
FULL
  A text field contains recognizable A1111-style Steps, Sampler, and Seed
  settings. Example: "Steps: 30, Sampler: Euler a, Seed: 12345".
  This means recognizable generation parameters are present. It does NOT
  guarantee that a complete or reproducible generation workflow exists.

PARTIAL
  The FULL signature is absent, but the scanner recognizes A1111-style
  settings. Examples include:
    "Postprocess upscale by: 4, Postprocess upscaler: 4x-UltraSharp"
    "Hires upscaler: Lanczos"
    "CFG scale: 7"
    "Steps: 30, Sampler: Euler a" (two incomplete generation fields)
  PARTIAL can contain valuable processing history even if the original
  image's generation process cannot be reconstructed.

NONE
  No text matched the scanner's A1111-recognition rules. This does NOT
  mean the file has no metadata. It may have camera, editing, descriptive,
  XMP, or other information. A NONE result is not proof that no A1111
  information exists in any possible format or metadata location.

ERROR
  The JPEG cannot be scanned reliably (for example, a malformed JPEG,
  unreadable file, or an EXIF parsing problem without usable recognized
  content). An ERROR is not the same as NONE.

The patterns indicate A1111-style information, not verified software origin.
FULL and PARTIAL are detection categories, not assessments of whether a
ComfyUI workflow can be reconstructed. FULL requires all three marker fields
in one recognized text field; PARTIAL recognizes characteristic A1111
postprocessing/extension names, distinctive generation fields, or two
commonly used generation fields. False positives and negatives are possible.

WHERE THE SCANNER LOOKS
-----------------------
For FULL / PARTIAL / NONE classification, the directory scanner examines
text within JPEG header metadata, specifically:
  - EXIF UserComment (usual A1111 JPEG generation-info location)
  - EXIF ImageDescription
  - EXIF XPComment
  - JPEG COM/comment segments

It parses header segments without decoding image pixels; classification does
not inspect every conceivable metadata container. Notably, XMP and IPTC
are displayed by --inspect when readable but are NOT evaluated by the
current directory-scan A1111 classification rules.

WHAT --inspect DISPLAYS
-----------------------
The --inspect FILE.jpg option prints the A1111 classification plus readable
metadata encountered in that one JPEG, such as:
  - EXIF tags: UserComment, ImageDescription, Software, dates, orientation,
    GPS, and other standard or unknown tag IDs
  - XMP text/XML, including assembled Extended XMP when complete
  - IPTC-IIM records in Photoshop APP13 resources
  - JPEG COM/comment text
  - Other APP segment information, if present
  - Technical markers such as JFIF headers, ICC profile segments,
    and Adobe APP14 data

Readable text is shown in full. Binary content is identified or summarized
rather than dumped in its entirety. If an EXIF tag or reference is damaged,
--inspect attempts to show other readable tags and may display a warning.

A JPEG with no descriptive/generation metadata can still contain technical
markers such as a JFIF header or an ICC color profile. A message saying no
descriptive metadata was found does not necessarily mean a file has zero
technical metadata.

EXAMPLE DIRECTORY OUTPUT
------------------------
  [FULL   ] image001.jpg (EXIF UserComment)
  [PARTIAL] image002.jpg (EXIF UserComment; A1111-style postprocessing fields: Postprocess upscaler)
  [NONE   ] image003.jpg (No recognizable A1111 metadata)

  Total JPEG files: 3 | A1111 FULL: 1 | PARTIAL: 1 | NONE: 1 | ERRORS: 0

EXAMPLE INSPECTION
------------------
  py scan_a1111_jpg_metadata.py --inspect "image002.jpg"

The output identifies the file, its A1111 classification and reason, and
then enumerates readable metadata fields (including EXIF UserComment text).

CSV REPORT
----------
The --report FILE.csv option writes one row per scanned JPEG, with columns:
  file             Path to the JPEG
  a1111_metadata   FULL, PARTIAL, NONE, or ERROR
  location         Where recognizable or relevant text was found
  details          Reason for the classification / error description

CSV uses UTF-8 with a byte-order mark (UTF-8-SIG) for spreadsheet
compatibility. The CSV file is created or overwritten at the specified
location. The scanner does not write to the JPEG files themselves.

COMMAND-LINE PARAMETERS
-----------------------
[directory]            Optional scan target; current folder (.) by default.
                       May be a directory or an individual .jpg/.jpeg file.
--inspect FILE.jpg     Show detailed metadata for ONE JPEG instead of
                       running the normal classification scan.
--recursive            Include JPEGs in subdirectories in a directory scan.
--report FILE.csv      Write a CSV report with per-file scan results.
--quiet                Suppress per-file terminal output; show totals only.
--version              Print version number and exit.
-h, --help             Print all supported command-line options and exit.

--inspect cannot be combined with --recursive, --report, or --quiet.
--recursive affects directory scans only.

EXIT CODES
----------
0   Scan/inspection completed without reported file-level scan errors.
1   Directory scan completed but one or more JPEGs were classified ERROR.
2   Invalid command-line usage, inspection error, or output I/O error.

LIMITATIONS AND SAFETY
----------------------
- Read-only with respect to JPEGs. No image recompression or pixel decoding.
- Does not scan PNGs, convert formats, or synthesize ComfyUI metadata.
- FULL is a recognizable signature, NOT a guarantee of a usable workflow.
- A1111 recognition is heuristic and may miss unfamiliar/custom formats.
- Malformed EXIF may lead to ERROR or partial inspection warnings.
- When printing --inspect output, the metadata may include prompts,
  descriptive text, and potentially personal EXIF/GPS information.
  Review it before publishing or sharing scan output.

Suggested workflow: scan a JPEG folder, review FULL/PARTIAL counts, inspect
representative files with --inspect, and separately decide whether to
convert those JPGs to PNGs. This scanner does not perform that conversion.
