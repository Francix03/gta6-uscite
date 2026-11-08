# Original synthwave background bed, generated from scratch (no samples, no third-party audio).
import numpy as np, soundfile as sf, sys
from scipy.signal import butter, sosfilt

SR = 44100
BPM = 104
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 64.0
OUT = sys.argv[2] if len(sys.argv) > 2 else "music.wav"
beat = 60 / BPM
bar = beat * 4
N = int(DUR * SR)
rng = np.random.default_rng(7)

def lp(x, fc, order=2):
    return sosfilt(butter(order, fc, "low", fs=SR, output="sos"), x)
def hp(x, fc, order=2):
    return sosfilt(butter(order, fc, "high", fs=SR, output="sos"), x)
def saw(f, t, det=0.0):
    out = 0
    for d in ([-det, 0, det] if det else [0]):
        ph = (f * (1 + d)) * t
        out = out + 2 * (ph - np.floor(ph + 0.5))
    return out / (3 if det else 1)
def note(n):  # midi -> Hz
    return 440 * 2 ** ((n - 69) / 12)
def env(L, a, d, s, r):
    e = np.ones(L) * s
    A, D, R = int(a * SR), int(d * SR), int(r * SR)
    A = min(A, L); e[:A] = np.linspace(0, 1, A)
    D = min(D, L - A); e[A:A + D] = np.linspace(1, s, D)
    if R and R < L: e[-R:] *= np.linspace(1, 0, R)
    return e

mix_drums = np.zeros(N); bass = np.zeros(N); pad = np.zeros(N); arp = np.zeros(N); side = np.ones(N)
# progression Am F C G (i VI III VII)
chords = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]
roots = [45, 41, 48, 43]

def add(buf, start, sig):
    s = int(start * SR)
    if s >= N: return
    e = min(N, s + len(sig)); buf[s:e] += sig[:e - s]

t_kick = np.arange(int(0.35 * SR)) / SR
kick = np.sin(2 * np.pi * (45 + 110 * np.exp(-t_kick * 28)) * t_kick) * np.exp(-t_kick * 9)
t_sn = np.arange(int(0.4 * SR)) / SR
snare = hp(rng.standard_normal(len(t_sn)), 1500) * np.exp(-t_sn * 14) * 0.32 + np.sin(2 * np.pi * 190 * t_sn) * np.exp(-t_sn * 25) * 0.4
t_hh = np.arange(int(0.06 * SR)) / SR
hat = hp(rng.standard_normal(len(t_hh)), 7000) * np.exp(-t_hh * 70) * 0.12

nbars = int(np.ceil(DUR / bar))
for b in range(nbars):
    t0 = b * bar
    ci = b % 4
    intro = b < 2
    for k in range(4):
        tb = t0 + k * beat
        if not intro:
            add(mix_drums, tb, kick)
            s = int(tb * SR); L = int(0.25 * SR)
            if s < N: side[s:min(N, s + L)] = np.minimum(side[s:min(N, s + L)], 0.45 + 0.55 * np.linspace(0, 1, min(L, N - s)))
        if k in (1, 3) and not intro:
            add(mix_drums, tb, snare)
        for h in range(2):
            add(mix_drums, tb + h * beat / 2, hat * (1.0 if h else 0.6))
    # bass: 8th notes on root, octave jump on offbeats
    for e8 in range(8):
        L = int(beat / 2 * SR * 0.9); tt = np.arange(L) / SR
        f = note(roots[ci] + (12 if e8 % 2 else 0))
        sig = lp(saw(f, tt, 0.004), 900) * env(L, 0.005, 0.12, 0.6, 0.03) * (0.0 if intro and e8 % 2 else 0.5)
        add(bass, t0 + e8 * beat / 2, sig)
    # pad: whole bar chord
    L = int(bar * SR); tt = np.arange(L) / SR
    sig = sum(saw(note(n), tt, 0.006) for n in chords[ci]) / 3
    sig = lp(sig, 1400 if not intro else 900) * env(L, 0.4, 0.5, 0.8, 0.4) * 0.35
    add(pad, t0, sig)
    # arp 16ths over chord tones (from bar 4)
    if b >= 4:
        tones = chords[ci] + [chords[ci][0] + 12]
        for s16 in range(16):
            L = int(beat / 4 * SR * 0.8); tt = np.arange(L) / SR
            f = note(tones[s16 % 4] + 12)
            sq = np.sign(np.sin(2 * np.pi * f * tt))
            add(arp, t0 + s16 * beat / 4, lp(sq, 2500) * env(L, 0.003, 0.08, 0.2, 0.02) * 0.12)

def delay(x, t, fb=0.35, mix=0.3):
    d = int(t * SR); y = x.copy()
    for k in range(1, 4):
        y[d * k:] += x[:-d * k] * (fb ** k) * mix / fb
    return y

music = mix_drums * 0.9 + (bass + pad * 0.9 + delay(arp, beat * 0.75)) * side
music = delay(music, 0.09, 0.2, 0.15)
fade = int(1.5 * SR); music[:fade] *= np.linspace(0, 1, fade); music[-fade:] *= np.linspace(1, 0, fade)
music = music / np.abs(music).max() * 0.9
st = np.stack([music, delay(music, 0.012, 0.0001, 1e-4) * 0.98], 1)
sf.write(OUT, st, SR)
print("ok", DUR)
