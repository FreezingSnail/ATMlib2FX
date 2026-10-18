/*
 * atm_fx_stream.h - compiled FX music stream decoder (ATMlib2FX-aoe prototype).
 *
 * A single sequential, pre-expanded, channel-interleaved byte stream is read
 * from FX by foreground code into a small SRAM ring buffer. The timer consumer
 * stages one complete music tick (or a run of silent ticks) from the ring and
 * applies it with the unmodified effect/command core. The runtime pattern and
 * return stacks are not part of this build (ATM_HAS_FX_STREAM == 1).
 *
 * Provisional framing (see tools/fx_compile_stream.c):
 *   0xF5 magic, then records: 0x00 <n> skip, 0x10 end, 0x01..0x0F bitmap.
 *
 * The platform supplies the byte source:
 *   void atm_fx_stream_fetch(uint32_t offset, uint8_t *dst, uint8_t n);
 */
#ifndef ATM_FX_STREAM_H
#define ATM_FX_STREAM_H

#include <stdint.h>

/* Ring buffer and foreground fetch sizes. Provisional; judged by the spike. */
#define ATM_FX_REFILL_BYTES (64)
#define ATM_FX_REFILL_CHUNK (16)

/* Largest staged tick frame (control + length bytes + command bytes). Limited
 * by the converter's max_frame assertion for the converted fixture. */
#define ATM_FX_MAX_FRAME (40)

/* Diagnostics (counters + trace). Off in production-size builds. */
#ifndef ATM_FX_STREAM_DIAG
#define ATM_FX_STREAM_DIAG (0)
#endif

#ifdef __cplusplus
extern "C" {
#endif

struct atm_fx_stream_state {
	uint8_t buf[ATM_FX_REFILL_BYTES];
	uint8_t head;          /* consumer read index (timer)        */
	uint8_t tail;          /* producer write index (foreground)  */
	uint32_t next_offset;  /* next FX stream byte to fetch       */
	uint32_t stream_end;   /* one past the last FX stream byte   */
	uint8_t active;
	uint8_t silent_remaining; /* pending silent ticks from a SKIP record */
#if ATM_FX_STREAM_DIAG
	uint16_t ticks;
	uint16_t underruns;
	uint16_t gap;          /* ticks since last service()         */
	uint16_t max_gap;
	uint16_t serviced;
	uint8_t overflow;      /* staged frame exceeded ATM_FX_MAX_FRAME */
#endif
};

extern struct atm_fx_stream_state atm_fx_stream_state;

/* Platform byte source (implemented by the sketch / host harness). */
void atm_fx_stream_fetch(uint32_t offset, uint8_t *dst, uint8_t n);

/* Start playback of the stream at `offset` (FX-section relative), `length`
 * bytes long. Resets the music channels and consumes immediately. */
void atm_fx_stream_play(uint32_t offset, uint32_t length);

/* Foreground refill. Call when no FX/OLED transaction is in progress. */
void atm_fx_stream_service(void);

/* Stop playback and unregister the timer consumer. */
void atm_fx_stream_stop(void);

/* True while the stream is still being consumed. */
uint8_t atm_fx_stream_is_active(void);

#ifdef __cplusplus
}
#endif

#endif /* ATM_FX_STREAM_H */
