#!/bin/sh
# Checks whether this machine can build AND open an eframe (egui) window.
# Everything happens in a temp dir, deleted at the end (target/ is ~1 GB).

echo "== 1. Rust version (eframe 0.35 needs rustc >= 1.92) =="
rustc --version

echo
echo "== 2. Disk space in HOME and /tmp (the build needs ~1.2 GB) =="
df -h "$HOME" /tmp | tail -n 2

echo
echo "== 3. Display =="
echo "DISPLAY=${DISPLAY} WAYLAND_DISPLAY=${WAYLAND_DISPLAY}"

echo
echo "== 4. Build + open a window (first build takes a few minutes) =="
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CARGO_HOME="${TMP}/.cargo-home"   # /opt/rust is read-only at school
cd "$TMP" || exit 1
cargo new --quiet gui_check || exit 1
cd gui_check || exit 1
cargo add --quiet eframe || exit 1
cat > src/main.rs <<'EOF'
fn main() -> eframe::Result {
    eframe::run_ui_native("gui check", Default::default(), |ui, _frame| {
        ui.label("eframe works: close this window");
    })
}
EOF
START=$(date +%s)
if cargo build --release --quiet 2>build.log; then
    echo "OK   build in $(( $(date +%s) - START )) s, target/ = $(du -sh target | cut -f1)"
    echo "     a window should open now: close it to finish"
    ./target/release/gui_check && echo "OK   window opened and closed" \
        || echo "FAIL the window could not open (see message above)"
else
    echo "FAIL build failed, last lines:"
    tail -n 20 build.log
fi
