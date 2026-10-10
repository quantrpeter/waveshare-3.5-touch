import lcd_bus
import machine
from time import sleep, ticks_ms, ticks_diff
import esp
import uctypes
import axs15231b
import lvgl as lv
import task_handler

# OV5640 preview for the Waveshare ESP32-S3-Touch-LCD-3.5B.
#
# The sensor sits on the 24-pin DVP socket and only answers on SCCB (I2C
# address 0x3C) while its XCLK pin is being clocked. This firmware has no
# camera driver, so one frame is pulled through the LCD_CAM DMA block into
# PSRAM and drawn on the LCD. The DMA descriptor has to live in internal RAM.

# Display settings for Waveshare ESP32-S3-Touch-LCD-3.5B (AXS15231B)
#   QSPI D0=1, D1=2, D2=3, D3=4, CLK=5, CS=12, BL=6
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
_LCD_CMD_RASET = 0x2B
_LCD_CMD_RAMWR = 0x2C
_LCD_CMD_RAMWRC = 0x3C
_LCD_QSPI_WRITE_COLOR = 0x32
_DRAW_BUFFER_LINES = 48

# Camera. SCCB shares the board I2C bus. XCLK is GPIO 38.
_I2C_SDA = 8
_I2C_SCL = 7
_XCLK = 38
_XCLK_HZ = 20000000
_PMU_ADDR = 0x34
_CAM_ADDR = 0x3C
_OV5640_ID = 0x5640

# DVP data bus, low bit first. VSYNC and HREF frame the picture.
_DVP = (45, 47, 48, 46, 42, 40, 39, 21)
_VSYNC = 17
_HREF = 18
_PCLK = 41

# One QQVGA YUV422 frame. Only the Y byte is drawn.
_CAM_W = 160
_CAM_H = 120
_FRAME_BYTES = _CAM_W * _CAM_H * 2

# ESP32-S3 LCD_CAM and GDMA. Clock/reset are bit 8 and bit 6 of the second
# peripheral clock and reset registers. Do not write these wholesale.
_SYSTEM = 0x600C0000
_LCD_CAM = 0x60041000
_GDMA = 0x6003F000
_DMA_DESC = 0x3FCEFE00
_CAM_DATA0 = 133
_CAM_PCLK_SIG = 149
_CAM_HREF_SIG = 150
_CAM_VSYNC_SIG = 152

_GPIO_IN = 0x6000403C  # for direct VSYNC read during sync (avoids Pin object)


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


def _pmu_read(i2c, reg):
    i2c.writeto(_PMU_ADDR, bytes([reg]))
    return i2c.readfrom(_PMU_ADDR, 1)[0]


def _sccb_write(i2c, reg, value):
    i2c.writeto(_CAM_ADDR, bytes([(reg >> 8) & 0xFF, reg & 0xFF, value & 0xFF]))


def _sccb_write16(i2c, reg, value):
    _sccb_write(i2c, reg, (value >> 8) & 0xFF)
    _sccb_write(i2c, reg + 1, value & 0xFF)


def _pmu_write(i2c, reg, value):
    i2c.writeto(_PMU_ADDR, bytes([reg, value & 0xFF]))


def _sccb_read(i2c, reg):
    # OV5640 registers are 16-bit addressed.
    i2c.writeto(_CAM_ADDR, bytes([(reg >> 8) & 0xFF, reg & 0xFF]))
    return i2c.readfrom(_CAM_ADDR, 1)[0]


def _start_camera(i2c):
    # AXP2101 ALDO voltage is 0.5 V + n * 0.1 V.
    # Factory comments: ALDO1 is camera DVDD, ALDO4 is camera AVDD.
    print("Setting camera rails...")
    _pmu_write(i2c, 0x92, 13)  # ALDO1 1.8 V
    _pmu_write(i2c, 0x93, 23)  # ALDO2 2.8 V
    _pmu_write(i2c, 0x95, 25)  # ALDO4 3.0 V
    on = _pmu_read(i2c, 0x90)
    _pmu_write(i2c, 0x90, on | 0x01 | 0x02 | 0x08)
    sleep(0.05)

    print("Starting XCLK...")
    pwm = machine.PWM(machine.Pin(_XCLK), freq=_XCLK_HZ, duty_u16=32768)
    print("XCLK", pwm.freq(), "Hz")
    sleep(0.1)

    found = i2c.scan()
    print("I2C scan:", [hex(addr) for addr in found])
    if _CAM_ADDR not in found:
        raise OSError("OV5640 not on I2C (is the camera plugged in?)")

    chip_id = (_sccb_read(i2c, 0x300A) << 8) | _sccb_read(i2c, 0x300B)
    print("OV5640 chip id:", hex(chip_id))
    return chip_id

def _stream_qqvga(i2c):
    # Software reset, then a slow QQVGA YUV422 window. PLL matches the
    # esp32-camera setting used for frames smaller than QVGA.
    print("Resetting sensor...")
    _sccb_write(i2c, 0x3008, 0x82)
    sleep(0.1)
    _sccb_write(i2c, 0x3103, 0x11)
    _sccb_write(i2c, 0x3008, 0x82)
    sleep(0.1)

    _sccb_write(i2c, 0x3039, 0x00)
    _sccb_write(i2c, 0x3034, 0x1A)
    _sccb_write(i2c, 0x3035, 0x11)
    _sccb_write(i2c, 0x3036, 20)
    _sccb_write(i2c, 0x3037, 0x01)
    _sccb_write(i2c, 0x3108, 0x16)
    _sccb_write(i2c, 0x3824, 8)
    _sccb_write(i2c, 0x460C, 0x22)
    _sccb_write(i2c, 0x3103, 0x13)

    # Active window and QQVGA output size.
    _sccb_write16(i2c, 0x3800, 0)
    _sccb_write16(i2c, 0x3802, 0)
    _sccb_write16(i2c, 0x3804, 2623)
    _sccb_write16(i2c, 0x3806, 1951)
    _sccb_write16(i2c, 0x3808, _CAM_W)
    _sccb_write16(i2c, 0x380A, _CAM_H)
    _sccb_write16(i2c, 0x380C, 1896)
    _sccb_write16(i2c, 0x380E, 984)
    _sccb_write16(i2c, 0x3810, 16)
    _sccb_write16(i2c, 0x3812, 6)

    # YUV422, binning, vflip. Format register 0x4300 = 0x30 is YUYV.
    _sccb_write(i2c, 0x4300, 0x30)
    _sccb_write(i2c, 0x501F, 0x00)
    _sccb_write(i2c, 0x3820, 0x47)
    _sccb_write(i2c, 0x3821, 0x01)
    _sccb_write(i2c, 0x4514, 0xBB)
    _sccb_write(i2c, 0x4520, 0x0B)
    _sccb_write(i2c, 0x3814, 0x31)
    _sccb_write(i2c, 0x3815, 0x31)
    # DVP output, PCLK only while HREF is high.
    _sccb_write(i2c, 0x3017, 0xFF)
    _sccb_write(i2c, 0x3018, 0xFF)
    _sccb_write(i2c, 0x300E, 0x58)
    _sccb_write(i2c, 0x4713, 0x03)
    _sccb_write(i2c, 0x3008, 0x02)
    sleep(0.05)

    # Enable auto exposure/gain so a normal scene produces visible brightness.
    _sccb_write(i2c, 0x3503, 0x00)
    sleep(0.15)
    print("Sensor streaming")


def _enable_camera_dma():
    clk = machine.mem32[_SYSTEM + 0x1C]
    rst = machine.mem32[_SYSTEM + 0x24]
    machine.mem32[_SYSTEM + 0x1C] = (clk | (1 << 8) | (1 << 6)) & 0xFFFFFFFF
    rst = machine.mem32[_SYSTEM + 0x24]
    machine.mem32[_SYSTEM + 0x24] = (rst & ~((1 << 8) | (1 << 6))) & 0xFFFFFFFF
    date = machine.mem32[_LCD_CAM + 0xFC] & 0xFFFFFFFF
    print("LCD_CAM date", hex(date))
    if date == 0:
        raise OSError("LCD_CAM clock did not start")

    # Route the camera into LCD_CAM. XCLK stays on PWM; do not also drive it.
    esp.gpio_matrix_in(_PCLK, _CAM_PCLK_SIG, False)
    esp.gpio_matrix_in(_HREF, _CAM_HREF_SIG, False)
    esp.gpio_matrix_in(_VSYNC, _CAM_VSYNC_SIG, False)
    bit = 0
    for gpio in _DVP:
        esp.gpio_matrix_in(gpio, _CAM_DATA0 + bit, False)
        bit += 1


def _grab(buf):
    # Each DMA node can hold 4095 bytes, and the node itself must sit in
    # internal RAM. The picture buffer can stay in PSRAM. The next pointer
    # is a full address; only the link register uses the low 20 bits.
    size = len(buf)
    baddr = uctypes.addressof(buf)
    nodes = (size + 2047) // 2048
    words = nodes * 3
    saved = bytearray(words * 4)
    si = 0
    while si < words:
        machine.mem32[uctypes.addressof(saved) + si * 4] = machine.mem32[_DMA_DESC + si * 4]
        si += 1

    # Best-effort VSYNC sync using direct GPIO IN reg (reliable even when matrix-routed).
    # We wait for a rising edge so capture starts near top of frame. If no edge seen
    # within timeout we just proceed (DMA will still clock whatever is on the bus).
    t0 = ticks_ms()
    def _vs_high():
        return (machine.mem32[_GPIO_IN] & (1 << _VSYNC)) != 0
    # Wait until VSYNC is low (or timeout)
    while _vs_high() and ticks_diff(ticks_ms(), t0) < 150:
        pass
    # Wait for rising edge (low -> high)
    while (not _vs_high()) and ticks_diff(ticks_ms(), t0) < 400:
        pass
    vs_wait = ticks_diff(ticks_ms(), t0)
    print("vsync sync waited", vs_wait, "ms")

    n = 0
    off = 0
    while off < size:
        addr = _DMA_DESC + n * 12
        take = size - off
        if take > 2048:
            take = 2048
        owner = take | (1 << 31)
        nxt = 0
        if off + take < size:
            nxt = _DMA_DESC + (n + 1) * 12
        else:
            owner |= 1 << 30
        machine.mem32[addr] = owner
        machine.mem32[addr + 4] = baddr + off
        machine.mem32[addr + 8] = nxt
        n += 1
        off += take

    # 8-bit DVP, VSYNC filter on, converter bypassed, EOF at buffer length.
    machine.mem32[_LCD_CAM + 0x04] = 0
    machine.mem32[_LCD_CAM + 0x08] = (size - 1) | (1 << 23)
    machine.mem32[_LCD_CAM + 0x0C] = 0
    machine.mem32[_LCD_CAM + 0x04] = 1 << 4

    machine.mem32[_GDMA + 0x00] = 1
    machine.mem32[_GDMA + 0x00] = 0
    machine.mem32[_GDMA + 0x04] = 12
    machine.mem32[_GDMA + 0x48] = 5
    machine.mem32[_GDMA + 0x14] = 0x3FF
    machine.mem32[_GDMA + 0x20] = (_DMA_DESC & 0xFFFFF) | (1 << 22)
    machine.mem32[_LCD_CAM + 0x08] = (size - 1) | (1 << 23) | (1 << 29)
    machine.mem32[_LCD_CAM + 0x04] = 1 << 4

    start = ticks_ms()
    raw = 0
    while ticks_diff(ticks_ms(), start) < 800:
        raw = machine.mem32[_GDMA + 0x08] & 0xFFFFFFFF
        if raw & 0x02:
            break

    machine.mem32[_GDMA + 0x20] = 1 << 21
    machine.mem32[_LCD_CAM + 0x08] = (size - 1) | (1 << 23)
    filled = 0
    ni = 0
    while ni < n:
        filled += (machine.mem32[_DMA_DESC + ni * 12] >> 12) & 0xFFF
        ni += 1
    si = 0
    while si < words:
        machine.mem32[_DMA_DESC + si * 4] = machine.mem32[uctypes.addressof(saved) + si * 4]
        si += 1

    if raw & 0x02:
        print("grab eof raw=", hex(raw), "filled=", filled)
        return filled

    # Fallback: if no EOF (e.g. sync started at bad phase), try one immediate grab
    # without re-building a full sync wait. Re-arm and start again.
    print("grab no eof, retrying immediate...")
    # re-arm descriptors (owner bits)
    off = 0
    ni = 0
    while off < size:
        addr = _DMA_DESC + ni * 12
        take = size - off
        if take > 2048:
            take = 2048
        owner = take | (1 << 31)
        if off + take >= size:
            owner |= 1 << 30
        machine.mem32[addr] = owner
        machine.mem32[addr + 4] = baddr + off
        # next already set from first build
        ni += 1
        off += take

    machine.mem32[_GDMA + 0x00] = 1
    machine.mem32[_GDMA + 0x00] = 0
    machine.mem32[_GDMA + 0x20] = (_DMA_DESC & 0xFFFFF) | (1 << 22)
    machine.mem32[_LCD_CAM + 0x08] = (size - 1) | (1 << 23) | (1 << 29)
    machine.mem32[_LCD_CAM + 0x04] = 1 << 4

    start = ticks_ms()
    raw = 0
    while ticks_diff(ticks_ms(), start) < 800:
        raw = machine.mem32[_GDMA + 0x08] & 0xFFFFFFFF
        if raw & 0x02:
            break
    machine.mem32[_GDMA + 0x20] = 1 << 21
    machine.mem32[_LCD_CAM + 0x08] = (size - 1) | (1 << 23)
    filled = 0
    ni = 0
    while ni < n:
        filled += (machine.mem32[_DMA_DESC + ni * 12] >> 12) & 0xFFF
        ni += 1
    si = 0
    while si < words:
        machine.mem32[_DMA_DESC + si * 4] = machine.mem32[uctypes.addressof(saved) + si * 4]
        si += 1
    print("grab2 raw=", hex(raw), "filled=", filled)
    if raw & 0x02:
        return filled
    return 0

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

scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x101418), 0)
scrn.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

title = lv.label(scrn)
title.set_text("OV5640")
title.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
title.align(lv.ALIGN.TOP_MID, 0, 8)

status = lv.label(scrn)
status.set_style_text_color(lv.color_hex(0xA0A8B0), 0)
status.align(lv.ALIGN.BOTTOM_MID, 0, -8)

_canvas_buf = bytearray(_CAM_W * _CAM_H * 2)
_frame = bytearray(_FRAME_BYTES)
canvas = lv.canvas(scrn)
canvas.set_buffer(_canvas_buf, _CAM_W, _CAM_H, lv.COLOR_FORMAT.RGB565)
canvas.align(lv.ALIGN.CENTER, 0, 0)
canvas.fill_bg(lv.color_hex(0x202428), lv.OPA.COVER)

print("Opening I2C...")
_i2c = machine.SoftI2C(
    sda=machine.Pin(_I2C_SDA),
    scl=machine.Pin(_I2C_SCL),
    freq=100000,
)

try:
    _chip_id = _start_camera(_i2c)
    if _chip_id != _OV5640_ID:
        raise RuntimeError("chip id " + hex(_chip_id))
    _stream_qqvga(_i2c)
    _enable_camera_dma()
except Exception as exc:
    print("Camera init failed:", exc)
    status.set_text("camera init failed")
    while True:
        lv.task_handler()
        sleep(0.05)

# Prove the canvas is on screen before touching the camera DMA block.
_i = 0
_pixels = _CAM_W * _CAM_H
while _i < _pixels:
    if (_i // _CAM_W) < 40:
        _canvas_buf[_i * 2] = 0x00
        _canvas_buf[_i * 2 + 1] = 0xF8
    elif (_i // _CAM_W) < 80:
        _canvas_buf[_i * 2] = 0xE0
        _canvas_buf[_i * 2 + 1] = 0x07
    else:
        _canvas_buf[_i * 2] = 0x1F
        _canvas_buf[_i * 2 + 1] = 0x00
    _i += 1
canvas.invalidate()
status.set_text("bars")
print("Color bars on canvas")
_t = ticks_ms()
while ticks_diff(ticks_ms(), _t) < 400:
    lv.task_handler()
    sleep(0.02)

print("Grabbing one frame...")
status.set_text("grabbing")
lv.task_handler()
_got = _grab(_frame)
if _got == 0:
    status.set_text("no frame")
    print("No frame")
else:
    # YUYV422: typically Y0,U0,Y1,V0,... so Y is at even indices.
    # Compute stats for diagnostics.
    _nz = 0
    _mn = 255
    _mx = 0
    for _b in _frame:
        if _b < _mn:
            _mn = _b
        if _b > _mx:
            _mx = _b
        if _b != 0xFF and _b != 0x00:
            _nz += 1
    _head = bytes(_frame[:16])
    print("frame bytes=", _got, "min=", hex(_mn), "max=", hex(_mx), "varied=", _nz)
    print("head:", _head)
    _i = 0
    while _i < _pixels:
        _y = _frame[_i * 2]  # even byte = Y for standard YUYV
        _canvas_buf[_i * 2] = (_y >> 3) | ((_y & 0x1C) << 3)
        _canvas_buf[_i * 2 + 1] = (_y & 0xF8) | (_y >> 5)
        _i += 1
    canvas.invalidate()
    lv.task_handler()
    lv.task_handler()
    status.set_text(str(_got) + "B " + str(_nz) + "v")
while True:
    lv.task_handler()
    sleep(0.05)
