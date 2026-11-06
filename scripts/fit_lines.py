#!/usr/bin/env python3
"""Проверить укладку русских строк в ритм-сетку бита.

Считает слоги, раскладывает их по слотам такта, показывает, какой слог падает
на удар, ловит провисы и перегруз, проверяет рифму в двустишиях.

Использование:
  python3 fit_lines.py lines.txt --slots 16 --accents 1,5,9,13
  cat lines.txt | python3 fit_lines.py -
"""
import sys, argparse, re

VOW = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
# служебные слоги: на ударе звучат как провал
# предлоги и частицы: на сильной доле внутри строки звучат как провал.
# местоимений здесь нет намеренно — «я не сплю» на первой доле это норма рэпа.
WEAK = {"в", "с", "и", "а", "но", "на", "по", "то", "же", "ли", "бы",
        "у", "о", "к", "за", "из", "до", "об", "от", "над", "под"}


def syllabify(word):
    """Открытый слог: согласная между гласными уходит в следующий слог."""
    if not any(c in VOW for c in word):
        return [word]
    out, cur, seen_v = [], "", False
    i = 0
    while i < len(word):
        c = word[i]
        cur += c
        if c in VOW:
            seen_v = True
            # смотрим, сколько согласных до следующей гласной
            j = i + 1
            cons = ""
            while j < len(word) and word[j] not in VOW:
                cons += word[j]
                j += 1
            if j < len(word):           # дальше ещё есть гласная
                # делим кластер: по умолчанию одна согласная уходит вправо,
                # но ь/ъ/й не могут начинать слог — тогда сдвигаем границу
                k = max(len(cons) - 1, 0)
                while k < len(cons) and cons[k] in "ьъй":
                    k += 1
                cur += cons[:k]
                i += k
                out.append(cur)
                cur = ""
                seen_v = False
            else:                       # хвост слова
                cur += cons
                out.append(cur)
                cur = ""
                i = j - 1
                seen_v = False
        i += 1
    if cur:
        if out and not seen_v:
            out[-1] += cur
        else:
            out.append(cur)
    return [s for s in out if s]


def line_syllables(line):
    """Слоги строки. Слово без гласной клеится к следующему."""
    words = re.findall(r"[а-яёА-ЯЁ]+", line)
    syl, carry = [], ""
    for w in words:
        parts = syllabify(w.lower())
        if len(parts) == 1 and not any(c in VOW for c in parts[0]):
            carry += parts[0]          # «в», «с», «к» — клеим к следующему слогу
            continue
        if carry:
            parts[0] = carry + parts[0]
            carry = ""
        whole = len(parts) == 1        # слог равен целому слову
        syl += [(x, whole) for x in parts]
    if carry and syl:
        syl[-1] = (syl[-1][0] + carry, syl[-1][1])
    return syl


def texts(syl):
    return [x for x, _ in syl]


def vowels(s):
    return "".join(c for c in s.lower() if c in VOW)


def rhyme_key(line):
    """Скелет окончания: две последние гласные + финальные согласные."""
    t = re.sub(r"[^а-яё]", "", line.lower())
    v = vowels(t)
    tail = re.search(r"[^аеёиоуыэюя]*$", t).group(0)
    return (v[-2:] if len(v) >= 2 else v, tail)


def rhyme_verdict(a, b):
    (va, ta), (vb, tb) = rhyme_key(a), rhyme_key(b)
    if not va or not vb:
        return "?"
    if va == vb and ta == tb:
        return "точная"
    if va[-1:] == vb[-1:] and ta == tb:
        return "хорошая"
    if va == vb:
        return "ассонанс"
    if va[-1:] == vb[-1:]:
        return "слабая"
    return "НЕТ РИФМЫ"


def render(syl, slots, accents):
    """Строка в виде групп по 4 слота, слог на ударе капсом."""
    cells = list(syl) + ["·"] * max(0, slots - len(syl))
    cells = cells[:slots]
    groups, g = [], []
    for i, c in enumerate(cells, 1):
        g.append(c.upper() if i in accents else c)
        if i % 4 == 0:
            groups.append("-".join(g))
            g = []
    if g:
        groups.append("-".join(g))
    return " | ".join(groups)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="файл со строками, или - для stdin")
    ap.add_argument("--slots", type=int, default=16, help="восьмых в строке")
    ap.add_argument("--accents", default="1,5,9,13", help="слоты удара через запятую")
    ap.add_argument("--no-grid", action="store_true")
    a = ap.parse_args()

    src = sys.stdin if a.file == "-" else open(a.file, encoding="utf-8")
    lines = [l.strip() for l in src if l.strip() and not l.strip().startswith("#")]
    accents = {int(x) for x in a.accents.split(",")}
    lo, hi = int(round(a.slots * .7)), int(round(a.slots * .88))

    print(f"сетка: {a.slots} слотов, удары {sorted(accents)}, коридор {lo}–{hi} слогов\n")
    problems = 0
    for i, l in enumerate(lines, 1):
        pairs = line_syllables(l)
        syl = texts(pairs)
        n = len(syl)
        tag = "ok     "
        if n < lo:
            tag = "ПРОВИС "
            problems += 1
        elif n > hi:
            tag = "ПЕРЕГР "
            problems += 1
        print(f"{i:2d}. [{tag}] {n:2d} сл  {l}")
        if not a.no_grid:
            print(f"            {render(syl, a.slots, accents)}")
        # служебный слог на ударе внутри строки (первый удар не трогаем)
        inner = [x for x in sorted(accents) if x > min(accents)]
        for acc in inner:
            if acc <= n and pairs[acc - 1][1] and syl[acc - 1] in WEAK:
                print(f"            ~ слот {acc} (удар) держит предлог «{syl[acc-1]}» — лучше переставить")
                problems += 1
        # где закрывается строка относительно удара
        near = min(accents, key=lambda x: abs(x - n))
        if abs(near - n) >= 3:
            print(f"            ~ рифма падает на слот {n}, ближайший удар {near} — закрытие висит в воздухе")
            problems += 1
    print()
    print("рифмовка двустиший:")
    for i in range(0, len(lines) - 1, 2):
        v = rhyme_verdict(lines[i], lines[i + 1])
        flag = "  <-- починить" if v in ("НЕТ РИФМЫ", "слабая") else ""
        print(f"  {i+1:2d}/{i+2:2d}  {v}{flag}")
        if v in ("НЕТ РИФМЫ",):
            problems += 1
    print()
    print(f"итого замечаний: {problems}")


if __name__ == "__main__":
    main()
