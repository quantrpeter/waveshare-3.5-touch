import lcd_bus
import machine
from time import sleep
import axs15231b
import lvgl as lv
import task_handler
from fs_driver import fs_register

# Display settings for Waveshare ESP32-S3-Touch-LCD-3.5B (AXS15231B)
# Pin mapping from the working ESP-IDF `06_lvgl_image` example:
#   QSPI D0=1, D1=2, D2=3, D3=4, CLK=5, CS=12, BL=6
#   QSPI panel IO uses 32-bit commands and no dedicated D/C GPIO (`dc = -1`)
#   LCD reset via TCA9554 IO expander pin 1 (I2C 0x20, SDA=8, SCL=7)
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
_TCA_ADDR = 0x20
_PMU_ADDR = 0x34
_PMU_CHIP_ID_REG = 0x03
_PMU_EXPECTED_CHIP_ID = 0x4A
_PMU_VBUS_VOL_LIMIT_REG = 0x15
_PMU_VBUS_CUR_LIMIT_REG = 0x16
_PMU_LDO_ONOFF_CTRL0_REG = 0x90
_PMU_BLDO1_VOL_REG = 0x96
_PMU_BLDO2_VOL_REG = 0x97
_LCD_CMD_SLPOUT = 0x11
_LCD_CMD_MADCTL = 0x36
_LCD_CMD_COLMOD = 0x3A
_LCD_CMD_DISPON = 0x29
_LCD_CMD_CASET = 0x2A
_LCD_CMD_RAMWR = 0x2C
_LCD_CMD_RAMWRC = 0x3C
_LCD_QSPI_WRITE_COLOR = 0x32
_DRAW_BUFFER_LINES = 48

print("=== displayImageAndText debug v7 ===")


def _i2c_read8(bus, addr, reg):
    return bus.readfrom_mem(addr, reg, 1)[0]


def _i2c_write8(bus, addr, reg, value):
    bus.writeto_mem(addr, reg, bytes([value & 0xFF]))


def _i2c_update_bits(bus, addr, reg, mask, value):
    current = _i2c_read8(bus, addr, reg)
    updated = (current & ~mask) | (value & mask)
    _i2c_write8(bus, addr, reg, updated)
    return current, updated


def _init_pmu(bus):
    try:
        chip_id = _i2c_read8(bus, _PMU_ADDR, _PMU_CHIP_ID_REG)
        print("PMU chip id:", hex(chip_id))
        if chip_id != _PMU_EXPECTED_CHIP_ID:
            print("Unexpected PMU chip id, skipping PMU rail setup")
            return

        # Match the vendor examples for this board family:
        # BLDO1 = 1.5V, BLDO2 = 2.8V, both enabled.
        _i2c_update_bits(bus, _PMU_ADDR, _PMU_VBUS_VOL_LIMIT_REG, 0x0F, 0x06)
        _i2c_update_bits(bus, _PMU_ADDR, _PMU_VBUS_CUR_LIMIT_REG, 0x07, 0x04)
        _i2c_update_bits(bus, _PMU_ADDR, _PMU_BLDO1_VOL_REG, 0x1F, 0x0A)
        _i2c_update_bits(bus, _PMU_ADDR, _PMU_BLDO2_VOL_REG, 0x1F, 0x17)
        _, ldo_ctrl = _i2c_update_bits(bus, _PMU_ADDR, _PMU_LDO_ONOFF_CTRL0_REG, 0x30, 0x30)

        print(
            "PMU rails set: BLDO1=1.5V BLDO2=2.8V, LDO_ONOFF0=",
            hex(ldo_ctrl),
        )
    except Exception as exc:
        print("PMU setup failed:", exc)


_IDF_06_LVGL_IMAGE_INIT_CMDS = (
    (0xBB, bytes.fromhex("00 00 00 00 00 00 5A A5"), 0),
    (0xA0, bytes.fromhex("C0 10 00 02 00 00 04 3F 20 05 3F 3F 00 00 00 00 00"), 0),
    (
        0xA2,
        bytes.fromhex(
            "30 3C 24 14 D0 20 FF E0 40 19 80 80 80 20 F9 10 "
            "02 FF FF F0 90 01 32 A0 91 E0 20 7F FF 00 5A"
        ),
        0,
    ),
    (
        0xD0,
        bytes.fromhex(
            "E0 40 51 24 08 05 10 01 20 15 42 C2 22 22 AA 03 "
            "10 12 60 14 1E 51 15 00 8A 20 00 03 3A 12"
        ),
        0,
    ),
    (0xA3, bytes.fromhex("A0 06 AA 00 08 02 0A 04 04 04 04 04 04 04 04 04 04 04 04 00 55 55"), 0),
    (
        0xC1,
        bytes.fromhex(
            "31 04 02 02 71 05 24 55 02 00 41 00 53 FF FF FF "
            "4F 52 00 4F 52 00 45 3B 0B 02 0D 00 FF 40"
        ),
        0,
    ),
    (0xC3, bytes.fromhex("00 00 00 50 03 00 00 00 01 80 01"), 0),
    (
        0xC4,
        bytes.fromhex(
            "00 24 33 80 00 EA 64 32 C8 64 C8 32 90 90 11 06 "
            "DC FA 00 00 80 FE 10 10 00 0A 0A 44 50"
        ),
        0,
    ),
    (
        0xC5,
        bytes.fromhex(
            "18 00 00 03 FE 3A 4A 20 30 10 88 DE 0D 08 0F 0F "
            "01 3A 4A 20 10 10 00"
        ),
        0,
    ),
    (0xC6, bytes.fromhex("05 0A 05 0A 00 E0 2E 0B 12 22 12 22 01 03 00 3F 6A 18 C8 22"), 0),
    (0xC7, bytes.fromhex("50 32 28 00 A2 80 8F 00 80 FF 07 11 9C 67 FF 24 0C 0D 0E 0F"), 0),
    (0xC9, bytes.fromhex("33 44 44 01"), 0),
    (
        0xCF,
        bytes.fromhex(
            "2C 1E 88 58 13 18 56 18 1E 68 88 00 65 09 22 C4 "
            "0C 77 22 44 AA 55 08 08 12 A0 08"
        ),
        0,
    ),
    (
        0xD5,
        bytes.fromhex(
            "40 8E 8D 01 35 04 92 74 04 92 74 04 08 6A 04 46 "
            "03 03 03 03 82 01 03 00 E0 51 A1 00 00 00"
        ),
        0,
    ),
    (
        0xD6,
        bytes.fromhex(
            "10 32 54 76 98 BA DC FE 93 00 01 83 07 07 00 07 "
            "07 00 03 03 03 03 03 03 00 84 00 20 01 00"
        ),
        0,
    ),
    (0xD7, bytes.fromhex("03 01 0B 09 0F 0D 1E 1F 18 1D 1F 19 40 8E 04 00 20 A0 1F"), 0),
    (0xD8, bytes.fromhex("02 00 0A 08 0E 0C 1E 1F 18 1D 1F 19"), 0),
    (0xD9, bytes.fromhex("1F 1F 1F 1F 1F 1F 1F 1F 1F 1F 1F 1F"), 0),
    (0xDD, bytes.fromhex("1F 1F 1F 1F 1F 1F 1F 1F 1F 1F 1F 1F"), 0),
    (0xDF, bytes.fromhex("44 73 4B 69 00 0A 02 90"), 0),
    (0xE0, bytes.fromhex("3B 28 10 16 0C 06 11 28 5C 21 0D 35 13 2C 33 28 0D"), 0),
    (0xE1, bytes.fromhex("37 28 10 16 0B 06 11 28 5C 21 0D 35 14 2C 33 28 0F"), 0),
    (0xE2, bytes.fromhex("3B 07 12 18 0E 0D 17 35 44 32 0C 14 14 36 3A 2F 0D"), 0),
    (0xE3, bytes.fromhex("37 07 12 18 0E 0D 17 35 44 32 0C 14 14 36 32 2F 0F"), 0),
    (0xE4, bytes.fromhex("3B 07 12 18 0E 0D 17 39 44 2E 0C 14 14 36 3A 2F 0D"), 0),
    (0xE5, bytes.fromhex("37 07 12 18 0E 0D 17 39 44 2E 0C 14 14 36 3A 2F 0F"), 0),
    (0xA4, bytes.fromhex("85 85 95 82 AF AA AA 80 10 30 40 40 20 FF 60 30"), 0),
    (0xA4, bytes.fromhex("85 85 95 85"), 0),
    (0xBB, bytes.fromhex("00 00 00 00 00 00 00 00"), 0),
    (0x13, None, 0),
    (0x11, None, 120),
    (0x2C, bytes.fromhex("00 00 00 00"), 0),
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

    def _set_memory_location_qspi(x1, y1, x2, y2):
        param_buf = display._param_buf  # NOQA

        param_buf[0] = (x1 >> 8) & 0xFF
        param_buf[1] = x1 & 0xFF
        param_buf[2] = (x2 >> 8) & 0xFF
        param_buf[3] = x2 & 0xFF

        # The generic framework uses raw tx_param() calls, but this panel needs
        # QSPI write-command wrapping for every command phase.
        display.set_params(_LCD_CMD_CASET, display._param_mv[:4])

        if y1 == 0:
            return _qspi_color_cmd(_LCD_CMD_RAMWR)

        return _qspi_color_cmd(_LCD_CMD_RAMWRC)

    display._set_memory_location = _set_memory_location_qspi


def _finish_display_init(display):
    full_frame_size = (
        display.display_width *
        display.display_height *
        lv.color_format_get_size(display._color_space)
    )

    if full_frame_size == len(display._frame_buffer1):
        x1 = display._offset_x
        y1 = display._offset_y
        x2 = x1 + display.display_width - 1
        y2 = y1 + display.display_height - 1
        display._set_memory_location(x1, y1, x2, y2)
        display._backup_set_memory_location = display._set_memory_location
        setattr(display, "_set_memory_location", display._dummy_set_memory_location)

    display._initilized = True


def _init_display_like_idf_example(display):
    print("Applying ESP-IDF 06_lvgl_image init sequence...")
    display.set_params(_LCD_CMD_SLPOUT)
    sleep(0.1)

    if lv.color_format_get_size(display._color_space) == 2:
        pixel_format = 0x55
    else:
        pixel_format = 0x66

    display.set_params(_LCD_CMD_MADCTL, bytes([display._color_byte_order & 0x08]))
    display.set_params(_LCD_CMD_COLMOD, bytes([pixel_format]))

    for cmd, data, delay_ms in _IDF_06_LVGL_IMAGE_INIT_CMDS:
        display.set_params(cmd, data)
        if delay_ms:
            sleep(delay_ms / 1000)

    display.set_params(_LCD_CMD_DISPON)
    _finish_display_init(display)
    print("Custom panel init complete")


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

# Force the backlight on with a plain GPIO output first.
# This removes PWM/driver behavior from the equation while bringing the panel up.
print("Forcing backlight GPIO high...")
_bl_pin = machine.Pin(_BL, machine.Pin.OUT)
_bl_pin.value(1)
sleep(0.05)

print("Opening I2C bus...")
_i2c = machine.SoftI2C(sda=machine.Pin(_I2C_SDA), scl=machine.Pin(_I2C_SCL), freq=400000)
print("I2C scan:", [hex(addr) for addr in _i2c.scan()])
_init_pmu(_i2c)

# Hardware reset via TCA9554 IO expander (required for AXS15231B)
print("Resetting display via TCA9554...")
try:
    _cfg = _i2c.readfrom_mem(_TCA_ADDR, 0x03, 1)[0] & ~0x02
    _i2c.writeto_mem(_TCA_ADDR, 0x03, bytes([_cfg]))
    _out = _i2c.readfrom_mem(_TCA_ADDR, 0x01, 1)[0] & ~0x02
    _i2c.writeto_mem(_TCA_ADDR, 0x01, bytes([_out]))
    sleep(0.1)
    _i2c.writeto_mem(_TCA_ADDR, 0x01, bytes([_out | 0x02]))
    sleep(0.2)
    print("Display reset complete")
except Exception as e:
    print("TCA9554 reset failed:", e)
del _i2c

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

print("Running custom display init...")
_init_display_like_idf_example(display)
_bl_pin.value(1)
print("Backlight forced on")

_screen_w = _WIDTH
_screen_h = _HEIGHT
print("Rotation left at 0 degrees for QSPI bring-up")

print("Display ready")

th = task_handler.TaskHandler()

scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x101820), 0)


def _make_block(parent, x, y, w, h, bg_color, text, text_color):
    block = lv.obj(parent)
    block.set_pos(x, y)
    block.set_size(w, h)
    block.set_style_radius(0, 0)
    block.set_style_border_width(3, 0)
    block.set_style_border_color(lv.color_hex(0x202020), 0)
    block.set_style_bg_color(lv.color_hex(bg_color), 0)

    block_label = lv.label(block)
    block_label.set_text(text)
    block_label.set_style_text_color(lv.color_hex(text_color), 0)
    block_label.align(lv.ALIGN.CENTER, 0, 0)
    return block


title = lv.label(scrn)
title.set_text("LCD TEST PATTERN")
title.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
title.align(lv.ALIGN.TOP_MID, 0, 8)

info = lv.label(scrn)
info.set_text("Expect: TL red, TR green, BL blue, BR white")
info.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
info.align(lv.ALIGN.TOP_MID, 0, 28)

pattern_top = 56
pattern_w = _screen_w
pattern_h = _screen_h - pattern_top
half_w = pattern_w // 2
half_h = pattern_h // 2

_make_block(scrn, 0, pattern_top, half_w, half_h, 0xFF0000, "TL\nRED", 0xFFFFFF)
_make_block(scrn, half_w, pattern_top, pattern_w - half_w, half_h, 0x00FF00, "TR\nGREEN", 0x000000)
_make_block(scrn, 0, pattern_top + half_h, half_w, pattern_h - half_h, 0x0000FF, "BL\nBLUE", 0xFFFFFF)
_make_block(
    scrn,
    half_w,
    pattern_top + half_h,
    pattern_w - half_w,
    pattern_h - half_h,
    0xFFFFFF,
    "BR\nWHITE",
    0x000000,
)

center = lv.obj(scrn)
center.set_size(44, 44)
center.set_style_radius(4, 0)
center.set_style_border_width(3, 0)
center.set_style_border_color(lv.color_hex(0x000000), 0)
center.set_style_bg_color(lv.color_hex(0xFFD400), 0)
center.align(lv.ALIGN.CENTER, 0, 12)

center_label = lv.label(center)
center_label.set_text("C")
center_label.set_style_text_color(lv.color_hex(0x000000), 0)
center_label.align(lv.ALIGN.CENTER, 0, 0)

footer = lv.label(scrn)
footer.set_text("rot=0  mode=3  qspi")
footer.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
footer.align(lv.ALIGN.BOTTOM_MID, 0, -8)

lv.task_handler()
lv.refr_now(None)

print("Test pattern drawn")

while True:
    lv.task_handler()
    sleep(0.1)
