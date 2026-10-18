/*
 * atm_fx_compact.h - compact, directly consumed FX music stream (ATMlib2FX-hlh.5).
 *
 * Experimental spike candidate, not a production ABI. A single sequential,
 * complete-record byte stream is read from FX by foreground code into a small
 * SRAM ring. Each record is a "due pass": the commands that run at the current
 * music tick for a bitmap of channels, plus one shared gap field giving the
 * number of effect-only ticks until the next pass. Per-channel delay bytecode
 * and the runtime pattern/return stacks are removed (see tools/fx_compact_spike/
 * fx_compile_compact.c); live effect/oscillator state is unchanged.
 *
 * The timer consumer preflights the whole record (length + structure) before
 * mutating any effect or channel state, applies it directly from the ring, and
 * only then advances the consumer head. It never touches SPI.
 *
 * The platform supplies the byte source:
 *   void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n);
 */
#ifndef ATM_FX_COMPACT_H
#define ATM_FX_COMPACT_H

#include <stdint.h>

/* Music ring size (power of two). 32-byte target; judged by the spike. */
#define ATM_FX_COMPACT_RING (32)
/* Largest foreground FX fetch per transaction (direct into the ring). */
#define ATM_FX_COMPACT_CHUNK (16)

/* Diagnostics (counters + trace). Off in production-size builds. */
#ifndef ATM_FX_COMPACT_DIAG
#define ATM_FX_COMPACT_DIAG (0)
#endif

#if (ATM_FX_COMPACT_RING & (ATM_FX_COMPACT_RING - 1)) != 0
#error "ATM_FX_COMPACT_RING must be a power of two"
#endif
#if ATM_FX_COMPACT_RING > 256
#error "ATM_FX_COMPACT_RING must fit a uint8_t index"
#endif

#ifdef __cplusplus
extern "C" {
#endif

struct atm_fx_compact_state {
	uint8_t buf[ATM_FX_COMPACT_RING];
	uint8_t head;          /* consumer read index (timer)       */
	uint8_t tail;          /* producer write index (foreground) */
	uint32_t next_offset;  /* next FX stream byte to fetch      */
	uint32_t stream_end;   /* one past the last FX stream byte   */
	uint8_t active;
	uint16_t gap;          /* effect-only ticks until the next pass */
	uint8_t error;         /* sticky 1=format 2=oversize (0 = none) */
#if ATM_FX_COMPACT_DIAG
	uint16_t ticks;
	uint16_t underruns;
	uint16_t service_gap;  /* ticks since last service()        */
	uint16_t max_service_gap;
	uint16_t serviced;
	uint16_t stop_tick;
	uint8_t max_record;    /* largest record consumed            */
	uint8_t window;        /* bytes consumed since last service  */
	uint8_t max_window;    /* largest such window                */
#endif
};

extern struct atm_fx_compact_state atm_fx_compact_state;

/* Platform byte source (implemented by the sketch / host harness). */
void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n);

/* Start playback of the stream at `offset` (FX-section relative), `length`
 * bytes long. Resets the music channels and consumes immediately. */
void atm_fx_compact_play(uint32_t offset, uint32_t length);

/* Foreground refill. Call when no FX/OLED transaction is in progress. */
void atm_fx_compact_service(void);

/* Stop playback and unregister the timer consumer. */
void atm_fx_compact_stop(void);

/* True while the stream is still being consumed. */
uint8_t atm_fx_compact_is_active(void);

#ifdef __cplusplus
}
#endif

#endif /* ATM_FX_COMPACT_H */
