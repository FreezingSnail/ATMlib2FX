/*
 * loops_trace_common.h - shared tick-CSV schema for the ATMlib2FX-hlh.8 loop
 * equivalence harnesses.
 *
 * The schema is byte-for-byte the ATMlib2FX-hlh.1 reference trace schema so the
 * unmodified original engine and the compact loop decoder can be diffed after
 * dropping the traversal-only columns. Include this after the library core
 * (src/atm_synth.c) has been included and PROGMEM/OSC_* are visible.
 *
 * Columns removed by the equivalence check (traversal-only in the compact
 * backend, which resolves traversal offline):
 *   cN_ps     per-channel pattern-stack index
 *   cN_delay  per-channel command delay
 *   cN_lp     per-channel loop target (kept as engine-internal traversal state)
 */
#ifndef LOOPS_TRACE_COMMON_H
#define LOOPS_TRACE_COMMON_H

static void loops_print_channel_fields(const struct osc_params *osc,
				       const struct atm_channel_state *ch)
{
#if ATM_HAS_FX_STREAM_BACKEND
	/* Traversal state is removed by the compact backend; the columns are
	 * dropped by the equivalence check. */
	printf(",0x%04x,%u,%u,%u,%u,%u,0x%04x,%u",
		(unsigned)osc->phase_increment, (unsigned)osc->mod, (unsigned)osc->vol,
		(unsigned)ch->note, (unsigned)ch->vol, (unsigned)ch->mod,
		(unsigned)ch->delay, 0u);
#else
	printf(",0x%04x,%u,%u,%u,%u,%u,0x%04x,%u",
		(unsigned)osc->phase_increment, (unsigned)osc->mod, (unsigned)osc->vol,
		(unsigned)ch->note, (unsigned)ch->vol, (unsigned)ch->mod,
		(unsigned)ch->delay, (unsigned)ch->pstack_index);
#endif
#if ATM_HAS_FX_SLIDE
	printf(",%d,%u,%u", (int)ch->vf_slide.slide_amount,
		(unsigned)ch->vf_slide.slide_config, (unsigned)ch->vf_slide.slide_count);
#else
	printf(",-,-,-");
#endif
#if ATM_HAS_FX_NOTE_RETRIG
	printf(",%u,%u,%u", (unsigned)ch->arpNotes, (unsigned)ch->arpTiming, (unsigned)ch->arpCount);
#else
	printf(",-,-,-");
#endif
#if ATM_HAS_FX_NOISE_RETRIG
	printf(",%u,%u", (unsigned)ch->reConfig, (unsigned)ch->reCount);
#else
	printf(",-,-");
#endif
#if ATM_HAS_FX_LFO
	printf(",%u,%u,%u", (unsigned)ch->treviDepth, (unsigned)ch->treviConfig, (unsigned)ch->treviCount);
#else
	printf(",-,-,-");
#endif
#if ATM_HAS_FX_GLISSANDO
	printf(",%d,%u", (int)ch->glisConfig, (unsigned)ch->glisCount);
#else
	printf(",-,-");
#endif
#if ATM_HAS_FX_LOOP
#if ATM_HAS_FX_STREAM_BACKEND
	printf(",0");
#else
	printf(",%u", (unsigned)ch->loop_pattern_index);
#endif
#else
	printf(",-");
#endif
}

static void loops_print_header(void)
{
	printf("event,tick,base,tempo,active");
	for (uint8_t c = 0; c < OSC_CH_COUNT; c++) {
		printf(",c%u_inc,c%u_mod,c%u_vol,c%u_note,c%u_cvol,c%u_cmod,c%u_delay,c%u_ps"
		       ",c%u_sla,c%u_slc,c%u_slk,c%u_arp,c%u_art,c%u_arc,c%u_rec,c%u_recn"
		       ",c%u_trd,c%u_trt,c%u_trc,c%u_glc,c%u_glk,c%u_lp",
			c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c);
	}
	printf("\n");
}

#endif /* LOOPS_TRACE_COMMON_H */
