/*
 * absim_audio_harness.cpp - capture the *actual* audio produced by a compiled
 * AVR image running against the local absim emulator core (Ardens source tree),
 * and write it to a WAV file.
 *
 * ATMlib2FX-3ii.2 (bounded faithful WAV preview).
 *
 * Unlike research/fx/footprint_baseline/trace/absim_harness.cpp (which clears
 * core_state.cpu.sound_buffer every millisecond and only reports serial/stack),
 * this harness preserves the emulator's int16 PCM sample stream.
 *
 * Audio facts read from the local Ardens sources (read-only):
 *   - source:   src/absim_sound.hpp  (atmega32u4_t::update_sound)
 *   - format:   int16 PCM, mono
 *   - rate:     F_CPU / SOUND_CYCLES = 16'000'000 / 320 = 50'000 Hz
 *   - neutral:  0 (all-zero samples while no speaker pin is an output)
 *   - enable:   DDRC bits DDC6/DDC7 (the Arduboy speaker pins)
 *   - PWM path: Timer4 OC4A/OC4B compare values (absim src/absim_timer.hpp)
 *
 * The "first music callback" is measured, never inferred: the caller supplies
 * the *instruction index* of the original engine's tick handler
 * (`osc_tick_handler`, located with avr-nm and divided by two); a non-step
 * program-counter breakpoint pauses the emulator exactly on its first entry,
 * and the current cycle count and sample-buffer length are recorded.
 *
 * This is a host diagnostic. It contributes no AVR bytes and never modifies the
 * Ardens tree.
 *
 * Usage:
 *   absim_audio_harness <rom.elf|rom.hex> <ms> <wav_out> [tick_instr_index_hex]
 *
 * stdout: one JSON object with the capture metadata.
 * stderr: human diagnostics.
 */

#include <absim.hpp>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

namespace
{
    constexpr uint32_t kSoundCycles = 320;      // absim src/absim.hpp
    constexpr int16_t  kSoundGain   = 2000;     // absim src/absim.hpp
    constexpr uint32_t kCpuHz       = 16000000; // ATmega32u4 @ 16 MHz
    constexpr uint32_t kSampleRate  = kCpuHz / kSoundCycles; // 50000

    void put_u16(std::vector<uint8_t>& v, uint16_t x)
    {
        v.push_back(uint8_t(x & 0xff));
        v.push_back(uint8_t((x >> 8) & 0xff));
    }
    void put_u32(std::vector<uint8_t>& v, uint32_t x)
    {
        v.push_back(uint8_t(x & 0xff));
        v.push_back(uint8_t((x >> 8) & 0xff));
        v.push_back(uint8_t((x >> 16) & 0xff));
        v.push_back(uint8_t((x >> 24) & 0xff));
    }

    bool write_wav(const char* path, std::vector<int16_t> const& samples)
    {
        std::vector<uint8_t> hdr;
        hdr.reserve(44);
        auto tag = [&](char const* s) { for (int i = 0; i < 4; ++i) hdr.push_back(uint8_t(s[i])); };
        const uint32_t data_bytes = uint32_t(samples.size()) * 2u;

        tag("RIFF");
        put_u32(hdr, 36u + data_bytes);
        tag("WAVE");
        tag("fmt ");
        put_u32(hdr, 16u);                       // PCM fmt chunk size
        put_u16(hdr, 1u);                        // PCM
        put_u16(hdr, 1u);                        // mono
        put_u32(hdr, kSampleRate);
        put_u32(hdr, kSampleRate * 2u);          // byte rate
        put_u16(hdr, 2u);                        // block align
        put_u16(hdr, 16u);                       // bits per sample
        tag("data");
        put_u32(hdr, data_bytes);

        std::ofstream of(path, std::ios::out | std::ios::binary | std::ios::trunc);
        if (!of) return false;
        of.write(reinterpret_cast<char const*>(hdr.data()), std::streamsize(hdr.size()));
        if (!samples.empty())
            of.write(reinterpret_cast<char const*>(samples.data()),
                     std::streamsize(samples.size() * sizeof(int16_t)));
        return bool(of);
    }
}

int main(int argc, char** argv)
{
    if (argc < 4)
    {
        std::fprintf(stderr,
            "usage: %s <rom.elf|rom.hex> <ms> <wav_out> [tick_instr_index_hex]\n", argv[0]);
        return 2;
    }

    const char* rom = argv[1];
    long ms = std::atol(argv[2]);
    const char* wav_out = argv[3];
    bool have_tick = (argc > 4) && std::strlen(argv[4]) > 0;
    uint32_t tick_instr = have_tick
        ? uint32_t(std::strtoul(argv[4], nullptr, 0)) : 0u;

    if (ms <= 0) { std::fprintf(stderr, "invalid ms\n"); return 2; }

    auto a = std::make_unique<absim::arduboy_t>();

    std::ifstream f(rom, std::ios::in | std::ios::binary);
    if (!f) { std::fprintf(stderr, "could not open %s\n", rom); return 1; }
    std::string err = a->load_file(rom, f);
    if (!err.empty()) { std::fprintf(stderr, "load_file: %s\n", err.c_str()); return 1; }

    a->program_state.cfg.display_type = absim::display_t::type_t::SSD1306;
    a->program_state.cfg.usb_bus_state = absim::USB_BUS_CONNECTED;
    a->program_state.cfg.bootloader = std::getenv("ABSIM_BOOTLOADER") != nullptr;
    a->program_state.cfg.boot_to_menu = false;

    a->reset();

    auto& cpu = a->core_state.cpu;

    // Simulate all Arduboy buttons released (active-low).
    cpu.data[absim::reg::addr::PINB] = absim::reg::bit::PINB::PINB4;
    cpu.data[absim::reg::addr::PINE] = absim::reg::bit::PINE::PINE6;
    cpu.data[absim::reg::addr::PINF] =
        absim::reg::bit::PINF::PINF7 |
        absim::reg::bit::PINF::PINF6 |
        absim::reg::bit::PINF::PINF5 |
        absim::reg::bit::PINF::PINF4;

    bool tick_breakpoint_armed = false;
    if (have_tick && tick_instr < a->debugger_state.breakpoints.size())
    {
        a->debugger_state.allow_nonstep_breakpoints = true;
        a->debugger_state.breakpoints.set(tick_instr);
        tick_breakpoint_armed = true;
    }

    uint64_t first_callback_cycle = 0;
    size_t   first_callback_sample = 0;
    bool     first_callback_found = false;

    std::vector<int16_t> samples;
    samples.reserve(size_t(ms) * (kSampleRate / 1000u) + 1024u);

    const uint64_t first_cycle = cpu.cycle_count;

    for (long i = 0; i < ms; ++i)
    {
        a->advance(1'000'000'000ull); // 1 ms
        if (tick_breakpoint_armed && !first_callback_found && a->debugger_state.paused)
        {
            first_callback_cycle = cpu.cycle_count;
            // sound_buffer only holds samples produced since the previous drain;
            // add the already-drained prefix so the offset is relative to sample 0.
            first_callback_sample = samples.size() + cpu.sound_buffer.size();
            first_callback_found = true;
            a->debugger_state.breakpoints.reset(tick_instr);
            a->debugger_state.paused = false;
        }
        else if (a->debugger_state.paused)
        {
            a->debugger_state.paused = false; // never leave the core stuck
        }
        if (!cpu.sound_buffer.empty())
        {
            samples.insert(samples.end(), cpu.sound_buffer.begin(), cpu.sound_buffer.end());
            cpu.sound_buffer.clear();
        }
    }

    // Flush any residual buffered samples.
    if (!cpu.sound_buffer.empty())
    {
        samples.insert(samples.end(), cpu.sound_buffer.begin(), cpu.sound_buffer.end());
        cpu.sound_buffer.clear();
    }

    int16_t min_s = 0, max_s = 0;
    size_t nonzero = 0;
    size_t first_nonzero = samples.size();
    for (size_t i = 0; i < samples.size(); ++i)
    {
        int16_t s = samples[i];
        if (s < min_s) min_s = s;
        if (s > max_s) max_s = s;
        if (s != 0) { ++nonzero; if (first_nonzero == samples.size()) first_nonzero = i; }
    }

    bool ok = write_wav(wav_out, samples);
    if (!ok) { std::fprintf(stderr, "could not write %s\n", wav_out); return 1; }

    std::fprintf(stderr,
        "cycles=%llu samples=%zu sound_enabled=%u first_callback_found=%d\n",
        (unsigned long long)(cpu.cycle_count - first_cycle),
        samples.size(), (unsigned)cpu.sound_enabled, (int)first_callback_found);
    std::fprintf(stderr, "wrote %s (%zu samples)\n", wav_out, samples.size());

    std::printf(
        "{\"cycles\": %llu, \"sample_rate\": %u, \"bit_depth\": 16, \"channels\": 1, "
        "\"samples\": %zu, \"sound_enabled\": %u, \"sound_gain\": %d, "
        "\"tick_breakpoint_armed\": %s, \"first_callback_found\": %s, "
        "\"first_callback_cycle\": %llu, \"first_callback_sample\": %zu, "
        "\"first_nonzero_sample\": %s, \"nonzero_samples\": %zu, "
        "\"min_sample\": %d, \"max_sample\": %d, \"wav\": \"%s\"}\n",
        (unsigned long long)(cpu.cycle_count - first_cycle), kSampleRate,
        samples.size(), (unsigned)cpu.sound_enabled, (int)kSoundGain,
        tick_breakpoint_armed ? "true" : "false",
        first_callback_found ? "true" : "false",
        (unsigned long long)first_callback_cycle, first_callback_sample,
        (first_nonzero == samples.size()) ? "null"
            : std::to_string(first_nonzero).c_str(),
        nonzero, (int)min_s, (int)max_s, wav_out);
    return 0;
}
