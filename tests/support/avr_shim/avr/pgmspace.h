/*
 * Minimal host shim for <avr/pgmspace.h> used by the C test harnesses.
 * Every host object is already in ordinary memory, so pgm_read_* reduce to
 * direct loads and PROGMEM is empty. This changes no library behavior.
 */
#ifndef ATM_TEST_AVR_PGMSPACE_SHIM_H
#define ATM_TEST_AVR_PGMSPACE_SHIM_H

#include <stdint.h>
#include <string.h>

#define PROGMEM

#define pgm_read_byte(addr)  (*(const uint8_t *)(addr))
#define pgm_read_word(addr)  (*(const uint16_t *)(addr))
#define memcpy_P(dest, src, n) memcpy((dest), (src), (n))

#endif
