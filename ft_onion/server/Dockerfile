# ft_onion server: nginx + sshd + tor in one Debian container.
FROM debian:trixie-slim

# Login of the SSH user, and its public key (given by the Makefile from
# ssh/id_ed25519.pub; a public key is not a secret).
ARG SSH_USER=vsyutkin
ARG SSH_PUBKEY

RUN apt-get update \
	&& apt-get install -y --no-install-recommends nginx openssh-server tor \
	&& rm -rf /var/lib/apt/lists/*

# Keep only the ed25519 host key (generated at install by openssh-server).
RUN rm -f /etc/ssh/ssh_host_rsa_key* /etc/ssh/ssh_host_ecdsa_key*

# Non-root SSH user. Password field "*": no password can match it, but the
# account is not "locked" ("!"), which sshd would refuse even for key login.
RUN test -n "$SSH_PUBKEY" \
	&& useradd --create-home --shell /bin/bash --password '*' "$SSH_USER" \
	&& install -d -m 0700 -o "$SSH_USER" -g "$SSH_USER" "/home/$SSH_USER/.ssh" \
	&& printf '%s\n' "$SSH_PUBKEY" > "/home/$SSH_USER/.ssh/authorized_keys" \
	&& chown "$SSH_USER:$SSH_USER" "/home/$SSH_USER/.ssh/authorized_keys" \
	&& chmod 0600 "/home/$SSH_USER/.ssh/authorized_keys"

# Hidden service directory, owned by tor's user and private (tor checks
# both). An empty named volume mounted here starts as a copy of it.
RUN install -d -m 0700 -o debian-tor -g debian-tor /var/lib/tor/hidden_service

# The CSP of nginx.conf must allow the exact script of index.html (its
# sha256 hash): a mismatch fails the build here, not silently in a browser.
COPY csp_check.sh index.html nginx.conf /tmp/csp/
RUN sh /tmp/csp/csp_check.sh /tmp/csp/index.html /tmp/csp/nginx.conf \
	&& rm -rf /tmp/csp

COPY nginx.conf /etc/nginx/nginx.conf
COPY sshd_config /etc/ssh/sshd_config
COPY torrc /etc/tor/torrc
COPY index.html /var/www/ft_onion/index.html
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

# No EXPOSE: no port is meant to be reachable from outside the container.
ENTRYPOINT ["/entrypoint.sh"]
