import lcd_bus
import machine
from time import sleep, ticks_ms
import st7796
import lvgl as lv
import i2c
import ft6x36
import pointer_framework
import task_handler
import random

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

if not indev.is_calibrated:
    indev.calibrate()

print("Display ready")

# Initialize task handler for LVGL
th = task_handler.TaskHandler()

# Get active screen
scrn = lv.screen_active()
scrn.set_style_bg_color(lv.color_hex(0x000000), 0)  # Black background

# Game constants
GRID_SIZE = 13
GRID_WIDTH = 20
GRID_HEIGHT = 22
CELL_SIZE = GRID_SIZE

# Game variables
snake = [[12, 10], [11, 10], [10, 10]]  # Start with 3 segments
direction = [1, 0]  # Moving right [dx, dy]
next_direction = [1, 0]
food = [random.randint(0, GRID_WIDTH-1), random.randint(0, GRID_HEIGHT-1)]
score = 0
game_over = False
game_speed = 200  # milliseconds per move

# Create game area background
game_area = lv.obj(scrn)
game_area.set_size(GRID_WIDTH * GRID_SIZE, GRID_HEIGHT * GRID_SIZE)
game_area.align(lv.ALIGN.TOP_LEFT, 10, 10)
game_area.set_style_bg_color(lv.color_hex(0x003300), 0)
game_area.set_style_border_width(2, 0)
game_area.set_style_border_color(lv.color_hex(0x00FF00), 0)
game_area.set_style_pad_all(0, 0)

# Create objects pool for snake segments and food
snake_objects = []
food_object = None

# Score label
score_label = lv.label(scrn)
score_label.set_text(f"Score: {score}")
score_label.align(lv.ALIGN.TOP_LEFT, 280, 20)
score_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
score_label.set_style_text_font(lv.font_montserrat_16, 0)

# Game over label (hidden initially)
game_over_label = lv.label(scrn)
game_over_label.set_text("GAME OVER!")
game_over_label.align(lv.ALIGN.CENTER, 0, -30)
game_over_label.set_style_text_color(lv.color_hex(0xFF0000), 0)
game_over_label.set_style_text_font(lv.font_montserrat_16, 0)
game_over_label.add_flag(lv.obj.FLAG.HIDDEN)

# Control buttons
btn_size = 50

# Up button
btn_up = lv.button(scrn)
btn_up.set_size(btn_size, btn_size)
btn_up.set_pos(340, 60)
btn_up.set_style_bg_color(lv.color_hex(0x4444FF), 0)
label_up = lv.label(btn_up)
label_up.set_text("up")
label_up.set_style_text_font(lv.font_montserrat_16, 0)
label_up.center()

# Down button
btn_down = lv.button(scrn)
btn_down.set_size(btn_size, btn_size)
btn_down.set_pos(340, 170)
btn_down.set_style_bg_color(lv.color_hex(0x4444FF), 0)
label_down = lv.label(btn_down)
label_down.set_text("dn")
label_down.set_style_text_font(lv.font_montserrat_16, 0)
label_down.center()

# Left button
btn_left = lv.button(scrn)
btn_left.set_size(btn_size, btn_size)
btn_left.set_pos(285, 115)
btn_left.set_style_bg_color(lv.color_hex(0x4444FF), 0)
label_left = lv.label(btn_left)
label_left.set_text("<")
label_left.set_style_text_font(lv.font_montserrat_16, 0)
label_left.center()

# Right button
btn_right = lv.button(scrn)
btn_right.set_size(btn_size, btn_size)
btn_right.set_pos(395, 115)
btn_right.set_style_bg_color(lv.color_hex(0x4444FF), 0)
label_right = lv.label(btn_right)
label_right.set_text(">")
label_right.set_style_text_font(lv.font_montserrat_16, 0)
label_right.center()

# Restart button
btn_restart = lv.button(scrn)
btn_restart.set_size(100, 40)
btn_restart.set_pos(295, 240)
btn_restart.set_style_bg_color(lv.color_hex(0xFF4444), 0)
label_restart = lv.label(btn_restart)
label_restart.set_text("RESTART")
label_restart.set_style_text_font(lv.font_montserrat_14, 0)
label_restart.center()

# Button event handlers
def btn_up_event(event):
    global next_direction
    if direction[1] != 1:  # Can't go up if moving down
        next_direction = [0, -1]

def btn_down_event(event):
    global next_direction
    if direction[1] != -1:  # Can't go down if moving up
        next_direction = [0, 1]

def btn_left_event(event):
    global next_direction
    if direction[0] != 1:  # Can't go left if moving right
        next_direction = [-1, 0]

def btn_right_event(event):
    global next_direction
    if direction[0] != -1:  # Can't go right if moving left
        next_direction = [1, 0]

def btn_restart_event(event):
    global snake, direction, next_direction, food, score, game_over
    snake = [[12, 10], [11, 10], [10, 10]]
    direction = [1, 0]
    next_direction = [1, 0]
    food = [random.randint(0, GRID_WIDTH-1), random.randint(0, GRID_HEIGHT-1)]
    score = 0
    game_over = False
    score_label.set_text(f"Score: {score}")
    game_over_label.add_flag(lv.obj.FLAG.HIDDEN)
    draw_game()

btn_up.add_event_cb(btn_up_event, lv.EVENT.CLICKED, None)
btn_down.add_event_cb(btn_down_event, lv.EVENT.CLICKED, None)
btn_left.add_event_cb(btn_left_event, lv.EVENT.CLICKED, None)
btn_right.add_event_cb(btn_right_event, lv.EVENT.CLICKED, None)
btn_restart.add_event_cb(btn_restart_event, lv.EVENT.CLICKED, None)

def draw_game():
    """Draw the entire game state"""
    global snake_objects, food_object
    
    # Clear old snake objects
    for obj in snake_objects:
        obj.delete()
    snake_objects = []
    
    # Draw snake segments
    for i, segment in enumerate(snake):
        seg_obj = lv.obj(game_area)
        seg_obj.set_size(CELL_SIZE - 2, CELL_SIZE - 2)
        seg_obj.set_pos(segment[0] * CELL_SIZE, segment[1] * CELL_SIZE)
        color = lv.color_hex(0x00FF00) if i == 0 else lv.color_hex(0x00AA00)
        seg_obj.set_style_bg_color(color, 0)
        seg_obj.set_style_border_width(0, 0)
        seg_obj.set_style_radius(2, 0)
        snake_objects.append(seg_obj)
    
    # Clear old food object
    if food_object:
        food_object.delete()
    
    # Draw food
    food_object = lv.obj(game_area)
    food_object.set_size(CELL_SIZE - 2, CELL_SIZE - 2)
    food_object.set_pos(food[0] * CELL_SIZE, food[1] * CELL_SIZE)
    food_object.set_style_bg_color(lv.color_hex(0xFF0000), 0)
    food_object.set_style_border_width(0, 0)
    food_object.set_style_radius(CELL_SIZE // 2, 0)

def update_game():
    """Update game logic"""
    global snake, direction, next_direction, food, score, game_over
    
    if game_over:
        return
    
    # Update direction
    direction = next_direction
    
    # Calculate new head position
    new_head = [
        snake[0][0] + direction[0],
        snake[0][1] + direction[1]
    ]
    
    # Check wall collision
    if (new_head[0] < 0 or new_head[0] >= GRID_WIDTH or
        new_head[1] < 0 or new_head[1] >= GRID_HEIGHT):
        game_over = True
        game_over_label.set_style_opa(lv.OPA.COVER, 0)
        return
    
    # Check self collision
    if new_head in snake:
        game_over = True
        game_over_label.set_style_opa(lv.OPA.COVER, 0)
        return
    
    # Add new head
    snake.insert(0, new_head)
    
    # Check food collision
    if new_head == food:
        score += 10
        score_label.set_text(f"Score: {score}")
        # Generate new food
        while True:
            food[0] = random.randint(0, GRID_WIDTH-1)
            food[1] = random.randint(0, GRID_HEIGHT-1)
            if food not in snake:
                break
    else:
        # Remove tail if no food eaten
        snake.pop()
    
    draw_game()

# Initial draw
draw_game()

# Refresh display
lv.task_handler()
lv.refr_now(None)

print("Snake game ready!")

# Game loop
last_update = ticks_ms()
while True:
    lv.task_handler()
    
    current_time = ticks_ms()
    if current_time - last_update >= game_speed:
        update_game()
        last_update = current_time
    
    sleep(0.02)
