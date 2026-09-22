"""Shot 狀態 → MiniMax H3 英文提示詞。

英文提示詞效果比中文好（AIGF-V2 教學實測）。遊戲背景圖多是歐洲街景 stock 圖，
跟台中舊城不符，所以預設 source=t2v：第一段 clip 用文生影片，
短鏡頭（< CUT_MIN_PARTS 段）以前一段最後一幀接續；長鏡頭改成同場景換角度（ReferenceToVideo）。
"""
from __future__ import annotations

from vns_shots import Shot

STYLE = ("Slow-burn Taiwanese folk horror film, 35mm film grain, muted desaturated palette, "
         "low-key lighting, underexposed, deep shadows, damp humid air. Slow deliberate camera, no fast cuts. "
         "No people visible, no faces, no on-screen text, no subtitles, no watermark.")

# source: t2v = 文生影片開場；bg = 用遊戲背景圖當首幀
SCENES: dict[str, dict] = {
    "old_city_dusk": {
        "source": "t2v",
        "look": ("A narrow alley in the old downtown of Taichung, Taiwan at late dusk, dark blue-hour sky, most shops already closed: worn 1970s concrete "
                 "shophouses with rusted iron window grilles, arcade walkways (qilou), parked scooters, "
                 "tangled power lines, a traditional market pulling down its metal shutters, puddles on "
                 "cracked asphalt reflecting sodium streetlights."),
        "camera": "Slow push-in along the alley at eye level.",
        "audio": "distant market metal shutters rolling down, scooter passing far away, low city hum",
    },
    "shrine_interior": {
        "source": "t2v",
        "look": ("Inside a cramped old Taoist altar room in a Taiwanese back alley: low ceiling, "
                 "red altar table with incense burner and thin smoke, faded deity paintings, "
                 "a fluorescent tube light, walls stained with pale salt efflorescence spreading "
                 "up from damp corners like old scars, a wooden table with an old swollen paper file."),
        "camera": "Static tripod shot with a very slow drift toward the altar.",
        "audio": "quiet room tone, incense crackle, faint dripping water",
    },
    "city_historical": {
        "source": "bg",
        "look": ("An old hand-drawn Qing dynasty ink map on aged paper, a river line crossing the "
                 "villages, paper fibers and stains."),
        "camera": "Slow top-down pan across the paper map, ink lines of the river subtly darkening as if wet.",
        "audio": "paper rustle, faint flowing water under silence",
    },
    "archive_room": {
        "source": "t2v",
        "look": ("A damp municipal archive storeroom in Taiwan: metal shelves of water-damaged folders, "
                 "brown-stained paper edges, a single bare bulb, mold on the concrete wall."),
        "camera": "Slow lateral dolly past the shelves.",
        "audio": "paper pages turning, distant water under the floor",
    },
    "shrine_entrance_night": {
        "source": "t2v",
        "look": ("The entrance of a small old Taiwanese temple at night: stone lions, red lanterns "
                 "swaying, wet stone steps, a flooded alley gutter where black water flows into a grate."),
        "camera": "Low angle slow push toward the dark doorway.",
        "audio": "heavy rain, wind, lantern creaking",
    },
    "underground_river": {
        "source": "t2v",
        "look": ("A buried culvert river under the city: a dark concrete box tunnel, black water "
                 "flowing slowly, old brick arches from the Japanese colonial era, a faint light far "
                 "down the tunnel."),
        "camera": "Slow glide forward just above the water surface.",
        "audio": "echoing flowing water, a wooden oar creaking somewhere in the dark",
    },
}

# 長鏡頭（CUT_MIN_PARTS 段以上）第 2 段起改成「同一場景換角度」，避免同一個固定畫面撐一分鐘。
# 每個角度以該 shot 第一段的畫面當參考圖（<Picture 1>），維持房間長相一致。
CUT_MIN_PARTS = 4
ANGLES: dict[str, list[str]] = {
    "shrine_interior": [
        "Extreme close-up of the incense burner on the altar, thin smoke curling upward. Very slow push-in.",
        "Close-up of the pale salt stains spreading across the damp wall like old scars. Slow tilt upward.",
        "View through the rain-streaked window toward the dark alley outside, droplets sliding down the glass.",
        "Top-down close-up of the old swollen paper file on the wooden table, brown water-stained edges. Slow drift.",
        "Low angle from the floor looking up at the fluorescent tube on the low ceiling, dust in the air.",
        "Close-up of the faded deity paintings above the altar, candle light trembling across their faces.",
    ],
    "archive_room": [
        "Close-up of water-damaged folders on a metal shelf, brown stains creeping across the paper. Slow lateral move.",
        "The single bare bulb swaying slightly on its wire, shadows of the shelves sliding across the wall.",
        "A drop of water falling from the ceiling onto an open folder, ink bleeding. Macro shot.",
        "Low angle across the wet concrete floor between the shelves, a thin film of water reflecting the bulb.",
    ],
    "shrine_entrance_night": [
        "Close-up of red lanterns swaying violently in the wind and rain, light flickering.",
        "Close-up of a stone lion's face streaming with rain water, eyes in deep shadow.",
        "Black water rushing along the alley gutter and disappearing into an iron grate. Low angle.",
        "Slow push toward the pitch-dark temple doorway, rain curtain in front of it.",
        "The temple roof ridge against a stormy night sky, lightning briefly lighting the clouds.",
        "Close-up of wet stone steps, rain water pooling and trembling on each step.",
    ],
    "old_city_dusk": [
        "Close-up of iron window grilles with rust streaks, rain dripping from them.",
        "A market vendor's metal shutter half-closed, dim light leaking from underneath. Low angle.",
        "Puddle on the asphalt reflecting a flickering sodium streetlight, ripples from drizzle.",
    ],
    "underground_river": [
        "Close-up of black water flowing slowly past old brick, debris drifting.",
        "Looking up at the concrete ceiling of the culvert, water stains and roots growing through cracks.",
        "A faint light far down the tunnel, reflecting on the black water surface.",
    ],
}

RAIN = {
    "none": "",
    "drizzle": "A fine drizzle drifts through the light.",
    "light": "Light rain falls outside, drops sliding down the window.",
    "heavy": "Heavy rain pours down, sheets of water, gutters overflowing.",
}

SFX = {
    "market_closing": "market metal shutters slamming closed one after another",
    "footsteps_puddle": "plastic slippers splashing through a puddle",
    "paper_rustle": "old damp paper pages rustling",
    "oar_creak": "a wooden oar creaking in dark water",
    "water_distant": "the low rumble of water flowing somewhere beneath the floor",
    "rain_heavy": "heavy rain drumming on tin roofs",
    "power_failure": "an electrical buzz then a sudden power cut",
    "thunder_crack": "a distant thunder crack",
}


def source_of(shot: Shot) -> str:
    return SCENES.get(shot.bg, {}).get("source", "bg")


def is_cut(shot: Shot, part: int, parts: int) -> bool:
    """這一段是否用「同場景換角度」而不是接續前一段。"""
    return part > 0 and parts >= CUT_MIN_PARTS and bool(ANGLES.get(shot.bg))


def build(shot: Shot, part: int, parts: int, revisit: int = 0) -> str:
    """revisit：同一場景第幾次出現（0 = 第一次）。重訪時第一段也參考第一次的畫面，
    換角度的起點也錯開，避免三場道壇戲的鏡頭順序一模一樣。"""
    sc = SCENES.get(shot.bg, {"look": shot.bg.replace("_", " "), "camera": "Slow push-in.", "audio": "room tone"})
    cut = is_cut(shot, part, parts)
    camera = sc["camera"]
    if cut:
        angles = ANGLES[shot.bg]
        camera = angles[(part - 1 + revisit * 2) % len(angles)]
    visual = [sc["look"], RAIN.get(shot.rain, "")]
    if cut:
        visual.insert(0, "The same place as <Picture 1>, same materials, colors and lighting, but a new camera angle.")
    elif part == 0 and revisit > 0:
        visual.insert(0, "Return to the same place as <Picture 1>, same materials, colors and layout.")
    if shot.dim >= 0.4:
        visual.append("The light gradually dims until the scene is almost dark, only faint highlights remain.")
    elif shot.dim > 0:
        visual.append("Dim, underexposed lighting.")
    if shot.flicker:
        visual.append("The fluorescent light flickers twice.")
    if shot.vignette:
        visual.append("Heavy dark vignette at the frame edges.")
    if shot.shake:
        visual.append("A brief subtle camera shake.")
    if part > 0 and not cut:
        visual.insert(0, "Continue the same shot seamlessly from the first frame, same place, same lighting.")

    audio = [sc["audio"]]
    audio += [SFX[s] for s in shot.sfx if s in SFX]
    if shot.rain in ("light", "drizzle"):
        audio.append("soft rain")
    audio_line = ("Audio: " + ", ".join(dict.fromkeys(a for a in audio if a)) +
                  ". No music, no speech, no voices.")

    return "\n\n".join([STYLE, " ".join(v for v in visual if v), camera, audio_line])
