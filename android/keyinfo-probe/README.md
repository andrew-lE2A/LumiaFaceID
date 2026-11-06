# Lumia KeyInfo diagnostic

Temporary, separate APK for querying the connected phone's Android Keystore.
It generates one AES key in the app UID's AndroidKeyStore that requires device
credential authentication for every use, reads `KeyInfo`, then deletes the
alias on success or handled failure. It does not request
camera, biometric, network, or LED permissions. Uninstall the package after a
run as an additional cleanup step.

This directory contains Apktool Smali source so the probe can be built without
an Android SDK installation. Build with Apktool 3.0.3 after pulling the target
phone's `framework-res.apk` and registering it as Apktool framework ID 1:

```sh
apktool if -p /private/tmp/lumia-apktool-framework /private/tmp/lumia-framework-res.apk
apktool b -p /private/tmp/lumia-apktool-framework android/keyinfo-probe \
  -o /private/tmp/LumiaKeyInfoProbe-unsigned.apk
```

Sign with a short-lived test key, install, launch, read the `LumiaKeyInfo` log
tag, then uninstall. Never reuse the diagnostic key for another package.
Device output from the first successful run is in
[`device-result-2026-11-06.json`](device-result-2026-11-06.json).

The phone must have a secure lock screen enabled to create a
credential-authenticated key. The probe does not read, store, or change the
credential. `device-result-2026-11-06.json` records the initial failure without
a credential and `pinned-credential-result-2026-11-06.json` records the
follow-up after the owner configured one. A software-level `KeyInfo` result
describes that generated key and configured Keymaster path; it does not prove
every Keymaster algorithm or key class has the same backing.
