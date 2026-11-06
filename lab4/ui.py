import base64
import csv
import json
import math
from pathlib import Path
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import zlib

import numpy as np

import core


FIELDS = (
    ("w", "W, мм", "2000"),
    ("h", "H, мм", "2000"),
    ("w_res", "W_res, пикс.", "400"),
    ("h_res", "H_res, пикс.", "400"),
    ("zo", "Наблюдатель z_O, мм", "5000"),
    ("xc", "Центр сферы x_C, мм", "0"),
    ("yc", "Центр сферы y_C, мм", "0"),
    ("zc", "Центр сферы z_C, мм", "800"),
    ("r", "Радиус r, мм", "600"),
)


SIZE_FIELDS = ("w", "h", "w_res", "h_res")

LIGHT_FIELDS = (("xl", "x_L, мм", "-400"), ("yl", "y_L, мм", "350"),
                ("zl", "z_L, мм", "2300"), ("i0", "I_0, Вт/ср", "1"),
                ("dx", "d_x", "0"), ("dy", "d_y", "0"), ("dz", "d_z", "-1"))
IMAGE_NAMES = ("image_A", "image_1", "image_2")


# Числовой ввод; конечные значения параметров сцены.
def read_number(value, label, integer=False):
    try:
        value = value.strip().replace(",", ".")
        number = int(value) if integer else float(value)
    except ValueError as exc:
        raise ValueError(f"{label}: введите {'целое число' if integer else 'число'}.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label}: введите конечное число.")
    return number


# Размеры прямоугольного экрана и разрешение; квадратный пиксель.
def adjust_image_size(values, changed):
    labels = {key: label for key, label, _ in FIELDS}
    sizes = {key: read_number(values[key], labels[key], key.endswith("_res"))
             for key in SIZE_FIELDS}
    if any(value <= 0 for value in sizes.values()):
        raise ValueError("Размеры экрана и разрешение должны быть больше нуля.")
    if math.isclose(sizes["w"] / sizes["w_res"],
                    sizes["h"] / sizes["h_res"], rel_tol=1e-12):
        return values.copy(), ""

    side = "h" if changed in ("h", "h_res") else "w"
    other = "w" if side == "h" else "h"
    resolution = side + "_res"
    step = sizes[other] / sizes[other + "_res"]

    wanted = round(sizes[side] / step) if changed == resolution else sizes[resolution]
    sizes[resolution] = max(1, wanted)
    sizes[side] = step * sizes[resolution]

    corrected = values.copy()
    changes = []
    for key in (resolution, side):
        if read_number(values[key], labels[key], key.endswith("_res")) != sizes[key]:
            corrected[key] = f"{sizes[key]:.12g}"
            changes.append(f"{key} = {corrected[key]}")
    return corrected, "Квадратный пиксель: " + ", ".join(changes) + "."


# Табличная спектрограмма 380–780 нм с шагом 10 нм; физические границы отражения.
def read_spectrum(text, reflection=False):
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.replace(";", " ").split()
        if len(parts) != 2:
            raise ValueError(f"Строка {number}: нужны длина волны и значение через пробел или табуляцию.")
        wave = read_number(parts[0], f"Строка {number}, λ", integer=True)
        value = read_number(parts[1], f"Строка {number}, значение")
        if wave not in core.WAVELENGTHS or wave in values:
            raise ValueError(f"Строка {number}: λ от 380 до 780 нм с шагом 10, без повторений.")
        if value < 0 or (reflection and value > 1):
            raise ValueError("K_d(λ) должен быть от 0 до 1." if reflection
                             else "Спектр источника не может быть отрицательным.")
        values[wave] = value
    if len(values) != len(core.WAVELENGTHS):
        raise ValueError("Нужна 41 строка: от 380 до 780 нм с шагом 10 нм.")
    spectrum = tuple(values[wave] for wave in core.WAVELENGTHS)
    if not reflection and not math.isfinite(core.integrate(spectrum)):
        raise ValueError("Интеграл спектра источника должен быть конечным.")
    return spectrum


# Блок PNG и контрольная сумма CRC.
def png_chunk(kind, data):
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


# Растровое изображение RGB в формате PNG.
def make_png(width, height, pixels, color=True):
    stride = width * (3 if color else 1)
    rows = b"".join(b"\0" + pixels[i * stride:(i + 1) * stride] for i in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2 if color else 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"sRGB", b"\0")
            + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b""))


# Исходные данные сцены; проверки чисел, радиуса и квадратных пикселей.
def read_parameters(values, lights):
    p = {key: read_number(values[key], label, key.endswith("_res")) for key, label, _ in FIELDS}
    if any(p[key] <= 0 for key in SIZE_FIELDS):
        raise ValueError("Размеры экрана и разрешение должны быть больше нуля.")
    if p["r"] < 0:
        raise ValueError("Радиус не может быть отрицательным.")
    if not math.isclose(p["w"] / p["w_res"], p["h"] / p["h_res"], rel_tol=1e-9):
        raise ValueError("Пиксели должны быть квадратными: W / Wres = H / Hres.")
    p["lights"] = lights
    return p


# Источник света: положение, сила излучения, направление и линейный CIE RGB.
def read_light(values, rgb_values):
    light = tuple(read_number(values[key], label) for key, label, _ in LIGHT_FIELDS)
    if light[3] < 0:
        raise ValueError("Сила излучения не может быть отрицательной.")
    rgb = tuple(read_number(value, label) for value, label in zip(rgb_values, ("R", "G", "B")))
    return (*light, rgb)


# Полный алгоритм lab4: RGB → спектры → image_A; сравнение с двумя методами lab3.
def calculate(p):
    sources, reflection = core.restore_scene(p["lights"], p["reflection_rgb"])
    points = core.calc_all_points_on_sphere(p["xc"], p["yc"], p["zc"], p["r"], p["zo"],
                                           p["w"], p["h"], p["w_res"], p["h_res"])
    inside = math.hypot(p["xc"], p["yc"], p["zo"] - p["zc"]) <= p["r"]
    args = (p["lights"], p["xc"], p["yc"], p["zc"], p["r"], p["original_spectra"],
            p["original_reflection"], sources, reflection)
    result = core.calc_images(*args, points, inside=inside)
    if any(not np.all(np.isfinite(value)) for value in result.values()):
        raise ArithmeticError("Результат вышел за пределы числового диапазона.")
    pixels, maximum = core.convert_rgb_to_pixels([result["rgb_" + name] for name in ("A", "1", "2")],
                                                points, p["w_res"], p["h_res"])
    result["png"] = [make_png(p["w_res"], p["h_res"], image) for image in pixels]
    result["differences"] = [core.compare_images(pixels[0], image, points, p["w_res"], p["h_res"])
                             for image in pixels[1:]]
    report_points = core.calc_report_points(p["xc"], p["yc"], p["zc"], p["r"], p["zo"])
    samples = core.calc_images(*args, dict(enumerate(point for _, point in report_points)), inside=inside)
    result["report_points"] = [(name, *point, samples["energy_A"][i], samples["luminance_A"][i],
                               samples["luminance_1"][i], samples["luminance_2"][i])
                              for i, (name, point) in enumerate(report_points)]
    comparisons = []
    for i, (original, restored, light) in enumerate(zip(p["original_spectra"], sources, p["lights"]), 1):
        original = np.asarray(core.normalize_spectrum(original))
        comparisons.append((f"Источник {i}", original, restored,
                            core.compare_spectra(original, restored, light[-1])))
    comparisons.append(("Поверхность", np.asarray(p["original_reflection"]), reflection,
                        core.compare_spectra(p["original_reflection"], reflection, p["reflection_rgb"], True)))
    result.update(params=p, points=points, comparisons=comparisons, maximum=maximum)
    return result


# Абсолютная энергетическая и световая яркость; min/max, три точки и ошибка восстановления цвета.
def result_text(result):
    lines = []
    for key, label, units in (("energy_A", "L_e (image_A)", "Вт/(м²·ср)"),
                               ("luminance_A", "L_v (image_A)", "кд/м²"),
                               ("luminance_1", "L_v (image_1)", "кд/м²"),
                               ("luminance_2", "L_v (image_2)", "кд/м²")):
        values = result[key]
        limits = f"min = {values.min():.6g}, max = {values.max():.6g}" if values.size else "min = —, max = —"
        lines.append(f"{label}: {limits} {units}")
    for name, (mean, maximum) in zip(("image_1", "image_2"), result["differences"]):
        lines.append(f"image_A / {name}, RGB 0–255: средняя разница = {mean:.6g}, максимальная = {maximum}")
    lines.extend(("Точка        x, мм      y, мм      z, мм      L_eA, Вт/(м²·ср)     L_vA        L_v1        L_v2, кд/м²",))
    for name, x, y, z, le, lva, lv1, lv2 in result["report_points"]:
        lines.append(f"{name:<9} {x:>9.5g} {y:>10.5g} {z:>10.6g} {le:>19.6g} {lva:>11.6g} {lv1:>11.6g} {lv2:>11.6g}")
    lines.append("Восстановление спектров: RMS, максимальная разница спектра, максимальная ошибка CIE RGB")
    for name, _, _, metrics in result["comparisons"]:
        lines.append(f"{name}: {metrics['rms']:.6g}; {metrics['max_difference']:.6g}; {metrics['rgb_error']:.6g}")
    lines.append(f"Общий максимум линейного sRGB: {result['maximum']:.8g}")
    if any(metrics["rgb_error"] > 1e-6 for _, _, _, metrics in result["comparisons"]):
        lines.append("Для заданного RGB найден приближённый спектр; ошибка цвета указана выше.")
    return "\n".join(lines)


# График исходного и восстановленного спектров; общие координаты для Canvas и SVG.
def spectrum_plot(original, restored, width=720, height=430):
    width, height = max(240, width), max(220, height)
    left, right, top, bottom = 70, width - 25, 30, height - 55
    maximum = max(float(np.max(original)), float(np.max(restored)), 1e-12) * 1.08
    curves = []
    for spectrum in (original, restored):
        curves.append([(left + (wave - 380) / 400 * (right - left),
                        bottom - float(value) / maximum * (bottom - top))
                       for wave, value in zip(core.WAVELENGTHS, spectrum)])
    return (left, right, top, bottom), maximum, curves


# Сохранение графика спектрограмм в SVG для отчёта.
def spectrum_svg(original, restored, title):
    width, height = 800, 480
    (left, right, top, bottom), maximum, curves = spectrum_plot(original, restored, width, height)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             f'<text x="{width / 2}" y="20" text-anchor="middle" font-family="sans-serif" font-size="16">{title}</text>',
             f'<path d="M {left} {top} V {bottom} H {right}" fill="none" stroke="black"/>']
    unit = "K_d(λ)" if title == "Поверхность" else "S(λ), 1/нм"
    parts.append(f'<text x="8" y="20" font-size="12">{unit}</text>')
    for wave in range(380, 781, 80):
        x = left + (wave - 380) / 400 * (right - left)
        parts.append(f'<text x="{x}" y="{bottom + 22}" text-anchor="middle" font-size="12">{wave}</text>')
    for i in range(5):
        y = bottom - i / 4 * (bottom - top)
        parts.append(f'<text x="{left - 8}" y="{y + 4}" text-anchor="end" font-size="12">{maximum * i / 4:.4g}</text>')
    for color, points in zip(("#19713a", "#bb2935"), curves):
        coordinates = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
        parts.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="2"/>')
    parts.extend((f'<text x="{width / 2}" y="{height - 6}" text-anchor="middle" font-size="13">λ, нм</text>',
                  '<text x="90" y="48" fill="#19713a" font-size="13">Исходный</text>',
                  '<text x="210" y="48" fill="#bb2935" font-size="13">Восстановленный</text>', '</svg>'))
    return "\n".join(parts)


# Запись image_A, эталонных изображений lab3, таблиц спектров, графиков и абсолютных результатов.
def save_result(result, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    p = result["params"]
    for name, data in zip(IMAGE_NAMES, result["png"]):
        (folder / (name + ".png")).write_bytes(data)
    (folder / "values.txt").write_text(result_text(result), encoding="utf-8")
    for i, (name, original, restored, _) in enumerate(result["comparisons"]):
        stem = f"source_{i + 1}" if i < len(p["lights"]) else "reflection"
        with (folder / (stem + "_spectra.csv")).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(("wavelength_nm", "original", "restored", "difference"))
            writer.writerows((wave, float(a), float(b), float(b - a))
                             for wave, a, b in zip(core.WAVELENGTHS, original, restored))
        (folder / (stem + "_spectra.svg")).write_text(spectrum_svg(original, restored, name), encoding="utf-8")
    scene = {key: p[key] for key, _, _ in FIELDS}
    scene.update(lights=[list(light[:7]) + [list(light[-1])] for light in p["lights"]],
                 reflection_rgb=list(p["reflection_rgb"]), original_reflection=list(p["original_reflection"]),
                 original_spectra=[list(spectrum) for spectrum in p["original_spectra"]])
    (folder / "scene.json").write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")


class LabWindow:
    # Интерфейс lab4: исходная сцена RGB, три изображения, таблицы и графики спектрограмм.
    def __init__(self, root):
        self.root = root
        root.title("Построение спектра по цвету")
        root.geometry("1320x900")
        root.minsize(1120, 720)
        self.values = {}
        self.light_values = {}
        self.light_spectra = {}
        self.original_reflection = core.default_reflection()
        self.result = None
        self.photos = []
        self.previews = []
        self.last_size_field = "w_res"
        self.adjusting_size = False
        self.loading_light = False
        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)
        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        form_canvas = tk.Canvas(left, width=352, highlightthickness=0)
        form_canvas.pack(side="left", fill="y")
        scroll = ttk.Scrollbar(left, orient="vertical", command=form_canvas.yview)
        scroll.pack(side="right", fill="y")
        form_canvas.configure(yscrollcommand=scroll.set)
        form = ttk.Frame(form_canvas, padding=6)
        form_canvas.create_window((0, 0), window=form, anchor="nw", width=352)
        form.bind("<Configure>", lambda _: form_canvas.configure(scrollregion=form_canvas.bbox("all")))
        parameters = ttk.LabelFrame(form, text="Параметры", padding=7)
        parameters.pack(fill="x")
        for row, (key, label, default) in enumerate(FIELDS):
            ttk.Label(parameters, text=label).grid(row=row, column=0, sticky="w", pady=2)
            variable = tk.StringVar(value=default)
            ttk.Entry(parameters, textvariable=variable, width=13).grid(row=row, column=1, padx=(8, 0), pady=2)
            self.values[key] = variable
        surface = ttk.LabelFrame(form, text="Поверхность: CIE RGB", padding=7)
        surface.pack(fill="x", pady=(0, 5))
        self.reflection_values = self.rgb_fields(surface, core.reflection_to_rgb(self.original_reflection), ("K_R", "K_G", "K_B"))
        light_form = ttk.LabelFrame(form, text="Источники света", padding=7)
        light_form.pack(fill="x")
        for row, (key, label, default) in enumerate(LIGHT_FIELDS):
            ttk.Label(light_form, text=label).grid(row=row, column=0, sticky="w", pady=1)
            variable = tk.StringVar(value=default)
            ttk.Entry(light_form, textvariable=variable, width=13).grid(row=row, column=1, sticky="e", pady=1)
            self.light_values[key] = variable
        colors = ttk.LabelFrame(light_form, text="CIE RGB, линейные", padding=4)
        colors.grid(row=len(LIGHT_FIELDS), column=0, columnspan=2, sticky="ew", pady=4)
        color = core.spectrum_to_rgb(core.normalize_spectrum(core.D65))
        self.rgb_values = self.rgb_fields(colors, color)
        ttk.Button(light_form, text="На центр сферы", command=self.aim_light).grid(
            row=len(LIGHT_FIELDS) + 1, column=0, columnspan=2, sticky="ew", pady=3)
        buttons = ttk.Frame(form)
        buttons.pack(fill="x", pady=5)
        ttk.Button(buttons, text="Добавить", command=self.add_light).pack(side="left")
        ttk.Button(buttons, text="Изменить", command=self.update_light).pack(side="left", padx=4)
        ttk.Button(buttons, text="Удалить", command=self.remove_light).pack(side="left")
        columns = tuple(key for key, _, _ in LIGHT_FIELDS) + ("R", "G", "B")
        self.light_list = ttk.Treeview(form, columns=columns, show="headings", height=3, selectmode="browse")
        for key in columns:
            self.light_list.heading(key, text=key)
            self.light_list.column(key, width=55, anchor="e", stretch=False)
        self.light_list.pack(fill="x")
        horizontal = ttk.Scrollbar(form, orient="horizontal", command=self.light_list.xview)
        horizontal.pack(fill="x")
        self.light_list.configure(xscrollcommand=horizontal.set)
        self.light_list.bind("<<TreeviewSelect>>", self.select_light)
        for position in ((-400, 350, 2300, 1, 0, 0, -1), (400, -350, 2300, 1, 0, 0, -1)):
            self.insert_light((*position, tuple(color)), core.D65)
        self.light_list.selection_set(self.light_list.get_children()[0])
        ttk.Button(form, text="Рассчитать", command=self.run).pack(fill="x", pady=(9, 4))
        self.save_button = ttk.Button(form, text="Сохранить результаты", command=self.save, state="disabled")
        self.save_button.pack(fill="x")
        self.status = tk.StringVar()
        ttk.Label(form, textvariable=self.status, wraplength=325).pack(fill="x", pady=5)
        result_frame = ttk.Frame(main)
        result_frame.grid(row=0, column=1, sticky="nsew")
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)
        notebook = ttk.Notebook(result_frame)
        notebook.grid(row=0, column=0, sticky="nsew")
        self.images = []
        for title in ("image_A", "image_1 (lab3)", "image_2 (lab3)"):
            page = ttk.Frame(notebook)
            notebook.add(page, text=title)
            label = ttk.Label(page, anchor="center")
            label.pack(fill="both", expand=True)
            self.images.append(label)
        page = ttk.Frame(notebook, padding=6)
        notebook.add(page, text="Спектры")
        self.spectrum_choice = tk.StringVar()
        self.spectrum_combo = ttk.Combobox(page, textvariable=self.spectrum_choice, state="readonly")
        self.spectrum_combo.pack(fill="x", pady=(0, 6))
        self.spectrum_combo.bind("<<ComboboxSelected>>", self.show_spectrum)
        body = ttk.Frame(page)
        body.pack(fill="both", expand=True)
        self.spectrum_table = ttk.Treeview(body, columns=("wave", "original", "restored", "difference"),
                                          show="headings", height=18)
        for key, title, width in (("wave", "λ, нм", 60), ("original", "Исходный", 120),
                                  ("restored", "Восстановленный", 150), ("difference", "Разница", 120)):
            self.spectrum_table.heading(key, text=title)
            self.spectrum_table.column(key, width=width, anchor="e", stretch=False)
        self.spectrum_table.pack(side="left", fill="y")
        vertical = ttk.Scrollbar(body, orient="vertical", command=self.spectrum_table.yview)
        vertical.pack(side="left", fill="y")
        self.spectrum_table.configure(yscrollcommand=vertical.set)
        self.graph = tk.Canvas(body, background="white", highlightthickness=1, highlightbackground="#aaa")
        self.graph.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.graph.bind("<Configure>", self.draw_spectrum)
        self.details = tk.Text(result_frame, height=14, width=90, wrap="none", state="disabled", font="TkFixedFont")
        self.details.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        scrollbar = ttk.Scrollbar(result_frame, orient="horizontal", command=self.details.xview)
        scrollbar.grid(row=2, column=0, sticky="ew")
        self.details.configure(xscrollcommand=scrollbar.set)
        for key, variable in self.values.items():
            variable.trace_add("write", lambda *_, key=key: self.parameter_changed(key))
        for variable in list(self.light_values.values()) + self.rgb_values + self.reflection_values:
            variable.trace_add("write", self.light_changed)
        root.bind("<Return>", lambda _: self.run())

    # Поля ввода трёх цветовых координат RGB.
    def rgb_fields(self, frame, values, labels=("R", "G", "B")):
        variables = []
        for i, (label, value) in enumerate(zip(labels, values)):
            ttk.Label(frame, text=label).grid(row=0, column=i, padx=2)
            variable = tk.StringVar(value=f"{value:.12g}")
            ttk.Entry(frame, textvariable=variable, width=9).grid(row=1, column=i, padx=2)
            variables.append(variable)
        return variables

    # Запись источника и его исходной спектрограммы для сравнения с lab3.
    def insert_light(self, light, spectrum):
        item = self.light_list.insert("", "end", values=tuple(f"{v:.12g}" for v in (*light[:7], *light[-1])))
        self.light_spectra[item] = np.asarray(core.normalize_spectrum(spectrum))
        return item

    # Изменение геометрии; запоминание стороны для согласования квадратных пикселей.
    def parameter_changed(self, key):
        if not self.adjusting_size:
            if key in SIZE_FIELDS:
                self.last_size_field = key
            self.clear_result()

    # Очистка устаревших изображений, таблиц и графиков.
    def clear_result(self):
        self.result = None
        self.photos = []
        self.previews = []
        for label in self.images:
            label.configure(image="", text="")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")
        self.spectrum_table.delete(*self.spectrum_table.get_children())
        self.spectrum_combo.configure(values=())
        self.spectrum_choice.set("")
        self.graph.delete("all")
        self.save_button.configure(state="disabled")
        self.status.set("")

    # Изменение цвета или параметров источника; сброс результатов.
    def light_changed(self, *_):
        if not self.loading_light:
            self.clear_result()

    # Чтение выбранного источника из полей интерфейса.
    def get_light(self):
        return read_light({key: var.get() for key, var in self.light_values.items()},
                          [var.get() for var in self.rgb_values])

    # Выбор источника в списке; загрузка положения, направления и RGB.
    def select_light(self, _=None):
        selected = self.light_list.selection()
        if selected:
            self.loading_light = True
            try:
                values = self.light_list.item(selected[0], "values")
                for variable, value in zip(list(self.light_values.values()) + self.rgb_values, values):
                    variable.set(value)
            finally:
                self.loading_light = False

    # Направление источника на центр сферы: нормированный вектор C − L.
    def aim_light(self):
        try:
            center = [read_number(self.values[key].get(), key) for key in ("xc", "yc", "zc")]
            position = [read_number(self.light_values[key].get(), key) for key in ("xl", "yl", "zl")]
            direction = core.unit(np.subtract(center, position))
            for key, value in zip(("dx", "dy", "dz"), direction):
                self.light_values[key].set(f"{value:.12g}")
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)

    # Добавление источника RGB; исходный спектр для нового источника — D65.
    def add_light(self):
        try:
            light = self.get_light()
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
            return
        item = self.insert_light(light, core.D65)
        self.light_list.selection_set(item)
        self.light_list.see(item)
        self.clear_result()

    # Сохранение изменённых параметров выбранного источника.
    def update_light(self):
        selected = self.light_list.selection()
        if not selected:
            messagebox.showerror("Ошибка", "Выберите источник в списке.", parent=self.root)
            return
        try:
            light = self.get_light()
            self.light_list.item(selected[0], values=tuple(f"{v:.12g}" for v in (*light[:7], *light[-1])))
            self.clear_result()
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)

    # Удаление источника света и соответствующего исходного спектра.
    def remove_light(self):
        selected = self.light_list.selection()
        if selected:
            self.light_list.delete(selected[0])
            del self.light_spectra[selected[0]]
            self.clear_result()
            items = self.light_list.get_children()
            if items:
                self.light_list.selection_set(items[0])

    # Расчёт трёх изображений и восстановленных спектров; визуализация результатов.
    def run(self):
        self.clear_result()
        try:
            values, correction = adjust_image_size({key: var.get() for key, var in self.values.items()}, self.last_size_field)
            self.adjusting_size = True
            try:
                for key in SIZE_FIELDS:
                    self.values[key].set(values[key])
            finally:
                self.adjusting_size = False
            selected = self.light_list.selection()
            if selected:
                light = self.get_light()
                self.light_list.item(selected[0], values=tuple(f"{v:.12g}" for v in (*light[:7], *light[-1])))
            lights = []
            originals = []
            for item in self.light_list.get_children():
                values_light = self.light_list.item(item, "values")
                light = read_light(dict(zip((key for key, _, _ in LIGHT_FIELDS), values_light[:7])), values_light[7:])
                lights.append(light)
                originals.append(self.light_spectra[item])
            p = read_parameters(values, lights)
            p.update(reflection_rgb=tuple(read_number(v.get(), name) for v, name in
                                         zip(self.reflection_values, ("K_R", "K_G", "K_B"))),
                     original_reflection=self.original_reflection, original_spectra=originals)
            self.status.set("Расчёт…")
            self.root.update_idletasks()
            result = calculate(p)
            self.photos = [tk.PhotoImage(data=base64.b64encode(data).decode("ascii"), format="png") for data in result["png"]]
            factor = max(1, math.ceil(p["w_res"] / 760), math.ceil(p["h_res"] / 480))
            self.previews = [photo.subsample(factor) if factor > 1 else photo for photo in self.photos]
            for label, photo in zip(self.images, self.previews):
                label.configure(image=photo)
            self.result = result
            self.details.configure(state="normal")
            self.details.insert("1.0", result_text(result))
            self.details.configure(state="disabled")
            self.spectrum_combo.configure(values=[name for name, *_ in result["comparisons"]])
            self.spectrum_combo.current(0)
            self.show_spectrum()
            self.save_button.configure(state="normal")
            self.status.set("Готово. " + correction)
        except (ValueError, ArithmeticError, MemoryError, tk.TclError, np.linalg.LinAlgError) as exc:
            self.status.set("Расчёт не выполнен.")
            messagebox.showerror("Ошибка", str(exc), parent=self.root)

    # Таблица спектрограммы: исходные и восстановленные значения по 41 длине волны.
    def show_spectrum(self, _=None):
        self.spectrum_table.delete(*self.spectrum_table.get_children())
        if self.result is None:
            return
        index = self.spectrum_combo.current()
        if index < 0:
            return
        _, original, restored, _ = self.result["comparisons"][index]
        for wave, a, b in zip(core.WAVELENGTHS, original, restored):
            self.spectrum_table.insert("", "end", values=(wave, f"{a:.6g}", f"{b:.6g}", f"{b - a:.6g}"))
        self.draw_spectrum()

    # Графики спектрального распределения исходного и восстановленного спектров.
    def draw_spectrum(self, _=None):
        self.graph.delete("all")
        if self.result is None or self.spectrum_combo.current() < 0:
            return
        index = self.spectrum_combo.current()
        name, original, restored, _ = self.result["comparisons"][index]
        width, height = self.graph.winfo_width(), self.graph.winfo_height()
        (left, right, top, bottom), maximum, curves = spectrum_plot(original, restored, width, height)
        self.graph.create_line(left, top, left, bottom, right, bottom)
        for wave in range(380, 781, 80):
            x = left + (wave - 380) / 400 * (right - left)
            self.graph.create_text(x, bottom + 15, text=str(wave))
        for i in range(5):
            y = bottom - i / 4 * (bottom - top)
            self.graph.create_text(left - 8, y, text=f"{maximum * i / 4:.3g}", anchor="e")
            if i:
                self.graph.create_line(left, y, right, y, fill="#ddd")
        for color, points in zip(("#19713a", "#bb2935"), curves):
            self.graph.create_line(*(coordinate for point in points for coordinate in point), fill=color, width=2)
        self.graph.create_text((left + right) / 2, height - 12, text="λ, нм")
        self.graph.create_text(8, 12, text="K_d(λ)" if name == "Поверхность" else "S(λ), 1/нм", anchor="w")
        self.graph.create_text(left + 5, top + 5, text="Исходный", fill="#19713a", anchor="nw")
        self.graph.create_text(left + 5, top + 25, text="Восстановленный", fill="#bb2935", anchor="nw")

    # Сохранение изображений, спектральных таблиц, SVG-графиков и значений яркости.
    def save(self):
        if self.result is None:
            return
        directory = filedialog.askdirectory(parent=self.root, title="Папка для результатов")
        if not directory:
            return
        folder = Path(directory) / "lab4_results"
        if folder.exists() and any(folder.iterdir()):
            if not messagebox.askyesno("Сохранение", f"Перезаписать результаты в {folder}?", parent=self.root):
                return
        try:
            save_result(self.result, folder)
        except OSError as exc:
            messagebox.showerror("Ошибка сохранения", str(exc), parent=self.root)
        else:
            self.status.set(f"Сохранено: {folder}")


if __name__ == "__main__":
    root = tk.Tk()
    LabWindow(root)
    root.mainloop()
