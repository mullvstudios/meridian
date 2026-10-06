#!/usr/bin/env python3
"""Verify, build and publish a Meridian release. Stdlib only.

  python3 release.py pv2o2b.mrpack                       # verify + build dist/Meridian-<version>.mrpack
  MODRINTH_TOKEN=... MODRINTH_PROJECT=<id|slug> \\
  python3 release.py pv2o2b.mrpack --publish

Versions are calendar based: YYYY.MM for the monthly release, YYYY.MM.1, .2 ... for hotfixes in the
same month. Omit the version and it is derived from today's date and meta.json.

--publish uploads the build to Modrinth, then appends the version to meta.json
(read in game by Modpack Update Checker). Commit and push meta.json + versions/ afterwards.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = "https://api.modrinth.com/v2"
UA = "mullvstudios/meridian release.py"
NAME = "Meridian"
PROJECT_URL = "https://modrinth.com/modpack/meridian"
# Hosts Modrinth accepts in modrinth.index.json downloads.
ALLOWED_HOSTS = {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
SKIP = "/.connector/"  # Sinytra Connector cache: regenerated on launch, not ours to redistribute


def is_bundled_pack(name):
    """Shader/resource packs bundled in overrides/ are never shipped (redistribution not permitted).
    Only the small top-level .txt shader settings stay. Modrinth-hosted packs listed in the index are unaffected."""
    return name.startswith(("overrides/shaderpacks/", "overrides/resourcepacks/")) and not (
        name.endswith(".txt") and name.count("/") == 2)


def call(path, data=None, headers=None):
    req = urllib.request.Request(API + path, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def unhosted(z, index):
    """Files Modrinth moderation would flag: bad download hosts, or override jars/zips not on Modrinth
    (bundled shader/resource packs are excluded from the build instead, see is_bundled_pack)."""
    bad = [f["path"] for f in index["files"] if not {u.split("/")[2] for u in f["downloads"]} <= ALLOWED_HOSTS]
    blobs = {
        hashlib.sha1(z.read(n)).hexdigest(): n
        for n in z.namelist()
        if n.startswith("overrides/") and n.endswith((".jar", ".zip")) and SKIP not in n and not is_bundled_pack(n)
    }
    body = json.dumps({"hashes": list(blobs), "algorithm": "sha1"}).encode()
    known = call("/version_files", body, {"Content-Type": "application/json"}) if blobs else {}
    return bad + [n for h, n in blobs.items() if h not in known]


def ensure_update_checker(index):
    if any("modpack-update-checker" in f["path"].lower() for f in index["files"]):
        return
    deps = index["dependencies"]
    loader = next(k for k in deps if k != "minecraft")
    q = urllib.parse.urlencode({"loaders": json.dumps([loader]), "game_versions": json.dumps([deps["minecraft"]])})
    f = next(x for x in call(f"/project/modpack-update-checker/version?{q}")[0]["files"] if x["primary"])
    index["files"].append({
        "path": f"mods/{f['filename']}",
        "hashes": {"sha1": f["hashes"]["sha1"], "sha512": f["hashes"]["sha512"]},
        "env": {"client": "required", "server": "unsupported"},
        "downloads": [f["url"]],
        "fileSize": f["size"],
    })


def build(z, index, version, out):
    index.update(name=NAME, versionId=version)
    ensure_update_checker(index)
    extra = {
        "overrides/" + p.relative_to(ROOT / "pack-config").as_posix(): p.read_text().replace("{{VERSION}}", version)
        for p in (ROOT / "pack-config").rglob("*") if p.is_file()
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in z.infolist():
            if (item.filename != "modrinth.index.json" and SKIP not in item.filename
                    and not is_bundled_pack(item.filename) and item.filename not in extra):
                zo.writestr(item, z.read(item.filename))
        zo.writestr("modrinth.index.json", json.dumps(index, indent=2))
        for name, text in extra.items():
            zo.writestr(name, text)


def upload(path, version, channel, changelog, index):
    token, project = os.environ["MODRINTH_TOKEN"], os.environ["MODRINTH_PROJECT"]
    deps = index["dependencies"]
    data = {
        "project_id": call(f"/project/{project}")["id"],
        "name": f"{NAME} {version}",
        "version_number": version,
        "changelog": changelog,
        "dependencies": [],
        "game_versions": [deps["minecraft"]],
        "loaders": [k for k in deps if k != "minecraft"],
        "version_type": channel,
        "featured": False,
        "file_parts": ["file"],
        "primary_file": "file",
    }
    b = "----meridian" + hashlib.md5(os.urandom(8)).hexdigest()
    body = (
        f'--{b}\r\nContent-Disposition: form-data; name="data"\r\nContent-Type: application/json\r\n\r\n{json.dumps(data)}\r\n'
        f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/x-modrinth-modpack+zip\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
    return call("/version", body, {"Authorization": token, "Content-Type": f"multipart/form-data; boundary={b}"})


def next_version(meta):
    base, ids = time.strftime("%Y.%m"), {v["id"] for v in meta["versions"]}
    n = 0
    while (v := base if n == 0 else f"{base}.{n}") in ids:
        n += 1
    return v


def bump_meta(version, update_type):
    p = ROOT / "meta.json"
    meta = json.loads(p.read_text())
    entry = {"id": version, "releasedAt": int(time.time() * 1000)}
    if update_type:
        entry["updateType"] = update_type
    entry["promotions"] = {"downloads": {"modrinth": PROJECT_URL}}
    meta["versions"].append(entry)
    p.write_text(json.dumps(meta, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack", type=Path, help="source .mrpack")
    ap.add_argument("version", nargs="?", help="YYYY.MM or YYYY.MM.N (default: next free one for this month)")
    ap.add_argument("--type", choices=["minor", "minor_breaking", "major", "incompatible"],
                    help="update type for Modpack Update Checker (default: minor for monthly, none for hotfix)")
    ap.add_argument("--channel", choices=["release", "beta", "alpha"], default="release")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--allow-unhosted", action="store_true", help="build anyway; Modrinth review will likely reject")
    a = ap.parse_args()
    meta = json.loads((ROOT / "meta.json").read_text())
    a.version = a.version or next_version(meta)
    if not re.fullmatch(r"\d{4}\.(0[1-9]|1[0-2])(\.[1-9]\d*)?", a.version):
        sys.exit("version must look like 2026.10 or 2026.10.1")
    a.type = a.type or (None if a.version.count(".") == 2 else "minor")

    changelog_path = ROOT / "versions" / a.version / "changelog.txt"
    if a.publish:
        if any(v["id"] == a.version for v in meta["versions"]):
            sys.exit(f"{a.version} is already in meta.json")
        if not changelog_path.exists() or "TODO" in changelog_path.read_text():
            sys.exit(f"write {changelog_path.relative_to(ROOT)} first (no TODO left in it)")

    z = zipfile.ZipFile(a.pack)
    index = json.loads(z.read("modrinth.index.json"))
    bad = unhosted(z, index)
    if bad:
        print("Not on Modrinth (needs author permission, a Modrinth-hosted file, or removal):")
        print("\n".join(f"  {n}" for n in bad))
        if not a.allow_unhosted:
            sys.exit(1)

    out = ROOT / "dist" / f"{NAME}-{a.version}.mrpack"
    out.parent.mkdir(exist_ok=True)
    build(z, index, a.version, out)
    print(f"built {out} ({out.stat().st_size / 1e6:.0f} MB)")
    if not a.publish:
        return
    v = upload(out, a.version, a.channel, changelog_path.read_text(), index)
    bump_meta(a.version, a.type)
    print(f"published {v['id']}; now commit + push meta.json and versions/{a.version}/")


if __name__ == "__main__":
    main()
