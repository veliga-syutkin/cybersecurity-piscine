#!/bin/sh
# Checks whether this machine can run the ft_onion setup (Docker + Tor).
#
# Home directory safety:
#   - no bind mount (-v / --mount) is used, so the container cannot write
#     anything into $HOME;
#   - the container runs with --rm and is force-removed on exit / Ctrl-C;
#   - the debian image is removed at the end if it was not there before;
#   - temp files go to /tmp (mktemp), not to $HOME;
#   - step 5 lists any file created in $HOME during the run that is NOT
#     owned by you, so you can see for yourself that nothing root-owned appeared.

IMAGE="debian:trixie-slim"
NAME="ft_onion_check_$$"
ME=$(id -u)
TMP=$(mktemp -d)
STAMP="$TMP/stamp"
touch "$STAMP"
IMAGE_WAS_PRESENT=0

cleanup() {
    docker rm -f "$NAME" >/dev/null 2>&1
    if [ "$IMAGE_WAS_PRESENT" -eq 0 ]; then
        docker rmi "$IMAGE" >/dev/null 2>&1
    fi
    rm -rf "$TMP"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

echo "== 1. Docker CLI and daemon access (without sudo) =="
if ! command -v docker >/dev/null 2>&1; then
    echo "MISS docker command not found"
    exit 1
fi
echo "OK   $(docker --version)"
if ! docker info >/dev/null 2>"$TMP/info.err"; then
    echo "FAIL cannot talk to the Docker daemon:"
    sed 's/^/     /' "$TMP/info.err" | head -n 5
    exit 1
fi
echo "OK   daemon reachable as $(id -un)"
ROOTDIR=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)
if docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless; then
    echo "INFO rootless Docker (data in $ROOTDIR)"
else
    echo "INFO rootful Docker (data in $ROOTDIR)"
fi
case "$ROOTDIR" in
    "$HOME"/*)
        echo "WARN Docker data lives inside your HOME: images count against your quota."
        echo "     Files in there belong to sub-UIDs by design; delete them with"
        echo "     'docker system prune -a', never with rm."
        ;;
esac

echo
echo "== 2. Disk space =="
df -h "$HOME" | tail -n 1 | awk '{print "HOME        " $4 " free (" $5 " used)"}'
if [ -d "$ROOTDIR" ] && [ -r "$ROOTDIR" ]; then
    df -h "$ROOTDIR" | tail -n 1 | awk '{print "Docker data " $4 " free (" $5 " used)"}'
fi

echo
echo "== 3. Pull $IMAGE =="
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    IMAGE_WAS_PRESENT=1
    echo "OK   already present (will be kept)"
elif docker pull -q "$IMAGE" >/dev/null 2>"$TMP/pull.err"; then
    echo "OK   pulled (will be removed at the end)"
else
    echo "FAIL pull failed (no network / registry blocked?):"
    sed 's/^/     /' "$TMP/pull.err" | head -n 5
    exit 1
fi

echo
echo "== 4. apt install tor + Tor bootstrap inside a container (up to ~3 min) =="
# No volume, no published port: the container only makes outbound connections.
docker run --rm --name "$NAME" "$IMAGE" sh -c '
    export DEBIAN_FRONTEND=noninteractive
    if ! apt-get update -qq >/dev/null 2>&1; then
        echo "FAIL apt-get update failed (Debian mirrors unreachable)"; exit 2
    fi
    if ! apt-get install -y -qq tor >/dev/null 2>&1; then
        echo "FAIL apt-get install tor failed"; exit 2
    fi
    echo "OK   tor installed: $(tor --version | head -n 1)"
    tor --DataDirectory /tmp/tor --SocksPort 0 --Log "notice stdout" >/tmp/tor.log 2>&1 &
    i=0
    while [ "$i" -lt 150 ]; do
        if grep -q "Bootstrapped 100" /tmp/tor.log; then
            echo "OK   $(grep Bootstrapped /tmp/tor.log | tail -n 1 | sed "s/.*\(Bootstrapped\)/\1/")"
            echo "OK   took about ${i}s"
            exit 0
        fi
        sleep 1
        i=$((i + 1))
    done
    echo "FAIL Tor did not reach 100% in 150s. Last relevant lines:"
    grep -E "Bootstrapped|\[warn\]|\[err\]" /tmp/tor.log | tail -n 6 | sed "s/^/     /"
    exit 3
'
RESULT=$?

echo
echo "== 5. Files created in HOME during this run that are not yours =="
# Docker's own data dir is skipped: in rootless mode it is full of sub-UID files by design.
FOUND=$(find "$HOME" -xdev -path "$ROOTDIR" -prune -o \
        -newer "$STAMP" ! -user "$ME" -print 2>/dev/null | head -n 20)
if [ -z "$FOUND" ]; then
    echo "OK   none"
else
    echo "WARN found (first 20):"
    echo "$FOUND" | sed 's/^/     /'
fi

echo
if [ "$RESULT" -eq 0 ]; then
    echo "=> This machine can run ft_onion."
else
    echo "=> Step 4 failed (code $RESULT): see above."
fi
exit "$RESULT"
