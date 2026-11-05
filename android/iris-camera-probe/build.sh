#!/bin/sh
set -eu

: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT}"
: "${PROBE_KEYSTORE:?Set PROBE_KEYSTORE}"
: "${PROBE_KEY_ALIAS:?Set PROBE_KEY_ALIAS}"
: "${PROBE_STORE_PASSWORD:?Set PROBE_STORE_PASSWORD}"
: "${PROBE_KEY_PASSWORD:?Set PROBE_KEY_PASSWORD}"

APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLATFORM="$ANDROID_SDK_ROOT/platforms/android-35/android.jar"
BUILD_TOOLS="$ANDROID_SDK_ROOT/build-tools/35.0.0"
OUT="$APP_DIR/build"
CLASSES="$OUT/classes"
DEX="$OUT/dex"

rm -rf "$CLASSES" "$DEX"
mkdir -p "$CLASSES" "$DEX"
"$BUILD_TOOLS/aapt" package -f -M "$APP_DIR/AndroidManifest.xml" \
    -I "$PLATFORM" -F "$OUT/unsigned.apk" \
    --min-sdk-version 26 --target-sdk-version 28
javac -source 8 -target 8 -classpath "$PLATFORM" -d "$CLASSES" \
    "$APP_DIR/src/com/lumia/irisprobe/IrisProbeActivity.java" \
    "$APP_DIR/src/com/lumia/irisprobe/EyeRegionGeometry.java" \
    "$APP_DIR/src/com/lumia/irisprobe/CircularBoundaryProposal.java" \
    "$APP_DIR/src/com/lumia/irisprobe/DiagnosticFrameQuality.java" \
    "$APP_DIR/src/com/lumia/irisprobe/LogGaborIrisCodePrototype.java"
jar cf "$OUT/classes.jar" -C "$CLASSES" .
"$BUILD_TOOLS/d8" --min-api 26 --lib "$PLATFORM" --output "$DEX" "$OUT/classes.jar"
cp "$DEX/classes.dex" "$OUT/classes.dex"
zip -q -j "$OUT/unsigned.apk" "$OUT/classes.dex"
"$BUILD_TOOLS/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
"$BUILD_TOOLS/apksigner" sign \
    --ks "$PROBE_KEYSTORE" --ks-key-alias "$PROBE_KEY_ALIAS" \
    --ks-pass "env:PROBE_STORE_PASSWORD" --key-pass "env:PROBE_KEY_PASSWORD" \
    --out "$OUT/LumiaIrisProbe.apk" "$OUT/aligned.apk"
"$BUILD_TOOLS/apksigner" verify "$OUT/LumiaIrisProbe.apk"
