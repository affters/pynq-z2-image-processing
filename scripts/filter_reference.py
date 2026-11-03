"""Independent integer references and reproducible multi-frame RTL fixtures."""
import argparse
import json
from pathlib import Path
import random
import statistics

from PIL import Image, ImageDraw, ImageFont


def clip(value):
    return max(0, min(255, value))


def window_filter(frame, width, height, mode):
    output = []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            a, b, c = frame[(y-1)*width+x-1:(y-1)*width+x+2]
            d, e, f = frame[y*width+x-1:y*width+x+2]
            g, h, i = frame[(y+1)*width+x-1:(y+1)*width+x+2]
            if mode == 0:
                value = e
            elif mode == 1:
                value = (a + 2*b + c + 2*d + 4*e + 2*f + g + 2*h + i + 8) // 16
            elif mode == 2:
                horizontal = c + 2*f + i - a - 2*d - g
                vertical = g + 2*h + i - a - 2*b - c
                value = min(255, (abs(horizontal) + abs(vertical)) // 4)
            else:
                value = clip(5*e - b - d - f - h)
            output.append(value)
    return output


def equalize(frame):
    histogram = [0] * 256
    for value in frame:
        histogram[value] += 1
    minimum = next(count for count in histogram if count)
    denominator = len(frame) - minimum
    if denominator == 0:
        return list(frame)
    cumulative = 0
    lookup = []
    for count in histogram:
        cumulative += count
        numerator = max(0, cumulative - minimum) * 255 + denominator // 2
        lookup.append(clip(numerator // denominator))
    return [lookup[value] for value in frame]


def make_frames(width, height, kind):
    clean = []
    for y in range(height):
        for x in range(width):
            if y * 4 < height:
                value = x * 255 // (width - 1)
            elif y * 2 < height:
                value = 40 if x * 3 < width else 200
            elif y * 4 < 3 * height:
                value = 70 if (x // max(1, width // 8) + y // max(1, height // 8)) % 2 else 180
            else:
                value = 20 + ((x + y) * 210 // (width + height - 2))
            clean.append(value)
    rng = random.Random(20261029 + width * 1000 + height)
    noisy = [clip(round(value + rng.gauss(0, 20))) for value in clean]
    first = [80 + value * 80 // 255 for value in clean] if kind == 'equalize' else clean
    return [first, noisy, [128] * (width * height)], clean


def prepare(args):
    if args.width < 3 or args.height < 3 or args.width * args.height * 3 > 65536:
        raise ValueError('Dimensions must be >=3 and the three-frame corpus <=65536 pixels')
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=True)
    frames, _ = make_frames(args.width, args.height, args.kind)
    expected_frames = [equalize(frame) if args.kind == 'equalize' else
                       window_filter(frame, args.width, args.height, args.mode) for frame in frames]
    pixels = [value for frame in frames for value in frame]
    expected = [value for frame in expected_frames for value in frame]
    for name, value in (('count.txt', len(pixels)), ('width.txt', args.width),
                        ('height.txt', args.height), ('mode.txt', args.mode)):
        (directory / name).write_text(str(value) + '\n', encoding='ascii')
    for name, values in (('input_gray.hex', pixels), ('expected_gray.hex', expected)):
        (directory / name).write_text(''.join(f'{value:02x}\n' for value in values), encoding='ascii')
    metadata = dict(kind=args.kind, mode=args.mode, width=args.width, height=args.height,
                    frames=3, input_count=len(pixels), output_count=len(expected),
                    seed=20261029 + args.width * 1000 + args.height)
    (directory / 'fixture.json').write_text(json.dumps(metadata, indent=2), encoding='ascii')
    print(f'PREPARE_OK kind={args.kind} mode={args.mode} inputs={len(pixels)} outputs={len(expected)}')


def save_image(path, values, width, height):
    image = Image.new('L', (width, height))
    image.putdata(values)
    image.save(path)
    return image


def verify(args):
    directory, destination = args.directory, args.output
    metadata = json.loads((directory / 'fixture.json').read_text())
    width, height, kind, mode = (metadata[k] for k in ('width', 'height', 'kind', 'mode'))
    pixels = [int(word, 16) for word in (directory / 'input_gray.hex').read_text().split()]
    size = width * height
    frames = [pixels[index:index+size] for index in range(0, len(pixels), size)]
    expected_frames = [equalize(frame) if kind == 'equalize' else window_filter(frame, width, height, mode)
                       for frame in frames]
    expected = [value for frame in expected_frames for value in frame]
    name = 'rtl_equalize.hex' if kind == 'equalize' else 'rtl_filter.hex'
    actual = [int(word, 16) for word in (directory / name).read_text().split()]
    if len(actual) != len(expected):
        raise ValueError(f'Output count mismatch: {len(actual)} != {len(expected)}')
    for index, (got, want) in enumerate(zip(actual, expected)):
        if got != want:
            raise ValueError(f'Output {index}: RTL={got}, expected={want}')
    destination.mkdir(parents=True, exist_ok=True)
    output_width = width if kind == 'equalize' else width - 2
    output_height = height if kind == 'equalize' else height - 2
    output_size = output_width * output_height
    input_image = save_image(destination / 'input.png', frames[0], width, height)
    raw_output = save_image(destination / 'rtl_output_inner.png', actual[:output_size], output_width, output_height)
    display_output = raw_output
    if kind == 'window':
        display_output = Image.new('L', (width, height))
        display_output.paste(raw_output, (1, 1))
    display_output.save(destination / 'rtl_output.png')
    factor = max(1, min(8, 512 // width))
    scaled = (width * factor, height * factor)
    canvas = Image.new('RGB', (2 * scaled[0] + 36, scaled[1] + 52), 'white')
    canvas.paste(input_image.resize(scaled, Image.Resampling.NEAREST), (12, 40))
    canvas.paste(display_output.resize(scaled, Image.Resampling.NEAREST), (scaled[0] + 24, 40))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 18)
    except OSError:
        font = ImageFont.load_default()
    label = 'Histogram equalization' if kind == 'equalize' else ('Center crop', 'Gaussian denoise', 'Sobel edges', 'Sharpen')[mode]
    draw.text((12, 10), 'Input grayscale', fill='black', font=font)
    draw.text((scaled[0] + 24, 10), 'RTL simulation: ' + label, fill='black', font=font)
    canvas.save(destination / 'comparison.png')
    metadata.update(exact_match=True, actual_output_count=len(actual), hardware_test=False,
                    output_width=output_width, output_height=output_height,
                    display_border='one zero pixel' if kind == 'window' else 'none')
    if kind == 'equalize':
        metadata['input_stddev_frame0'] = statistics.pstdev(frames[0])
        metadata['output_stddev_frame0'] = statistics.pstdev(actual[:output_size])
        assert actual[2*output_size:] == frames[2], 'Uniform frame must remain unchanged'
    if kind == 'window' and mode == 1:
        _, clean = make_frames(width, height, kind)
        clean_inner = window_filter(clean, width, height, 0)
        noisy_inner = window_filter(frames[1], width, height, 0)
        denoised = actual[output_size:2*output_size]
        mse = lambda values: sum((a-b)**2 for a, b in zip(values, clean_inner)) / output_size
        metadata['noisy_mse_frame1_inner'] = mse(noisy_inner)
        metadata['filtered_mse_frame1_inner'] = mse(denoised)
        save_image(destination / 'noisy_input.png', frames[1], width, height)
        save_image(destination / 'denoised_inner.png', denoised, output_width, output_height)
    (destination / 'verification.json').write_text(json.dumps(metadata, indent=2), encoding='ascii')
    print(f'VERIFY_OK kind={kind} mode={mode} outputs={len(actual)} exact_match=True')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('prepare', 'verify'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--kind', choices=('window', 'equalize'), default='window')
    parser.add_argument('--mode', type=int, choices=range(4), default=1)
    parser.add_argument('--width', type=int, default=128)
    parser.add_argument('--height', type=int, default=96)
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    if arguments.operation == 'prepare':
        prepare(arguments)
    elif arguments.output is None:
        parser.error('verify requires --output')
    else:
        verify(arguments)
