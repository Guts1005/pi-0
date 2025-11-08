#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import threading
import os

class GPIOHandler:
    def __init__(self, main_window):
        self.main_window = main_window
        # Define GPIO pins.
        self.btn_video = 17   # Video toggle pushbutton.
        self.btn_image = 27   # Image capture pushbutton.
        self.btn_audio = 22   # Audio toggle pushbutton.
        self.led_video = 23   # Video indicator LED.
        self.led_audio = 24   # Audio indicator LED.
        self.led_system = 25  # System "alive" LED.

        # Setup GPIO.
        GPIO.setmode(GPIO.BCM)
        # Setup buttons as inputs with pull-up resistors.
        GPIO.setup(self.btn_video, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.btn_image, GPIO.IN)
        GPIO.setup(self.btn_audio, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # Setup LEDs as outputs.
        GPIO.setup(self.led_video, GPIO.OUT)
        GPIO.setup(self.led_audio, GPIO.OUT)
        GPIO.setup(self.led_system, GPIO.OUT)

        # Turn the system LED on.
        GPIO.output(self.led_system, GPIO.HIGH)

        self.running = True
        # Optimized polling interval for Pi Zero 2 W
        # 0.1s is sufficient for button responsiveness while reducing CPU load
        self.poll_interval = 0.1
        
        # Improved debouncing: track last state and debounce time
        self.video_pressed = False
        self.image_pressed = False
        self.audio_pressed = False
        self.debounce_time = 0.05  # 50ms debounce
        
        self.poll_thread = threading.Thread(target=self.poll_gpio, daemon=True)
        self.poll_thread.start()
        
        # Set lower thread priority to prevent GPIO polling from blocking critical operations
        self._set_thread_priority()

    def _set_thread_priority(self):
        """Set thread priority to low to prevent GPIO polling from blocking critical operations"""
        try:
            if hasattr(os, 'nice'):
                os.nice(5)  # Lower priority
        except (OSError, AttributeError):
            pass

    def poll_gpio(self):
        """
        Optimized GPIO polling for Pi Zero 2 W:
        - Improved debouncing to prevent false triggers
        - Error handling to prevent crashes
        - Efficient state checking
        """
        last_video_state = GPIO.HIGH
        last_image_state = GPIO.HIGH
        last_audio_state = GPIO.HIGH
        video_press_time = 0
        image_press_time = 0
        audio_press_time = 0

        while self.running:
            try:
                current_time = time.time()
                
                # Check pushbuttons (active low) with improved debouncing
                video_state = GPIO.input(self.btn_video)
                image_state = GPIO.input(self.btn_image)
                audio_state = GPIO.input(self.btn_audio)
                
                # Video button - debounced edge detection
                if video_state == GPIO.LOW:
                    if last_video_state == GPIO.HIGH:
                        # Button just pressed, record time
                        video_press_time = current_time
                    elif not self.video_pressed and (current_time - video_press_time) >= self.debounce_time:
                        # Button has been pressed for debounce period, trigger action
                        self.video_pressed = True
                        try:
                            self.main_window.toggle_video_recording()
                        except Exception as e:
                            print(f"Error toggling video: {e}")
                else:
                    # Button released
                    self.video_pressed = False
                last_video_state = video_state
                
                # Image button - debounced edge detection
                if image_state == GPIO.LOW:
                    if last_image_state == GPIO.HIGH:
                        # Button just pressed, record time
                        image_press_time = current_time
                    elif not self.image_pressed and (current_time - image_press_time) >= self.debounce_time:
                        # Button has been pressed for debounce period, trigger action
                        self.image_pressed = True
                        try:
                            self.main_window.handle_capture_image()
                        except Exception as e:
                            print(f"Error capturing image: {e}")
                else:
                    # Button released
                    self.image_pressed = False
                last_image_state = image_state
                
                # Audio button - debounced edge detection
                if audio_state == GPIO.LOW:
                    if last_audio_state == GPIO.HIGH:
                        # Button just pressed, record time
                        audio_press_time = current_time
                    elif not self.audio_pressed and (current_time - audio_press_time) >= self.debounce_time:
                        # Button has been pressed for debounce period, trigger action
                        self.audio_pressed = True
                        try:
                            self.main_window.toggle_audio_recording()
                        except Exception as e:
                            print(f"Error toggling audio: {e}")
                else:
                    # Button released
                    self.audio_pressed = False
                last_audio_state = audio_state
                
                # Update LED states based on the MainWindow flags (with error handling)
                try:
                    GPIO.output(self.led_video, GPIO.HIGH if self.main_window.video_recording else GPIO.LOW)
                    GPIO.output(self.led_audio, GPIO.HIGH if self.main_window.audio_recording else GPIO.LOW)
                except Exception as e:
                    print(f"Error updating LEDs: {e}")
                
                time.sleep(self.poll_interval)
                
            except Exception as e:
                print(f"GPIO polling error: {e}")
                time.sleep(self.poll_interval)  # Continue polling even on error

    def cleanup(self):
        self.running = False
        self.poll_thread.join()
        # Turn off the system LED.
        GPIO.output(self.led_system, GPIO.LOW)
        GPIO.cleanup()
