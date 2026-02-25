import lcd_bus
import machine
from time import sleep
import lvgl as lv
import builtins
builtins.lv = lv
import axs15231b
import random
import i2c
import axs15231
import pointer_framework
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
_I2C_SDA = 8
_I2C_SCL = 7

# Touch settings
_TOUCH_I2C_ADDR = 0x38
_TOUCH_INT = 4
_TOUCH_RST = None

# Game constants (display is rotated to 480x320)
SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320
BIRD_SIZE = 30
PIPE_WIDTH = 50
PIPE_GAP = 120
GRAVITY = 0.7
JUMP_STRENGTH = -4
PIPE_SPEED = 3

print("Initializing SPI bus...")
spi_bus = machine.SPI.Bus(host=_HOST, mosi=_MOSI, miso=_MISO, sck=_SCK)

print("Initializing display bus...")
display_bus = lcd_bus.SPIBus(spi_bus=spi_bus, freq=_LCD_FREQ, dc=_DC, cs=_LCD_CS)

buf1 = display_bus.allocate_framebuffer(100*320*2, lcd_bus.MEMORY_SPIRAM)
buf2 = display_bus.allocate_framebuffer(100*320*2, lcd_bus.MEMORY_SPIRAM)

print("Initializing AXS15231B display...")
display = axs15231b.AXS15231B(
    data_bus=display_bus,
    display_width=_WIDTH,
    display_height=_HEIGHT,
    backlight_pin=_BL,
    reset_pin=None,
    backlight_on_state=axs15231b.STATE_HIGH,
    color_space=lv.COLOR_FORMAT.RGB565,
    color_byte_order=axs15231b.BYTE_ORDER_BGR,
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
touch_dev = i2c.I2C.Device(bus=i2c_bus, dev_id=_TOUCH_I2C_ADDR, reg_bits=axs15231.BITS)
indev = axs15231.AXS15231(touch_dev, startup_rotation=pointer_framework.lv.DISPLAY_ROTATION._90)
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
scrn.set_style_bg_color(lv.color_hex(0x87CEEB), 0)  # Sky blue background
scrn.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

# Game variables
bird_y = float(SCREEN_HEIGHT // 2)
bird_velocity = 0.0
pipes = []
score = 0
game_over = False
game_started = False

# Create bird (using a circle)
bird = lv.obj(scrn)
bird.set_size(BIRD_SIZE, BIRD_SIZE)
bird.set_style_radius(BIRD_SIZE // 2, 0)
bird.set_style_bg_color(lv.color_hex(0xFFD700), 0)  # Golden yellow
bird.set_style_border_width(2, 0)
bird.set_style_border_color(lv.color_hex(0xFF8C00), 0)
bird.set_pos(100, int(bird_y))

# Create score label
score_label = lv.label(scrn)
score_label.set_text("Score: 0")
score_label.set_pos(10, 10)
score_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
score_label.set_style_text_font(lv.font_montserrat_16, 0)

# Create start/restart message
msg_label = lv.label(scrn)
msg_label.set_text("TAP TO START")
msg_label.align(lv.ALIGN.CENTER, 0, 120)
msg_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
msg_label.set_style_text_font(lv.font_montserrat_16, 0)

# Register filesystem driver
print("Registering filesystem...")
fs_drv = lv.fs_drv_t()
fs_register(fs_drv, "S")

# Create start image
# start_img = lv.image(scrn)
# start_img.set_src("S:semiblockGames100.jpg")
# start_img.set_size(200, 100)
# start_img.align(lv.ALIGN.CENTER, 0, 0)

# Jump trigger flag
jump_requested = False

# Create pipe class
class Pipe:
    def __init__(self, x, gap_y):
        # Top pipe
        self.top = lv.obj(scrn)
        self.top.set_size(PIPE_WIDTH, gap_y)
        self.top.set_style_bg_color(lv.color_hex(0x228B22), 0)  # Green
        self.top.set_style_border_width(2, 0)
        self.top.set_style_border_color(lv.color_hex(0x006400), 0)
        self.top.set_pos(x, 0)
        
        # Bottom pipe
        self.bottom = lv.obj(scrn)
        self.bottom.set_size(PIPE_WIDTH, SCREEN_HEIGHT - gap_y - PIPE_GAP)
        self.bottom.set_style_bg_color(lv.color_hex(0x228B22), 0)
        self.bottom.set_style_border_width(2, 0)
        self.bottom.set_style_border_color(lv.color_hex(0x006400), 0)
        self.bottom.set_pos(x, gap_y + PIPE_GAP)
        
        self.x = x
        self.gap_y = gap_y
        self.scored = False
    
    def update(self):
        self.x -= PIPE_SPEED
        self.top.set_pos(self.x, 0)
        self.bottom.set_pos(self.x, self.gap_y + PIPE_GAP)
    
    def is_off_screen(self):
        return self.x < -PIPE_WIDTH
    
    def delete(self):
        lv.obj.delete(self.top)
        lv.obj.delete(self.bottom)
    
    def collides_with_bird(self, bird_x, bird_y):
        # Check if bird is in pipe's x range
        if bird_x + BIRD_SIZE > self.x and bird_x < self.x + PIPE_WIDTH:
            # Check if bird hits top or bottom pipe
            if bird_y < self.gap_y or bird_y + BIRD_SIZE > self.gap_y + PIPE_GAP:
                return True
        return False

def spawn_pipe():
    gap_y = random.randint(50, SCREEN_HEIGHT - PIPE_GAP - 50)
    pipes.append(Pipe(SCREEN_WIDTH, gap_y))

def reset_game():
    global bird_y, bird_velocity, pipes, score, game_over, game_started
    
    # Reset bird
    bird_y = float(SCREEN_HEIGHT // 2)
    bird_velocity = 0.0
    bird.set_pos(100, int(bird_y))
    
    # Remove all pipes
    for pipe in pipes:
        pipe.delete()
    pipes.clear()
    
    # Reset score
    score = 0
    score_label.set_text("Score: 0")
    
    game_over = False
    game_started = False
    msg_label.set_text("TAP TO START")
    # start_img.set_style_opa(lv.OPA.COVER, 0)

def bird_jump():
    global bird_velocity, game_started
    if not game_started:
        game_started = True
        msg_label.set_text("")
        # start_img.set_style_opa(lv.OPA.TRANSP, 0)
        spawn_pipe()
    
    if not game_over:
        bird_velocity = JUMP_STRENGTH

# Touch event handler
def touch_event_cb(event):
    global jump_requested
    code = event.get_code()
    if code == lv.EVENT.PRESSED or code == lv.EVENT.CLICKED:
        jump_requested = True

# Add event handler to the screen itself
scrn.add_event_cb(touch_event_cb, lv.EVENT.PRESSED, None)
scrn.add_event_cb(touch_event_cb, lv.EVENT.CLICKED, None)

# Game variables for timing
frame_count = 0
pipe_spawn_interval = 150  # Frames between pipes

print("Game ready! Tap to start...")

# Initial refresh
lv.task_handler()
lv.refr_now(None)

# Game loop
while True:
    # Handle jump request
    if jump_requested:
        jump_requested = False
        if game_over:
            reset_game()
        else:
            bird_jump()
    
    if game_started and not game_over:
        # Update bird physics
        bird_velocity += GRAVITY
        bird_y += bird_velocity
        
        # Check bounds
        if bird_y < 0:
            bird_y = 0
            bird_velocity = 0
        elif bird_y > SCREEN_HEIGHT - BIRD_SIZE:
            game_over = True
            msg_label.set_text("GAME OVER! TAP TO RESTART")
        
        bird.set_pos(100, int(bird_y))
        
        # Spawn pipes
        frame_count += 1
        if frame_count >= pipe_spawn_interval:
            spawn_pipe()
            frame_count = 0
        
        # Update pipes
        for pipe in pipes[:]:
            pipe.update()
            
            # Check collision
            if pipe.collides_with_bird(100, int(bird_y)):
                game_over = True
                msg_label.set_text("GAME OVER! TAP TO RESTART")
            
            # Check scoring
            if not pipe.scored and pipe.x + PIPE_WIDTH < 100:
                pipe.scored = True
                score += 1
                score_label.set_text(f"Score: {score}")
            
            # Remove off-screen pipes
            if pipe.is_off_screen():
                pipe.delete()
                pipes.remove(pipe)
    
    # Refresh display
    lv.task_handler()
    sleep(0.02)  # ~50 FPS
