import lcd_bus
import machine
from time import sleep
import st7796
import lvgl as lv
from fs_driver import fs_register
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

# buf1 = display_bus.allocate_framebuffer(46080, lcd_bus.MEMORY_INTERNAL | lcd_bus.MEMORY_DMA)
# buf2 = display_bus.allocate_framebuffer(46080, lcd_bus.MEMORY_INTERNAL | lcd_bus.MEMORY_DMA)


buf1 = display_bus.allocate_framebuffer(100*320*2, lcd_bus.MEMORY_SPIRAM)
buf2 = display_bus.allocate_framebuffer(100*320*2, lcd_bus.MEMORY_SPIRAM)

print("Initializing ST7796 display...")
display = st7796.ST7796(
    data_bus=display_bus,
    display_width=_WIDTH,
    display_height=_HEIGHT,
    frame_buffer1=buf1,
    frame_buffer2=buf2,
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
scrn.set_style_bg_color(lv.color_hex(0x003366), 0)

# Register filesystem
print("Registering filesystem...")
fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")

# Create title
title = lv.label(scrn)
title.set_text("Animated Cat with lv.animimg")
title.align(lv.ALIGN.TOP_MID, 0, 10)
title.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
title.set_style_text_font(lv.font_montserrat_16, 0)

# For lv.animimg, we need multiple image frames
# Since we only have one cat image, we'll create multiple references
# In a real use case, you'd have cat_frame1.png, cat_frame2.png, etc.
print("Creating animated image object...")

# Create image descriptor array for animimg
# We'll use the same cat image but you can add more frames
img_dsc = [
    "S:cat_small.png",
]

# Create animimg widget
animimg = lv.animimg(scrn)
animimg.set_src(img_dsc, len(img_dsc))
animimg.set_duration(200)  # 1 second per frame (not relevant with 1 frame)
animimg.set_repeat_count(lv.ANIM_REPEAT_INFINITE)
animimg.start()

# Position the animimg
start_x = (480 - 100) // 2  # Assuming cat_small is ~100px
start_y = (320 - 100) // 2
animimg.set_pos(start_x, start_y)

print("Starting position animation...")

# Animation variables for moving the animimg widget
cat_x = float(start_x)
cat_y = float(start_y)
cat_dir_x = 1
cat_dir_y = 1
cat_speed_x = 1
cat_speed_y = 1

# Initial refresh
lv.task_handler()
lv.refr_now(None)

print("Entering main loop...")
while True:
    # Animate position
    cat_x += cat_speed_x * cat_dir_x
    cat_y += cat_speed_y * cat_dir_y
    
    # Bounce horizontally
    if cat_x >= 380 or cat_x <= 20:
        cat_dir_x *= -1
    
    # Bounce vertically
    if cat_y >= 220 or cat_y <= 40:
        cat_dir_y *= -1
    
    animimg.set_pos(int(cat_x), int(cat_y))
    
    lv.task_handler()
    lv.refr_now(None)
    # sleep(0.03)  # ~33 FPS
