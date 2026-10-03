"""Safe, static inspection of an untrusted attachment.

SAFETY CONTRACT
  * Input is bytes already in memory. Nothing is written to disk, extracted,
    executed, imported, opened as a URL or passed to a shell.
  * ZIP archives are inspected through their central directory only
    (`ZipFile.infolist()`); entry contents are never read.
  * Output is structural evidence ("suspicious executable content detected"),
    never a malware verdict. It is independent of message analysis, behaviour
    analysis and any risk score.
"""

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import Optional

from . import config

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class AttachmentError(Exception):
    """The attachment cannot be analyzed at all (bad input, not a finding)."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Finding:
    type: str
    severity: str
    message: str
    entry: Optional[str] = None

    def to_dict(self) -> dict:
        data = {"type": self.type, "severity": self.severity, "message": self.message}
        if self.entry is not None:
            data["entry"] = self.entry
        return data


# --------------------------------------------------------------------------- #
# Small pure helpers
# --------------------------------------------------------------------------- #
def _safe_display(name: str) -> str:
    """Make an untrusted name safe to show/serialize: no control chars, bounded length."""
    cleaned = _CONTROL_CHARS.sub("?", name)
    limit = config.MAX_FILENAME_LENGTH
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"


def _basename(name: str) -> str:
    return name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _extensions(basename: str) -> list[str]:
    """All extensions, lower-case. Trailing dots/spaces are ignored (Windows drops them)."""
    parts = basename.strip().rstrip(" .").lower().split(".")
    return ["." + p.strip() for p in parts[1:] if p.strip()] if len(parts) > 1 else []


def _last_extension(basename: str) -> str:
    exts = _extensions(basename)
    return exts[-1] if exts else ""


def _category(ext: str) -> str:
    if ext in config.EXECUTABLE_EXTENSIONS:
        return "executable"
    if ext in config.SCRIPT_EXTENSIONS:
        return "script"
    if ext in config.SHORTCUT_EXTENSIONS:
        return "shortcut"
    if ext in config.ARCHIVE_EXTENSIONS:
        return "archive"
    if ext in config.DOCUMENT_EXTENSIONS:
        return "document"
    return "other"


def _has_double_extension(basename: str) -> bool:
    exts = _extensions(basename)
    return len(exts) >= 2 and exts[-2] in config.DOCUMENT_EXTENSIONS and exts[-1] in config.RISKY_EXTENSIONS


def _looks_like_document(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in config.DOCUMENT_NAME_KEYWORDS)


def _is_path_traversal(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized):
        return True
    return ".." in normalized.split("/") or ".." in posixpath.normpath(normalized).split("/")


def detect_type(data: bytes) -> str:
    """Identify content from leading signature bytes (never trusts the file name)."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if data.startswith(b"MZ"):
        return "pe_executable"
    if data.startswith(b"\x7fELF"):
        return "elf_executable"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole_document"
    if data.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if data.startswith(b"\x1f\x8b"):
        return "gzip"
    return "unknown"


# --------------------------------------------------------------------------- #
# ZIP directory inspection
# --------------------------------------------------------------------------- #
def _inspect_zip(data: bytes, findings: list[Finding], notes: list[str]) -> dict:
    result = {"inspected": False, "entries": [], "file_count": None, "total_uncompressed_bytes": None}
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()  # central directory only; no member is read
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, OSError, ValueError, EOFError):
        findings.append(Finding("invalid_archive", "medium",
                                "The ZIP structure could not be read, so its contents were not inspected."))
        return result

    files = [info for info in infos if not info.is_dir()]
    result["inspected"] = True
    result["file_count"] = len(files)
    if not files:
        notes.append("The archive contains no files.")

    listed = files[: config.MAX_ENTRIES_INSPECTED]
    if len(files) > len(listed):
        findings.append(Finding("too_many_entries", "medium",
                                f"Archive has {len(files)} files; only the first {len(listed)} were inspected."))

    total = compressed_total = 0
    encrypted = nested = False
    entries = []
    for info in listed:
        name = info.filename
        base = _basename(name)
        ext = _last_extension(base)
        category = _category(ext)
        shown = _safe_display(name)
        total += info.file_size
        compressed_total += info.compress_size
        entries.append({"name": shown, "extension": ext, "category": category,
                        "size_bytes": info.file_size, "compressed_bytes": info.compress_size})

        if category in ("executable", "script", "shortcut"):
            label = config.EXTENSION_LABELS.get(ext, category.title())
            findings.append(Finding("executable_inside_archive", "high", f"{label} inside archive.", shown))
        if _has_double_extension(base):
            findings.append(Finding("double_extension", "high",
                                    "Filename uses a document-looking extension followed by an executable extension.", shown))
        if _is_path_traversal(name):
            findings.append(Finding("path_traversal", "high",
                                    "Entry path points outside the archive folder (path traversal indicator).", shown))
        if len(name) > config.MAX_FILENAME_LENGTH:
            findings.append(Finding("long_entry_name", "medium",
                                    f"Entry name is longer than {config.MAX_FILENAME_LENGTH} characters.", shown))
        if category == "archive":
            nested = True
            findings.append(Finding("nested_archive", "medium",
                                    "Archive nested inside the archive; its contents were not inspected.", shown))
        if info.flag_bits & 0x1:
            encrypted = True

    if encrypted:
        findings.append(Finding("encrypted_entries", "medium",
                                "Some entries are password-protected, so they cannot be inspected."))
    if compressed_total > 0 and total / compressed_total > config.COMPRESSION_RATIO_WARN:
        findings.append(Finding("high_compression_ratio", "medium",
                                "Declared uncompressed size is far larger than the archive (possible archive bomb)."))
    elif total > config.TOTAL_UNCOMPRESSED_WARN:
        findings.append(Finding("large_uncompressed_size", "medium",
                                "Declared uncompressed size is very large (possible archive bomb)."))

    result["entries"] = entries
    result["total_uncompressed_bytes"] = total
    return result


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def analyze_attachment(file_name: str, data: bytes, content_type: Optional[str] = None) -> dict:
    """Statically analyze one uploaded file. Raises AttachmentError for unusable input."""
    if not file_name or not file_name.strip():
        raise AttachmentError("invalid_filename", "The uploaded file has no name.")
    if len(file_name) > config.MAX_FILENAME_LENGTH:
        raise AttachmentError("filename_too_long",
                              f"File name is longer than {config.MAX_FILENAME_LENGTH} characters.")
    if len(data) == 0:
        raise AttachmentError("empty_file", "The uploaded file is empty.")
    if len(data) > config.max_upload_bytes():
        raise AttachmentError("file_too_large",
                              f"File exceeds the {config.max_upload_bytes()} byte limit.", status_code=413)

    name = _safe_display(_basename(file_name))
    ext = _last_extension(name)
    detected = detect_type(data)
    is_archive = detected in ("zip", "rar", "7z", "gzip")
    findings: list[Finding] = []
    notes: list[str] = []
    zip_info = {"inspected": False, "entries": [], "file_count": None, "total_uncompressed_bytes": None}

    # OOXML documents (.docx/.xlsx/.pptx) are ZIP containers by design: treat as documents, not archives.
    file_type = detected
    if detected == "zip" and ext in (".docx", ".xlsx", ".pptx"):
        file_type, is_archive = "office_document", False

    if is_archive and detected == "zip":
        zip_info = _inspect_zip(data, findings, notes)
    elif is_archive:
        findings.append(Finding("archive_not_inspected", "low",
                                f"{detected.upper()} archives are not opened; contents were not inspected."))
    elif detected == "unknown":
        notes.append("File type is not recognized; only name and size were evaluated.")

    # Name vs content
    if detected in config.EXECUTABLE_CONTENT_TYPES:
        findings.append(Finding("executable_file", "high",
                                "The file content is an executable program."))
    expected = config.EXPECTED_TYPES.get(ext)
    if expected is not None and file_type not in expected:
        if detected in config.EXECUTABLE_CONTENT_TYPES:
            findings.append(Finding("content_type_mismatch", "high",
                                    f"File is named {ext} but its content looks like an executable."))
        else:
            findings.append(Finding("content_type_mismatch", "medium",
                                    f"File is named {ext} but its content looks like {file_type}."))
    if ext in config.RISKY_EXTENSIONS and detected not in config.EXECUTABLE_CONTENT_TYPES:
        findings.append(Finding("risky_extension", "high",
                                f"{config.EXTENSION_LABELS.get(ext, 'Risky')} file type."))
    if _has_double_extension(name):
        findings.append(Finding("double_extension", "high",
                                "Filename uses a document-looking extension followed by an executable extension."))

    entries = zip_info["entries"]
    exec_entries = [e for e in entries if e["category"] in ("executable", "script", "shortcut")]
    contains_executable = bool(exec_entries) or detected in config.EXECUTABLE_CONTENT_TYPES or ext in config.RISKY_EXTENSIONS
    if exec_entries and _looks_like_document(name):
        findings.append(Finding("document_with_executable_content", "medium",
                                "File name suggests a document or statement, but the archive contains executable content. "
                                "Suspicious executable content detected."))

    findings.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.type, f.entry or ""))
    suspicious = any(f.severity in ("high", "medium") for f in findings)

    return {
        "file_name": name,
        "extension": ext,
        "file_type": file_type,
        "content_type": content_type,
        "size_bytes": len(data),
        "archive": is_archive,
        "inspected": zip_info["inspected"] if is_archive else True,
        "file_count": zip_info["file_count"],
        "total_uncompressed_bytes": zip_info["total_uncompressed_bytes"],
        "entries": entries,
        "extensions": sorted({e["extension"] for e in entries if e["extension"]}),
        "executable_files": [e["name"] for e in exec_entries],
        "contains_executable": contains_executable,
        "suspicious": suspicious,
        "findings": [f.to_dict() for f in findings],
        "notes": notes + ["Structural analysis only - this does not prove that the file is malware."],
        "is_final_decision": False,
    }
