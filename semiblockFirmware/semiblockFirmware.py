import lcd_bus
import machine
from time import sleep
import st7796
import lvgl as lv
import i2c
import ft6x36
import pointer_framework
import task_handler
import network

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

# WiFi credentials
SSID = "peter 2.4G"
PASSWORD = "peter1234"

print("Initializing SPI bus...")
spi_bus = machine.SPI.Bus(host=_HOST, mosi=_MOSI, miso=_MISO, sck=_SCK)

print("Initializing display bus...")
display_bus = lcd_bus.SPIBus(spi_bus=spi_bus, freq=_LCD_FREQ, dc=_DC, cs=_LCD_CS)

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
display.set_rotation(lv.DISPLAY_ROTATION._90)
display.set_color_inversion(True)
display.set_backlight(100)

print("Display ready")

# Initialize task handler for LVGL
th = task_handler.TaskHandler()

# Create screen
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)  # Black background
scrn.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

# Create status label
status_label = lv.label(scrn)
status_label.set_text("Connecting to WiFi...")
status_label.align(lv.ALIGN.CENTER, 0, -40)
status_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
status_label.set_style_text_font(lv.font_montserrat_16, 0)

# Create SSID label
ssid_label = lv.label(scrn)
ssid_label.set_text(f"SSID: {SSID}")
ssid_label.align(lv.ALIGN.CENTER, 0, 0)
ssid_label.set_style_text_color(lv.color_hex(0x00FF00), 0)
ssid_label.set_style_text_font(lv.font_montserrat_16, 0)

# Create IP label
ip_label = lv.label(scrn)
ip_label.set_text("IP: ---")
ip_label.align(lv.ALIGN.CENTER, 0, 40)
ip_label.set_style_text_color(lv.color_hex(0x00FFFF), 0)
ip_label.set_style_text_font(lv.font_montserrat_16, 0)

# Initial refresh
lv.task_handler()
lv.refr_now(None)

# Connect to WiFi
print(f"Connecting to WiFi: {SSID}")
print("WiFi Status Codes:")
print("  1000 = STAT_IDLE")
print("  1001 = STAT_CONNECTING") 
print("  1010 = STAT_GOT_IP (Connected)")
print("  201 = STAT_WRONG_PASSWORD")
print("  202 = STAT_NO_AP_FOUND")
print("  203 = STAT_CONNECT_FAIL")
print()

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(SSID, PASSWORD)

# Wait for connection
max_wait = 30  # Increased wait time
while max_wait > 0:
    status = wlan.status()
    print(f'Waiting for connection... Status: {status}')
    
    # Check if connected (status 1010 or 3)
    if status == 1010 or status == 3:
        print("Connection successful!")
        break
    
    # Check if connection failed
    if status in [201, 202, 203] or status < 0:
        print("Connection failed!")
        break
    
    max_wait -= 1
    sleep(1)
    lv.task_handler()

# Check connection status
final_status = wlan.status()
print(f'Final WiFi status: {final_status}')

if final_status == 1010 or final_status == 3:
    status_label.set_text("WiFi Connected!")
    status_label.set_style_text_color(lv.color_hex(0x00FF00), 0)
    ip = wlan.ifconfig()[0]
    ip_label.set_text(f"IP: {ip}")
    print(f'Connected! IP: {ip}')
else:
    status_label.set_text(f"Connection Failed! (Status: {final_status})")
    status_label.set_style_text_color(lv.color_hex(0xFF0000), 0)
    print(f'Network connection failed with status: {final_status}')

lv.task_handler()
lv.refr_now(None)

# Keep display active
print("WiFi setup complete")
while True:
    lv.task_handler()
    sleep(0.1)
