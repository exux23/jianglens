#!/usr/bin/env python3
"""Tiny local desktop UI for transcribe.py, with no web server or extra packages."""
import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from transcribe import default_output

ROOT = Path(__file__).resolve().parent


def main():
    app = tk.Tk()
    app.title("JiangLens Local Transcriber")
    app.geometry("760x530")
    content = ttk.Frame(app, padding=18)
    content.pack(fill="both", expand=True)
    source = tk.StringVar()
    channel = tk.StringVar(value="@PredictiveHistory")
    output = tk.StringVar(value=str(default_output()))
    diarization = tk.BooleanVar(value=False)
    model = tk.StringVar(value="large-v3")
    proc = [None]
    events = queue.Queue()

    def field(label, variable, browse=False):
        ttk.Label(content, text=label).pack(anchor="w")
        line = ttk.Frame(content)
        line.pack(fill="x", pady=(3, 8))
        ttk.Entry(line, textvariable=variable).pack(side="left", fill="x", expand=True)
        if browse:
            def choose():
                value = filedialog.askdirectory() if browse == "dir" else filedialog.askopenfilename()
                if value:
                    variable.set(value)
            ttk.Button(line, text="Browse", command=choose).pack(side="left", padx=(5, 0))

    field("YouTube video, playlist, channel URL, or local media file", source, "file")
    field("Channel folder", channel)
    field("Output directory", output, "dir")
    options = ttk.Frame(content)
    options.pack(fill="x", pady=(0, 8))
    ttk.Label(options, text="Whisper model").pack(side="left")
    ttk.Combobox(options, state="readonly", width=12, textvariable=model, values=("large-v3", "medium", "small")).pack(side="left", padx=8)
    ttk.Checkbutton(options, text="Identify speakers (requires HF_TOKEN)", variable=diarization).pack(side="left", padx=15)
    controls = ttk.Frame(content)
    controls.pack(fill="x", pady=(0, 8))
    log = tk.Text(content, wrap="word", state="disabled", height=16)
    log.pack(fill="both", expand=True)

    def append(line):
        log.configure(state="normal")
        log.insert("end", line)
        log.see("end")
        log.configure(state="disabled")

    def worker(cmd):
        try:
            proc[0] = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in proc[0].stdout:
                events.put(("log", line))
            code = proc[0].wait()
            events.put(("done", code))
        except Exception as exc:
            events.put(("log", f"Error launching process: {exc}\n"))
            events.put(("done", 1))

    def start():
        if not source.get().strip():
            messagebox.showerror("Missing source", "Enter a YouTube URL or local media file path")
            return
        cmd = [sys.executable, str(ROOT / "transcribe.py"), source.get().strip(), "--channel", channel.get(),
               "--output", output.get(), "--model", model.get()]
        if diarization.get():
            cmd.append("--diarize")
        run.configure(state="disabled")
        stop.configure(state="normal")
        append("Starting...\n")
        threading.Thread(target=worker, args=(cmd,), daemon=True).start()

    def cancel():
        if proc[0] and proc[0].poll() is None:
            proc[0].terminate()
            append("Stopping current run...\n")

    def poll():
        try:
            while True:
                event, value = events.get_nowait()
                if event == "log":
                    append(value)
                else:
                    proc[0] = None
                    run.configure(state="normal")
                    stop.configure(state="disabled")
                    append(f"Finished with exit code {value}.\n")
        except queue.Empty:
            pass
        app.after(100, poll)

    run = ttk.Button(controls, text="Start transcription", command=start)
    run.pack(side="left")
    stop = ttk.Button(controls, text="Stop", command=cancel, state="disabled")
    stop.pack(side="left", padx=8)
    poll()
    app.mainloop()


if __name__ == "__main__":
    main()
