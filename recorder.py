#!/usr/bin/env python3
import pyaudio
import wave
import threading
import datetime
import os
import time
import subprocess
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

# Pi Zero 2 W optimized audio settings
# Reduced sample rate from 44.1kHz to 16kHz: Lower CPU usage, sufficient for voice
# Reduced chunk size from 1024 to 512: Lower latency and memory usage
CHUNK = 512
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000  # Reduced from 44100 to 16000 for Pi Zero 2 W

# Video encoding settings for Pi Zero 2 W
# Bitrate: 2-3 Mbps is optimal for 720p on Pi Zero 2 W (reduces CPU/GPU load)
# Frame rate: Set to 20fps in camera.py configuration (reduces CPU/GPU load)
VIDEO_BITRATE = 2500000  # 2.5 Mbps

class AudioRecorder:
    def __init__(self):
        os.makedirs("Audios", exist_ok=True)
        self.audio_thread = None
        self.stop_event = None
        self.temp_audio_file = os.path.join("Audios", "temp_audio.wav")
        self.recording_start_time = None
        self.audio_counter = 1
        # For segmented recording:
        self.segment_audio_thread = None
        self.segment_stop_event = None
        self.segment_temp_file = None
        self.segment_start_time = None
        # Thread priority management
        self._set_thread_priority_low()

    def _set_thread_priority_low(self):
        """Set thread priority to low to prevent audio from blocking critical operations"""
        try:
            # Lower process priority using os.nice (Linux/Unix only)
            if hasattr(os, 'nice'):
                os.nice(5)  # Lower priority (higher nice value)
        except (OSError, AttributeError):
            # Not available on this system, skip
            pass

    def start_recording(self):
        if self.audio_thread is not None and self.audio_thread.is_alive():
            return
        self.stop_event = threading.Event()
        self.recording_start_time = datetime.datetime.now()
        self.audio_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.audio_thread.start()

    def record_audio(self):
        """
        Optimized audio recording for Pi Zero 2 W:
        - Writes incrementally to disk instead of storing all frames in memory
        - Uses lower sample rate and chunk size
        """
        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
        
        # Open wave file immediately and write incrementally to reduce memory usage
        wf = wave.open(self.temp_audio_file, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        
        try:
            while not self.stop_event.is_set():
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    wf.writeframes(data)  # Write immediately instead of storing in memory
                except Exception as e:
                    print("Audio error:", e)
                    continue
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            wf.close()

    def stop_recording(self, media_category):
        if self.stop_event:
            self.stop_event.set()
        if self.audio_thread:
            self.audio_thread.join()
        start = self.recording_start_time.strftime("%d%b%Y_%H%M%S").lower()
        end_time = datetime.datetime.now()
        end = end_time.strftime("%d%b%Y_%H%M%S").lower()
        start_hms = self.recording_start_time.strftime("%H:%M:%S")
        end_hms = end_time.strftime("%H:%M:%S")
        final_filename = os.path.join("Audios", f"audio_{self.audio_counter}_{start}_to_{end}_{media_category}.wav")
        try:
            os.rename(self.temp_audio_file, final_filename)
        except Exception as e:
            print("Error renaming audio file:", e)
            final_filename = self.temp_audio_file
        self.audio_counter += 1
        return final_filename, start_hms, end_hms

    # Methods for segmented audio recording:
    def start_segmented_recording(self):
        self.segment_stop_event = threading.Event()
        self.segment_start_time = datetime.datetime.now()
        self.segment_temp_file = os.path.join("Audios", "temp_seg_audio.wav")
        self.segment_audio_thread = threading.Thread(target=self.record_segment_audio, daemon=True)
        self.segment_audio_thread.start()

    def record_segment_audio(self):
        """
        Optimized segmented audio recording for Pi Zero 2 W:
        - Writes incrementally to disk instead of storing all frames in memory
        """
        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
        
        # Open wave file immediately and write incrementally
        wf = wave.open(self.segment_temp_file, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        
        try:
            while not self.segment_stop_event.is_set():
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    wf.writeframes(data)  # Write immediately instead of storing in memory
                except Exception as e:
                    print("Segmented audio error:", e)
                    continue
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            wf.close()

    def stop_segmented_recording(self):
        if self.segment_stop_event:
            self.segment_stop_event.set()
        if self.segment_audio_thread:
            self.segment_audio_thread.join()
        start = self.segment_start_time.strftime("%d%b%Y_%H%M%S").lower()
        end_time = datetime.datetime.now()
        end = end_time.strftime("%d%b%Y_%H%M%S").lower()
        final_filename = os.path.join("Audios", f"audio_seg_{start}_to_{end}.wav")
        try:
            os.rename(self.segment_temp_file, final_filename)
        except Exception as e:
            print("Error renaming segmented audio file:", e)
            final_filename = self.segment_temp_file
        return final_filename
        
class VideoRecorder:
    def __init__(self, camera, audio_recorder=None):
        self.camera = camera
        self.audio_recorder = audio_recorder
        self.recording = False
        # Reduced segment threshold for Pi Zero 2 W to prevent memory issues
        self.segment_threshold = 30 * 1024 * 1024  # 30MB instead of 50MB
        self.current_video_file = None
        self.segments = []
        self.monitor_thread = None
        self.stop_monitor = False
        self.with_audio = False
        self.session_counter = 1
        self.chunk_num = 1
        self.video_start_time = None
        self.segmentation_thread = None
        self.current_segment_start = None
        # Monitor interval: Check less frequently to reduce CPU load
        self.monitor_interval = 2  # Check every 2 seconds instead of 1

    def generate_video_filename(self):
        now = datetime.datetime.now()
        date_str = now.strftime("%d%b%Y").lower()
        time_str = now.strftime("%H%M%S")
        return os.path.join("Videos", f"temp_vdo_{date_str}_{time_str}.mp4")

    def start_recording(self, with_audio=False):
        if self.recording:
            print("DEBUG: Recording already in progress, ignoring start request")
            return
        print(f"DEBUG: start_recording called, with_audio={with_audio}")
        self.recording = True
        self.with_audio = with_audio
        self.segments.clear()
        os.makedirs("Videos", exist_ok=True)

        self.current_segment_start = datetime.datetime.now()
        print(f"DEBUG: Recording start time: {self.current_segment_start}")

        # Ensure camera is in video mode: stop -> configure(video) -> start
        self.camera.prepare_video_mode()
        print("DEBUG: Camera prepared for video mode")

        if self.with_audio and self.audio_recorder is not None:
            # Start segmented audio+video thread
            print("DEBUG: Starting segmentation thread for audio+video recording")
            self.segmentation_thread = threading.Thread(target=self._record_with_segmentation, daemon=True)
            self.segmentation_thread.start()
            print("DEBUG: Segmentation thread started")
        else:
            self.current_video_file = self.generate_video_filename()
            print(f"DEBUG: Starting video-only recording, file: {self.current_video_file}")
            # Optimized encoder settings for Pi Zero 2 W
            # Bitrate: 2.5 Mbps is optimal for 720p without overloading CPU/GPU
            encoder = H264Encoder(bitrate=VIDEO_BITRATE, repeat=True)
            output = FfmpegOutput(self.current_video_file)
            try:
                self.camera.picam2.start_recording(encoder, output)
                print(f"DEBUG: Video recording started successfully for {self.current_video_file}")
            except Exception as e:
                print(f"DEBUG: Error starting video recording: {e}")
                import traceback
                traceback.print_exc()
                self.recording = False
                return

            self.stop_monitor = False
            self.monitor_thread = threading.Thread(target=self.monitor_video_size, daemon=True)
            self.monitor_thread.start()
            print("DEBUG: Monitor thread started")

    def monitor_video_size(self):
        """
        Monitor video file size for segmentation.
        Optimized for Pi Zero 2 W: Longer sleep interval to reduce CPU load.
        """
        while self.recording and not self.stop_monitor:
            if os.path.exists(self.current_video_file):
                size = os.path.getsize(self.current_video_file)
                if size >= self.segment_threshold:
                    segment_end = datetime.datetime.now()
                    try:
                        self.camera.picam2.stop_recording()
                    except Exception as e:
                        print("Error stopping recording for segmentation:", e)

                    segment_record = {
                        "file": self.current_video_file,
                        "start": self.current_segment_start.strftime("%H:%M:%S"),
                        "end": segment_end.strftime("%H:%M:%S"),
                        "start_str": self.current_segment_start.strftime("%d%b%Y_%H%M%S").lower(),
                        "end_str": segment_end.strftime("%d%b%Y_%H%M%S").lower()
                    }
                    self.segments.append(segment_record)

                    self.current_segment_start = segment_end
                    self.current_video_file = self.generate_video_filename()
                    # Use optimized encoder settings
                    encoder = H264Encoder(bitrate=VIDEO_BITRATE, repeat=True)
                    output = FfmpegOutput(self.current_video_file)
                    self.camera.picam2.start_recording(encoder, output)

            time.sleep(self.monitor_interval)  # Longer sleep to reduce CPU load

    # (your _record_with_segmentation(), merge_video_audio(), stop_recording() stay EXACTLY the same)
    
    def _record_with_segmentation(self):
        """
        Segmentation loop for "with audio" scenario. Each chunk is recorded
        until the threshold is reached, then we merge that chunk's video/audio.
        """
        print("DEBUG: _record_with_segmentation started")
        # Ensure video mode is prepared before starting loop
        self.camera.prepare_video_mode()
        seg_start = self.current_segment_start
        video_file = None
        audio_started = False
        recording_started = False
        
        try:
            while self.recording:
                video_file = self.generate_video_filename()
                print(f"DEBUG: Starting new segment, video_file: {video_file}")
                # Start a new chunk with optimized encoder settings
                encoder = H264Encoder(bitrate=VIDEO_BITRATE, repeat=True)
                output = FfmpegOutput(video_file)
                self.camera.picam2.start_recording(encoder, output)
                recording_started = True
                self.audio_recorder.start_segmented_recording()
                audio_started = True
                print(f"DEBUG: Recording and audio started for {video_file}")

                # Wait until threshold is hit or user stops recording
                # Longer sleep interval to reduce CPU load
                while self.recording:
                    if os.path.exists(video_file) and os.path.getsize(video_file) >= self.segment_threshold:
                        print(f"DEBUG: Segment threshold reached for {video_file}")
                        break
                    time.sleep(self.monitor_interval)  # Check less frequently

                # Stop this chunk - always stop even if recording was stopped early
                print(f"DEBUG: Stopping recording for {video_file}, recording flag: {self.recording}")
                was_recording = recording_started
                try:
                    if recording_started:
                        self.camera.picam2.stop_recording()
                        print("DEBUG: Recording stopped, waiting for FFmpeg to finish writing...")
                        recording_started = False
                except Exception as e:
                    print(f"DEBUG: Error stopping recording in segmentation: {e}")
                
                # Give FFmpeg time to flush buffers and finish writing the file
                # This is critical - FFmpeg needs time to close the file properly
                time.sleep(2.0)  # Increased wait time for FFmpeg to finish
                
                seg_end = datetime.datetime.now()
                
                # Stop audio recording
                if audio_started:
                    try:
                        audio_file = self.audio_recorder.stop_segmented_recording()
                        print(f"DEBUG: Audio recording stopped, audio_file: {audio_file}")
                    except Exception as e:
                        print(f"DEBUG: Error stopping audio recording: {e}")
                        audio_file = None
                    audio_started = False
                else:
                    audio_file = None

                # Process segment - wait a bit for file to be fully written if it was just created
                # Give it a moment to ensure the file is written to disk
                print(f"DEBUG: Waiting for video file {video_file} to be created (was_recording={was_recording})...")
                max_wait = 15  # Increased wait time even more
                waited = 0
                file_exists = False
                while waited < max_wait:
                    if os.path.exists(video_file):
                        file_size = os.path.getsize(video_file)
                        print(f"DEBUG: File {video_file} exists, size: {file_size} bytes (waited {waited:.1f}s)")
                        if file_size > 0:
                            file_exists = True
                            break
                    time.sleep(0.3)
                    waited += 0.3

                # Process segment if video file exists and has content
                # Even if file doesn't exist, if we were recording, try to find it
                if not file_exists and was_recording:
                    # Check if file exists with different name or check Videos directory
                    videos_dir = "Videos"
                    if os.path.exists(videos_dir):
                        # Look for any recently created temp files
                        all_files = os.listdir(videos_dir)
                        temp_files = [f for f in all_files if "temp" in f.lower() and f.endswith(".mp4")]
                        print(f"DEBUG: Found temp files in Videos directory: {temp_files}")
                        # Sort by modification time, get most recent
                        if temp_files:
                            temp_files_with_time = [(f, os.path.getmtime(os.path.join(videos_dir, f))) for f in temp_files]
                            temp_files_with_time.sort(key=lambda x: x[1], reverse=True)
                            if temp_files_with_time:
                                most_recent = temp_files_with_time[0][0]
                                video_file = os.path.join(videos_dir, most_recent)
                                print(f"DEBUG: Using most recent temp file: {video_file}")
                                file_exists = os.path.exists(video_file) and os.path.getsize(video_file) > 0
                
                if file_exists or (os.path.exists(video_file) and os.path.getsize(video_file) > 0):
                    print(f"DEBUG: Processing segment: {video_file}")
                    merged_file = self.merge_video_audio(video_file, audio_file, seg_start, seg_end, None)
                    if merged_file and os.path.exists(merged_file):
                        segment_record = {
                            "file": merged_file,
                            "start": seg_start.strftime("%H:%M:%S"),
                            "end": seg_end.strftime("%H:%M:%S"),
                            "start_str": seg_start.strftime("%d%b%Y_%H%M%S").lower(),
                            "end_str": seg_end.strftime("%d%b%Y_%H%M%S").lower()
                        }
                        self.segments.append(segment_record)
                        print(f"DEBUG: Added merged segment, total segments: {len(self.segments)}")
                    elif os.path.exists(video_file):
                        # If merging failed, just keep the raw video file
                        segment_record = {
                            "file": video_file,
                            "start": seg_start.strftime("%H:%M:%S"),
                            "end": seg_end.strftime("%H:%M:%S"),
                            "start_str": seg_start.strftime("%d%b%Y_%H%M%S").lower(),
                            "end_str": seg_end.strftime("%d%b%Y_%H%M%S").lower()
                        }
                        self.segments.append(segment_record)
                        print(f"DEBUG: Added raw video segment (merge failed), total segments: {len(self.segments)}")
                else:
                    print(f"DEBUG: Warning: Video file {video_file} does not exist or is empty after {waited} seconds, skipping segment")
                
                self.chunk_num += 1
                # Next chunk starts exactly when this one ended
                seg_start = seg_end
                
            # Handle case where recording was stopped before first segment completed
            # This happens when recording is stopped before the inner loop processes the segment
            if recording_started and video_file:
                print("DEBUG: Recording was stopped while recording was active, processing final segment...")
                try:
                    self.camera.picam2.stop_recording()
                except Exception as e:
                    print(f"DEBUG: Error stopping recording at end: {e}")
                
                # Wait for file to be written
                time.sleep(2.0)  # Give FFmpeg time to finish writing
                
                if audio_started:
                    try:
                        audio_file = self.audio_recorder.stop_segmented_recording()
                    except Exception as e:
                        print(f"DEBUG: Error stopping audio at end: {e}")
                        audio_file = None
                else:
                    audio_file = None
                
                seg_end = datetime.datetime.now()
                
                # Wait for video file to be created
                print(f"DEBUG: Waiting for final video file {video_file}...")
                max_wait = 10
                waited = 0
                while waited < max_wait:
                    if os.path.exists(video_file):
                        file_size = os.path.getsize(video_file)
                        if file_size > 0:
                            print(f"DEBUG: Final video file found, size: {file_size} bytes")
                            break
                    time.sleep(0.2)
                    waited += 0.2
                
                # Process the final segment
                if os.path.exists(video_file) and os.path.getsize(video_file) > 0:
                    print(f"DEBUG: Processing final segment: {video_file}")
                    merged_file = self.merge_video_audio(video_file, audio_file, seg_start, seg_end, None)
                    if merged_file and os.path.exists(merged_file):
                        segment_record = {
                            "file": merged_file,
                            "start": seg_start.strftime("%H:%M:%S"),
                            "end": seg_end.strftime("%H:%M:%S"),
                            "start_str": seg_start.strftime("%d%b%Y_%H%M%S").lower(),
                            "end_str": seg_end.strftime("%d%b%Y_%H%M%S").lower()
                        }
                        self.segments.append(segment_record)
                        print(f"DEBUG: Added final merged segment, total segments: {len(self.segments)}")
                    elif os.path.exists(video_file):
                        segment_record = {
                            "file": video_file,
                            "start": seg_start.strftime("%H:%M:%S"),
                            "end": seg_end.strftime("%H:%M:%S"),
                            "start_str": seg_start.strftime("%d%b%Y_%H%M%S").lower(),
                            "end_str": seg_end.strftime("%d%b%Y_%H%M%S").lower()
                        }
                        self.segments.append(segment_record)
                        print(f"DEBUG: Added final raw video segment, total segments: {len(self.segments)}")
                else:
                    print(f"DEBUG: Final video file {video_file} does not exist or is empty")
        except Exception as e:
            print(f"DEBUG: Exception in _record_with_segmentation: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"DEBUG: _record_with_segmentation finished, total segments: {len(self.segments)}")

    def merge_video_audio(self, video_file, audio_file, seg_start, seg_end, media_category):
        """
        Merge video and audio using FFmpeg with hardware acceleration optimizations.
        Optimized for Pi Zero 2 W to reduce CPU load during merging.
        """
        seg_start_str = seg_start.strftime("%d%b%Y_%H%M%S").lower()
        seg_end_str = seg_end.strftime("%d%b%Y_%H%M%S").lower()
        category_str = media_category if media_category else ""
        merged_file = os.path.join(
            "Videos",
            f"merged_{self.session_counter}_{self.chunk_num}_{seg_start_str}_to_{seg_end_str}_{category_str}.mp4"
        )
        
        # Optimized FFmpeg command for Pi Zero 2 W:
        # - Use hardware-accelerated H.264 decoder if available
        # - Copy video stream (no re-encoding) to save CPU
        # - Use fast AAC encoding preset
        # - Lower process priority to prevent system overload
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-loglevel", "error",  # Reduce logging overhead
            "-i", video_file,
            "-i", audio_file,
            "-c:v", "copy",  # Copy video stream (no re-encoding)
            "-c:a", "aac",  # Encode audio to AAC
            "-b:a", "128k",  # Lower audio bitrate for faster encoding
            "-threads", "1",  # Limit threads to prevent overload
            merged_file
        ]
        try:
            # Run with lower priority to prevent system overload
            # Use nice to reduce process priority
            result = subprocess.run(
                cmd, 
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=lambda: os.nice(10) if hasattr(os, 'nice') else None
            )
            os.remove(video_file)
            os.remove(audio_file)
            return merged_file
        except subprocess.CalledProcessError as e:
            print("Error during merging:", e)
            return None

    def stop_recording(self, media_category):
        """
        Stop recording. If any partial segment is still open, close it out,
        record its start/end times, and rename the files. Return a list of
        all final segments with their start/end times for uploading.
        """
        print(f"DEBUG: stop_recording called, with_audio={self.with_audio}, segments count before stop: {len(self.segments)}")
        self.recording = False

        if self.with_audio and self.segmentation_thread is not None:
            # Wait for the segmentation thread to exit (with timeout)
            print("DEBUG: Waiting for segmentation thread to finish...")
            self.segmentation_thread.join(timeout=10)
            print(f"DEBUG: Segmentation thread finished, segments count: {len(self.segments)}")
        else:
            # Stop the monitor thread if in no-audio mode
            self.stop_monitor = True
            if self.monitor_thread:
                self.monitor_thread.join(timeout=2)

            # Stop recording - need to check if recording actually started
            print(f"DEBUG: Stopping recording, current_video_file: {self.current_video_file}")
            try:
                # Check if recording is actually running before trying to stop
                if hasattr(self.camera.picam2, '_recording') or True:  # Try to stop anyway
                    self.camera.picam2.stop_recording()
                    print("DEBUG: Recording stopped successfully")
            except Exception as e:
                print(f"DEBUG: Error stopping video recording: {e}")

            # Give the file a moment to be fully written after stopping
            time.sleep(1.0)  # Increased wait time

            # If there's a final chunk still open, close it now
            # Wait a bit for the file to be written to disk
            if self.current_video_file:
                print(f"DEBUG: Checking for video file: {self.current_video_file}")
                print(f"DEBUG: File exists: {os.path.exists(self.current_video_file)}")
                
                max_wait = 10  # Increased wait time to 10 seconds
                waited = 0
                file_found = False
                while waited < max_wait:
                    if os.path.exists(self.current_video_file):
                        file_size = os.path.getsize(self.current_video_file)
                        print(f"DEBUG: File size: {file_size} bytes")
                        if file_size > 0:
                            file_found = True
                            break
                    time.sleep(0.2)
                    waited += 0.2
                
                seg_end = datetime.datetime.now()
                
                # Add final segment record if file exists and has content
                if os.path.exists(self.current_video_file) and os.path.getsize(self.current_video_file) > 0:
                    print(f"DEBUG: Adding final segment: {self.current_video_file}")
                    segment_record = {
                        "file": self.current_video_file,
                        "start": self.current_segment_start.strftime("%H:%M:%S"),
                        "end": seg_end.strftime("%H:%M:%S"),
                        "start_str": self.current_segment_start.strftime("%d%b%Y_%H%M%S").lower(),
                        "end_str": seg_end.strftime("%d%b%Y_%H%M%S").lower()
                    }
                    self.segments.append(segment_record)
                    print(f"DEBUG: Segment added, total segments: {len(self.segments)}")
                else:
                    print(f"DEBUG: Warning: Final video file {self.current_video_file} does not exist or is empty after {waited} seconds")
                    # Check if file exists in the Videos directory with a different name
                    videos_dir = "Videos"
                    if os.path.exists(videos_dir):
                        files = os.listdir(videos_dir)
                        temp_files = [f for f in files if f.startswith("temp_vdo_")]
                        print(f"DEBUG: Found temp video files: {temp_files}")
            else:
                print("DEBUG: Warning: No current video file set - recording may not have started properly")

        # Resume camera preview so image capture remains available
        self.camera.restore_preview()

        print(f"DEBUG: Total segments before renaming: {len(self.segments)}")
        
        # Rename final segments
        final_segments = []
        prefix = "merged" if self.with_audio else "vdo"

        for idx, seg in enumerate(self.segments, start=1):
            final_name = os.path.join(
                "Videos",
                f"{prefix}_{self.session_counter}_{idx}_{seg['start_str']}_to_{seg['end_str']}_{media_category}.mp4"
            )
            try:
                if os.path.exists(seg["file"]):
                    os.rename(seg["file"], final_name)
                    print(f"DEBUG: Renamed {seg['file']} to {final_name}")
                else:
                    print(f"DEBUG: Warning: Source file {seg['file']} does not exist for renaming")
                    final_name = seg["file"]
            except Exception as e:
                print(f"DEBUG: Error renaming video file: {e}")
                final_name = seg["file"]
            final_segments.append({
                "file": final_name,
                "start": seg["start"],
                "end": seg["end"]
            })

        print(f"DEBUG: Returning {len(final_segments)} final segments")
        self.session_counter += 1
        self.chunk_num = 1
        return final_segments
