# Build the maintained FX data-image packer (ATMlib2FX-hlh.10).
#
#   make -C tools/fx_image            # builds ../../build/fx-port/image/fx_image
#   make -C tools/fx_image BUILD_DIR=/somewhere
#
# Outputs are generated artifacts and stay out of the source tree (build/ is
# ignored). No network and no external dependencies beyond a C11 compiler.

CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra
BUILD_DIR ?= ../../build/fx-port/image

FX_IMAGE := $(BUILD_DIR)/fx_image
SRCS := fx_image.c fx_image_core.c
HDRS := fx_image_core.h

.PHONY: all clean

all: $(FX_IMAGE)

$(FX_IMAGE): $(SRCS) $(HDRS)
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ $(SRCS)

clean:
	rm -f $(FX_IMAGE)
