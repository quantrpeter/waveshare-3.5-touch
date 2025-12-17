import lcd_bus
import machine
from time import sleep
import st7796
import lvgl as lv
import i2c
import ft6x36
import pointer_framework
import task_handler

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
_I2C_SDA = 8
_I2C_SCL = 7

# Touch settings
_TOUCH_I2C_ADDR = 0x38
_TOUCH_INT = 4
_TOUCH_RST = None

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

# Initialize touch BEFORE setting rotation
print("Initializing FT6336 touch...")
i2c_bus = i2c.I2C.Bus(host=0, scl=_I2C_SCL, sda=_I2C_SDA, freq=400000, use_locks=False)
touch_dev = i2c.I2C.Device(bus=i2c_bus, dev_id=_TOUCH_I2C_ADDR, reg_bits=ft6x36.BITS)
indev = ft6x36.FT6x36(touch_dev, startup_rotation=pointer_framework.lv.DISPLAY_ROTATION._90)
print("Touch driver initialized")

# Set rotation AFTER touch initialization
display.set_rotation(lv.DISPLAY_ROTATION._90)  # Landscape mode
display.set_color_inversion(True)
display.set_backlight(100)

if not indev.is_calibrated:
    indev.calibrate()

print("Display ready")

# Initialize task handler for LVGL
th = task_handler.TaskHandler()

# Get active screen
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)  # Black background

# Counter variable
counter = 0

# Create button on the left
btn = lv.button(scrn)
btn.set_size(150, 80)
btn.align(lv.ALIGN.LEFT_MID, 50, 0)
btn.set_style_bg_color(lv.color_hex(0x4444FF), 0)

btn_label = lv.label(btn)
btn_label.set_text("Click Me!")
btn_label.set_style_text_font(lv.font_montserrat_16, 0)
btn_label.center()

# Create label on the right
count_label = lv.label(scrn)
count_label.set_text("0")
count_label.align(lv.ALIGN.RIGHT_MID, -50, 0)
count_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
count_label.set_style_text_font(lv.font_montserrat_16, 0)

# Button click event handler
def btn_clicked(event):
    global counter
    counter += 1
    count_label.set_text(str(counter))
    print(f"Button clicked! Count: {counter}")

btn.add_event_cb(btn_clicked, lv.EVENT.CLICKED, None)

# Refresh display
lv.task_handler()
lv.refr_now(None)

print("Ready! Click the button to increment the counter.")

# Keep the display running
while True:
    lv.task_handler()
    sleep(0.05)
