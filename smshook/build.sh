#!/system/bin/sh
# Build SmsPoller DEX for the UZ801 dongle.
#
# This script compiles SmsPoller.java -> DEX using the Android build tools
# and android.jar (API 19). The resulting smshook.dex runs on the dongle
# via: app_process /data/local/tmp com.godwhitelight.smshook.SmsPoller
#
# Prerequisites:
#   - JDK 8+ (javac)
#   - Android build-tools (d8.jar)
#   - android.jar (API 19)
#
# Usage (on Windows with the build tools in build/):
#   bash build.sh
#
# Or adapt the paths below for your system.

ANDROID_JAR=${ANDROID_JAR:-../build/android-19.jar}
D8_JAR=${D8_JAR:-../build/build-tools/android-14/lib/d8.jar}
SRC=src/com/godwhitelight/smshook/SmsPoller.java
OUT_DIR=obj
BIN_DIR=bin
DEX_FILE=smshook.dex

echo "=== [1/4] Compiling Java ==="
mkdir -p $OUT_DIR
javac -source 8 -target 8 -Xlint:-options \
    -bootclasspath "$ANDROID_JAR" \
    -d $OUT_DIR \
    "$SRC" || { echo "FAILED: javac"; exit 1; }

echo "=== [2/4] Converting to DEX ==="
mkdir -p $BIN_DIR
java -cp "$D8_JAR" com.android.tools.r8.D8 \
    --release --min-api 19 \
    --lib "$ANDROID_JAR" \
    --output $BIN_DIR \
    $OUT_DIR/com/godwhitelight/smshook/*.class || { echo "FAILED: d8"; exit 1; }

echo "=== [3/4] Copying DEX ==="
cp $BIN_DIR/classes.dex $DEX_FILE

echo "=== [4/4] Done ==="
echo "Built: $DEX_FILE ($(wc -c < $DEX_FILE) bytes)"
echo ""
echo "To deploy to dongle:"
echo "  adb push $DEX_FILE /data/local/tmp/smshook.dex"
echo "  adb shell 'export ANDROID_DATA=/data CLASSPATH=/data/local/tmp/smshook.dex && app_process /data/local/tmp com.godwhitelight.smshook.SmsPoller &'"
echo ""
echo "Or use the Python library:"
echo "  from uz801_sms import UZ801"
echo "  dongle = UZ801()"
echo "  dongle.deploy_poller()"
echo "  dongle.start_poller()"
