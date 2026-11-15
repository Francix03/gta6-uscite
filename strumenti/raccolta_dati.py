#!/usr/bin/env python3
"""Raccolta dati gratis per il canale GTA6-clips-news (gira su GitHub Actions ogni 3 ore).

Cosa fa (solo librerie standard di Python):
  1. YouTube: Shorts "gta 6" degli ultimi 7 giorni e delle ultime 48 ore, con views al giorno,
     views all'ora e "outlier" (views del video / media delle views del suo canale).
  2. YouTube: commenti più rilevanti dei 3 video GTA 6 più visti della settimana (domande dei fan),
     al massimo una volta ogni 20 ore.
  3. Feed RSS dei canali concorrenti e del nostro canale (gratis, senza chiave).
  4. Storico delle views dei nostri video, per sapere quante views fa ogni Short a 24 e 48 ore.
  5. Twitch: clip di GTA VI più viste delle ultime 24 ore (solo come SEGNALE di cosa piace;
     le clip non si scaricano e non si ricaricano mai).

Chiavi (Settings -> Secrets and variables -> Actions del repo): YT_API_KEY, TWITCH_CLIENT_ID,
TWITCH_CLIENT_SECRET. Se una chiave manca, quella parte viene saltata e scritta in "errori".

Uscite: dati/ricerca.json (tutto), dati/ricerca.md (riassunto leggibile), dati/storico_nostro.csv.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATI = os.path.join(BASE, "dati")
UA = {"User-Agent": "Mozilla/5.0 (gta6-uscite raccolta dati)"}

# Canali da controllare (modello-clip-gta6.md, sezione 12). Si possono aggiungere handle qui.
CONCORRENTI = ["MrBossFTW", "GTA6Videos_", "GTASeriesVideos", "BreeZeGTA", "GrandGecko",
               "LegacyKillaHD", "gameranxTV", "TmarTn2"]
NOSTRO = "gta-vi-news-clips"
TWITCH_GIOCO = "Grand Theft Auto VI"
STORICO_GIORNI = 14

YT = "https://www.googleapis.com/youtube/v3/"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}


# ---------------------------------------------------------------- utilità
def ora():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def leggi_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def http(url, params=None, headers=None, data=None, testo=False):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        corpo = r.read().decode("utf-8", "replace")
    return corpo if testo else json.loads(corpo)


def durata_s(iso_dur):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_dur or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def ore_da(pubblicato, adesso):
    return max((adesso - leggi_iso(pubblicato)).total_seconds() / 3600, 0.5)


# ---------------------------------------------------------------- YouTube API
def yt(endpoint, chiave, **params):
    params["key"] = chiave
    return http(YT + endpoint, params)


def cerca_video(chiave, dopo, durata="short", n=25, q="gta 6"):
    r = yt("search", chiave, part="snippet", q=q, type="video", videoDuration=durata,
           publishedAfter=iso(dopo), order="viewCount", maxResults=n, relevanceLanguage="en")
    return [it["id"]["videoId"] for it in r.get("items", []) if it.get("id", {}).get("videoId")]


def dettagli_video(chiave, ids):
    out = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        r = yt("videos", chiave, part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]),
               fields="items(id,snippet(title,channelId,channelTitle,publishedAt,defaultAudioLanguage),"
                      "statistics(viewCount,commentCount),contentDetails(duration))")
        for it in r.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            out[it["id"]] = {
                "id": it["id"], "titolo": sn["title"], "canale": sn["channelTitle"],
                "canale_id": sn["channelId"], "pubblicato": sn["publishedAt"],
                "lingua": sn.get("defaultAudioLanguage", ""),
                "views": int(st.get("viewCount", 0)), "commenti": int(st.get("commentCount", 0)),
                "durata_s": durata_s(it["contentDetails"].get("duration")),
                "link": "https://www.youtube.com/watch?v=" + it["id"],
            }
    return out


def media_canali(chiave, canali):
    out = {}
    canali = list(dict.fromkeys(canali))
    for i in range(0, len(canali), 50):
        r = yt("channels", chiave, part="statistics", id=",".join(canali[i:i + 50]),
               fields="items(id,statistics(viewCount,videoCount,subscriberCount))")
        for it in r.get("items", []):
            st = it.get("statistics", {})
            v, n = int(st.get("viewCount", 0)), int(st.get("videoCount", 0))
            out[it["id"]] = {"media": round(v / n) if n else None,
                             "iscritti": int(st.get("subscriberCount", 0) or 0)}
    return out


def calcola(video, canali, adesso):
    for v in video:
        ore = ore_da(v["pubblicato"], adesso)
        v["ore"] = round(ore, 1)
        v["views_ora"] = round(v["views"] / ore)
        v["views_giorno"] = round(v["views"] / ore * 24)
        c = canali.get(v["canale_id"], {})
        v["media_canale"] = c.get("media")
        v["iscritti_canale"] = c.get("iscritti")
        v["outlier"] = round(v["views"] / c["media"], 1) if c.get("media") else None
    return video


def sezione_shorts(chiave, adesso, out):
    id7 = cerca_video(chiave, adesso - dt.timedelta(days=7))
    id48 = cerca_video(chiave, adesso - dt.timedelta(hours=48))
    det = dettagli_video(chiave, id7 + id48)
    can = media_canali(chiave, [v["canale_id"] for v in det.values()])
    tutti = calcola(list(det.values()), can, adesso)
    lim48 = adesso - dt.timedelta(hours=48)
    out["shorts_7g"] = sorted(tutti, key=lambda v: -v["views_giorno"])
    out["shorts_48h"] = sorted([v for v in tutti if leggi_iso(v["pubblicato"]) >= lim48],
                               key=lambda v: -v["views_ora"])


def sezione_fan(chiave, adesso, out, vecchio):
    prec = (vecchio or {}).get("domande_fan") or {}
    if prec.get("aggiornato") and ore_da(prec["aggiornato"], adesso) < 20:
        out["domande_fan"] = prec  # già fatto nelle ultime 20 ore: si risparmia quota
        return
    ids = cerca_video(chiave, adesso - dt.timedelta(days=7), durata="any", n=10)
    det = sorted(dettagli_video(chiave, ids).values(), key=lambda v: -v["views"])
    scelti = [v for v in det if (v["durata_s"] or 0) > 60][:3] or det[:3]
    video = []
    for v in scelti:
        try:
            r = yt("commentThreads", chiave, part="snippet", videoId=v["id"], order="relevance",
                   maxResults=40, textFormat="plainText")
            comm = [{"testo": it["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:300],
                     "like": it["snippet"]["topLevelComment"]["snippet"].get("likeCount", 0)}
                    for it in r.get("items", [])]
        except Exception as e:  # commenti chiusi o altro
            comm = [{"testo": "errore: " + str(e)[:100], "like": 0}]
        video.append({"id": v["id"], "titolo": v["titolo"], "canale": v["canale"],
                      "views": v["views"], "link": v["link"],
                      "commenti": sorted(comm, key=lambda c: -c["like"])})
    out["domande_fan"] = {"aggiornato": iso(adesso), "video": video}


# ---------------------------------------------------------------- feed RSS (senza chiave)
def id_canale(handle, chiave, cache):
    if handle in cache:
        return cache[handle]
    cid = None
    if chiave:
        try:
            r = yt("channels", chiave, part="id", forHandle="@" + handle)
            if r.get("items"):
                cid = r["items"][0]["id"]
        except Exception:
            cid = None
    if not cid:  # metodo del "canonical" (il vecchio "channelId" prende l'ID sbagliato)
        pagina = http("https://www.youtube.com/@" + handle, testo=True)
        m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]+)"', pagina)
        cid = m.group(1) if m else None
    if cid:
        cache[handle] = cid
    return cid


def leggi_feed(cid, adesso):
    xml = http("https://www.youtube.com/feeds/videos.xml", {"channel_id": cid}, testo=True)
    radice = ET.fromstring(xml)
    video = []
    for e in radice.findall("a:entry", NS):
        link = e.find("a:link", NS).get("href")
        stat = e.find("media:group/media:community/media:statistics", NS)
        views = int(stat.get("views")) if stat is not None and stat.get("views") else None
        pub = e.find("a:published", NS).text
        v = {"id": e.find("yt:videoId", NS).text, "titolo": e.find("a:title", NS).text,
             "link": link, "pubblicato": pub, "views": views, "short": "/shorts/" in link}
        if views is not None:
            v["views_giorno"] = round(views / ore_da(pub, adesso) * 24)
        video.append(v)
    return video


def leggi_canale_api(chiave, cid, adesso):
    """Ultimi 15 video di un canale con l'API (1-2 unità). Si usa quando il feed RSS non risponde:
    dai server di GitHub i feed di YouTube danno 404 (provato il 15/11)."""
    r = yt("playlistItems", chiave, part="contentDetails", playlistId="UU" + cid[2:], maxResults=15)
    ids = [it["contentDetails"]["videoId"] for it in r.get("items", [])]
    video = []
    for v in dettagli_video(chiave, ids).values():
        short = (v["durata_s"] or 0) <= 180
        video.append({"id": v["id"], "titolo": v["titolo"], "pubblicato": v["pubblicato"],
                      "views": v["views"], "short": short,
                      "link": ("https://www.youtube.com/shorts/" if short else "https://www.youtube.com/watch?v=") + v["id"],
                      "views_giorno": round(v["views"] / ore_da(v["pubblicato"], adesso) * 24)})
    return sorted(video, key=lambda v: v["pubblicato"], reverse=True)


def leggi_video_canale(chiave, cid, adesso):
    try:
        return leggi_feed(cid, adesso)
    except Exception:
        if not chiave:
            raise
        return leggi_canale_api(chiave, cid, adesso)


def sezione_feed(chiave, adesso, out, vecchio, errori):
    cache = dict((vecchio or {}).get("id_canali") or {})
    conc = []
    for h in CONCORRENTI:
        try:
            cid = id_canale(h, chiave, cache)
            if not cid:
                errori.append(f"feed {h}: ID del canale non trovato")
                continue
            vid = [v for v in leggi_video_canale(chiave, cid, adesso) if ore_da(v["pubblicato"], adesso) <= 7 * 24]
            conc.append({"canale": h, "canale_id": cid, "video": vid})
        except Exception as e:
            errori.append(f"feed {h}: {e}"[:200])
    out["concorrenti"] = conc
    try:
        cid = id_canale(NOSTRO, chiave, cache)
        out["nostro_canale"] = leggi_video_canale(chiave, cid, adesso) if cid else []
    except Exception as e:
        errori.append(f"feed nostro canale: {e}"[:200])
        out["nostro_canale"] = []
    out["id_canali"] = cache


# ---------------------------------------------------------------- storico nostro canale
def aggiorna_storico(adesso, nostri, percorso):
    righe = []
    if os.path.exists(percorso):
        with open(percorso, newline="", encoding="utf-8") as f:
            righe = list(csv.DictReader(f))
    limite = adesso - dt.timedelta(days=STORICO_GIORNI)
    righe = [r for r in righe if leggi_iso(r["quando"]) >= limite]
    for v in nostri:
        if v.get("views") is not None:
            righe.append({"quando": iso(adesso), "id": v["id"], "titolo": v["titolo"],
                          "pubblicato": v["pubblicato"], "short": "1" if v["short"] else "0",
                          "views": str(v["views"])})
    with open(percorso, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["quando", "id", "titolo", "pubblicato", "short", "views"])
        w.writeheader()
        w.writerows(righe)
    return righe


def views_a(punti, pub, ore_obiettivo, tolleranza=3.0):
    """Views a N ore dalla pubblicazione: interpolazione tra le due misure intorno a N ore."""
    obiettivo = pub + dt.timedelta(hours=ore_obiettivo)
    prima = [p for p in punti if p[0] <= obiettivo]
    dopo = [p for p in punti if p[0] >= obiettivo]
    if prima and dopo:
        a, b = prima[-1], dopo[0]
        if (b[0] - a[0]).total_seconds() <= 2 * tolleranza * 3600:
            if b[0] == a[0]:
                return a[1]
            f = (obiettivo - a[0]).total_seconds() / (b[0] - a[0]).total_seconds()
            return round(a[1] + f * (b[1] - a[1]))
    vicini = [p for p in punti if abs((p[0] - obiettivo).total_seconds()) <= tolleranza * 3600]
    if vicini:
        return min(vicini, key=lambda p: abs((p[0] - obiettivo).total_seconds()))[1]
    return None


def risultati_nostri(righe):
    per_video = {}
    for r in righe:
        per_video.setdefault(r["id"], {"r": r, "punti": []})["punti"].append(
            (leggi_iso(r["quando"]), int(r["views"])))
    out = []
    for vid, d in per_video.items():
        pub = leggi_iso(d["r"]["pubblicato"])
        punti = sorted(d["punti"])
        out.append({"id": vid, "titolo": d["r"]["titolo"], "pubblicato": d["r"]["pubblicato"],
                    "short": d["r"]["short"] == "1",
                    "views_24h": views_a(punti, pub, 24), "views_48h": views_a(punti, pub, 48),
                    "views_ultime": punti[-1][1]})
    return sorted(out, key=lambda v: v["pubblicato"], reverse=True)


# ---------------------------------------------------------------- Twitch
def sezione_twitch(cid, segreto, adesso, out):
    tok = http("https://id.twitch.tv/oauth2/token", data=urllib.parse.urlencode(
        {"client_id": cid, "client_secret": segreto, "grant_type": "client_credentials"}).encode())
    h = {"Client-Id": cid, "Authorization": "Bearer " + tok["access_token"]}
    g = http("https://api.twitch.tv/helix/games", {"name": TWITCH_GIOCO}, headers=h).get("data", [])
    if not g:
        out["twitch_gta6"] = {"nota": f"'{TWITCH_GIOCO}' non ancora presente su Twitch", "clip": []}
        return
    gid = g[0]["id"]
    clip, cursore = [], None
    for _ in range(3):  # fino a 300 clip, finestra di 24 ore (sotto il tetto di ~1.000 risultati)
        p = {"game_id": gid, "started_at": iso(adesso - dt.timedelta(hours=24)),
             "ended_at": iso(adesso), "first": 100}
        if cursore:
            p["after"] = cursore
        r = http("https://api.twitch.tv/helix/clips", p, headers=h)
        clip += r.get("data", [])
        cursore = (r.get("pagination") or {}).get("cursor")
        if not cursore:
            break
    visti, tenute = [], []
    for c in sorted(clip, key=lambda c: -c["view_count"]):
        # stesso streamer + stesso momento della diretta (±60 s) = stesso momento: si tiene la più vista
        off = c.get("vod_offset")
        if any(c["broadcaster_id"] == b and off is not None and o is not None and abs(off - o) <= 60
               for b, o in visti):
            continue
        visti.append((c["broadcaster_id"], off))
        ore = ore_da(c["created_at"], adesso)
        tenute.append({"titolo": c["title"], "streamer": c["broadcaster_name"], "views": c["view_count"],
                       "creata": c["created_at"], "ore": round(ore, 1),
                       "views_ora": round(c["view_count"] / ore), "durata_s": c.get("duration"),
                       "lingua": c.get("language"), "url": c["url"]})
    out["twitch_gta6"] = {"game_id": gid, "clip": sorted(tenute, key=lambda c: -c["views_ora"])[:40]}


# ---------------------------------------------------------------- riassunto leggibile
def riassunto(d):
    r = [f"# Dati raccolti il {d['aggiornato']} (UTC)", ""]
    if d["errori"]:
        r += ["## Errori"] + [f"- {e}" for e in d["errori"]] + [""]
    if d.get("shorts_48h"):
        r += ["## Shorts partiti nelle ultime 48 ore (per views all'ora)",
              "| Titolo | Canale | Views | Ore | Views/ora | Outlier |", "|---|---|---|---|---|---|"]
        for v in d["shorts_48h"][:15]:
            r.append(f"| {v['titolo']} | {v['canale']} | {v['views']:,} | {v['ore']} | {v['views_ora']:,} | "
                     f"{('x' + str(v['outlier'])) if v['outlier'] else '-'} |")
        r.append("")
    if d.get("shorts_7g"):
        r += ["## Shorts degli ultimi 7 giorni (per views al giorno)",
              "| Titolo | Canale | Views | Al giorno | Outlier |", "|---|---|---|---|---|"]
        for v in d["shorts_7g"][:15]:
            r.append(f"| {v['titolo']} | {v['canale']} | {v['views']:,} | {v['views_giorno']:,} | "
                     f"{('x' + str(v['outlier'])) if v['outlier'] else '-'} |")
        r.append("")
    if d.get("nostri_risultati"):
        r += ["## Nostri video: views a 24 e 48 ore", "| Pubblicato | Titolo | 24 h | 48 h | Ultime |",
              "|---|---|---|---|---|"]
        for v in d["nostri_risultati"][:20]:
            r.append(f"| {v['pubblicato'][:16]} | {v['titolo']} | {v['views_24h'] if v['views_24h'] is not None else '-'} | "
                     f"{v['views_48h'] if v['views_48h'] is not None else '-'} | {v['views_ultime']} |")
        r.append("")
    tw = d.get("twitch_gta6") or {}
    if tw.get("clip"):
        r += ["## Twitch GTA VI: clip più forti delle ultime 24 ore (solo segnale, mai da ricaricare)",
              "| Titolo | Streamer | Views | Views/ora |", "|---|---|---|---|"]
        for c in tw["clip"][:15]:
            r.append(f"| {c['titolo']} | {c['streamer']} | {c['views']:,} | {c['views_ora']:,} |")
        r.append("")
    elif tw.get("nota"):
        r += [f"Twitch: {tw['nota']}", ""]
    return "\n".join(r) + "\n"


# ---------------------------------------------------------------- main
def main():
    os.makedirs(DATI, exist_ok=True)
    adesso = ora()
    p_json = os.path.join(DATI, "ricerca.json")
    vecchio = None
    if os.path.exists(p_json):
        try:
            with open(p_json, encoding="utf-8") as f:
                vecchio = json.load(f)
        except Exception:
            vecchio = None
    errori, out = [], {"aggiornato": iso(adesso)}
    yk = os.environ.get("YT_API_KEY", "").strip()
    if yk:
        for nome, fn in (("shorts", lambda: sezione_shorts(yk, adesso, out)),
                         ("domande dei fan", lambda: sezione_fan(yk, adesso, out, vecchio))):
            try:
                fn()
            except Exception as e:
                errori.append(f"YouTube {nome}: {e}"[:200])
    else:
        errori.append("YouTube API saltata: manca il secret YT_API_KEY")
    sezione_feed(yk, adesso, out, vecchio, errori)
    righe = aggiorna_storico(adesso, out.get("nostro_canale", []), os.path.join(DATI, "storico_nostro.csv"))
    out["nostri_risultati"] = risultati_nostri(righe)
    tid, tsec = os.environ.get("TWITCH_CLIENT_ID", "").strip(), os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
    if tid and tsec:
        try:
            sezione_twitch(tid, tsec, adesso, out)
        except Exception as e:
            errori.append(f"Twitch: {e}"[:200])
    else:
        errori.append("Twitch saltato: mancano i secret TWITCH_CLIENT_ID e TWITCH_CLIENT_SECRET")
    out["errori"] = errori
    with open(p_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATI, "ricerca.md"), "w", encoding="utf-8") as f:
        f.write(riassunto(out))
    print(f"Fatto: {len(out.get('shorts_7g', []))} Shorts 7g, {len(out.get('shorts_48h', []))} Shorts 48h, "
          f"{len(out.get('concorrenti', []))} feed, {len(out['nostri_risultati'])} nostri video, "
          f"{len((out.get('twitch_gta6') or {}).get('clip', []))} clip Twitch, {len(errori)} errori")
    for e in errori:
        print("  -", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
