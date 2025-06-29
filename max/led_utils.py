import time
import logging
import queue
import threading
import atexit
from datetime import datetime
from typing import Optional, Dict, List, Any
from enum import Enum

try:
    import adafruit_pixelbuf
    import board
    from adafruit_led_animation.animation.rainbow import Rainbow
    from adafruit_led_animation.animation.rainbowchase import RainbowChase
    from adafruit_led_animation.animation.rainbowcomet import RainbowComet
    from adafruit_led_animation.animation.rainbowsparkle import RainbowSparkle
    from adafruit_led_animation.animation.sparklepulse import SparklePulse
    from adafruit_led_animation.animation.solid import Solid
    from adafruit_raspberry_pi5_neopixel_write import neopixel_write
    NEOPIXEL_AVAILABLE = True
except ImportError:
    logging.warning("NeoPixel libraries not available - LED functionality disabled")
    NEOPIXEL_AVAILABLE = False

from state_class import ThreadSafeState

# LED Configuration
ACTIVE_HOURS = (0, 24)  # 7 PM to 7 AM (19:00 to 07:00)

# Default LED strand configurations
LED_STRANDS = {
    'main': {
        'pin': board.D18,
        'pixels': 48,
        'animation_type': 'rainbow_comet',
        'responds_to_people': True
    },
    'accent': {
        'pin': board.D12,  # Different GPIO pin
        'pixels': 24,
        'animation_type': 'sparkle_pulse',
        'responds_to_people': False
    }
}

# Global flags for safe shutdown
_shutdown_requested = False
_led_controller = None


class AnimationType(Enum):
    """Available animation types"""
    RAINBOW = "rainbow"
    RAINBOW_CHASE = "rainbow_chase" 
    RAINBOW_COMET = "rainbow_comet"
    RAINBOW_SPARKLE = "rainbow_sparkle"
    SPARKLE_PULSE = "sparkle_pulse"
    SOLID = "solid"


class Pi5PixelBuf(adafruit_pixelbuf.PixelBuf):
    """Custom PixelBuf implementation for Raspberry Pi 5 with safety checks"""
    
    def __init__(self, pin, size, **kwargs):
        self._pin = pin
        self._last_transmit_time = 0
        self._min_transmit_interval = 0.005  # Increased from 1ms to 5ms to reduce stuttering
        super().__init__(size=size, **kwargs)

    def _transmit(self, buf):
        """Transmit data with safety checks - NO THREADING"""
        global _shutdown_requested
        
        # Skip if shutdown requested
        if _shutdown_requested:
            return
            
        # Throttle transmissions to prevent overwhelming hardware
        current_time = time.time()
        if current_time - self._last_transmit_time < self._min_transmit_interval:
            return
            
        try:
            # Direct hardware call - no threading to avoid segfaults
            neopixel_write(self._pin, buf)
            self._last_transmit_time = current_time
        except Exception as e:
            logging.error(f"Hardware transmit error on pin {self._pin}: {e}")
            # Don't re-raise - let the system continue


class LEDStrand:
    """Manages a single LED strand with its own animation and state"""
    
    def __init__(self, name: str, pin, num_pixels: int, animation_type: str = 'rainbow_comet'):
        self.name = name
        self.pin = pin
        self.num_pixels = num_pixels
        self.animation_type = AnimationType(animation_type)
        self.pixels = None
        self.animation = None
        self.is_active = False
        self.current_speed = 0.025
        self.current_color = (255, 255, 255)
        self._animate_error_count = 0
        self._max_errors = 5
        self._disabled = False
        
        self._init_hardware()
        self._init_animation()
    
    def _init_hardware(self) -> bool:
        """Initialize the NeoPixel hardware for this strand"""
        if not NEOPIXEL_AVAILABLE or _shutdown_requested:
            return False
            
        try:
            self.pixels = Pi5PixelBuf(
                self.pin, 
                self.num_pixels, 
                auto_write=True, 
                byteorder="RGB"
            )
            logging.info(f"Initialized LED strand '{self.name}' with {self.num_pixels} pixels on pin {self.pin}")
            return True
        except Exception as e:
            logging.error(f"Failed to initialize LED strand '{self.name}': {e}")
            self._disabled = True
            return False
    
    def _create_animation(self, animation_type: AnimationType, **kwargs):
        """Create an animation object of the specified type"""
        if not self.pixels or self._disabled:
            return None
            
        speed = kwargs.get('speed', self.current_speed)
        color = kwargs.get('color', self.current_color)
        
        try:
            if animation_type == AnimationType.RAINBOW:
                return Rainbow(self.pixels, speed=speed, period=2)
            elif animation_type == AnimationType.RAINBOW_CHASE:
                return RainbowChase(self.pixels, speed=speed, size=5, spacing=3)
            elif animation_type == AnimationType.RAINBOW_COMET:
                return RainbowComet(self.pixels, speed=speed, tail_length=12, bounce=True)
            elif animation_type == AnimationType.RAINBOW_SPARKLE:
                return RainbowSparkle(self.pixels, speed=speed, num_sparkles=15)
            elif animation_type == AnimationType.SPARKLE_PULSE:
                return SparklePulse(self.pixels, speed=speed, color=color)
            elif animation_type == AnimationType.SOLID:
                return Solid(self.pixels, color=color)
            else:
                logging.warning(f"Unknown animation type: {animation_type}")
                return None
        except Exception as e:
            logging.error(f"Failed to create {animation_type} animation for '{self.name}': {e}")
            return None
    
    def _init_animation(self):
        """Initialize the default animation for this strand"""
        if not self._disabled:
            self.animation = self._create_animation(self.animation_type)
    
    def set_animation_type(self, animation_type: str, **kwargs) -> bool:
        """Change the animation type for this strand"""
        if self._disabled:
            return False
            
        try:
            new_type = AnimationType(animation_type)
            self.animation_type = new_type
            self.animation = self._create_animation(new_type, **kwargs)
            self._animate_error_count = 0
            logging.info(f"Changed strand '{self.name}' to {animation_type}")
            return True
        except (ValueError, Exception) as e:
            logging.error(f"Failed to set animation type for '{self.name}': {e}")
            return False
    
    def set_speed(self, speed: float) -> bool:
        """Set the animation speed for this strand"""
        if self._disabled:
            return False
            
        speed = max(0.001, min(0.1, speed))
        
        if self.current_speed != speed:
            self.current_speed = speed
            self.animation = self._create_animation(self.animation_type, speed=speed)
            logging.debug(f"Set strand '{self.name}' speed to {speed}")
        return True
    
    def set_color(self, color: tuple) -> bool:
        """Set the color for color-based animations"""
        if self._disabled:
            return False
            
        if self.current_color != color:
            self.current_color = color
            if self.animation_type in [AnimationType.SPARKLE_PULSE, AnimationType.SOLID]:
                self.animation = self._create_animation(self.animation_type, color=color)
                logging.debug(f"Set strand '{self.name}' color to {color}")
        return True
    
    def set_active(self, active: bool):
        """Set this strand's active state"""
        if not self._disabled:
            self.is_active = active
            if not active:
                self.turn_off()
    
    def turn_off(self):
        """Turn off this strand safely"""
        if self.pixels and not self._disabled and not _shutdown_requested:
            try:
                self.pixels.fill(0)
                # Let the auto_write handle the transmission
            except Exception as e:
                logging.error(f"Error turning off strand '{self.name}': {e}")
    
    def animate(self) -> bool:
        """Animate one frame for this strand with error protection"""
        if (self._disabled or _shutdown_requested or 
            not (self.pixels and self.animation and self.is_active)):
            return True
            
        # Skip if too many consecutive errors
        if self._animate_error_count >= self._max_errors:
            self._disabled = True
            logging.warning(f"Strand '{self.name}' disabled due to too many errors")
            return False
            
        try:
            self.animation.animate()
            self._animate_error_count = 0
            return True
            
        except Exception as e:
            self._animate_error_count += 1
            logging.error(f"Error animating strand '{self.name}' (count: {self._animate_error_count}): {e}")
            
            # Disable strand if too many errors
            if self._animate_error_count >= self._max_errors:
                self._disabled = True
                logging.warning(f"Disabling strand '{self.name}' due to repeated errors")
            
            return False


class LEDController:
    """Manages multiple LED strands"""
    
    def __init__(self, strand_configs: Dict[str, Dict] = None):
        self.strands: Dict[str, LEDStrand] = {}
        self.is_active = False
        
        # Use provided config or default
        configs = strand_configs or LED_STRANDS
        
        # Initialize all configured strands
        for name, config in configs.items():
            if NEOPIXEL_AVAILABLE and not _shutdown_requested:
                strand = LEDStrand(
                    name=name,
                    pin=config['pin'],
                    num_pixels=config['pixels'],
                    animation_type=config['animation_type']
                )
                self.strands[name] = strand
                logging.info(f"Added LED strand: {name}")
    
    def get_strand_names(self) -> List[str]:
        """Get list of all strand names"""
        return list(self.strands.keys())
    
    def get_strand(self, name: str) -> Optional[LEDStrand]:
        """Get a specific strand by name"""
        return self.strands.get(name)
    
    def set_all_active(self, active: bool):
        """Set active state for all strands"""
        if _shutdown_requested:
            return
            
        self.is_active = active
        for strand in self.strands.values():
            strand.set_active(active)
        logging.info(f"All LED strands {'activated' if active else 'deactivated'}")
    
    def set_strand_active(self, name: str, active: bool) -> bool:
        """Set active state for a specific strand"""
        if _shutdown_requested:
            return False
            
        strand = self.strands.get(name)
        if strand:
            strand.set_active(active)
            logging.info(f"LED strand '{name}' {'activated' if active else 'deactivated'}")
            return True
        return False
    
    def animate_all(self) -> int:
        """Animate all active strands, return number of successful animations"""
        if _shutdown_requested:
            return 0
            
        successful_animations = 0
        
        for strand in self.strands.values():
            try:
                if strand.animate():
                    successful_animations += 1
            except Exception as e:
                logging.error(f"Critical error animating strand '{strand.name}': {e}")
        
        return successful_animations
    
    def turn_off_all(self):
        """Turn off all strands"""
        for strand in self.strands.values():
            strand.turn_off()
    
    def emergency_shutdown(self):
        """Emergency shutdown - just fill with zeros, no complex operations"""
        global _shutdown_requested
        _shutdown_requested = True
        
        for strand in self.strands.values():
            if strand.pixels:
                try:
                    strand.pixels.fill(0)
                    # Don't force show() - let auto_write handle it
                except:
                    pass  # Ignore all errors during emergency shutdown
    
    def set_people_count(self, people_count: int):
        """Update animations based on people count for responsive strands"""
        if _shutdown_requested:
            return
            
        for name, strand in self.strands.items():
            config = LED_STRANDS.get(name, {})
            if config.get('responds_to_people', False):
                speed = get_speed_for_people_count(people_count)
                strand.set_speed(speed)


def _emergency_cleanup():
    """Emergency cleanup function"""
    global _shutdown_requested, _led_controller
    _shutdown_requested = True
    
    if _led_controller:
        _led_controller.emergency_shutdown()


def init_leds(strand_configs: Dict[str, Dict] = None) -> bool:
    """Initialize the LED system with multiple strands"""
    global _led_controller
    
    logging.info("Starting LED initialization...")
    
    if not NEOPIXEL_AVAILABLE:
        logging.warning("NeoPixel libraries not available")
        return False
    
    logging.info("NeoPixel libraries available, proceeding...")
    
    # Register emergency cleanup
    atexit.register(_emergency_cleanup)
    
    try:
        logging.info("Creating LED controller...")
        _led_controller = LEDController(strand_configs)
        logging.info(f"Initialized LED system with {len(_led_controller.strands)} strands")
        
        # Remove debug activation to prevent spam
        return True
    except Exception as e:
        logging.error(f"Failed to initialize LED system: {e}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return False


def is_active_time() -> bool:
    """Check if current time is within active hours (7 PM to 7 AM)"""
    current_hour = datetime.now().hour
    start_hour, end_hour = ACTIVE_HOURS
    
    if start_hour > end_hour:  # Spans midnight (19:00 to 07:00)
        is_active = current_hour >= start_hour or current_hour < end_hour
    else:  # Same day range
        is_active = start_hour <= current_hour < end_hour
    
    # Remove debug logging - it was causing spam
    return is_active


def get_speed_for_people_count(people_count: int) -> float:
    """Calculate animation speed based on number of people"""
    speed_map = {
        0: 0.050,  # Very slow when no one is around
        1: 0.025,  # Normal speed for one person
        2: 0.015,  # Faster for two people
        3: 0.010,  # Fast for three people
        4: 0.005,  # Very fast for four or more people
    }
    
    if people_count >= max(speed_map.keys()):
        return speed_map[max(speed_map.keys())]
    
    return speed_map.get(people_count, 0.025)


# High-level functional interface
def set_all_active(active: bool) -> bool:
    """Set active state for all LED strands"""
    if _led_controller and not _shutdown_requested:
        _led_controller.set_all_active(active)
        return True
    return False


def set_strand_active(strand_name: str, active: bool) -> bool:
    """Set active state for a specific strand"""
    if _led_controller and not _shutdown_requested:
        return _led_controller.set_strand_active(strand_name, active)
    return False


def set_strand_animation(strand_name: str, animation_type: str, **kwargs) -> bool:
    """Set animation type for a specific strand"""
    if _led_controller and not _shutdown_requested:
        strand = _led_controller.get_strand(strand_name)
        if strand:
            return strand.set_animation_type(animation_type, **kwargs)
    return False


def set_strand_speed(strand_name: str, speed: float) -> bool:
    """Set animation speed for a specific strand"""
    if _led_controller and not _shutdown_requested:
        strand = _led_controller.get_strand(strand_name)
        if strand:
            return strand.set_speed(speed)
    return False


def set_strand_color(strand_name: str, color: tuple) -> bool:
    """Set color for a specific strand"""
    if _led_controller and not _shutdown_requested:
        strand = _led_controller.get_strand(strand_name)
        if strand:
            return strand.set_color(color)
    return False


def set_people_count(people_count: int) -> bool:
    """Update people-responsive strands based on people count"""
    if _led_controller and not _shutdown_requested:
        _led_controller.set_people_count(people_count)
        return True
    return False


def animate_leds() -> bool:
    """Animate all LED strands with safety checks"""
    if _led_controller and not _shutdown_requested:
        try:
            successful_animations = _led_controller.animate_all()
            return successful_animations > 0 or len(_led_controller.strands) == 0
        except Exception as e:
            logging.error(f"Critical error in animate_leds: {e}")
            return False
    return False


def turn_off_all_leds():
    """Turn off all LED strands"""
    if _led_controller:
        _led_controller.turn_off_all()


def get_strand_names() -> List[str]:
    """Get list of all strand names"""
    if _led_controller:
        return _led_controller.get_strand_names()
    return []


def process_led_command(command: dict):
    """Process a command from the LED queue"""
    if _shutdown_requested:
        return
        
    try:
        cmd_type = command.get('type')
        
        if cmd_type == 'set_all_active':
            active = command.get('active', True)
            set_all_active(active)
        
        elif cmd_type == 'set_strand_active':
            strand_name = command.get('strand')
            active = command.get('active', True)
            set_strand_active(strand_name, active)
        
        elif cmd_type == 'set_strand_animation':
            strand_name = command.get('strand')
            animation_type = command.get('animation')
            kwargs = command.get('kwargs', {})
            set_strand_animation(strand_name, animation_type, **kwargs)
        
        elif cmd_type == 'set_strand_speed':
            strand_name = command.get('strand')
            speed = command.get('speed', 0.025)
            set_strand_speed(strand_name, speed)
        
        elif cmd_type == 'set_strand_color':
            strand_name = command.get('strand')
            color = command.get('color', (255, 255, 255))
            set_strand_color(strand_name, color)
        
        elif cmd_type == 'set_people_count':
            people_count = command.get('count', 0)
            set_people_count(people_count)
        
        elif cmd_type == 'turn_off_all':
            turn_off_all_leds()
        
        else:
            logging.warning(f"Unknown LED command type: {cmd_type}")
            
    except Exception as e:
        logging.error(f"Error processing LED command: {e}")


def led_control_thread(led_queue: queue.Queue, state: ThreadSafeState):
    """LED control thread function - SAFE VERSION"""
    global _shutdown_requested  # Need to access the global variable
    
    logging.info("LED control thread starting")
    
    if not NEOPIXEL_AVAILABLE:
        logging.warning("NeoPixel libraries not available - LED thread exiting")
        return
    
    # Initialize LEDs
    if not init_leds():
        logging.error("Failed to initialize LEDs - LED thread exiting")
        return
    
    # Note: Signal handlers can only be set in the main thread
    # The main thread will set state["should_run"] = False
    # and we'll check _shutdown_requested set by the main thread
    
    # Thread control variables
    last_time_check = 0
    last_people_count = -1
    check_interval = 60
    people_check_interval = 2
    last_people_check = 0
    frame_counter = 0
    
    logging.info("LED control thread initialized successfully")
    
    try:
        while state["should_run"] and not _shutdown_requested:
            current_time = time.time()
            
            # Check shutdown signal every 25 frames for responsiveness
            if frame_counter % 25 == 0:
                if not state["should_run"] or _shutdown_requested:
                    break
            
            # Process commands
            try:
                command = led_queue.get_nowait()
                logging.debug(f"Processing LED command: {command}")
                process_led_command(command)
            except queue.Empty:
                pass
            
            # Time-based activation check
            if current_time - last_time_check > check_interval:
                should_be_active = is_active_time()
                if _led_controller and should_be_active != _led_controller.is_active:
                    logging.info(f"LED activation state changing: {_led_controller.is_active} -> {should_be_active}")
                    set_all_active(should_be_active)
                    if should_be_active:
                        logging.info("Entering active hours - LEDs enabled")
                    else:
                        logging.info("Exiting active hours - LEDs disabled")
                last_time_check = current_time
            
            # People count updates
            if current_time - last_people_check > people_check_interval:
                local_people = state.get("local_num_people", 0)
                if local_people != last_people_count:
                    set_people_count(local_people)
                    logging.info(f"Updated LED speed for {local_people} local people")
                    last_people_count = local_people
                last_people_check = current_time
            
            # Animation
            if _led_controller and _led_controller.is_active and is_active_time() and not _shutdown_requested:
                animate_success = animate_leds()
                if frame_counter % 100 == 0:  # Log every 100 frames
                    logging.debug(f"Animation frame {frame_counter}, success: {animate_success}")
                time.sleep(0.02)  # 50 FPS
            else:
                if frame_counter % 100 == 0:  # Debug why not animating
                    logging.debug(f"Not animating: controller={_led_controller is not None}, "
                                f"active={_led_controller.is_active if _led_controller else False}, "
                                f"time_active={is_active_time()}, shutdown={_shutdown_requested}")
                time.sleep(0.1)  # Responsive when inactive
            
            frame_counter += 1
            
    except KeyboardInterrupt:
        logging.info("LED thread received keyboard interrupt")
    except Exception as e:
        logging.error(f"Error in LED control thread: {e}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")
    finally:
        # Cleanup
        logging.info("LED control thread stopping")
        _emergency_cleanup()
        logging.info(f"LED thread received signal")
        _shutdown_requested = True
        state["should_run"] = False
    

    # Thread control variables
    last_time_check = 0
    last_people_count = -1
    check_interval = 60
    people_check_interval = 2
    last_people_check = 0
    frame_counter = 0
    
    logging.info("LED control thread initialized successfully")
    
    try:
        while state["should_run"] and not _shutdown_requested:
            current_time = time.time()
            
            # Check shutdown signal every 25 frames for responsiveness
            if frame_counter % 25 == 0:
                if not state["should_run"] or _shutdown_requested:
                    break
            
            # Process commands
            try:
                command = led_queue.get_nowait()
                process_led_command(command)
            except queue.Empty:
                pass
            
            # Time-based activation check
            if current_time - last_time_check > check_interval:
                should_be_active = is_active_time()
                if _led_controller and should_be_active != _led_controller.is_active:
                    set_all_active(should_be_active)
                    if should_be_active:
                        logging.info("Entering active hours - LEDs enabled")
                    else:
                        logging.info("Exiting active hours - LEDs disabled")
                last_time_check = current_time
            
            # People count updates
            if current_time - last_people_check > people_check_interval:
                local_people = state.get("local_num_people", 0)
                if local_people != last_people_count:
                    set_people_count(local_people)
                    logging.info(f"Updated LED speed for {local_people} local people")
                    last_people_count = local_people
                last_people_check = current_time
            
            # Animation
            if (_led_controller and _led_controller.is_active and 
                is_active_time() and not _shutdown_requested):
                
                animate_leds()
                time.sleep(0.02)  # 50 FPS
            else:
                time.sleep(0.1)  # Responsive when inactive
            
            frame_counter += 1
            
    except KeyboardInterrupt:
        logging.info("LED thread received keyboard interrupt")
    except Exception as e:
        logging.error(f"Error in LED control thread: {e}")
    finally:
        # Cleanup
        logging.info("LED control thread stopping")
        _emergency_cleanup()


def send_led_command(led_queue: queue.Queue, command: dict):
    """Send a command to the LED controller"""
    if _shutdown_requested:
        return
        
    try:
        led_queue.put_nowait(command)
        logging.debug(f"Sent LED command: {command}")
    except queue.Full:
        logging.warning("LED command queue is full - command dropped")
    except Exception as e:
        logging.error(f"Error sending LED command: {e}")


# Convenience functions for queue-based control
def queue_set_all_active(led_queue: queue.Queue, active: bool = True):
    """Queue command to activate/deactivate all strands"""
    send_led_command(led_queue, {'type': 'set_all_active', 'active': active})


def queue_set_strand_active(led_queue: queue.Queue, strand_name: str, active: bool = True):
    """Queue command to activate/deactivate a specific strand"""
    send_led_command(led_queue, {'type': 'set_strand_active', 'strand': strand_name, 'active': active})


def queue_set_strand_animation(led_queue: queue.Queue, strand_name: str, animation_type: str, **kwargs):
    """Queue command to set animation for a specific strand"""
    send_led_command(led_queue, {
        'type': 'set_strand_animation', 
        'strand': strand_name, 
        'animation': animation_type,
        'kwargs': kwargs
    })


def queue_set_strand_speed(led_queue: queue.Queue, strand_name: str, speed: float):
    """Queue command to set speed for a specific strand"""
    send_led_command(led_queue, {'type': 'set_strand_speed', 'strand': strand_name, 'speed': speed})


def queue_set_strand_color(led_queue: queue.Queue, strand_name: str, color: tuple):
    """Queue command to set color for a specific strand"""
    send_led_command(led_queue, {'type': 'set_strand_color', 'strand': strand_name, 'color': color})


def queue_set_people_count(led_queue: queue.Queue, people_count: int):
    """Queue command to update people-responsive strands"""
    send_led_command(led_queue, {'type': 'set_people_count', 'count': people_count})


def led_control_process(led_queue, restart_queue):
    """LED control process function - runs in separate process for isolation"""
    import multiprocessing as mp
    import os
    import sys
    
    # Set up logging for this process to go to the same place as main process
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s - LED-PID-{os.getpid()} - %(levelname)s - %(message)s",
        force=True  # Override any existing logging config
    )
    
    # Also set up a console handler to make sure it goes to terminal
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(f"%(asctime)s - LED-PID-{os.getpid()} - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)
    
    # Get root logger and add our handler
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # Remove any existing handlers
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)
    
    logging.info("LED control process starting")
    sys.stdout.flush()  # Make sure this appears immediately
    
    try:
        # Process-local state (separate from main process)
        process_state = {
            "should_run": True,
            "local_num_people": 0,
            "is_active": False  # Start as False, wait for activation command
        }
        
        if not NEOPIXEL_AVAILABLE:
            logging.warning("NeoPixel libraries not available - LED process exiting")
            return
        
        # Initialize LEDs in this process
        if not init_leds():
            logging.error("Failed to initialize LEDs - LED process exiting")
            sys.stdout.flush()
            return
        
        logging.info("*** LED HARDWARE INITIALIZED ***")
        sys.stdout.flush()
        
        # Process control variables
        last_time_check = 0
        last_people_count = -1
        check_interval = 60  # Check time every 60 seconds
        people_check_interval = 2  # Check people count every 2 seconds
        last_people_check = 0
        frame_counter = 0
        
        logging.info("LED process initialized successfully")
        
        # Test log to make sure logging is working
        logging.info("*** LED PROCESS LOGGING TEST - YOU SHOULD SEE THIS ***")
        
        # Main process loop
        while process_state["should_run"]:
            try:
                current_time = time.time()
                
                # Process commands from main process (non-blocking)
                commands_processed = 0
                while commands_processed < 10:  # Limit to prevent blocking
                    try:
                        command = led_queue.get_nowait()
                        logging.debug(f"LED process received command: {command}")
                        
                        # Handle shutdown command
                        if command.get('type') == 'shutdown':
                            logging.info("LED process received shutdown command")
                            process_state["should_run"] = False
                            break
                        
                        # Handle people count updates
                        elif command.get('type') == 'set_people_count':
                            people_count = command.get('count', 0)
                            if people_count != process_state["local_num_people"]:
                                process_state["local_num_people"] = people_count
                                set_people_count(people_count)
                                logging.debug(f"LED process updated for {people_count} people")
                        
                        # Handle other LED commands
                        else:
                            # Log important commands
                            if command.get('type') == 'set_all_active':
                                active = command.get('active', False)
                                logging.info(f"*** LED ACTIVATION COMMAND: {active} ***")
                                sys.stdout.flush()  # Force output to appear immediately
                            process_led_command(command)
                        
                        commands_processed += 1
                        
                    except:  # queue.Empty or other queue errors
                        break
                
                # Time-based activation check - ONLY every 60 seconds
                if current_time - last_time_check > check_interval:
                    should_be_active = is_active_time()
                    if should_be_active != process_state["is_active"]:
                        process_state["is_active"] = should_be_active
                        set_all_active(should_be_active)
                        if should_be_active:
                            logging.info("LED process: Entering active hours")
                        else:
                            logging.info("LED process: Exiting active hours")
                    last_time_check = current_time  # IMPORTANT: Update the timestamp
                
                # Track animation state changes for debugging
                should_animate = process_state["is_active"] and is_active_time()
                
                # Log state changes - make it INFO level so it's visible
                if frame_counter == 0 or frame_counter % 1500 == 0:  # Every ~50 seconds at 30 FPS
                    logging.info(f"*** LED STATE: active={process_state['is_active']}, "
                               f"time_active={is_active_time()}, should_animate={should_animate} ***")
                    sys.stdout.flush()
                
                # Animation
                if should_animate:
                    animate_success = animate_leds()
                    if not animate_success and frame_counter % 500 == 0:  # Less frequent error logging
                        logging.warning("LED animation failing consistently")
                    time.sleep(0.033)  # ~30 FPS (was 50 FPS) - reduced to prevent stuttering
                else:
                    time.sleep(0.1)  # Slower when inactive
                
                frame_counter += 1
                
                # Heartbeat every 1500 frames (~50 seconds at 30 FPS) - much less frequent
                if frame_counter % 1500 == 0:
                    logging.info(f"*** LED HEARTBEAT: frame {frame_counter}, animating={should_animate} ***")
                    sys.stdout.flush()
                
            except KeyboardInterrupt:
                logging.info("LED process received keyboard interrupt")
                break
            except Exception as e:
                logging.error(f"Error in LED process main loop: {e}")
                time.sleep(1)
        
        logging.info("LED process main loop exiting")
        
    except Exception as e:
        logging.error(f"Fatal error in LED process: {e}")
        import traceback
        logging.error(f"LED process traceback: {traceback.format_exc()}")
    finally:
        # Cleanup - turn off LEDs
        logging.info("LED process cleanup: turning off all LEDs")
        try:
            _emergency_cleanup()
        except:
            pass  # Ignore cleanup errors
        
        logging.info("LED process terminated")


def send_led_command_mp(led_queue, command):
    """Send command to LED process (multiprocessing version)"""
    try:
        led_queue.put_nowait(command)
        logging.debug(f"Sent LED command to process: {command}")
    except:
        logging.warning("LED process command queue full - command dropped")


# Multiprocessing versions of queue functions
def queue_set_all_active_mp(led_queue, active=True):
    """Queue command to activate/deactivate all LED strands (multiprocessing)"""
    send_led_command_mp(led_queue, {'type': 'set_all_active', 'active': active})


def queue_set_strand_active_mp(led_queue, strand_name, active=True):
    """Queue command to activate/deactivate a specific strand (multiprocessing)"""
    send_led_command_mp(led_queue, {'type': 'set_strand_active', 'strand': strand_name, 'active': active})


def queue_set_strand_animation_mp(led_queue, strand_name, animation_type, **kwargs):
    """Queue command to set animation for a specific strand (multiprocessing)"""
    send_led_command_mp(led_queue, {
        'type': 'set_strand_animation', 
        'strand': strand_name, 
        'animation': animation_type,
        'kwargs': kwargs
    })


def queue_set_people_count_mp(led_queue, people_count):
    """Queue command to update people-responsive strands (multiprocessing)"""
    send_led_command_mp(led_queue, {'type': 'set_people_count', 'count': people_count})


def queue_turn_off_all_mp(led_queue):
    """Queue command to turn off all strands (multiprocessing)"""
    send_led_command_mp(led_queue, {'type': 'turn_off_all'})


def shutdown_led_process(led_queue):
    """Send shutdown command to LED process"""
    send_led_command_mp(led_queue, {'type': 'shutdown'})