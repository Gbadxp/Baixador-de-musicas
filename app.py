"""Janela do Baixador de Musicas.

Usa o spotDL para baixar musicas, albuns e playlists do Spotify (metadados)
com audio do YouTube, e depois o metadata_fallback.py para conferir capas e
tags. Abra pelo BaixarSpotify.bat ou com: pythonw app.py
"""

import codecs
import datetime
import importlib.util
import json
import os
import queue
import re
import shutil
import site
import ssl
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_NAME = "Baixador de Músicas"
APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "configuracoes.json"
SPOTDL_HOME = Path.home() / ".spotdl"
TOOL_PACKAGES = ["spotdl", "yt-dlp", "ytmusicapi", "brotli", "websockets", "mutagen", "truststore"]
CA_BUNDLE = Path(tempfile.gettempdir()) / "baixador_musicas_certificados.pem"

# Roda o spotDL validando HTTPS pelo Windows (truststore). Sem isso ele falha em
# redes que inspecionam HTTPS, como firewalls de empresa (FortiGate etc.).
SPOTDL_LAUNCHER = (
    "import runpy, truststore; truststore.inject_into_ssl(); "
    "runpy.run_module('spotdl', run_name='__main__', alter_sys=True)"
)
FOLDER_BASES = {
    "spotify": "Musicas_Spotify",
    "youtube": "Musicas_YouTube",
    "generico": "Musicas_Baixadas",
}
LINK_HINTS = {
    "spotify": "Spotify: metadados do Spotify, áudio buscado no YouTube.",
    "youtube": "YouTube: os metadados dependem do que o spotDL identificar.",
    "generico": "Link não reconhecido como Spotify ou YouTube. Vou tentar mesmo assim.",
}

NO_WINDOW = subprocess.CREATE_NO_WINDOW
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PROGRESS_RE = re.compile(r"(\d+)/(\d+) complete")
# Lista final do --print-errors: "<link> - <TipoDoErro>: <mensagem>"
FAILED_RE = re.compile(r"^(https?://\S+) - (\w+(?:Error|Exception)): (.*)$")
# So a verificacao de robo e bloqueio de verdade (restricao de idade nao e).
BLOCKED_RE = re.compile(r"not a bot|po token", re.I)
FAILED_FILE = "musicas_que_falharam.txt"
TEMPORARY_FAILURE = "Erro ao baixar do YouTube (pode dar certo tentando de novo mais tarde)"


class Cancelled(Exception):
    pass


# ----------------------------------------------------------------------------
# Funcoes auxiliares
# ----------------------------------------------------------------------------

def console_python():
    """python.exe ao lado do pythonw.exe, para os comandos terem saida legivel."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def detect_link(url):
    lower = url.lower()
    if "open.spotify.com" in lower or lower.startswith("spotify:"):
        return "spotify"
    if "youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    return "generico"


def find_tool(name):
    exe = name + ".exe"
    candidates = [shutil.which(name), SPOTDL_HOME / exe]
    if name == "ffmpeg":
        candidates.append(Path(r"C:\ffmpeg\bin") / exe)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def missing_packages():
    return [name for name in ("spotdl", "mutagen", "truststore") if importlib.util.find_spec(name) is None]


def windows_ca_bundle():
    """certifi + certificados confiaveis do Windows, para o curl_cffi (que o truststore nao cobre)."""
    import certifi

    parts = [Path(certifi.where()).read_text(encoding="ascii")]
    for store in ("ROOT", "CA"):
        parts += [
            ssl.DER_cert_to_PEM_cert(der)
            for der, encoding, _trust in ssl.enum_certificates(store)
            if encoding == "x509_asn"
        ]
    CA_BUNDLE.write_text("\n".join(parts), encoding="ascii")
    return str(CA_BUNDLE)


def create_folder(base_dir, name):
    """Cria Musicas_Spotify, Musicas_Spotify_2, ... sem nunca reaproveitar uma pasta."""
    folder = Path(base_dir) / name
    count = 1
    while folder.exists():
        count += 1
        folder = Path(base_dir) / f"{name}_{count}"
    folder.mkdir(parents=True)
    return folder


def failure_reason(error, message):
    if error == "LookupError":
        return "Não encontradas no YouTube"
    if "confirm your age" in message:
        return "Com restrição de idade no YouTube (exigem login)"
    return TEMPORARY_FAILURE


def write_failures(folder, failed):
    """Salva as musicas que falharam, agrupadas pelo motivo."""
    groups = {}
    for link, (reason, name) in failed.items():
        groups.setdefault(reason, []).append(f"{name} - {link}" if name else link)
    lines = [f"Músicas que não puderam ser baixadas: {len(failed)}", ""]
    for reason, items in groups.items():
        lines += [f"{reason} ({len(items)}):", *(f"  {item}" for item in sorted(items)), ""]
    (Path(folder) / FAILED_FILE).write_text("\n".join(lines), encoding="utf-8")


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Trabalho em segundo plano (download, verificacao, atualizacao)
# ----------------------------------------------------------------------------

class Job:
    """Roda os comandos fora da janela e manda eventos para ela por uma fila."""

    repaired_this_session = False

    def __init__(self, events):
        self.events = events
        self.python = console_python()
        self.process = None
        self.cancelled = False
        self.ffmpeg = None
        self.cert_env = {}

    # --- comunicacao com a janela ---
    def emit(self, kind, *data):
        self.events.put((kind, *data))

    def log(self, text):
        self.emit("log", text)

    def status(self, text):
        self.emit("status", text)

    def check_cancel(self):
        if self.cancelled:
            raise Cancelled()

    def cancel(self):
        self.cancelled = True
        process = self.process
        if process and process.poll() is None:
            # /T encerra tambem os filhos (ffmpeg, yt-dlp).
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )

    # --- execucao de comandos ---
    def run_command(self, args, cwd=None, log_file=None, on_line=None, env_extra=None, shown=None):
        self.check_cancel()
        env = os.environ.copy()
        # Saida em UTF-8, sem buffer e sem quebrar linhas longas do spotDL.
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", COLUMNS="200", **(env_extra or {}))
        self.log("> " + " ".join(shown or args[1:]))
        self.process = subprocess.Popen(
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=NO_WINDOW,
        )
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        pending = ""

        def handle(raw):
            line = ANSI_RE.sub("", raw).strip()
            if not line:
                return
            self.log(line)
            if log_file:
                log_file.write(line + "\n")
            if on_line:
                on_line(line)

        while True:
            chunk = self.process.stdout.read1(4096)
            if not chunk:
                break
            pending += decoder.decode(chunk)
            *lines, pending = re.split(r"[\r\n]", pending)
            for line in lines:
                handle(line)
        handle(pending + decoder.decode(b"", final=True))
        code = self.process.wait()
        self.check_cancel()
        return code

    def pip_install(self, packages):
        return self.run_command(
            [self.python, "-m", "pip", "install", "-U", "-q", "--disable-pip-version-check", *packages]
        )

    def run_spotdl(self, *args, **kwargs):
        return self.run_command(
            [self.python, "-c", SPOTDL_LAUNCHER, *args],
            env_extra=self.cert_env,
            shown=["spotdl", *args],
            **kwargs,
        )

    def trust_windows_certificates(self):
        """Usa os mesmos certificados que o Windows confia (inclusive os de firewall de empresa)."""
        import truststore

        truststore.inject_into_ssl()  # buscas de capas/tags feitas por esta janela
        bundle = windows_ca_bundle()
        self.cert_env = {name: bundle for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")}

    # --- ferramentas ---
    def ensure_tools(self):
        if missing_packages():
            self.status("Instalando spotDL e Mutagen (só na primeira vez)...")
            if self.pip_install(TOOL_PACKAGES) != 0:
                raise RuntimeError("Não foi possível instalar o spotDL. Veja os detalhes abaixo.")
            # O pip pode ter criado agora a pasta de pacotes do usuario, que o
            # Python so poe no sys.path se ela ja existia quando o app abriu.
            site.addsitedir(site.getusersitepackages())
            importlib.invalidate_caches()
            if missing_packages():
                raise RuntimeError("O spotDL foi instalado, mas não pôde ser carregado. Feche e abra o app de novo.")
        self.trust_windows_certificates()

        self.ffmpeg = find_tool("ffmpeg")
        if not self.ffmpeg:
            self.status("Baixando o FFmpeg (só na primeira vez)...")
            self.run_spotdl("--download-ffmpeg")
            self.ffmpeg = find_tool("ffmpeg")
            if not self.ffmpeg:
                raise RuntimeError("O FFmpeg não foi encontrado nem pôde ser baixado.")

        if not find_tool("deno"):
            self.status("Baixando o Deno (só na primeira vez)...")
            self.run_spotdl("--download-deno")
            if not find_tool("deno"):
                self.log("[AVISO] O Deno não pôde ser instalado. Algumas músicas do YouTube podem falhar.")

    def update_tools(self):
        """Atualiza spotDL/yt-dlp: resolve a maioria dos erros do YouTube."""
        self.status("Atualizando spotDL e yt-dlp...")
        code = self.pip_install(TOOL_PACKAGES)
        if not find_tool("deno") and not missing_packages():
            self.trust_windows_certificates()
            self.run_spotdl("--download-deno")
        Job.repaired_this_session = code == 0
        return code

    # --- download ---
    def spotdl(self, url, folder, attempt):
        args = [
            "download", url,
            "--audio", "youtube", "youtube-music",
            "--format", "mp3",
            "--threads", "4",
            "--max-retries", "5",
            "--simple-tui",
            "--print-errors",
        ]
        if self.ffmpeg:
            args += ["--ffmpeg", self.ffmpeg]

        result = {"failed": {}, "blocked": False}

        def on_line(line):
            match = PROGRESS_RE.search(line)
            if match:
                self.emit("progress", int(match.group(1)), int(match.group(2)))
            match = FAILED_RE.match(line)
            if match:
                link, error, message = match.groups()
                name = message.split("for song:", 1)[1].strip() if "for song:" in message else ""
                result["failed"][link] = (failure_reason(error, message), name)
            if BLOCKED_RE.search(line):
                result["blocked"] = True

        self.emit("busy")
        with open(Path(folder) / "download_log.txt", "a", encoding="utf-8") as log_file:
            log_file.write("=" * 60 + "\n")
            log_file.write(f"{attempt}: {datetime.datetime.now():%d/%m/%Y %H:%M:%S}\n")
            log_file.write(f"Link: {url}\n")
            code = self.run_spotdl(*args, cwd=folder, log_file=log_file, on_line=on_line)
            log_file.write(f"Resultado: código {code}, {len(result['failed'])} música(s) com falha\n")
        result["code"] = code
        return result

    def download(self, url, base_dir):
        self.status("Verificando ferramentas...")
        self.emit("busy")
        self.ensure_tools()
        import metadata_fallback

        kind = detect_link(url)
        folder = create_folder(base_dir, FOLDER_BASES[kind])
        self.emit("folder", str(folder))
        self.log(f"Pasta criada: {folder}")

        self.status("Baixando músicas...")
        result = self.spotdl(url, folder, "Tentativa 1")
        temporary = [link for link, (reason, _name) in result["failed"].items() if reason == TEMPORARY_FAILURE]
        # So repete falhas temporarias (ou se o spotDL parou sem listar erros);
        # musica que nao existe no YouTube continuaria nao existindo.
        if temporary or (result["code"] != 0 and not result["failed"]):
            if Job.repaired_this_session:
                self.status("Algumas músicas falharam. Tentando de novo...")
            else:
                self.status("Algumas músicas falharam. Atualizando yt-dlp e tentando de novo...")
                self.update_tools()
            # Musicas ja baixadas sao puladas pelo spotDL; so as que faltam sao refeitas.
            result = self.spotdl(url, folder, "Tentativa 2 (após reparo)")
        if result["failed"]:
            write_failures(folder, result["failed"])
            self.log(f"Lista das músicas que falharam salva em {FAILED_FILE}.")

        self.status("Conferindo capas e tags...")
        self.emit("busy")
        summary = metadata_fallback.run(folder, log=self.log, stop=lambda: self.cancelled)
        if summary["set_aside"]:
            # Arquivos sem capa foram separados; baixa de novo e devolve o que nao vier.
            try:
                self.status(f"Baixando de novo {summary['set_aside']} música(s) sem capa...")
                self.spotdl(url, folder, "Nova tentativa (sem capa)")
            finally:
                if self.cancelled:
                    metadata_fallback.restore_set_aside(Path(folder))
            self.status("Conferindo capas e tags novamente...")
            self.emit("busy")
            summary = metadata_fallback.run(folder, final=True, log=self.log, stop=lambda: self.cancelled)
        if self.cancelled:
            metadata_fallback.restore_set_aside(Path(folder))
            raise Cancelled()

        return {
            "folder": str(folder),
            "files": len(metadata_fallback.list_mp3(folder)),
            "summary": summary,
            "failed": len(result["failed"]),
            "blocked": result["blocked"],
        }

    # --- pontos de entrada das threads ---
    def run_download(self, url, base_dir):
        self._run(lambda: ("download", self.download(url, base_dir)))

    def run_update(self):
        self._run(lambda: ("update", self.update_tools()))

    def _run(self, task):
        try:
            kind, result = task()
            self.emit("finished", kind, "ok", result)
        except Cancelled:
            self.emit("finished", "", "cancelled", None)
        except Exception as exc:
            self.log(f"[ERRO] {exc}")
            self.emit("finished", "", "error", str(exc))


# ----------------------------------------------------------------------------
# Janela
# ----------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("780x620")
        self.minsize(620, 480)

        self.settings = load_settings()
        self.events = queue.Queue()
        self.job = None
        self.folder = None

        self._setup_style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.poll_events)

    # --- aparencia ---
    def _setup_style(self):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family="Segoe UI", size=10)
        tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=9)

        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("Muted.TLabel", foreground="#5f6368")
        style.configure("Status.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("Ok.Status.TLabel", foreground="#1a7f37")
        style.configure("Warn.Status.TLabel", foreground="#9a6700")
        style.configure("Error.Status.TLabel", foreground="#cf222e")
        style.configure("Big.TButton", font=("Segoe UI Semibold", 11), padding=(18, 6))

    def _build(self):
        main = ttk.Frame(self, padding=18)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        intro = ttk.Label(
            main,
            text="Cole o link de uma música, álbum ou playlist do Spotify ou do YouTube. "
            "As músicas são salvas em MP3 com capa e tags.",
            style="Muted.TLabel",
            wraplength=720,
        )
        intro.grid(row=1, column=0, sticky="we", pady=(2, 14))

        # Link
        ttk.Label(main, text="Link").grid(row=2, column=0, sticky="w")
        link_row = ttk.Frame(main)
        link_row.grid(row=3, column=0, sticky="we")
        link_row.columnconfigure(0, weight=1)
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", lambda *_: self.update_link_hint())
        self.url_entry = ttk.Entry(link_row, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=0, sticky="we", ipady=3)
        self.url_entry.bind("<Return>", lambda _: self.start_download())
        self.paste_button = ttk.Button(link_row, text="Colar", command=self.paste_link)
        self.paste_button.grid(row=0, column=1, padx=(8, 0))
        self.link_hint = ttk.Label(main, text=" ", style="Muted.TLabel")
        self.link_hint.grid(row=4, column=0, sticky="w", pady=(3, 10))

        # Pasta de destino
        ttk.Label(main, text="Salvar em").grid(row=5, column=0, sticky="w")
        folder_row = ttk.Frame(main)
        folder_row.grid(row=6, column=0, sticky="we")
        folder_row.columnconfigure(0, weight=1)
        self.base_dir_var = tk.StringVar(value=self.settings.get("pasta_destino") or str(APP_DIR))
        ttk.Entry(folder_row, textvariable=self.base_dir_var, state="readonly").grid(
            row=0, column=0, sticky="we", ipady=3
        )
        self.choose_button = ttk.Button(folder_row, text="Alterar...", command=self.choose_base_dir)
        self.choose_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(
            main,
            text="Cada download ganha uma pasta nova (Musicas_Spotify, Musicas_Spotify_2...).",
            style="Muted.TLabel",
        ).grid(row=7, column=0, sticky="w", pady=(3, 14))

        # Acoes
        actions = ttk.Frame(main)
        actions.grid(row=8, column=0, sticky="we")
        actions.columnconfigure(2, weight=1)
        self.download_button = ttk.Button(
            actions, text="Baixar", style="Big.TButton", command=self.start_download
        )
        self.download_button.grid(row=0, column=0)
        self.cancel_button = ttk.Button(actions, text="Cancelar", command=self.cancel_job, state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=(8, 0))
        self.open_button = ttk.Button(actions, text="Abrir pasta", command=self.open_folder, state="disabled")
        self.open_button.grid(row=0, column=3)

        # Progresso
        self.status_label = ttk.Label(main, text="Pronto.", style="Status.TLabel", wraplength=720)
        self.status_label.grid(row=9, column=0, sticky="w", pady=(16, 4))
        # Textos longos quebram linha conforme a largura da janela.
        main.bind(
            "<Configure>",
            lambda event: [label.configure(wraplength=max(event.width - 40, 200)) for label in (intro, self.status_label)],
        )
        progress_row = ttk.Frame(main)
        progress_row.grid(row=10, column=0, sticky="we")
        progress_row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=1, value=0)
        self.progress.grid(row=0, column=0, sticky="we")
        self.counter_label = ttk.Label(progress_row, text="", width=10, anchor="e", style="Muted.TLabel")
        self.counter_label.grid(row=0, column=1, padx=(8, 0))

        # Detalhes
        ttk.Label(main, text="Detalhes", style="Muted.TLabel").grid(row=11, column=0, sticky="w", pady=(14, 2))
        log_frame = ttk.Frame(main)
        log_frame.grid(row=12, column=0, sticky="nsew")
        main.rowconfigure(12, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            height=10,
            wrap="word",
            state="disabled",
            font="TkFixedFont",
            relief="solid",
            borderwidth=1,
            background="#fafafa",
            padx=8,
            pady=6,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        # Rodape
        footer = ttk.Frame(main)
        footer.grid(row=13, column=0, sticky="we", pady=(10, 0))
        footer.columnconfigure(1, weight=1)
        self.update_button = ttk.Button(footer, text="Atualizar ferramentas", command=self.start_update)
        self.update_button.grid(row=0, column=0)
        ttk.Label(
            footer,
            text="Use só com conteúdo que você tem direito de baixar.",
            style="Muted.TLabel",
        ).grid(row=0, column=1, sticky="e")

        self.url_entry.focus_set()

    # --- interacoes ---
    def update_link_hint(self):
        url = self.url_var.get().strip()
        self.link_hint.configure(text=LINK_HINTS[detect_link(url)] if url else " ")

    def paste_link(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        self.url_var.set(text.strip().strip('"'))
        self.url_entry.icursor("end")

    def choose_base_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.base_dir_var.get(), title="Onde salvar as músicas?")
        if chosen:
            self.base_dir_var.set(str(Path(chosen)))
            self.settings["pasta_destino"] = str(Path(chosen))
            save_settings(self.settings)

    def open_folder(self):
        if self.folder and Path(self.folder).exists():
            os.startfile(self.folder)

    def set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.download_button, self.update_button, self.choose_button, self.paste_button):
            widget.configure(state=state)
        self.url_entry.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def set_status(self, text, kind=""):
        self.status_label.configure(text=text, style=f"{kind}.Status.TLabel" if kind else "Status.TLabel")

    def append_log(self, text):
        at_bottom = self.log_text.yview()[1] >= 0.999
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 5000:
            self.log_text.delete("1.0", f"{lines - 5000}.0")
        self.log_text.configure(state="disabled")
        if at_bottom:
            self.log_text.see("end")

    def start_progress(self):
        self.counter_label.configure(text="")
        if str(self.progress.cget("mode")) != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)

    def stop_progress(self, filled):
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=1, value=1 if filled else 0)

    def start_job(self, target, *args):
        self.job = Job(self.events)
        self.set_busy(True)
        self.thread = threading.Thread(target=target, args=(self.job, *args), daemon=True)
        self.thread.start()

    def start_download(self):
        if self.job:
            return
        url = self.url_var.get().strip().strip('"')
        if not url:
            self.set_status("Cole um link primeiro.", "Warn")
            self.url_entry.focus_set()
            return
        base_dir = self.base_dir_var.get()
        if not Path(base_dir).is_dir():
            self.set_status("A pasta de destino não existe. Escolha outra em \"Alterar...\".", "Error")
            return

        self.folder = None
        self.open_button.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.set_status("Começando...")
        self.start_job(Job.run_download, url, base_dir)

    def start_update(self):
        if self.job:
            return
        self.set_status("Atualizando ferramentas...")
        self.start_job(Job.run_update)

    def cancel_job(self):
        if self.job:
            self.set_status("Cancelando...", "Warn")
            self.cancel_button.configure(state="disabled")
            threading.Thread(target=self.job.cancel, daemon=True).start()

    def on_close(self):
        if self.job:
            if not messagebox.askyesno(APP_NAME, "Um download está em andamento. Cancelar e fechar?"):
                return
            self.job.cancel()
            # Da tempo de devolver musicas separadas para nova tentativa.
            self.thread.join(timeout=10)
        self.destroy()

    # --- eventos vindos da thread ---
    def poll_events(self):
        try:
            for _ in range(300):
                event = self.events.get_nowait()
                self.handle_event(*event)
        except queue.Empty:
            pass
        self.after(100, self.poll_events)

    def handle_event(self, kind, *data):
        if kind == "log":
            self.append_log(data[0])
        elif kind == "status":
            self.set_status(data[0])
        elif kind == "busy":
            self.start_progress()
        elif kind == "progress":
            done, total = data
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=max(total, 1), value=done)
            self.counter_label.configure(text=f"{done} de {total}")
        elif kind == "folder":
            self.folder = data[0]
            self.open_button.configure(state="normal")
        elif kind == "finished":
            self.finish(*data)

    def finish(self, task, state, result):
        self.job = None
        self.set_busy(False)

        if state == "cancelled":
            self.stop_progress(False)
            self.set_status("Cancelado.", "Warn")
            return
        if state == "error":
            self.stop_progress(False)
            self.set_status("Não foi possível concluir. Veja os detalhes abaixo.", "Error")
            messagebox.showerror(APP_NAME, result)
            return

        self.stop_progress(True)
        if task == "update":
            if result == 0:
                self.set_status("Ferramentas atualizadas.", "Ok")
            else:
                self.set_status("A atualização falhou. Veja os detalhes abaixo.", "Error")
            return

        self.counter_label.configure(text="")
        files = result["files"]
        summary = result["summary"]
        folder_name = Path(result["folder"]).name
        if files == 0:
            self.stop_progress(False)
            message = "Nenhuma música foi baixada."
            if result["blocked"]:
                message += " O YouTube bloqueou a sessão; tente mais tarde."
            self.set_status(message, "Error")
            return

        notes = []
        if result["failed"]:
            notes.append(f"{result['failed']} não puderam ser baixadas (veja {FAILED_FILE})")
        tag_notes = []
        if summary["without_cover"]:
            tag_notes.append(f"{summary['without_cover']} sem capa")
        if summary["incomplete"]:
            tag_notes.append(f"{summary['incomplete']} com tags incompletas")
        if tag_notes:
            notes.append(", ".join(tag_notes) + " (veja metadata_report.txt)")
        text = f"Concluído: {files} música(s) em {folder_name}."
        if notes:
            text += " Atenção: " + "; ".join(notes) + "."
        if result["blocked"]:
            text += " O YouTube bloqueou parte dos downloads; tente mais tarde."
        self.set_status(text, "Warn" if notes or result["blocked"] else "Ok")
        self.append_log("")
        self.append_log(text)


def enable_dpi_awareness():
    """Evita texto borrado em telas com escala acima de 100% no Windows."""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main():
    enable_dpi_awareness()
    App().mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        # Aberto com pythonw nao ha terminal: mostra o erro numa caixa.
        messagebox.showerror(APP_NAME, "O aplicativo não conseguiu abrir.\n\n" + traceback.format_exc()[-1500:])
        raise
