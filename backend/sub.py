import whisperx
import os
import subprocess
from whisperx.utils import get_writer

input_file = "FamilyGuy9-11.mp4"                # Video to extract audio
base_name = os.path.splitext(os.path.basename(input_file))[0]

audio_file = "output.mp3"                       # Audio from video

subprocess.run([
    "ffmpeg",
    "-i", input_file,
    "-vn",
    "-acodec", "libmp3lame",
    "-q:a", "2",
    audio_file
])

device = "cpu"                                  # cpu or cuda

model = whisperx.load_model("large-v2", device)

audio = whisperx.load_audio(audio_file)
result = model.transcribe(audio)

language = result["language"]                   # Detects language

output_name = f"{base_name}_{language}"

model_a, metadata = whisperx.load_align_model(
    language_code=language, device=device
)

result = whisperx.align(result["segments"], model_a, metadata, audio, device)

result["language"] = language

writer = get_writer("srt", "C:/nvim/Dragonhack")

custom_path = os.path.join("C:/nvim/Dragonhack", output_name + ".mp3")

writer(result, custom_path, {                   # Create .srt file
    "max_line_width": 40,
    "max_line_count": 2,
    "highlight_words": False
})

os.remove(audio_file)
