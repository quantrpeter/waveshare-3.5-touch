import lcd_bus
import machine
from time import sleep
import axs15231b
import lvgl as lv
import task_handler
from fs_driver import fs_register

# Display settings for Waveshare ESP32-S3-Touch-LCD-3.5B (AXS15231B)
# Pin mapping from the working ESP-IDF `06_lvgl_image` example:
#   QSPI D0=1, D1=2, D2=3, D3=4, CLK=5, CS=12, BL=6
#   QSPI panel IO uses 32-bit commands and no dedicated D/C GPIO (`dc = -1`)
#   LCD reset via TCA9554 IO expander pin 1 (I2C 0x20, SDA=8, SCL=7)
_WIDTH = 320
_HEIGHT = 480
_QSPI_D0 = 1
_QSPI_D1 = 2
_QSPI_D2 = 3
_QSPI_D3 = 4
_QSPI_CLK = 5
_HOST = 1
_LCD_CS = 12
_BL = 6
_LCD_FREQ = 40000000
_I2C_SDA = 8
_I2C_SCL = 7
_TCA_ADDR = 0x20
_PMU_ADDR = 0x34
_PMU_CHIP_ID_REG = 0x03
_PMU_EXPECTED_CHIP_ID = 0x4A
_PMU_VBUS_VOL_LIMIT_REG = 0x15
_PMU_VBUS_CUR_LIMIT_REG = 0x16
_PMU_LDO_ONOFF_CTRL0_REG = 0x90
_PMU_BLDO1_VOL_REG = 0x96
_PMU_BLDO2_VOL_REG = 0x97
_LCD_CMD_CASET = 0x2A
_LCD_CMD_RAMWR = 0x2C
_LCD_CMD_RAMWRC = 0x3C
_LCD_QSPI_WRITE_COLOR = 0x32
_DRAW_BUFFER_LINES = 48

def _qspi_color_cmd(cmd):
    cmd &= 0xFF
    cmd <<= 8
    cmd |= _LCD_QSPI_WRITE_COLOR << 24
    return cmd

def _install_axs15231b_qspi_workarounds(display):
    if not isinstance(display._data_bus, lcd_bus.SPIBus):
        return

    if display._data_bus.get_lane_count() != 4:
        return

    def _set_memory_location_qspi(x1, y1, x2, y2):
        param_buf = display._param_buf  # NOQA

        param_buf[0] = (x1 >> 8) & 0xFF
        param_buf[1] = x1 & 0xFF
        param_buf[2] = (x2 >> 8) & 0xFF
        param_buf[3] = x2 & 0xFF

        # The generic framework uses raw tx_param() calls, but this panel needs
        # QSPI write-command wrapping for every command phase.
        display.set_params(_LCD_CMD_CASET, display._param_mv[:4])

        if y1 == 0:
            return _qspi_color_cmd(_LCD_CMD_RAMWR)

        return _qspi_color_cmd(_LCD_CMD_RAMWRC)

    display._set_memory_location = _set_memory_location_qspi


def _allocate_draw_buffers(display_bus, width, lines, color_space):
    buf_size = width * lines * lv.color_format_get_size(color_space)
    print("Allocating draw buffer:", width, "x", lines, "=", buf_size, "bytes")

    for flags, label in (
        (lcd_bus.MEMORY_SPIRAM | lcd_bus.MEMORY_DMA, "SPIRAM|DMA"),
        (lcd_bus.MEMORY_SPIRAM, "SPIRAM"),
        (lcd_bus.MEMORY_INTERNAL | lcd_bus.MEMORY_DMA, "INTERNAL|DMA"),
        (lcd_bus.MEMORY_INTERNAL, "INTERNAL"),
    ):
        try:
            buf1 = display_bus.allocate_framebuffer(buf_size, flags)
            print("Framebuffer 1:", label)
        except MemoryError:
            continue

        buf2 = None
        try:
            buf2 = display_bus.allocate_framebuffer(buf_size, flags)
            print("Framebuffer 2:", label)
        except MemoryError:
            print("Second framebuffer unavailable, using single buffering")

        return buf1, buf2

    raise MemoryError("Unable to allocate draw buffers")

# Force the backlight on with a plain GPIO output first.
# This removes PWM/driver behavior from the equation while bringing the panel up.
print("Forcing backlight GPIO high...")
_bl_pin = machine.Pin(_BL, machine.Pin.OUT)
_bl_pin.value(1)
sleep(0.05)

print("Opening I2C bus...")
_i2c = machine.SoftI2C(sda=machine.Pin(_I2C_SDA), scl=machine.Pin(_I2C_SCL), freq=400000)
print("I2C scan:", [hex(addr) for addr in _i2c.scan()])

# Hardware reset via TCA9554 IO expander (required for AXS15231B)
# print("Resetting display via TCA9554...")
# try:
#     _cfg = _i2c.readfrom_mem(_TCA_ADDR, 0x03, 1)[0] & ~0x02
#     _i2c.writeto_mem(_TCA_ADDR, 0x03, bytes([_cfg]))
#     _out = _i2c.readfrom_mem(_TCA_ADDR, 0x01, 1)[0] & ~0x02
#     _i2c.writeto_mem(_TCA_ADDR, 0x01, bytes([_out]))
#     sleep(0.1)
#     _i2c.writeto_mem(_TCA_ADDR, 0x01, bytes([_out | 0x02]))
#     sleep(0.2)
#     print("Display reset complete")
# except Exception as e:
#     print("TCA9554 reset failed:", e)
# del _i2c

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
    dc=-1,
    cs=_LCD_CS,
    freq=_LCD_FREQ,
    spi_mode=3,
    quad=True,
)

buf1, buf2 = _allocate_draw_buffers(
    display_bus,
    _WIDTH,
    _DRAW_BUFFER_LINES,
    lv.COLOR_FORMAT.RGB565,
)

print("Initializing AXS15231B display...")
display = axs15231b.AXS15231B(
    data_bus=display_bus,
    display_width=_WIDTH,
    display_height=_HEIGHT,
    backlight_pin=None,
    reset_pin=None,
    color_space=lv.COLOR_FORMAT.RGB565,
    rgb565_byte_swap=True,
    frame_buffer1=buf1,
    frame_buffer2=buf2,
)
_install_axs15231b_qspi_workarounds(display)

_bl_pin.value(1)
print("Backlight forced on")

_screen_w = _WIDTH
_screen_h = _HEIGHT
print("Rotation left at 0 degrees for QSPI bring-up")

print("Display ready")

th = task_handler.TaskHandler()

scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)

print("Registering filesystem...")
fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")

print("Loading semiblock_logo_2.png...")
logo_img = lv.image(scrn)
logo_img.set_src("S:semiblock_logo_2.png")
logo_img.align(lv.ALIGN.CENTER, 0, 0)

lv.task_handler()
lv.refr_now(None)

print("Image displayed")

while True:
    lv.task_handler()
    sleep(0.1)
