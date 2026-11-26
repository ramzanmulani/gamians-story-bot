"""Daily game spotlight: one different game a day -> Instagram feed, Facebook Page, Threads.

    python scripts/spotlight.py            (DRY_RUN=1 renders + prints, publishes nothing)

The game list, blurb and banner come from the live site (gamians.com/assets/games-index.json and each
game page's og: tags), so a game added to the site joins the line-up with no edit here. Newest games go
first; after that it is a shuffle bag, so every game is used once before any repeats.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from common import LOG, REPO_ROOT, ConfigError, env_flag, http_request, load_config, read_json, require_env, write_json

SITE = "https://gamians.com"
STATE = REPO_ROOT / "state" / "spotlight.json"
THREADS_STORE = REPO_ROOT / "state" / "threads_token.enc"
GRAPH = "https://graph.facebook.com/v21.0"
THREADS = "https://graph.threads.net/v1.0"

LABELS = ["GAME OF THE DAY", "TODAY'S CHAOS", "PLAY THIS NOW", "FREE GAME ALERT", "TRY NOT TO LAUGH", "NEW HIGH SCORE?"]
OPENERS = [
    "Today's pick is {t}, and it will happily eat your whole lunch break.",
    "Warning: {t} may cause loud laughing on public transport.",
    "Your boss is in a meeting. Perfect time for {t}.",
    "{t}: zero downloads, zero sign-ups, maximum nonsense.",
    "Bored? {t} has entered the chat.",
    "Doctors recommend one round of {t} a day. (They don't. But they should.)",
    "If you only play one game today, make it {t}. If you play two, also {t}.",
    "{t} is free, it runs on your phone, and it is very, very silly.",
    "Plot twist: {t} is harder than it looks. Prove us wrong.",
    "Tag the friend who would lose at {t} in ten seconds.",
    "Five minutes of {t}. That's the plan. (It is never five minutes.)",
    "Fresh off the Gamians shelf: {t}.",
]
CLOSERS = [
    "Play free in your browser, no download.",
    "Free on phone and PC, straight in the browser.",
    "No app, no sign-up, just press play.",
    "Works on phone and PC. Free forever.",
]
TAGS = ["#gamians", "#browsergames", "#freegames", "#indiegames", "#mobilegames", "#casualgames",
        "#html5games", "#gamingmemes", "#indiegame", "#playnow", "#webgames", "#gamedev"]


# ---------------------------------------------------------------- site data

def site_games(exclude: set[str]) -> list[str]:
    resp = http_request("GET", f"{SITE}/assets/games-index.json")
    idx = resp.json()
    return [s for s in idx if s not in exclude]


def game_info(slug: str) -> dict:
    page = http_request("GET", f"{SITE}/games/{slug}/").text
    meta = {m.group(1): html.unescape(m.group(2)) for m in re.finditer(r'<meta property="og:(\w+)" content="([^"]*)"', page)}
    title = re.sub(r"^Play\s+|\s+Free Online.*$|\s*\|\s*Gamians$", "", meta.get("title", slug)).strip()
    if not meta.get("image"):
        raise RuntimeError(f"{slug}: game page has no og:image")
    return {"slug": slug, "title": title, "blurb": meta.get("description", ""), "image": meta["image"],
            "url": f"{SITE}/games/{slug}/"}


# ---------------------------------------------------------------- picking

def pick(state: dict, games: list[str]) -> str:
    seen = set(state.setdefault("seen", []))
    new = [g for g in games if g not in seen]
    bag = [g for g in state.get("bag", []) if g in games]
    if not state.get("seen"):            # first run: the newest 8 lead, the rest shuffled
        rest = games[:-8]
        random.shuffle(rest)
        bag = list(reversed(games[-8:])) + rest
    else:
        bag = list(reversed(new)) + bag  # a game added to the site jumps the queue
    if not bag:
        recent = [p["slug"] for p in state.get("posted", [])[-10:]]
        bag = [g for g in games if g not in recent] or list(games)
        random.shuffle(bag)
    state["seen"] = sorted(seen | set(games))
    slug = bag.pop(0)
    state["bag"] = bag
    return slug


# ---------------------------------------------------------------- card image

def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise ConfigError("No bold font found for the post card (needs DejaVuSans-Bold).")


def _wrap(d: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while d.textlength(lines[-1] + "...", font=font) > width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "..."
    return [l for l in lines if l]


def render_card(info: dict, label: str, out: Path) -> Path:
    raw = http_request("GET", info["image"]).content
    ban = Image.open(io.BytesIO(raw)).convert("RGB")
    W, H = 1080, 1350
    avg = ban.resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    top = tuple(int(c * .55) for c in avg)
    bg = Image.new("RGB", (W, H))
    for y in range(H):
        k = y / H
        bg.paste(tuple(int(top[i] * (1 - k) + 12 * k) for i in range(3)), (0, y, W, y + 1))
    blur = ban.resize((W, int(W * ban.height / ban.width))).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, blur.resize((W, H)), .25)
    d = ImageDraw.Draw(bg)

    f_lab = _font(46)
    lw = d.textlength(label, font=f_lab)
    d.rounded_rectangle(((W - lw) / 2 - 34, 70, (W + lw) / 2 + 34, 150), 40, fill=(255, 210, 31))
    d.text((W / 2, 110), label, font=f_lab, fill=(26, 13, 0), anchor="mm")

    bw = 1000
    bh = int(bw * ban.height / ban.width)
    pic = ban.resize((bw, bh), Image.LANCZOS)
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw, bh), 36, fill=255)
    by = 200
    d.rounded_rectangle((40 - 8, by - 8, 40 + bw + 8, by + bh + 8), 44, fill=(255, 255, 255))
    bg.paste(pic, (40, by), mask)

    y = by + bh + 40
    size = 92
    while size > 54:
        f_t = _font(size)
        lines = _wrap(d, info["title"].upper(), f_t, 980, 2)
        if not lines[-1].endswith("..."):
            break
        size -= 8
    for l in lines:
        d.text((W / 2, y), l, font=f_t, fill="white", anchor="ma", stroke_width=6, stroke_fill=(20, 10, 0))
        y += int(size * 1.12)
    f_b = _font(40)
    y += 14
    for l in _wrap(d, info["blurb"], f_b, 960, 3):
        d.text((W / 2, y), l, font=f_b, fill=(240, 240, 240), anchor="ma")
        y += 52

    f_p = _font(50)
    cta = "PLAY FREE  >  gamians.com"
    cw = d.textlength(cta, font=f_p)
    d.rounded_rectangle(((W - cw) / 2 - 40, H - 150, (W + cw) / 2 + 40, H - 62), 44, fill=(255, 210, 31))
    d.text((W / 2, H - 106), cta, font=f_p, fill=(26, 13, 0), anchor="mm")
    bg.save(out, "JPEG", quality=90)
    return out


# ---------------------------------------------------------------- captions

def captions(info: dict, rnd: random.Random, last: int = -1) -> tuple[dict, int]:
    t = info["title"]
    oi = rnd.choice([i for i in range(len(OPENERS)) if i != last])
    opener = OPENERS[oi].format(t=t)
    closer = rnd.choice(CLOSERS)
    gtag = "#" + re.sub(r"[^A-Za-z0-9]", "", t.split(":")[0]).lower()
    tags = " ".join([gtag] + rnd.sample(TAGS, 7))
    ig = f"{opener}\n\n{info['blurb']}\n\n{closer}\nPlay it: gamians.com/games/{info['slug']} (link in bio)\n\n{tags}"
    fb = f"{opener}\n\n{info['blurb']}\n\n{closer}\n{info['url']}"
    th = f"{opener}\n\n{closer}\n{info['url']}"
    if len(th) > 490:
        th = f"{opener}\n{info['url']}"[:490]
    return {"instagram": ig, "facebook": fb, "threads": th}, oi


# ---------------------------------------------------------------- publishers

def _graph(resp, what: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"{what}: HTTP {resp.status_code} {resp.text[:200]}")
    if resp.status_code >= 400 or "error" in data:
        e = data.get("error", {})
        raise RuntimeError(f"{what}: [{e.get('code')}] {e.get('message', resp.text[:200])}")
    return data


def post_instagram(ig_id: str, token: str, image_url: str, caption: str) -> str:
    c = _graph(http_request("POST", f"{GRAPH}/{ig_id}/media",
                            data={"image_url": image_url, "caption": caption, "access_token": token}), "IG container")["id"]
    for _ in range(30):
        st = _graph(http_request("GET", f"{GRAPH}/{c}", params={"fields": "status_code", "access_token": token}), "IG status")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG could not process the image: {st}")
        time.sleep(5)
    return _graph(http_request("POST", f"{GRAPH}/{ig_id}/media_publish",
                               data={"creation_id": c, "access_token": token}), "IG publish")["id"]


def post_facebook(token: str, page_id: str, image_url: str, message: str) -> str:
    return _graph(http_request("POST", f"{GRAPH}/{page_id}/photos",
                               data={"url": image_url, "message": message, "access_token": token}), "FB photo").get("post_id", "")


def _threads_key(seed: str) -> bytes:
    return hashlib.sha256(("gamians-threads-store:" + seed).encode()).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    stream = b""
    i = 0
    while len(stream) < len(data):
        stream += hashlib.sha256(key + i.to_bytes(4, "big")).digest()
        i += 1
    return bytes(a ^ b for a, b in zip(data, stream))


def threads_token(seed: str, refresh: bool) -> str | None:
    """The live Threads token: the stored (refreshed) one, else the THREADS_TOKEN secret.

    Threads long-lived tokens last 60 days; every run older than 7 days refreshes it and keeps the new one
    in state/threads_token.enc, encrypted with a key made from the never-expiring IG Page token secret.
    """
    key = _threads_key(seed)
    store = None
    if THREADS_STORE.exists():
        try:
            store = json.loads(_xor(base64.b64decode(THREADS_STORE.read_text()), key))
        except Exception as exc:  # unreadable store = start again from the secret, said out loud
            LOG.warning("Threads token store unreadable (%s) - using the THREADS_TOKEN secret.", exc)
    secret = (os.environ.get("THREADS_TOKEN") or "").strip()
    if store and secret and store.get("seed_hash") != hashlib.sha256(secret.encode()).hexdigest():
        store = None                     # a new secret was saved: it wins over the old store
    if not store and not secret:
        return None
    if not store:
        store = {"token": secret, "at": 0, "seed_hash": hashlib.sha256(secret.encode()).hexdigest()}
    if refresh and time.time() - store["at"] > 7 * 86400:
        r = http_request("GET", "https://graph.threads.net/refresh_access_token",
                         params={"grant_type": "th_refresh_token", "access_token": store["token"]})
        data = _graph(r, "Threads token refresh")
        store.update(token=data["access_token"], at=time.time())
        THREADS_STORE.write_text(base64.b64encode(_xor(json.dumps(store).encode(), key)).decode())
        LOG.info("Threads token refreshed (good for %d more days).", int(data.get("expires_in", 0)) // 86400)
    return store["token"]


def post_threads(token: str, image_url: str, text: str) -> str:
    c = _graph(http_request("POST", f"{THREADS}/me/threads",
                            data={"media_type": "IMAGE", "image_url": image_url, "text": text, "access_token": token}),
               "Threads container")["id"]
    time.sleep(30)                       # Meta asks for ~30 s before publishing
    return _graph(http_request("POST", f"{THREADS}/me/threads_publish",
                               data={"creation_id": c, "access_token": token}), "Threads publish")["id"]


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slug", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    dry = a.dry_run or env_flag("DRY_RUN")
    import yaml
    sc = (yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}).get("spotlight", {})
    exclude = set(sc.get("exclude", ["food-run", "food-run-3d"]))

    state = read_json(STATE, {})
    games = site_games(exclude)
    slug = a.slug or pick(state, games)
    info = game_info(slug)
    rnd = random.Random()
    label = rnd.choice([l for l in LABELS if l != state.get("last_label")])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out = Path(a.out or (REPO_ROOT / f"spot-{stamp}-{slug}.jpg"))
    render_card(info, label, out)
    caps, state["last_opener"] = captions(info, rnd, state.get("last_opener", -1))
    state["last_label"] = label
    LOG.info("Spotlight: %s (%s) -> %s", info["title"], label, out)
    if dry:
        for k, v in caps.items():
            print(f"--- {k} ---\n{v}\n")
        return 0

    cfg = load_config()
    from fb_api import FacebookClient
    import host
    ig_id, token = require_env("IG_USER_ID"), require_env("IG_ACCESS_TOKEN")
    image_url = host.publish_file(out, repo_slug=host.repo_slug(), token=require_env("GITHUB_TOKEN"),
                                  pages_origin=cfg["account"]["pages_origin"],
                                  retention_hours=48, wait_sec=int(cfg.get("hosting", {}).get("pages_wait_sec", 240)))
    targets = sc.get("targets", {"instagram": True, "facebook": True, "threads": True})
    done, failed = {}, {}
    jobs = {
        "instagram": lambda: post_instagram(ig_id, token, image_url, caps["instagram"]),
        "facebook": lambda: (lambda fb: post_facebook(fb._token, fb.page_id, image_url, caps["facebook"]))(
            FacebookClient.resolve(token, prefer_ig_user_id=ig_id)),
    }
    th = threads_token(token, refresh=True) if targets.get("threads") else None
    if th:
        jobs["threads"] = lambda: post_threads(th, image_url, caps["threads"])
    elif targets.get("threads"):
        LOG.info("Threads: no THREADS_TOKEN secret yet - skipped.")
    for k, fn in jobs.items():
        if not targets.get(k, False):
            continue
        try:
            done[k] = fn()
            LOG.info("%s posted: %s", k, done[k])
        except Exception as exc:  # one platform failing must not stop the others; reported below
            failed[k] = str(exc)
            LOG.error("%s FAILED: %s", k, exc)
    if not done:                         # nothing went out: keep the game for the next run
        return 1
    state.setdefault("posted", []).append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                           "slug": slug, **done, **({"failed": failed} if failed else {})})
    state["posted"] = state["posted"][-200:]
    write_json(STATE, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
