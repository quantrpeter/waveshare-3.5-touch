import lcd_bus
from micropython import const
import machine
from time import sleep
import st7796
import lvgl as lv
import utime as time
from fs_driver import fs_register
from machine import Pin, I2C

# display settings for Waveshare ESP32-S3-Touch-LCD-3.5
# Resolution
_WIDTH = 320
_HEIGHT = 480

# SPI pins (direct GPIO)
_MOSI = 1 
_MISO = 2
_SCK = 5
_HOST = 1

# LCD control pins (direct GPIO - not through IO expander)
_DC = 3
_LCD_CS = 0
_RST = 0
_BL = 6

_LCD_FREQ = 20000000  # 20MHz

_OFFSET_X = 0
_OFFSET_Y = 0

# I2C for TCA9554 IO expander (controls LCD reset)
_I2C_SDA = 8
_I2C_SCL = 7
_TCA9554_ADDR = 0x20

# TCA9554 Registers
TCA9554_OUTPUT_PORT = 0x01
TCA9554_CONFIG = 0x03

print("Initializing I2C for TCA9554...")
i2c = I2C(0, scl=Pin(_I2C_SCL), sda=Pin(_I2C_SDA), freq=400000)
print("I2C devices found:", [hex(addr) for addr in i2c.scan()])

print("Configuring TCA9554...")
print("Resetting LCD via TCA9554...")
print("LCD reset complete")

print("Initializing SPI bus...")
spi_bus = machine.SPI.Bus(
    host=_HOST,
    mosi=_MOSI,
    miso=_MISO,
    sck=_SCK
)
print("SPI bus initialized")

print("Initializing display bus...")
display_bus = lcd_bus.SPIBus(
    spi_bus=spi_bus,
    freq=_LCD_FREQ,
    dc=_DC,
    cs=_LCD_CS,
)
print("Display bus initialized")

print("Initializing ST7796 display...")
display = st7796.ST7796(
    data_bus=display_bus,
    display_width=_WIDTH,
    display_height=_HEIGHT,
    backlight_pin=_BL,
    reset_pin=None,  # Reset already done via TCA9554
    backlight_on_state=st7796.STATE_HIGH,
    color_space=lv.COLOR_FORMAT.RGB565,
    color_byte_order=st7796.BYTE_ORDER_BGR,
    rgb565_byte_swap=True,
    offset_x=_OFFSET_X,
    offset_y=_OFFSET_Y,
)
print("Display object created")

print("Initializing display...")
display.init()
print("Display initialized")

print("Setting rotation...")
display.set_rotation(lv.DISPLAY_ROTATION._90)
print("Rotation set")

print("Setting color inversion...")
display.set_color_inversion(True)
print("Color inversion enabled")

print("Setting backlight to 100%...")
display.set_backlight(100)
print("Backlight set")

# Create screen
print("Creating screen...")
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x003366), 0)
print("Screen created with dark blue background")

# Register filesystem driver
print("Registering filesystem...")
fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")

# Create image object
print("Creating cat image...")
cat_img = lv.image(scrn)
cat_img.set_src("S:cat_small.png")
# Position at center of screen (480x320 display, 224x224 image)
start_x = (480 - 224) // 2
start_y = (320 - 224) // 2
cat_img.set_pos(start_x, start_y)
print("Cat image positioned at ({start_x}, {start_y})")

print("Starting animation loop...")

# Animation variables
cat_x = float(start_x)
cat_y = float(start_y)
cat_dir_x = 1
cat_dir_y = 1
cat_speed_x = 5
cat_speed_y = 4
frame_count = 0

print("Entering main loop...")
while True:
    # Animate cat position
    cat_x += cat_speed_x * cat_dir_x
    cat_y += cat_speed_y * cat_dir_y
    
    # Bounce horizontally
    if cat_x >= 480 - 224 - 20 or cat_x <= 20:
        cat_dir_x *= -1
    
    # Bounce vertically
    if cat_y >= 320 - 224 - 20 or cat_y <= 40:
        cat_dir_y *= -1
    
    cat_img.set_pos(int(cat_x), int(cat_y))
    
    # Force redraw
    lv.task_handler()
    lv.refr_now(None)
    sleep(0.05)  # 20 FPS for stability
