import lcd_bus
import machine
from time import sleep
import st7796
import lvgl as lv
import task_handler
from fs_driver import fs_register

# Display settings for Waveshare ESP32-S3-Touch-LCD-3.5
_WIDTH = 320
_HEIGHT = 480
_MOSI = 1 
_MISO = 2
_SCK = 5
_HOST = 1
_DC = 3
_LCD_CS = 0
_BL = 6
_LCD_FREQ = 20000000
_OFFSET_X = 0
_OFFSET_Y = 0

print("Initializing SPI bus...")
spi_bus = machine.SPI.Bus(host=_HOST, mosi=_MOSI, miso=_MISO, sck=_SCK)

print("Initializing display bus...")
display_bus = lcd_bus.SPIBus(spi_bus=spi_bus, freq=_LCD_FREQ, dc=_DC, cs=_LCD_CS)

# Allocate framebuffers in SPIRAM
buf1 = display_bus.allocate_framebuffer(100*320*2, lcd_bus.MEMORY_SPIRAM)
buf2 = display_bus.allocate_framebuffer(100*320*2, lcd_bus.MEMORY_SPIRAM)

print("Initializing ST7796 display...")
display = st7796.ST7796(
    data_bus=display_bus,
    display_width=_WIDTH,
    display_height=_HEIGHT,
    backlight_pin=_BL,
    reset_pin=None,
    backlight_on_state=st7796.STATE_HIGH,
    color_space=lv.COLOR_FORMAT.RGB565,
    color_byte_order=st7796.BYTE_ORDER_BGR,
    rgb565_byte_swap=True,
    offset_x=_OFFSET_X,
    offset_y=_OFFSET_Y,
    frame_buffer1=buf1,
    frame_buffer2=buf2,
)

display.init()
display.set_rotation(lv.DISPLAY_ROTATION._90)  # Landscape mode
display.set_color_inversion(True)
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

# Refresh display
lv.task_handler()
lv.refr_now(None)

print("Image displayed successfully!")

# Keep the display running
while True:
    lv.task_handler()
    sleep(0.1)
