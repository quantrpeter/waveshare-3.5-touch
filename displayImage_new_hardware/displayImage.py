import lcd_bus
import machine
import lvgl as lv
import axs15231b
import time

# Display settings for Waveshare ESP32-S3-Touch-LCD-3.5B (QSPI, from bsp_display.h)
# SPI2_HOST, CS=12, SCLK=5, D0=1, D1=2, D2=3, D3=4, BL=6, no DC
_WIDTH = 320
_HEIGHT = 480
_HOST = 2         # SPI2_HOST
_SCK = 5
_DATA0 = 1
_DATA1 = 2
_DATA2 = 3
_DATA3 = 4
_LCD_CS = 12
_BL = 6
_LCD_FREQ = 40000000   # 40 MHz as used in BSP
_OFFSET_X = 0
_OFFSET_Y = 0

print("Initializing QSPI bus...")
spi_bus = machine.SPI.Bus(
    host=_HOST,
    sck=_SCK,
    quad_pins=(_DATA0, _DATA1, _DATA2, _DATA3)
)

print("Initializing display bus...")
display_bus = lcd_bus.SPIBus(
    spi_bus=spi_bus,
    dc=-1,          # No DC pin for QSPI AXS15231B
    cs=_LCD_CS,
    freq=_LCD_FREQ,
    quad=True
)

# Allocate framebuffers in SPIRAM
buf1 = display_bus.allocate_framebuffer(100 * 320 * 2, lcd_bus.MEMORY_SPIRAM)
buf2 = display_bus.allocate_framebuffer(100 * 320 * 2, lcd_bus.MEMORY_SPIRAM)

print("Initializing AXS15231B display...")
display = axs15231b.AXS15231B(
    data_bus=display_bus,
    display_width=_WIDTH,
    display_height=_HEIGHT,
    backlight_pin=_BL,
    reset_pin=None,
    backlight_on_state=axs15231b.STATE_HIGH,
    color_space=lv.COLOR_FORMAT.RGB565,
    color_byte_order=axs15231b.BYTE_ORDER_BGR,
    rgb565_byte_swap=True,
    offset_x=_OFFSET_X,
    offset_y=_OFFSET_Y,
    frame_buffer1=buf1,
    frame_buffer2=buf2,
)

# The default _param_buf is only 4 bytes, but the init sequence writes up to
# 31 bytes. Enlarge it before init so all register writes succeed.
display._param_buf = bytearray(32)
display._param_mv = memoryview(display._param_buf)

display.set_params(0x01)  # Software reset
time.sleep_ms(120)

display.init()

# The init sequence ends with ALLPOFF (0x22) which overrides GRAM output.
# Send NORON (0x13) to restore normal display mode.
display.set_params(0x13)  # NORON
time.sleep_ms(20)

# Restore 4-byte param buffer for runtime (CASET/RASET need exactly 4 bytes)
display._param_buf = bytearray(4)
display._param_mv = memoryview(display._param_buf)

# Fix: The driver's _set_memory_location has a QSPI bug - it sends CASET
# without QSPI command wrapping (0x02 instruction prefix) and skips RASET
# entirely. The C-level tx_color does NOT handle addressing (marks x/y as
# LCD_UNUSED), so the display never knows where to write pixel data.
_WRITE_CMD = 0x02
_WRITE_COLOR = 0x32
_CASET = 0x2A
_RASET = 0x2B
_RAMWR = 0x2C


def _qspi_set_memory_location(x1, y1, x2, y2):
    param_buf = display._param_buf
    param_mv = display._param_mv

    # Column addresses - CASET wrapped for QSPI
    param_buf[0] = (x1 >> 8) & 0xFF
    param_buf[1] = x1 & 0xFF
    param_buf[2] = (x2 >> 8) & 0xFF
    param_buf[3] = x2 & 0xFF
    display._data_bus.tx_param((_WRITE_CMD << 24) | (_CASET << 8), param_mv[:4])

    # Row addresses - RASET wrapped for QSPI
    param_buf[0] = (y1 >> 8) & 0xFF
    param_buf[1] = y1 & 0xFF
    param_buf[2] = (y2 >> 8) & 0xFF
    param_buf[3] = y2 & 0xFF
    display._data_bus.tx_param((_WRITE_CMD << 24) | (_RASET << 8), param_mv[:4])

    # Return RAMWR wrapped with WRITE_COLOR instruction for tx_color
    return (_WRITE_COLOR << 24) | (_RAMWR << 8)


display._set_memory_location = _qspi_set_memory_location

display.set_rotation(lv.DISPLAY_ROTATION._90)
display.set_color_inversion(True)
display.set_backlight(100)

print("Display ready")

# Get active screen and set background
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x0000FF), 0)  # Blue background

# Add a label to confirm rendering works
label = lv.label(scrn)
label.set_text("Hello Display!")
label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
label.align(lv.ALIGN.CENTER, 0, 0)

print("Screen set up, entering main loop...")

import task_handler

th = task_handler.TaskHandler()

while True:
    time.sleep_ms(100)