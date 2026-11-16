# Display firmware

ESP32 firmware for the ESP32-2432S028R display board ("CYD"), the instrument's sole I2C master. It
decides what is displayed; the controllers own timing and hardware state
([architecture](../../docs/architecture.md#ownership)).

**Version 0.1: the I2C path only.** It contains the dekatron controller client, status polling and
the SCPI host interface over USB serial. There is no UI yet: the backlight and the RGB LED are held
off. It is not bench-tested yet (`tools/display_i2c_test.py`, bring-up step 4).

## Build and flash

```
pio run -d firmware/display
pio run -d firmware/display -t upload --upload-port COMx
```

The platform is pinned to `espressif32@7.1.3` (Arduino core 2.0.17), as in nanovolt-divider. Core
logging is compiled out, because it would land in the SCPI response stream. The firmware's own
unsolicited lines start with `# `.

## I2C

* The bus is SDA = IO27 and SCL = IO18, on the module's SPI connector, at 100 kHz. The pull-ups are
  on the dekatron board ([hardware.md, Display harness](../../docs/hardware.md#display-harness)).
* IO18 is also the microSD clock. The card is held deselected, with its command line idle.
* **The dekatron client** ([`src/dekatron_client.h`](src/dekatron_client.h)) uses the contract in
  [i2c_protocol.md](../../docs/i2c_protocol.md#dekatron-controller) and the shared header
  [`firmware/common/dekatron_protocol.h`](../common/dekatron_protocol.h).
  * **Every write is confirmed.** The client reads status, writes the frame, and polls status until
    `cmd_seq` moves on (up to 50 ms). The command's result is then `last_error`.
  * **Bus failures are reported separately.** A missing ACK, a short read, or a status block that is
    not the dekatron's protocol 2 is `bus`. A write that never shows in `cmd_seq` is `timeout`.
  * **Status is read every 100 ms.** That keeps the controller's 5 s master-loss timer fed while the
    tube is lit, and gives the master the recovery counters to trend.

## Host interface (SCPI)

USB serial at 115200 baud, one program message per line. The parser is nanovolt-divider's:
* `;` separates commands, and a leading `:` is optional.
* Headers work in long or short form, in any case.
* Errors go to the queue (`SYST:ERR?`), never to the response stream.

The spellings follow the drafts in [host_interface.md](../../docs/host_interface.md). Values out of
range are sent on to the controller, which rejects them (`range`); nothing is clamped. Only a number
that cannot fit its field at all is refused locally (-222).

| Command | Does |
|---|---|
| `*IDN?` | `UND,Universal Nixie Display,<MAC>,<version>` |
| `SYST:ERR?` | Next queued error. Controller results come back as `-200,"Execution error;dekatron <error>"`; a bus failure as `-240,"Hardware error;dekatron I2C"` or `...;dekatron no confirmation"` |
| `DEK:LIGHt`, `DEK:DARK`, `DEK:HOME`, `DEK:STOP`, `DEK:CLEar`, `DEK:EXERcise`, `DEK:PING` | As the ops |
| `DEK:POSition k[,SHORt\|FWD\|REV]` | `MOVE_TO` |
| `DEK:STEP n` | `MOVE_RELATIVE` |
| `DEK:ROTate r` | `ROTATE`, in steps/s with decimals |
| `DEK:MOTion rate,accel` | `SET_MOTION` |
| `DEK:EFFect SWING,centre,amp,period_s` / `BOUNCE,a,b,rate` / `SPIN,start,end,accel,turns` | Local animations |
| `DEK:WEDGe a,b[,rate]` / `DEK:EYE centre,half_width[,rate]` / `DEK:GAUGe v` | In cathodes, 0.01 resolution. The rate defaults to 2000 steps/s |
| `DEK:IDXcheck open_ms,limit_ms` | `SET_INDEX_CHECK` |
| `DEK:STATus?` | The decoded status block as `key=value` fields, named as on the controller's console |
| `DIAG:I2C?` | Bus counters since boot |
| `DIAG:DEK:RAW? "hex"` | Sends any frame and returns the controller's verdict, e.g. `bad_len` (error-path tests) |
| `DIAG:DEK:POLL ON\|OFF` | Stops the status polling, to test master loss |
