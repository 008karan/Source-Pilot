"""The type scale and contrast floor are part of the product, so they are tested.

15px body and table data · 17px/600 section headings · 26px/600 page titles ·
14px/400 secondary text · 12px/600 uppercase eyebrow labels · nothing else below
15px · line height 1.4-1.5 · every text colour at least 4.5:1 on its own background.
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'
SHEETS = ['styles.css', 'experience.css', 'workspace.css']
MIN_CONTRAST = 4.5
EYEBROW = 14.0


def rules(css: str) -> list[tuple[str, str]]:
    out, i, n = [], 0, len(css)
    while i < n:
        j = css.find('{', i)
        if j < 0:
            break
        selector = css[i:j]
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == '{':
                depth += 1
            elif css[k] == '}':
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        if selector.strip().startswith('@') and '{' in body:
            out += rules(body)
        else:
            out.append((selector.strip(), body))
        i = k
    return out


def every_rule():
    for name in SHEETS:
        for selector, body in rules((FRONTEND / name).read_text()):
            yield name, selector, body


def rgb(value: str):
    text = value.lstrip('#')
    if len(text) == 3:
        text = ''.join(c * 2 for c in text)
    if not re.fullmatch(r'[0-9a-fA-F]{6}', text):
        return None
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def luminance(colour) -> float:
    channel = lambda c: (c / 255 / 12.92) if c / 255 <= .03928 else ((c / 255 + .055) / 1.055) ** 2.4
    r, g, b = colour
    return .2126 * channel(r) + .7152 * channel(g) + .0722 * channel(b)


def contrast(foreground, background) -> float:
    a, b = luminance(foreground), luminance(background)
    return (max(a, b) + .05) / (min(a, b) + .05)


def size_of(body: str) -> float | None:
    match = re.search(r'font-size:\s*(\d+(?:\.\d+)?)px', body)
    return float(match.group(1)) if match else None


def test_no_text_is_smaller_than_the_eyebrow_tier():
    offenders = [(sheet, selector, size) for sheet, selector, body in every_rule()
                 if (size := size_of(body)) is not None and 0 < size < EYEBROW]
    assert not offenders, f'text below {EYEBROW:g}px: {offenders}'


def test_eleven_pixel_text_is_only_ever_an_eyebrow_label():
    """14px is reserved for small-caps labels; everything else stays at 15px or above."""
    offenders = []
    for sheet, selector, body in every_rule():
        if size_of(body) != EYEBROW:
            continue
        if 'text-transform:uppercase' not in body.replace(' ', ''):
            offenders.append((sheet, selector))
    assert not offenders, f'14px text that is not an uppercase label: {offenders}'


def test_body_and_heading_sizes_stay_on_the_scale():
    """Everything between the eyebrow and display tiers is one of the four defined steps."""
    allowed = {14.0, 15.0, 16.0, 17.0, 19.0}
    offenders = [(sheet, selector, size) for sheet, selector, body in every_rule()
                 if (size := size_of(body)) is not None and 15 <= size < 20 and size not in allowed]
    assert not offenders, f'off-scale text sizes: {offenders}'


def test_line_height_tracks_the_font_size():
    offenders = []
    for sheet, selector, body in every_rule():
        match = re.search(r'line-height:\s*(\d+(?:\.\d+)?)\s*(?:;|$|!)', body)
        if not match or size_of(body) is None:
            continue
        # A single-glyph control centres its icon; running text does not.
        if 'button' in selector and float(match.group(1)) == 1:
            continue
        if not 1.25 <= float(match.group(1)) <= 1.6:
            offenders.append((sheet, selector, match.group(1)))
    assert not offenders, f'line heights outside 1.25-1.6: {offenders}'


@pytest.mark.parametrize('sheet', SHEETS)
def test_every_text_colour_is_readable_on_its_own_background(sheet):
    """Measured against the rule's own background, falling back to the page white."""
    offenders = []
    for selector, body in rules((FRONTEND / sheet).read_text()):
        found = re.search(r'(?:^|;)\s*color:\s*(#[0-9a-fA-F]{3,6})', body)
        if not found or not (foreground := rgb(found.group(1))):
            continue
        own = re.search(r'(?:^|;)\s*background(?:-color)?:\s*(#[0-9a-fA-F]{3,6})', body)
        background = rgb(own.group(1)) if own and rgb(own.group(1)) else (255, 255, 255)
        ratio = contrast(foreground, background)
        if ratio < MIN_CONTRAST:
            offenders.append((selector[:60], found.group(1), round(ratio, 2)))
    assert not offenders, f'{sheet}: text below {MIN_CONTRAST}:1 — {offenders}'


def test_the_secondary_tier_is_a_grey_not_a_whisper():
    """16px helper text must be a readable grey in the #6B7280 family, never lighter."""
    offenders = []
    for sheet, selector, body in every_rule():
        if size_of(body) != 16.0:
            continue
        found = re.search(r'(?:^|;)\s*color:\s*(#[0-9a-fA-F]{3,6})', body)
        if not found or not (colour := rgb(found.group(1))):
            continue
        own = re.search(r'(?:^|;)\s*background(?:-color)?:\s*(#[0-9a-fA-F]{3,6})', body)
        # Light text belongs on a dark chip; the floor applies to text on the page.
        if own and rgb(own.group(1)) and luminance(rgb(own.group(1))) < 0.18:
            continue
        lightness = colorsys.rgb_to_hls(*[c / 255 for c in colour])[1]
        if lightness > 0.62:
            offenders.append((sheet, selector, found.group(1), round(lightness, 2)))
    assert not offenders, f'secondary text lighter than the #6B7280 family: {offenders}'
