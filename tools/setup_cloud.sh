#!/bin/sh
# Pinned Linux x86_64 Platform Tools, kept outside the application checkout.
set -eu
cd /workspace/LumiaFaceID
python3 - <<'PY'
import hashlib
import os
from pathlib import Path
import urllib.request
import zipfile

if os.uname().machine != 'x86_64':
    raise SystemExit('This setup pins the Linux x86_64 Platform Tools package')
root = Path('/workspace/.lumiafaceid')
root.mkdir(exist_ok=True)
archive = root / 'platform-tools_r37.0.1-linux.zip'
expected = 'd230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1'
# Google's repository2-1.xml published size 9054187 and SHA-1
# 477254aa5f903c15cf51001717bdf347fb6b53e0. SHA-256 was pinned after
# validating that official metadata on 2026-11-02. TLS stays enabled.
if not archive.exists():
    with urllib.request.urlopen(
        'https://dl.google.com/android/repository/platform-tools_r37.0.1-linux.zip',
        timeout=60,
    ) as response:
        data = response.read(9054188)
    if len(data) != 9054187 or hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit('Platform Tools download failed checksum/size verification')
    with archive.open('xb') as output:
        output.write(data)
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit('Cached Platform Tools checksum mismatch; refusing installation')
sdk = root / 'sdk'
with zipfile.ZipFile(archive) as package:
    # Validate every path and existing file before adding anything.
    for member in package.infolist():
        target = sdk / member.filename
        if not target.resolve().is_relative_to(sdk.resolve()):
            raise SystemExit('Invalid archive path')
        if target.exists() and not member.is_dir():
            if not target.is_file() or target.read_bytes() != package.read(member):
                raise SystemExit(f'Refusing to overwrite different existing file: {target}')
    for member in package.infolist():
        target = sdk / member.filename
        if not target.exists():
            package.extract(member, sdk)
        mode = (member.external_attr >> 16) & 0o777
        if mode:
            target.chmod(mode)
PY
# ADB requires the real user configuration directory even for `adb version`.
# Cloud filesystem approval may be required when the directory is absent.
mkdir -p "$HOME/.android"
/workspace/.lumiafaceid/sdk/platform-tools/adb version
/workspace/.lumiafaceid/sdk/platform-tools/fastboot --version
command -v cc >/dev/null || { echo 'A host C compiler is required for the kernel sequence tests' >&2; exit 1; }
python3 -m unittest discover -s tests -v
