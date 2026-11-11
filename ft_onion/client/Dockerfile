# ft_onion test client: tor + curl + ssh, to reach the hidden service through
# the real Tor network, without installing anything on the host.
FROM debian:trixie-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends tor curl openssh-client netcat-openbsd \
	&& rm -rf /var/lib/apt/lists/*

COPY torrc /etc/tor/torrc
COPY ssh_config /etc/ssh/ssh_config.d/onion.conf

CMD ["tor", "-f", "/etc/tor/torrc"]
