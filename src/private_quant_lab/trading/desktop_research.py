"""只读桌面研究：参考图定位、单次点击、页面后置校验。不提供交易操作。"""

import json
from pathlib import Path
import time


REFERENCES = ("holdings_tab", "holdings_view", "export_button", "export_dialog")
ACTIONS = {"holdings_tab": "holdings_view", "export_button": "export_dialog"}


class DesktopResearchError(RuntimeError):
    pass


def validate_reference(value):
    """输入本地标定信息；拒绝越界区域和不受支持的动作名称。"""
    if not isinstance(value, dict) or value.get("name") not in REFERENCES:
        raise DesktopResearchError("unsupported reference")
    size, region = value.get("screen_size"), value.get("region")
    if not isinstance(size, list) or len(size) != 2 or not isinstance(region, list) or len(region) != 4:
        raise DesktopResearchError("invalid screen size or region")
    if any(type(n) is not int for n in size + region):
        raise DesktopResearchError("coordinates must be integers")
    x, y, w, h = region
    if min(size) <= 0 or min(x, y) < 0 or min(w, h) < 8 or x + w > size[0] or y + h > size[1]:
        raise DesktopResearchError("region outside primary display or too small")
    return value


def load_reference(directory, name):
    if name not in REFERENCES:
        raise DesktopResearchError("unsupported reference")
    try:
        value = validate_reference(json.loads((Path(directory) / (name + ".json")).read_text()))
    except (OSError, ValueError) as exc:
        raise DesktopResearchError("missing or invalid calibration: " + name) from exc
    if value["name"] != name:
        raise DesktopResearchError("reference name mismatch")
    return value


class PyAutoGUIDesktop:
    """依赖延迟加载，离线测试及 --help 不访问桌面。仅支持主显示器。"""

    def __init__(self, directory):
        try:
            import pyautogui
            from PIL import Image
        except ImportError as exc:
            raise DesktopResearchError("install desktop-research extra first") from exc
        self.gui, self.Image, self.directory = pyautogui, Image, Path(directory)
        self.gui.FAILSAFE = True
        self.gui.PAUSE = 0.2

    def frame(self):
        self.gui.failSafeCheck()
        size = tuple(self.gui.size())
        frame = self.gui.screenshot().convert("RGB")
        # Retina 截图像素与鼠标逻辑坐标可能为 2:1，标定和匹配统一使用逻辑坐标。
        if frame.size != size:
            sx, sy = frame.width / size[0], frame.height / size[1]
            if abs(sx - sy) > 0.01 or sx < 1:
                raise DesktopResearchError("unsupported display scaling; use primary display only")
            frame = frame.resize(size, self.Image.Resampling.LANCZOS)
        return frame

    def capture(self, name, region):
        frame = self.frame()
        value = validate_reference({"name": name, "screen_size": list(frame.size), "region": list(region)})
        x, y, w, h = region
        cropped = frame.crop((x, y, x + w, y + h))
        if max(high - low for low, high in cropped.getextrema()) < 20:
            raise DesktopResearchError("reference is blank or lacks contrast")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        png, meta = self.directory / (name + ".png"), self.directory / (name + ".json")
        if png.exists() or meta.exists():
            raise DesktopResearchError("reference exists; use a new calibration directory")
        with png.open("xb") as stream:
            cropped.save(stream, format="PNG")
        png.chmod(0o600)
        with meta.open("x") as stream:
            json.dump(value, stream)
        meta.chmod(0o600)
        return value

    def locate(self, reference):
        validate_reference(reference)
        frame = self.frame()
        if list(frame.size) != reference["screen_size"]:
            raise DesktopResearchError("display size changed; recalibrate")
        with self.Image.open(self.directory / (reference["name"] + ".png")) as image:
            needle = image.convert("RGB")
        x, y, w, h = reference["region"]
        if needle.size != (w, h):
            raise DesktopResearchError("template size mismatch")
        left, top = max(0, x - 24), max(0, y - 24)
        right, bottom = min(frame.width, x + w + 24), min(frame.height, y + h + 24)
        area = frame.crop((left, top, right, bottom))
        # 精确彩色匹配，不依赖 OpenCV 阈值；找不到或多处匹配都停止。
        matches = []
        from PIL import ImageChops
        for dy in range(area.height - h + 1):
            for dx in range(area.width - w + 1):
                if area.getpixel((dx, dy)) != needle.getpixel((0, 0)):
                    continue
                crop = area.crop((dx, dy, dx + w, dy + h))
                if ImageChops.difference(needle, crop).getbbox() is None:
                    matches.append((left + dx + w // 2, top + dy + h // 2))
                    if len(matches) == 2:
                        return matches
        return matches

    def click(self, point):
        self.gui.click(*point, clicks=1, button="left")


def run_step(desktop, target, expected, guard=None, execute=False, confirm=None,
             timeout=5.0, clock=time.monotonic, sleep=time.sleep):
    """默认预览；显式执行时再次定位，最多点击一次，不发送按键、不重试点击。

    输出仅包含步骤、坐标与状态；截图及账户内容不进入结果。
    """
    validate_reference(target)
    validate_reference(expected)
    name = target["name"]
    if ACTIONS.get(name) != expected["name"]:
        raise DesktopResearchError("unsupported read-only transition")
    if not 0 < timeout <= 30:
        raise DesktopResearchError("timeout must be between 0 and 30 seconds")
    if name == "export_button":
        if guard is None or guard.get("name") != "holdings_view":
            raise DesktopResearchError("export requires holdings page guard")
        validate_reference(guard)
    if len(desktop.locate(expected)):
        raise DesktopResearchError("destination already visible; no click needed")

    def locate_target():
        if guard is not None and len(desktop.locate(guard)) != 1:
            raise DesktopResearchError("holdings page guard not uniquely matched")
        points = desktop.locate(target)
        if len(points) != 1:
            raise DesktopResearchError("target not uniquely matched; no click")
        return points[0]

    point = locate_target()
    result = {"step": name, "point": list(point), "status": "preview", "clicks": 0}
    if not execute:
        return result
    if confirm is None or not confirm(name, point):
        raise DesktopResearchError("execution not confirmed; no click")
    if len(desktop.locate(expected)) or locate_target() != point:
        raise DesktopResearchError("screen changed after confirmation; no click")
    desktop.click(point)
    deadline = clock() + timeout
    while clock() < deadline:
        matches = desktop.locate(expected)
        if len(matches) == 1:
            return dict(result, status="verified", clicks=1)
        if len(matches) > 1:
            raise DesktopResearchError("clicked once; destination ambiguous; do not blindly retry")
        sleep(0.25)
    raise DesktopResearchError("clicked once; destination not verified; inspect manually, do not retry")
