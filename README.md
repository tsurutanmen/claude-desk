# claude-desk

Say 「ヘイ、クロード」 to your PC and talk to your Claude Code sessions. Plus a desktop wallpaper that shows what they are doing.

**Windows only.** The listener and the speech are for Japanese.

Three programs:

| File | What it does |
|---|---|
| `wake.py` | Listens to the microphone for 「ヘイ、クロード」. After the beep, say what you want and it goes out as text. The reply is read aloud. |
| `server.py` | One local endpoint (`127.0.0.1:8795/state`) that the wallpaper reads |
| `wallpaper/` | A Wallpaper Engine web wallpaper: open sessions, usage limits, the listener's state |

## What works without the other projects

`wake.py` sends what you say to one of two places:

- 「〇〇のセッションに…」 goes to that Claude Code session through [session-bridge](https://github.com/tsurutanmen/session-bridge). Sessions are found by their `/namae` name or by part of their title. Voice messages are read-only: the session may read, not change anything. The talk button (🔊) of session-bridge also uses this listener to read replies aloud and hear yours.
- Anything else goes to a [homedot](https://github.com/tsurutanmen/homedot) agent on `127.0.0.1:8790`. Without one, you hear that it could not be reached.

So with session-bridge alone you can already talk to your sessions by voice. The wallpaper shows sessions and limits when [session-dash](https://github.com/tsurutanmen/session-dash) is installed.

## Privacy

Speech is recognized on your PC with [Vosk](https://alphacephei.com/vosk/). Audio is never saved or sent. Only the words said after the wake word leave the program, as text, to the places above. Each day's exchanges are kept in `talks/YYYY-MM-DD.md` beside the script.

While another app records from the microphone (Claude's own voice input, Discord, a call), the listener rests and does not react.

## Setup

1. Python 3.11, then in this folder:
   ```
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```
2. Download the Vosk model `vosk-model-small-ja-0.22` and unpack it into `models\`.
3. Optional: [VOICEVOX](https://voicevox.hiroshiba.jp/) for the voice. Put the full path of its `run.exe` in a file named `voicevox.path` beside `start.cmd`. Without it, the Windows Japanese voice reads instead.
4. Optional: copy `wake.config.example.json` to `wake.config.json` and change what you need (the microphone, where session-bridge is, games to pause for).
5. Run `start.cmd`.

For the wallpaper, add the `wallpaper` folder to Wallpaper Engine. If Wallpaper Engine keeps its own copy, write that folder in `desk.config.json` (see `desk.config.example.json`), so `server.py` can put its key there. Without the key, the server answers 403, so no web page can read your sessions.

## Credits

The voices are VOICEVOX:ずんだもん and VOICEVOX:四国めたん (in session-bridge meetings). Using them means following the [VOICEVOX terms](https://voicevox.hiroshiba.jp/term/) and each character's terms.

## Related

Five tools that work together, all MIT:

| | |
|---|---|
| [homedot](https://github.com/tsurutanmen/homedot) | A Dots-style personal agent on Claude Code, in a WSL2 VM on your own PC |
| [session-bridge](https://github.com/tsurutanmen/session-bridge) | Let open Claude Code sessions talk to each other, hold meetings, and answer your voice |
| [claude-desk](https://github.com/tsurutanmen/claude-desk) | "Hey Claude" voice listener with VOICEVOX replies, and a desktop wallpaper of your sessions |
| [homedot-panel](https://github.com/tsurutanmen/homedot-panel) | homedot and the 5-hour limit in Claude Code's status line |
| [session-dash](https://github.com/tsurutanmen/session-dash) | Usage limits above the prompt, and every open session in one pane |

More Claude Code plugins: [tsurutanmen/claude-plugins](https://github.com/tsurutanmen/claude-plugins)

## License

MIT

---

# claude-desk（日本語）

PC に「ヘイ、クロード」と話しかけて、Claude Code のセッションと話せます。セッションが何をしているかを出すデスクトップの壁紙もついています。

**Windows 専用です。** 聞き取りと読み上げは日本語です。

中身は3つです。

| ファイル | すること |
|---|---|
| `wake.py` | マイクで「ヘイ、クロード」を待ちます。ピッと鳴ったら話した言葉を文字にして送り、返事を読み上げます |
| `server.py` | 壁紙が読む、このPCの中だけの口（`127.0.0.1:8795/state`） |
| `wallpaper/` | Wallpaper Engine の壁紙。開いているセッション、使用量、聞き役の様子を出します |

## ほかのものが無くてもどこまで動くか

`wake.py` は話した言葉を2つのどちらかに送ります。

- 「〇〇のセッションに…」は、[session-bridge](https://github.com/tsurutanmen/session-bridge) を通ってそのセッションに届きます。`/namae` の名前か、題名の一部で探します。声からの伝言は読むだけで、セッションは何も書き換えません。session-bridge の会話ボタン 🔊 も、この聞き役を使って返事を読み上げ、こちらの言葉を聞きます。
- それ以外は、`127.0.0.1:8790` の [homedot](https://github.com/tsurutanmen/homedot) に送ります。homedot が無いと「届きませんでした」と言います。

なので session-bridge だけでも、声でセッションと話せます。壁紙のセッションと使用量は、[session-dash](https://github.com/tsurutanmen/session-dash) を入れていると出ます。

## 音とプライバシー

聞き取りは [Vosk](https://alphacephei.com/vosk/) でこのPCの中だけでします。音は保存も送信もしません。外に出るのは、合図のあとに話した言葉を文字にしたものだけで、行き先は上の2つです。やりとりは日ごとに `talks/YYYY-MM-DD.md` に残します。

ほかのアプリがマイクを使っている間（Claude の音声入力、Discord、通話など）は、聞き役は休んで反応しません。

## 準備

1. Python 3.11 を入れて、このフォルダで次を打ちます。
   ```
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```
2. Vosk のモデル `vosk-model-small-ja-0.22` をダウンロードして、`models\` に展開します。
3. 好みで [VOICEVOX](https://voicevox.hiroshiba.jp/) を入れます。`start.cmd` と同じ場所に `voicevox.path` というファイルを作り、`run.exe` の場所を書きます。無いときは Windows の日本語の声で読みます。
4. 好みで `wake.config.example.json` を `wake.config.json` に写して、マイク、session-bridge の場所、止めたいゲームなどを変えます。
5. `start.cmd` を起動します。

壁紙は `wallpaper` フォルダを Wallpaper Engine に入れます。Wallpaper Engine が自分の場所に写しを作るときは、その場所を `desk.config.json` に書いてください（`desk.config.example.json` を参照）。`server.py` がそこに合言葉を置きます。合言葉が無いと 403 を返すので、ほかのウェブページからセッションの様子は読めません。

## クレジット

声は VOICEVOX:ずんだもん と VOICEVOX:四国めたん（session-bridge の会議）です。使うときは [VOICEVOX の利用規約](https://voicevox.hiroshiba.jp/term/) と、各キャラクターの規約に従ってください。

## ライセンス

MIT
