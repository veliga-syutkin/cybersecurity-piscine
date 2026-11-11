# ft_onion: a static page and SSH, published as a Tor hidden service.
# Everything runs in Docker; no port is published on the host, and no host
# directory is mounted in a container (only a named volume, for tor's keys).

SSH_USER	= vsyutkin
SSH_KEY		= ssh/id_ed25519

SERVER_IMG	= ft_onion-server
CLIENT_IMG	= ft_onion-client
SERVER		= ft_onion_server
CLIENT		= ft_onion_client
KEYS_VOLUME	= ft_onion_keys
HS_HOSTNAME	= /var/lib/tor/hidden_service/hostname

# Wait until both tor instances (server and client) are connected to the
# Tor network. Usually a few seconds; several minutes on a slow network.
WAIT_TOR	= for c in $(SERVER) $(CLIENT); do i=0; \
			until docker logs $$c 2>&1 | grep -q 'Bootstrapped 100'; do \
			[ $$i -eq 0 ] && echo "waiting for tor in $$c..."; \
			[ $$i -ge 300 ] && { echo "$$c: tor not connected after 300 s" >&2; exit 1; }; \
			sleep 1; i=$$((i + 1)); done; done
# The .onion address, read from the server.
ADDRESS		= $$(docker exec $(SERVER) cat $(HS_HOSTNAME))

all: up

# SSH key pair, created once on the host (owned by you, git-ignored).
$(SSH_KEY):
	mkdir -p ssh
	ssh-keygen -q -t ed25519 -N '' -C 'ft_onion' -f $(SSH_KEY)

build: $(SSH_KEY)
	docker build -t $(SERVER_IMG) --build-arg SSH_USER=$(SSH_USER) \
		--build-arg SSH_PUBKEY="$$(cat $(SSH_KEY).pub)" server
	docker build -t $(CLIENT_IMG) client

# True if container $(1) is running from the current build of image $(2).
UP_TO_DATE	= [ "$$(docker inspect -f '{{.State.Running}} {{.Image}}' $(1) 2> /dev/null)" \
			= "true $$(docker image inspect -f '{{.Id}}' $(2))" ]

# Start both containers. A container already running from the current image
# is left alone: restarting the server makes it unreachable for a couple of
# minutes (see README). No -p: nothing is reachable from the host's network;
# the server is only reachable through Tor.
up: build
	docker volume create $(KEYS_VOLUME) > /dev/null
	@if $(call UP_TO_DATE,$(SERVER),$(SERVER_IMG)); then \
		echo "$(SERVER): already running this image, not restarted"; \
	else \
		docker rm -f $(SERVER) > /dev/null 2>&1 || true; \
		echo "starting $(SERVER)"; \
		docker run -d --name $(SERVER) \
			--mount type=volume,src=$(KEYS_VOLUME),dst=/var/lib/tor/hidden_service \
			$(SERVER_IMG) > /dev/null; \
	fi
	@if $(call UP_TO_DATE,$(CLIENT),$(CLIENT_IMG)); then \
		echo "$(CLIENT): already running this image, not restarted"; \
	else \
		docker rm -f $(CLIENT) > /dev/null 2>&1 || true; \
		echo "starting $(CLIENT)"; \
		docker run -d --name $(CLIENT) $(CLIENT_IMG) > /dev/null; \
	fi
	@$(MAKE) --no-print-directory address

# Print the .onion address (waits for tor to create it).
address:
	@i=0; until docker exec $(SERVER) test -s $(HS_HOSTNAME) 2> /dev/null; do \
		[ $$i -ge 30 ] && { echo 'no address: see make logs' >&2; exit 1; }; \
		sleep 1; i=$$((i + 1)); done
	@echo "http://$(ADDRESS)"

# Fetch the page through Tor. The first request after a start can take a
# minute: the service must publish its descriptor on the network first.
curl:
	@$(WAIT_TOR)
	docker exec $(CLIENT) curl -sS --socks5-hostname 127.0.0.1:9050 \
		--max-time 60 --retry 5 --retry-delay 5 --retry-all-errors \
		-D - http://$(ADDRESS)/

# Open an SSH session on port 4242 through Tor. The private key is sent
# through stdin into the client container (no file shared with the host).
ssh: $(SSH_KEY)
	@$(WAIT_TOR)
	@docker exec -i $(CLIENT) sh -c 'umask 077; mkdir -p /root/.ssh; \
		cat > /root/.ssh/id_ed25519' < $(SSH_KEY)
	docker exec -it $(CLIENT) ssh -p 4242 $(SSH_USER)@$(ADDRESS)

logs:
	docker logs -f $(SERVER)

down:
	docker rm -f $(SERVER) $(CLIENT) > /dev/null 2>&1 || true

clean: down
	docker rmi -f $(SERVER_IMG) $(CLIENT_IMG) > /dev/null 2>&1 || true

# Also deletes the hidden service keys (next start: a new .onion address)
# and the SSH key pair.
fclean: clean
	docker volume rm -f $(KEYS_VOLUME) > /dev/null 2>&1 || true
	rm -rf ssh

re: fclean all

.PHONY: all build up address curl ssh logs down clean fclean re
