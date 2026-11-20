# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ["C:\\", "D:\\新建文件夹", "E:\\_keys", "ghp_", "github_pat_", "sk-", "身份证", "手机号"]


def test_required_files():
    assert (ROOT / "README.md").exists()
    assert (ROOT / "LICENSE").exists()
    assert (ROOT / "scripts" / "dual_verify.py").exists()
    assert (ROOT / "results" / "s2_report.json").exists()


def test_no_forbidden_paths_or_keys():
    for p in ROOT.rglob("*"):
        if p.name == "test_package_integrity.py":
            continue
        if not p.is_file() or p.suffix.lower() not in {".py", ".md", ".json", ".txt", ".yml", ".yaml"}:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for bad in FORBIDDEN:
            assert bad not in text, f"{bad} in {p}"


def test_result_json_valid():
    for p in (ROOT / "results").glob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))
