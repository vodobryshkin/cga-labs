import base64
import math
from pathlib import Path
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import zlib
import core

FIELDS = (
    ("w", "Ширина W, мм", "2000"),
    ("h", "Высота H, мм", "2000"),
    ("w_res", "Ширина, пиксели", "400"),
    ("h_res", "Высота, пиксели", "400"),
    ("xl", "Источник xL, мм", "0"),
    ("yl", "Источник yL, мм", "0"),
    ("zl", "Источник zL, мм", "1000"),
    ("i0", "I0, Вт/ср", "1"),
    ("xc", "Центр круга x, мм", "0"),
    ("yc", "Центр круга y, мм", "0"),
    ("r", "Радиус круга, мм", "800"),
)


def read_parameters(values):
    numbers = {}
    labels = {key: label for key, label, _ in FIELDS}
    for key in labels:
        value = values[key].strip().replace(",", ".")
        try:
            number = int(value) if key in ("w_res", "h_res") else float(value)
        except ValueError as exc:
            raise ValueError(f"{labels[key]}: введите число.") from exc
        if not math.isfinite(number):
            raise ValueError(f"{labels[key]}: число должно быть конечным.")
        numbers[key] = number

    for key in ("w", "h"):
        if not 100 <= numbers[key] <= 10000:
            raise ValueError(f"{labels[key]}: допустимо от 100 до 10000 мм.")
    for key in ("w_res", "h_res"):
        if not 200 <= numbers[key] <= 800:
            raise ValueError(f"{labels[key]}: допустимо от 200 до 800 пикселей.")
    for key in ("xl", "yl"):
        if not -10000 <= numbers[key] <= 10000:
            raise ValueError(f"{labels[key]}: допустимо от −10000 до 10000 мм.")
    if not 100 <= numbers["zl"] <= 10000:
        raise ValueError("Высота источника zL: допустимо от 100 до 10000 мм.")
    if not 0.01 <= numbers["i0"] <= 10000:
        raise ValueError("I0: допустимо от 0,01 до 10000 Вт/ср.")

    x_step = numbers["h"] / numbers["h_res"]
    y_step = numbers["w"] / numbers["w_res"]
    if not math.isclose(x_step, y_step, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError(
            "Нужны квадратные пиксели: H / высота в пикселях "
            "должно равняться W / ширина в пикселях."
        )
    if numbers["r"] <= 0:
        raise ValueError("Радиус круга должен быть больше нуля.")
    if (abs(numbers["xc"]) + numbers["r"] > numbers["h"] / 2
            or abs(numbers["yc"]) + numbers["r"] > numbers["w"] / 2):
        raise ValueError("Круг должен целиком помещаться внутри прямоугольника W × H.")
    return numbers


def png_chunk(kind, payload):
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def grayscale_png(width, height, pixels):
    rows = bytearray()
    for row in range(height):
        rows.append(0)  # PNG filter: none
        rows.extend(pixels[row * width:(row + 1) * width])
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", header)
            + png_chunk(b"IDAT", zlib.compress(rows))
            + png_chunk(b"IEND", b""))


def calculate(params):
    p = params
    points = core.calc_all_points_in_the_circle(
        p["xc"], p["yc"], p["r"], p["w"], p["h"], p["w_res"], p["h_res"]
    )
    if not points:
        raise ValueError("В круг не попал центр ни одного пикселя. Увеличьте радиус или разрешение.")

    irradiance = core.calc_e_for_all_points(p["i0"], p["xl"], p["yl"], p["zl"], points)
    gray = core.convert_e_to_g(irradiance)
    samples = list(irradiance.values())
    stats = (min(samples), max(samples), sum(samples) / len(samples))

    pixels = bytearray(p["w_res"] * p["h_res"])
    dx, dy = p["h"] / p["h_res"], p["w"] / p["w_res"]
    for i in range(p["h_res"]):
        x = (-p["h"] / 2) + (i + 0.5) * dx
        row_start = i * p["w_res"]
        for j in range(p["w_res"]):
            y = (-p["w"] / 2) + (j + 0.5) * dy
            pixels[row_start + j] = gray.get((x, y), 0)

    xc, yc, r = p["xc"], p["yc"], p["r"]
    locations = (
        ("Центр", xc, yc),
        ("−X", xc - r, yc),
        ("+X", xc + r, yc),
        ("−Y", xc, yc - r),
        ("+Y", xc, yc + r),
    )
    five_points = [
        (name, x, y, core.calc_e(p["i0"], p["xl"], p["yl"], p["zl"], x, y))
        for name, x, y in locations
    ]
    section = [
        (xc - r + 2 * r * k / 300,
         core.calc_e(p["i0"], p["xl"], p["yl"], p["zl"], xc - r + 2 * r * k / 300, yc))
        for k in range(301)
    ]
    return grayscale_png(p["w_res"], p["h_res"], pixels), stats, five_points, section


class LabWindow:
    def __init__(self, root):
        self.root = root
        root.minsize(960, 700)
        self.png_data = None
        self.photo = None
        self.preview = None
        self.values = {}

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        form = ttk.LabelFrame(main, text="Параметры", padding=10)
        form.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        for row, (key, label, default) in enumerate(FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            variable = tk.StringVar(value=default)
            ttk.Entry(form, textvariable=variable, width=12).grid(row=row, column=1, pady=3, padx=(8, 0))
            self.values[key] = variable

        ttk.Button(form, text="Рассчитать", command=self.run).grid(
            row=len(FIELDS), column=0, columnspan=2, sticky="ew", pady=(16, 5)
        )
        self.save_button = ttk.Button(form, text="Сохранить PNG…", command=self.save, state="disabled")
        self.save_button.grid(row=len(FIELDS) + 1, column=0, columnspan=2, sticky="ew")
        self.status = tk.StringVar(value="Задайте параметры и нажмите «Рассчитать».")
        ttk.Label(form, textvariable=self.status, wraplength=225).grid(
            row=len(FIELDS) + 2, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        tabs = ttk.Notebook(main)
        tabs.grid(row=0, column=1, sticky="nsew")
        image_tab = ttk.Frame(tabs, padding=10)
        result_tab = ttk.Frame(tabs, padding=10)
        tabs.add(image_tab, text="Изображение")
        tabs.add(result_tab, text="Сечение и значения")

        self.image_label = ttk.Label(image_tab, text="Изображение появится после расчёта")
        self.image_label.pack(expand=True)
        self.image_size = ttk.Label(image_tab, text="")
        self.image_size.pack(anchor="w")

        self.graph = tk.Canvas(result_tab, width=620, height=285, bg="white", highlightthickness=1,
                               highlightbackground="#b8b8b8")
        self.graph.pack(fill="x")
        self.stats_label = ttk.Label(result_tab, text="", justify="left")
        self.stats_label.pack(anchor="w", pady=(12, 8))
        self.table = ttk.Treeview(result_tab, columns=("point", "x", "y", "e"), show="headings", height=5)
        for key, title, width in (
            ("point", "Точка", 100), ("x", "x, мм", 115),
            ("y", "y, мм", 115), ("e", "E, Вт/м²", 150)
        ):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, anchor="center")
        self.table.pack(fill="x")
        ttk.Label(result_tab, text="−X, +X, −Y, +Y — края круга по осям через его центр.").pack(
            anchor="w", pady=(8, 0)
        )

        for variable in self.values.values():
            variable.trace_add("write", self.invalidate)

    def invalidate(self, *_):
        self.png_data = None
        self.photo = None
        self.preview = None
        self.save_button.configure(state="disabled")
        self.image_label.configure(image="", text="Нажмите «Рассчитать» для новых параметров")
        self.image_size.configure(text="")
        self.graph.delete("all")
        self.stats_label.configure(text="")
        for item in self.table.get_children():
            self.table.delete(item)
        self.status.set("Параметры изменены. Рассчитайте снова.")

    def run(self):
        try:
            params = read_parameters({key: var.get() for key, var in self.values.items()})

            self.invalidate()
            self.status.set("Расчёт…")
            self.root.update_idletasks()

            png_data, stats, locations, section = calculate(params)

            photo = tk.PhotoImage(data=base64.b64encode(png_data).decode("ascii"), format="png")
            factor = max(1, math.ceil(params["w_res"] / 630), math.ceil(params["h_res"] / 530))
            self.photo = photo
            self.preview = photo.subsample(factor, factor) if factor > 1 else photo

            self.image_label.configure(image=self.preview, text="")
            self.image_size.configure(text=f"Полный размер: {params['w_res']} × {params['h_res']} пикселей")
            self.stats_label.configure(text=(f"Внутри круга: минимум {stats[0]:.6g}, максимум {stats[1]:.6g}, среднее {stats[2]:.6g} Вт/м²"))

            for item in self.table.get_children():
                self.table.delete(item)

            for name, x, y, e in locations:
                self.table.insert("", "end", values=(name, f"{x:.6g}", f"{y:.6g}", f"{e:.6g}"))


            self.draw_section(section, params["yc"])
            self.png_data = png_data
            self.save_button.configure(state="normal")
            self.status.set("Готово. Можно сохранить изображение.")

        except (ValueError, ArithmeticError, tk.TclError) as exc:
            self.status.set("Исправьте параметры или повторите расчёт.")
            messagebox.showerror("Не удалось рассчитать", str(exc), parent=self.root)

    def draw_section(self, section, fixed_y):
        canvas = self.graph
        canvas.delete("all")

        width = int(canvas["width"])
        height = int(canvas["height"])
        left, right, top, bottom = 70, width - 18, 26, height - 46

        canvas.create_line(left, top, left, bottom, right, bottom, fill="#333333")

        x_min, x_max = section[0][0], section[-1][0]
        y_max = max(value for _, value in section)
        coords = []

        for x, e in section:
            coords.extend((left + (x - x_min) / (x_max - x_min) * (right - left),
                           bottom - e / y_max * (bottom - top)))

        canvas.create_line(*coords, fill="#2f658a", width=2)

        for x, anchor in ((left, "w"), ((left + right) / 2, "center"), (right, "e")):
            value = x_min + (x - left) / (right - left) * (x_max - x_min)
            canvas.create_text(x, bottom + 14, text=f"{value:.6g}", anchor=anchor)

        canvas.create_text(left - 8, top, text=f"{y_max:.3g}", anchor="e")
        canvas.create_text(left - 8, bottom, text="0", anchor="e")
        canvas.create_text((left + right) / 2, height - 12, text=f"x, мм (сечение при y = {fixed_y:g} мм)")
        canvas.create_text(left, 10, text="E, Вт/м²", anchor="w")

    def save(self):
        if self.png_data is None:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".png", initialfile="illumination.png", filetypes=[("PNG", "*.png")])
        if not path:
            return
        try:
            Path(path).write_bytes(self.png_data)
        except OSError as exc:
            messagebox.showerror("Не удалось сохранить", str(exc), parent=self.root)
        else:
            self.status.set(f"Сохранено: {path}")


if __name__ == "__main__":
    window = tk.Tk()
    LabWindow(window)
    window.mainloop()
