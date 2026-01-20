from machine import Pin, SoftI2C, ADC, PWM, UART
from time import sleep,sleep_ms, sleep_us
import Servo

servo1 = Servo(1)
servo1.angle(45)
servo1.angle(-60)