import lcd_bus
import machine
from time import sleep, localtime
import axs15231b
import lvgl as lv
import task_handler

# Display settings for Waveshare ESP32-S3-Touch-LCD-3.5B (AXS15231B)
# Pin mapping from the working ESP-IDF `06_lvgl_image` example:
#   QSPI D0=1, D1=2, D2=3, D3=4, CLK=5, CS=12, BL=6
#   QSPI panel IO uses 32-bit commands and no dedicated D/C GPIO (`dc = -1`)
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

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
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
    # redraws (anything after the first full-screen paint) land in the wrong
    # place and the screen appears frozen.
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
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)
scrn.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

# ---------------------------------------------------------------------------
# Seven-segment digit rendering (built-in fonts only go up to 16px, so we
# draw big crisp digits out of rectangles instead)
# ---------------------------------------------------------------------------
_SEG_COLOR = lv.color_hex(0x00FF88)
_DIGIT_W = 38
_DIGIT_H = 90
_SEG_T = 10
_COLON_W = 12
_GAP = 8

# Segments: A=top, B=top-right, C=bottom-right, D=bottom, E=bottom-left,
# F=top-left, G=middle. Rectangles as (x, y, w, h) inside a digit.
_HALF = (_DIGIT_H - _SEG_T) // 2
_SEG_RECTS = (
    (_SEG_T, 0, _DIGIT_W - 2 * _SEG_T, _SEG_T),                          # A
    (_DIGIT_W - _SEG_T, _SEG_T, _SEG_T, _HALF - _SEG_T),                 # B
    (_DIGIT_W - _SEG_T, _HALF + _SEG_T, _SEG_T,
     _DIGIT_H - _HALF - 2 * _SEG_T),                                     # C
    (_SEG_T, _DIGIT_H - _SEG_T, _DIGIT_W - 2 * _SEG_T, _SEG_T),          # D
    (0, _HALF + _SEG_T, _SEG_T, _DIGIT_H - _HALF - 2 * _SEG_T),          # E
    (0, _SEG_T, _SEG_T, _HALF - _SEG_T),                                 # F
    (_SEG_T, _HALF, _DIGIT_W - 2 * _SEG_T, _SEG_T),                      # G
)

# Which segments (ABCDEFG) are lit for each digit 0-9
_DIGIT_SEGS = (
    0b1111110,  # 0: ABCDEF
    0b0110000,  # 1: BC
    0b1101101,  # 2: ABDEG
    0b1111001,  # 3: ABCDG
    0b0110011,  # 4: BCFG
    0b1011011,  # 5: ACDFG
    0b1011111,  # 6: ACDEFG
    0b1110000,  # 7: ABC
    0b1111111,  # 8: all
    0b1111011,  # 9: ABCDFG
)


def _make_rect(parent, x, y, w, h):
    o = lv.obj(parent)
    o.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
    o.set_style_bg_color(_SEG_COLOR, 0)
    o.set_style_border_width(0, 0)
    o.set_style_radius(2, 0)
    o.set_style_pad_all(0, 0)
    o.set_size(w, h)
    o.set_pos(x, y)
    return o


class Digit:
    def __init__(self, parent, x, y):
        self.segs = []
        for rx, ry, rw, rh in _SEG_RECTS:
            seg = _make_rect(parent, x + rx, y + ry, rw, rh)
            seg.add_flag(lv.obj.FLAG.HIDDEN)
            self.segs.append(seg)
        self.value = -1

    def set(self, value):
        if value == self.value:
            return
        self.value = value
        mask = _DIGIT_SEGS[value]
        for i, seg in enumerate(self.segs):
            if mask & (0b1000000 >> i):
                seg.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                seg.add_flag(lv.obj.FLAG.HIDDEN)


def _make_colon(parent, x, y):
    dot_y1 = y + _DIGIT_H // 4 - _COLON_W // 2
    dot_y2 = y + 3 * _DIGIT_H // 4 - _COLON_W // 2
    _make_rect(parent, x, dot_y1, _COLON_W, _COLON_W)
    _make_rect(parent, x, dot_y2, _COLON_W, _COLON_W)


# Layout: [D D : D D : D D] centered horizontally
_ITEMS_W = 6 * _DIGIT_W + 2 * _COLON_W + 7 * _GAP
_X0 = (_WIDTH - _ITEMS_W) // 2
_Y0 = (_HEIGHT - _DIGIT_H) // 2 - 40

digits = []
_x = _X0
for i in range(6):
    digits.append(Digit(scrn, _x, _Y0))
    _x += _DIGIT_W + _GAP
    if i in (1, 3):
        _make_colon(scrn, _x, _Y0)
        _x += _COLON_W + _GAP

date_label = lv.label(scrn)
date_label.set_style_text_color(lv.color_hex(0xAAAAAA), 0)
date_label.set_style_text_font(lv.font_montserrat_16, 0)
date_label.set_text("")
date_label.align(lv.ALIGN.CENTER, 0, _DIGIT_H // 2 + 10)

_last_second = -1
_last_date = None


def _update_clock():
    global _last_second, _last_date

    year, month, day, hour, minute, second, weekday, _ = localtime()
    if second == _last_second:
        return
    _last_second = second
    print(second)

    digits[0].set(hour // 10)
    digits[1].set(hour % 10)
    digits[2].set(minute // 10)
    digits[3].set(minute % 10)
    digits[4].set(second // 10)
    digits[5].set(second % 10)

    date = (year, month, day)
    if date != _last_date:
        _last_date = date
        date_label.set_text(
            "%s %d %s %d" % (_WEEKDAYS[weekday], day, _MONTHS[month - 1], year)
        )
        date_label.align(lv.ALIGN.CENTER, 0, _DIGIT_H // 2 + 10)


print("Clock running")

lv.task_handler()
lv.refr_now(None)

while True:
    _update_clock()
    lv.task_handler()
    scrn.invalidate()
    lv.task_handler()
    lv.refr_now(None)
    sleep(0.05)
