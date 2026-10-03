"""Unit tests for safe attachment analysis. Synthetic, inert files only (stdlib unittest).

Run from backend/:  python -m unittest discover -s tests -t . -v
"""

import builtins
import io
import os
import subprocess
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from app.services.attachment_analysis import AttachmentError, analyze_attachment, config

INERT = b"synthetic placeholder text - not a real program\n" * 4
PDF = b"%PDF-1.4\n% synthetic test pdf\n%%EOF\n"


def make_zip(entries, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as archive:
        for name in entries:
            archive.writestr(name, INERT)
    return buf.getvalue()


def types(result):
    return [f["type"] for f in result["findings"]]


class AttachmentAnalysisTests(unittest.TestCase):
    # 1
    def test_normal_pdf(self):
        r = analyze_attachment("Report.pdf", PDF, "application/pdf")
        self.assertEqual(r["file_type"], "pdf")
        self.assertFalse(r["archive"] or r["contains_executable"] or r["suspicious"])
        self.assertEqual(r["findings"], [])

    # 2
    def test_normal_zip_with_pdfs(self):
        r = analyze_attachment("Invoices.zip", make_zip(["a.pdf", "docs/b.pdf"]))
        self.assertTrue(r["archive"])
        self.assertEqual(r["file_count"], 2)
        self.assertEqual(r["extensions"], [".pdf"])
        self.assertFalse(r["contains_executable"] or r["suspicious"])
        self.assertEqual(r["findings"], [])

    # 3
    def test_zip_with_exe(self):
        r = analyze_attachment("files.zip", make_zip(["Update.exe", "Readme.txt"]))
        self.assertTrue(r["contains_executable"] and r["suspicious"])
        self.assertEqual(r["executable_files"], ["Update.exe"])
        finding = next(f for f in r["findings"] if f["type"] == "executable_inside_archive")
        self.assertEqual((finding["severity"], finding["entry"]), ("high", "Update.exe"))

    # 4
    def test_zip_with_dll(self):
        r = analyze_attachment("files.zip", make_zip(["helper.dll"]))
        self.assertTrue(r["contains_executable"])
        self.assertIn("DLL", r["findings"][0]["message"])

    # 5 + core scenario
    def test_rbi_statement_scenario(self):
        r = analyze_attachment("RBI_Statement.zip", make_zip(["Statement.pdf", "Update.exe", "helper.dll"]), "application/zip")
        self.assertEqual((r["file_type"], r["archive"], r["file_count"]), ("zip", True, 3))
        self.assertTrue(r["contains_executable"] and r["suspicious"])
        self.assertEqual(r["executable_files"], ["Update.exe", "helper.dll"])
        self.assertEqual(r["extensions"], [".dll", ".exe", ".pdf"])
        self.assertEqual(types(r).count("executable_inside_archive"), 2)
        self.assertIn("document_with_executable_content", types(r))
        self.assertFalse(r["is_final_decision"])
        text = " ".join(f["message"] for f in r["findings"]) + " ".join(r["notes"])
        self.assertIn("Suspicious executable content detected", text)
        self.assertNotIn("definitely malware", text.lower())
        self.assertIn("does not prove", text)

    # 6
    def test_double_extension_filename(self):
        for name in ("Statement.pdf.exe", "Invoice.pdf.scr", "RBI_Statement.pdf.lnk", "STATEMENT.PDF.EXE", "a.pdf.exe. "):
            r = analyze_attachment(name, b"unrecognized bytes")
            self.assertIn("double_extension", types(r), name)
            self.assertTrue(r["suspicious"])

    def test_double_extension_inside_archive_and_no_false_positive(self):
        r = analyze_attachment("x.zip", make_zip(["Invoice.pdf.scr"]))
        self.assertIn("double_extension", types(r))
        r = analyze_attachment("x.zip", make_zip(["backup.tar.zip.txt", "v1.2.pdf"]))
        self.assertNotIn("double_extension", types(r))

    # 7
    def test_suspicious_archive_filename_only_matters_with_executable(self):
        with_exe = analyze_attachment("Bank_Notice.zip", make_zip(["x.exe"]))
        self.assertIn("document_with_executable_content", types(with_exe))
        plain = analyze_attachment("Bank_Notice.zip", make_zip(["x.pdf"]))
        self.assertNotIn("document_with_executable_content", types(plain))
        neutral = analyze_attachment("photos.zip", make_zip(["x.exe"]))
        self.assertNotIn("document_with_executable_content", types(neutral))

    # 8
    def test_empty_zip(self):
        r = analyze_attachment("empty.zip", make_zip([]))
        self.assertEqual((r["archive"], r["file_count"], r["inspected"]), (True, 0, True))
        self.assertFalse(r["suspicious"])
        self.assertIn("The archive contains no files.", r["notes"])

    # 9
    def test_invalid_or_corrupted_zip(self):
        good = make_zip(["a.pdf", "b.exe"])
        for blob in (b"PK\x03\x04" + b"garbage" * 10, good[: len(good) // 2], b"PK\x05\x06" + b"\x00" * 5):
            r = analyze_attachment("broken.zip", blob)
            self.assertFalse(r["inspected"])
            self.assertIn("invalid_archive", types(r))
            self.assertTrue(r["suspicious"])
            self.assertIsNone(r["file_count"])

    # 10 (missing attachment at service level; the API case is in the API tests)
    def test_missing_or_empty_input(self):
        with self.assertRaises(AttachmentError) as ctx:
            analyze_attachment("empty.bin", b"")
        self.assertEqual(ctx.exception.code, "empty_file")
        with self.assertRaises(AttachmentError) as ctx:
            analyze_attachment("", b"abc")
        self.assertEqual(ctx.exception.code, "invalid_filename")

    # 11
    def test_unsupported_file_type(self):
        r = analyze_attachment("notes.xyz", b"just some text")
        self.assertEqual(r["file_type"], "unknown")
        self.assertFalse(r["suspicious"])
        self.assertTrue(any("not recognized" in n for n in r["notes"]))
        r = analyze_attachment("pack.rar", b"Rar!\x1a\x07\x00" + b"\x00" * 10)
        self.assertEqual((r["file_type"], r["archive"], r["inspected"]), ("rar", True, False))
        self.assertIn("archive_not_inspected", types(r))

    # 12
    def test_large_filename_and_path_edge_cases(self):
        with self.assertRaises(AttachmentError) as ctx:
            analyze_attachment("a" * 300 + ".pdf", PDF)
        self.assertEqual(ctx.exception.code, "filename_too_long")
        long_entry = "d/" * 150 + "x.pdf"
        r = analyze_attachment("ok.zip", make_zip([long_entry]))
        self.assertIn("long_entry_name", types(r))
        self.assertLessEqual(len(r["entries"][0]["name"]), config.MAX_FILENAME_LENGTH + 1)
        too_big = b"%PDF-" + b"0" * (config.max_upload_bytes() + 1)
        with self.assertRaises(AttachmentError) as ctx:
            analyze_attachment("big.pdf", too_big)
        self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("file_too_large", 413))

    def test_entry_limit(self):
        names = [f"f{i}.txt" for i in range(config.MAX_ENTRIES_INSPECTED + 5)]
        r = analyze_attachment("many.zip", make_zip(names))
        self.assertEqual(r["file_count"], len(names))
        self.assertEqual(len(r["entries"]), config.MAX_ENTRIES_INSPECTED)
        self.assertIn("too_many_entries", types(r))

    # 13
    def test_path_traversal_entries(self):
        for bad in ("../../evil.txt", "..\\..\\evil.txt", "/etc/cron.d/x", "C:\\Windows\\x.txt", "a/../../b.txt"):
            r = analyze_attachment("t.zip", make_zip([bad]))
            self.assertIn("path_traversal", types(r), bad)
        r = analyze_attachment("t.zip", make_zip(["safe/dir/file.txt", "v1..2/x.txt"]))
        self.assertNotIn("path_traversal", types(r))

    # optional checks
    def test_nested_archive_encrypted_and_bomb(self):
        r = analyze_attachment("n.zip", make_zip(["inner.zip"]))
        self.assertIn("nested_archive", types(r))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("zeros.bin", b"\x00" * 5_000_000)  # compresses ~1000:1; only 5 MB in memory
        r = analyze_attachment("bomb.zip", buf.getvalue())
        self.assertIn("high_compression_ratio", types(r))
        enc = bytearray(make_zip(["secret.pdf"]))
        for marker in (b"PK\x03\x04", b"PK\x01\x02"):  # set the 'encrypted' flag bit in local + central headers
            pos = enc.find(marker)
            flag_at = pos + (6 if marker == b"PK\x03\x04" else 8)
            enc[flag_at] |= 0x1
        self.assertIn("encrypted_entries", types(analyze_attachment("e.zip", bytes(enc))))

    def test_content_does_not_match_name(self):
        r = analyze_attachment("Statement.pdf", b"MZ" + b"\x00" * 30)  # inert 'MZ' header stub, not a program
        self.assertEqual(r["file_type"], "pe_executable")
        self.assertIn("content_type_mismatch", types(r))
        self.assertTrue(r["contains_executable"] and r["suspicious"])
        r = analyze_attachment("Statement.pdf", make_zip(["a.txt"]))
        self.assertEqual(next(f for f in r["findings"] if f["type"] == "content_type_mismatch")["severity"], "medium")

    def test_docx_is_a_document_not_an_archive(self):
        r = analyze_attachment("Letter.docx", make_zip(["[Content_Types].xml", "word/document.xml"]))
        self.assertEqual((r["file_type"], r["archive"]), ("office_document", False))
        self.assertFalse(r["suspicious"])

    def test_findings_are_deterministic_and_sorted(self):
        blob = make_zip(["Statement.pdf", "Update.exe", "helper.dll", "../x.txt"])
        first = analyze_attachment("RBI_Statement.zip", blob)
        self.assertEqual(first, analyze_attachment("RBI_Statement.zip", blob))
        order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        severities = [order[f["severity"]] for f in first["findings"]]
        self.assertEqual(severities, sorted(severities))

    def test_control_characters_in_names_are_neutralised(self):
        r = analyze_attachment("t.zip", make_zip(["bad\x07name\x1b[31m.txt"]))
        self.assertNotRegex(r["entries"][0]["name"], r"[\x00-\x1f\x7f]")


class NoExecutionTests(unittest.TestCase):
    """The analyzer must never run, extract, read members, write files or spawn processes."""

    def test_analysis_touches_no_process_file_or_member_apis(self):
        blob = make_zip(["Statement.pdf", "Update.exe", "helper.dll", "run.bat", "../x.txt"])

        def boom(*_a, **_k):
            raise AssertionError("forbidden call during attachment analysis")

        with mock.patch.object(subprocess, "Popen", boom), mock.patch.object(os, "system", boom), \
             mock.patch.object(os, "startfile", boom, create=True), mock.patch.object(builtins, "open", boom), \
             mock.patch.object(zipfile.ZipFile, "extract", boom), mock.patch.object(zipfile.ZipFile, "extractall", boom), \
             mock.patch.object(zipfile.ZipFile, "read", boom), mock.patch.object(zipfile.ZipFile, "open", boom):
            result = analyze_attachment("RBI_Statement.zip", blob)
        self.assertTrue(result["contains_executable"])

    def test_source_does_not_import_execution_modules(self):
        src_dir = Path(__file__).resolve().parents[1] / "app" / "services" / "attachment_analysis"
        forbidden = ("subprocess", "os.system", "ctypes", "importlib", "tempfile", "shutil", "socket", "urllib", "requests", "eval(", "exec(")
        for path in src_dir.glob("*.py"):
            text = path.read_text()
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name} mentions {token}")
            if path.name != "config.py":  # config only reads one env var for the upload limit
                self.assertNotIn("import os", text)


if __name__ == "__main__":
    unittest.main()
