# FABBRICA CLIP GTA 6 - un solo comando: testo (clip.json) -> clip verticale pronta.
# Uso:  python3 fabbrica.py CARTELLA_CLIP CARTELLA_MATERIALI MODELLI_VOCE [anteprima]
#   CARTELLA_CLIP      contiene clip.json; qui finiscono video, anteprime e testi
#   CARTELLA_MATERIALI contiene video-clip/, extended-look/, musica/
#   MODELLI_VOCE       contiene kokoro-v1.0.onnx e voices-v1.0.bin (scaricabili da GitHub)
# Passi: 1 voce (Kokoro, gratis) -> 2 inquadrature verticali -> 3 montaggio con titoli,
#        sottotitoli parola per parola, barra di avanzamento -> 4 audio (voce+musica) -> 5 file finale
import json, sys, os, re, hashlib, subprocess
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

CLIP, MAT, MOD = [os.path.abspath(a) for a in sys.argv[1:4]]
PREVIEW = len(sys.argv) > 4 and sys.argv[4] == "anteprima"
W, H, FPS, SR = 1080, 1920, 30, 24000
GAP, TAIL = 0.3, 0.8
FONT = "/usr/share/fonts/opentype/inter/Inter-Black.otf"
FONT_SMALL = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
YELLOW = (255, 214, 0)
cfg = json.load(open(f"{CLIP}/clip.json"))
SC = cfg["scene"]
os.makedirs(f"{CLIP}/lavoro/audio", exist_ok=True)
os.makedirs(f"{CLIP}/lavoro/inquadrature", exist_ok=True)
os.makedirs(f"{CLIP}/lavoro/scene", exist_ok=True)

def ff(args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + args, check=True)

def probe(path, entry):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entry,
                           "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()

# ---------- 1. VOCE ----------
def make_voice():
    from kokoro_onnx import Kokoro
    k = Kokoro(f"{MOD}/kokoro-v1.0.onnx", f"{MOD}/voices-v1.0.bin")
    durs = []
    for i, s in enumerate(SC, 1):
        a, sr = k.create(s["voce"], voice=cfg.get("voce", "am_puck"), speed=cfg.get("velocita", 1.0), lang="en-us")
        idx = np.where(np.abs(a) > 0.01)[0]
        a = a[max(0, idx[0] - int(0.03 * sr)): idx[-1] + int(0.1 * sr)]
        sf.write(f"{CLIP}/lavoro/audio/l{i:02d}.wav", a, sr); durs.append(len(a) / sr)
    return durs

# ---------- 2. INQUADRATURE (1080x1920) ----------
def shot_file(sp):
    key = hashlib.md5(json.dumps(sp, sort_keys=True).encode()).hexdigest()[:10]
    out = f"{CLIP}/lavoro/inquadrature/{sp['src']}_{key}.mp4"
    if os.path.exists(out): return out
    src = f"{MAT}/{cfg['fonti_video'][sp['src']]}"
    W0, H0 = map(int, probe(src, "stream=width,height").split(","))
    t0, t1 = sp.get("t0", 0), sp.get("t1")
    trim = f"trim={t0}:{t1}," if t1 else (f"trim=start={t0}," if t0 else "")
    speed = sp.get("speed", 1.0)
    post = ""
    if speed != 1.0: post += f",minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:vsbmc=1,setpts={1/speed}*PTS,fps=30"
    if sp.get("luce"): post += ",eq=gamma=1.45:saturation=1.15:contrast=1.05"
    if sp["modo"] == "crop":
        h = int(H0 / sp.get("zoom", 1.0)); w = int(h * 9 / 16)
        x = max(0, min(W0 - w, int(sp.get("cx", 0.5) * W0 - w / 2)))
        fc = f"[0:v]{trim}setpts=PTS-STARTPTS,crop={w}:{h}:{x}:{(H0-h)//2},scale=1080:1920:flags=lanczos{post}[v]"
    else:  # fit: fotogramma 16:9 intero su sfondo sfocato
        fgw = sp.get("fgw", 1350); fgh = int(round(fgw * 9 / 16 / 2) * 2); x = int((fgw - 1080) * sp.get("cx", 0.5))
        y = sp.get("y", (1920 - fgh) // 2)
        fc = (f"[0:v]{trim}setpts=PTS-STARTPTS{post},split[a][b];"
              f"[a]scale=-2:1920,crop=1080:1920,boxblur=24:2,eq=brightness=-0.18[bg];"
              f"[b]scale={fgw}:{fgh}:flags=lanczos,crop=1080:{fgh}:{x}:0[fg];[bg][fg]overlay=0:{y}[v]")
    # avanti + indietro (ping-pong) cosi' i pezzi corti durano il doppio senza scatti
    fc += ";[v]split[f][r0];[r0]reverse[r];[f][r]concat=n=2:v=1:a=0,fps=30[o]"
    ff(["-i", src, "-filter_complex", fc, "-map", "[o]", "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "17", "-pix_fmt", "yuv420p", out])
    return out

# ---------- 3. MONTAGGIO ----------
f_cap = ImageFont.truetype(FONT, 92); f_head = ImageFont.truetype(FONT, 96); f_small = ImageFont.truetype(FONT_SMALL, 30)

def word_timings(text, dur):
    w = []
    for wd in text.split():
        base = len(re.sub(r"[^\w']", "", wd)) + 1.5
        pause = 5.0 if wd.endswith("...") else (3.5 if wd[-1] in ".?!:" else (2.0 if wd[-1] == "," else 0))
        w.append((wd, base, pause))
    tot = sum(b + p for _, b, p in w); out, c = [], 0.0
    for wd, b, p in w:
        out.append((wd, c / tot * dur, (c + b) / tot * dur)); c += b + p
    return out

def chunks(wt):
    res, cur = [], []
    for item in wt:
        cur.append(item)
        if len(cur) == 3 or item[0][-1] in ".,?!:": res.append(cur); cur = []
    if cur: res.append(cur)
    return res

def static_layer(idx):
    L = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = np.zeros((H, W, 4), np.uint8)
    top = np.clip(1 - np.arange(H) / 760, 0, 1) ** 1.6 * 200
    bot = np.clip((np.arange(H) - 1000) / 920, 0, 1) ** 1.3 * 200
    g[..., 3] = np.maximum(top, bot).astype(np.uint8)[:, None]
    L = Image.alpha_composite(L, Image.fromarray(g, "RGBA")); d = ImageDraw.Draw(L); y = 150
    for ln in SC[idx]["titolo"].split("\n"):
        bb = d.textbbox((0, 0), ln, font=f_head); tw, th = bb[2] - bb[0], bb[3] - bb[1]; x = (W - tw) // 2
        d.rounded_rectangle([x - 30, y - 18, x + tw + 30, y + th + 34], radius=18, fill=YELLOW + (255,))
        d.text((x - bb[0], y - bb[1]), ln, font=f_head, fill=(0, 0, 0)); y += th + 66
    d.text((40, 1830), cfg.get("credito", ""), font=f_small, fill=(255, 255, 255, 170))
    return L

def caption_img(chunk, active):
    L = Image.new("RGBA", (W, 260), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    words = [c[0].upper().replace("...", "…") for c in chunk]; space = 26; f = f_cap
    widths = [d.textbbox((0, 0), w, font=f, stroke_width=10)[2] for w in words]
    total = sum(widths) + space * (len(words) - 1)
    if total > 1000:
        f = ImageFont.truetype(FONT, int(92 * 1000 / total))
        widths = [d.textbbox((0, 0), w, font=f, stroke_width=10)[2] for w in words]
        total = sum(widths) + space * (len(words) - 1)
    x = (W - total) // 2
    for i, w in enumerate(words):
        d.text((x, 80), w, font=f, fill=YELLOW if i == active else (255, 255, 255), stroke_width=10, stroke_fill=(0, 0, 0))
        x += widths[i] + space
    return L

def ease_out(x): return 1 - (1 - x) ** 3

class VidShot:
    def __init__(self, path, dur):
        self.path, self.dur = path, dur; self.last = None; self.open()
    def open(self):
        self.p = subprocess.Popen(["ffmpeg", "-loglevel", "quiet", "-i", self.path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                  stdout=subprocess.PIPE)
    def frame(self, tt):
        buf = self.p.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:  # finito: ricomincia (loop)
            self.open(); buf = self.p.stdout.read(W * H * 3)
        self.last = Image.frombuffer("RGB", (W, H), buf)
        z = (1.0 + 0.04 * tt / self.dur) * (1.06 - 0.06 * ease_out(min(1, tt / 0.22)))
        cw, ch = W / z, H / z
        return self.last.resize((W, H), Image.BILINEAR, box=((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2))

def render_scene(idx, durs, starts, sdur, total, only=None):
    stat = static_layer(idx); ch = chunks(word_timings(SC[idx]["voce"], durs[idx]))
    shots = SC[idx]["inquadrature"]; fixed = sum(s.get("dur", 0) for s in shots)
    rest = max(1.0, sdur[idx] - fixed); plan, t0 = [], 0.0
    for s in shots:
        d = s.get("dur") or rest; plan.append((t0, d, s)); t0 += d
    objs, cache = {}, {}
    def get_shot(tt):
        for k, (a, d, s) in enumerate(plan):
            if tt < a + d or k == len(plan) - 1:
                if k not in objs: objs[k] = VidShot(shot_file(s), d)
                return objs[k], tt - a
    def frame(fi):
        tt = fi / FPS; sh, lt = get_shot(tt)
        im = Image.alpha_composite(sh.frame(lt).convert("RGBA"), stat); cur = None
        for ci, c in enumerate(ch):
            end = ch[ci + 1][0][1] - 0.05 if ci + 1 < len(ch) else durs[idx] + GAP + 0.3
            if c[0][1] - 0.05 <= tt <= end:
                act = 0
                for wi, wv in enumerate(c):
                    if tt >= wv[1] - 0.03: act = wi
                cur = (ci, act)
        if cur:
            if cur not in cache: cache[cur] = caption_img(ch[cur[0]], cur[1])
            im.alpha_composite(cache[cur], (0, 1060))
        d = ImageDraw.Draw(im); gp = (starts[idx] + tt) / total
        d.rectangle([0, 0, W, 14], fill=(0, 0, 0, 255)); d.rectangle([0, 0, int(W * gp), 14], fill=YELLOW + (255,))
        return im.convert("RGB")
    n = int(round(sdur[idx] * FPS))
    if only is not None:
        want = sorted(min(n - 1, int(t * FPS)) for t in only); res = []
        for fi in range(max(want) + 1):
            f = frame(fi)
            if fi in want: res.append(f)
        return res
    out = f"{CLIP}/lavoro/scene/s{idx+1:02d}.mp4"
    pr = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                           "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    for fi in range(n): pr.stdin.write(frame(fi).tobytes())
    pr.stdin.close(); pr.wait(); return out

# ---------- 4. AUDIO ----------
def make_audio(starts, total):
    voice = np.zeros(int(total * SR) + SR, np.float32)
    for i in range(len(SC)):
        a, sr = sf.read(f"{CLIP}/lavoro/audio/l{i+1:02d}.wav", dtype="float32"); p = int(starts[i] * SR)
        voice[p:p + len(a)] += a
    mus_wav = f"{CLIP}/lavoro/audio/musica.wav"
    ff(["-stream_loop", "-1", "-i", f"{MAT}/{cfg['musica']}", "-t", str(total + 1), "-ac", "1", "-ar", str(SR), mus_wav])
    m, _ = sf.read(mus_wav, dtype="float32"); m = m[:len(voice)]
    if len(m) < len(voice): m = np.pad(m, (0, len(voice) - len(m)))
    m = m / (np.abs(m).max() + 1e-9)
    # ducking: musica piu' bassa mentre parla la voce
    env = np.convolve((np.abs(voice) > 0.02).astype(np.float32), np.ones(int(0.25 * SR)) / int(0.25 * SR), "same")
    gain = cfg.get("volume_musica", 0.10) * (1 - 0.55 * np.clip(env * 3, 0, 1))
    fade = np.ones_like(m); fl = int(1.2 * SR); fade[-fl:] = np.linspace(1, 0, fl)
    mix = voice + m * gain * fade
    sf.write(f"{CLIP}/lavoro/audio/mix.wav", mix[:int(total * SR)], SR)

if __name__ == "__main__":
    print("1/5 voce..."); durs = make_voice()
    starts, sdur, t = [], [], 0.0
    for i, d in enumerate(durs):
        starts.append(t); sd = d + GAP + (TAIL if i == len(durs) - 1 else 0); sdur.append(sd); t += sd
    total = t; print("   durata totale", round(total, 1), "s", [round(d, 1) for d in durs])
    print("2/5 inquadrature...")
    for s in SC:
        for sp in s["inquadrature"]: shot_file(sp)
    os.makedirs(f"{CLIP}/anteprima", exist_ok=True)
    print("3/5 anteprime...")
    thumbs = []
    for i in range(len(SC)):
        for fr in render_scene(i, durs, starts, sdur, total, only=[sdur[i] * 0.3]): thumbs.append(fr)
    sheet = Image.new("RGB", (360 * len(thumbs), 640))
    for k, fr in enumerate(thumbs): sheet.paste(fr.resize((360, 640)), (360 * k, 0))
    sheet.save(f"{CLIP}/anteprima/foglio-anteprime.jpg", quality=85)
    if PREVIEW: sys.exit(0)
    print("3/5 montaggio scene...")
    parts = [render_scene(i, durs, starts, sdur, total) for i in range(len(SC))]
    print("4/5 audio..."); make_audio(starts, total)
    print("5/5 file finale...")
    with open(f"{CLIP}/lavoro/scene/lista.txt", "w") as fh:
        for p in parts: fh.write(f"file '{p}'\n")
    name = re.sub(r"[^A-Za-z0-9]+", "-", cfg["titolo"]).strip("-").lower()
    final = f"{CLIP}/{name}.mp4"
    ff(["-f", "concat", "-safe", "0", "-i", f"{CLIP}/lavoro/scene/lista.txt", "-i", f"{CLIP}/lavoro/audio/mix.wav",
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-shortest", "-movflags", "+faststart", final])
    p = cfg.get("pubblicazione", {})
    with open(f"{CLIP}/pubblicazione.txt", "w") as fh:
        fh.write(f"TITOLO:\n{p.get('titolo_youtube','')}\n\nDESCRIZIONE:\n{p.get('descrizione','')}\n\nHASHTAG:\n{p.get('hashtag','')}\n\n")
        fh.write("FONTI DEI FATTI (da controllare prima di pubblicare):\n" + "\n".join("- " + f for f in cfg.get("fonti_fatti", [])) + "\n")
    print("FATTO:", final)
