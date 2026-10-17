/*
 * Minimal host shim for <avr/pgmspace.h>.
 *
 * The reference trace harness (research/fx/footprint_baseline/trace) compiles the
 * *unmodified* library sources on the host to obtain deterministic tick-level
 * expected values. On AVR, PROGMEM data cannot be read with ordinary pointers;
 * on the host every object is already in ordinary memory, so the pgm_read_*
 * helpers reduce to direct loads and PROGMEM is empty.
 *
 * This shim changes no library behavior: it only provides the flash-access
 * primitives the library already uses.
 */
#ifndef ATM_FOOTPRINT_AVR_PGMSPACE_SHIM_H
#define ATM_FOOTPRINT_AVR_PGMSPACE_SHIM_H

#include <stdint.h>
#include <string.h>

#define PROGMEM

#define pgm_read_byte(addr)  (*(const uint8_t *)(addr))
#define pgm_read_word(addr)  (*(const uint16_t *)(addr))
#define memcpy_P(dest, src, n) memcpy((dest), (src), (n))

#endif
