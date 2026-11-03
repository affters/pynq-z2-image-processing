"""Generate independent RGB fixtures and verify RTL grayscale output."""
import argparse
import itertools
import json
from pathlib import Path
import random
import shutil

from PIL import Image, ImageDraw, ImageFont


def gray(rgb):
    red, green, blue = rgb
    return (77 * red + 150 * green + 29 * blue + 128) // 256


def read_rgb(path):
    words = [int(line, 16) for line in path.read_text().split()]
    return [((word >> 16) & 255, (word >> 8) & 255, word & 255) for word in words]


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    palette = list(itertools.product((0, 255), repeat=3))
    pixels = palette + [(v, v, v) for v in range(256)]
    for channel in range(3):
        for value in range(256):
            sample = [0, 0, 0]
            sample[channel] = value
            pixels.append(tuple(sample))
    pixels += list(itertools.product((0, 1, 127, 128, 254, 255), repeat=3))
    rng = random.Random(20261029)
    pixels += [tuple(rng.randrange(256) for _ in range(3)) for _ in range(1024)]

    width, height = 128, 96
    image_pixels = []
    for y in range(height):
        for x in range(width):
            if y < 32:
                rgb = palette[x // 16]
            elif y < 64:
                red = x * 255 // (width - 1)
                rgb = (red, (y - 32) * 255 // 31, 255 - red)
            elif y < 80:
                rgb = (255, 180, 40) if (x // 8 + y // 8) % 2 else (20, 60, 200)
            else:
                value = x * 255 // (width - 1)
                rgb = (value, value, value)
            image_pixels.append(rgb)
    image_start = len(pixels)
    pixels += image_pixels
    expected = [gray(rgb) for rgb in pixels]
    assert gray((0, 0, 0)) == 0 and gray((255, 255, 255)) == 255
    assert [gray(rgb) for rgb in ((255, 0, 0), (0, 255, 0), (0, 0, 255))] == [77, 149, 29]
    assert all(gray((value,) * 3) == value for value in range(256))

    (directory / 'count.txt').write_text(str(len(pixels)) + '\n', encoding='ascii')
    (directory / 'input_rgb.hex').write_text(
        ''.join(f'{r:02x}{g:02x}{b:02x}\n' for r, g, b in pixels), encoding='ascii')
    (directory / 'expected_gray.hex').write_text(
        ''.join(f'{value:02x}\n' for value in expected), encoding='ascii')
    manifest = dict(width=width, height=height, image_start=image_start,
                    vector_count=len(pixels), seed=20261029,
                    input_order='RGB, R in bits 23:16, G in 15:8, B in 7:0',
                    formula='(77*R + 150*G + 29*B + 128) // 256')
    (directory / 'fixture.json').write_text(json.dumps(manifest, indent=2), encoding='ascii')
    original = Image.new('RGB', (width, height))
    original.putdata(image_pixels)
    original.save(directory / 'input_rgb.png')
    reference = Image.new('L', (width, height))
    reference.putdata(expected[image_start:])
    reference.save(directory / 'reference_gray.png')
    print(f'PREPARE_OK pixels={len(pixels)} image={width}x{height}')


def verify(directory, output_directory):
    manifest = json.loads((directory / 'fixture.json').read_text())
    pixels = read_rgb(directory / 'input_rgb.hex')
    expected = [gray(rgb) for rgb in pixels]
    actual = [int(word, 16) for word in (directory / 'rtl_gray.hex').read_text().split()]
    if len(actual) != len(expected):
        raise ValueError(f'Output length mismatch: {len(actual)} != {len(expected)}')
    for index, (got, want) in enumerate(zip(actual, expected)):
        if got != want:
            raise ValueError(f'Pixel {index}: RTL={got}, reference={want}, RGB={pixels[index]}')

    rounded_decimal = [(299*r + 587*g + 114*b + 500) // 1000 for r, g, b in pixels]
    approximation_error = max(abs(a - b) for a, b in zip(expected, rounded_decimal))
    if approximation_error > 1:
        raise ValueError(f'Unexpected coefficient approximation error: {approximation_error}')

    output_directory.mkdir(parents=True, exist_ok=True)
    actual_image = Image.new('L', (manifest['width'], manifest['height']))
    actual_image.putdata(actual[manifest['image_start']:])
    actual_image.save(output_directory / 'rtl_gray.png')
    for name in ('input_rgb.png', 'reference_gray.png', 'fixture.json'):
        shutil.copy2(directory / name, output_directory / name)

    scaled_size = (manifest['width'] * 4, manifest['height'] * 4)
    source = Image.open(directory / 'input_rgb.png').resize(scaled_size, Image.Resampling.NEAREST)
    result = actual_image.convert('RGB').resize(scaled_size, Image.Resampling.NEAREST)
    comparison = Image.new('RGB', (scaled_size[0] * 2 + 36, scaled_size[1] + 52), 'white')
    comparison.paste(source, (12, 40))
    comparison.paste(result, (scaled_size[0] + 24, 40))
    draw = ImageDraw.Draw(comparison)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 20)
    except OSError:
        font = ImageFont.load_default()
    draw.text((12, 10), 'RGB input', fill='black', font=font)
    draw.text((scaled_size[0] + 24, 10), 'RTL grayscale output', fill='black', font=font)
    comparison.save(output_directory / 'comparison.png')
    summary = dict(pixel_count=len(actual), exact_match=True,
                   max_error_vs_selected_integer_algorithm=0,
                   max_error_vs_rounded_decimal_coefficients=approximation_error,
                   image_width=manifest['width'], image_height=manifest['height'],
                   formula=manifest['formula'], source='Vivado XSim RTL output',
                   hardware_test=False)
    (output_directory / 'verification.json').write_text(json.dumps(summary, indent=2), encoding='ascii')
    print(f'VERIFY_OK pixels={len(actual)} exact_match=True approximation_error={approximation_error}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('prepare', 'verify'))
    parser.add_argument('vector_directory', type=Path)
    parser.add_argument('output_directory', type=Path, nargs='?')
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare(args.vector_directory)
    elif args.output_directory is None:
        parser.error('verify requires output_directory')
    else:
        verify(args.vector_directory, args.output_directory)
