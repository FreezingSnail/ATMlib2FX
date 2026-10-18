# Build the supported finite-v1 compact FX converter (ATMlib2FX-hlh.7).
#
#   make -C tools/fx_pack            # builds ../../build/fx-port/pack/fx_pack
#   make -C tools/fx_pack BUILD_DIR=/somewhere
#
# Outputs are generated artifacts and stay out of the source tree (build/ is
# ignored). No network and no external dependencies beyond a C11 compiler.

CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter
BUILD_DIR ?= ../../build/fx-port/pack

FX_PACK := $(BUILD_DIR)/fx_pack
SRCS := fx_pack.c fx_score.c fx_encode.c
HDRS := fx_score.h fx_encode.h

.PHONY: all clean

all: $(FX_PACK)

$(FX_PACK): $(SRCS) $(HDRS)
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ $(SRCS)

clean:
	rm -f $(FX_PACK)
