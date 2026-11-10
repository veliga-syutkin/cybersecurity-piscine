NAMES   := spider scorpion

PYTHON  ?= python3
VENV    := .venv
VPY     := $(VENV)/bin/python
STAMP   := $(VENV)/.installed

all: $(NAMES)

# Virtual environment + dependencies (rebuilt when requirements.txt changes)
$(STAMP): requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VPY) -m pip install --quiet --upgrade pip
	$(VPY) -m pip install --quiet -r requirements.txt
	@touch $@

# ./spider and ./scorpion: launchers that run <name>_src/launcher_<name>.py
# with the venv's Python, from any working directory.
# The repository root is added to PYTHONPATH so both programs can
# import the shared code from common/.
spider:   spider_src/launcher_spider.py     $(STAMP)
scorpion: scorpion_src/launcher_scorpion.py $(STAMP)

$(NAMES):
	@printf '#!/bin/sh\nd=$$(cd "$$(dirname "$$0")" && pwd)\nPYTHONPATH="$$d$${PYTHONPATH:+:$$PYTHONPATH}" exec "$$d/$(VPY)" "$$d/$<" "$$@"\n' > $@
	@chmod +x $@
	@echo "$@ ready: ./$@"

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf data

fclean: clean
	rm -f $(NAMES)
	rm -rf $(VENV)

re: fclean all

.PHONY: all clean fclean re
