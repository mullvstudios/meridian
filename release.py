#!/usr/bin/env python3
"""Verify, build and publish a Meridian release. Stdlib only.

  python3 release.py pv2o2b.mrpack                       # verify + build dist/Meridian-<version>.mrpack
  python3 release.py pv2o2b.mrpack --publish             # token/project from .env (see .env.example) or the environment
  python3 release.py pv2o2b.mrpack 2026.09 --github      # GitHub release: powerful + slowpc + no-packs (Modrinth) builds

Versions are calendar based: YYYY.MM for the monthly release, YYYY.MM.1, .2 ... for hotfixes in the
same month. Omit the version and it is derived from today's date and meta.json.

--publish uploads the no-packs build to Modrinth, --github creates the GitHub release; both record the download in meta.json
(read in game by Modpack Update Checker). Commit and push meta.json + versions/ afterwards.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
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
PROJECT_URL = "https://modrinth.com/modpack/meridian-mullv"
REPO = "mullvstudios/meridian"
PACK_DIRS = ("shaderpacks/", "resourcepacks/")
# GitHub release assets. keep_packs: keep the Modrinth-hosted shader/resource packs listed in the index
# (the launcher downloads them from Modrinth's CDN). Packs bundled in overrides/ are never shipped.
# "modrinth" has no packs at all (what Modrinth review accepts) and is what --publish uploads.
VARIANTS = {"": False, "powerful": True, "slowpc": False}  # suffix -> keep_packs
# Mod files left out of a variant, matched case-insensitively on the start of the jar name (so version bumps keep
# matching). Each prefix must match at least one file, so a rename upstream fails the build instead of silently
# shipping the mod. Measured in spark: Antique Atlas ~20% and Sound Physics ~5% of the render thread.
EXCLUDE = {
    "": ("spawn-4.0.7",),  # two Spawn versions are exported side by side; NeoForge loads 4.0.8 (drop this once removed from the pack)
    "slowpc": (
        "antique-atlas", "antique_transport",  # transport requires the atlas; Map Atlases stays
        "sound-physics-",  # remastered + aeronautics
        "entity_model_features", "entity_texture_features", "continuity", "polytone",  # only useful with resource packs
        "fpsreducer", "lambdynamiclights", "create-dyn-light", "blur-neoforge", "eg-inventory-blur",
        "enhancedvisuals", "immersivethunder",
    ),
}
# Hosts Modrinth accepts in modrinth.index.json downloads.
ALLOWED_HOSTS = {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
# Never shipped: per-player state exported along with the pack (account ids, last world, old server list) and
# FancyMenu media of unknown origin/licence (241 MB wav, 25 MB mp4) that would also bloat every build to 260 MB.
PRIVATE = ("overrides/config/fancymenu/assets/background_music.wav", "overrides/config/fancymenu/assets/238264.mp4",
           "overrides/fancymenu_data/buddy/", "overrides/fancymenu_data/last_world.fmdata",
           "overrides/config/fancymenu/user_variables.db", "overrides/servers.dat_old")
SKIP = "/.connector/"  # Sinytra Connector cache: regenerated on launch, not ours to redistribute


def is_bundled_pack(name, keep_settings=True):
    """Shader/resource packs bundled in overrides/ are never shipped (redistribution not permitted).
    Top-level .txt shader settings stay when keep_settings. Modrinth-hosted packs in the index are unaffected."""
    return name.startswith(("overrides/shaderpacks/", "overrides/resourcepacks/")) and not (
        keep_settings and name.endswith(".txt") and name.count("/") == 2)


def load_env():
    """Read KEY=VALUE lines from .env (git-ignored); real environment variables win."""
    p = ROOT / ".env"
    for line in p.read_text().splitlines() if p.exists() else []:
        k, sep, v = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def call(path, data=None, headers=None):
    req = urllib.request.Request(API + path, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def unhosted(z, index):
    """Files Modrinth moderation would flag: bad download hosts, or override jars/zips not on Modrinth
    and not listed in allowed-overrides.txt
    (bundled shader/resource packs are excluded from the build instead, see is_bundled_pack)."""
    bad = [f["path"] for f in index["files"] if not {u.split("/")[2] for u in f["downloads"]} <= ALLOWED_HOSTS]
    blobs = {
        hashlib.sha1(z.read(n)).hexdigest(): n
        for n in z.namelist()
        if n.startswith("overrides/") and n.endswith((".jar", ".zip")) and SKIP not in n and not is_bundled_pack(n)
    }
    body = json.dumps({"hashes": list(blobs), "algorithm": "sha1"}).encode()
    known = call("/version_files", body, {"Content-Type": "application/json"}) if blobs else {}
    allowed = {l.split("#")[0].strip() for l in (ROOT / "allowed-overrides.txt").read_text().splitlines()}
    return bad + [n for h, n in blobs.items() if h not in known and n not in allowed]


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


def excluded(index, prefixes):
    """Index entries whose jar name starts with one of the prefixes; fails if a prefix matches nothing."""
    hits = {p: [f for f in index["files"] if f["path"].split("/")[-1].lower().startswith(p)] for p in prefixes}
    stale = [p for p, fs in hits.items() if not fs]
    if stale:
        sys.exit(f"EXCLUDE entries match no file in the pack (renamed or removed?): {', '.join(stale)}")
    return {f["path"] for fs in hits.values() for f in fs}


def build(z, index, version, out, keep_packs=False, exclude=()):
    index = copy.deepcopy(index)
    index.update(name=NAME, versionId=version)
    if exclude:
        gone = excluded(index, exclude)
        index["files"] = [f for f in index["files"] if f["path"] not in gone]
    if not keep_packs:
        index["files"] = [f for f in index["files"] if not f["path"].startswith(PACK_DIRS)]
    ensure_update_checker(index)
    extra = {
        "overrides/" + p.relative_to(ROOT / "pack-config").as_posix(): p.read_text().replace("{{VERSION}}", version)
        for p in (ROOT / "pack-config").rglob("*") if p.is_file()
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in z.infolist():
            if (item.filename != "modrinth.index.json" and SKIP not in item.filename
                    and not is_bundled_pack(item.filename, keep_packs) and item.filename not in extra
                    and not item.filename.startswith(PRIVATE)):
                zo.writestr(copy.copy(item), z.read(item.filename))
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


def has_download(meta, version, key):
    return any(v["id"] == version and key in v.get("promotions", {}).get("downloads", {}) for v in meta["versions"])


def bump_meta(version, update_type, key, url):
    """Record version in meta.json (created on first call) and add this download link to it."""
    p = ROOT / "meta.json"
    meta = json.loads(p.read_text())
    entry = next((v for v in meta["versions"] if v["id"] == version), None)
    if entry is None:
        entry = {"id": version, "releasedAt": int(time.time() * 1000)}
        if update_type:
            entry["updateType"] = update_type
        meta["versions"].append(entry)
    entry.setdefault("promotions", {}).setdefault("downloads", {})[key] = url
    p.write_text(json.dumps(meta, indent=2) + "\n")


def github_release(version, assets, notes):
    tag = f"v{version}"
    subprocess.run(["gh", "release", "create", tag, *map(str, assets), "--repo", REPO,
                    "--title", f"{NAME} {version}", "--notes-file", str(notes)], check=True)
    return f"https://github.com/{REPO}/releases/tag/{tag}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack", type=Path, help="source .mrpack")
    ap.add_argument("version", nargs="?", help="YYYY.MM or YYYY.MM.N (default: next free one for this month)")
    ap.add_argument("--type", choices=["minor", "minor_breaking", "major", "incompatible"],
                    help="update type for Modpack Update Checker (default: minor for monthly, none for hotfix)")
    ap.add_argument("--channel", choices=["release", "beta", "alpha"], default="release")
    ap.add_argument("--publish", action="store_true", help="upload the no-packs build to Modrinth")
    ap.add_argument("--github", action="store_true", help="build all variants and create the GitHub release")
    ap.add_argument("--allow-unhosted", action="store_true", help="build anyway; Modrinth review will likely reject")
    a = ap.parse_args()
    load_env()
    meta = json.loads((ROOT / "meta.json").read_text())
    a.version = a.version or next_version(meta)
    if not re.fullmatch(r"\d{4}\.(0[1-9]|1[0-2])(\.[1-9]\d*)?", a.version):
        sys.exit("version must look like 2026.10 or 2026.10.1")
    a.type = a.type or (None if a.version.count(".") == 2 else "minor")

    changelog_path = ROOT / "versions" / a.version / "changelog.txt"
    if a.publish:
        missing = [k for k in ("MODRINTH_TOKEN", "MODRINTH_PROJECT") if not os.environ.get(k)]
        if missing:
            sys.exit(f"--publish needs {' and '.join(missing)} set in the environment")
        if has_download(meta, a.version, "modrinth"):
            sys.exit(f"{a.version} is already published on Modrinth")
    if a.github and has_download(meta, a.version, "generic"):
        sys.exit(f"{a.version} already has a GitHub release")
    if a.publish or a.github:
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

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    built = {}
    for suffix, keep in (VARIANTS.items() if a.github else [("", False)]):
        out = dist / f"{NAME}-{a.version}{'-' + suffix if suffix else ''}.mrpack"
        build(z, index, a.version, out, keep, EXCLUDE[""] + EXCLUDE.get(suffix, ()))
        built[suffix] = out
        print(f"built {out.name} ({out.stat().st_size / 1e6:.0f} MB)")
    if a.github:
        url = github_release(a.version, built.values(), changelog_path)
        bump_meta(a.version, a.type, "generic", url)
        print(f"GitHub release: {url}")
    if a.publish:
        v = upload(built[""], a.version, a.channel, changelog_path.read_text(), index)
        bump_meta(a.version, a.type, "modrinth", PROJECT_URL)
        print(f"published {v['id']} on Modrinth")
    if a.github or a.publish:
        print(f"now commit + push meta.json and versions/{a.version}/")


if __name__ == "__main__":
    main()
