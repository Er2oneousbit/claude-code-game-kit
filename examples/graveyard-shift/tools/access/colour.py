#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# colour.py
# Purpose : The colour maths the kit's accessibility checks share, standard library only: what a colour looks like to
#           a player with protanopia, deuteranopia, tritanopia or achromatopsia (simulation), how far apart two
#           colours are (CIEDE2000), the WCAG contrast ratio, and the kit's colour-blind filter (the colorblind shader
#           recipe's daltonization) as a reference.
# Usage   : import colour; colour.simulate((255, 0, 77), "deuteranopia"); colour.delta_e00(lab1, lab2);
#           colour.contrast((255, 255, 255), (0, 0, 0)); colour.daltonize(rgb, "protanopia")
# Notes   : Colours are 8-bit sRGB tuples (r, g, b). Simulation: Machado, Oliveira and Fernandes 2009 at severity 1.0
#           (dichromacy), applied in linear RGB as the paper's model assumes (E157); achromatopsia keeps only the
#           relative luminance (WCAG's, E158). CIEDE2000 follows Sharma, Wu and Dalal 2005, checked against their 34
#           test pairs (E159). Contrast is WCAG 2.2's formula (E158). daltonize() is tools/shaders/ksl/colorblind.ksl
#           in Python (gamma-space LMS, as the shader runs), so a palette can be checked under the filter.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import math

# Machado et al. 2009, Table 1, severity 1.0 (rows multiply linear RGB column vectors); E157
MACHADO = {
    "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}
KINDS = ("protanopia", "deuteranopia", "tritanopia", "achromatopsia")
LUMA = (0.2126, 0.7152, 0.0722)            # WCAG relative luminance weights (E158)
LINEAR_KNEE = 0.04045                      # sRGB decoding threshold (WCAG 2.2 uses 0.04045; E158)
WHITE_D65 = (0.95047, 1.0, 1.08883)        # XYZ of the sRGB white, for CIELAB
SRGB_TO_XYZ = ((0.4124564, 0.3575761, 0.1804375), (0.2126729, 0.7151522, 0.0721750),
               (0.0193339, 0.1191920, 0.9503041))
# the colorblind recipe's LMS daltonization (ksl/colorblind.ksl): mode 1 protanopia, 2 deuteranopia, 3 tritanopia
RGB_TO_LMS = ((17.8824, 43.5161, 4.11935), (3.45565, 27.1554, 3.86714), (0.0299566, 0.184309, 1.46709))
LMS_TO_RGB = ((0.0809444479, -0.130504409, 0.116721066), (-0.0102485335, 0.0540193266, -0.113614708),
              (-0.000365296938, -0.00412161469, 0.693511405))


def _mul(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def _clamp01(x):
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def to_linear(c8):
    """8-bit sRGB -> linear 0..1."""
    out = []
    for v in c8:
        s = v / 255.0
        out.append(s / 12.92 if s <= LINEAR_KNEE else ((s + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def to_srgb8(lin):
    """linear 0..1 -> 8-bit sRGB (clamped, rounded)."""
    out = []
    for v in lin:
        v = _clamp01(v)
        s = v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        out.append(int(round(s * 255)))
    return tuple(out)


def luminance(c8):
    """WCAG relative luminance, 0 (black) to 1 (white)."""
    return sum(w * v for w, v in zip(LUMA, to_linear(c8)))


def contrast(c1, c2):
    """WCAG contrast ratio, 1 to 21 (unrounded: 4.499 does not meet 4.5)."""
    a, b = sorted((luminance(c1), luminance(c2)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def simulate(c8, kind):
    """What a player with this colour vision deficiency sees (dichromacy, or no colour at all)."""
    if kind in ("none", "", None):
        return tuple(c8)
    if kind == "achromatopsia":
        y = luminance(c8)
        return to_srgb8((y, y, y))
    if kind not in MACHADO:
        raise ValueError(f"unknown colour vision kind {kind!r} (one of {', '.join(KINDS)})")
    return to_srgb8(_mul(MACHADO[kind], to_linear(c8)))


def daltonize(c8, mode):
    """The kit's colour-blind filter (the colorblind shader recipe) applied to one colour; mode none is a no-op."""
    if mode in ("none", "", None):
        return tuple(c8)
    c = tuple(v / 255.0 for v in c8)
    lms = list(_mul(RGB_TO_LMS, c))
    l, m, s = lms
    if mode == "protanopia":
        lms[0] = 2.02344 * m - 2.52581 * s
    elif mode == "deuteranopia":
        lms[1] = 0.494207 * l + 1.24827 * s
    elif mode == "tritanopia":
        lms[2] = -0.395913 * l + 0.801109 * m
    else:
        raise ValueError(f"the filter has no mode {mode!r}")
    back = _mul(LMS_TO_RGB, lms)
    err = tuple(a - b for a, b in zip(c, back))
    shift = (0.0, 0.7 * err[0] + err[1], 0.7 * err[0] + err[2])
    return tuple(int(round(_clamp01(a + b) * 255)) for a, b in zip(c, shift))


def lab(c8):
    """8-bit sRGB -> CIELAB (D65)."""
    x, y, z = (v / w for v, w in zip(_mul(SRGB_TO_XYZ, to_linear(c8)), WHITE_D65))

    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e00(lab1, lab2):
    """CIEDE2000 colour difference (kL = kC = kH = 1), as Sharma, Wu and Dalal 2005 implement it."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    dLp, dCp = L2 - L1, c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    Lbar, cbarp = (L1 + L2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbar = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbar = (h1p + h2p + 360) / 2
    else:
        hbar = (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbar - 30)) + 0.24 * math.cos(math.radians(2 * hbar))
         + 0.32 * math.cos(math.radians(3 * hbar + 6)) - 0.20 * math.cos(math.radians(4 * hbar - 63)))
    dtheta = 30 * math.exp(-(((hbar - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cbarp ** 7 / (cbarp ** 7 + 25 ** 7))
    sl = 1 + 0.015 * (Lbar - 50) ** 2 / math.sqrt(20 + (Lbar - 50) ** 2)
    sc = 1 + 0.045 * cbarp
    sh = 1 + 0.015 * cbarp * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt((dLp / sl) ** 2 + (dCp / sc) ** 2 + (dHp / sh) ** 2 + rt * (dCp / sc) * (dHp / sh))


def difference(c1, c2):
    """CIEDE2000 between two 8-bit sRGB colours."""
    return delta_e00(lab(c1), lab(c2))


def parse(text):
    """'#rrggbb', '0xrrggbb', 'rrggbb' or [r, g, b] -> (r, g, b)."""
    if isinstance(text, (list, tuple)) and len(text) == 3:
        return tuple(int(v) for v in text)
    s = str(text).strip().lower()
    s = s[1:] if s.startswith("#") else s[2:] if s.startswith("0x") else s
    if len(s) != 6 or any(ch not in "0123456789abcdef" for ch in s):
        raise ValueError(f"not a colour: {text!r} (#rrggbb)")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
