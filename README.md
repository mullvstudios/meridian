# Meridian (Survival 2027)

Release tooling and Modrinth assets for the mullv.studio Meridian modpack
(Minecraft 1.21.1, NeoForge 21.1.248). Pattern copied from `mullvstudios/earthworks`.

```
modrinth/       icon.png, banner.png (gallery), description.md, summary.txt  -> paste into Modrinth
pack-config/    files injected into overrides/ at build (Modpack Update Checker config)
meta.json       Modpack Update Checker feed (grows one entry per release)
versions/YYYY.MM/changelog.txt   one per release, also used as the Modrinth changelog
release.py      verify + build + publish
art/make_art.py regenerates icon/banner (change NAME, re-run)
```

## Before the first publish (blockers)

Bundled shader packs and resource packs (in `overrides/`) are never shipped: `release.py` strips them
automatically (Modrinth-hosted ones listed in the index stay). `python3 release.py pv2o2b.mrpack` then lists
the remaining files Modrinth moderation will reject. Today that is 3 mod jars:

| File | Fix |
|---|---|
| `refurbished_furniture`, `framework` (jars) | Furniture is MIT: use the Modrinth-hosted file (project `mrcrayfishs-furniture-mod-tools-refurbished`). Framework (its dependency) did not turn up in a Modrinth search: check its license, or ask the author |
| `tfmg ... community.jar` | project `create-tfmg` (MIT-NON-AI) is on Modrinth: switch to its hosted file, or ask the author for the community build |

The `.connector` cache folder is stripped automatically. Put replaced files into the pack's
`modrinth.index.json` (re-export from the Modrinth App) and re-run.

## One-time setup

1. (Done: the project already exists.) Project settings used (modpack, under the mullv.studio organization):
   title **Meridian**, slug `meridian`, summary from `modrinth/summary.txt`, body from
   `modrinth/description.md`, icon `modrinth/icon.png`, gallery `modrinth/banner.png` (featured),
   license MIT (or your choice), environment client + server, categories technology / adventure / multiplayer,
   source/issues links to the new GitHub repo.
2. Create GitHub repo `mullvstudios/meridian` and push this folder (the update checker reads
   `https://raw.githubusercontent.com/mullvstudios/meridian/main/meta.json`).
3. Modrinth settings > PATs: token with "Create versions".

## Releasing (monthly)

Calendar versioning: `YYYY.MM` for the monthly release (`2026.10`, `2026.11`, ...), `YYYY.MM.1`, `.2`
for hotfixes within the same month. The same string is the Modrinth version number, the
`modrinth.index.json` versionId, the update checker `currentVersion` and the `versions/<v>/` folder.
`release.py` picks the next free one from today's date and `meta.json`.

Update type shown by the update checker: monthly releases default to `minor`. Pass `--type major`
or `--type incompatible` when a world backup or fresh world is needed (e.g. a Minecraft version bump),
hotfixes default to none.

```
# 1. export the updated pack as .mrpack from the Modrinth App
# 2. write versions/2026.11/changelog.txt   (version = this month, see `python3 release.py x.mrpack` output)
# 3.
export MODRINTH_TOKEN=... MODRINTH_PROJECT=meridian
python3 release.py new.mrpack --publish
# 4. git add meta.json versions && git commit && git push   (in-game update notice goes live)
```

Players on the Modrinth App see an update button as soon as the version is published; the
update checker covers other launchers and shows the changelog in game.
