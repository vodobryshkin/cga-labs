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
    ("xl", "x_L, мм", "0"),
    ("yl", "y_L, мм", "0"),
    ("zl", "z_L, мм", "1000"),
    ("i0", "I_0, Вт/ср", "1"),
    ("xc", "Центр круга x_c, мм", "0"),
    ("yc", "Центр круга y_c, мм", "0"),
    ("r", "Радиус r, мм", "800"),
)


def read_parameters(values):
    labels = {key: label for key, label, _ in FIELDS}
    params = {}
    for key, label in labels.items():
        value = values[key].strip().replace(",", ".")
        try:
            number = int(value) if key in ("w_res", "h_res") else float(value)
        except ValueError as exc:
            raise ValueError(f"{label}: введите число.") from exc
        if not math.isfinite(number):
            raise ValueError(f"{label}: введите конечное число.")
        params[key] = number

    limits = {
        "w": (100, 10000), "h": (100, 10000),
        "w_res": (200, 800), "h_res": (200, 800),
        "xl": (-10000, 10000), "yl": (-10000, 10000),
        "zl": (100, 10000), "i0": (0.01, 10000),
    }
    for key, (low, high) in limits.items():
        if not low <= params[key] <= high:
            raise ValueError(f"{labels[key]}: допустимо от {low:g} до {high:g}.")

    if not math.isclose(params["w"] / params["w_res"],
                        params["h"] / params["h_res"], rel_tol=1e-9):
        raise ValueError("Пиксели должны быть квадратными: W / Wres = H / Hres.")
    if params["r"] <= 0:
        raise ValueError("Радиус должен быть больше нуля.")
    if (abs(params["xc"]) + params["r"] > params["h"] / 2
            or abs(params["yc"]) + params["r"] > params["w"] / 2):
        raise ValueError("Круг должен целиком помещаться внутри прямоугольника.")
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
    points = core.calc_all_points_in_the_circle(
        p["xc"], p["yc"], p["r"], p["w"], p["h"], p["w_res"], p["h_res"]
    )
    if not points:
        raise ValueError("Внутрь круга не попал ни один пиксель. Увеличьте радиус.")

    values = core.calc_e_for_all_points(p["i0"], p["xl"], p["yl"], p["zl"], points)
    gray = core.convert_e_to_g(values)
    pixels = bytearray(p["w_res"] * p["h_res"])
    for i in range(p["h_res"]):
        x = -p["h"] / 2 + (i + 0.5) * p["h"] / p["h_res"]
        for j in range(p["w_res"]):
            y = -p["w"] / 2 + (j + 0.5) * p["w"] / p["w_res"]
            pixels[i * p["w_res"] + j] = gray.get((x, y), 0)

    xc, yc, r = p["xc"], p["yc"], p["r"]
    positions = (("Центр", xc, yc), ("−X", xc - r, yc),
                 ("+X", xc + r, yc), ("−Y", xc, yc - r),
                 ("+Y", xc, yc + r))
    five_points = [(name, x, y, core.calc_e(p["i0"], p["xl"], p["yl"],
                                               p["zl"], x, y))
                   for name, x, y in positions]
    section = []
    for i in range(201):
        x = xc - r + 2 * r * i / 200
        section.append((x, core.calc_e(p["i0"], p["xl"], p["yl"], p["zl"], x, yc)))

    samples = list(values.values())
    stats = min(samples), max(samples), sum(samples) / len(samples)
    return make_png(p["w_res"], p["h_res"], pixels), stats, five_points, section


class LabWindow:
    def __init__(self, root):
        self.root = root
        root.title("Освещённость плоскости")
        root.minsize(850, 700)
        self.values = {}
        self.png_data = None
        self.photo = None
        self.preview = None

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)

        form = ttk.LabelFrame(main, text="Параметры", padding=10)
        form.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        for row, (key, label, default) in enumerate(FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            variable = tk.StringVar(value=default)
            ttk.Entry(form, textvariable=variable, width=12).grid(row=row, column=1, padx=(8, 0), pady=3)
            self.values[key] = variable

        ttk.Button(form, text="Рассчитать", command=self.run).grid(
            row=len(FIELDS), column=0, columnspan=2, sticky="ew", pady=(16, 5))
        self.save_button = ttk.Button(form, text="Сохранить PNG", command=self.save, state="disabled")
        self.save_button.grid(row=len(FIELDS) + 1, column=0, columnspan=2, sticky="ew")
        self.status = tk.StringVar(value="Введите параметры и нажмите «Рассчитать».")
        ttk.Label(form, textvariable=self.status, wraplength=225).grid(
            row=len(FIELDS) + 2, column=0, columnspan=2, sticky="w", pady=(12, 0))

        result = ttk.Frame(main)
        result.grid(row=0, column=1, sticky="nsew")
        ttk.Label(result, text="Распределение освещённости").pack(anchor="w")
        self.image = ttk.Label(result, text="Нажмите «Рассчитать»", anchor="center")
        self.image.pack(fill="both", expand=True, pady=(5, 12))
        ttk.Label(result, text="Сечение по X через центр круга, y = y_c").pack(anchor="w")
        self.graph = tk.Canvas(result, width=550, height=175, bg="white")
        self.graph.pack(fill="x", pady=(5, 10))
        self.details = ttk.Label(result, text="", justify="left", font="TkFixedFont")
        self.details.pack(anchor="w")

        for variable in self.values.values():
            variable.trace_add("write", self.clear_result)

    def clear_result(self, *_):
        self.png_data = None
        self.photo = None
        self.preview = None
        self.image.configure(image="", text="Нажмите «Рассчитать»")
        self.graph.delete("all")
        self.details.configure(text="")
        self.save_button.configure(state="disabled")
        self.status.set("Параметры изменены. Рассчитайте снова.")

    def run(self):
        self.clear_result()
        try:
            params = read_parameters({key: var.get() for key, var in self.values.items()})
            self.status.set("Расчёт…")
            self.root.update_idletasks()
            png_data, stats, points, section = calculate(params)

            self.photo = tk.PhotoImage(data=base64.b64encode(png_data).decode("ascii"), format="png")
            factor = max(1, math.ceil(params["w_res"] / 550), math.ceil(params["h_res"] / 390))
            self.preview = self.photo.subsample(factor) if factor > 1 else self.photo
            self.image.configure(image=self.preview, text="")
            self.draw_section(section)

            lines = [f"Мин: {stats[0]:.6g}    Макс: {stats[1]:.6g}    Среднее: {stats[2]:.6g} Вт/м²",
                     "Точка       x, мм       y, мм       E, Вт/м²"]
            lines.extend(f"{name:<7} {x:>11.6g} {y:>11.6g} {e:>13.6g}"
                         for name, x, y, e in points)
            self.details.configure(text="\n".join(lines))
            self.png_data = png_data
            self.save_button.configure(state="normal")
            self.status.set("Готово. Изображение можно сохранить.")
        except (ValueError, ArithmeticError, tk.TclError) as exc:
            self.status.set("Расчёт не выполнен.")
            messagebox.showerror("Ошибка", str(exc), parent=self.root)

    def draw_section(self, section):
        canvas = self.graph
        left, right, top, bottom = 65, int(canvas["width"]) - 15, 20, 140
        maximum = max(e for _, e in section)
        x_min, x_max = section[0][0], section[-1][0]
        coords = []
        for x, e in section:
            coords.extend((left + (x - x_min) / (x_max - x_min) * (right - left),
                           bottom - e / maximum * (bottom - top)))
        canvas.create_line(left, top, left, bottom, right, bottom)
        canvas.create_line(*coords, fill="blue")
        canvas.create_text(left - 5, top, text=f"{maximum:.3g}", anchor="e")
        canvas.create_text(left - 5, bottom, text="0", anchor="e")
        canvas.create_text(left, bottom + 15, text=f"{x_min:g}")
        canvas.create_text(right, bottom + 15, text=f"{x_max:g}")
        canvas.create_text((left + right) / 2, bottom + 15, text="x, мм")
        canvas.create_text(left, 9, text="E, Вт/м²", anchor="w")

    def save(self):
        if self.png_data is None:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".png",
                                            initialfile="illumination.png", filetypes=[("PNG", "*.png")])
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
