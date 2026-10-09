import base64
import math
from pathlib import Path
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import zlib

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
    ("kd", "K_d", "0.2"),
    ("ks", "K_s", "0.7"),
    ("ke", "k_e", "64"),
    ("c", "Коэффициент блеска c", "3"),
)

LIGHT_FIELDS = (
    ("xl", "x_L, мм", "-400"),
    ("yl", "y_L, мм", "350"),
    ("zl", "z_L, мм", "2300"),
    ("i0", "I_0, Вт/ср", "1"),
)

SIZE_FIELDS = ("w", "h", "w_res", "h_res")


def read_number(value, label, integer=False):
    try:
        value = value.strip().replace(",", ".")
        number = int(value) if integer else float(value)
    except ValueError as exc:
        raise ValueError(f"{label}: введите {'целое число' if integer else 'число'}.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label}: введите конечное число.")
    return number


def check_limits(params, labels, limits):
    for key, (low, high) in limits.items():
        if not low <= params[key] <= high:
            raise ValueError(f"{labels[key]}: допустимо от {low:g} до {high:g}.")


def adjust_image_size(values, changed):
    labels = {key: label for key, label, _ in FIELDS}
    sizes = {key: read_number(values[key], labels[key], key.endswith("_res"))
             for key in SIZE_FIELDS}
    check_limits(sizes, labels, {"w": (100, 10000), "h": (100, 10000),
                                 "w_res": (200, 800), "h_res": (200, 800)})
    if math.isclose(sizes["w"] / sizes["w_res"],
                    sizes["h"] / sizes["h_res"], rel_tol=1e-12):
        return values.copy(), ""

    side = "h" if changed in ("h", "h_res") else "w"
    other = "w" if side == "h" else "h"
    resolution = side + "_res"
    step = sizes[other] / sizes[other + "_res"]
    # Меняем последнюю введённую сторону; другую сторону сохраняем.
    low = max(200, math.ceil(100 / step - 1e-12))
    high = min(800, math.floor(10000 / step + 1e-12))
    wanted = round(sizes[side] / step) if changed == resolution else sizes[resolution]
    sizes[resolution] = min(high, max(low, wanted))
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
    check_limits(params, labels, {"xl": (-10000, 10000), "yl": (-10000, 10000),
                                  "zl": (100, 10000), "i0": (0.01, 10000)})
    return tuple(params[key] for key, _, _ in LIGHT_FIELDS)


def read_parameters(values, lights):
    labels = {key: label for key, label, _ in FIELDS}
    params = {key: read_number(values[key], label, key.endswith("_res"))
              for key, label in labels.items()}
    check_limits(params, labels, {
        "w": (100, 10000), "h": (100, 10000),
        "w_res": (200, 800), "h_res": (200, 800),
        "xc": (-10000, 10000), "yc": (-10000, 10000), "zc": (100, 10000),
        "kd": (0, 1), "ks": (0, 1),
    })
    if params["r"] <= 0:
        raise ValueError("Радиус должен быть больше нуля.")
    if params["zo"] <= params["zc"] + params["r"]:
        raise ValueError("Наблюдатель должен находиться перед всей сферой: z_O > z_C + r.")
    if params["ke"] <= 0 or params["c"] < 0:
        raise ValueError("k_e должен быть больше нуля, c — не меньше нуля.")
    if not math.isclose(params["w"] / params["w_res"],
                        params["h"] / params["h_res"], rel_tol=1e-9):
        raise ValueError("Пиксели должны быть квадратными: W / Wres = H / Hres.")
    if not core.is_sphere_in_view(params["xc"], params["yc"], params["zc"],
                                   params["r"], params["zo"], params["w"], params["h"]):
        raise ValueError("Сфера должна целиком помещаться в область видимости. "
                         "Увеличьте экран, уменьшите радиус или измените положение сферы.")
    if not lights:
        raise ValueError("Добавьте хотя бы один источник света.")

    checked_lights = []
    for number, light in enumerate(lights, 1):
        light_values = {key: str(value) for (key, _, _), value in zip(LIGHT_FIELDS, light)}
        try:
            light = read_light(light_values)
        except ValueError as exc:
            raise ValueError(f"Источник {number}: {exc}") from exc
        xl, yl, zl, _ = light
        if ((xl - params["xc"]) ** 2 + (yl - params["yc"]) ** 2
                + (zl - params["zc"]) ** 2 <= params["r"] ** 2):
            raise ValueError(f"Источник {number} должен находиться вне сферы.")
        checked_lights.append(light)
    params["lights"] = checked_lights
    return params


def png_chunk(kind, data):
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def make_png(width, height, pixels):
    rows = b"".join(b"\0" + pixels[i * width:(i + 1) * width]
                    for i in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
            + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b""))


def calculate(p):
    points = core.calc_all_points_on_sphere(
        p["xc"], p["yc"], p["zc"], p["r"], p["zo"],
        p["w"], p["h"], p["w_res"], p["h_res"]
    )
    if not points:
        raise ValueError("На сферу не попал ни один пиксель. Увеличьте радиус или разрешение.")

    args = (p["lights"], p["zo"], p["xc"], p["yc"], p["zc"],
            p["r"], p["kd"], p["ks"], p["ke"], p["c"])
    values = core.calc_l_for_all_points(*args, points)
    if not all(math.isfinite(l) for l in values.values()):
        raise ValueError("Яркость вышла за пределы числового диапазона. Измените параметры.")
    gray = core.convert_l_to_g(values)
    pixels = bytearray(p["w_res"] * p["h_res"])
    for (i, j), g in gray.items():
        pixels[i * p["w_res"] + j] = g

    three_points = []
    for name, point in core.calc_report_points(p["xc"], p["yc"], p["zc"], p["r"], p["zo"]):
        three_points.append((name, *point, core.calc_l(point, *args)))
    section = core.calc_section(*args, p["h"])
    samples = values.values()
    stats = min(samples), max(samples)
    return make_png(p["w_res"], p["h_res"], pixels), stats, three_points, section


class LabWindow:
    def __init__(self, root):
        self.root = root
        root.title("Яркость сферы")
        root.minsize(1050, 820)
        self.values = {}
        self.light_values = {}
        self.last_size_field = "w_res"
        self.adjusting_size = False
        self.loading_light = False
        self.png_data = None
        self.photo = None
        self.preview = None

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
        ttk.Label(form, text="Экран z = 0: X по высоте, Y по ширине.\nВзгляд и излучение источников: -Z.",
                  wraplength=285).grid(row=row, column=0, columnspan=2, sticky="w", pady=(7, 9))
        light_form = ttk.LabelFrame(form, text="Источники света", padding=6)
        light_form.grid(row=row + 1, column=0, columnspan=2, sticky="ew")
        for light_row, (key, label, default) in enumerate(LIGHT_FIELDS):
            ttk.Label(light_form, text=label).grid(row=light_row, column=0, sticky="w", pady=1)
            variable = tk.StringVar(value=default)
            ttk.Entry(light_form, textvariable=variable, width=12).grid(
                row=light_row, column=1, sticky="e", padx=(8, 0), pady=1)
            self.light_values[key] = variable
        buttons = ttk.Frame(light_form)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(5, 5))
        ttk.Button(buttons, text="Добавить", command=self.add_light).pack(side="left")
        ttk.Button(buttons, text="Изменить", command=self.update_light).pack(side="left", padx=3)
        ttk.Button(buttons, text="Удалить", command=self.remove_light).pack(side="left")
        self.light_list = ttk.Treeview(light_form, columns=("xl", "yl", "zl", "i0"),
                                       show="headings", height=2, selectmode="browse")
        for key, heading, width in (("xl", "x_L", 65), ("yl", "y_L", 65),
                                    ("zl", "z_L", 65), ("i0", "I_0", 60)):
            self.light_list.heading(key, text=heading)
            self.light_list.column(key, width=width, anchor="e", stretch=True)
        self.light_list.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.light_list.bind("<<TreeviewSelect>>", self.select_light)
        first_light = self.light_list.insert(
            "", "end", values=tuple(default for _, _, default in LIGHT_FIELDS))
        self.light_list.selection_set(first_light)

        ttk.Button(form, text="Рассчитать", command=self.run).grid(
            row=row + 2, column=0, columnspan=2, sticky="ew", pady=(12, 5))
        self.save_button = ttk.Button(form, text="Сохранить PNG", command=self.save, state="disabled")
        self.save_button.grid(row=row + 3, column=0, columnspan=2, sticky="ew")
        self.status = tk.StringVar(value="Введите параметры и нажмите «Рассчитать».")
        ttk.Label(form, textvariable=self.status, wraplength=285).grid(
            row=row + 4, column=0, columnspan=2, sticky="w", pady=(9, 0))

        result = ttk.Frame(main)
        result.grid(row=0, column=1, sticky="nsew")
        ttk.Label(result, text="Распределение яркости").pack(anchor="w")
        self.image = ttk.Label(result, text="Нажмите «Рассчитать»", anchor="center")
        self.image.pack(fill="both", expand=True, pady=(5, 12))
        ttk.Label(result, text="Сечение по X через проекцию центра сферы").pack(anchor="w")
        self.graph = tk.Canvas(result, width=620, height=175, bg="white")
        self.graph.pack(fill="x", pady=(5, 10))
        self.details = ttk.Label(result, text="", justify="left", font="TkFixedFont")
        self.details.pack(anchor="w")

        for key, variable in self.values.items():
            variable.trace_add("write", lambda *_, key=key: self.parameter_changed(key))
        for variable in self.light_values.values():
            variable.trace_add("write", self.light_changed)
        root.bind("<Return>", lambda _: self.run())

    def parameter_changed(self, key):
        if self.adjusting_size:
            return
        if key in SIZE_FIELDS:
            self.last_size_field = key
        self.clear_result()

    def clear_result(self):
        self.png_data = None
        self.photo = None
        self.preview = None
        self.image.configure(image="", text="Нажмите «Рассчитать»")
        self.graph.delete("all")
        self.details.configure(text="")
        self.save_button.configure(state="disabled")
        self.status.set("Параметры изменены. Рассчитайте снова.")

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

    def add_light(self):
        try:
            light = self.get_light()
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
            return
        item = self.light_list.insert("", "end", values=tuple(f"{value:.12g}" for value in light))
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
            self.clear_result()

    def run(self):
        self.clear_result()
        try:
            values, correction = adjust_image_size(
                {key: variable.get() for key, variable in self.values.items()}, self.last_size_field)
            self.adjusting_size = True
            try:
                for key in SIZE_FIELDS:
                    if self.values[key].get() != values[key]:
                        self.values[key].set(values[key])
            finally:
                self.adjusting_size = False
            selected = self.light_list.selection()
            if selected:
                light = self.get_light()
                self.light_list.item(selected[0], values=tuple(f"{value:.12g}" for value in light))
            lights = [self.light_list.item(item, "values") for item in self.light_list.get_children()]
            params = read_parameters(values, lights)
            self.status.set("Расчёт…")
            self.root.update_idletasks()
            png_data, stats, points, section = calculate(params)

            self.photo = tk.PhotoImage(data=base64.b64encode(png_data).decode("ascii"), format="png")
            factor = max(1, math.ceil(params["w_res"] / 620), math.ceil(params["h_res"] / 430))
            self.preview = self.photo.subsample(factor) if factor > 1 else self.photo
            self.image.configure(image=self.preview, text="")
            self.draw_section(section)
            lines = [f"Видимые пиксели сферы: L_min = {stats[0]:.6g}, L_max = {stats[1]:.6g} Вт/(м²·ср)",
                     "Точка          x, мм       y, мм       z, мм     L, Вт/(м²·ср)"]
            lines.extend(f"{name:<9} {x:>11.6g} {y:>11.6g} {z:>11.6g} {l:>15.6g}"
                         for name, x, y, z, l in points)
            self.details.configure(text="\n".join(lines))
            self.png_data = png_data
            self.save_button.configure(state="normal")
            text = "Готово. " if stats[1] else "Готово. Источники не освещают видимую поверхность. "
            self.status.set(text + correction + " Изображение можно сохранить.")
        except (ValueError, ArithmeticError, tk.TclError) as exc:
            self.status.set("Расчёт не выполнен.")
            messagebox.showerror("Ошибка", str(exc), parent=self.root)

    def draw_section(self, section):
        canvas = self.graph
        left, right, top, bottom = 75, int(canvas["width"]) - 15, 20, 140
        maximum = max(l for _, l in section)
        x_min, x_max = section[0][0], section[-1][0]
        coords = []
        for x, l in section:
            coords.extend((left + (x - x_min) / (x_max - x_min) * (right - left),
                           bottom - (l / maximum if maximum else 0) * (bottom - top)))
        canvas.create_line(left, top, left, bottom, right, bottom)
        canvas.create_line(*coords, fill="blue")
        canvas.create_text(left - 5, top, text=f"{maximum:.3g}", anchor="e")
        canvas.create_text(left - 5, bottom, text="0", anchor="e")
        canvas.create_text(left, bottom + 15, text=f"{x_min:g}")
        canvas.create_text(right, bottom + 15, text=f"{x_max:g}")
        canvas.create_text((left + right) / 2, bottom + 15, text="x экрана, мм")
        canvas.create_text(left, 9, text="L, Вт/(м²·ср)", anchor="w")

    def save(self):
        if self.png_data is None:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".png",
                                            initialfile="sphere.png", filetypes=[("PNG", "*.png")])
        if path:
            try:
                Path(path).write_bytes(self.png_data)
            except OSError as exc:
                messagebox.showerror("Ошибка сохранения", str(exc), parent=self.root)
            else:
                self.status.set(f"Сохранено: {path}")


if __name__ == "__main__":
    root = tk.Tk()
    LabWindow(root)
    root.mainloop()
