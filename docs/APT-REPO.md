# APT repository (GitHub Pages)

This repo can publish a **signed APT repository** to its own `gh-pages` branch, so
users install with `apt` and get updates automatically:

```bash
sudo apt install meeting-recorder
```

The [`APT repository`](../.github/workflows/apt-repo.yml) workflow runs whenever a
release is published: it builds the `.deb`, adds it to the pool (keeping older
versions), regenerates and signs the index, and pushes to `gh-pages`.

---

## One-time setup (maintainers)

### 1. Create a signing key

APT will only trust a signed repository, so the repo needs a GPG key. Use a key
**dedicated to this purpose** — never your personal key.

```bash
gpg --batch --quick-generate-key \
    "Smart Meeting Recorder <YOUR-EMAIL>" default default never
```

Find its fingerprint:

```bash
gpg --list-secret-keys --keyid-format=long
```

### 2. Add the key as repository secrets

Export the **private** key:

```bash
gpg --armor --export-secret-keys <FINGERPRINT>
```

In **Settings → Secrets and variables → Actions → New repository secret**, add:

| Secret | Value |
|---|---|
| `GPG_PRIVATE_KEY` | the full `-----BEGIN PGP PRIVATE KEY BLOCK-----` output above |
| `GPG_PASSPHRASE` | the key's passphrase (leave empty if it has none) |

> 🔐 Keep the private key backed up somewhere safe and **never commit it**. If it
> leaks, revoke it and publish a new one — every user has to re-add the new key,
> so treat this as a key you keep for the life of the project.

Optionally add a **variable** (not a secret) `DEB_MAINTAINER`, e.g.
`Your Name <you@example.com>`, which is written into the package metadata.

### 3. Enable GitHub Pages

**Settings → Pages → Build and deployment → Source: Deploy from a branch**,
branch **`gh-pages`**, folder **`/ (root)`**.

The branch is created by the first workflow run, so publish a release first (or
run the workflow manually via **Actions → APT repository → Run workflow**).

### 4. Publish

Every published release now updates the repository. To backfill an existing
release, run the workflow manually and give it the tag (e.g. `v0.1.1`).

---

## What gets published

```
gh-pages/
├── KEY.gpg                                   # public key users import
├── index.html                                # landing page with instructions
├── dists/stable/
│   ├── InRelease                             # inline-signed index
│   ├── Release
│   ├── Release.gpg
│   └── main/binary-all/Packages{,.gz}
└── pool/main/m/meeting-recorder/*.deb        # every published version
```

Old versions stay in `pool/`, so `apt install meeting-recorder=0.1.0` keeps working.

---

## User instructions

```bash
# 1. Trust the signing key
curl -fsSL https://sskazal.github.io/meeting-recorder/KEY.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/meeting-recorder.gpg

# 2. Add the repository
echo "deb [arch=all signed-by=/usr/share/keyrings/meeting-recorder.gpg] https://sskazal.github.io/meeting-recorder stable main" \
  | sudo tee /etc/apt/sources.list.d/meeting-recorder.list

# 3. Install
sudo apt update
sudo apt install meeting-recorder
```

> **Why `arch=all`?** The package is `Architecture: all` (pure Python, works on any
> CPU), so the repository only publishes a `binary-all` index. Without `arch=all`,
> apt also looks for `binary-amd64`/`binary-i386` and prints harmless
> "doesn't support architecture" notes. The package installs either way.

Uninstall:

```bash
sudo apt remove meeting-recorder
sudo rm /etc/apt/sources.list.d/meeting-recorder.list \
        /usr/share/keyrings/meeting-recorder.gpg
```

---

## Testing it locally

The generator is a plain script, so you can build and validate a repository
without touching GitHub:

```bash
./packaging/build-deb.sh
GPG_KEY_ID=<FINGERPRINT> ./packaging/build-apt-repo.sh /tmp/aptrepo dist/*.deb

# serve it and point apt at it
(cd /tmp/aptrepo && python3 -m http.server 8788) &
gpg --armor --export <FINGERPRINT> | gpg --dearmor | sudo tee /usr/share/keyrings/mr-test.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/mr-test.gpg] http://127.0.0.1:8788 stable main" \
  | sudo tee /etc/apt/sources.list.d/mr-test.list
sudo apt update && apt policy meeting-recorder
```

Omitting `GPG_KEY_ID` produces an unsigned repo — useful for checking the layout,
but `apt` will refuse it without `[trusted=yes]`.

## Troubleshooting

**`NO_PUBKEY` / `not signed`** — the user didn't import `KEY.gpg`, or the
workflow ran without `GPG_PRIVATE_KEY`.

**`404` on `InRelease`** — GitHub Pages isn't serving `gh-pages` yet; check
**Settings → Pages**. The `.nojekyll` file must exist (the workflow creates it),
otherwise Jekyll hides the `dists/` directory.

**Package not found after `apt update`** — the architecture must match: this is
an `all` package, and the repo is generated for `binary-all`.
