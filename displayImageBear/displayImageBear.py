from machine import Pin, SoftI2C, ADC, PWM, UART
from time import sleep,sleep_ms, sleep_us
#import tm1637
import network
import math
 
### start
 
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
spi_bus = machine.SPI.Bus(host=_HOST, mosi=_MOSI, miso=_MISO, sck=_SCK)
display_bus = lcd_bus.SPIBus(spi_bus=spi_bus, freq=_LCD_FREQ, dc=_DC, cs=_LCD_CS)
buf1 = display_bus.allocate_framebuffer(100*320*2, lcd_bus.MEMORY_SPIRAM)
buf2 = display_bus.allocate_framebuffer(100*320*2, lcd_bus.MEMORY_SPIRAM)
display = st7796.ST7796(data_bus=display_bus, display_width=320, display_height=480, backlight_pin=6, reset_pin=None, backlight_on_state=st7796.STATE_HIGH, color_space=lv.COLOR_FORMAT.RGB565, color_byte_order=st7796.BYTE_ORDER_BGR, rgb565_byte_swap=True, offset_x=0, offset_y=0, frame_buffer1=buf1, frame_buffer2=buf2)
display.init()
display.set_rotation(lv.DISPLAY_ROTATION._90)
display.set_color_inversion(True)
display.set_backlight(100)
th = task_handler.TaskHandler()
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0xFFdd99), 0)
fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")
image = lv.image(scrn)
image.set_src("b1.png")
image.set_size(100, 100)
image.align(lv.ALIGN.CENTER, 0, 0)
label = lv.label(scrn)
label.set_text("Hello World")
label.set_style_text_color(lv.color_hex(0x0000FF), 0)
lv.task_handler()
lv.refr_now(None) 