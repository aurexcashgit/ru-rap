#!/usr/bin/env python3
"""Снять ритм-сетку с аудиофайла бита.

Выдаёт: BPM, фазу сетки, паттерн кика/клапа/хэтов по 16-м, хав-тайм или нет,
ровные 16-е или триоли, место дропа, таймкоды тактов и строк,
и слоговый коридор для строки.

Зависимости: ffmpeg в PATH, numpy.
Использование: python3 beat_grid.py <audio> [--from 13.7] [--lines 16]
"""
import subprocess, sys, shutil, argparse, os
import numpy as np

SR = 22050


def decode(path):
    if shutil.which("ffmpeg") is None:
        sys.exit("нужен ffmpeg в PATH")
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True)
    if p.returncode != 0:
        sys.exit("ffmpeg не смог прочитать файл:\n" + p.stderr.decode()[:500])
    x = np.frombuffer(p.stdout, dtype=np.float32)
    if x.size < SR:
        sys.exit("файл слишком короткий")
    return x.astype(np.float64)


def stft(x, n=1024, hop=128):
    w = np.hanning(n)
    frames = (len(x) - n) // hop
    S = np.empty((frames, n // 2 + 1))
    for i in range(frames):
        S[i] = np.abs(np.fft.rfft(x[i * hop:i * hop + n] * w))
    return S, np.fft.rfftfreq(n, 1 / SR), SR / hop


def flux(S, freqs, lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    f = np.maximum(0, np.diff(S[:, m], axis=0)).sum(axis=1)
    return (f - f.mean()) / (f.std() + 1e-9)


def find_tempo(sig, fps, lo=70.0, hi=185.0):
    best = None
    for bpm in np.arange(lo, hi, 0.05):
        per = fps * 60 / bpm
        nb = int(len(sig) / per) - 1
        if nb < 8:
            continue
        idx = np.arange(nb) * per
        scores = []
        for ph in np.arange(0, per, 1.0):
            s = sig[np.clip((idx + ph).round().astype(int), 0, len(sig) - 1)].sum()
            scores.append((s, ph))
        s, ph = max(scores)
        s /= nb  # нормируем, иначе медленные темпы всегда выигрывают
        if best is None or s > best[0]:
            best = (s, bpm, ph)
    return best[1], best[2]


def profile(sig, fps, per, phase, t0, t1):
    """Средняя энергия по 16 позициям такта."""
    step = per / 4
    out, cnt = np.zeros(16), np.zeros(16)
    t, k = phase, 0
    while t / fps < t1:
        if t / fps >= t0:
            out[k % 16] += sig[min(int(round(t)), len(sig) - 1)]
            cnt[k % 16] += 1
        t += step
        k += 1
    v = out / np.maximum(cnt, 1)
    v -= v.min()
    return v / (v.max() + 1e-9)


def bars(v):
    return " ".join(f"{int(round(q * 9)):>3}" for q in v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--from", dest="start", type=float, default=None,
                    help="с какой секунды заходит парт (по умолчанию ближайшая доля к дропу)")
    ap.add_argument("--lines", type=int, default=None, help="сколько строк планируешь")
    a = ap.parse_args()

    x = decode(a.audio)
    dur = len(x) / SR
    S, freqs, fps = stft(x)
    kick = flux(S, freqs, 20, 120)
    snare = flux(S, freqs, 150, 900)
    hats = flux(S, freqs, 4000, 11000)
    full = kick + snare + hats

    bpm, phase = find_tempo(full, fps)
    # 70 bpm и 140 bpm дают одну сетку: приводим к рабочему диапазону рэп-битов
    while bpm < 85:
        bpm *= 2
    while bpm > 185:
        bpm /= 2
    per = fps * 60 / bpm          # доля в фреймах
    bar_s = 60 / bpm * 4

    # ВАЖНО: гребёнка цепляется за самую громкую долю, а это часто снейр.
    # Первая доля такта там, где максимум низа (кик) — проверяем 4 сдвига.
    def kick_at(ph0):
        t, s_, c = ph0, 0.0, 0
        while t / fps < len(x) / SR:
            s_ += kick[min(int(round(t)), len(kick) - 1)]
            c += 1
            t += per * 4
        return s_ / max(c, 1)
    phase += per * max(range(4), key=lambda i: kick_at(phase + per * i))
    phase %= per * 4

    # дроп: первый резкий скачок RMS
    env = np.sqrt(np.convolve(x ** 2, np.ones(SR // 2) / (SR // 2), "same"))
    sec = np.array([env[min(int((s + .5) * SR), len(env) - 1)] for s in range(int(dur))])
    drop = None
    for i in range(1, len(sec)):
        if sec[i] > 2.2 * np.median(sec[:max(i, 1)]) and sec[i] > 0.6 * sec.max():
            drop = i
            break
    t0 = (drop if drop is not None else 0)
    t1 = min(dur, t0 + 45)

    pk = profile(kick, fps, per, phase, t0, t1)
    ps = profile(snare, fps, per, phase, t0, t1)
    ph_ = profile(hats, fps, per, phase, t0, t1)

    # триоли против ровных 16-х по хэтам
    def gscore(step):
        t, s, c = phase, 0.0, 0
        while t / fps < t1:
            if t / fps >= t0:
                s += hats[min(int(round(t)), len(hats) - 1)]
                c += 1
            t += step
        return s / max(c, 1)
    straight, triplet = gscore(per / 4), gscore(per / 3)

    # хав-тайм: клап сидит на 3, а не на 2 и 4.
    # Плюс практика: на 118+ BPM рэп всегда пишется строкой в два такта.
    on3 = ps[8]
    on24 = (ps[4] + ps[12]) / 2
    half = (bpm >= 118) or (on3 > on24)
    why = "BPM выше 118" if bpm >= 118 else ("клап на 3" if on3 > on24 else "клап на 2 и 4")
    line_bars = 2 if half else 1
    line_s = bar_s * line_bars
    slots = 8 * line_bars                      # восьмых в строке
    corridor = (int(round(slots * .7)), int(round(slots * .88)))

    names = ["1", "e", "&", "a", "2", "e", "&", "a", "3", "e", "&", "a", "4", "e", "&", "a"]
    print(f"файл            {os.path.basename(a.audio)}  ({dur:.1f}с)")
    print(f"BPM             {bpm:.2f}")
    print(f"фаза сетки      {phase / fps:.3f}с")
    print(f"такт            {bar_s:.3f}с")
    print(f"дроп            {'~%.1fс' % drop if drop is not None else 'не найден (бит ровный)'}")
    print(f"хэты            {'ТРИОЛИ / шаффл' if triplet > straight else 'ровные 16-е'}"
          f"  (16-е {straight:.2f} / триоли {triplet:.2f})")
    print(f"доля            {'ХАВ-ТАЙМ, строка в два такта' if half else 'бэкбит, строка в один такт'}"
          f"  ({why})")
    print()
    print("паттерн по 16-м (0 нет / 9 макс)")
    print("            " + " ".join(f"{n:>3}" for n in names))
    print("  КИК       " + bars(pk))
    print("  КЛАП      " + bars(ps))
    print("  ХЭТ       " + bars(ph_))
    print()
    print(f"СТРОКА = {line_bars} такт(а) = {line_s:.2f}с = {slots} восьмых")
    print(f"удар голосом в слоты: " + ("1, 5, 9, 13" if half else "1, 5"))
    print(f"слоговый коридор: {corridor[0]}–{corridor[1]} слогов на строку")
    print("  меньше — провис, больше — захлёбываешься")
    print()

    start = a.start
    if start is None:
        # ближайшая доля такта к дропу
        if drop is not None:
            k = round((drop - phase / fps) / bar_s)
            start = phase / fps + k * bar_s
        else:
            start = phase / fps
    n = a.lines if a.lines else int((dur - start) // line_s)
    print(f"таймкоды строк (заход с {start:.2f}с, {n} строк по {line_s:.2f}с)")
    for i in range(n):
        t = start + i * line_s
        if t >= dur:
            print(f"  строка {i + 1:2d}: {t:6.2f}с  — ВЫХОДИТ ЗА КОНЕЦ ТРЕКА")
            break
        mark = "  <- дроп" if drop is not None and abs(t - drop) < line_s / 2 else ""
        print(f"  строка {i + 1:2d}: {int(t) // 60}:{t % 60:04.1f}{mark}")
    tail = dur - (start + n * line_s)
    if tail > 1:
        print(f"  хвост {tail:.1f}с — под ад-либы или хук")


if __name__ == "__main__":
    main()
