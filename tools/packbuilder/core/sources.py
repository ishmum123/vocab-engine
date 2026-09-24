"""Source downloads and the Tatoeba corpus stage (target-language sentences
that have an English translation, plus permissive audio)."""
import bz2
import gzip
import hashlib
import io
import json
import tarfile
import time
import urllib.request
from collections import Counter, defaultdict

from .util import log, file_sig

USER_AGENT = "vocab-packbuilder/2.0"
PERMISSIVE_AUDIO = {"CC BY 2.0 FR", "CC BY-SA 3.0", "CC BY-SA 4.0", "CC BY 4.0", "CC0 1.0"}


def _remote_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
    except Exception:
        return None


def kaikki_plain(env):
    return env.cache / env.spec.kaikki_file[:-3] if env.spec.kaikki_file.endswith(".gz") \
        else env.cache / env.spec.kaikki_file


def ensure_downloaded(env, check_remote=False):
    """Download missing sources. With check_remote, re-download when the
    cached size differs from the server's (sources are updated weekly)."""
    env.cache.mkdir(exist_ok=True)
    for name, url in env.spec.sources.items():
        dest = env.cache / name
        if dest.exists() and dest.stat().st_size > 0:
            if not check_remote:
                continue
            expected = _remote_size(url)
            if expected is None or dest.stat().st_size == expected:
                continue
            log(f"  {name}: cached size {dest.stat().st_size} != remote {expected}, re-downloading")
        log(f"downloading {name} ...")
        t0 = time.time()
        tmp = dest.with_suffix(dest.suffix + ".part")
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                tmp.replace(dest)
                break
            except Exception as e:
                log(f"  attempt {attempt+1} failed: {e}")
                if attempt == 4:
                    raise
        log(f"  {name}: {dest.stat().st_size} bytes in {time.time()-t0:.1f}s")

    gz = env.cache / env.spec.kaikki_file
    plain = kaikki_plain(env)
    if gz != plain and gz.exists() and not plain.exists():
        log(f"decompressing {gz.name} ...")
        with gzip.open(gz, "rb") as fin, open(plain, "wb") as fout:
            while True:
                chunk = fin.read(1 << 20)
                if not chunk:
                    break
                fout.write(chunk)


# ---------------------------------------------------------------------------
# Stage corpus: target-language sentences that have an English translation
# ---------------------------------------------------------------------------

def corpus_path(env):
    sp = env.spec
    ver = sp.versions["corpus"]
    # extra_corpus_files: repo-relative files of spec.extra_corpus_rows (fa: sentences written for the pack)
    sig = hashlib.sha1("|".join([ver] + [file_sig(env.cache / n) for n in
                       (sp.sentences_file, sp.eng_file, sp.links_file, sp.audio_file)] +
                       [file_sig(env.repo / n) for n in sp.extra_corpus_files]
                       ).encode()).hexdigest()[:10]
    return env.derived / f"corpus_{ver}_{sig}.json.gz"


def _link_lines(path):
    if path.name.endswith(".tar.bz2"):
        with tarfile.open(path, "r:bz2") as tf:
            member = next(m for m in tf.getmembers() if m.name.endswith("links.csv"))
            yield from io.TextIOWrapper(tf.extractfile(member), encoding="utf-8")
    else:
        with bz2.open(path, "rt", encoding="utf-8") as f:
            yield from f


def stage_corpus(env):
    sp = env.spec
    out = corpus_path(env)
    if out.exists():
        with gzip.open(out, "rt", encoding="utf-8") as f:
            return json.load(f)
    env.derived.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tgt = {}
    data = bz2.decompress((env.cache / sp.sentences_file).read_bytes()).decode("utf-8")
    for line in data.split("\n"):
        p = line.split("\t")
        if len(p) >= 3 and p[1] == sp.tatoeba_code:
            tgt[int(p[0])] = (p[2], p[3] if len(p) > 3 else "")
    eng = {}
    data = bz2.decompress((env.cache / sp.eng_file).read_bytes()).decode("utf-8")
    for line in data.split("\n"):
        p = line.split("\t")
        if len(p) >= 3:
            eng[int(p[0])] = p[2]
    del data
    # links: sentence_id <tab> translation_id, from the all-languages
    # links.tar.bz2 (links.csv, both directions listed) or a per-pair
    # <iso3>-eng_links.tsv.bz2 export
    best_en = {}
    for raw in _link_lines(env.cache / sp.links_file):
        p = raw.rstrip("\n").split("\t")
        if len(p) < 2:
            continue
        a, b = int(p[0]), int(p[1])
        if a in tgt and b in eng:
            if a not in best_en or b < best_en[a]:
                best_en[a] = b  # lowest English id: deterministic choice
    # sentences_with_audio.csv columns: sentence_id, audio_id, username,
    # license, attribution_url (verified against the Tatoeba API: sentence
    # 4369 -> audio 1009973).
    audio = {}
    with tarfile.open(env.cache / sp.audio_file, "r:bz2") as tf:
        member = next(m for m in tf.getmembers() if "sentences_with_audio" in m.name)
        for raw in io.TextIOWrapper(tf.extractfile(member), encoding="utf-8"):
            p = raw.rstrip("\n").split("\t")
            if len(p) < 4 or not p[0].isdigit() or not p[1].isdigit():
                continue
            sid, aid, lic = int(p[0]), int(p[1]), p[3]
            if sid in tgt and lic in PERMISSIVE_AUDIO and sp.use_audio:   # id: no audio shipped
                if sid not in audio or aid < audio[sid][0]:
                    audio[sid] = (aid, lic)
    rows = []
    # untranslated_rows (fa): every target sentence is tagged for frequency and
    # lemma evidence; one without an English link has english "" and is never shipped
    for sid in sorted(tgt if sp.untranslated_rows else best_en):
        text, user = tgt[sid]
        aid, lic = audio.get(sid, (None, None))
        rows.append([sid, text, user, eng[best_en[sid]] if sid in best_en else "", aid, lic])
    extra = sp.extra_corpus_rows(env)
    rows += extra
    # key names kept from the Italian build ("n_ita") so cached corpora stay valid
    result = {"rows": rows, "n_ita": len(tgt), "n_with_en": len(best_en) + len(extra),
              "n_audio": sum(1 for r in rows if r[4])}
    with gzip.GzipFile(out, "wb", mtime=0) as g:
        g.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    log(f"corpus: {len(tgt)} {sp.tatoeba_code} sentences, {len(rows)} with English, "
        f"{result['n_audio']} with permissive audio ({time.time()-t0:.0f}s)")
    return result


def audio_recorders(env, sentences):
    """{licence: [{"recorder": username, "clips": n}]} for the clips the pack links."""
    used = {int(s["audio"].rsplit("/", 1)[1]) for s in sentences if "audio" in s}
    meta = {}
    with tarfile.open(env.cache / env.spec.audio_file, "r:bz2") as tf:
        member = next(m for m in tf.getmembers() if "sentences_with_audio" in m.name)
        for raw in io.TextIOWrapper(tf.extractfile(member), encoding="utf-8"):
            p = raw.rstrip("\n").split("\t")
            if len(p) >= 4 and p[1].isdigit() and int(p[1]) in used:
                meta[int(p[1])] = (p[2], p[3])
    per = defaultdict(Counter)
    for aid in used:
        user, lic = meta.get(aid, ("unknown", "unknown"))
        per[lic or "unknown"][user or "unknown"] += 1
    return {lic: [{"recorder": u, "clips": n} for u, n in sorted(c.items(), key=lambda x: (-x[1], x[0]))]
            for lic, c in sorted(per.items())}
