#!/usr/bin/env python3
"""
License Scanner – generates license data for the Help page.

Scans:
  1. npm production dependencies (via npx license-checker)
  2. Python dependencies (via pip-licenses or pip list + importlib.metadata)

Outputs a JavaScript file that can be imported by HelpView.jsx.

Usage:
    python tools/scan_licenses.py

The output is written to:
    elab_workbench/src/plugins/Help/licenseData.generated.js
"""

import json
import subprocess
import sys
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Subprocess errors that may occur when invoking pip-licenses, npx, etc.
_SUBPROCESS_ERRORS = (
    OSError,                       # missing executable / permission denied
    subprocess.SubprocessError,    # incl. TimeoutExpired, CalledProcessError
    json.JSONDecodeError,          # malformed tool output
    UnicodeDecodeError,
)

_UNKNOWN_LICENSE_VALUES = {
    "",
    "unknown",
    "none",
    "n/a",
    "=========================",
}

IS_WIN = sys.platform == "win32"
NPX = "npx.cmd" if IS_WIN else "npx"

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "elab_workbench"
OUTPUT = WEB_DIR / "src" / "plugins" / "Help" / "licenseData.generated.js"
VENV_PIP = ROOT / ".venv" / ("Scripts" if IS_WIN else "bin") / ("pip.exe" if IS_WIN else "pip")


def _resolve_pip_command():
    """Return a pip command that works in local dev and CI environments."""
    if VENV_PIP.exists():
        return [str(VENV_PIP)]
    return [sys.executable, "-m", "pip"]


def _normalize_repo_url(url):
    """Normalize repository URLs to a browser-friendly HTTPS form."""
    if not url:
        return ""

    cleaned = str(url).strip()
    if cleaned.startswith("git+"):
        cleaned = cleaned[4:]
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if cleaned.startswith("git://"):
        cleaned = "https://" + cleaned[len("git://") :]

    parts = urlsplit(cleaned)
    if not parts.scheme:
        return cleaned

    if parts.netloc.lower() == "github.com":
        path = parts.path.rstrip("/")
        return urlunsplit(("https", parts.netloc, path, parts.query, parts.fragment))
    return cleaned.rstrip("/")


def _build_github_license_tab(repo_url, license_name):
    """Return a GitHub tab URL that opens the detected license view when possible."""
    normalized = _normalize_repo_url(repo_url)
    if not normalized:
        return ""

    parts = urlsplit(normalized)
    if parts.netloc.lower() != "github.com":
        return normalized
    if "/blob/" in parts.path or "/tree/" in parts.path:
        return normalized
    if parts.query and "tab=" in parts.query:
        return normalized

    slug = _license_to_tab_slug(license_name)
    if slug:
        return f"{normalized}?tab={slug}-1-ov-file"

    return f"{normalized}?tab=License-1-ov-file"


def _is_unknown_license(value):
    return (value or "").strip().lower() in _UNKNOWN_LICENSE_VALUES


def _is_generic_license(value):
    """Return True when a license string is too generic for precise tab selection."""
    normalized = (value or "").strip().upper()
    return normalized in {"BSD", "GPL", "LGPL", "AGPL"}


def _license_to_tab_slug(license_name):
    """Convert free-form license text to a stable GitHub tab slug where possible."""
    raw = (license_name or "").strip()
    if _is_unknown_license(raw):
        return ""

    up = raw.upper()
    if "MIT" in up:
        return "MIT"
    if "BSD" in up and "3" in up and "CLAUSE" in up:
        return "BSD-3-Clause"
    if "BSD" in up and "2" in up and "CLAUSE" in up:
        return "BSD-2-Clause"
    if "APACHE" in up and "2" in up:
        return "Apache-2.0"
    if "MPL" in up and "2" in up:
        return "MPL-2.0"
    if "LGPL" in up and "3" in up:
        return "LGPL-3.0"

    primary = re.split(r"\s+(?:or|and)\s+|/|,|;", raw, maxsplit=1, flags=re.IGNORECASE)[0]
    return re.sub(r"[^A-Za-z0-9.-]+", "-", primary).strip("-")


def _github_owner_repo(repo_url):
    normalized = _normalize_repo_url(repo_url)
    parts = urlsplit(normalized)
    if parts.netloc.lower() != "github.com":
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        return None
    return segments[0], segments[1]


def _fetch_github_spdx(repo_url, cache):
    """Fetch SPDX identifier from GitHub API for a repository URL."""
    owner_repo = _github_owner_repo(repo_url)
    if not owner_repo:
        return ""
    if owner_repo in cache:
        return cache[owner_repo]

    owner, repo = owner_repo
    api_url = f"https://api.github.com/repos/{owner}/{repo}/license"
    request = Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "E-Lab-License-Scanner",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            spdx_id = payload.get("license", {}).get("spdx_id", "")
            if isinstance(spdx_id, str) and spdx_id and spdx_id not in ("NOASSERTION", "UNKNOWN"):
                cache[owner_repo] = spdx_id
                return spdx_id
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        pass

    cache[owner_repo] = ""
    return ""


def _detect_license_from_text(text):
    """Extract a likely SPDX-like license from arbitrary license page text."""
    if not text:
        return ""

    # Prefer explicit SPDX references when present.
    spdx_match = re.search(r"SPDX\s*[-:]?\s*([A-Za-z0-9.+-]+)", text, re.IGNORECASE)
    if spdx_match:
        spdx = spdx_match.group(1).strip(" .,)\"]'")
        if spdx and spdx.upper() not in {"UNKNOWN", "NOASSERTION"}:
            return spdx

    upper = text.upper()
    if "MIT LICENSE" in upper or "PERMISSION IS HEREBY GRANTED, FREE OF CHARGE" in upper:
        return "MIT"
    if "APACHE LICENSE" in upper and "VERSION 2" in upper:
        return "Apache-2.0"
    if "BSD 3-CLAUSE" in upper or "BSD-3-CLAUSE" in upper:
        return "BSD-3-Clause"
    if "BSD 2-CLAUSE" in upper or "BSD-2-CLAUSE" in upper:
        return "BSD-2-Clause"
    if "GNU GENERAL PUBLIC LICENSE" in upper and "VERSION 3" in upper:
        if "OR ANY LATER VERSION" in upper or "OR LATER" in upper:
            return "GPL-3.0-or-later"
        return "GPL-3.0"
    if "GNU GENERAL PUBLIC LICENSE" in upper and "VERSION 2" in upper:
        if "OR ANY LATER VERSION" in upper or "OR LATER" in upper:
            return "GPL-2.0-or-later"
        return "GPL-2.0"
    if "LESSER GENERAL PUBLIC LICENSE" in upper and "VERSION 3" in upper:
        return "LGPL-3.0"
    if "MOZILLA PUBLIC LICENSE" in upper and "2.0" in upper:
        return "MPL-2.0"

    return ""


def _fetch_license_from_github_tab(repo_url, cache):
    """Read GitHub license tab content and infer a license identifier via regex."""
    owner_repo = _github_owner_repo(repo_url)
    if not owner_repo:
        return ""
    cache_key = (owner_repo[0], owner_repo[1], "tab")
    if cache_key in cache:
        return cache[cache_key]

    normalized = _normalize_repo_url(repo_url)
    owner, repo = owner_repo
    candidates = [
        f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/LICENSE",
        f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/LICENSE.txt",
        f"https://raw.githubusercontent.com/{owner}/{repo}/main/LICENSE",
        f"https://raw.githubusercontent.com/{owner}/{repo}/main/LICENSE.txt",
        f"https://raw.githubusercontent.com/{owner}/{repo}/master/LICENSE",
        f"https://raw.githubusercontent.com/{owner}/{repo}/master/LICENSE.txt",
        f"{normalized}?tab=License-1-ov-file",
        f"{normalized}/blob/main/LICENSE",
        f"{normalized}/blob/master/LICENSE",
    ]

    detected = ""
    for url in candidates:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "E-Lab-License-Scanner",
            },
        )
        try:
            with urlopen(request, timeout=6) as response:
                html_text = response.read().decode("utf-8", errors="replace")
                detected = _detect_license_from_text(html_text)
                if detected:
                    break
        except (URLError, HTTPError, TimeoutError):
            continue

    cache[cache_key] = detected
    return detected


def _read_license_from_pip_show(name, pip_cmd):
    """Read richer license metadata from pip show -v for one package."""
    try:
        show = subprocess.run(
            [*pip_cmd, "show", "-v", name],
            capture_output=True, text=True, timeout=12,
            check=False,
        )
    except _SUBPROCESS_ERRORS:
        return ""

    if show.returncode != 0:
        return ""

    direct_license = ""
    classifiers = []
    for line in show.stdout.splitlines():
        if line.startswith("License-Expression:"):
            value = line.split(":", 1)[1].strip()
            if value and not _is_unknown_license(value):
                return value
        elif line.startswith("License:"):
            direct_license = line.split(":", 1)[1].strip()
        elif "License ::" in line:
            classifiers.append(line.strip())

    if direct_license and not _is_unknown_license(direct_license):
        return direct_license

    for classifier in classifiers:
        if "MIT" in classifier:
            return "MIT"
        if "BSD" in classifier and "3" in classifier:
            return "BSD-3-Clause"
        if "BSD" in classifier:
            return "BSD"
        if "Apache" in classifier and "2" in classifier:
            return "Apache-2.0"
        if "MPL" in classifier and "2" in classifier:
            return "MPL-2.0"

    return ""


def _enrich_python_dependency(dep, pip_cmd, github_cache):
    """Improve repo + license quality for one Python dependency entry."""
    dep["repo"] = _normalize_repo_url(dep.get("repo", ""))
    current_license = dep.get("license", "Unknown")

    if _is_unknown_license(current_license):
        detected = _read_license_from_pip_show(dep.get("name", ""), pip_cmd)
        if detected:
            current_license = detected

    if _is_unknown_license(current_license):
        spdx = _fetch_github_spdx(dep.get("repo", ""), github_cache)
        if spdx:
            current_license = spdx
        else:
            detected = _fetch_license_from_github_tab(dep.get("repo", ""), github_cache)
            if detected:
                current_license = detected
    elif _is_generic_license(current_license):
        spdx = _fetch_github_spdx(dep.get("repo", ""), github_cache)
        if spdx:
            current_license = spdx
        else:
            detected = _fetch_license_from_github_tab(dep.get("repo", ""), github_cache)
            if detected:
                current_license = detected

    dep["license"] = current_license or "Unknown"
    dep["repo"] = _build_github_license_tab(dep.get("repo", ""), dep["license"])


def scan_npm():
    """Scan npm production deps via license-checker."""
    print("[npm] Scanning production dependencies …")
    try:
        result = subprocess.run(
            [NPX, "--yes", "license-checker", "--json", "--production"],
            capture_output=True, text=True, cwd=str(WEB_DIR), timeout=60,
            check=False,
        )
        if result.returncode != 0:
            print(f"[npm] license-checker failed: {result.stderr[:200]}")
            return []
        data = json.loads(result.stdout)
    except _SUBPROCESS_ERRORS as e:
        print(f"[npm] Error: {e}")
        return []

    deps = []
    for pkg_key, info in sorted(data.items()):
        name_version = pkg_key.rsplit("@", 1)
        name = name_version[0] if len(name_version) == 2 else pkg_key
        version = name_version[1] if len(name_version) == 2 else ""
        # Skip the project itself
        if name in ("elab_workbench", "elab-workbench", "e_lab"):
            continue
        repo = info.get("repository", "")
        if isinstance(repo, dict):
            repo = repo.get("url", "")
        repo = _normalize_repo_url(repo)
        deps.append({
            "name": name,
            "version": version,
            "license": info.get("licenses", "Unknown"),
            "repo": repo,
        })
    print(f"[npm] Found {len(deps)} packages")
    return deps


def scan_python():
    """Scan Python deps from the venv."""
    print("[python] Scanning Python dependencies …")
    deps = []
    pip_cmd = _resolve_pip_command()

    # Try pip-licenses first
    # Resolve pip-licenses executable next to pip in the venv when available,
    # otherwise use module invocation for CI/global Python installs.
    pip_licenses_cmd = None
    if VENV_PIP.exists():
        if IS_WIN:
            pip_licenses_exe = VENV_PIP.parent / "pip-licenses.exe"
        else:
            pip_licenses_exe = VENV_PIP.parent / "pip-licenses"
        if pip_licenses_exe.exists():
            pip_licenses_cmd = [str(pip_licenses_exe), "--format=json", "--with-urls"]

    if pip_licenses_cmd is None:
        pip_licenses_cmd = [sys.executable, "-m", "piplicenses", "--format=json", "--with-urls"]

    github_cache = {}

    try:
        result = subprocess.run(
            pip_licenses_cmd,
            capture_output=True, text=True, timeout=30,
            check=False,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for pkg in data:
                dep = {
                    "name": pkg.get("Name", ""),
                    "version": pkg.get("Version", ""),
                    "license": pkg.get("License", "Unknown"),
                    "repo": pkg.get("URL", ""),
                }
                _enrich_python_dependency(dep, pip_cmd, github_cache)
                deps.append(dep)
            print(f"[python] Found {len(deps)} packages via pip-licenses")
            return deps
    except _SUBPROCESS_ERRORS:
        pass

    # Fallback: pip list + importlib.metadata
    try:
        result = subprocess.run(
            [*pip_cmd, "list", "--format=json"],
            capture_output=True, text=True, timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return []
        pkgs = json.loads(result.stdout)

        # Try to get license info via pip show
        for pkg in pkgs:
            name = pkg["name"]
            version = pkg["version"]
            # Skip pip, setuptools, etc.
            if name.lower() in ("pip", "setuptools", "wheel", "pkg_resources"):
                continue
            license_str = ""
            home_url = ""
            try:
                show = subprocess.run(
                    [*pip_cmd, "show", name],
                    capture_output=True, text=True, timeout=10,
                    check=False,
                )
                for line in show.stdout.splitlines():
                    if line.startswith("License:"):
                        license_str = line.split(":", 1)[1].strip()
                    elif line.startswith("Home-page:"):
                        home_url = line.split(":", 1)[1].strip()
            except _SUBPROCESS_ERRORS:
                pass
            dep = {
                "name": name,
                "version": version,
                "license": license_str or "Unknown",
                "repo": home_url,
            }
            _enrich_python_dependency(dep, pip_cmd, github_cache)
            deps.append(dep)
        print(f"[python] Found {len(deps)} packages via pip list")
    except _SUBPROCESS_ERRORS as e:
        print(f"[python] Error: {e}")

    return deps


def write_output(npm_deps, python_deps):
    """Write JS module with license data."""
    js = "// Auto-generated by scripts/scan_licenses.py – do not edit manually\n\n"
    js += f"export const FRONTEND_DEPS = {json.dumps(npm_deps, indent=2)};\n\n"
    js += f"export const BACKEND_DEPS = {json.dumps(python_deps, indent=2)};\n"

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(js, encoding="utf-8")
    print(f"\n[ok] Written to {OUTPUT.relative_to(ROOT)}")


def main():
    """Main entry point."""
    npm_deps = scan_npm()
    python_deps = scan_python()

    # Add embedded drivers/third-party licenses
    python_deps.append({
        "name": "Owon XDM1041 Driver",
        "version": "embedded",
        "license": "Unknown (Default Copyright)",
        "repo": "https://github.com/ElDuderino/XDM1041Python",
    })

    write_output(npm_deps, python_deps)
    print(f"\nTotal: {len(npm_deps)} npm + {len(python_deps)} Python packages")


if __name__ == "__main__":
    main()
