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
_I2C_SDA = 8
_I2C_SCL = 7

# Touch settings
_TOUCH_I2C_ADDR = 0x38
_TOUCH_INT = 4
_TOUCH_RST = None

# # WiFi credentials
# SSID = "peter 2.4G"
# PASSWORD = "peter1234"
SSID = "perfect group"
PASSWORD = "LanghamPlace51#"

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

# Register filesystem driver
print("Registering filesystem...")
fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")

# Create logo at top
logo_img = lv.image(scrn)
logo_img.set_src("S:semiblock.png")
logo_img.align(lv.ALIGN.TOP_MID, 0, 10)

# Create status label
status_label = lv.label(scrn)
status_label.set_text("Scanning WiFi networks...")
status_label.align(lv.ALIGN.TOP_MID, 0, 90)
status_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
status_label.set_style_text_font(lv.font_montserrat_14, 0)

# Initial refresh
lv.task_handler()
lv.refr_now(None)

# Scan WiFi networks
print("Scanning WiFi networks...")
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
networks = wlan.scan()

# Sort by signal strength (RSSI)
networks_sorted = sorted(networks, key=lambda x: x[3], reverse=True)

# Create scrollable list for WiFi networks
wifi_list = lv.list(scrn)
wifi_list.set_size(440, 200)
wifi_list.align(lv.ALIGN.TOP_MID, 0, 120)
wifi_list.set_style_bg_color(lv.color_hex(0x222222), 0)
wifi_list.set_style_border_width(2, 0)
wifi_list.set_style_border_color(lv.color_hex(0x4CAF50), 0)

selected_ssid = None
selected_password = ""
selected_auth = 0

def show_keyboard_screen(ssid, auth):
    """Show password entry keyboard screen"""
    global selected_ssid, selected_auth, selected_password
    selected_ssid = ssid
    selected_auth = auth
    selected_password = ""
    
    # Hide WiFi list and status
    wifi_list.add_flag(lv.obj.FLAG.HIDDEN)
    status_label.add_flag(lv.obj.FLAG.HIDDEN)
    
    # Shrink logo
    logo_img.set_size(150, 50)
    logo_img.align(lv.ALIGN.TOP_MID, 0, 5)
    
    # Create password entry screen
    pwd_label = lv.label(scrn)
    pwd_label.set_text(f"WiFi: {ssid}")
    pwd_label.align(lv.ALIGN.TOP_MID, 0, 60)
    pwd_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
    pwd_label.set_style_text_font(lv.font_montserrat_14, 0)
    
    # Password display
    pwd_display = lv.textarea(scrn)
    pwd_display.set_size(400, 40)
    pwd_display.align(lv.ALIGN.TOP_MID, 0, 85)
    pwd_display.set_placeholder_text("Enter password...")
    pwd_display.set_password_mode(True)
    pwd_display.set_one_line(True)
    
    # Create keyboard
    kb = lv.keyboard(scrn)
    kb.set_size(480, 180)
    kb.align(lv.ALIGN.BOTTOM_MID, 0, 0)
    kb.set_textarea(pwd_display)
    
    def kb_event(event):
        global selected_password
        code = event.get_code()
        if code == lv.EVENT.READY or code == lv.EVENT.CANCEL:
            selected_password = pwd_display.get_text()
            print(f"Password entered: {'*' * len(selected_password)}")
            # Restore logo size
            logo_img.set_zoom(256)
            logo_img.align(lv.ALIGN.TOP_MID, 0, 10)
            # Clean up keyboard screen
            kb.delete()
            pwd_display.delete()
            pwd_label.delete()
            # Start WiFi connection
            connect_to_wifi(selected_ssid, selected_password)
    
    kb.add_event_cb(kb_event, lv.EVENT.READY, None)
    kb.add_event_cb(kb_event, lv.EVENT.CANCEL, None)
    
    lv.task_handler()
    lv.refr_now(None)

def wifi_btn_event(event, ssid, auth):
    print(f"Selected SSID: {ssid}, Auth: {auth}")
    if auth > 0:  # Secured network
        show_keyboard_screen(ssid, auth)
    else:  # Open network
        connect_to_wifi(ssid, "")

# Add WiFi networks to list
for net in networks_sorted[:10]:  # Show top 10 networks
    ssid = net[0].decode('utf-8') if isinstance(net[0], bytes) else net[0]
    rssi = net[3]
    auth = net[4]
    
    # Create signal strength indicator
    if rssi > -50:
        signal = "▂▄▆█"
    elif rssi > -60:
        signal = "▂▄▆"
    elif rssi > -70:
        signal = "▂▄"
    else:
        signal = "▂"
    
    # Create lock icon for secured networks
    lock = "🔒" if auth > 0 else ""
    
    btn_text = f"{signal} {ssid} {lock}"
    btn = wifi_list.add_button(None, btn_text)
    btn.add_event_cb(lambda e, s=ssid, a=auth: wifi_btn_event(e, s, a), lv.EVENT.CLICKED, None)

status_label.set_text(f"Found {len(networks)} networks")

# Update display
lv.task_handler()
lv.refr_now(None)

def connect_to_wifi(ssid, password):
    """Connect to selected WiFi network"""
    # Show connecting status
    wifi_list.add_flag(lv.obj.FLAG.HIDDEN)
    status_label.clear_flag(lv.obj.FLAG.HIDDEN)
    status_label.set_text(f"Connecting to {ssid}...")
    status_label.align(lv.ALIGN.CENTER, 0, 0)
    lv.task_handler()
    lv.refr_now(None)
    
    print(f"Connecting to WiFi: {ssid}")
    print("WiFi Status Codes:")
    print("  1000 = STAT_IDLE")
    print("  1001 = STAT_CONNECTING") 
    print("  1010 = STAT_GOT_IP (Connected)")
    print("  201 = STAT_WRONG_PASSWORD")
    print("  202 = STAT_NO_AP_FOUND")
    print("  203 = STAT_CONNECT_FAIL")
    print()
    
    wlan.connect(ssid, password)
    
    # Wait for connection
    max_wait = 30
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
            status_label.set_text(f"Failed to connect to {ssid}")
            status_label.set_style_text_color(lv.color_hex(0xFF0000), 0)
            lv.task_handler()
            sleep(3)
            # Show WiFi list again
            wifi_list.clear_flag(lv.obj.FLAG.HIDDEN)
            status_label.set_text(f"Found {len(networks)} networks")
            status_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
            status_label.align(lv.ALIGN.TOP_MID, 0, 90)
            return
        
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
        status_label.set_text(f"Connected! IP: {ip}")
        print(f'Connected! IP: {ip}')
        
        lv.task_handler()
        lv.refr_now(None)
        sleep(2)
        
        # Hide status and continue to main app
        status_label.add_flag(lv.obj.FLAG.HIDDEN)
        show_main_app()
    else:
        status_label.set_text("Connection timeout")
        status_label.set_style_text_color(lv.color_hex(0xFF0000), 0)
        lv.task_handler()
        sleep(3)
        # Show WiFi list again
        wifi_list.clear_flag(lv.obj.FLAG.HIDDEN)
        status_label.set_text(f"Found {len(networks)} networks")
        status_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        status_label.align(lv.ALIGN.TOP_MID, 0, 90)

def show_main_app():
    """Show the main application after WiFi connection"""
    # Create keypad screen
    code_input = ""
    code_complete = False
    
    # Create display label for entered code
    code_display = lv.label(scrn)
    code_display.set_text("Enter 4-digit code:")
    code_display.align(lv.ALIGN.TOP_MID, 0, 100)
    code_display.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
    code_display.set_style_text_font(lv.font_montserrat_16, 0)
    
    code_label = lv.label(scrn)
    code_label.set_text("____")
    code_label.align(lv.ALIGN.TOP_MID, 0, 140)
    code_label.set_style_text_color(lv.color_hex(0x00FF00), 0)
    code_label.set_style_text_font(lv.font_montserrat_16, 0)
    
    # Button event handlers
    def num_btn_event_with_num(event, num):
        global code_input
        if len(code_input) < 4:
            code_input += str(num)
            display_text = code_input + "_" * (4 - len(code_input))
            code_label.set_text(display_text)
            print(f"Code: {code_input}")
    
    def clear_btn_event(event):
        global code_input
        code_input = ""
        code_label.set_text("____")
        print("Code cleared")
    
    def enter_btn_event(event):
        global code_input, code_complete
        print(f"Enter button pressed! Code length: {len(code_input)}")
        if len(code_input) == 4:
            code_complete = True
            print(f"Code entered: {code_input}")
        else:
            print(f"Need 4 digits, only have {len(code_input)}")
    
    # Create number buttons (3x4 grid)
    btn_width = 70
    btn_height = 50
    btn_spacing = 8
    start_x = (480 - (3 * btn_width + 2 * btn_spacing)) // 2
    start_y = 100
    
    buttons = []
    for i in range(1, 10):
        row = (i - 1) // 3
        col = (i - 1) % 3
        
        btn = lv.button(scrn)
        btn.set_size(btn_width, btn_height)
        btn.set_pos(start_x + col * (btn_width + btn_spacing), 
                   start_y + row * (btn_height + btn_spacing))
        btn.set_style_bg_color(lv.color_hex(0x4444FF), 0)
        
        label = lv.label(btn)
        label.set_text(str(i))
        label.set_style_text_font(lv.font_montserrat_16, 0)
        label.center()
        
        # Use lambda with default argument to capture the value
        btn.add_event_cb(lambda e, num=i: num_btn_event_with_num(e, num), lv.EVENT.CLICKED, None)
        buttons.append(btn)
    
    # Button 0
    btn_0 = lv.button(scrn)
    btn_0.set_size(btn_width, btn_height)
    btn_0.set_pos(start_x + btn_width + btn_spacing, 
                 start_y + 3 * (btn_height + btn_spacing))
    btn_0.set_style_bg_color(lv.color_hex(0x4444FF), 0)
    
    label_0 = lv.label(btn_0)
    label_0.set_text("0")
    label_0.set_style_text_font(lv.font_montserrat_16, 0)
    label_0.center()
    
    btn_0.add_event_cb(lambda e: num_btn_event_with_num(e, 0), lv.EVENT.CLICKED, None)
    
    # Clear button
    btn_clear = lv.button(scrn)
    btn_clear.set_size(btn_width, btn_height)
    btn_clear.set_pos(start_x, start_y + 3 * (btn_height + btn_spacing))
    btn_clear.set_style_bg_color(lv.color_hex(0xFF4444), 0)
    
    label_clear = lv.label(btn_clear)
    label_clear.set_text("CLR")
    label_clear.set_style_text_font(lv.font_montserrat_16, 0)
    label_clear.center()
    
    btn_clear.add_event_cb(clear_btn_event, lv.EVENT.CLICKED, None)
    
    # Enter button
    btn_enter = lv.button(scrn)
    btn_enter.set_size(btn_width, btn_height)
    btn_enter.set_pos(start_x + 2 * (btn_width + btn_spacing), 
                     start_y + 3 * (btn_height + btn_spacing))
    btn_enter.set_style_bg_color(lv.color_hex(0x44FF44), 0)
    
    label_enter = lv.label(btn_enter)
    label_enter.set_text("OK")
    label_enter.set_style_text_font(lv.font_montserrat_16, 0)
    label_enter.center()
    
    btn_enter.add_event_cb(enter_btn_event, lv.EVENT.CLICKED, None)
    btn_enter.add_event_cb(enter_btn_event, lv.EVENT.PRESSED, None)
    
    lv.task_handler()
    lv.refr_now(None)
    
    # Wait for code entry
    print("Waiting for 4-digit code...")
    while not code_complete:
        lv.task_handler()
        sleep(0.05)
    
    # Code entered, fetch from server
    print(f"Fetching code with: {code_input}")
    code_display.set_text("Fetching code...")
    lv.task_handler()
    
    try:
        import urequests
        url = f"https://build.semiblock.ai/api/getProject?code={code_input}"
        print(f"URL: {url}")
        response = urequests.get(url)
        if response.status_code == 200:
            code = response.text
            print(f"Code received ({len(code)} bytes)")
            code_display.set_text("Executing code...")
            lv.task_handler()
            sleep(1)
            
            # Execute the code
            exec(code)
        else:
            print(f"Failed to fetch code: HTTP {response.status_code}")
            code_display.set_text(f"Fetch failed: {response.status_code}")
            code_display.set_style_text_color(lv.color_hex(0xFF0000), 0)
        response.close()
    except Exception as e:
        print(f"Error fetching/executing code: {e}")
        code_display.set_text(f"Error: {str(e)}")
        code_display.set_style_text_color(lv.color_hex(0xFF0000), 0)

lv.task_handler()
lv.refr_now(None)

# Keep display active
print("Setup complete")
while True:
    lv.task_handler()
    sleep(0.1)
