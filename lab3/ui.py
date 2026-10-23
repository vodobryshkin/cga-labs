import base64
import csv
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

LIGHT_FIELDS = (
    ("xl", "x_L, мм", "-400"),
    ("yl", "y_L, мм", "350"),
    ("zl", "z_L, мм", "2300"),
    ("i0", "I_0, Вт/ср", "1"),
    ("dx", "d_x", "0"),
    ("dy", "d_y", "0"),
    ("dz", "d_z", "-1"),
)

SIZE_FIELDS = ("w", "h", "w_res", "h_res")
MODES = ("Белые (D65)", "Цветные")
IMAGE_NAMES = ("image_1", "image_2", "image_1_gray", "image_2_gray")


def read_number(value, label, integer=False):
    try:
        value = value.strip().replace(",", ".")
        number = int(value) if integer else float(value)
    except ValueError as exc:
        raise ValueError(f"{label}: введите {'целое число' if integer else 'число'}.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label}: введите конечное число.")
    return number


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


def read_light(values):
    labels = {key: label for key, label, _ in LIGHT_FIELDS}
    params = {key: read_number(values[key], label) for key, label in labels.items()}
    if params["i0"] < 0:
        raise ValueError("Сила излучения не может быть отрицательной.")
    return tuple(params[key] for key, _, _ in LIGHT_FIELDS)


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


def read_parameters(values, lights):
    labels = {key: label for key, label, _ in FIELDS}
    params = {key: read_number(values[key], label, key.endswith("_res"))
              for key, label in labels.items()}
    if any(params[key] <= 0 for key in SIZE_FIELDS):
        raise ValueError("Размеры экрана и разрешение должны быть больше нуля.")
    if params["r"] < 0:
        raise ValueError("Радиус не может быть отрицательным.")
    if not math.isclose(params["w"] / params["w_res"],
                        params["h"] / params["h_res"], rel_tol=1e-9):
        raise ValueError("Пиксели должны быть квадратными: W / Wres = H / Hres.")
    params["lights"] = lights
    return params


def png_chunk(kind, data):
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def make_png(width, height, pixels, color=True):
    stride = width * (3 if color else 1)
    rows = b"".join(b"\0" + pixels[i * stride:(i + 1) * stride] for i in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2 if color else 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"sRGB", b"\0")
            + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b""))


def calculate(p):
    points = core.calc_all_points_on_sphere(
        p["xc"], p["yc"], p["zc"], p["r"], p["zo"],
        p["w"], p["h"], p["w_res"], p["h_res"])
    args = (p["lights"], p["xc"], p["yc"], p["zc"], p["r"], p["reflection"])
    inside = math.hypot(p["xc"], p["yc"], p["zo"] - p["zc"]) <= p["r"]
    result = core.calc_images(*args, points, inside=inside)
    if not all(np.isfinite(result[key]).all() for key in ("rgb_1", "rgb_2")):
        raise ValueError("Яркость вышла за пределы числового диапазона.")
    pixels, maximum = core.convert_rgb_to_pixels(
        result["rgb_1"], result["rgb_2"], points, p["w_res"], p["h_res"])
    gray = [core.convert_to_gray(image) for image in pixels]
    result["png"] = [make_png(p["w_res"], p["h_res"], image, i < 2)
                     for i, image in enumerate(pixels + gray)]
    result["maximum"] = maximum

    indices = np.array(list(points), dtype=int).reshape(-1, 2)
    image_1, image_2 = (np.frombuffer(image, dtype=np.uint8).reshape(p["h_res"], p["w_res"], 3)
                        for image in pixels)
    differences = np.abs(image_1[indices[:, 0], indices[:, 1]].astype(np.int16)
                          - image_2[indices[:, 0], indices[:, 1]].astype(np.int16))
    result["mae"] = float(differences.mean()) if differences.size else 0.0
    result["max_difference"] = int(differences.max(initial=0))
    result["points"] = points
    report_points = core.calc_report_points(p["xc"], p["yc"], p["zc"], p["r"], p["zo"])
    samples = core.calc_images(*args, dict(enumerate(point for _, point in report_points)), inside=inside)
    result["report_points"] = [(name, *point, samples["energy"][i],
                                 samples["luminance_1"][i], samples["luminance_2"][i])
                                for i, (name, point) in enumerate(report_points)]
    result["params"] = p
    return result


def result_text(result):
    p = result["params"]
    lines = [f"Вариант: {p['mode']}. Видимые пиксели сферы:"]
    for key, label, units in (("energy", "L_e (спектральный)", "Вт/(м²·ср)"),
                               ("luminance_1", "L_v (image_1)", "кд/м²"),
                               ("luminance_2", "L_v (image_2)", "кд/м²")):
        values = result[key]
        if values.size:
            lines.append(f"{label}: min = {values.min():.6g}, max = {values.max():.6g} {units}")
        else:
            lines.append(f"{label}: min = —, max = —")
    lines.extend((f"Разница RGB 0–255 по сфере: средняя = {result['mae']:.4g}, "
                  f"максимальная = {result['max_difference']}",
                  "Точка        x, мм     y, мм     z, мм      L_e, Вт/(м²·ср)    L_v1, кд/м²    L_v2, кд/м²"))
    lines.extend(f"{name:<9} {x:>9.4g} {y:>9.4g} {z:>9.4g} {energy:>19.6g} {lv1:>14.6g} {lv2:>14.6g}"
                 for name, x, y, z, energy, lv1, lv2 in result["report_points"])
    return "\n".join(lines)


class LabWindow:
    def __init__(self, root):
        self.root = root
        root.title("Цветная диффузная сфера")
        root.minsize(1180, 820)
        self.values = {}
        self.light_values = {}
        self.light_spectra = {}
        self.reflection = core.make_spectrum("Зелёный", reflection=True)
        self.last_size_field = "w_res"
        self.adjusting_size = False
        self.loading_light = False
        self.result = None
        self.photos = []
        self.previews = []

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)
        form = ttk.LabelFrame(main, text="Параметры", padding=10)
        form.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        for row, (key, label, default) in enumerate(FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=2)
            variable = tk.StringVar(value=default)
            ttk.Entry(form, textvariable=variable, width=12).grid(
                row=row, column=1, padx=(8, 0), pady=2)
            self.values[key] = variable

        row = len(FIELDS)
        ttk.Button(form, text="Спектр отражения K_d(λ)", command=lambda: self.edit_spectrum(True)).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(8, 8))
        self.mode = tk.StringVar(value=MODES[0])
        ttk.Combobox(form, textvariable=self.mode, values=MODES, state="readonly").grid(
            row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        light_form = ttk.LabelFrame(form, text="Источники света", padding=6)
        light_form.grid(row=row + 2, column=0, columnspan=2, sticky="ew")
        for light_row, (key, label, default) in enumerate(LIGHT_FIELDS):
            ttk.Label(light_form, text=label).grid(row=light_row, column=0, sticky="w", pady=1)
            variable = tk.StringVar(value=default)
            ttk.Entry(light_form, textvariable=variable, width=12).grid(
                row=light_row, column=1, sticky="e", padx=(8, 0), pady=1)
            self.light_values[key] = variable
        light_row = len(LIGHT_FIELDS)
        ttk.Button(light_form, text="На центр сферы", command=self.aim_light).grid(
            row=light_row, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        buttons = ttk.Frame(light_form)
        buttons.grid(row=light_row + 1, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Button(buttons, text="Добавить", command=self.add_light).pack(side="left")
        ttk.Button(buttons, text="Изменить", command=self.update_light).pack(side="left", padx=3)
        ttk.Button(buttons, text="Удалить", command=self.remove_light).pack(side="left")
        self.light_list = ttk.Treeview(light_form, columns=tuple(key for key, _, _ in LIGHT_FIELDS),
                                       show="headings", height=3, selectmode="browse")
        for key, heading in (("xl", "x_L"), ("yl", "y_L"), ("zl", "z_L"), ("i0", "I_0"),
                             ("dx", "d_x"), ("dy", "d_y"), ("dz", "d_z")):
            self.light_list.heading(key, text=heading)
            self.light_list.column(key, width=48, anchor="e", stretch=True)
        self.light_list.grid(row=light_row + 2, column=0, columnspan=2, sticky="ew")
        self.light_list.bind("<<TreeviewSelect>>", self.select_light)
        first = self.light_list.insert("", "end", values=(-400, 350, 2300, 1, 0, 0, -1))
        second = self.light_list.insert("", "end", values=(400, -350, 2300, 1, 0, 0, -1))
        self.light_spectra[first] = core.make_spectrum("Красный")
        self.light_spectra[second] = core.make_spectrum("Синий")
        self.light_list.selection_set(first)
        self.spectrum_button = ttk.Button(light_form, text="Спектр выбранного источника",
                                          command=self.edit_spectrum)
        self.spectrum_button.grid(row=light_row + 3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.spectrum_button.configure(state="disabled")

        ttk.Button(form, text="Рассчитать", command=self.run).grid(
            row=row + 3, column=0, columnspan=2, sticky="ew", pady=(10, 5))
        self.save_button = ttk.Button(form, text="Сохранить результаты", command=self.save, state="disabled")
        self.save_button.grid(row=row + 4, column=0, columnspan=2, sticky="ew")
        self.status = tk.StringVar()
        ttk.Label(form, textvariable=self.status, wraplength=285).grid(
            row=row + 5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        result_frame = ttk.Frame(main)
        result_frame.grid(row=0, column=1, sticky="nsew")
        notebook = ttk.Notebook(result_frame)
        notebook.pack(fill="both", expand=True)
        self.images = []
        for title in ("1. Спектральный расчёт", "2. Расчёт RGB", "1. Серое", "2. Серое"):
            page = ttk.Frame(notebook)
            notebook.add(page, text=title)
            label = ttk.Label(page, anchor="center")
            label.pack(fill="both", expand=True)
            self.images.append(label)
        self.details = tk.Text(result_frame, height=11, width=94, wrap="none", state="disabled",
                               font="TkFixedFont")
        self.details.pack(fill="x")
        scrollbar = ttk.Scrollbar(result_frame, orient="horizontal", command=self.details.xview)
        scrollbar.pack(fill="x")
        self.details.configure(xscrollcommand=scrollbar.set)

        for key, variable in self.values.items():
            variable.trace_add("write", lambda *_, key=key: self.parameter_changed(key))
        for variable in self.light_values.values():
            variable.trace_add("write", self.light_changed)
        self.mode.trace_add("write", self.mode_changed)
        root.bind("<Return>", lambda _: self.run())

    def parameter_changed(self, key):
        if self.adjusting_size:
            return
        if key in SIZE_FIELDS:
            self.last_size_field = key
        self.clear_result()

    def clear_result(self):
        self.result = None
        self.photos = []
        self.previews = []
        for label in self.images:
            label.configure(image="", text="")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.status.set("")

    def mode_changed(self, *_):
        self.spectrum_button.configure(state="disabled" if self.mode.get() == MODES[0] else "normal")
        self.clear_result()

    def select_light(self, _=None):
        selected = self.light_list.selection()
        if selected:
            self.loading_light = True
            try:
                for (key, _, _), value in zip(LIGHT_FIELDS, self.light_list.item(selected[0], "values")):
                    self.light_values[key].set(value)
            finally:
                self.loading_light = False

    def light_changed(self, *_):
        if not self.loading_light:
            self.clear_result()

    def get_light(self):
        return read_light({key: variable.get() for key, variable in self.light_values.items()})

    def aim_light(self):
        try:
            center = tuple(read_number(self.values[key].get(), key) for key in ("xc", "yc", "zc"))
            position = tuple(read_number(self.light_values[key].get(), key) for key in ("xl", "yl", "zl"))
            direction = tuple(c - p for c, p in zip(center, position))
            if math.hypot(*direction) == 0:
                return
            direction = core.unit(direction)
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
            return
        for key, value in zip(("dx", "dy", "dz"), direction):
            self.light_values[key].set(f"{value:.12g}")

    def add_light(self):
        try:
            light = self.get_light()
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
            return
        item = self.light_list.insert("", "end", values=tuple(f"{value:.12g}" for value in light))
        self.light_spectra[item] = core.D65
        self.light_list.selection_set(item)
        self.light_list.see(item)
        self.clear_result()

    def update_light(self):
        selected = self.light_list.selection()
        if not selected:
            messagebox.showerror("Ошибка", "Выберите источник в списке.", parent=self.root)
            return
        try:
            light = self.get_light()
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
            return
        self.light_list.item(selected[0], values=tuple(f"{value:.12g}" for value in light))
        self.clear_result()

    def remove_light(self):
        selected = self.light_list.selection()
        if selected:
            self.light_list.delete(selected[0])
            del self.light_spectra[selected[0]]
            self.clear_result()
            items = self.light_list.get_children()
            if items:
                self.light_list.selection_set(items[0])

    def edit_spectrum(self, reflection=False):
        selected = self.light_list.selection()
        if not reflection and not selected:
            messagebox.showerror("Ошибка", "Выберите источник в списке.", parent=self.root)
            return
        item = selected[0] if selected else None
        spectrum = self.reflection if reflection else self.light_spectra[item]
        dialog = tk.Toplevel(self.root)
        dialog.title("Спектр отражения" if reflection else "Спектр источника")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="λ, нм    K_d(λ), от 0 до 1" if reflection
                  else "λ, нм    Относительная спектральная плотность").pack(anchor="w")
        presets = ("Серый", "Красный", "Зелёный", "Синий", "Равномерный", "Чёрный") if reflection else (
            "D65", "6500 K", "Равномерный", "Красный", "Зелёный", "Синий")
        choice = tk.StringVar(value=presets[0])
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Combobox(toolbar, textvariable=choice, values=presets, state="readonly", width=20).pack(side="left")
        content = ttk.Frame(frame)
        content.pack(fill="both", expand=True)
        text = tk.Text(content, width=45, height=22, wrap="none", font="TkFixedFont")
        text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(content, command=text.yview)
        scrollbar.pack(side="right", fill="y")
        text.configure(yscrollcommand=scrollbar.set)

        def fill(values):
            text.delete("1.0", "end")
            text.insert("1.0", "\n".join(f"{wave}\t{value:.15g}"
                                        for wave, value in zip(core.WAVELENGTHS, values)))

        def apply():
            try:
                values = read_spectrum(text.get("1.0", "end"), reflection)
            except ValueError as exc:
                messagebox.showerror("Ошибка", str(exc), parent=dialog)
                return
            if reflection:
                self.reflection = values
            else:
                self.light_spectra[item] = values
            self.clear_result()
            dialog.destroy()

        ttk.Button(toolbar, text="Заполнить", command=lambda: fill(
            core.make_spectrum(choice.get(), reflection))).pack(side="left", padx=6)
        fill(spectrum)
        ttk.Button(frame, text="Применить", command=apply).pack(fill="x", pady=(10, 0))

    def run(self):
        self.clear_result()
        try:
            values, correction = adjust_image_size(
                {key: variable.get() for key, variable in self.values.items()}, self.last_size_field)
            self.adjusting_size = True
            try:
                for key in SIZE_FIELDS:
                    self.values[key].set(values[key])
            finally:
                self.adjusting_size = False
            selected = self.light_list.selection()
            if selected:
                self.light_list.item(selected[0], values=self.get_light())
            lights = []
            for item in self.light_list.get_children():
                light_values = dict(zip((key for key, _, _ in LIGHT_FIELDS),
                                        self.light_list.item(item, "values")))
                spectrum = core.D65 if self.mode.get() == MODES[0] else self.light_spectra[item]
                lights.append((*read_light(light_values), spectrum))
            params = read_parameters(values, lights)
            params["reflection"] = self.reflection
            params["mode"] = self.mode.get()
            self.status.set("Расчёт…")
            self.root.update_idletasks()
            result = calculate(params)
            self.photos = [tk.PhotoImage(data=base64.b64encode(data).decode("ascii"), format="png")
                           for data in result["png"]]
            factor = max(1, math.ceil(params["w_res"] / 720), math.ceil(params["h_res"] / 500))
            self.previews = [photo.subsample(factor) if factor > 1 else photo for photo in self.photos]
            for label, preview in zip(self.images, self.previews):
                label.configure(image=preview, text="")
            self.details.configure(state="normal")
            self.details.insert("1.0", result_text(result))
            self.details.configure(state="disabled")
            self.result = result
            self.save_button.configure(state="normal")
            self.status.set("Готово. " + correction)
        except (ValueError, ArithmeticError, MemoryError, tk.TclError) as exc:
            self.status.set("Расчёт не выполнен.")
            messagebox.showerror("Ошибка", str(exc), parent=self.root)

    def save(self):
        if self.result is None:
            return
        directory = filedialog.askdirectory(parent=self.root, title="Папка для результатов")
        if not directory:
            return
        p = self.result["params"]
        folder = Path(directory) / ("white" if p["mode"] == MODES[0] else "colored")
        if folder.exists() and any(folder.iterdir()):
            if not messagebox.askyesno("Сохранение", f"Перезаписать результаты в {folder}?", parent=self.root):
                return
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for name, data in zip(IMAGE_NAMES, self.result["png"]):
                (folder / (name + ".png")).write_bytes(data)
            lines = [result_text(self.result), "", "Параметры:"]
            lines.extend(f"{label}: {p[key]:.12g}" for key, label, _ in FIELDS)
            lines.append(f"Общий максимум линейного sRGB: {self.result['maximum']:.12g}")
            for number, light in enumerate(p["lights"], 1):
                lines.append(f"Источник {number}: x_L={light[0]:g}, y_L={light[1]:g}, "
                             f"z_L={light[2]:g} мм, I_0={light[3]:g} Вт/ср, "
                             f"d=({light[4]:g}, {light[5]:g}, {light[6]:g})")
            (folder / "values.txt").write_text("\n".join(lines), encoding="utf-8")
            with (folder / "spectra.csv").open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow(["wavelength_nm", "Kd"] + [f"source_{i + 1}_relative"
                                                           for i in range(len(p["lights"]))])
                for i, wave in enumerate(core.WAVELENGTHS):
                    writer.writerow([wave, p["reflection"][i]] + [light[-1][i] for light in p["lights"]])
        except OSError as exc:
            messagebox.showerror("Ошибка сохранения", str(exc), parent=self.root)
        else:
            self.status.set(f"Сохранено: {folder}")


if __name__ == "__main__":
    root = tk.Tk()
    LabWindow(root)
    root.mainloop()