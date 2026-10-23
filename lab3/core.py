from math import acos, cos, exp, hypot, pi, sin, sqrt

import numpy as np


WAVELENGTHS = tuple(range(380, 781, 10))
WEIGHTS = (5,) + (10,) * 39 + (5,)


CIE_XYZ = (
    (0.0014, 0.0, 0.0065),
    (0.0042, 0.0001, 0.0201),
    (0.0143, 0.0004, 0.0679),
    (0.0435, 0.0012, 0.2074),
    (0.1344, 0.004, 0.6456),
    (0.2839, 0.0116, 1.3856),
    (0.3483, 0.023, 1.7471),
    (0.3362, 0.038, 1.7721),
    (0.2908, 0.06, 1.6692),
    (0.1954, 0.091, 1.2876),
    (0.0956, 0.139, 0.813),
    (0.032, 0.208, 0.4652),
    (0.0049, 0.323, 0.272),
    (0.0093, 0.503, 0.1582),
    (0.0633, 0.71, 0.0782),
    (0.1655, 0.862, 0.0422),
    (0.2904, 0.954, 0.0203),
    (0.4334, 0.995, 0.0087),
    (0.5945, 0.995, 0.0039),
    (0.7621, 0.952, 0.0021),
    (0.9163, 0.87, 0.0017),
    (1.0263, 0.757, 0.0011),
    (1.0622, 0.631, 0.0008),
    (1.0026, 0.503, 0.0003),
    (0.8544, 0.381, 0.0002),
    (0.6424, 0.265, 0.0),
    (0.4479, 0.175, 0.0),
    (0.2835, 0.107, 0.0),
    (0.1649, 0.061, 0.0),
    (0.0874, 0.032, 0.0),
    (0.0468, 0.017, 0.0),
    (0.0227, 0.0082, 0.0),
    (0.0114, 0.0041, 0.0),
    (0.0058, 0.0021, 0.0),
    (0.0029, 0.001, 0.0),
    (0.0014, 0.0005, 0.0),
    (0.0007, 0.0002, 0.0),
    (0.0003, 0.0001, 0.0),
    (0.0002, 0.0001, 0.0),
    (0.0001, 0.0, 0.0),
    (0.0, 0.0, 0.0),
)


D65 = (
    49.9755, 54.6482, 82.7549, 91.486, 93.4318, 86.6823,
    104.865, 117.008, 117.812, 114.861, 115.923, 108.811,
    109.354, 107.802, 104.79, 107.689, 104.405, 104.046,
    100.0, 96.3342, 95.788, 88.6856, 90.0062, 89.5991,
    87.6987, 83.2886, 83.6992, 80.0268, 80.2146, 82.2778,
    78.2842, 69.7213, 71.6091, 74.349, 61.604, 69.8856,
    75.087, 63.5927, 46.4182, 66.8054, 63.3828,
)


BLACK_BODY_6500 = (
    0.936778172150841, 0.955662912271476, 0.970908129341595, 0.982707660622558,
    0.991272653465463, 0.996824807644081, 0.999590781366, 0.999797650517951,
    0.997669292126664, 0.993423577575078, 0.987270255089552, 0.979409410552046,
    0.970030417780058, 0.959311281384787, 0.947418307447197, 0.9345060231951,
    0.920717305017797, 0.906183655078115, 0.891025596902746, 0.875353150793493,
    0.859266366468582, 0.842855892853327, 0.826203560923265, 0.809382977089677,
    0.792460106042721, 0.775493842048154, 0.758536562673406, 0.741634652392577,
    0.724829010126833, 0.708155517125381, 0.691645486773777, 0.675326076248855,
    0.659220674578801, 0.643349262088184, 0.627728739721906, 0.612373236782354,
    0.597294390553546, 0.582501601326376, 0.568002272865336, 0.553802023256161,
    0.539904881696968,
)

RGB_TO_XYZ = tuple(tuple(value / 0.17697 for value in row) for row in (
    (0.49, 0.31, 0.20),
    (0.17697, 0.81240, 0.01063),
    (0.0, 0.01, 0.99),
))


XYZ_TO_RGB = (
    (0.41846571242189451, -0.158660784803799, -0.082834927618095466),
    (-0.091168963909022724, 0.25243144213946506, 0.015707521769557604),
    (0.00092089862534366364, -0.0025498125468632832, 0.17859891392151958),
)


XYZ_TO_SRGB = (
    (3.2406255, -1.5372080, -0.4986286),
    (-0.9689307, 1.8757561, 0.0415175),
    (0.0557101, -0.2040211, 1.0569959),
)

RGB_TO_XYZ = np.array(RGB_TO_XYZ)
XYZ_TO_RGB = np.array(XYZ_TO_RGB)
XYZ_TO_SRGB = np.array(XYZ_TO_SRGB)
XYZ_WEIGHTS = np.array(CIE_XYZ) * np.array(WEIGHTS)[:, None]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def unit(vector):
    length = hypot(*vector)
    return tuple(value / length for value in vector)


def multiply(matrix, vector):
    return np.asarray(vector) @ np.asarray(matrix).T


def integrate(spectrum):
    return np.asarray(spectrum) @ WEIGHTS


def normalize_spectrum(spectrum):
    total = integrate(spectrum)
    return tuple(value / total for value in spectrum)


def spectrum_to_xyz(spectrum):
    return np.asarray(spectrum) @ XYZ_WEIGHTS


def spectrum_to_rgb(spectrum):
    return multiply(XYZ_TO_RGB, spectrum_to_xyz(spectrum))


def reflection_to_rgb(reflection):
    white = spectrum_to_rgb(D65)
    reflected = spectrum_to_rgb(tuple(light * kd for light, kd in zip(D65, reflection)))
    return tuple(value / reference for value, reference in zip(reflected, white))


def make_spectrum(name, reflection=False):
    if name == "D65":
        return D65
    if name == "6500 K":
        return BLACK_BODY_6500
    if name == "Равномерный":
        return (1.0,) * len(WAVELENGTHS)
    if name == "Серый":
        return (0.5,) * len(WAVELENGTHS)
    if name == "Чёрный":
        return (0.0,) * len(WAVELENGTHS)
    center = {"Красный": 630, "Зелёный": 540, "Синий": 460}[name]
    width = 45 if reflection else 25
    base, height = (0.08, 0.82) if reflection else (0, 1)
    return tuple(base + height * exp(-0.5 * ((wave - center) / width) ** 2)
                 for wave in WAVELENGTHS)


def camera_frame(xc, yc, zc, zo):
    observer = np.array((0.0, 0.0, zo))
    center = np.array((xc, yc, zc), dtype=float)
    forward = np.array(unit(center - observer))
    axis_x = np.array((1.0, 0.0, 0.0))
    if abs(dot(axis_x, forward)) > 0.999999:
        axis_x = np.array((0.0, 1.0, 0.0))
    axis_x = np.array(unit(axis_x - dot(axis_x, forward) * forward))
    axis_y = np.cross(axis_x, forward)
    distance = hypot(xc, yc, zc - zo)
    return observer, forward, axis_x, axis_y, distance


def ray_sphere_point(x, y, zo, xc, yc, zc, r):
    observer, forward, axis_x, axis_y, distance = camera_frame(xc, yc, zc, zo)
    c = distance ** 2 - r ** 2
    discriminant = distance ** 2 * r ** 2 - (x ** 2 + y ** 2) * c
    if discriminant < 0:
        return None
    t = c / (distance ** 2 + sqrt(discriminant))
    if t <= 0:
        return None
    direction = distance * forward + x * axis_x + y * axis_y
    return tuple(observer + t * direction)


def is_sphere_in_view(xc, yc, zc, r, zo, w, h):
    distance = hypot(xc, yc, zc - zo)
    if distance <= r:
        return False
    projected_radius = r / sqrt(1 - (r / distance) ** 2)
    return projected_radius <= min(w, h) / 2 + 1e-9 * r


def calc_all_points_on_sphere(xc, yc, zc, r, zo, w, h, w_res, h_res):
    observer, forward, axis_x, axis_y, distance = camera_frame(xc, yc, zc, zo)
    x = -h / 2 + (np.arange(h_res)[:, None] + 0.5) * (h / h_res)
    y = -w / 2 + (np.arange(w_res)[None, :] + 0.5) * (w / w_res)
    c = distance ** 2 - r ** 2
    discriminant = distance ** 2 * r ** 2 - (x ** 2 + y ** 2) * c
    t = c / (distance ** 2 + np.sqrt(np.maximum(discriminant, 0)))
    visible = (discriminant >= 0) & (t > 0)
    rows, columns = np.nonzero(visible)
    directions = (distance * forward + x[rows, 0, None] * axis_x
                   + y[0, columns, None] * axis_y)
    coordinates = observer + t[visible, None] * directions
    return dict(zip(zip(rows.tolist(), columns.tolist()), coordinates.tolist()))


def calc_light_factor(point, light, xc, yc, zc, r):
    point = np.asarray(point)
    xl, yl, zl, i0, dx, dy, dz, _ = light
    n = (point - (xc, yc, zc)) / r
    to_light = (xl, yl, zl) - point
    distance_squared = np.sum(to_light ** 2, axis=-1)
    s = to_light / np.sqrt(distance_squared)[..., None]
    direction = unit((dx, dy, dz))
    cos_alpha = np.clip(-np.sum(s * direction, axis=-1), 0, 1)
    cos_theta = np.clip(np.sum(s * n, axis=-1), 0, 1)

    return 10 ** 6 * i0 * cos_alpha * cos_theta / (pi * distance_squared)


def prepare_lights(lights):
    return [(xl, yl, zl, i0, dx, dy, dz, normalize_spectrum(spectrum))
            for xl, yl, zl, i0, dx, dy, dz, spectrum in lights]


def calc_images(lights, xc, yc, zc, r, reflection, points):
    lights = prepare_lights(lights)
    coordinates = np.asarray(list(points.values()), dtype=np.float64).reshape(-1, 3)
    spectra = np.array([light[-1] for light in lights])
    light_colors = spectrum_to_rgb(spectra)
    reflection_rgb = reflection_to_rgb(reflection)

    factors = np.column_stack([calc_light_factor(coordinates, light, xc, yc, zc, r)
                               for light in lights])
    spectral = factors @ spectra
    spectral *= reflection
    xyz = spectrum_to_xyz(spectral)
    rgb_1 = multiply(XYZ_TO_RGB, xyz)
    rgb_2 = (factors @ light_colors) * reflection_rgb
    energy = integrate(spectral)
    luminance_1 = 683 * xyz[:, 1]
    luminance_2 = 683 * (rgb_2 @ RGB_TO_XYZ[1])

    return {"spectral": spectral.ravel(), "rgb_1": rgb_1.ravel(), "rgb_2": rgb_2.ravel(),
            "energy": energy, "luminance_1": luminance_1, "luminance_2": luminance_2}


def encode_srgb(value):
    value = np.clip(value, 0, 1)
    encoded = np.where(value <= 0.0031308, 12.92 * value, 1.055 * value ** (1 / 2.4) - 0.055)
    return np.rint(255 * encoded).astype(np.uint8)


def convert_rgb_to_pixels(rgb_1, rgb_2, points, w_res, h_res):
    monitor_images = []
    for image in (rgb_1, rgb_2):
        image = np.asarray(image).reshape(-1, 3)
        xyz = multiply(RGB_TO_XYZ, image)
        monitor_images.append(multiply(XYZ_TO_SRGB, xyz))

    maximum = max(float(image.max(initial=0)) for image in monitor_images)
    indices = np.array(list(points), dtype=int).reshape(-1, 2)
    result = []
    for image in monitor_images:
        pixels = np.zeros((h_res, w_res, 3), dtype=np.uint8)
        if maximum:
            pixels[indices[:, 0], indices[:, 1]] = encode_srgb(image / maximum)
        result.append(bytearray(pixels.tobytes()))
    return result, maximum


def convert_to_gray(pixels):
    image = np.frombuffer(pixels, dtype=np.uint8).reshape(-1, 3) / 255
    linear = np.where(image <= 0.04045, image / 12.92, ((image + 0.055) / 1.055) ** 2.4)
    gray = encode_srgb(linear @ np.array((0.2126, 0.7152, 0.0722)))
    return bytearray(gray.tobytes())


def calc_report_points(xc, yc, zc, r, zo):
    to_observer = (-xc, -yc, zo - zc)
    _, _, axis_x, _, distance = camera_frame(xc, yc, zc, zo)
    v = unit(to_observer)
    angle = min(pi / 6, acos(r / distance) / 2)
    result = []
    for name, theta in (("Ближняя", 0), ("-X", -angle), ("+X", angle)):
        normal = tuple(cos(theta) * vi + sin(theta) * ai for vi, ai in zip(v, axis_x))
        point = tuple(center + r * ni for center, ni in zip((xc, yc, zc), normal))
        result.append((name, point))
    return result