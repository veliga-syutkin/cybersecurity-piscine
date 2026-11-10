# ############################################################################ #
#						# PROJECT SOURCES DECLARATIONS #					   #
# ############################################################################ #

#Only .rs files (cargo finds them itself: listed for make's dependencies)
SRC_DIR =	./src/
SRCS =	main.rs \
		options.rs \
		errors.rs \
		key.rs \
		storage.rs \
		totp.rs

FILES =	$(addprefix $(SRC_DIR), $(SRCS)) Cargo.toml Cargo.lock

SRC_BONUS_DIR =	./src_bonus/
SRCS_BONUS =	main.rs \
				options_bonus.rs \
				qr.rs \
				gui.rs

FILES_BONUS =	$(FILES) $(addprefix $(SRC_BONUS_DIR), $(SRCS_BONUS))

# ############################################################################ #
#						# PROJECT END_FILES DECLARATIONS #					   #
# ############################################################################ #

NAME =	ft_otp

PROGRAM =	./$(NAME)

NAME_BONUS =	ft_otp_bonus

# Where cargo builds: the binaries are copied from here to ./
BUILD =	./target/release/$(NAME)
BUILD_BONUS =	./target/release/$(NAME_BONUS)

KEY_FILE =	ft_otp.key
QR_FILE =	ft_otp_qr.svg

# ############################################################################ #
#						# PROJECT MACROS #									   #
# ############################################################################ #

# On the school machines CARGO_HOME is /opt/rust, read-only for students:
# cargo cannot write its cache there. Forced (not ?=) into the project,
# git-ignored and removed by fclean: nothing is left in the evaluator's home.
export CARGO_HOME :=	$(CURDIR)/.cargo-home

CARGO =	cargo
CARGO_FLAGS =	--release --locked
# The bonus crates (qrcode, eframe) are an optional cargo feature: only here
CARGO_BONUS_FLAGS =	$(CARGO_FLAGS) --features bonus

RM =	rm -f
RM_DIR =	rm -rf

# ############################################################################ #
#						# PROJECT RULES DECLARATIONS #						   #
# ############################################################################ #

all: $(NAME)

$(NAME): $(FILES)
	$(CARGO) build $(CARGO_FLAGS) --bin $(NAME)
	cp $(BUILD) $(NAME)

clean:
	$(CARGO) clean

fclean: clean
	$(RM) $(NAME) $(NAME_BONUS) $(KEY_FILE) $(QR_FILE)
	$(RM_DIR) $(CARGO_HOME)

re: fclean all

.PHONY: all clean fclean re

# ############################################################################ #
#						# PROJECT BONUS #									   #

# A second binary: ./ft_otp is left as it is
bonus: $(NAME_BONUS)

$(NAME_BONUS): $(FILES_BONUS)
	$(CARGO) build $(CARGO_BONUS_FLAGS) --bin $(NAME_BONUS)
	cp $(BUILD_BONUS) $(NAME_BONUS)

.PHONY: bonus

# ############################################################################ #
#						# PROJECT CUSTOM #									   #

clear:
	clear

# RFC 4226 / 6238 vectors and key checks (see the tests in src/)
test:
	$(CARGO) test $(CARGO_FLAGS) --bin $(NAME)

# Same tests run again inside ft_otp_bonus, plus base32 / URI ones
test_bonus:
	$(CARGO) test $(CARGO_BONUS_FLAGS) --bin $(NAME_BONUS)

# Our code next to oathtool's, from the same key.hex, in the same 30 s
compare: all
	@test -f key.hex || (echo "compare: put a 64-hex key in key.hex" && false)
	$(PROGRAM) -g key.hex
	@echo "ft_otp:   $$($(PROGRAM) -k $(KEY_FILE))"
	@echo "oathtool: $$(oathtool --totp $$(cat key.hex))"

# The whole show, in one go, on a NEW random key each time:
#	1) the subject's example: a bad key refused, a 64-hex key saved, a code
#	2) the same code from oathtool (skipped if oathtool is missing)
#	3) bonus: the QR code of that key, to scan with a phone
# The key comes from /dev/urandom through od (no openssl needed). The demo
# files are removed at the end; ft_otp.key stays, for -k or --gui after.
DEMO_BAD =	demo_bad.txt
DEMO_KEY =	demo_key.hex

demo: all bonus
	@echo "\n== 1. Subject example ==\n"
	printf "NEVER GONNA GIVE YOU UP" > $(DEMO_BAD)
	@echo "$(PROGRAM) -g $(DEMO_BAD)"
	@$(PROGRAM) -g $(DEMO_BAD) || true
	od -An -tx1 -N32 /dev/urandom | tr -d ' \n' > $(DEMO_KEY)
	cat $(DEMO_KEY) | wc -c
	$(PROGRAM) -g $(DEMO_KEY)
	$(PROGRAM) -k $(KEY_FILE)
	@echo "\n== 2. Same key, same 30 s window: oathtool ==\n"
	@if command -v oathtool >/dev/null; then \
		echo "ft_otp:   $$($(PROGRAM) -k $(KEY_FILE))"; \
		echo "oathtool: $$(oathtool --totp $$(cat $(DEMO_KEY)))"; \
	else echo "oathtool not installed: skipped"; fi
	@echo "\n== 3. Bonus: QR code of $(KEY_FILE), scan it ==\n"
	./$(NAME_BONUS) -q $(KEY_FILE)
	@echo "Phone, ft_otp and oathtool show: $$($(PROGRAM) -k $(KEY_FILE))"
	@$(RM) $(DEMO_BAD) $(DEMO_KEY)

.PHONY: clear test test_bonus compare demo
