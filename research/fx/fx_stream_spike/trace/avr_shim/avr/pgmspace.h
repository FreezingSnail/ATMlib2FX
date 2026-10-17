/*
 * Minimal host shim for <avr/pgmspace.h> (ATMlib2FX-aoe FX stream trace).
 *
 * The host trace harness compiles the library core on the host; every object is
 * already in ordinary memory, so pgm_read_* reduce to direct loads and PROGMEM
 * is empty. Mirrors research/fx/footprint_baseline/trace/avr_shim so the two
 * harnesses use identical semantics; changes no library behavior.
 */
#ifndef ATM_FX_STREAM_AVR_PGMSPACE_SHIM_H
#define ATM_FX_STREAM_AVR_PGMSPACE_SHIM_H

#include <stdint.h>
#include <string.h>

#define PROGMEM

#define pgm_read_byte(addr)  (*(const uint8_t *)(addr))
#define pgm_read_word(addr)  (*(const uint16_t *)(addr))
#define memcpy_P(dest, src, n) memcpy((dest), (src), (n))

#endif
