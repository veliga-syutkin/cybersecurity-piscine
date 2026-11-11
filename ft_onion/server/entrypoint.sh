#!/bin/bash
# Starts the three services of the ft_onion server (sshd, tor, nginx) and
# watches them: if any of them stops, the other two are stopped as well and
# the container exits with status 1, so a failure shows in "docker ps -a"
# instead of a container that looks up while the site is unreachable.
# All of them log to the container logs (docker logs).
# bash, not sh: "wait -n -p" (wait for the first child to exit, and tell
# which one) is a bash feature.
set -eu

HS_DIR=/var/lib/tor/hidden_service
SSHD_PID=
TOR_PID=
NGINX_PID=

# Stop every service still running, and wait for them.
stop_all() {
	kill $SSHD_PID $TOR_PID $NGINX_PID 2> /dev/null || true
	wait || true
}

# docker stop sends SIGTERM to this script (PID 1): pass it on, exit cleanly.
trap 'stop_all; exit 0' TERM INT

# sshd needs its privilege separation directory. On a normal Debian system,
# systemd creates it; there is no systemd in a container.
mkdir -p /run/sshd
chmod 0755 /run/sshd

# Check the three configurations first: a broken file stops the container
# here, with the error in docker logs, instead of a half-working server.
nginx -t -q
/usr/sbin/sshd -t
tor -f /etc/tor/torrc --verify-config > /dev/null

# -D: no daemon fork (the process stays our child, so we can watch it),
# -e: log to stderr, so to docker logs.
/usr/sbin/sshd -D -e &
SSHD_PID=$!
tor -f /etc/tor/torrc &
TOR_PID=$!

# tor writes the .onion address as soon as it has the keys (created on the
# first start, read from the volume afterwards).
i=0
while [ ! -s "$HS_DIR/hostname" ] && [ "$i" -lt 30 ]; do
	sleep 1
	i=$((i + 1))
done
if [ ! -s "$HS_DIR/hostname" ]; then
	echo "ft_onion: tor did not create $HS_DIR/hostname" >&2
	stop_all
	exit 1
fi
echo "ft_onion: address is http://$(cat "$HS_DIR/hostname")"

nginx -g 'daemon off;' &
NGINX_PID=$!

# Wait for the first service to stop, whichever it is.
set +e
wait -n -p DEAD_PID $SSHD_PID $TOR_PID $NGINX_PID
STATUS=$?
case "$DEAD_PID" in
	"$SSHD_PID") NAME=sshd ;;
	"$TOR_PID") NAME=tor ;;
	*) NAME=nginx ;;
esac
echo "ft_onion: $NAME stopped (status $STATUS), stopping the container" >&2
stop_all
exit 1
