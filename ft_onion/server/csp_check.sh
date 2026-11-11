#!/bin/sh
# Build-time check: the Content-Security-Policy in nginx.conf must allow the
# exact <script> of index.html, through its sha256 hash. Any change to the
# script changes the hash; without this check, the browser would silently
# block the demo. Run by the Dockerfile: a mismatch fails the build and
# prints the value to put in nginx.conf.
#
# The hash covers the text between <script> and </script>, so both tags must
# stand alone on their own line, without indentation.
set -eu

HTML=${1:-index.html}
CONF=${2:-nginx.conf}

# Script text = the newline right after <script>, then every line up to
# </script> (each with its newline).
HEX=$( { printf '\n'; sed -n '/^<script>$/,/^<\/script>$/p' "$HTML" | sed '1d;$d'; } \
	| sha256sum | cut -c1-64)
# hex -> raw bytes -> base64 (coreutils printf understands \xHH).
HASH=$(env printf "$(echo "$HEX" | sed 's/../\\x&/g')" | base64)

if grep -q "'sha256-$HASH'" "$CONF"; then
	echo "csp_check: script hash OK (sha256-$HASH)"
else
	echo "csp_check: nginx.conf does not allow the script of $HTML." >&2
	echo "csp_check: expected script-src 'sha256-$HASH'" >&2
	exit 1
fi
