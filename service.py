import os
import sys
import re
import uuid
import shutil
import subprocess
import requests
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(ROOT))
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024

@app.after_request
def disable_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response

CORS(app, resources={r"/api/*": {"origins": "*"}})

ALLOWED_TOOLS = {
    "auto-master-magic", "smart-instrumental-blend", "poyo-ai", "pixazo-ai",
    "3d-audio", "autopanner", "bass-booster", "equalizer", "noise-reducer",
    "pitch-shifter", "reverb-vocal-only", "reverb-full-song", "reverb", "reverse",
    "stereo-panner", "tempo", "trimmer", "vocal-remover", "instrument-extractor",
    "volume", "lofi", "nightcore", "underwater", "phone-call", "concert-hall",
    "radio-broadcast", "chipmunk", "demon-dark", "spatial-wide", "vinyl-crackles",
    "phaser-fx", "flanger-fx", "tremolo-fx", "vibrato-fx", "studio-master",
    "club-punch", "ambient-space", "hq-enhance", "cyberpunk-fx", "sub-bass-drop",
    "downmixer", "spectrogram", "waveform", "converter",
    "vocal-chop", "smooth-flow", "vocal-presence", "de-esser", "warm-analog", "club-pump", "vocal-isolator", "phonk-maker", "brazilian-funk", "drift-phonk", "cowbell-layer", "808-bass-layer", "funk-drum-pulse", "dark-synth", "beat-drop-impact", "lofi-remix", "romantic-remix", "reels-master",
    "reels-slowed-reverb", "reels-sped-up", "phonk-reels", "sad-reels", "romantic-reels", "dreamy-vocal", "glitch-edit", "cinematic-drop", "viral-master", "clean-vocal-mix", "bass-drop-impact", "stereo-reels",
    "preset-8d-audio", "preset-slowed-reverb", "preset-432hz",
    "preset-very-light-bass", "preset-light-bass", "preset-moderate-bass",
    "preset-heavy-bass", "preset-extreme-bass", "preset-vocal-reverb",
    "preset-bathroom-reverb", "preset-small-room-reverb", "preset-medium-room-reverb",
    "preset-large-room-reverb", "preset-church-hall-reverb", "preset-cathedral-reverb",
    'aggressive-remix', 'ambient-remix', 'atmospheric-remix', 'bass-boost-remix', 'chill-remix', 'cinematic-remix', 'club-remix', 'concert-hall-remix', 'dance-remix', 'dark-remix', 'dreamy-remix', 'echo-fx', 'echo-remix', 'reverb-remix', 'sad-remix', 'slowed-remix', 'space-remix', 'stereo-widening', 'underwater-remix', 'vinyl-remix'
}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".aiff", ".webm"}

def number(name, default, lo, hi):
    try:
        value = float(request.form.get(name, default))
    except (TypeError, ValueError):
        value = float(default)
    return max(lo, min(hi, value))

def ffmpeg_available():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")

@app.route("/")
def index():
    return send_from_directory(ROOT, "index.html")

@app.get("/api/status")
def status():
    return jsonify({
        "name": "Akhil Audio Studio Pro",
        "status": "online" if ffmpeg_available() else "missing_dependency",
        "engine": "FFmpeg",
        "api_integrations": "not configured",
        "max_upload_mb": 150
    })

@app.get("/api/tools")
def tools():
    return jsonify(sorted(ALLOWED_TOOLS))

def find_demucs():
    """Return a usable Demucs command if the local AI stem-separation package is installed."""
    try:
        import importlib.util
        if importlib.util.find_spec("demucs"):
            return [sys.executable, "-m", "demucs"]
    except Exception:
        pass
    exe = shutil.which("demucs")
    return [exe] if exe else None


def run_stem_separation(input_path, output_path, tool, uid):
    """
    Run real local AI source separation when Demucs is installed.
    Returns True if an output was written, otherwise raises a useful error.
    """
    demucs_cmd = find_demucs()
    if not demucs_cmd:
        # Always return a usable approximation on lightweight Android/Termux installs.
        # True AI separation remains preferable when Demucs is available.
        fallback = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path),
            "-af", "pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0,highpass=f=80,alimiter=limit=0.95",
            "-codec:a", "libmp3lame", "-b:a", "320k", str(output_path)
        ]
        proc = subprocess.run(fallback, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0 or not output_path.exists():
            raise RuntimeError(("Fallback vocal filter failed: " + (proc.stderr or "FFmpeg failed"))[-700:])
        return True
    temp_dir = OUTPUTS / f"stems_{uid}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        cmd = demucs_cmd + ["--two-stems", "vocals", "-n", "htdemucs", "-o", str(temp_dir), str(input_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            raise RuntimeError(("Demucs failed: " + (proc.stderr or proc.stdout or "unknown error"))[-900:])
        track_dir = temp_dir / "htdemucs" / Path(input_path).stem
        if tool == "vocal-isolator":
            stem_name = "vocals.wav"
        else:
            stem_name = "no_vocals.wav"
        stem_path = track_dir / stem_name
        if not stem_path.exists():
            # Some Demucs versions sanitize the source basename differently; search output tree.
            matches = list(temp_dir.rglob(stem_name))
            if not matches:
                raise RuntimeError("Demucs completed but its expected stem file was not found.")
            stem_path = matches[0]
        # Convert the high-quality separated WAV to a standard 320 kbps MP3 output.
        conv = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(stem_path),
             "-codec:a", "libmp3lame", "-b:a", "320k", str(output_path)],
            capture_output=True, text=True, timeout=300
        )
        if conv.returncode != 0 or not output_path.exists():
            raise RuntimeError(("Could not encode separated audio: " + (conv.stderr or "FFmpeg failed"))[-700:])
        return True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




def render_synth_layer(input_path, output_path, tool, p1, p2):
    """Generate a local oscillator layer and mix it with the complete source track."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)],
        capture_output=True, text=True, timeout=30
    )
    try:
        duration = max(0.1, min(3600.0, float(probe.stdout.strip())))
    except (ValueError, TypeError):
        raise RuntimeError("Could not read the audio duration for instrument generation.")

    if tool == "cowbell-layer":
        # Two inharmonic sine partials create a metallic cowbell-like synthetic tone.
        freq = max(500, min(1800, float(p2)))
        volume = max(0.02, min(0.28, float(p1) / 35.0))
        source = f"aevalsrc=0.65*sin(2*PI*{freq:.2f}*t)+0.35*sin(2*PI*{freq*1.477:.2f}*t):s=44100:d={duration:.4f}"
        layer_filter = f"highpass=f=350,lowpass=f=4200,tremolo=f=5:d=0.22,volume={volume:.3f}"
    elif tool == "808-bass-layer":
        freq = max(35, min(90, float(p2)))
        volume = max(0.03, min(0.50, float(p1) / 28.0))
        source = f"sine=frequency={freq:.2f}:sample_rate=44100:duration={duration:.4f}"
        layer_filter = f"lowpass=f=140,afade=t=in:st=0:d=0.03,volume={volume:.3f}"
    else:
        # A pulsed low sine layer, not a claim of a complete drum performance.
        rate = max(2, min(14, float(p2)))
        volume = max(0.02, min(0.30, float(p1) / 35.0))
        source = f"sine=frequency=115:sample_rate=44100:duration={duration:.4f}"
        layer_filter = f"tremolo=f={rate:.2f}:d=0.85,highpass=f=45,lowpass=f=240,volume={volume:.3f}"

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path), "-f", "lavfi", "-i", source,
        "-filter_complex",
        f"[1:a]{layer_filter},aformat=sample_rates=44100:channel_layouts=stereo[synth];"
        f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[base];"
        f"[base][synth]amix=inputs=2:duration=first:dropout_transition=0:weights=1 0.45,alimiter=limit=0.93[out]",
        "-map", "[out]", "-codec:a", "libmp3lame", "-b:a", "320k", str(output_path)
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(("Instrument layer generation failed: " + (proc.stderr or "FFmpeg failed"))[-700:])
    return True


def make_filter(tool, p1, p2):
    # Inputs are bounded before being interpolated into FFmpeg filter expressions.
    p1f, p2f = float(p1), float(p2)
    p1i, p2i = int(p1f), int(p2f)
    filters = {
        "auto-master-magic": f"highpass=f=30,bass=g={min(12,p1f)}:f=90,treble=g={min(8,p2f)}:f=4500,acompressor=threshold=-14dB:ratio=3.5:attack=5:release=50,loudnorm=I=-16:TP=-1.5:LRA=11",
        "smart-instrumental-blend": f"extrastereo=m={max(1,min(2.5,p2f)):.2f},bass=g={min(12,p1f)}:f=65,equalizer=f=320:width_type=o:w=1.5:g=2,aecho=0.8:0.7:55:0.25",
        "poyo-ai": f"highpass=f=35,acompressor=threshold=-12dB:ratio=4:attack=5:release=50,bass=g={min(12,p1f)}:f=95,treble=g={min(8,p2f)}:f=4200",
        "pixazo-ai": f"equalizer=f=3200:width_type=o:w=2:g={min(8,p1f)},bass=g=4:f=100,acompressor=threshold=-11dB:ratio=3.5,volume={min(5,p2f)}dB",
        "3d-audio": f"apulsator=mode=sine:hz={max(.05,min(3,p1f/10)):.2f}:width=1,extrastereo=m={max(1,min(2.5,p2f)):.2f},aecho=0.7:0.6:60:0.25",
        "autopanner": f"apulsator=mode=sine:hz={max(.1,min(5,p1f)):.2f}:width={max(.1,min(1,p2f/100)):.2f}",
        "bass-booster": f"bass=g={max(-6,min(18,p1f))}:f={max(50,min(250,p2i))}:w=0.5,alimiter=limit=0.95",
        "equalizer": f"bass=g={max(-18,min(18,p1f))}:f=100,treble=g={max(-18,min(18,p2f))}:f=3500",
        "noise-reducer": f"highpass=f={max(60,min(400,p2i))},lowpass=f={max(4000,min(16000,12000-p1i*300))},afftdn=nf=-25",
        "pitch-shifter": f"asetrate=44100*{2**(max(-12,min(12,p1f))/12):.6f},aresample=44100,atempo={max(.5,min(2,2**(-max(-12,min(12,p1f))/12))):.6f}",
        "reverb-full-song": f"aecho=0.8:0.7:{max(30,min(900,int(p1f*22)))}:{max(.1,min(.85,p2f/100)):.2f},extrastereo=m=1.25",
        "reverb": f"aecho=0.8:0.7:{max(20,min(1000,int(p1f*10)))}:{max(.1,min(.85,p2f/100)):.2f}",
        "reverse": f"areverse,volume={max(-12,min(12,p1f))}dB",
        "stereo-panner": f"pan=stereo|c0={max(0,min(1,1-max(0,p1f/10))):.2f}*c0|c1={max(0,min(1,1+min(0,p1f/10))):.2f}*c1",
        "tempo": f"atempo={max(.5,min(2,p1f)):.3f}",
        "vocal-remover": "pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0,highpass=f=90,alimiter=limit=0.95",
        "instrument-extractor": f"pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0,highpass=f=90,lowpass=f={max(1500,min(12000,p2i))},bass=g={max(0,min(6,p1f))}:f=95,alimiter=limit=0.95",
        "volume": f"volume={max(-24,min(18,p1f))}dB",
        "lofi": f"asetrate=44100*{max(.75,min(1,p2f/100)):.3f},aresample=44100,highpass=f=220,lowpass=f={max(1800,min(4800,4800-p1i*130))},aecho=0.7:0.6:45:0.2",
        "nightcore": f"asetrate=44100*{1.1+max(1,min(20,p1f))*.012:.3f},aresample=44100,bass=g={max(0,min(12,p2f))}:f=110",
        "underwater": f"lowpass=f={max(200,800-int(p1f*28))},aecho=0.7:0.6:80:0.25",
        "phone-call": f"highpass=f=450,lowpass=f={max(1500,min(4000,int(p1f*180)))},acompressor=threshold=-15dB:ratio=5",
        "concert-hall": f"aecho=0.8:0.7:{max(80,int(p1f*25))}:{max(.2,min(.85,p2f/100)):.2f},extrastereo=m=1.3",
        "radio-broadcast": f"highpass=f=320,lowpass=f=3800,acompressor=threshold=-12dB:ratio={max(2,min(10,p1f)):.1f},volume=2dB",
        "chipmunk": f"asetrate=44100*{1.25+max(1,min(20,p1f))*.018:.3f},aresample=44100,atempo=0.85",
        "demon-dark": f"asetrate=44100*{max(.55,.85-max(1,min(20,p1f))*.012):.3f},aresample=44100,atempo=1.1,bass=g={max(5,min(18,p2f))}:f=85",
        "spatial-wide": f"extrastereo=m={max(1.1,min(3,1.1+p1f*.1)):.2f}",
        "vinyl-crackles": f"highpass=f=280,lowpass=f=4500,vibrato=f={max(1,min(10,p1f*.5)):.1f}:d=0.2,aecho=0.7:0.6:30:0.2",
        "phaser-fx": f"aphaser=in_gain=0.6:out_gain=0.8:delay=3:decay={max(.1,min(.9,p2f/100)):.2f}:speed={max(.1,min(2,p1f*.1)):.2f}",
        "flanger-fx": f"flanger=delay=5:depth={max(1,min(10,int(p1f/2)))}:speed={max(.1,min(5,p2f/10)):.2f}",
        "tremolo-fx": f"tremolo=f={max(1,min(18,p1f*.8)):.1f}:d={max(.1,min(.95,p2f/100)):.2f}",
        "vibrato-fx": f"vibrato=f={max(1.5,min(14,p1f*.6)):.1f}:d={max(.1,min(.95,p2f/100)):.2f}",
        "studio-master": f"bass=g={max(2,min(12,p1f/2))}:f=95,treble=g={max(-6,min(10,p2f))}:f=4500,acompressor=threshold=-12dB:ratio=3.5,alimiter=limit=0.95",
        "club-punch": f"bass=g={max(3,min(18,p1f))}:f=88,acompressor=threshold=-10dB:ratio=4,volume={max(-3,min(5,p2f))}dB,alimiter=limit=0.95",
        "ambient-space": f"aecho=0.8:0.7:{max(120,int(p1f*30))}:0.55,lowpass=f=6000,extrastereo=m=1.3",
        "hq-enhance": f"treble=g={max(2,min(10,p1f))}:f=4200,bass=g={max(-3,min(8,p2f))}:f=100,alimiter=limit=0.95",
        "cyberpunk-fx": f"highpass=f=150,lowpass=f=5500,aphaser=in_gain=0.5:out_gain=0.8:delay=2.5:decay=0.4:speed=0.6,bass=g={max(4,min(16,p1f))}:f=90",
        "sub-bass-drop": f"bass=g={max(5,min(18,p1f))}:f={max(45,min(120,p2i))}:w=0.5,alimiter=limit=0.95",
        # New effects: all are local FFmpeg DSP, no cloud/API required.
        "vocal-isolator": "highpass=f=80,lowpass=f=14000,acompressor=threshold=-20dB:ratio=2.5:attack=8:release=90,alimiter=limit=0.95",
        "reverb-vocal-only": "highpass=f=100,lowpass=f=12000,aecho=0.7:0.6:90:0.3,alimiter=limit=0.95",
        "vocal-chop": (
            f"highpass=f=100,acompressor=threshold=-18dB:ratio=3:attack=4:release=45,"
            f"agate=threshold=0.015:ratio=8:attack=5:release=35,"
            f"aselect='not(mod(n,{max(2,min(12,p1i))}))',asetpts=N/SR/TB,"
            f"afade=t=in:d=0.008,afade=t=out:st=0:d=0.008"
        ),
        "smooth-flow": (
            "highpass=f=28,lowpass=f=18000,"
            "equalizer=f=250:width_type=o:w=1.2:g=-1.5,"
            "equalizer=f=3500:width_type=o:w=1.2:g=1.2,"
            "acompressor=threshold=-18dB:ratio=2.5:attack=15:release=120,"
            "alimiter=limit=0.95,loudnorm=I=-16:TP=-1.5:LRA=11"
        ),
        "vocal-presence": (
            f"highpass=f=75,equalizer=f=220:width_type=o:w=1.2:g=-2,"
            f"equalizer=f=3000:width_type=o:w=1.1:g={max(1,min(6,p1f)):.1f},"
            f"equalizer=f=9000:width_type=o:w=1.5:g={max(0,min(4,p2f)):.1f},"
            "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=90,alimiter=limit=0.95"
        ),
        "de-esser": (
            f"highpass=f=250,lowpass=f=14000,"
            f"equalizer=f=6500:width_type=o:w=1.2:g={-max(1,min(8,p1f)):.1f},"
            "acompressor=threshold=-20dB:ratio=2:attack=2:release=60,alimiter=limit=0.95"
        ),
        "warm-analog": (
            f"highpass=f=30,bass=g={max(0,min(5,p1f))}:f=110,"
            f"equalizer=f=2500:width_type=o:w=1.5:g=-1.5,"
            f"treble=g={max(-2,min(3,p2f))}:f=8500,"
            "acompressor=threshold=-18dB:ratio=2:attack=20:release=140,alimiter=limit=0.95"
        ),
        "club-pump": (
            f"bass=g={max(2,min(10,p1f))}:f=85,"
            f"tremolo=f={max(1,min(8,p2f))}:d=0.35,"
            "acompressor=threshold=-14dB:ratio=3:attack=5:release=80,alimiter=limit=0.93"
        ),
        # Reels / Shorts style effects. These are FFmpeg DSP presets, not AI stem separation.
        "reels-slowed-reverb": (
            f"asetrate=44100*{max(.72,min(.98,p1f/100)):.3f},aresample=44100,"
            f"atempo={max(1.0,min(1.35,1/(max(.72,min(.98,p1f/100))))):.3f},"
            f"aecho=0.75:0.65:{max(45,min(320,int(p2f*4)))}:0.32,"
            "bass=g=3:f=90,alimiter=limit=0.94"
        ),
        "reels-sped-up": (
            f"asetrate=44100*{max(1.04,min(1.35,1+p1f/100)):.3f},aresample=44100,"
            "highpass=f=28,bass=g=2:f=110,alimiter=limit=0.95"
        ),
        "phonk-reels": (
            f"highpass=f=28,bass=g={max(5,min(14,p1f))}:f=72,"
            "equalizer=f=250:width_type=o:w=1.3:g=-2,"
            "equalizer=f=1800:width_type=o:w=1.2:g=2.5,"
            "acompressor=threshold=-13dB:ratio=4:attack=4:release=70,"
            "alimiter=limit=0.92"
        ),
        "sad-reels": (
            f"asetrate=44100*{max(.78,min(.96,p1f/100)):.3f},aresample=44100,"
            f"atempo={max(1.02,min(1.25,1/(max(.78,min(.96,p1f/100))))):.3f},"
            f"aecho=0.7:0.6:{max(80,min(380,int(p2f*5)))}:0.42,"
            "lowpass=f=14500,alimiter=limit=0.94"
        ),
        "romantic-reels": (
            f"highpass=f=35,bass=g=2:f=100,"
            f"equalizer=f=3200:width_type=o:w=1.3:g=1.5,"
            f"aecho=0.72:0.58:{max(45,min(220,int(p1f*5)))}:0.22,"
            "acompressor=threshold=-19dB:ratio=2:attack=15:release=140,alimiter=limit=0.95"
        ),
        "dreamy-vocal": (
            f"highpass=f=90,equalizer=f=3000:width_type=o:w=1.2:g=2.5,"
            f"equalizer=f=9000:width_type=o:w=1.5:g=1.5,"
            f"aecho=0.65:0.55:{max(35,min(240,int(p1f*4)))}:0.28,"
            "acompressor=threshold=-19dB:ratio=2.2:attack=8:release=100,alimiter=limit=0.94"
        ),
        "glitch-edit": (
            f"highpass=f=80,aphaser=in_gain=0.6:out_gain=0.8:delay=3:decay=0.5:speed={max(.3,min(2.5,p1f/5)):.2f},"
            f"tremolo=f={max(4,min(16,p2f)):.1f}:d=0.55,alimiter=limit=0.93"
        ),
        "cinematic-drop": (
            f"lowpass=f={max(500,min(6000,int(p1f*250)))} ,"
            f"aecho=0.8:0.65:{max(100,min(700,int(p2f*18)))}:0.4,"
            "bass=g=5:f=65,acompressor=threshold=-12dB:ratio=3.5:attack=5:release=100,alimiter=limit=0.92"
        ),
        "viral-master": (
            "highpass=f=28,lowpass=f=18500,"
            "equalizer=f=220:width_type=o:w=1.1:g=-1,"
            "equalizer=f=3200:width_type=o:w=1.1:g=1.5,"
            "bass=g=2.5:f=95,acompressor=threshold=-16dB:ratio=3:attack=8:release=90,"
            "loudnorm=I=-14:TP=-1.2:LRA=10,alimiter=limit=0.94"
        ),
        "clean-vocal-mix": (
            "highpass=f=75,afftdn=nf=-22,"
            "equalizer=f=220:width_type=o:w=1.2:g=-1.5,"
            "equalizer=f=3000:width_type=o:w=1.1:g=2,"
            "equalizer=f=8000:width_type=o:w=1.5:g=1,"
            "acompressor=threshold=-19dB:ratio=2.5:attack=8:release=100,alimiter=limit=0.94"
        ),
        "bass-drop-impact": (
            f"highpass=f=25,bass=g={max(5,min(15,p1f))}:f={max(45,min(100,p2i))}:w=0.5,"
            "equalizer=f=250:width_type=o:w=1.2:g=-2,"
            "acompressor=threshold=-12dB:ratio=4:attack=3:release=80,alimiter=limit=0.91"
        ),
        "stereo-reels": (
            f"highpass=f=30,extrastereo=m={max(1.1,min(2.5,1+p1f/10)):.2f},"
            f"apulsator=mode=sine:hz={max(.08,min(1.5,p2f/10)):.2f}:width=0.7,alimiter=limit=0.94"
        ),
        # Music-style remix presets. These process the uploaded mix; they do not separate stems.
        "phonk-maker": (
            f"highpass=f=28,bass=g={max(4,min(14,p1f))}:f=72,"
            "equalizer=f=240:width_type=o:w=1.2:g=-2,"
            "equalizer=f=1600:width_type=o:w=1.1:g=2.5,"
            "acompressor=threshold=-13dB:ratio=4:attack=4:release=75,alimiter=limit=0.92"
        ),
        "brazilian-funk": (
            f"highpass=f=30,bass=g={max(3,min(12,p1f))}:f=95,"
            f"tremolo=f={max(2,min(12,p2f))}:d=0.25,"
            "acompressor=threshold=-12dB:ratio=3.5:attack=5:release=80,alimiter=limit=0.92"
        ),
        "drift-phonk": (
            f"highpass=f=25,bass=g={max(5,min(15,p1f))}:f=65,"
            "equalizer=f=280:width_type=o:w=1.2:g=-2.5,"
            "equalizer=f=2200:width_type=o:w=1.1:g=3,"
            "acompressor=threshold=-12dB:ratio=4.5:attack=3:release=75,alimiter=limit=0.91"
        ),
        "cowbell-layer": (
            f"equalizer=f=650:width_type=o:w=1.1:g={max(1,min(8,p1f))},"
            "equalizer=f=1300:width_type=o:w=1.1:g=2,"
            "tremolo=f=5:d=0.45,alimiter=limit=0.94"
        ),
        "808-bass-layer": (
            f"bass=g={max(4,min(14,p1f))}:f={max(35,min(90,p2i))}:w=0.5,"
            "lowpass=f=140,acompressor=threshold=-15dB:ratio=3:attack=5:release=90,alimiter=limit=0.92"
        ),
        "funk-drum-pulse": (
            f"highpass=f=30,bass=g={max(2,min(10,p1f))}:f=100,"
            f"tremolo=f={max(3,min(14,p2f))}:d=0.4,"
            "acompressor=threshold=-13dB:ratio=3.5:attack=4:release=65,alimiter=limit=0.92"
        ),
        "dark-synth": (
            f"lowpass=f={max(1200,min(7000,int(p1f*500)))},"
            f"aphaser=in_gain=0.6:out_gain=0.8:delay=3:decay=0.65:speed={max(.2,min(2,p2f/5)):.2f},"
            "bass=g=4:f=75,alimiter=limit=0.93"
        ),
        "beat-drop-impact": (
            f"bass=g={max(4,min(12,p1f))}:f=60,"
            f"aecho=0.8:0.65:{max(80,min(600,int(p2f*12)))}:0.35,"
            "acompressor=threshold=-12dB:ratio=4:attack=3:release=80,alimiter=limit=0.92"
        ),
        "lofi-remix": (
            f"asetrate=44100*{max(.82,min(1,p1f/100)):.3f},aresample=44100,"
            "lowpass=f=7000,highpass=f=180,aecho=0.7:0.55:70:0.22,alimiter=limit=0.94"
        ),
        "romantic-remix": (
            f"equalizer=f=250:width_type=o:w=1.2:g=1.5,"
            f"equalizer=f=3500:width_type=o:w=1.2:g=1.2,"
            f"aecho=0.75:0.58:{max(45,min(220,int(p1f*5)))}:0.22,"
            "acompressor=threshold=-19dB:ratio=2.2:attack=12:release=130,alimiter=limit=0.94"
        ),
        "reels-master": (
            "highpass=f=28,lowpass=f=18500,"
            "equalizer=f=220:width_type=o:w=1.1:g=-1,"
            "equalizer=f=3200:width_type=o:w=1.1:g=1.5,"
            "acompressor=threshold=-15dB:ratio=3:attack=8:release=90,"
            "loudnorm=I=-14:TP=-1.2:LRA=10,alimiter=limit=0.94"
        ),
        "echo-fx": f"aecho=0.8:0.7:{max(30,min(700,p1i))}:{max(.1,min(.85,p2f/100)):.2f},alimiter=limit=0.94",
        "stereo-widening": f"extrastereo=m={max(1.05,min(2.5,1+p1f*.075)):.2f},alimiter=limit=0.95",
        "sad-remix": f"asetrate=44100*{max(.78,min(.96,p1f/100)):.3f},aresample=44100,aecho=0.72:0.58:{max(70,min(380,int(p2f*5)))}:0.38,lowpass=f=15000,alimiter=limit=0.94",
        "dark-remix": f"highpass=f=28,lowpass=f={max(2500,min(9000,9000-p1i*250))},bass=g={max(2,min(10,p1f))}:f=85,aphaser=in_gain=0.6:out_gain=0.8:delay=3:decay=.45:speed={max(.2,min(1.8,p2f/10)):.2f},aecho=0.7:0.55:110:0.22,alimiter=limit=0.93",
        "aggressive-remix": f"highpass=f=28,bass=g={max(4,min(14,p1f))}:f=75,equalizer=f=240:width_type=o:w=1.2:g=-2,equalizer=f=2200:width_type=o:w=1.1:g={max(1,min(5,p2f))},acompressor=threshold=-13dB:ratio=4:attack=4:release=75,alimiter=limit=0.92",
        "cinematic-remix": f"highpass=f=28,equalizer=f=180:width_type=o:w=1.2:g=2,aecho=0.8:0.65:{max(100,min(700,int(p1f*20)))}:{max(.2,min(.65,p2f/100)):.2f},extrastereo=m=1.35,acompressor=threshold=-16dB:ratio=2.5:attack=15:release=130,alimiter=limit=0.93",
        "ambient-remix": f"lowpass=f={max(3500,min(9000,9000-p1i*200))},aecho=0.8:0.68:{max(100,min(700,int(p1f*20)))}:{max(.2,min(.7,p2f/100)):.2f},extrastereo=m=1.45,alimiter=limit=0.93",
        "echo-remix": f"aecho=0.8:0.7:{max(80,min(600,int(p1f*18)))}:{max(.15,min(.8,p2f/100)):.2f},equalizer=f=3000:width_type=o:w=1.2:g=1,alimiter=limit=0.94",
        "concert-hall-remix": f"aecho=0.8:0.72:{max(100,min(850,int(p1f*24)))}|{max(240,min(1000,int(p1f*24)+140))}:{max(.2,min(.8,p2f/100)):.2f}|0.28,extrastereo=m=1.4,alimiter=limit=0.93",
        "underwater-remix": f"lowpass=f={max(220,min(1800,1800-p1i*65))},highpass=f=35,aecho=0.72:0.6:{max(60,min(300,int(p2f*4)))}:0.3,alimiter=limit=0.94",
        "vinyl-remix": f"highpass=f=120,lowpass=f={max(3500,min(9000,9000-p1i*220))},vibrato=f={max(1,min(8,p2f/2)):.1f}:d=0.12,aecho=0.65:0.45:35:0.12,alimiter=limit=0.94",
        "slowed-remix": f"asetrate=44100*{max(.70,min(.98,p1f/100)):.3f},aresample=44100,lowpass=f=16000,aecho=0.75:0.62:{max(50,min(350,int(p2f*4)))}:0.25,alimiter=limit=0.93",
        "reverb-remix": f"aecho=0.75:0.68:{max(50,min(700,int(p1f*18)))}:{max(.15,min(.8,p2f/100)):.2f},extrastereo=m=1.25,alimiter=limit=0.94",
        "dreamy-remix": f"equalizer=f=3200:width_type=o:w=1.2:g=2,equalizer=f=9000:width_type=o:w=1.5:g=1.5,aecho=0.65:0.55:{max(45,min(300,int(p1f*5)))}:{max(.15,min(.6,p2f/100)):.2f},extrastereo=m=1.4,alimiter=limit=0.93",
        "space-remix": f"extrastereo=m={max(1.2,min(2.2,1.2+p1f/12)):.2f},aecho=0.8:0.65:{max(120,min(750,int(p1f*25)))}:{max(.2,min(.7,p2f/100)):.2f},lowpass=f=8500,alimiter=limit=0.93",
        "chill-remix": f"highpass=f=30,bass=g={max(1,min(5,p1f/2))}:f=110,treble=g=-1:f=7000,aecho=0.7:0.55:{max(40,min(240,int(p2f*3)))}:0.18,acompressor=threshold=-18dB:ratio=2.2:attack=18:release=140,alimiter=limit=0.94",
        "bass-boost-remix": f"highpass=f=25,bass=g={max(2,min(16,p1f))}:f={max(45,min(150,p2i))}:w=0.5,acompressor=threshold=-13dB:ratio=3,alimiter=limit=0.91",
        "dance-remix": f"highpass=f=28,bass=g={max(2,min(9,p1f))}:f=95,equalizer=f=3500:width_type=o:w=1.2:g={max(1,min(4,p2f))},acompressor=threshold=-14dB:ratio=3:attack=5:release=80,alimiter=limit=0.93",
        "club-remix": f"highpass=f=28,bass=g={max(3,min(12,p1f))}:f=85,treble=g={max(1,min(5,p2f))}:f=5000,acompressor=threshold=-13dB:ratio=3.5:attack=5:release=80,extrastereo=m=1.2,alimiter=limit=0.92",
        "atmospheric-remix": f"lowpass=f=12000,aecho=0.75:0.65:{max(90,min(750,int(p1f*22)))}:{max(.2,min(.75,p2f/100)):.2f},aphaser=in_gain=0.7:out_gain=0.8:delay=3:decay=.35:speed=.25,extrastereo=m=1.35,alimiter=limit=0.93",
        "downmixer": f"volume={max(-12,min(12,p1f))}dB",
        "preset-8d-audio": f"apulsator=mode=sine:hz={max(.05,min(1.5,p1f/20)):.3f}:width=1,extrastereo=m=1.6,aecho=0.7:0.6:60:0.25,bass=g={max(0,min(10,p2f))}:f=100",
        "preset-slowed-reverb": f"asetrate=44100*{max(.65,min(.98,p1f/100)):.3f},aresample=44100,aecho=0.7:0.6:{max(30,min(300,int(p2f*8)))}:0.35",
        "preset-432hz": "asetrate=44100*0.981818,aresample=44100,atempo=1.018518",
        "preset-very-light-bass": f"bass=g={max(0,min(10,p1f))}:f={max(50,min(250,p2i))}",
        "preset-light-bass": f"bass=g={max(0,min(12,p1f))}:f={max(50,min(250,p2i))}",
        "preset-moderate-bass": f"bass=g={max(0,min(15,p1f))}:f={max(50,min(250,p2i))}",
        "preset-heavy-bass": f"bass=g={max(0,min(18,p1f))}:f={max(50,min(250,p2i))},alimiter=limit=0.95",
        "preset-extreme-bass": f"bass=g={max(0,min(20,p1f))}:f={max(50,min(250,p2i))},alimiter=limit=0.92",
        "preset-vocal-reverb": f"aecho=0.8:0.7:{max(20,int(p1f*5))}:{max(.1,min(.85,p2f/100)):.2f}",
        "preset-bathroom-reverb": f"aecho=0.8:0.7:{max(15,int(p1f*3))}|{max(35,int(p1f*3)+20)}:{max(.1,min(.85,p2f/100)):.2f}|0.25",
        "preset-small-room-reverb": f"aecho=0.8:0.7:{max(25,int(p1f*5))}:{max(.1,min(.85,p2f/100)):.2f}",
        "preset-medium-room-reverb": f"aecho=0.8:0.7:{max(40,int(p1f*8))}:{max(.1,min(.85,p2f/100)):.2f}",
        "preset-large-room-reverb": f"aecho=0.8:0.7:{max(80,int(p1f*12))}:{max(.1,min(.88,p2f/100)):.2f}",
        "preset-church-hall-reverb": f"aecho=0.8:0.7:{max(120,int(p1f*18))}|{max(260,int(p1f*18)+140)}:{max(.2,min(.9,p2f/100)):.2f}|0.3",
        "preset-cathedral-reverb": f"aecho=0.8:0.7:{max(200,int(p1f*25))}|{max(550,int(p1f*25)+350)}:{max(.2,min(.9,p2f/100)):.2f}|0.4",
    }
    if tool == "trimmer":
        return None
    if tool == "reverb-vocal-only":
        # A simple, compatible frequency-focused wet blend; not true stem isolation.
        delay = max(25, min(700, int(p1f * 20)))
        decay = max(.1, min(.85, p2f / 100))
        return f"highpass=f=180,aecho=0.7:0.6:{delay}:{decay:.2f},amix=inputs=1"
    return filters.get(tool)



# Built-in example track is only used in the Before / After comparison area.
def get_example_audio():
    candidates = [p for p in ROOT.iterdir()
                  if p.is_file() and p.suffix.lower() in AUDIO_EXTS
                  and ("example" in p.name.lower() or "before and after" in p.name.lower())]
    return candidates[0] if candidates else None

@app.get("/api/example-source")
def example_source():
    source = get_example_audio()
    if source is None:
        return jsonify(error="The example song was not found in the project folder."), 404
    return send_file(source, conditional=True)

@app.post("/api/example-render")
def example_render():
    if not ffmpeg_available():
        return jsonify(error="FFmpeg and ffprobe must be installed."), 503
    source = get_example_audio()
    if source is None:
        return jsonify(error="The example song was not found in the project folder."), 404
    tool = request.form.get("tool", "")
    if tool not in ALLOWED_TOOLS or tool in {"spectrogram", "waveform"}:
        return jsonify(error="This tool does not create an audio preview."), 400
    p1 = number("param1", 6, -24, 2500)
    p2 = number("param2", 2, -24, 2500)
    safe_tool = re.sub(r"[^a-zA-Z0-9_-]", "", tool)
    cache_name = f"example_{safe_tool}_{str(p1).replace('.', '_')}_{str(p2).replace('.', '_')}.mp3"
    output = OUTPUTS / cache_name
    if not output.exists():
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
        filt = make_filter(tool, p1, p2)
        if filt:
            cmd += ["-af", filt]
        cmd += ["-codec:a", "libmp3lame", "-b:a", "320k", str(output)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            output.unlink(missing_ok=True)
            return jsonify(error="Example processing took too long on this device."), 504
        if proc.returncode != 0 or not output.exists():
            output.unlink(missing_ok=True)
            return jsonify(error=(proc.stderr or "Could not process the example song.")[-600:]), 500
    return send_file(output, mimetype="audio/mpeg", conditional=True)



@app.post("/api/ai/cover")
def generate_ai_cover():
    """Submit cover-art generation to Pixazo without exposing the API key."""
    api_key = os.environ.get("PIXAZO_API_KEY", "").strip()
    if not api_key:
        return jsonify(error="Pixazo is not configured on the server."), 503

    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()

    if len(prompt) < 3 or len(prompt) > 3000:
        return jsonify(error="Prompt must contain 3–3000 characters."), 400

    try:
        response = requests.post(
            "https://gateway.pixazo.ai/gpt-image-2/v1/text-to-image",
            headers={
                "Ocp-Apim-Subscription-Key": api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            },
            json={"prompt": prompt},
            timeout=30,
        )

        if response.status_code not in (200, 202):
            return jsonify(
                error=f"Pixazo request failed ({response.status_code}).",
                details=response.text[:500]
            ), 502

        result = response.json()
        request_id = result.get("request_id")
        if not request_id:
            return jsonify(error="Pixazo returned no request ID."), 502

        return jsonify(
            request_id=request_id,
            status=result.get("status", "QUEUED"),
        ), 202

    except requests.RequestException:
        return jsonify(error="Could not connect to Pixazo. Try again later."), 502
    except ValueError:
        return jsonify(error="Pixazo returned an invalid response."), 502


@app.get("/api/ai/cover/status/<request_id>")
def ai_cover_status(request_id):
    """Check Pixazo job status using a fixed, trusted API endpoint."""
    api_key = os.environ.get("PIXAZO_API_KEY", "").strip()
    if not api_key:
        return jsonify(error="Pixazo is not configured on the server."), 503

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", request_id):
        return jsonify(error="Invalid request ID."), 400

    try:
        response = requests.get(
            "https://gateway.pixazo.ai/v2/requests/status/"
            + request_id,
            headers={"Ocp-Apim-Subscription-Key": api_key},
            timeout=20,
        )

        if response.status_code != 200:
            return jsonify(
                error=f"Pixazo status check failed ({response.status_code})."
            ), 502

        result = response.json()
        state = str(result.get("status", "UNKNOWN")).upper()
        output = result.get("output") or {}
        urls = output.get("media_url") or []
        image_url = urls[0] if urls else None

        # Only return a public image URL from the expected CDN domain.
        if image_url:
            from urllib.parse import urlparse
            parsed = urlparse(image_url)
            if parsed.scheme != "https" or not (
                parsed.hostname or ""
            ).endswith(".r2.dev"):
                image_url = None

        return jsonify(
            request_id=request_id,
            status=state,
            image_url=image_url if state == "COMPLETED" else None,
            error=result.get("error"),
        )

    except requests.RequestException:
        return jsonify(error="Could not check Pixazo job status."), 502
    except ValueError:
        return jsonify(error="Pixazo returned an invalid status response."), 502


@app.post("/api/process")
def process_audio():
    if not ffmpeg_available():
        return jsonify(error="FFmpeg and ffprobe must be installed and available on PATH."), 503
    if "audio" not in request.files:
        return jsonify(error="Choose an audio file first."), 400
    upload = request.files["audio"]
    if not upload.filename:
        return jsonify(error="The selected file has no filename."), 400
    original = secure_filename(upload.filename)
    ext = Path(original).suffix.lower()
    if ext not in AUDIO_EXTS:
        return jsonify(error="Unsupported audio format. Try MP3, WAV, FLAC, OGG, M4A, AAC, OPUS or WMA."), 400
    tool = request.form.get("tool", "")
    if tool not in ALLOWED_TOOLS:
        return jsonify(error="Unknown tool."), 400

    p1 = number("param1", 6, -24, 2500)
    p2 = number("param2", 2, -24, 2500)
    uid = uuid.uuid4().hex[:10]
    input_path = UPLOADS / f"{uid}{ext}"
    upload.save(input_path)

    out_format = request.form.get("format", "mp3").lower()
    if out_format not in {"mp3", "wav", "flac", "ogg", "m4a"}:
        input_path.unlink(missing_ok=True)
        return jsonify(error="Unsupported output format."), 400

    is_image = tool in {"spectrogram", "waveform"}
    out_ext = ".png" if is_image else (f".{out_format}" if tool == "converter" else ".mp3")
    output_path = OUTPUTS / f"studio_{uid}_{tool}{out_ext}"

    try:
        if tool in {"cowbell-layer", "808-bass-layer", "funk-drum-pulse"}:
            render_synth_layer(input_path, output_path, tool, p1, p2)
            return send_file(output_path, mimetype="audio/mpeg", as_attachment=False, download_name=output_path.name)
        elif tool in {"vocal-remover", "instrument-extractor", "vocal-isolator"}:
            run_stem_separation(input_path, output_path, tool, uid)
            return send_file(output_path, mimetype="audio/mpeg", as_attachment=False, download_name=output_path.name)
        elif tool == "reverb-vocal-only" and find_demucs():
            # Isolate vocals with the AI model, then apply the requested vocal-style reverb.
            temp_dir = OUTPUTS / f"vocal_reverb_{uid}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            try:
                cmd_sep = find_demucs() + ["--two-stems", "vocals", "-n", "htdemucs", "-o", str(temp_dir), str(input_path)]
                proc_sep = subprocess.run(cmd_sep, capture_output=True, text=True, timeout=1800)
                if proc_sep.returncode != 0:
                    raise RuntimeError(("Demucs failed: " + (proc_sep.stderr or proc_sep.stdout or "unknown error"))[-900:])
                stem_matches = list(temp_dir.rglob("vocals.wav"))
                if not stem_matches:
                    raise RuntimeError("AI vocal stem was not created.")
                filt = f"aecho=0.75:0.6:{max(35,min(250,int(p1*5)))}:{max(.1,min(.8,p2/100)):.2f},alimiter=limit=0.95"
                proc_fx = subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(stem_matches[0]),"-af",filt,"-codec:a","libmp3lame","-b:a","320k",str(output_path)],capture_output=True,text=True,timeout=300)
                if proc_fx.returncode != 0:
                    raise RuntimeError(("Vocal reverb failed: " + (proc_fx.stderr or "FFmpeg failed"))[-700:])
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return send_file(output_path, mimetype="audio/mpeg", as_attachment=False, download_name=output_path.name)
        elif tool == "spectrogram":
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path),
                   "-lavfi", "showspectrumpic=s=1280x640:color=fiery", str(output_path)]
        elif tool == "waveform":
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path),
                   "-lavfi", "showwavespic=s=1280x360:colors=0x00e5ff", str(output_path)]
        else:
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
            if tool == "trimmer":
                start = number("start", 0, 0, 86400)
                end = number("end", 30, 0.1, 86400)
                if end <= start:
                    return jsonify(error="End time must be greater than start time."), 400
                cmd += ["-ss", str(start), "-to", str(end), "-i", str(input_path)]
            else:
                cmd += ["-i", str(input_path)]
            if tool == "downmixer":
                cmd += ["-ac", "1"]
            if tool == "converter":
                if out_format == "mp3":
                    cmd += ["-codec:a", "libmp3lame", "-b:a", "320k"]
                elif out_format == "m4a":
                    cmd += ["-codec:a", "aac", "-b:a", "256k"]
                elif out_format == "ogg":
                    cmd += ["-codec:a", "libvorbis", "-q:a", "6"]
                elif out_format == "flac":
                    cmd += ["-codec:a", "flac"]
                else:
                    cmd += ["-codec:a", "pcm_s16le"]
            else:
                filt = make_filter(tool, p1, p2)
                if filt:
                    cmd += ["-af", filt]
                cmd += ["-codec:a", "libmp3lame", "-b:a", "320k"]
            cmd.append(str(output_path))

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0 or not output_path.exists():
            message = (proc.stderr or "FFmpeg could not process this file.")[-700:]
            return jsonify(error=message), 500
        mimetype = "image/png" if is_image else ("audio/wav" if out_ext == ".wav" else "audio/mpeg")
        return send_file(output_path, mimetype=mimetype, as_attachment=False, download_name=output_path.name)
    except subprocess.TimeoutExpired:
        return jsonify(error="Processing took too long. Try a shorter audio file."), 504
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503
    finally:
        input_path.unlink(missing_ok=True)

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="File is too large. Maximum upload size is 150 MB."), 413

if __name__ == "__main__":
    print("Akhil Audio Studio Pro: http://127.0.0.1:5000")
    print("For local use only. Keep API keys out of source code.")
    app.run(host="127.0.0.1", port=5000, debug=False)
