import asyncio
import edge_tts
import sounddevice as sd
import numpy as np

VOICE = "vi-VN-HoaiMyNeural"

async def speak(text):
    communicate = edge_tts.Communicate(text=text, voice=VOICE)

    audio_bytes = b""

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]

    # convert mp3 -> pcm (cần ffmpeg ngầm)
    import subprocess

    p = subprocess.Popen(
        ["ffmpeg", "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    pcm, _ = p.communicate(audio_bytes)

    audio = np.frombuffer(pcm, dtype=np.int16)
    sd.play(audio, samplerate=24000)
    sd.wait()

asyncio.run(speak("Xin chào, đây là giọng Hoài My phát trực tiếp"))