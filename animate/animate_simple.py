import lcd_bus
from micropython import const
import machine
from time import sleep
import st7796
import lvgl as lv
from machine import Pin, I2C

# display settings for Waveshare ESP32-S3-Touch-LCD-3.5
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
_I2C_SDA = 8
_I2C_SCL = 7

print("Initializing I2C for TCA9554...")
i2c = I2C(0, scl=Pin(_I2C_SCL), sda=Pin(_I2C_SDA), freq=400000)
print("I2C devices found:", [hex(addr) for addr in i2c.scan()])

print("Initializing SPI bus...")
spi_bus = machine.SPI.Bus(host=_HOST, mosi=_MOSI, miso=_MISO, sck=_SCK)

print("Initializing display bus...")
display_bus = lcd_bus.SPIBus(spi_bus=spi_bus, freq=_LCD_FREQ, dc=_DC, cs=_LCD_CS)

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
)

display.init()
display.set_rotation(lv.DISPLAY_ROTATION._90)
display.set_color_inversion(True)
display.set_backlight(100)

# Create screen
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)

# Create title
title = lv.label(scrn)
title.set_text("LVGL Animation Demo")
title.align(lv.ALIGN.TOP_MID, 0, 10)
title.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
title.set_style_text_font(lv.font_montserrat_16, 0)

# Create a colored circle
circle = lv.obj(scrn)
circle.set_size(80, 80)
circle.set_style_radius(40, 0)  # Make it circular
circle.set_style_bg_color(lv.color_hex(0xFF6B35), 0)  # Orange
circle.set_style_border_width(0, 0)
circle.set_pos(50, 100)

# Create a colored square
square = lv.obj(scrn)
square.set_size(60, 60)
square.set_style_radius(0, 0)  # Square corners
square.set_style_bg_color(lv.color_hex(0x4ECDC4), 0)  # Teal
square.set_style_border_width(0, 0)
square.set_pos(200, 150)

# Create a colored triangle (using a label with special character)
triangle = lv.obj(scrn)
triangle.set_size(70, 70)
triangle.set_style_radius(5, 0)
triangle.set_style_bg_color(lv.color_hex(0xF7B731), 0)  # Yellow
triangle.set_style_border_width(0, 0)
triangle.set_pos(100, 200)

print("Starting animation loop...")

# Animation variables
circle_x = 20
circle_dir = 1
circle_speed = 4

square_y = 40
square_dir = 1
square_speed = 3

triangle_x = 10
triangle_y = 50
triangle_dir_x = 1
triangle_dir_y = 1
triangle_speed = 2

print("Entering main loop...")
while True:
    # Animate circle horizontally
    circle_x += circle_speed * circle_dir
    if circle_x >= 400 or circle_x <= 20:
        circle_dir *= -1
    circle.set_x(int(circle_x))
    
    # Animate square vertically
    square_y += square_speed * square_dir
    if square_y >= 250 or square_y <= 40:
        square_dir *= -1
    square.set_y(int(square_y))
    
    # Animate triangle diagonally
    triangle_x += triangle_speed * triangle_dir_x
    triangle_y += triangle_speed * triangle_dir_y
    if triangle_x >= 400 or triangle_x <= 10:
        triangle_dir_x *= -1
    if triangle_y >= 240 or triangle_y <= 50:
        triangle_dir_y *= -1
    triangle.set_x(int(triangle_x))
    triangle.set_y(int(triangle_y))
    
    lv.refr_now(lv.screen_active().get_display())
    lv.task_handler()
    sleep(0.02)  # 50 FPS
