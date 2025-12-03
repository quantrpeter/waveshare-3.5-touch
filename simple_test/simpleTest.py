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

# Configure TCA9554 pin 1 as output for LCD reset
print("Configuring TCA9554...")
# config = i2c.readfrom_mem(_TCA9554_ADDR, TCA9554_CONFIG, 1)[0]
# config &= ~(1 << 1)  # Set pin 1 as output
# i2c.writeto_mem(_TCA9554_ADDR, TCA9554_CONFIG, bytes([config]))

# Perform LCD reset sequence
print("Resetting LCD via TCA9554...")
# i2c.writeto_mem(_TCA9554_ADDR, TCA9554_OUTPUT_PORT, bytes([0xFF]))  # All high
# sleep(0.01)
# i2c.writeto_mem(_TCA9554_ADDR, TCA9554_OUTPUT_PORT, bytes([0xFD]))  # Pin 1 low (bit 1 = 0)
# sleep(0.01)
# i2c.writeto_mem(_TCA9554_ADDR, TCA9554_OUTPUT_PORT, bytes([0xFF]))  # All high again
# sleep(0.2)
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
# buf1 = display_bus.allocate_framebuffer(320 * 480 * 2, lcd_bus.MEMORY_PSRAM)
# buf2 = display_bus.allocate_framebuffer(320 * 480 * 2, lcd_bus.MEMORY_PSRAM)
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
	# frame_buffer1=buf1,
    # frame_buffer2=buf2,
)
print("Display object created")

print("Initializing display...")
display.init()
print("Display initialized")

print("Setting rotation...")
display.set_rotation(lv.DISPLAY_ROTATION._270)
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
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)
print("Screen created with black background")

# Create a simple label (skip image for now)
print("Creating label...")
label = lv.label(scrn)
label.set_text("TEST - Waveshare 3.5")
label.set_pos(50, 100)
label.set_style_text_color(lv.color_hex(0x00ffff), 0)
label.set_style_text_font(lv.font_montserrat_16, 0)
print("Label created")

fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")
img = lv.image(scrn)
img.set_src("S:blue.png")
img.set_size(480, 320)
img.set_pos(0, 0)

print("Refreshing display...")
lv.refr_now(lv.screen_active().get_display())
lv.task_handler()
print("Display refreshed - you should see red screen with white text")

print("Entering main loop...")
while True:
	lv.refr_now(lv.screen_active().get_display())
	lv.task_handler()
	sleep(0.5)
