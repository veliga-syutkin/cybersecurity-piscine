#!/bin/sh
# Checks whether this machine can build a small Rust project with crates.
# Read-only except for a throwaway project in a temp dir (deleted at the end).

echo "== 1. Toolchain =="
for bin in rustup cargo rustc; do
    if command -v "$bin" >/dev/null 2>&1; then
        echo "OK   $bin -> $(command -v "$bin") ($("$bin" --version 2>/dev/null | head -n1))"
    else
        echo "MISS $bin"
    fi
done

echo
echo "== 2. Network access to crates.io =="
if command -v curl >/dev/null 2>&1; then
    if curl -sSf -m 10 -o /dev/null https://index.crates.io/config.json; then
        echo "OK   crates.io index reachable"
    else
        echo "FAIL crates.io index NOT reachable (proxy/firewall?)"
    fi
    if curl -sSf -m 10 -o /dev/null https://sh.rustup.rs; then
        echo "OK   sh.rustup.rs reachable (rustup install possible without root)"
    else
        echo "FAIL sh.rustup.rs NOT reachable"
    fi
else
    echo "MISS curl"
fi

echo
echo "== 3. Disk space in HOME (rustup toolchain needs ~1-1.5 GB) =="
df -h "$HOME" | tail -n1
if command -v quota >/dev/null 2>&1; then
    quota -s 2>/dev/null
fi

echo
echo "== 4. Real build test (hmac + sha1 crates) =="
if ! command -v cargo >/dev/null 2>&1; then
    echo "SKIP cargo not available"
    exit 0
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP" || exit 1
cargo new --quiet otp_check || exit 1
cd otp_check || exit 1
cat >> Cargo.toml <<'EOF'
hmac = "0.12"
sha1 = "0.10"
EOF
if cargo build --quiet 2>build.log; then
    echo "OK   build with external crates succeeded"
else
    echo "FAIL build failed, last lines:"
    tail -n 15 build.log
fi
