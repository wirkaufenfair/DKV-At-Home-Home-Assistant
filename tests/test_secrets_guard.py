"""Guard: no tokens, account numbers or personal data in the repository.

The repository is public and this project handles logins. The tests scan
every versioned file. Tests build their tokens at run time, so no real or
fake token may be written down literally.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Built from parts so this file does not match itself.
FORBIDDEN_LITERALS = [
    "10000" + "0451057",  # the DKV account number of the maintainer
    "axians" + "-infoma",  # employer address
    "andre" + ".cords",
]

# A JWT: three base64url parts, the first starts with {"
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")
# A bearer token or refresh token value written into a file
TOKEN_VALUE = re.compile(
    r"""(refresh_token|access_token|Authorization)["']?\s*[:=]\s*["'](?!x["'])"""
    r"""[A-Za-z0-9._-]{30,}["']"""
)
# Windows user directories and the like
PRIVATE_PATH = re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+", re.IGNORECASE)

THIS_FILE = Path(__file__).name


def tracked_files():
    names = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode().split("\0")
    for name in filter(None, names):
        path = ROOT / name
        if path.name == THIS_FILE or path.suffix in {".png", ".jpg", ".ico"}:
            continue
        try:
            yield name, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue


FILES = list(tracked_files())


def test_there_are_files_to_scan():
    assert len(FILES) > 20


@pytest.mark.parametrize("literal", FORBIDDEN_LITERALS)
def test_no_personal_literal_in_any_file(literal):
    found = [name for name, text in FILES if literal in text]
    assert not found, f"{literal[:6]}… found in {found}"


def test_no_jwt_in_any_file():
    found = [name for name, text in FILES if JWT.search(text)]
    assert not found, f"token-like strings in {found}"


def test_no_token_value_in_any_file():
    found = [name for name, text in FILES if TOKEN_VALUE.search(text)]
    assert not found, f"token values in {found}"


def test_no_private_path_in_any_file():
    found = [name for name, text in FILES if PRIVATE_PATH.search(text)]
    assert not found, f"private paths in {found}"


def test_the_guard_recognizes_what_it_looks_for():
    """Control: the patterns must match real examples."""
    sample_jwt = "eyJhbGciOiJub25lIn0.eyJleHAiOjF9.c2lnbmF0dXJl"
    assert JWT.search(sample_jwt)
    assert TOKEN_VALUE.search('"refresh_token": "' + "a" * 40 + '"')
    assert PRIVATE_PATH.search("C:\\Users\\someone\\file")
