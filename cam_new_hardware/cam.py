import lcd_bus
import machine
import micropython
import gc
import array
from time import sleep, ticks_ms, ticks_diff
import axs15231b
import lvgl as lv
import builtins
builtins.lv = lv  # the axs15231 touch driver expects a global `lv`
import task_handler
import i2c
import axs15231

# OV5640 camera demo for Waveshare ESP32-S3-Touch-LCD-3.5B (AXS15231B).
# Live colour preview with touch controls: FREEZE/RESUME, MIRROR, FLIP and an
# effect cycler (colour, gray, thermal, night vision, sepia, negative, mono).
# Non-colour effects map luma through a 256-entry RGB565 lookup table.
# Effects, mirror and flip also apply to a frozen frame.
# Display pins match the other *_new_hardware examples.
# Camera pins match Waveshare Arduino `03_camera_web_server`:
#   XCLK=38  SIOD=8  SIOC=7  VSYNC=17  HREF=18  PCLK=41
#   D0..D7 = 45, 47, 48, 46, 42, 40, 39, 21
# This lvgl_micropython build has no esp32-camera C module, so frames are
# sampled from the DVP pins in viper. RGB565 DVP on this module does not
# emit one PCLK per byte (HREF stays high for ~9781 clocks), so the preview
# captures YUYV at a slowed PCLK and converts it to RGB565 in viper.

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
_LCD_CMD_CASET = 0x2A
_LCD_CMD_RAMWR = 0x2C
_LCD_CMD_RAMWRC = 0x3C
_LCD_QSPI_WRITE_COLOR = 0x32
# Same band size as flippybird / the animation example; full-width
# 240-line strips keep this QSPI panel aligned.
_DRAW_BUFFER_LINES = 240

_I2C_SDA = 8
_I2C_SCL = 7
_PMU_ADDR = 0x34
_TOUCH_I2C_ADDR = 0x3B
_OV5640_ADDR = 0x3C
_XCLK_PIN = 38
_XCLK_FREQ = 10000000
_VSYNC_PIN = 17
_HREF_PIN = 18
_PCLK_PIN = 41
_DATA_PINS = (45, 47, 48, 46, 42, 40, 39, 21)

_CAM_W = 160
_CAM_H = 120
_PREVIEW_W = 320
_PREVIEW_H = 240
_REG_DLY = 0xFFFF


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

    # Match flippybird / displayImage_animation_new_hardware. This panel's
    # QSPI path only stays aligned when each flush is a full-width strip:
    # CASET, then RAMWR for the first strip and RAMWRC to continue downward.
    # Sending RASET or restarting RAMWR mid-screen scrambles the image.
    def _set_memory_location_qspi(x1, y1, x2, y2):
        param_buf = display._param_buf  # NOQA

        param_buf[0] = (x1 >> 8) & 0xFF
        param_buf[1] = x1 & 0xFF
        param_buf[2] = (x2 >> 8) & 0xFF
        param_buf[3] = x2 & 0xFF
        display.set_params(_LCD_CMD_CASET, display._param_mv[:4])

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


_OV5640_INIT = (
    (0x3008, 0x82),
    (_REG_DLY, 10),
    (0x3103, 0x13),
    (0x3008, 0x02),
    (0x3017, 0xFF),
    (0x3018, 0xFF),
    (0x300E, 0x58),
    (0x302C, 0xC3),
    (0x4740, 0x21),
    (0x4713, 0x00),
    (0x3000, 0x20),
    (_REG_DLY, 10),
    (0x3002, 0x1C),
    (0x3004, 0xFF),
    (0x3006, 0xC3),
    (0x5000, 0xA7),
    (0x5001, 0xA3),
    (0x370C, 0x02),
    (0x3634, 0x40),
    (0x3A02, 0x03),
    (0x3A03, 0xD8),
    (0x3A08, 0x01),
    (0x3A09, 0x27),
    (0x3A0A, 0x00),
    (0x3A0B, 0xF6),
    (0x3A0D, 0x04),
    (0x3A0E, 0x03),
    (0x3A0F, 0x30),
    (0x3A10, 0x28),
    (0x3A11, 0x60),
    (0x3A13, 0x43),
    (0x3A14, 0x03),
    (0x3A15, 0xD8),
    (0x3A18, 0x00),
    (0x3A19, 0xF8),
    (0x4001, 0x02),
    (0x4004, 0x02),
    (0x5180, 0xFF),
    (0x5181, 0xF2),
    (0x5182, 0x00),
    (0x5183, 0x14),
    (0x5184, 0x25),
    (0x5185, 0x24),
    (0x5186, 0x09),
    (0x5187, 0x09),
    (0x5188, 0x09),
    (0x5189, 0x75),
    (0x518A, 0x54),
    (0x518B, 0xE0),
    (0x518C, 0xB2),
    (0x518D, 0x42),
    (0x518E, 0x3D),
    (0x518F, 0x56),
    (0x5190, 0x46),
    (0x5191, 0xF8),
    (0x5192, 0x04),
    (0x5193, 0x70),
    (0x5194, 0xF0),
    (0x5195, 0xF0),
    (0x5196, 0x03),
    (0x5197, 0x01),
    (0x5198, 0x04),
    (0x5199, 0x12),
    (0x519A, 0x04),
    (0x519B, 0x00),
    (0x519C, 0x06),
    (0x519D, 0x82),
    (0x519E, 0x38),
    (0x5480, 0x01),
    (0x5481, 0x00),
    (0x5482, 0x1E),
    (0x5483, 0x3B),
    (0x5484, 0x58),
    (0x5485, 0x66),
    (0x5486, 0x71),
    (0x5487, 0x7D),
    (0x5488, 0x83),
    (0x5489, 0x8F),
    (0x548A, 0x98),
    (0x548B, 0xA6),
    (0x548C, 0xB8),
    (0x548D, 0xCA),
    (0x548E, 0xD7),
    (0x548F, 0xE3),
    (0x5490, 0x1D),
    (0x5580, 0x06),
    (0x5583, 0x40),
    (0x5584, 0x10),
    (0x5586, 0x20),
    (0x5587, 0x00),
    (0x5588, 0x00),
    (0x5589, 0x10),
    (0x558A, 0x00),
    (0x558B, 0xF8),
    (0x501D, 0x40),
    # YUV422 (YUYV) on DVP: 2 bytes per pixel, converted to RGB565 in viper.
    # RGB565 HREF is not one byte per PCLK on this module.
    (0x501F, 0x00),
    (0x4300, 0x30),
    (0x3820, 0x41),
    (0x3821, 0x01),
    (0x4514, 0xAA),
    (0x4520, 0x0B),
    (0x3212, 0x00),
    (0x3800, 0x00),
    (0x3801, 0x00),
    (0x3802, 0x00),
    (0x3803, 0x00),
    (0x3804, 0x0A),
    (0x3805, 0x3F),
    (0x3806, 0x07),
    (0x3807, 0x9F),
    (0x3808, 0x00),
    (0x3809, 0xA0),
    (0x380A, 0x00),
    (0x380B, 0x78),
    # HTS 4120 (2x the usual 2060) so each output row of 320 YUYV bytes
    # fits through the ~250 kHz PCLK before the next row is ready.
    (0x380C, 0x10),
    (0x380D, 0x18),
    # VTS 984 = 1968 / 2, as esp32-camera uses for 2x2 binned 4:3 modes.
    # A short VTS (0xB0) cuts the array readout and AEC, leaving a black image.
    (0x380E, 0x03),
    (0x380F, 0xD8),
    (0x3810, 0x00),
    (0x3811, 0x10),
    (0x3812, 0x00),
    (0x3813, 0x08),
    (0x3814, 0x31),
    (0x3815, 0x31),
    (0x3212, 0x10),
    (0x3212, 0xA0),
    # ~250 kHz PCLK so viper can sample every Y8 byte.
    (0x3039, 0x00),
    (0x3034, 0x18),
    (0x3035, 0x41),
    (0x3036, 50),
    (0x3037, 0x01),
    (0x3108, 0x36),
    (0x3824, 31),
    (0x460C, 0x22),
    (0x3103, 0x13),
    (0x3008, 0x02),
    (0x503D, 0x00),
)


class OV5640:
    def __init__(self, i2c, addr=_OV5640_ADDR):
        self._i2c = i2c
        self._addr = addr

    def _write(self, reg, value):
        self._i2c.writeto_mem(self._addr, reg, bytes([value & 0xFF]), addrsize=16)

    def _read(self, reg):
        return self._i2c.readfrom_mem(self._addr, reg, 1, addrsize=16)[0]

    def pid(self):
        return (self._read(0x300A) << 8) | self._read(0x300B)

    def init(self):
        for reg, value in _OV5640_INIT:
            if reg == _REG_DLY:
                sleep(value / 1000)
            else:
                self._write(reg, value)


@micropython.viper
def _href_gaps(out: ptr32, n: int):
    # Record how long HREF stays low before each of the next `n` lines,
    # in loop iterations. The loop matches the sync loop in _capture_frame.
    gpio_in = ptr32(0x6000403C)
    href = 1 << 18
    while gpio_in[0] & href:
        pass
    i = 0
    while i < n:
        c = 0
        while (gpio_in[0] & href) == 0:
            c += 1
            if c > 50000000:
                return
        out[i] = c
        while gpio_in[0] & href:
            pass
        i += 1


@micropython.viper
def _capture_frame(buf: ptr8, width: int, height: int, gap_threshold: int) -> int:
    # `width` is bytes per line (2 per pixel for YUYV).
    gpio_in = ptr32(0x6000403C)
    gpio_in1 = ptr32(0x60004040)
    href = 1 << 18
    pclk = 1 << 9
    # VSYNC never pulses at this slowed PCLK, so find the frame start from
    # HREF instead: vertical blanking is a low gap several lines long.
    # The first HREF after it is a short dummy line, which the row loop
    # below skips by waiting for that line to end.
    t = 20000000
    while gpio_in[0] & href:
        t -= 1
        if t == 0:
            return -1
    tries = 0
    while True:
        c = 0
        while (gpio_in[0] & href) == 0:
            c += 1
            if c > 50000000:
                return -2
        if c > gap_threshold:
            break
        t = 20000000
        while gpio_in[0] & href:
            t -= 1
            if t == 0:
                return -1
        tries += 1
        if tries > 1000:
            return -3
    lastx = 0
    y = 0
    while y < height:
        t = 20000000
        while gpio_in[0] & href:
            t -= 1
            if t == 0:
                return -(10 + y)
        t = 20000000
        while (gpio_in[0] & href) == 0:
            t -= 1
            if t == 0:
                return -(110 + y)
        x = 0
        dest = y * width
        while gpio_in[0] & href:
            t = 40000
            while gpio_in1[0] & pclk:
                t -= 1
                if t == 0:
                    return -200
            t = 40000
            while (gpio_in1[0] & pclk) == 0:
                t -= 1
                if t == 0:
                    return -201
            if x < width:
                in0 = gpio_in[0]
                in1 = gpio_in1[0]
                b = (in1 >> 13) & 1
                b |= ((in1 >> 15) & 1) << 1
                b |= ((in1 >> 16) & 1) << 2
                b |= ((in1 >> 14) & 1) << 3
                b |= ((in1 >> 10) & 1) << 4
                b |= ((in1 >> 8) & 1) << 5
                b |= ((in1 >> 7) & 1) << 6
                b |= ((in0 >> 21) & 1) << 7
                buf[dest + x] = b
            x += 1
        lastx = x
        y += 1
    # HREF often has a dummy extra PCLK; a couple short is still a usable line.
    if lastx < width - 2:
        return -300 - lastx
    return y


@micropython.viper
def _yuyv_to_rgb565_2x(src: ptr8, dst: ptr16, lut: ptr16, width: int, height: int, flags: int):
    # Each source pixel becomes a 2x2 block of RGB565.
    # flags: 1 = mirror, 2 = vertical flip, 4 = true colour (else lut[Y]).
    mirror = flags & 1
    vflip = flags & 2
    color = flags & 4
    out_w = width * 2
    y = 0
    while y < height:
        src_row = y * width * 2
        oy = height - 1 - y if vflip else y
        dst_row0 = (oy * 2) * out_w
        dst_row1 = dst_row0 + out_w
        x = 0
        while x < width:
            base = src_row + x * 2
            y0 = src[base]
            y1 = src[base + 2]
            if color:
                u = src[base + 1] - 128
                v = src[base + 3] - 128
                rd = (359 * v) >> 8
                gd = (88 * u + 183 * v) >> 8
                bd = (454 * u) >> 8
            k = 0
            while k < 2:
                lum = y1 if k else y0
                if color:
                    r = lum + rd
                    g = lum - gd
                    b = lum + bd
                    if r < 0:
                        r = 0
                    elif r > 255:
                        r = 255
                    if g < 0:
                        g = 0
                    elif g > 255:
                        g = 255
                    if b < 0:
                        b = 0
                    elif b > 255:
                        b = 255
                    pix = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                else:
                    pix = lut[lum]
                ox = x + k
                if mirror:
                    ox = width - 1 - ox
                d = ox * 2
                dst[dst_row0 + d] = pix
                dst[dst_row0 + d + 1] = pix
                dst[dst_row1 + d] = pix
                dst[dst_row1 + d + 1] = pix
                k += 1
            x += 2
        y += 1


def _rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _lerp(a, b, t, span):
    return a + (b - a) * t // span


def _thermal(v):
    # black -> blue -> magenta -> red -> yellow -> white
    stops = (
        (0, (0, 0, 0)),
        (64, (0, 0, 160)),
        (112, (160, 0, 160)),
        (160, (230, 30, 0)),
        (210, (255, 210, 0)),
        (255, (255, 255, 255)),
    )
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if v <= p1:
            t = v - p0
            span = p1 - p0
            return (
                _lerp(c0[0], c1[0], t, span),
                _lerp(c0[1], c1[1], t, span),
                _lerp(c0[2], c1[2], t, span),
            )
    return stops[-1][1]


def _build_lut(fn):
    lut = bytearray(512)
    mv = memoryview(lut)
    for v in range(256):
        r, g, b = fn(v)
        pix = _rgb565(min(r, 255), min(g, 255), min(b, 255))
        mv[v * 2] = pix & 0xFF
        mv[v * 2 + 1] = pix >> 8
    return lut


# A None palette means true colour from the YUYV chroma.
_EFFECTS = (
    ("Color", None),
    ("Gray", lambda v: (v, v, v)),
    ("Thermal", _thermal),
    ("Night", lambda v: (v // 6, v, v // 5)),
    ("Sepia", lambda v: (v * 112 // 100 + 20, v * 92 // 100 + 10, v * 70 // 100)),
    ("Negative", lambda v: (255 - v, 255 - v, 255 - v)),
    ("Mono", lambda v: (255, 255, 255) if v >= 110 else (0, 0, 0)),
)


def _enable_camera_power(i2c):
    try:
        chip = i2c.readfrom_mem(_PMU_ADDR, 0x03, 1)[0]
    except OSError:
        print("AXP2101 not found")
        return
    if chip != 0x4A:
        print("Unexpected PMU id", hex(chip))
        return
    i2c.writeto_mem(_PMU_ADDR, 0x92, bytes([(3300 - 500) // 100]))
    i2c.writeto_mem(_PMU_ADDR, 0x96, bytes([(1500 - 500) // 100]))
    i2c.writeto_mem(_PMU_ADDR, 0x97, bytes([(2800 - 500) // 100]))
    onoff = i2c.readfrom_mem(_PMU_ADDR, 0x90, 1)[0]
    i2c.writeto_mem(_PMU_ADDR, 0x90, bytes([onoff | 0x31]))
    print("AXP2101 camera rails enabled")


def _start_xclk():
    xclk = machine.PWM(machine.Pin(_XCLK_PIN), freq=_XCLK_FREQ, duty_u16=32768)
    print("XCLK", xclk.freq(), "Hz on GPIO", _XCLK_PIN)
    return xclk


def _prepare_dvp_pins():
    for pin in (_VSYNC_PIN, _HREF_PIN, _PCLK_PIN) + _DATA_PINS:
        machine.Pin(pin, machine.Pin.IN)


def _frame_gap_threshold():
    # Normal line gaps are all about the same; blanking is ~6x longer.
    gaps = array.array("i", [0] * 130)
    _href_gaps(gaps, len(gaps))
    normal = sorted(gaps)[len(gaps) // 2]
    if normal <= 0:
        raise OSError("no HREF from camera")
    return normal * 3


print("Forcing backlight GPIO high...")
_bl_pin = machine.Pin(_BL, machine.Pin.OUT)
_bl_pin.value(1)
sleep(0.05)

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
# TaskHandler polls touch. Pause LVGL's own refresh timer so a button press
# cannot flush a partial rectangle; the main loop repaints the full screen.
_refr_timer = lv.display_get_default().get_refr_timer()
if _refr_timer:
    _refr_timer.pause()


def _refresh():
    scrn.invalidate()
    lv.refr_now(None)


scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x101418), 0)
scrn.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

title = lv.label(scrn)
title.set_text("OV5640 Camera Demo")
title.set_style_text_color(lv.color_hex(0x8BE9FD), 0)
title.set_style_text_font(lv.font_montserrat_16, 0)
title.align(lv.ALIGN.TOP_MID, 0, 12)

status = lv.label(scrn)
status.set_style_text_color(lv.color_hex(0xA0A8B0), 0)
status.align(lv.ALIGN.TOP_MID, 0, 290)
status.set_text("starting")

_refresh()

print("Opening I2C bus...")
_i2c = machine.SoftI2C(
    sda=machine.Pin(_I2C_SDA),
    scl=machine.Pin(_I2C_SCL),
    freq=100000,
)
_enable_camera_power(_i2c)
_xclk = _start_xclk()
sleep(0.05)
print("I2C scan:", [hex(addr) for addr in _i2c.scan()])

cam_error = None
sensor = OV5640(_i2c)
try:
    if _OV5640_ADDR not in _i2c.scan():
        raise OSError("OV5640 0x3C not on I2C (is XCLK running?)")
    pid = sensor.pid()
    print("OV5640 PID", hex(pid))
    if pid != 0x5640:
        raise OSError("unexpected camera PID %s" % hex(pid))
    print("Initializing OV5640...")
    sensor.init()
    _prepare_dvp_pins()
    sleep(0.3)
    _gap_threshold = _frame_gap_threshold()
    print("OV5640 ready, frame gap threshold", _gap_threshold)
except Exception as exc:
    cam_error = exc
    print("Camera init failed:", exc)

if cam_error is not None:
    status.set_text("camera init failed")
    err = lv.label(scrn)
    err.set_style_text_color(lv.color_hex(0xFF5555), 0)
    err.set_text(str(cam_error))
    err.set_long_mode(lv.label.LONG.WRAP)
    err.set_width(280)
    err.align(lv.ALIGN.CENTER, 0, 0)
    _refresh()
    print("Display stays up. Camera error:", cam_error)
    while True:
        lv.task_handler()
        sleep(0.1)

# Touch is opened only after the OV5640 has been configured over SoftI2C,
# because the hardware I2C bus takes over the same SDA/SCL pins.
print("Initializing AXS15231 touch...")
i2c_bus = i2c.I2C.Bus(host=0, scl=_I2C_SCL, sda=_I2C_SDA)
touch_dev = i2c.I2C.Device(bus=i2c_bus, dev_id=_TOUCH_I2C_ADDR, reg_bits=axs15231.BITS)
indev = axs15231.AXS15231(touch_dev)
print("Touch driver initialized")

print("Building palettes...")
_gray_lut = _build_lut(lambda v: (v, v, v))
_luts = [_build_lut(fn) if fn else _gray_lut for _, fn in _EFFECTS]
gc.collect()

_yuyv = bytearray(_CAM_W * 2 * _CAM_H)
_rgb = bytearray(_PREVIEW_W * _PREVIEW_H * 2)
_img_dsc = lv.image_dsc_t(
    {
        "header": {
            "magic": lv.IMAGE_HEADER_MAGIC,
            "cf": lv.COLOR_FORMAT.RGB565,
            "w": _PREVIEW_W,
            "h": _PREVIEW_H,
            "stride": _PREVIEW_W * 2,
        },
        "data_size": len(_rgb),
        "data": _rgb,
    }
)

cam_img = lv.image(scrn)
cam_img.set_src(_img_dsc)
cam_img.align(lv.ALIGN.TOP_MID, 0, 40)

fps_label = lv.label(scrn)
fps_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
fps_label.set_style_bg_color(lv.color_hex(0x000000), 0)
fps_label.set_style_bg_opa(160, 0)
fps_label.set_style_pad_all(3, 0)
fps_label.set_text("-- fps")
fps_label.align(lv.ALIGN.TOP_RIGHT, -6, 46)

_state = {"effect": 0, "mirror": False, "flip": True, "frozen": False, "dirty": False}
_COLOR_ON = lv.color_hex(0x2E8B57)
_COLOR_OFF = lv.color_hex(0x2A3440)


def _make_button(text, x, y, w, cb):
    btn = lv.button(scrn)
    btn.set_size(w, 64)
    btn.set_pos(x, y)
    btn.set_style_bg_color(_COLOR_OFF, 0)
    btn.set_style_radius(10, 0)
    lbl = lv.label(btn)
    lbl.set_text(text)
    lbl.set_style_text_font(lv.font_montserrat_16, 0)
    lbl.center()
    # PRESSED rather than CLICKED: a capture blocks the loop, so a short tap
    # may not be seen both pressed and released.
    btn.add_event_cb(cb, lv.EVENT.PRESSED, None)
    return btn, lbl


def _on_freeze(event):
    _state["frozen"] = not _state["frozen"]
    _update_controls()


def _on_mirror(event):
    _state["mirror"] = not _state["mirror"]
    _update_controls()


def _on_flip(event):
    _state["flip"] = not _state["flip"]
    _update_controls()


def _on_effect(event):
    _state["effect"] = (_state["effect"] + 1) % len(_EFFECTS)
    _update_controls()


freeze_btn, freeze_lbl = _make_button("FREEZE", 12, 320, 92, _on_freeze)
mirror_btn, mirror_lbl = _make_button("MIRROR", 114, 320, 92, _on_mirror)
flip_btn, flip_lbl = _make_button("FLIP", 216, 320, 92, _on_flip)
effect_btn, effect_lbl = _make_button("", 12, 396, 296, _on_effect)


def _update_controls():
    frozen = _state["frozen"]
    freeze_lbl.set_text("RESUME" if frozen else "FREEZE")
    freeze_btn.set_style_bg_color(lv.color_hex(0xB03A2E) if frozen else _COLOR_OFF, 0)
    mirror_btn.set_style_bg_color(_COLOR_ON if _state["mirror"] else _COLOR_OFF, 0)
    flip_btn.set_style_bg_color(_COLOR_ON if _state["flip"] else _COLOR_OFF, 0)
    effect_lbl.set_text("Effect: %s  >" % _EFFECTS[_state["effect"]][0])
    _state["dirty"] = True


def _render():
    effect = _state["effect"]
    flags = 1 if _state["mirror"] else 0
    if _state["flip"]:
        flags |= 2
    if _EFFECTS[effect][1] is None:
        flags |= 4
    _yuyv_to_rgb565_2x(_yuyv, _rgb, _luts[effect], _CAM_W, _CAM_H, flags)
    cam_img.set_src(_img_dsc)


_update_controls()
status.set_text("%dx%d YUYV -> %dx%d" % (_CAM_W, _CAM_H, _PREVIEW_W, _PREVIEW_H))
_refresh()
print("Preview running. Ctrl-C to stop.")

_frames = 0
_fps_t0 = ticks_ms()
_fps_n = 0
while True:
    # Poll touch before spending time on a capture.
    lv.task_handler()

    if _state["frozen"]:
        if _state["dirty"]:
            _state["dirty"] = False
            _render()  # re-render the held frame with the new effect/mirror
            fps_label.set_text("paused")
            _refresh()
        sleep(0.03)
        continue

    rc = _capture_frame(_yuyv, _CAM_W * 2, _CAM_H, _gap_threshold)
    if rc != _CAM_H:
        print("capture", rc)
        status.set_text("capture error %s" % rc)
    else:
        _render()
        _frames += 1
        _fps_n += 1
        now = ticks_ms()
        dt = ticks_diff(now, _fps_t0)
        if dt >= 1000:
            fps_text = "%d.%d fps" % (_fps_n * 1000 // dt, (_fps_n * 10000 // dt) % 10)
            fps_label.set_text(fps_text)
            print("frame", _frames, fps_text)
            _fps_t0 = now
            _fps_n = 0
    _state["dirty"] = False
    # Full-screen refresh: this QSPI panel misplaces partial dirty regions.
    _refresh()
