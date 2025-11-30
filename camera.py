#!/usr/bin/env python3
import os
import datetime
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2
from libcamera import Transform


class Camera:
    def __init__(self):
        self.picam2 = Picamera2()
        self.preview_widget = None
        self.preview_started = False
        self.image_counter = 1
        os.makedirs("Images", exist_ok=True)

        # Apply transform ONCE at initialization
        self.transform = Transform(hflip=True, vflip=True)
        
        # Pi Zero 2 W optimized settings: Lower resolution to reduce CPU/GPU load
        # Preview: 1280x720 (720p) - sufficient for preview and reduces GPU load
        self.PREVIEW_WIDTH = 1280
        self.PREVIEW_HEIGHT = 720
        
        # Video: 1280x720 @ 20fps max - optimal for Pi Zero 2 W
        self.VIDEO_WIDTH = 1280
        self.VIDEO_HEIGHT = 720
        
        # Still images: Use reasonable size (not full sensor) to reduce processing time
        # Will use sensor's native still configuration but with quality control

    def _stop_if_running(self):
        try:
            self.picam2.stop()
        except Exception:
            pass

    def _configure_preview(self):
        # Reduced resolution for Pi Zero 2 W: 1280x720 instead of 1640x1232
        # This reduces GPU load significantly while maintaining good preview quality
        config = self.picam2.create_preview_configuration(
            main={
                "size": (self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT),
                "transform": Transform(hflip=True, vflip=True)
            },
            buffer_count=2
        )

        self.picam2.configure(config)

    def _configure_still(self):
        # Use still configuration but limit quality for faster processing
        # Pi Zero 2 W can handle full resolution stills, but we'll optimize quality
        still_config = self.picam2.create_still_configuration(
            main={
                "transform": Transform(hflip=True, vflip=True)
            },
            buffer_count=1
        )

        self.picam2.configure(still_config)

    def _configure_video(self):
        # Reduced resolution and frame rate for Pi Zero 2 W
        # 1280x720 @ 20fps is optimal balance between quality and performance
        VIDEO_FRAMERATE = 60  # Reduced from default 30fps to 20fps for Pi Zero 2 W  CHANGED TO 30 FPS
        
        video_config = self.picam2.create_video_configuration(
            main={
                "size": (self.VIDEO_WIDTH, self.VIDEO_HEIGHT),
                "transform": Transform(hflip=True, vflip=True)
            },
            buffer_count=2
        )

        
        # Set frame rate limits to enforce 20fps
        # FrameDurationLimits is in microseconds: 1e6 / framerate
        frame_duration = int(1e6 // VIDEO_FRAMERATE)
        video_config["controls"]["FrameDurationLimits"] = (frame_duration, frame_duration)
        
        self.picam2.configure(video_config)

    def start_preview(self):
        """
        Starts the preview with a 180-degree rotated image.
        """
        if self.preview_started:
            return self.preview_widget

        # Ensure stop -> configure -> start ordering for preview
        self._stop_if_running()
        self._configure_preview()

        # Start preview widget
        self.preview_widget = QGlPicamera2(
            self.picam2,
            keep_ar=True,
            transform=Transform(rotation=180)
        )

        self.picam2.start()
        self.preview_started = True
        return self.preview_widget

    def stop_preview(self):
        """
        Stops live preview.
        """
        if self.preview_started:
            self.picam2.stop()
            self.preview_started = False

    def capture_image(self, media_category="general"):
        """
        Capture still image with rotation and restore preview afterwards.
        Optimized for Pi Zero 2 W: Uses optimized capture settings.
        """
        # Stop -> configure(still) -> start
        self._stop_if_running()
        self._configure_still()
        self.picam2.start()

        sanitized_category = media_category.replace(" ", "_").lower()
        now = datetime.datetime.now()
        date_str = now.strftime("%d%b%Y").lower()
        time_str = now.strftime("%H%M%S")
        filename = os.path.join(
            "Images",
            f"img_{self.image_counter}_{date_str}_{time_str}_{sanitized_category}.jpg"
        )

        try:
            # Capture image - picamera2 handles encoding efficiently with hardware acceleration
            # The library automatically uses optimal settings for Pi Zero 2 W
            self.picam2.capture_file(filename)
        except Exception as e:
            raise Exception("Capture failed: " + str(e))

        self.image_counter += 1

        # Restore rotated preview: stop -> configure(preview) -> start
        self._stop_if_running()
        self._configure_preview()
        self.picam2.start()

        self.preview_started = True

        return filename

    def prepare_video_mode(self):
        """
        Ensure the pipeline is in video mode with rotation and running.
        """
        self._stop_if_running()
        self._configure_video()
        self.picam2.start()

    def restore_preview(self):
        """
        Restore the preview mode after any capture/recording.
        """
        self._stop_if_running()
        self._configure_preview()
        self.picam2.start()
        self.preview_started = True

    def update_controls(self, controls):
        """
        Update camera controls in real-time.
        Maps slider values (0–100) → (0.0–1.0).
        """
        normalized_controls = {key: value / 100.0 for key, value in controls.items()}
        try:
            self.picam2.set_controls(normalized_controls)
        except Exception as e:
            print("Error updating camera controls:", e)
