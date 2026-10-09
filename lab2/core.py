from math import acos, cos, pi, sin, sqrt


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def unit(vector):
    length = sqrt(dot(vector, vector))
    return tuple(value / length for value in vector)


def ray_sphere_point(x, y, zo, xc, yc, zc, r):
    # Луч O + t * (P - O), где O = (0, 0, zo), P = (x, y, 0).
    direction = (x, y, -zo)
    offset = (-xc, -yc, zo - zc)
    a = dot(direction, direction)
    b = 2 * dot(direction, offset)
    c = dot(offset, offset) - r ** 2
    discriminant = b ** 2 - 4 * a * c
    if discriminant < 0:
        return None

    # Выбираем ближайшее положительное пересечение со сферой.
    t = (-b - sqrt(discriminant)) / (2 * a)
    if t <= 0:
        return None
    return (t * x, t * y, zo * (1 - t))


def is_sphere_in_view(xc, yc, zc, r, zo, w, h):
    # Расстояния до четырёх боковых плоскостей пирамиды видимости.
    # Как в lab1, X идёт по высоте экрана, Y — по ширине.
    for coordinate, size in ((xc, h), (yc, w)):
        slope = size / (2 * zo)
        distance = (slope * (zo - zc) - abs(coordinate)) / sqrt(1 + slope ** 2)
        if distance < r - 1e-9 * r:
            return False
    return True


def calc_all_points_on_sphere(xc, yc, zc, r, zo, w, h, w_res, h_res):
    points = {}
    pixel_x, pixel_y = h / h_res, w / w_res
    for i in range(h_res):
        x = -h / 2 + (i + 0.5) * pixel_x
        for j in range(w_res):
            y = -w / 2 + (j + 0.5) * pixel_y
            point = ray_sphere_point(x, y, zo, xc, yc, zc, r)
            if point is not None:
                points[(i, j)] = point
    return points


def calc_l(point, lights, zo, xc, yc, zc, r, kd, ks, ke, c):
    x, y, z = point
    n = ((x - xc) / r, (y - yc) / r, (z - zc) / r)
    v = unit((-x, -y, zo - z))
    result = 0

    for xl, yl, zl, i0 in lights:
        to_light = (xl - x, yl - y, zl - z)
        distance_squared = dot(to_light, to_light)
        distance = sqrt(distance_squared)
        s = tuple(value / distance for value in to_light)

        # I(alpha) = I0 * cos(alpha): источник излучает вдоль -Z.
        cos_alpha = max(0, s[2])
        cos_theta = max(0, min(1, dot(s, n)))
        if cos_alpha == 0 or cos_theta == 0:
            continue

        # Закон обратных квадратов; 10**6 переводит мм² в м².
        li = 10 ** 6 * i0 * cos_alpha / distance_squared

        # Именно h = (v + s) / 2 из методички, стр. 50.
        h = tuple((vi + si) / 2 for vi, si in zip(v, s))
        cos_h = max(0, min(1, dot(h, n)))

        # Формула (3.4.5.3): L = Li * (Kd*(s·n) + c*Ks*(h·n)**ke).
        result += li * (kd * cos_theta + c * ks * cos_h ** ke)

    return result


def calc_l_for_all_points(lights, zo, xc, yc, zc, r, kd, ks, ke, c, points):
    result = {}
    for pixel, point in points.items():
        result[pixel] = calc_l(point, lights, zo, xc, yc, zc, r, kd, ks, ke, c)
    return result


def convert_l_to_g(points_with_l):
    l_max = max(points_with_l.values())
    if l_max == 0:
        return {pixel: 0 for pixel in points_with_l}
    return {pixel: round(255 * l / l_max) for pixel, l in points_with_l.items()}


def calc_report_points(xc, yc, zc, r, zo):
    to_observer = (-xc, -yc, zo - zc)
    distance = sqrt(dot(to_observer, to_observer))
    v = unit(to_observer)
    axis_x = unit((v[2], 0, -v[0]))
    # Три разные точки внутри видимой части сферы, даже вблизи наблюдателя.
    angle = min(pi / 6, acos(r / distance) / 2)
    result = []
    for name, theta in (("Ближняя", 0), ("-X", -angle), ("+X", angle)):
        normal = tuple(cos(theta) * vi + sin(theta) * ai
                       for vi, ai in zip(v, axis_x))
        point = tuple(center + r * ni for center, ni in zip((xc, yc, zc), normal))
        result.append((name, point))
    return result


def calc_section(lights, zo, xc, yc, zc, r, kd, ks, ke, c, h):
    y = zo * yc / (zo - zc)
    section = []
    for i in range(201):
        x = -h / 2 + h * i / 200
        point = ray_sphere_point(x, y, zo, xc, yc, zc, r)
        l = 0 if point is None else calc_l(point, lights, zo, xc, yc, zc, r, kd, ks, ke, c)
        section.append((x, l))
    return section
