def calc_e(i0, xl, yl, zl, x, y):
    return 10 ** 6 * i0 * ((zl ** 2) / ((x - xl) ** 2 + (y - yl) ** 2 + zl ** 2))


def is_in_the_circle(x, y, xc, yc, r):
    return (x - xc) ** 2 + (y - yc) ** 2 <= r ** 2


def calc_all_points_in_the_circle(xc, yc, r, w, h, w_res, h_res):
    pixel_y, pixel_x = w / w_res, h / h_res

    points = []

    for i in range(h_res):
        x = (- h / 2) + (i + 0.5) * pixel_x

        for j in range(w_res):
            y = (- w / 2) + (j + 0.5) * pixel_y

            if is_in_the_circle(x, y, xc, yc, r):
                points.append((x, y))

    return points


def calc_e_for_all_points(i0, xl, yl, zl, points):
    result = {}

    for point in points:
        x, y = point[0], point[1]

        result[point] = calc_e(i0, xl, yl, zl, x, y)

    return result


def convert_e_to_g(points_with_e: dict):
    e_max = max(points_with_e.values())

    g_result = {}

    for point in points_with_e.keys():
        e = points_with_e[point]

        g_result[point] = round(255 * (e / e_max))

    return g_result