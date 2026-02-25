import lcd_bus
import machine
from time import sleep
import lvgl as lv
import axs15231b
import task_handler
from fs_driver import fs_register

# Display settings for Waveshare ESP32-S3-Touch-LCD-3.5
_WIDTH = 320
_HEIGHT = 480
_MOSI = 1 
_MISO = 2
_SCK = 5
_HOST = 2
_DC = -1    # No DC GPIO for QSPI AXS15231B - D/C encoded in protocol
_LCD_CS = 12
_BL = 6
_LCD_FREQ = 20000000
_OFFSET_X = 0
_OFFSET_Y = 0

_DATA0_PIN = 1   # QSPI Data 0 (MOSI equivalent)
_DATA1_PIN = 2   # QSPI Data 1 (MISO equivalent)
_DATA2_PIN = 3   # QSPI Data 2
_DATA3_PIN = 4   # QSPI Data 3

print("Initializing SPI bus...")
# spi_bus = machine.SPI.Bus(host=_HOST, mosi=_MOSI, miso=_MISO, sck=_SCK)
spi_bus = machine.SPI.Bus(
    host=_HOST,  # SPI2_HOST
    sck=_SCK,
    quad_pins=(_DATA0_PIN, _DATA1_PIN, _DATA2_PIN, _DATA3_PIN)
)

print("Initializing display bus...")
# display_bus = lcd_bus.SPIBus(spi_bus=spi_bus, freq=_LCD_FREQ, dc=_DC, cs=_LCD_CS)
display_bus = lcd_bus.SPIBus(
    spi_bus=spi_bus,
    dc=_DC,
    cs=_LCD_CS, 
    freq=_LCD_FREQ,
    spi_mode=0,      # SPI mode 0 (CPOL=0, CPHA=0) - AXS15231B default
    quad=True        # Enable QSPI mode (4-wire)
)

# Allocate framebuffers in SPIRAM (partial buffer - 100 rows at a time to stay within SPI DMA limits)
_BUFFER_SIZE = 100 * _WIDTH * 2
buf1 = display_bus.allocate_framebuffer(_BUFFER_SIZE, lcd_bus.MEMORY_SPIRAM)
buf2 = display_bus.allocate_framebuffer(_BUFFER_SIZE, lcd_bus.MEMORY_SPIRAM)

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

display.init()
display.set_rotation(lv.DISPLAY_ROTATION._90)
display.set_color_inversion(True)
display.set_power(True)
display.set_backlight(100)

print("Display ready")

# Initialize task handler for LVGL
th = task_handler.TaskHandler()

# Get active screen
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)  # Black background

# Register filesystem driver
print("Registering filesystem...")
fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")

# Create and display image
print("Creating image...")
img = lv.image(scrn)
img.set_src("S:semiblock_logo_2.png")  # Change to your image filename
img.set_size(200, 200)  # Set image size (width, height)
img.align(lv.ALIGN.CENTER, 0, 0)  # Center the image

print("Image displayed successfully!")

# Keep the display running
while True:
    lv.task_handler()
    sleep(0.1)
