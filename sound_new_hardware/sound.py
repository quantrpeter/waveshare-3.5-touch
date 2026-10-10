import lcd_bus
import machine
from time import sleep
import axs15231b
import lvgl as lv
import task_handler

# Speaker demo for Waveshare ESP32-S3-Touch-LCD-3.5B.
# Display pins match the other *_new_hardware examples.
# Audio pins match Waveshare Arduino `04_es8311_example`:
#   ES8311 I2C 0x18 on SDA=8 SCL=7
#   I2S BCLK=13 LRCK=15 DOUT=16 (ESP32 -> codec DAC)
# This lvgl_micropython build's machine.I2S has no mck argument and leaves
# GPIO 44 idle, so the codec takes its master clock from BCLK.
# The onboard amp has no GPIO enable (BSP uses GPIO_NUM_NC).

_WIDTH = 320
_HEIGHT = 480
_QSPI_D0 = 1
_QSPI_D1 = 2
_QSPI_D2 = 3
_QSPI_D3 = 4
_QSPI_CLK = 5
_HOST = 1
_LCD_CS = 12
_BL = 6
_LCD_FREQ = 40000000
_I2C_SDA = 8
_I2C_SCL = 7
_LCD_CMD_CASET = 0x2A
_LCD_CMD_RASET = 0x2B
_LCD_CMD_RAMWR = 0x2C
_LCD_CMD_RAMWRC = 0x3C
_LCD_QSPI_WRITE_COLOR = 0x32
_DRAW_BUFFER_LINES = 48

_ES8311_ADDR = 0x18
_SAMPLE_RATE = 16000
_VOICE_VOLUME = 70  # 0-100, same scale as the Waveshare example
_I2S_BCLK = 13
_I2S_LRCK = 15
_I2S_DOUT = 16

# C major scale, one beat each, then a rest. Repeated by the main loop.
_NOTES = (
    ("C4", 262),
    ("D4", 294),
    ("E4", 330),
    ("F4", 349),
    ("G4", 392),
    ("A4", 440),
    ("B4", 494),
    ("C5", 523),
    ("rest", 0),
)


def _qspi_color_cmd(cmd):
    cmd &= 0xFF
    cmd <<= 8
    cmd |= _LCD_QSPI_WRITE_COLOR << 24
    return cmd


def _install_axs15231b_qspi_workarounds(display):
    if not isinstance(display._data_bus, lcd_bus.SPIBus):
        return

    if display._data_bus.get_lane_count() != 4:
        return

    # Both CASET and RASET must be sent for every flush, otherwise partial
    # redraws land in the wrong place and the screen appears frozen.
    def _set_memory_location_qspi(x1, y1, x2, y2):
        param_buf = display._param_buf  # NOQA

        param_buf[0] = (x1 >> 8) & 0xFF
        param_buf[1] = x1 & 0xFF
        param_buf[2] = (x2 >> 8) & 0xFF
        param_buf[3] = x2 & 0xFF
        display.set_params(_LCD_CMD_CASET, display._param_mv[:4])

        param_buf[0] = (y1 >> 8) & 0xFF
        param_buf[1] = y1 & 0xFF
        param_buf[2] = (y2 >> 8) & 0xFF
        param_buf[3] = y2 & 0xFF
        display.set_params(_LCD_CMD_RASET, display._param_mv[:4])

        if y1 == 0:
            return _qspi_color_cmd(_LCD_CMD_RAMWR)

        return _qspi_color_cmd(_LCD_CMD_RAMWRC)

    display._set_memory_location = _set_memory_location_qspi


def _allocate_draw_buffers(display_bus, width, lines, color_space):
    buf_size = width * lines * lv.color_format_get_size(color_space)
    print("Allocating draw buffer:", width, "x", lines, "=", buf_size, "bytes")

    for flags, label in (
        (lcd_bus.MEMORY_SPIRAM | lcd_bus.MEMORY_DMA, "SPIRAM|DMA"),
        (lcd_bus.MEMORY_SPIRAM, "SPIRAM"),
        (lcd_bus.MEMORY_INTERNAL | lcd_bus.MEMORY_DMA, "INTERNAL|DMA"),
        (lcd_bus.MEMORY_INTERNAL, "INTERNAL"),
    ):
        try:
            buf1 = display_bus.allocate_framebuffer(buf_size, flags)
            print("Framebuffer 1:", label)
        except MemoryError:
            continue

        buf2 = None
        try:
            buf2 = display_bus.allocate_framebuffer(buf_size, flags)
            print("Framebuffer 2:", label)
        except MemoryError:
            print("Second framebuffer unavailable, using single buffering")

        return buf1, buf2

    raise MemoryError("Unable to allocate draw buffers")


class ES8311:
    """Minimal playback init, matching Espressif es8311_init for 16 kHz.

    MCLK is 256 * Fs (4.096 MHz). That row of the official coeff table is
    machine.I2S on this firmware does not drive the MCLK pin, so the codec
    is told to take MCLK from BCLK (reg 0x01 bit 7). 16-bit stereo BCLK is
    32 * Fs = 512 kHz. The matching coeff row is pre_div=1, mult=8x,
    adc/dac div=1, fs single-speed, lrck=32, bclk_div=1"""

    def __init__(self, i2c, addr=_ES8311_ADDR):
        self._i2c = i2c
        self._addr = addr

    def _write(self, reg, value):
        self._i2c.writeto_mem(self._addr, reg, bytes([value & 0xFF]))

    def _read(self, reg):
        return self._i2c.readfrom_mem(self._addr, reg, 1)[0]

    def _rmw(self, reg, mask, value):
        current = self._read(reg)
        self._write(reg, (current & mask) | value)

    def init(self, volume=_VOICE_VOLUME):
        # Reset, then power-on with the serial port in slave mode.
        self._write(0x00, 0x1F)
        sleep(0.02)
        self._write(0x00, 0x00)
        self._write(0x00, 0x80) #. Bit 7 selects BCLK as the MCLK source.
        self._write(0x01, 0xBF)
        # SCLK not inverted. Low 5 bits are rewritten by the divider setup.
        self._rmw(0x06, 0xDF, 0x00)

        # Dividers for MCLK = BCLK = 32 * 16000 = 512 kHz.
        self._rmw(0x02, 0x07, 0x18)  # pre_div=1, pre_multi=8x
        self._write(0x03, 0x10)      # fs_mode=single, adc_osr=0x10
        self._write(0x04, 0x10)      # dac_osr=0x10
        self._write(0x05, 0x00)      # adc_div=1, dac_div=1
        self._rmw(0x06, 0xE0, 0x00)  # bclk_div=1 -> (1 - 1)
        self._rmw(0x07, 0xC0, 0x00)  # lrck high = 0
        self._write(0x08, 0x1F)      # lrck low = 31, divider = 32
        self._rmw(0x07, 0xC0, 0x00)  # lrck high = 0
        self._write(0x08, 0xFF)      # lrck low = 255, divider = 256

        # Slave + 16-bit I2S on both SDP in and SDP out.
        self._rmw(0x00, 0xBF, 0x00)
        self._write(0x09, 0x0C)
        self._write(0x0A, 0x0C)

        self._write(0x0D, 0x01)  # power up analog
        self._write(0x0E, 0x02)  # analog PGA + ADC modulator
        self._write(0x12, 0x00)  # power up DAC
        self._write(0x13, 0x10)  # enable HP drive
        self._write(0x1C, 0x6A)  # ADC EQ bypass, cancel DC offset
        self._write(0x37, 0x08)  # bypass DAC equalizer
        self.set_volume(volume)
        self.unmute()

    def set_volume(self, volume):
        if volume <= 0:
            reg = 0
        elif volume >= 100:
            reg = 255
        else:
            reg = (volume * 256 // 100) - 1
        self._write(0x32, reg)

    def unmute(self):
        self._rmw(0x31, 0x9F, 0x00)


def _sine_table(length=256):
    # Quarter-wave of a sine, mirrored. Avoids importing math on-device.
    # Index 64 is the peak and is not stored; quadrants 1 and 3 read it as 32767.
    quarter = (
        0, 804, 1608, 2410, 3212, 4011, 4808, 5602,
        6393, 7179, 7962, 8739, 9512, 10278, 11039, 11793,
        12539, 13279, 14010, 14732, 15446, 16151, 16846, 17530,
        18204, 18868, 19519, 20159, 20787, 21403, 22005, 22594,
        23170, 23731, 24279, 24811, 25329, 25832, 26319, 26790,
        27245, 27683, 28105, 28510, 28898, 29268, 29621, 29956,
        30273, 30571, 30852, 31113, 31356, 31580, 31785, 31971,
        32137, 32285, 32412, 32521, 32609, 32678, 32728, 32757,
    )
    table = bytearray(length * 2)
    span = length // 4
    for i in range(length):
        quadrant = i // span
        pos = i % span
        if quadrant == 0:
            sample = quarter[pos]
        elif quadrant == 1:
            if pos == 0:
                sample = 32767
            else:
                sample = quarter[span - pos]
        elif quadrant == 2:
            sample = -quarter[pos]
        else:
            if pos == 0:
                sample = -32767
            else:
                sample = -quarter[span - pos]
        table[i * 2] = sample & 0xFF
        table[i * 2 + 1] = (sample >> 8) & 0xFF
    return table


def _render_tone(freq, rate, seconds, amplitude=12000):
    """Interleaved stereo int16 frames. freq=0 yields silence."""
    frames = rate * seconds
    buf = bytearray(frames * 4)
    if freq <= 0 or amplitude <= 0:
        return buf

    table = _sine_table()
    phase = 0
    step = (freq * 256 * 65536) // rate
    # 10 ms raised edges so the speaker does not click on each note.
    edge = rate // 100
    if edge < 1:
        edge = 1
    if edge * 2 > frames:
        edge = frames // 2

    for i in range(frames):
        sample = table[((phase >> 16) & 0xFF) * 2]
        sample |= table[((phase >> 16) & 0xFF) * 2 + 1] << 8
        if sample & 0x8000:
            sample -= 0x10000
        gain = amplitude
        if i < edge:
            gain = amplitude * i // edge
        elif i > frames - edge:
            gain = amplitude * (frames - i) // edge
        sample = (sample * gain) // 32767
        lo = sample & 0xFF
        hi = (sample >> 8) & 0xFF
        off = i * 4
        buf[off] = lo
        buf[off + 1] = hi
        buf[off + 2] = lo
        buf[off + 3] = hi
        phase = (phase + step) & 0xFFFFFFFF
    return buf


def _pump(ms):
    end = ms
    while end > 0:
        lv.task_handler()
        step = 20
        if end < step:
            step = end
        sleep(step / 1000)
        end -= step


print("Forcing backlight GPIO high...")
_bl_pin = machine.Pin(_BL, machine.Pin.OUT)
_bl_pin.value(1)
sleep(0.05)

print("Opening I2C bus...")
_i2c = machine.SoftI2C(
    sda=machine.Pin(_I2C_SDA),
    scl=machine.Pin(_I2C_SCL),
    freq=400000,
)
_found = _i2c.scan()
print("I2C scan:", [hex(addr) for addr in _found])

print("Initializing SPI bus...")
spi_bus = machine.SPI.Bus(
    host=_HOST,
    mosi=_QSPI_D0,
    miso=_QSPI_D1,
    sck=_QSPI_CLK,
    quad_pins=(_QSPI_D0, _QSPI_D1, _QSPI_D2, _QSPI_D3),
)

print("Initializing display bus...")
display_bus = lcd_bus.SPIBus(
    spi_bus=spi_bus,
    dc=-1,
    cs=_LCD_CS,
    freq=_LCD_FREQ,
    spi_mode=3,
    quad=True,
)

buf1, buf2 = _allocate_draw_buffers(
    display_bus,
    _WIDTH,
    _DRAW_BUFFER_LINES,
    lv.COLOR_FORMAT.RGB565,
)

print("Initializing AXS15231B display...")
display = axs15231b.AXS15231B(
    data_bus=display_bus,
    display_width=_WIDTH,
    display_height=_HEIGHT,
    backlight_pin=None,
    reset_pin=None,
    color_space=lv.COLOR_FORMAT.RGB565,
    rgb565_byte_swap=True,
    frame_buffer1=buf1,
    frame_buffer2=buf2,
)
_install_axs15231b_qspi_workarounds(display)

_bl_pin.value(1)
print("Display ready")

th = task_handler.TaskHandler()

scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x101418), 0)
scrn.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

title = lv.label(scrn)
title.set_text("ES8311")
title.set_style_text_color(lv.color_hex(0x8BE9FD), 0)
title.align(lv.ALIGN.TOP_MID, 0, 70)

note_label = lv.label(scrn)
note_label.set_text("--")
note_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
note_label.align(lv.ALIGN.CENTER, 0, -10)

status = lv.label(scrn)
status.set_style_text_color(lv.color_hex(0xA0A8B0), 0)
status.align(lv.ALIGN.BOTTOM_MID, 0, -70)
status.set_text("starting")

lv.task_handler()
lv.refr_now(None)

codec = None
i2s = None
audio_error = None

try:
    if _ES8311_ADDR not in _found:
        raise OSError("ES8311 0x18 not on I2C")
    print("Initializing ES8311...")
    codec = ES8311(_i2c)
    codec.init(_VOICE_VOLUME)
    print("ES8311 ready, volume", _VOICE_VOLUME)
except Exception as exc:
    audio_error = exc
    print("ES8311 init failed:", exc)

if audio_error is None:
    try:
        # No mck=: this port hard-wires the MCLK GPIO unused.
        print("Initializing I2S...")
        i2s = machine.I2S(
            0,
            sck=machine.Pin(_I2S_BCLK),
            ws=machine.Pin(_I2S_LRCK),
            sd=machine.Pin(_I2S_DOUT),
            mode=machine.I2S.TX,
            bits=16,
            format=machine.I2S.STEREO,
            rate=_SAMPLE_RATE,
            ibuf=8000,
        )
        print("I2S ready")
    except Exception as exc:
        audio_error = exc
        print("I2S init failed:", exc)

if audio_error is not None:
    status.set_text("audio init failed")
    note_label.set_text("!")
    print("Display stays up. Audio error:", audio_error)
    while True:
        lv.task_handler()
        sleep(0.1)

status.set_text("C major  " + str(_SAMPLE_RATE) + " Hz")
print("Rendering notes...")
_clips = tuple(
    (name, _render_tone(freq, _SAMPLE_RATE, 1)) for name, freq in _NOTES
)
print("Playing scale. Ctrl-C to stop.")

while True:
    for name, pcm in _clips:
        note_label.set_text(name)
        lv.task_handler()
        lv.refr_now(None)
        print("note", name)
        written = 0
        while written < len(pcm):
            written += i2s.write(pcm[written:])
            lv.task_handler()
        _pump(40)
