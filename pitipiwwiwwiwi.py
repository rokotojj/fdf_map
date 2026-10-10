import math
import string
import sys
import tkinter as tk
from operator import itemgetter
from pathlib import Path

MAP_PATH = "swap.fdf"

LINE_COLOR = "#FFFFFF"
BACKGROUND = "#000000"
COS30 = math.cos(math.radians(30))
DEFAULT_TILT = math.degrees(math.atan(1 / math.sqrt(2)))
DEGREES_PER_PIXEL = 0.5
ZOOM_STEP = 1.15


class FdfError(Exception):
    pass


class MapFormatError(FdfError):
    def __init__(self, line: int, column: int, reason: str) -> None:
        super().__init__(f"строка {line}, колонка {column}: {reason}")


def parse_color(text: str) -> str:
    digits = text[2:]
    if text[:2].lower() != "0x" or not 1 <= len(digits) <= 6:
        raise ValueError(text)
    if not all(c in string.hexdigits for c in digits):
        raise ValueError(text)
    return f"#{int(digits, 16):06X}"


def parse_map(path: Path) -> tuple[int, int, list[int], list[str | None]]:
    with open(path, encoding="utf-8-sig") as file:
        lines = file.read().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise MapFormatError(1, 1, "файл пуст")

    width = len(lines[0].split())
    heights: list[int] = []
    colors: list[str | None] = []
    for y, line in enumerate(lines, start=1):
        tokens = line.split()
        if len(tokens) != width:
            reason = f"значений {len(tokens)}, а в первой строке {width}"
            raise MapFormatError(y, min(len(tokens), width) + 1, reason)
        for x, token in enumerate(tokens, start=1):
            z, comma, color = token.partition(",")
            try:
                heights.append(int(z))
                colors.append(parse_color(color) if comma else None)
            except ValueError:
                raise MapFormatError(y, x, f"'{token}' - неверное значение")
    return width, len(lines), heights, colors


class App:
    def __init__(self, width: int, height: int, heights: list[int], colors: list[str | None]):
        self.root = tk.Tk()
        self.root.title(f"FdF - {MAP_PATH}")
        self.root.geometry("1000x750")
        self.canvas = tk.Canvas(self.root, background=BACKGROUND, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        cx, cy = (width - 1) / 2, (height - 1) / 2
        self.dx = [x - cx for y in range(height) for x in range(width)]
        self.dy = [y - cy for y in range(height) for x in range(width)]
        self.z = heights

        order = [y * width + x for x in range(width) for y in range(height)]
        self.by_columns = itemgetter(*[j for i in order for j in (2 * i, 2 * i + 1)])

        self.row_lines = self.make_lines(colors, width, height)
        self.column_lines = self.make_lines([colors[i] for i in order], height, width)

        self.angle = 0.0
        self.scale = 1.0
        self.zoom = 1.0
        self.tilt = DEFAULT_TILT
        self.drag_x = self.drag_y = 0
        self.drag_angle = self.drag_tilt = 0.0
        self.pending = False
        self.canvas.bind("<Configure>", self.fit)
        self.root.bind("<Escape>", lambda event: self.root.destroy())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.fit)
        self.canvas.bind("<MouseWheel>", self.on_wheel)

    def make_lines(
        self, colors: list[str | None], length: int, count: int
    ) -> list[tuple[int, int, int]]:
        lines = []
        for first in range(0, length * count, length):
            last = first + length - 1
            start = first
            for i in range(first + 1, last + 1):
                if colors[i] != colors[start] or i == last:
                    item = self.canvas.create_line(0, 0, 0, 0, fill=colors[start] or LINE_COLOR)
                    lines.append((item, 2 * start, 2 * i + 2))
                    start = i
        return lines

    def project(self, scale: float) -> tuple[list[float], list[float]]:
        a = math.radians(self.angle)
        c, s = math.cos(a), math.sin(a)
        t = math.radians(self.tilt)
        depth = COS30 * math.sin(t) * scale
        ax, ay = COS30 * (c - s) * scale, -COS30 * (c + s) * scale
        bx, by = depth * (c + s), depth * (c - s)
        k = math.sqrt(2) * COS30 * math.cos(t) * scale
        xs = [ax * dx + ay * dy for dx, dy in zip(self.dx, self.dy)]
        ys = [bx * dx + by * dy - k * z for dx, dy, z in zip(self.dx, self.dy, self.z)]
        return xs, ys

    def fit(self, event: object = None) -> None:
        xs, ys = self.project(1.0)
        span_x = (max(xs) - min(xs)) or 1
        span_y = (max(ys) - min(ys)) or 1
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.scale = 0.9 * min(width / span_x, height / span_y)
        self.schedule_redraw()

    def on_press(self, event: "tk.Event[tk.Canvas]") -> None:
        self.drag_x, self.drag_y = event.x, event.y
        self.drag_angle, self.drag_tilt = self.angle, self.tilt

    def on_drag(self, event: "tk.Event[tk.Canvas]") -> None:
        angle = self.drag_angle + (event.x - self.drag_x) * DEGREES_PER_PIXEL
        self.angle = angle % 360
        tilt = self.drag_tilt + (self.drag_y - event.y) * DEGREES_PER_PIXEL
        self.tilt = min(max(tilt, 0.0), 90.0)
        self.schedule_redraw()

    def on_wheel(self, event: "tk.Event[tk.Canvas]") -> None:
        if event.delta > 0:
            self.zoom *= ZOOM_STEP
        elif event.delta < 0:
            self.zoom /= ZOOM_STEP
        self.schedule_redraw()

    def schedule_redraw(self) -> None:
        if not self.pending:
            self.pending = True
            self.root.after_idle(self.redraw)

    def redraw(self) -> None:
        self.pending = False
        xs, ys = self.project(self.scale * self.zoom)
        flat = [0.0] * (2 * len(xs))
        flat[0::2] = xs
        flat[1::2] = ys
        columns = self.by_columns(flat)
        set_coords = self.canvas.coords
        for item, start, end in self.row_lines:
            set_coords(item, flat[start:end])
        for item, start, end in self.column_lines:
            set_coords(item, columns[start:end])
        shift_x = self.canvas.winfo_width() / 2 - (min(xs) + max(xs)) / 2
        shift_y = self.canvas.winfo_height() / 2 - (min(ys) + max(ys)) / 2
        self.canvas.move("all", shift_x, shift_y)


def main() -> int:
    path = Path(__file__).resolve().parent / MAP_PATH
    try:
        width, height, heights, colors = parse_map(path)
    except OSError as error:
        print(f"{path}: {error.strerror}", file=sys.stderr)
        return 1
    except (FdfError, UnicodeDecodeError) as error:
        print(f"{path}: {error}", file=sys.stderr)
        return 1
    App(width, height, heights, colors).root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())