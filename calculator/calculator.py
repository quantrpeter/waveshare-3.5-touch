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
_TOUCH_I2C_ADDR = 0x38

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

# Initialize touch in portrait mode (no rotation)
print("Initializing FT6336 touch...")
i2c_bus = i2c.I2C.Bus(host=0, scl=_I2C_SCL, sda=_I2C_SDA, freq=400000, use_locks=False)
touch_dev = i2c.I2C.Device(bus=i2c_bus, dev_id=_TOUCH_I2C_ADDR, reg_bits=ft6x36.BITS)
indev = ft6x36.FT6x36(touch_dev)

print("Touch driver initialized")

# No rotation - use portrait mode
display.set_color_inversion(True)
display.set_backlight(100)
# display.set_rotation(lv.DISPLAY_ROTATION._180)

print("Display ready")

# Initialize task handler for LVGL
th = task_handler.TaskHandler()

# ========== Calculator Logic Class ==========
class Calculator:
    def __init__(self):
        self.current_input = "0"
        self.previous_input = ""
        self.operator = ""
        self.should_reset = False
        
    def input_digit(self, digit):
        if self.should_reset or self.current_input == "0":
            self.current_input = str(digit)
            self.should_reset = False
        else:
            self.current_input += str(digit)
        return self.current_input
    def input_decimal(self):
        if self.should_reset:
            self.current_input = "0."
            self.should_reset = False
        elif "." not in self.current_input:
            self.current_input += "."
        return self.current_input
    
    def set_operator(self, op):
        if self.previous_input and self.operator and not self.should_reset:
            self.calculate()
        
        self.previous_input = self.current_input
        self.operator = op
        self.should_reset = True
        return self.current_input
    
    def calculate(self):
        if not self.previous_input or not self.operator:
            return self.current_input
        
        try:
            prev = float(self.previous_input)
            curr = float(self.current_input)
            result = 0
            
            if self.operator == "+":
                result = prev + curr
            elif self.operator == "-":
                result = prev - curr
            elif self.operator == "×":
                result = prev * curr
            elif self.operator == "÷":
                if curr == 0:
                    return "Error"
                result = prev / curr
            
            # Format result (don't show decimal point for integers)
            if result.is_integer():
                self.current_input = str(int(result))
            else:
                # Limit decimal places
                self.current_input = "{:.10f}".format(result).rstrip('0').rstrip('.')
                
        except:
            self.current_input = "Error"
        
        self.previous_input = ""
        self.operator = ""
        self.should_reset = True
        return self.current_input
    
    def clear(self):
        self.current_input = "0"
        self.previous_input = ""
        self.operator = ""
        self.should_reset = False
        return self.current_input
    
    def clear_entry(self):
        self.current_input = "0"
        self.should_reset = False
        return self.current_input
    
    def backspace(self):
        if len(self.current_input) > 1:
            self.current_input = self.current_input[:-1]
        else:
            self.current_input = "0"
        self.should_reset = False
        return self.current_input

# ========== Create UI ==========
class CalculatorUI:
    def __init__(self):
        self.calc = Calculator()
        self.screen = lv.screen_active()
        self.screen.set_style_bg_color(lv.color_hex(0x121212), 0)
        self.screen.set_style_bg_opa(lv.OPA.COVER, 0)
        
        self.create_display()
        self.create_buttons()
        
    def create_display(self):
        # Display background
        disp_bg = lv.obj(self.screen)
        disp_bg.set_size(280, 80)
        disp_bg.set_align(lv.ALIGN.TOP_MID)
        disp_bg.set_y(30)
        disp_bg.set_style_bg_color(lv.color_hex(0x000000), 0)
        disp_bg.set_style_bg_opa(lv.OPA.COVER, 0)
        disp_bg.set_style_radius(10, 0)
        disp_bg.set_style_border_width(0, 0)
        disp_bg.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        
        # Display text
        self.display_label = lv.label(disp_bg)
        self.display_label.set_text("0")
        self.display_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        self.display_label.set_style_text_font(lv.font_montserrat_16, 0)
        self.display_label.set_align(lv.ALIGN.RIGHT_MID)
        self.display_label.set_x(-20)
        
        # Status display (previous operation)
        self.status_label = lv.label(disp_bg)
        self.status_label.set_text("")
        self.status_label.set_style_text_color(lv.color_hex(0x888888), 0)
        self.status_label.set_style_text_font(lv.font_montserrat_14, 0)
        self.status_label.set_align(lv.ALIGN.TOP_LEFT)
        self.status_label.set_x(20)
        self.status_label.set_y(10)
    
    def create_button(self, parent, x, y, text, width=70, height=60, color=0x333333, text_color=0xFFFFFF, radius=15):
        btn = lv.obj(parent)
        btn.set_size(width, height)
        btn.set_pos(x, y)
        btn.set_style_bg_color(lv.color_hex(color), 0)
        btn.set_style_bg_opa(lv.OPA.COVER, 0)
        btn.set_style_radius(radius, 0)
        btn.set_style_border_width(0, 0)
        btn.set_style_pad_all(0, 0)
        
        label = lv.label(btn)
        label.set_text(text)
        label.set_style_text_color(lv.color_hex(text_color), 0)
        label.set_style_text_font(lv.font_montserrat_16, 0)
        label.center()
        
        return btn
    
    def create_buttons(self):
        # Button container
        btn_container = lv.obj(self.screen)
        btn_container.set_size(300, 340)
        btn_container.set_align(lv.ALIGN.BOTTOM_MID)
        btn_container.set_y(-10)
        btn_container.set_style_bg_color(lv.color_hex(0x121212), 0)
        btn_container.set_style_bg_opa(lv.OPA.COVER, 0)
        btn_container.set_style_border_width(0, 0)
        btn_container.set_style_pad_all(0, 0)
        btn_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        
        # Button definitions (row, col, text, color, text_color)
        buttons = [
            (0, 0, "C", 0xFF5722, 0xFFFFFF),    # Red - Clear
            (0, 1, "CE", 0x4CAF50, 0xFFFFFF),   # Green - Clear Entry
            (0, 2, "BK", 0x4CAF50, 0xFFFFFF),    # Green - Backspace
            (0, 3, "/", 0x2196F3, 0xFFFFFF),    # Blue - Division
            
            (1, 0, "7", 0x555555, 0xFFFFFF),
            (1, 1, "8", 0x555555, 0xFFFFFF),
            (1, 2, "9", 0x555555, 0xFFFFFF),
            (1, 3, "x", 0x2196F3, 0xFFFFFF),    # Blue - Multiplication
            
            (2, 0, "4", 0x555555, 0xFFFFFF),
            (2, 1, "5", 0x555555, 0xFFFFFF),
            (2, 2, "6", 0x555555, 0xFFFFFF),
            (2, 3, "-", 0x2196F3, 0xFFFFFF),    # Blue - Subtraction
            
            (3, 0, "1", 0x555555, 0xFFFFFF),
            (3, 1, "2", 0x555555, 0xFFFFFF),
            (3, 2, "3", 0x555555, 0xFFFFFF),
            (3, 3, "+", 0x2196F3, 0xFFFFFF),    # Blue - Addition
            
            (4, 0, "+/-", 0x555555, 0xFFFFFF),    # Plus/Minus
            (4, 1, "0", 0x555555, 0xFFFFFF),
            (4, 2, ".", 0x555555, 0xFFFFFF),
            (4, 3, "=", 0xFF9800, 0xFFFFFF),    # Orange - Equals
        ]
        
        self.buttons = {}
        for row, col, text, color, text_color in buttons:
            x = 5 + col * 72
            y = 5 + row * 65
            
            btn = self.create_button(btn_container, x, y, text, 68, 60, color, text_color)
            
            btn.add_event_cb(lambda e, t=text: self.button_pressed(t), lv.EVENT.PRESSED, None)
            btn.add_event_cb(lambda e, t=text: self.button_pressed(t), lv.EVENT.CLICKED, None)
            self.buttons[text] = btn
    
    def update_display(self):
        # Update main display
        self.display_label.set_text(self.calc.current_input)
        
        # Update status display
        if self.calc.previous_input and self.calc.operator:
            status = f"{self.calc.previous_input} {self.calc.operator}"
            self.status_label.set_text(status)
        else:
            self.status_label.set_text("")
        
        # Auto adjust font size for long numbers
        text_len = len(self.calc.current_input)
        if text_len > 10:
            font = lv.font_montserrat_14
        else:
            font = lv.font_montserrat_16
        
        self.display_label.set_style_text_font(font, 0)
    
    def button_pressed(self, text):
        print(f"Button pressed: {text}")
        if text.isdigit():
            self.calc.input_digit(text)
        elif text == ".":
            self.calc.input_decimal()
        elif text in ["+", "-", "×", "÷"]:
            self.calc.set_operator(text)
        elif text == "=":
            self.calc.calculate()
        elif text == "C":
            self.calc.clear()
        elif text == "CE":
            self.calc.clear_entry()
        elif text == "⌫":
            self.calc.backspace()
        elif text == "±":
            # Toggle plus/minus sign
            if self.calc.current_input != "0":
                if self.calc.current_input[0] == "-":
                    self.calc.current_input = self.calc.current_input[1:]
                else:
                    self.calc.current_input = "-" + self.calc.current_input
        
        self.update_display()

# Debug touch event handler
def debug_touch(event):
    print(f"Touch event: {event.get_code()}")

# ========== Main Program ==========
if __name__ == "__main__":
    # Initialize UI
    ui = CalculatorUI()
    
    # Add debug touch handler to screen
    scrn = lv.screen_active()
    scrn.add_event_cb(debug_touch, lv.EVENT.PRESSED, None)
    
    # Add title
    title = lv.label(scrn)
    title.set_text("SemiBlock Calculator")
    title.set_style_text_color(lv.color_hex(0xff0F50), 0)
    title.set_style_text_font(lv.font_montserrat_16, 0)
    title.align(lv.ALIGN.TOP_MID, 0, 5)
    
    # Force initial display update
    lv.task_handler()
    lv.refr_now(None)
    
    print("Calculator started! Touch screen to use.")
    
    # Main loop
    while True:
        lv.task_handler()
        sleep(0.01)