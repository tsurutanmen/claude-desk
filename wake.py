"""Say "ヘイ、クロード" and an agent answers.

Listens to the default microphone and recognizes speech on this PC with a
small Vosk model. Audio is never saved or sent anywhere; only the words said
after the wake word go out: "〇〇のセッションに…" to that Claude Code session
through session-bridge, anything else to the homedot agent on 127.0.0.1:8790.
The reply is read aloud with VOICEVOX, or the Windows voice when it is not running. The state goes to
~/.claude/session-dash/wake.json for the Claude Desk wallpaper.

Run: venv/Scripts/python wake.py   (settings in wake.config.json beside it)
"""
import json
import pathlib
import queue
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

HERE = pathlib.Path(__file__).parent
CONFIG = {
    "model": str(HERE / "models" / "vosk-model-small-ja-0.22"),
    # what counts as the wake word, after spaces are removed (Vosk writes words apart)
    "wake": ["ヘイクロード", "へいくろーど", "へー蔵人", "ヘイ蔵人", "蔵人", "クロード", "くろーど", "くろうど", "クロウド"],
    # part of the microphone's name (e.g. "USB MIC", "NVIDIA Broadcast"); null = the Windows default
    "device": None,
    "dots_url": "http://127.0.0.1:8790/api/chat",
    "speak": True,
    # VOICEVOX engine and voice (3 = ずんだもん, 2 = 四国めたん, 8 = 春日部つむぎ); Windows voice when it is not running
    "voicevox_url": "http://127.0.0.1:50021",
    "voicevox_speaker": 3,
    # 1.0 = VOICEVOX's own pace
    "voicevox_speed": 1.3,
    # after a reply, listen without the wake word: "question" = when the dot asked something, "always", "off"
    "follow_up": "question",
    # say back what was heard while the dot thinks; a word more after this many seconds
    "ack": True,
    # where each day's exchanges are kept, one markdown file per day
    "talks_dir": str(HERE / "talks"),
    "still_working_sec": 8,
    # "〇〇のセッションに…" goes to that Claude Code session through session-bridge (read-only for voice)
    "bridge_dir": str(HERE.parent / "session-bridge"),
    # wait this long for a session's answer; past it, say so and read the answer out when it comes
    "session_wait_sec": 90,
    # the talk button reads a session's reply: this many sentences, this many characters at most
    "talk_sentences": 6,
    "talk_chars": 500,
    "silence_sec": 1.2,
    "max_sec": 15,
    # stop listening while these are running (voice chat in a game)
    "pause_when": [],  # e.g. ["VALORANT-Win64-Shipping.exe"]
    # stop listening while another app records from the mic (Claude's voice input, Discord, a call)
    "pause_when_mic_shared": True,
    # write what was heard and the mic level to wake.log (text only, never audio)
    "debug": False,
    # a quiet headset mic: multiply the samples before recognizing
    "gain": 8,
    # mean level (after gain) that counts as talking
    "speech_level": 300,
}
STATE = pathlib.Path.home() / ".claude" / "session-dash" / "wake.json"
RATE = 16000
S_LEVEL = [0.0]


def load_config():
    f = HERE / "wake.config.json"
    if f.exists():
        CONFIG.update(json.loads(f.read_text(encoding="utf-8")))


def put(state, **kw):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"state": state, "at": time.time() * 1000, **kw}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE)


def debug(line):
    if CONFIG["debug"]:
        log = HERE / "wake.log"
        # it holds what was heard: keep it small, dropping the older half past 1 MB
        if log.exists() and log.stat().st_size > 1_000_000:
            text = log.read_text(encoding="utf-8", errors="replace")
            log.write_text(text[len(text) // 2:], encoding="utf-8")
        with open(log, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + line + "\n")


def squash(text):
    return re.sub(r"\s+", "", text)


def after_wake(text):
    """The words said after the wake word in the same breath, or None if there was no wake word."""
    s = squash(text)
    for w in sorted(CONFIG["wake"], key=len, reverse=True):
        i = s.find(w)
        if i >= 0:
            return s[i + len(w):].lstrip("、。,. ")
    return None


def paused():
    names = CONFIG["pause_when"]
    if not names:
        return False
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, errors="replace").stdout
    return any(n.lower() in out.lower() for n in names)


MIC_USERS = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def boot_filetime():
    import ctypes
    ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_uint64
    up = ctypes.windll.kernel32.GetTickCount64() / 1000
    return int((time.time() - up + 11644473600) * 10_000_000)


def mic_in_use_by_other():
    """The name of another app recording from the mic right now, or None.

    Windows keeps, per app, when it last started and stopped using the mic (the
    privacy indicator reads the same keys); stop = 0 means it is using it now.
    Entries from before this boot, and ones whose program is gone, are stale.
    """
    import os
    import winreg
    me = {os.path.normcase(p) for p in (sys.executable, getattr(sys, "_base_executable", "")) if p}
    since = boot_filetime()

    def walk(key, nonpackaged):
        for i in range(winreg.QueryInfoKey(key)[0]):
            name = winreg.EnumKey(key, i)
            with winreg.OpenKey(key, name) as sub:
                if name == "NonPackaged":
                    yield from walk(sub, True)
                    continue
                try:
                    start = winreg.QueryValueEx(sub, "LastUsedTimeStart")[0]
                    stop = winreg.QueryValueEx(sub, "LastUsedTimeStop")[0]
                except OSError:
                    continue
                yield name, start, stop, nonpackaged

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIC_USERS) as root:
            for name, start, stop, is_exe in walk(root, False):
                if stop != 0 or start < since:
                    continue
                if is_exe:
                    exe = name.replace("#", "\\")
                    if os.path.normcase(exe) in me or not os.path.exists(exe):
                        continue
                    return os.path.basename(exe)
                return name.split("_")[0]
    except OSError:
        pass
    return None


def pick_device(name):
    """The input device whose name contains `name` (MME devices first), or the default."""
    if not name:
        return None
    for host in ("MME", "Windows WASAPI", None):
        for i, d in enumerate(sd.query_devices()):
            api = sd.query_hostapis(d["hostapi"])["name"]
            if d["max_input_channels"] > 0 and name.lower() in d["name"].lower() and (host is None or api == host):
                return i
    print(f"「{name}」という名前のマイクが無いので、既定のマイクを使います", flush=True)
    return None


def warm_dots():
    """Tell the dot someone is about to speak, so its long-running claude starts while they talk."""
    import threading

    def go():
        try:
            req = urllib.request.Request(CONFIG["dots_url"].replace("/api/chat", "/api/warm"), data=b"{}",
                                         headers={"Content-Type": "application/json", "X-Dots": "1"})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass  # an older dot without /api/warm, or not running

    threading.Thread(target=go, daemon=True).start()


def save_talk(heard, reply, secs, is_first, who="ドット"):
    """Keep the exchange in talks/<date>.md: a heading per "ヘイ、クロード", each turn below it."""
    folder = pathlib.Path(CONFIG["talks_dir"])
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / time.strftime("%Y-%m-%d.md"), "a", encoding="utf-8") as f:
        if is_first:
            f.write(f"\n## {time.strftime('%H:%M')}\n\n")
        f.write(f"- **あなた**：{heard}\n- **{who}**（{secs:.0f}秒）：{reply.strip()}\n")


# answers that came after the wait ran out: (session name, what was asked, answer to read)
LATER = queue.Queue()
# the sessions' talk button: replies to read out land here; the listener marks it is alive beside it
SPEAK_DIR = STATE.parent / "speak"
ALIVE = STATE.parent / "wake.alive"


def read_out_reply(model, audio):
    """Read the oldest waiting reply of a session whose talk button is on. True when it said one.

    With "listen", beep afterwards, hear the person and send their words straight to that session,
    so no send button is needed; its reply comes back here, and so on until they stay quiet.
    """
    files = sorted(SPEAK_DIR.glob("*.json")) if SPEAK_DIR.exists() else []
    if not files:
        return False
    f = files[0]
    try:
        item = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        item = None
    f.unlink(missing_ok=True)
    if not item or time.time() * 1000 - item.get("at", 0) > 10 * 60 * 1000:
        return False  # broken, or too old to still matter
    raw = item.get("text", "")
    if raw:
        try:
            text = bridge().for_speech(raw, sentences=CONFIG["talk_sentences"], limit=CONFIG["talk_chars"])
        except Exception:
            text = re.sub(r"\s+", " ", raw)[:CONFIG["talk_chars"]]
        put("replied", reply=text)
        speak(text, speaker=item.get("voice"))
    if item.get("listen") and item.get("session"):
        while not audio.empty():  # drop what the speaker said into the mic
            audio.get_nowait()
        put("listening")
        beep()
        heard = listen_command(model, audio)
        beep_end()
        if heard:
            debug(f"会話ボタン→{item.get('from')}: {heard}")
            try:
                bridge().post({"id": item["session"]}, heard, frm="声（本人）", mode="do", kind="voice")
                save_talk(heard, "（セッションに送った）", 0, is_first=False, who=item.get("from") or "セッション")
            except Exception as e:
                speak(f"送れなかったのだ（{type(e).__name__}）")
    put("idle")
    return True


def bridge():
    if CONFIG["bridge_dir"] not in sys.path:
        sys.path.insert(0, CONFIG["bridge_dir"])
    import bridge as b
    return b


def route(text):
    """(session or None, words for it, a reply to say instead). A session only when the words name one."""
    try:
        b = bridge()
    except Exception:
        return None, text, None  # session-bridge is not there: everything goes to the dot
    hit = b.parse(text)
    if not hit:
        return None, text, None
    name, words = hit
    s, others = b.pick(name)
    if s:
        return s, words, None
    if others:
        return None, words, f"{'と'.join(others)}のどっちなのだ？名前を入れてもう一度言ってほしいのだ"
    names = b.named()
    if not names:
        return None, words, "呼べるセッションが無いのだ"
    return None, words, f"「{name}」というセッションが見つからないのだ。呼べるのは{'、'.join(names[:4])}なのだ"


def ask_session(s, text):
    """Ask a session read-only and wait a while; past that, read its answer out later."""
    import threading
    b = bridge()
    mid = b.post(s, text, frm="声", mode="ask")
    ans = b.wait_for(s, mid, CONFIG["session_wait_sec"])
    if ans is not None:
        return b.for_speech(ans)

    def later():
        a = b.wait_for(s, mid, 30 * 60)
        if a is not None:
            LATER.put((b.label(s), text, b.for_speech(a)))

    threading.Thread(target=later, daemon=True).start()
    return "時間がかかってるのだ。終わったら教えるのだ"


def ask_dots(text):
    req = urllib.request.Request(
        CONFIG["dots_url"], data=json.dumps({"text": text, "via": "声"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Dots": "1"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read()).get("reply", "")


def voicevox_wav(text, speaker=None):
    """One sentence as WAV bytes from the local VOICEVOX engine, or None."""
    base, spk = CONFIG["voicevox_url"], speaker or CONFIG["voicevox_speaker"]
    try:
        q = urllib.parse.urlencode({"text": text, "speaker": spk})
        with urllib.request.urlopen(urllib.request.Request(f"{base}/audio_query?{q}", data=b"", method="POST"), timeout=30) as r:
            query = json.loads(r.read())
        query["speedScale"] = CONFIG["voicevox_speed"]
        req = urllib.request.Request(f"{base}/synthesis?speaker={spk}", data=json.dumps(query).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except Exception:
        return None


def speak_voicevox(text, speaker=None):
    """Say it sentence by sentence, making the next one while the current one plays. False when the engine is not there."""
    import threading
    import winsound
    parts = [p.strip() for p in re.split(r"(?<=[。！!？?\n])", text) if p.strip()]
    if not parts:
        return True
    first = voicevox_wav(parts[0], speaker)
    if first is None:
        return False
    nxt = {}
    for i, part in enumerate(parts):
        wav = first if i == 0 else nxt.get(i)
        worker = None
        if i + 1 < len(parts):
            worker = threading.Thread(target=lambda k=i + 1: nxt.__setitem__(k, voicevox_wav(parts[k], speaker)))
            worker.start()
        if wav:
            winsound.PlaySound(wav, winsound.SND_MEMORY)
        if worker:
            worker.join()
    return True


def speak(text, speaker=None):
    """Read aloud; `speaker` picks the VOICEVOX voice (a meeting gives each session its own)."""
    if not CONFIG["speak"] or not text:
        return
    text = re.sub(r"[*#`>]", "", text)  # markdown marks are not for reading aloud
    if speak_voicevox(text[:CONFIG["talk_chars"]], speaker):
        return
    # the text goes through stdin so no quoting can break the command
    script = ("Add-Type -AssemblyName System.Speech;"
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'ja-JP' } | Select-Object -First 1;"
              "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) };"
              "[Console]::InputEncoding = [Text.Encoding]::UTF8;"
              "$s.Speak([Console]::In.ReadToEnd())")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], input=text[:600], text=True, encoding="utf-8")


def boost(chunk):
    """Raise a quiet microphone so the recognizer can hear it (clipped, never saved)."""
    g = CONFIG["gain"]
    if g == 1:
        return chunk
    a = np.frombuffer(chunk, dtype=np.int16).astype(np.int32) * g
    return np.clip(a, -32768, 32767).astype(np.int16).tobytes()


def wake_recognizer(model):
    """A recognizer that only chooses between the wake phrases and "something else"."""
    phrases = ["ヘイ クロード", "へい クロード", "ねえ クロード", "クロード", "[unk]"]
    return KaldiRecognizer(model, RATE, json.dumps(phrases, ensure_ascii=False))


def main():
    load_config()
    SetLogLevel(-1)
    model = Model(CONFIG["model"])
    audio = queue.Queue()

    def on_audio(data, frames, t, status):
        audio.put(bytes(data))

    put("idle")
    print("聞いています。「ヘイ、クロード」で呼んでください。Ctrl+C で終わります。", flush=True)
    last_check, is_paused = 0.0, False
    last_mic, mic_user = 0.0, None
    last_alive, last_speak = 0.0, 0.0
    device = pick_device(CONFIG["device"])
    print(f"マイク：{sd.query_devices(device, 'input')['name']}", flush=True)
    with sd.RawInputStream(samplerate=RATE, blocksize=4000, dtype="int16", channels=1, callback=on_audio, device=device):
        rec = wake_recognizer(model)
        while True:
            chunk = boost(audio.get())
            if time.time() - last_check > 10:
                last_check, is_paused = time.time(), paused()
            if time.time() - last_mic > 0.5:
                last_mic = time.time()
                other = mic_in_use_by_other() if CONFIG["pause_when_mic_shared"] else None
                if other != mic_user:
                    debug(f"{other} がマイクを使い始めたので休む" if other else f"{mic_user} がマイクを離したので聞き直す")
                    mic_user = other
                    rec = wake_recognizer(model)  # forget what it half-heard meanwhile
            if time.time() - last_alive > 10:  # tell the sessions' talk button the listener is here
                last_alive = time.time()
                try:
                    ALIVE.write_text(str(last_alive), encoding="utf-8")
                except OSError:
                    pass
            if is_paused or mic_user:
                continue
            if time.time() - last_speak > 0.5:  # a session with its talk button on finished a reply
                last_speak = time.time()
                said_one = read_out_reply(model, audio)
                if said_one:
                    while not audio.empty():
                        audio.get_nowait()
                    rec = wake_recognizer(model)
                    continue
            if not LATER.empty():  # a session answered after the wait ran out
                who, heard, ans = LATER.get()
                speak(f"{who}のセッションから返事なのだ。{ans}")
                save_talk(heard, ans, 0, is_first=True, who=f"{who}のセッション（あとから）")
                while not audio.empty():
                    audio.get_nowait()
                rec = wake_recognizer(model)
                continue
            is_final = rec.AcceptWaveform(chunk)
            said = json.loads(rec.Result())["text"] if is_final else json.loads(rec.PartialResult())["partial"]
            if CONFIG["debug"]:
                if is_final and said.replace("[unk]", "").strip():
                    debug(f"合図の候補: {said}")
                if time.time() - S_LEVEL[0] > 5:
                    S_LEVEL[0] = time.time()
                    debug(f"音量（増幅後）: {int(np.abs(np.frombuffer(chunk, dtype=np.int16)).mean())}")
            if "クロード" not in said:
                continue
            # A partial guess can flip ("クラウド" looks like "クロード" for a moment):
            # keep the audio and let the phrase close before trusting it.
            held = [chunk]
            while not is_final and len(held) < 12:
                c = boost(audio.get())
                held.append(c)
                is_final = rec.AcceptWaveform(c)
            final = json.loads(rec.Result() if is_final else rec.FinalResult())["text"]
            rec = wake_recognizer(model)
            if "クロード" not in final:
                debug(f"合図ではなかった: {final}")
                continue
            # the wake word: a short beep, then the words that follow (those already said are in `held`)
            put("listening")
            debug("合図を聞いた")
            warm_dots()
            talk_started = False
            beep()
            text = listen_command(model, audio, held[1:])
            beep_end()
            # Conversation: while the dot ends on a question, its answer needs no wake word.
            # It stays with whoever it started with: a session named in the first words, else the dot.
            target, who = None, "ドット"
            while text:
                debug(f"頼まれた: {text}")
                put("thinking", heard=text)
                t0 = time.time()
                if not talk_started:
                    target, text, miss = route(text)
                    if target:
                        who = f"{bridge().label(target)}のセッション"
                if not talk_started and miss:
                    reply = miss
                elif target:
                    reply = ask_with_ack(text, ask=lambda q=text, s=target: ask_session(s, q), ack=f"{who}に聞いてるのだ")
                else:
                    reply = ask_with_ack(text)
                debug(f"{who}の返事まで {time.time() - t0:.1f}秒")
                put("replied", heard=text, reply=reply)
                save_talk(text, reply, time.time() - t0, is_first=not talk_started, who=who)
                talk_started = True
                t0 = time.time()
                speak(reply)
                debug(f"読み上げ {time.time() - t0:.1f}秒（{len(reply)}字）")
                while not audio.empty():  # drop what the speaker said into the mic
                    audio.get_nowait()
                if not wants_answer(reply):
                    break
                put("listening", reply=reply)
                debug("会話モード：返事を待つ")
                beep()
                text = listen_command(model, audio)
                beep_end()
            rec = wake_recognizer(model)
            put("idle")


QUESTION = re.compile(r"(？|\?|ですか|ますか|ましょうか|どう(する|します)?|どっち|どれ|教えて(ください|ね)?|聞かせて|いい(です)?か|かな)[。！!」）)\s]*$")


def wants_answer(reply):
    """True when the dot ended on a question to the person (its last sentence)."""
    if CONFIG["follow_up"] == "always":
        return True
    if CONFIG["follow_up"] == "off" or not reply:
        return False
    last = [s for s in re.split(r"(?<=[。！!？?\n])", reply.strip()) if s.strip()]
    return bool(last) and bool(QUESTION.search(last[-1].strip()))


ACKS = ["「{q}」だね。調べてるのだ", "「{q}」、ちょっと待ってて", "了解、「{q}」ね。考えてるのだ"]


def ask_with_ack(text, ask=None, ack=None):
    """Ask the dot (or `ask`), and fill the wait: say back what was heard at once, and a word more if it runs long.

    Saying it back also shows a mishearing right away; `ack` replaces the line said back.
    """
    import random
    import threading
    out = {}

    def run():
        try:
            out["reply"] = (ask or ask_dots)(text)
        except Exception as e:  # Dots or the session is not running, or it failed
            out["reply"] = f"届きませんでした（{type(e).__name__}）"

    worker = threading.Thread(target=run)
    worker.start()
    if CONFIG["ack"]:
        q = text if len(text) <= 24 else text[:22] + "…"
        speak(ack or random.choice(ACKS).format(q=q))
        worker.join(max(0.0, CONFIG["still_working_sec"] - 2))
        if worker.is_alive():
            speak("もう少しかかるのだ")
    worker.join()
    return out["reply"]


def beep():
    """High: listening now."""
    try:
        import winsound
        winsound.Beep(880, 120)
    except Exception:
        pass


def beep_end():
    """Low: done listening."""
    try:
        import winsound
        winsound.Beep(587, 110)
    except Exception:
        pass


def listen_command(model, audio, already=()):
    """Wait for speech to start, record until a pause, then recognize it."""
    # The recognizer decides where a sentence ends: a loudness rule fails once a
    # quiet mic is boosted, because room noise then never counts as silence.
    rec = KaldiRecognizer(model, RATE)
    said = []
    for chunk in already:  # heard while the wake phrase closed
        if rec.AcceptWaveform(chunk):
            said.append(json.loads(rec.Result())["text"])
    said = [t for t in said if after_wake(t) != ""]  # a sentence that was only the wake word
    start = time.time()
    while time.time() - start < CONFIG["max_sec"]:
        if rec.AcceptWaveform(boost(audio.get())):
            t = json.loads(rec.Result())["text"]
            if t and after_wake(t) != "":
                said.append(t)
                break
        elif not said and time.time() - start > 6 and not json.loads(rec.PartialResult())["partial"]:
            break  # nothing said after the beep
    else:
        said.append(json.loads(rec.FinalResult())["text"])
    text = squash(" ".join(said))
    return after_wake(text) if after_wake(text) is not None else text


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        put("idle")
        sys.exit(0)
