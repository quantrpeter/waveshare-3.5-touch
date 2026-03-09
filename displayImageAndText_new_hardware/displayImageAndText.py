import lcd_bus
import machine
from time import sleep
import axs15231b
import lvgl as lv
import task_handler
from fs_driver import fs_register

# Display settings for Waveshare ESP32-S3-Touch-LCD-3.5B (AXS15231B)
# Pin mapping from official ESP-IDF demo (05_lvgl_example/bsp_display.h)
#   QSPI D0=1, D1=2, D2=3, D3=4, CLK=5, CS=12, BL=6
#   No physical DC pin -- AXS15231B uses 9-bit SPI command prefix in QSPI mode
#   LCD reset via TCA9554 IO expander pin 1 (I2C 0x20, SDA=8, SCL=7)
_WIDTH = 320
_HEIGHT = 480
_QSPI_D0 = 1
_QSPI_D1 = 2
_QSPI_D2 = 3
_QSPI_D3 = 4
_QSPI_CLK = 5
_HOST = 1
_DC = 0        # no physical DC on this board; use GPIO 0 (BOOT btn) as dummy
_LCD_CS = 12
_BL = 6
_LCD_FREQ = 40000000
_I2C_SDA = 8
_I2C_SCL = 7

# Hardware reset via TCA9554 IO expander (required for AXS15231B)
print("Resetting display via TCA9554...")
_TCA_ADDR = 0x20
_tca = machine.SoftI2C(sda=machine.Pin(_I2C_SDA), scl=machine.Pin(_I2C_SCL), freq=400000)
try:
    _cfg = _tca.readfrom_mem(_TCA_ADDR, 0x03, 1)[0] & ~0x02
    _tca.writeto_mem(_TCA_ADDR, 0x03, bytes([_cfg]))
    _out = _tca.readfrom_mem(_TCA_ADDR, 0x01, 1)[0] & ~0x02
    _tca.writeto_mem(_TCA_ADDR, 0x01, bytes([_out]))
    sleep(0.1)
    _tca.writeto_mem(_TCA_ADDR, 0x01, bytes([_out | 0x02]))
    sleep(0.2)
    print("Display reset complete")
except Exception as e:
    print("TCA9554 reset failed:", e)
del _tca

print("Initializing SPI bus...")
spi_bus = machine.SPI.Bus(
    host=_HOST,
    mosi=_QSPI_D0,
    miso=_QSPI_D1,
    sck=_QSPI_CLK,
    quad_pins=(_QSPI_D0, _QSPI_D1, _QSPI_D2, _QSPI_D3),
)

print("Initializing display bus...")
display_bus = lcd_bus.SPIBus(
    spi_bus=spi_bus,
    dc=_DC,
    cs=_LCD_CS,
    freq=_LCD_FREQ,
    spi_mode=0,
    quad=True,
)

buf1 = display_bus.allocate_framebuffer(100 * 320 * 2, lcd_bus.MEMORY_SPIRAM)
buf2 = display_bus.allocate_framebuffer(100 * 320 * 2, lcd_bus.MEMORY_SPIRAM)

print("Initializing AXS15231B display...")
display = axs15231b.AXS15231B(
    data_bus=display_bus,
    display_width=_WIDTH,
    display_height=_HEIGHT,
    backlight_pin=_BL,
    reset_pin=None,
    backlight_on_state=axs15231b.STATE_PWM,
    color_space=lv.COLOR_FORMAT.RGB565,
    rgb565_byte_swap=True,
    frame_buffer1=buf1,
    frame_buffer2=buf2,
)

print("Running display.init()...")
display.init()
print("Setting backlight...")
display.set_backlight(100)

print("Display ready")

th = task_handler.TaskHandler()

scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)

print("Registering filesystem...")
fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")

print("Creating image...")
img = lv.image(scrn)
img.set_src("S:semiblock_logo_2.png")
img.set_size(200, 200)
img.align(lv.ALIGN.CENTER, 0, 0)

label = lv.label(scrn)
label.set_text("Hello World")
label.set_style_text_color(lv.color_hex(0x0000FF), 0)

lv.task_handler()
lv.refr_now(None)

print("Image displayed successfully!")

while True:
    lv.task_handler()
    sleep(0.1)
