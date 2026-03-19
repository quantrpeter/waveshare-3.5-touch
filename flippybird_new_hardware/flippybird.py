import lcd_bus
import machine
from time import sleep
import axs15231b
import lvgl as lv
import builtins
builtins.lv = lv
import task_handler
from fs_driver import fs_register
import random
import i2c
import axs15231
import pointer_framework

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
_LCD_CMD_CASET = 0x2A
_LCD_CMD_RAMWR = 0x2C
_LCD_CMD_RASET = 0x2B
_LCD_CMD_RAMWRC = 0x3C
_LCD_QSPI_WRITE_COLOR = 0x32
_DRAW_BUFFER_LINES = 80

_TOUCH_I2C_ADDR = 0x3B

# Game constants (portrait 320x480, no rotation on QSPI panel)
SCREEN_WIDTH = 320
SCREEN_HEIGHT = 480
BIRD_X = 70
BIRD_SIZE = 30
PIPE_WIDTH = 50
PIPE_GAP = 150
GRAVITY = 0.7
JUMP_STRENGTH = -4
PIPE_SPEED = 3
MAX_PIPES = 3

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
        param_buf = display._param_buf

        param_buf[0] = (x1 >> 8) & 0xFF
        param_buf[1] = x1 & 0xFF
        param_buf[2] = (x2 >> 8) & 0xFF
        param_buf[3] = x2 & 0xFF
        display.set_params(_LCD_CMD_CASET, display._param_mv[:4])

        param_buf[0] = (y1 >> 8) & 0xFF
        param_buf[1] = y1 & 0xFF
        param_buf[2] = (y2 >> 8) & 0xFF
        param_buf[3] = y2 & 0xFF
        display.set_params(_LCD_CMD_RASET, display._param_mv[:4])

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

print("Forcing backlight GPIO high...")
_bl_pin = machine.Pin(_BL, machine.Pin.OUT)
_bl_pin.value(1)
sleep(0.05)

print("Opening I2C bus...")
_i2c = machine.SoftI2C(sda=machine.Pin(_I2C_SDA), scl=machine.Pin(_I2C_SCL), freq=400000)
print("I2C scan:", [hex(addr) for addr in _i2c.scan()])

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

print("Initializing AXS15231 touch...")
i2c_bus = i2c.I2C.Bus(host=0, scl=_I2C_SCL, sda=_I2C_SDA)
touch_dev = i2c.I2C.Device(bus=i2c_bus, dev_id=_TOUCH_I2C_ADDR, reg_bits=axs15231.BITS)
indev = axs15231.AXS15231(touch_dev)
print("Touch driver initialized")

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
bird.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
bird.set_style_radius(BIRD_SIZE // 2, 0)
bird.set_style_bg_color(lv.color_hex(0xFFD700), 0)
bird.set_style_border_width(2, 0)
bird.set_style_border_color(lv.color_hex(0xFF8C00), 0)
bird.set_pos(BIRD_X, int(bird_y))

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

jump_requested = False

def _make_pipe_obj():
    o = lv.obj(scrn)
    o.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
    o.set_style_bg_color(lv.color_hex(0x228B22), 0)
    o.set_style_border_width(2, 0)
    o.set_style_border_color(lv.color_hex(0x006400), 0)
    o.add_flag(lv.obj.FLAG.HIDDEN)
    return o

class Pipe:
    def __init__(self):
        self.top = _make_pipe_obj()
        self.bottom = _make_pipe_obj()
        self.x = 0
        self.gap_y = 0
        self.scored = False
        self.active = False

    def activate(self, x, gap_y):
        self.x = x
        self.gap_y = gap_y
        self.scored = False
        self.active = True
        self.top.set_size(PIPE_WIDTH, gap_y)
        self.top.set_pos(x, 0)
        self.top.remove_flag(lv.obj.FLAG.HIDDEN)
        self.bottom.set_size(PIPE_WIDTH, SCREEN_HEIGHT - gap_y - PIPE_GAP)
        self.bottom.set_pos(x, gap_y + PIPE_GAP)
        self.bottom.remove_flag(lv.obj.FLAG.HIDDEN)

    def deactivate(self):
        self.active = False
        self.top.add_flag(lv.obj.FLAG.HIDDEN)
        self.bottom.add_flag(lv.obj.FLAG.HIDDEN)

    def update(self):
        self.x -= PIPE_SPEED
        self.top.set_pos(self.x, 0)
        self.bottom.set_pos(self.x, self.gap_y + PIPE_GAP)

    def is_off_screen(self):
        return self.x < -PIPE_WIDTH

    def collides_with_bird(self, bx, by):
        if bx + BIRD_SIZE > self.x and bx < self.x + PIPE_WIDTH:
            if by < self.gap_y or by + BIRD_SIZE > self.gap_y + PIPE_GAP:
                return True
        return False

pipe_pool = [Pipe() for _ in range(MAX_PIPES)]

def spawn_pipe():
    gap_y = random.randint(50, SCREEN_HEIGHT - PIPE_GAP - 50)
    for p in pipe_pool:
        if not p.active:
            p.activate(SCREEN_WIDTH, gap_y)
            return

def reset_game():
    global bird_y, bird_velocity, score, game_over, game_started
    bird_y = float(SCREEN_HEIGHT // 2)
    bird_velocity = 0.0
    bird.set_pos(BIRD_X, int(bird_y))
    for p in pipe_pool:
        if p.active:
            p.deactivate()
    score = 0
    score_label.set_text("Score: 0")
    game_over = False
    game_started = False
    msg_label.set_text("TAP TO START")

def bird_jump():
    global bird_velocity, game_started
    if not game_started:
        game_started = True
        msg_label.set_text("")
        spawn_pipe()
    if not game_over:
        bird_velocity = JUMP_STRENGTH

def touch_event_cb(event):
    global jump_requested
    code = event.get_code()
    if code == lv.EVENT.PRESSED or code == lv.EVENT.CLICKED:
        jump_requested = True

scrn.add_event_cb(touch_event_cb, lv.EVENT.PRESSED, None)
scrn.add_event_cb(touch_event_cb, lv.EVENT.CLICKED, None)

frame_count = 0
pipe_spawn_interval = 150

print("Game ready! Tap to start...")

lv.task_handler()
lv.refr_now(None)

while True:
    if jump_requested:
        jump_requested = False
        if game_over:
            reset_game()
        else:
            bird_jump()

    if game_started and not game_over:
        bird_velocity += GRAVITY
        bird_y += bird_velocity

        if bird_y < 0:
            bird_y = 0
            bird_velocity = 0
        elif bird_y > SCREEN_HEIGHT - BIRD_SIZE:
            game_over = True
            msg_label.set_text("GAME OVER! TAP TO RESTART")

        bird.set_pos(BIRD_X, int(bird_y))

        frame_count += 1
        if frame_count >= pipe_spawn_interval:
            spawn_pipe()
            frame_count = 0

        for p in pipe_pool:
            if not p.active:
                continue
            p.update()
            if p.collides_with_bird(BIRD_X, int(bird_y)):
                game_over = True
                msg_label.set_text("GAME OVER! TAP TO RESTART")
            if not p.scored and p.x + PIPE_WIDTH < BIRD_X:
                p.scored = True
                score += 1
                score_label.set_text(f"Score: {score}")
            if p.is_off_screen():
                p.deactivate()

    lv.task_handler()
    sleep(0.02)
