#!/bin/bash
# Isolated packaging control-flow tests; never create/mount a real disk image.
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test_root=$(mktemp -d "${TMPDIR:-/tmp}/docufreedom-dmg-test.XXXXXX")
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/bin" "$test_root/input.app" "$test_root/tmp"
cat > "$test_root/bin/ditto" <<'SH'
#!/bin/bash
mkdir -p "$2"
SH
cat > "$test_root/bin/sleep" <<'SH'
#!/bin/bash
echo "$1" >> "$TEST_SLEEPS"
SH
cat > "$test_root/bin/hdiutil" <<'SH'
#!/bin/bash
count=0
if [ -f "$TEST_COUNT" ]; then count=$(cat "$TEST_COUNT"); fi
count=$((count + 1))
echo "$count" > "$TEST_COUNT"
if [ "$TEST_CASE" = always-busy ] || { [ "$TEST_CASE" = busy-once ] && [ "$count" -eq 1 ]; }; then
    echo 'hdiutil: create failed - Resource busy' >&2
    exit 16
fi
if [ "$TEST_CASE" = non-busy ]; then
    echo 'hdiutil: create failed - No space left on device' >&2
    exit 28
fi
touch "${@: -1}"
SH
chmod +x "$test_root/bin/ditto" "$test_root/bin/sleep" "$test_root/bin/hdiutil"
export PATH="$test_root/bin:$PATH"
export TMPDIR="$test_root/tmp"
for scenario in busy-once always-busy non-busy; do
    export TEST_CASE="$scenario" TEST_COUNT="$test_root/$scenario.count" TEST_SLEEPS="$test_root/$scenario.sleeps"
    : > "$TEST_SLEEPS"
    status=0
    "$SCRIPT_DIR/package-dmg.sh" "$test_root/input.app" "$test_root/$scenario.dmg" > "$test_root/$scenario.stdout" 2> "$test_root/$scenario.stderr" || status=$?
    count=$(cat "$TEST_COUNT")
    case "$scenario" in
        busy-once)
            [ "$status" -eq 0 ]
            [ "$count" -eq 2 ]
            [ -f "$test_root/$scenario.dmg" ]
            [ "$(cat "$TEST_SLEEPS")" = 2 ]
            grep -q 'Resource busy' "$test_root/$scenario.hdiutil.log"
            ;;
        always-busy)
            [ "$status" -eq 16 ]
            [ "$count" -eq 3 ]
            [ ! -e "$test_root/$scenario.dmg" ]
            [ "$(tr '\n' ',' < "$TEST_SLEEPS")" = '2,5,' ]
            [ "$(grep -c 'Resource busy' "$test_root/$scenario.hdiutil.log")" -eq 3 ]
            ;;
        non-busy)
            [ "$status" -eq 28 ]
            [ "$count" -eq 1 ]
            [ ! -s "$TEST_SLEEPS" ]
            grep -q 'No space left on device' "$test_root/$scenario.stderr"
            ;;
    esac
    [ -z "$(ls -A "$test_root/tmp")" ]
    echo "PASS: $scenario"
done
