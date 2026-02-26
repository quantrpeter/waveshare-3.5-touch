import lcd_bus
import machine
import lvgl as lv
import axs15231b

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
    offset_y=_OFFSET_Y
)

display.init()
display.set_rotation(lv.DISPLAY_ROTATION._90)
display.set_color_inversion(True)
display.set_power(True)
display.set_backlight(100)

print("Display ready")

# Get active screen and set background
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x0000FF), 0)  # Blue background - visible test

# Add a label to confirm rendering works
label = lv.label(scrn)
label.set_text("Hello Display!")
label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
label.align(lv.ALIGN.CENTER, 0, 0)

print("Screen set up, entering main loop...")


import task_handler

th = task_handler.TaskHandler()