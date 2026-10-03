"""Central configuration for safe attachment analysis.

Every extension list and limit lives here so the analyzer has no hard-coded
policy. Extensions are lower-case and include the leading dot.
"""

import os

# ---- Extension policy (denylist of risky types; everything else is "other") ---- #
EXECUTABLE_EXTENSIONS = frozenset({".exe", ".dll", ".scr", ".com", ".msi"})
SCRIPT_EXTENSIONS = frozenset({".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse"})
SHORTCUT_EXTENSIONS = frozenset({".lnk"})
RISKY_EXTENSIONS = EXECUTABLE_EXTENSIONS | SCRIPT_EXTENSIONS | SHORTCUT_EXTENSIONS

# Human wording per risky extension (used in findings). Falls back to the category label.
EXTENSION_LABELS = {
    ".exe": "Executable file",
    ".dll": "DLL (dynamic-link library)",
    ".scr": "Screensaver executable",
    ".com": "DOS/Windows command executable",
    ".msi": "Windows installer package",
    ".bat": "Batch script",
    ".cmd": "Command script",
    ".ps1": "PowerShell script",
    ".vbs": "VBScript",
    ".js": "JavaScript file",
    ".jse": "Encoded JScript file",
    ".lnk": "Windows shortcut",
}

# Extensions that make a file *look like* a document (used for double-extension checks).
DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".csv", ".jpg", ".jpeg", ".png"}
)

ARCHIVE_EXTENSIONS = frozenset({".zip", ".rar", ".7z", ".gz", ".tar", ".tgz", ".jar"})

# Words in a file name that suggest an official/financial document.
DOCUMENT_NAME_KEYWORDS = (
    "statement", "invoice", "receipt", "rbi", "bank", "payment", "tax", "notice",
    "kyc", "report", "challan", "settlement", "remittance", "swift", "gst",
)

# Extensions whose *content* we can verify against file signatures: ext -> allowed detected types.
EXPECTED_TYPES = {
    ".pdf": {"pdf"},
    ".zip": {"zip"},
    ".png": {"png"},
    ".jpg": {"jpeg"},
    ".jpeg": {"jpeg"},
    ".gif": {"gif"},
    ".docx": {"office_document"},
    ".xlsx": {"office_document"},
    ".pptx": {"office_document"},
    ".doc": {"ole_document"},
    ".xls": {"ole_document"},
    ".ppt": {"ole_document"},
}
EXECUTABLE_CONTENT_TYPES = frozenset({"pe_executable", "elf_executable"})

# ---- Defensive limits ---------------------------------------------------------- #
MAX_FILENAME_LENGTH = 255        # upload file name and each archive entry name
MAX_ENTRIES_INSPECTED = 1000     # entries listed; the rest are counted but not listed
COMPRESSION_RATIO_WARN = 100     # declared uncompressed / compressed size
TOTAL_UNCOMPRESSED_WARN = 1024**3  # 1 GiB declared


def max_upload_bytes() -> int:
    """Maximum accepted upload size (env TRUSTBREAK_MAX_UPLOAD_BYTES, default 10 MiB)."""
    try:
        value = int(os.environ.get("TRUSTBREAK_MAX_UPLOAD_BYTES", str(10 * 1024**2)))
    except ValueError:
        return 10 * 1024**2
    return value if value > 0 else 10 * 1024**2
