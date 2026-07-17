# Launchpad PPA

> ## ⚠️ Not published yet
>
> **There is no `ppa:sskazal/meeting-recorder` today — don't advertise one.** The
> packaging in [`debian/`](../debian) is finished and CI builds it on every push,
> so this is ready to go whenever we want it; nothing here is done yet though.
>
> Use the [GitHub Pages APT repository](APT-REPO.md) instead: it gives users the
> same `sudo apt install meeting-recorder` with auto-updates, needs no Launchpad
> account, and publishes automatically on release.
>
> A PPA only adds the familiar `add-apt-repository ppa:...` one-liner. Worth doing
> eventually; not worth blocking on.

---

A PPA gives Ubuntu users the most native install path:

```bash
sudo add-apt-repository ppa:sskazal/meeting-recorder
sudo apt update
sudo apt install meeting-recorder
```

Unlike the [GitHub Pages APT repo](APT-REPO.md), **Launchpad builds from source**
— you upload a *source package* and its build farm produces the `.deb`. That's
why this repo carries a real [`debian/`](../debian) directory alongside
`packaging/build-deb.sh`.

> The two paths install exactly the same files. `debian/rules` and
> `packaging/build-deb.sh` share `packaging/meeting-recorder.bin`, the service
> unit, desktop entry, icon and man page — if you change one, change both. CI
> builds **both** on every push so they can't silently drift.

---

## One-time setup

1. **Create a Launchpad account** — <https://launchpad.net>
2. **Register a GPG key** with it: <https://launchpad.net/~/+editpgpkeys>
   ```bash
   gpg --list-secret-keys --keyid-format=long   # find your key
   gpg --send-keys --keyserver keyserver.ubuntu.com <KEY_ID>
   ```
   Launchpad emails you an encrypted confirmation — decrypt it and follow the link.
3. **Sign the Ubuntu Code of Conduct**: <https://launchpad.net/codeofconduct>
4. **Create the PPA**: on your profile, *Create a new PPA*, name it
   `meeting-recorder`.
5. Install the tools:
   ```bash
   sudo apt install devscripts debhelper dput
   ```

---

## Publishing a release

```bash
# 1. Make sure debian/changelog has an entry for this version and the right
#    Ubuntu series (noble, jammy, ...). To add one interactively:
dch -v 0.1.2 -D noble "Describe the change"

# 2. Build a SIGNED source package (this is what Launchpad accepts).
#    -S = source only, -sa = include the original tarball.
debuild -S -sa

# 3. Upload
dput ppa:sskazal/meeting-recorder ../meeting-recorder_0.1.2_source.changes
```

Launchpad emails you an accept/reject notice, then builds. Watch progress at
`https://launchpad.net/~sskazal/+archive/ubuntu/meeting-recorder/+packages`.

### Notes and gotchas

- **Version numbers must never be reused.** Launchpad rejects a re-upload of an
  existing version — bump to `0.1.2`, or `0.1.2~ppa2` while iterating.
- **One upload per Ubuntu series.** To support both noble and jammy, upload the
  same source twice with series-specific versions, e.g. `0.1.2~noble1` and
  `0.1.2~jammy1` (change the distribution in `debian/changelog` each time).
- We use `3.0 (native)` source format, so the version has **no** Debian revision
  (`0.1.2`, not `0.1.2-1`). That's appropriate because upstream and packaging live
  in the same repo.
- `debian/rules` runs the test suite via `override_dh_auto_test`, so a broken
  build fails on Launchpad rather than shipping.
- **`gir1.2-appindicator3-0.1` must exist in the target series.** It's present in
  noble; check before promising support for an older series.

### Checking before you upload

```bash
dpkg-buildpackage -us -uc -b     # build the .deb from debian/ locally
lintian ../meeting-recorder_*.deb
sudo apt install ../meeting-recorder_*.deb
meeting-recorder --version
```

CI runs the first two on every push (see the *Build source package (PPA)* job),
so breakage is usually caught before you get here.

---

## Which channel should I use?

| | GitHub Pages APT repo | Launchpad PPA |
|---|---|---|
| Setup | GPG key + 2 secrets, fully automated | Launchpad account, CoC, key registration |
| Publishing | automatic on release | manual `debuild -S` + `dput` |
| Builds | our `.deb`, built in CI | built by Launchpad from source |
| Users | `curl` key + add source line | `add-apt-repository ppa:...` (one line) |
| Multiple Ubuntu series | one `all` package serves all | one upload per series |

Running both is fine — they're independent. The Pages repo needs no human in the
loop, so it's the better default; the PPA is worth it for the familiar
`add-apt-repository` flow Ubuntu users expect.
