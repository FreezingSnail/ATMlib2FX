/*
 * absim_harness.cpp - run an FX data-image sketch against the local absim
 * emulator core (read-only Ardens source tree), with the FX data image loaded
 * (ATMlib2FX-hlh.10).
 *
 * Adapted, unchanged in behaviour, from the retired hlh.5 spike harness.
 * It sets program_state.fxdata before reload_fx() so the emulated
 * W25Q128 holds this lane's stream + bitmap image, then reports captured
 * USB-CDC serial bytes and the emulator stack high-water (min_stack). Host
 * diagnostic only; no AVR bytes are contributed.
 *
 * Usage:
 *   absim_harness <rom.elf|hex> <ms> <bss_end_hex> <fxdata.bin>
 * Env:
 *   EMIT_SERIAL=1   write captured serial bytes to stdout
 *   STOP_ON_SERIAL  stop early once any serial byte has arrived
 */
#include <absim.hpp>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

int main(int argc, char** argv)
{
    if (argc < 5)
    {
        std::fprintf(stderr,
            "usage: %s <rom.elf|rom.hex> <ms> <bss_end_hex> <fxdata.bin>\n", argv[0]);
        return 2;
    }

    const char* rom = argv[1];
    int ms = std::atoi(argv[2]);
    uint32_t bss_end = (uint32_t)std::strtoul(argv[3], nullptr, 0);
    const char* fxdata_path = argv[4];
    bool emit_serial = std::getenv("EMIT_SERIAL") != nullptr;
    bool stop_on_serial = std::getenv("STOP_ON_SERIAL") != nullptr;

    auto a = std::make_unique<absim::arduboy_t>();

    std::ifstream f(rom, std::ios::in | std::ios::binary);
    if (!f)
    {
        std::fprintf(stderr, "could not open %s\n", rom);
        return 1;
    }
    std::string err = a->load_file(rom, f);
    if (!err.empty())
    {
        std::fprintf(stderr, "load_file: %s\n", err.c_str());
        return 1;
    }

    // Load the external FX image. absim's non-cart layout places
    // program_state.fxdata at the top of the 16 MB chip; the sketch is compiled
    // with the matching FX::begin(page). Raw asset bytes, no .arduboy cart.
    {
        std::ifstream fx(fxdata_path, std::ios::in | std::ios::binary);
        if (!fx)
        {
            std::fprintf(stderr, "could not open %s\n", fxdata_path);
            return 1;
        }
        fx.seekg(0, std::ios::end);
        std::streamoff sz = fx.tellg();
        fx.seekg(0, std::ios::beg);
        a->program_state.fxdata.resize((size_t)sz);
        if (sz > 0)
            fx.read(reinterpret_cast<char*>(a->program_state.fxdata.data()), sz);
        a->program_state.fxsave.clear();
        a->reload_fx();
    }

    a->program_state.cfg.display_type = absim::display_t::type_t::SSD1306;
    a->program_state.cfg.usb_bus_state = absim::USB_BUS_CONNECTED;
    a->program_state.cfg.bootloader = std::getenv("ABSIM_BOOTLOADER") != nullptr;
    a->program_state.cfg.boot_to_menu = false;

    a->reset();

    auto& cpu = a->core_state.cpu;

    cpu.data[absim::reg::addr::PINB] = absim::reg::bit::PINB::PINB4;
    cpu.data[absim::reg::addr::PINE] = absim::reg::bit::PINE::PINE6;
    cpu.data[absim::reg::addr::PINF] =
        absim::reg::bit::PINF::PINF7 |
        absim::reg::bit::PINF::PINF6 |
        absim::reg::bit::PINF::PINF5 |
        absim::reg::bit::PINF::PINF4;

    auto& serial = cpu.serial_bytes;
    uint64_t const first_cycle = cpu.cycle_count;

    for (int i = 0; i < ms; ++i)
    {
        a->advance(1'000'000'000ull); // 1 ms
        cpu.sound_buffer.clear();
        if (stop_on_serial && !serial.empty())
            break;
    }

    std::fprintf(stderr,
        "cycles=%llu min_stack=0x%04x stack_check=0x%04x pushed=%d serial_bytes=%zu autobreaks=0x%llx\n",
        (unsigned long long)(cpu.cycle_count - first_cycle),
        (unsigned)cpu.min_stack, (unsigned)cpu.stack_check,
        (int)cpu.pushed_at_least_once, serial.size(),
        (unsigned long long)cpu.autobreaks.to_ullong());
    if (bss_end != 0 && cpu.min_stack != 0xffff)
    {
        uint32_t b = bss_end & 0xffffu;
        std::fprintf(stderr, "bss_end=0x%04x headroom_bytes=%d\n",
            (unsigned)b, (int)(cpu.min_stack - b));
    }

    if (emit_serial)
    {
        std::fwrite(serial.data(), 1, serial.size(), stdout);
        std::fflush(stdout);
    }
    return 0;
}
