from __future__ import annotations

import logging
import queue
import sys
import threading
from facebook_scraper.config import Settings, SettingsError, load_settings
from facebook_scraper.runner import DriverControl, QueueLogHandler, configure_logging, run_scraper

try:
    import tkinter as tk
    from tkinter import scrolledtext, ttk
except Exception:  # pragma: no cover
    tk = None
    ttk = None
    scrolledtext = None


def run_cli() -> int:
    configure_logging()
    logger = logging.getLogger("facebook_scraper")

    try:
        settings = load_settings()
    except SettingsError as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    return run_scraper(settings)


def run_gui() -> int:
    if tk is None or ttk is None or scrolledtext is None:
        return run_cli()

    class ScraperApp:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.log_queue: queue.Queue[str] = queue.Queue()
            self.log_handler = QueueLogHandler(self.log_queue)
            self.run_control: DriverControl | None = None
            self.is_running = False

            self.search_var = tk.StringVar()
            self.groups_var = tk.StringVar()
            self.posts_var = tk.StringVar()
            self.show_process_var = tk.BooleanVar(value=True)
            self.status_var = tk.StringVar(value="Ready")

            self._build_ui()
            self._poll_logs()

        def _build_ui(self) -> None:
            self.root.title("Facebook Data Extractor")
            self.root.geometry("880x640")
            self.root.minsize(820, 600)
            self.root.configure(bg="#f5f3ef")

            style = ttk.Style(self.root)
            style.theme_use("clam")
            style.configure("App.TFrame", background="#f5f3ef")
            style.configure("Card.TFrame", background="#ffffff")
            style.configure("Heading.TLabel", background="#ffffff", foreground="#111827", font=("Segoe UI Semibold", 28))
            style.configure("Sub.TLabel", background="#ffffff", foreground="#6b7280", font=("Segoe UI", 12))
            style.configure("Label.TLabel", background="#ffffff", foreground="#111827", font=("Segoe UI Semibold", 14))
            style.configure("Status.TLabel", background="#ffffff", foreground="#1f2937", font=("Segoe UI Semibold", 12))

            outer = ttk.Frame(self.root, style="App.TFrame", padding=18)
            outer.pack(fill="both", expand=True)

            card = ttk.Frame(outer, style="Card.TFrame", padding=24)
            card.pack(fill="both", expand=True)
            card.columnconfigure(0, weight=1)
            card.rowconfigure(5, weight=1)

            ttk.Label(card, text="Facebook Data Extractor", style="Heading.TLabel").grid(row=0, column=0, sticky="w")

            form = ttk.Frame(card, style="Card.TFrame")
            form.grid(row=1, column=0, sticky="w", pady=(18, 0))
            form.columnconfigure(0, minsize=430)

            ttk.Label(form, text="SEARCH IN FACEBOOK", style="Label.TLabel").grid(row=0, column=0, sticky="w")
            self.search_entry = ttk.Entry(form, textvariable=self.search_var, font=("Segoe UI", 14), width=36)
            self.search_entry.grid(row=1, column=0, sticky="w", pady=(6, 12))

            ttk.Label(form, text="GROUP LINKS NUMBER", style="Label.TLabel").grid(row=2, column=0, sticky="w")
            self.groups_entry = ttk.Entry(form, textvariable=self.groups_var, font=("Segoe UI", 14), width=36)
            self.groups_entry.grid(row=3, column=0, sticky="w", pady=(6, 12))

            ttk.Label(form, text="POSTS FROM EACH GROUP", style="Label.TLabel").grid(row=4, column=0, sticky="w")
            self.posts_entry = ttk.Entry(form, textvariable=self.posts_var, font=("Segoe UI", 14), width=36)
            self.posts_entry.grid(row=5, column=0, sticky="w", pady=(6, 2))

            self.show_process_checkbox = tk.Checkbutton(
                form,
                text="See the process?",
                variable=self.show_process_var,
                onvalue=True,
                offvalue=False,
                bg="#ffffff",
                activebackground="#ffffff",
                fg="#111827",
                font=("Segoe UI Semibold", 13),
                padx=2,
                pady=6,
            )
            self.show_process_checkbox.grid(row=6, column=0, sticky="w", pady=(8, 4))

            buttons = ttk.Frame(card, style="Card.TFrame")
            buttons.grid(row=2, column=0, sticky="w", pady=(14, 12))

            self.run_button = tk.Button(
                buttons,
                text="Run",
                command=self._start_run,
                font=("Segoe UI Semibold", 13),
                bg="#1f2937",
                fg="#ffffff",
                activebackground="#111827",
                activeforeground="#ffffff",
                relief="flat",
                padx=28,
                pady=9,
                cursor="hand2",
            )
            self.run_button.grid(row=0, column=0, padx=(0, 8))

            self.stop_button = tk.Button(
                buttons,
                text="Stop",
                command=self._stop_run,
                font=("Segoe UI Semibold", 13),
                bg="#b91c1c",
                fg="#ffffff",
                activebackground="#991b1b",
                activeforeground="#ffffff",
                relief="flat",
                padx=24,
                pady=9,
                cursor="hand2",
                state="disabled",
            )
            self.stop_button.grid(row=0, column=1, padx=(0, 8))

            self.clear_button = tk.Button(
                buttons,
                text="Clear Logs",
                command=self._clear_logs,
                font=("Segoe UI", 12),
                bg="#e5e7eb",
                fg="#111827",
                activebackground="#d1d5db",
                activeforeground="#111827",
                relief="flat",
                padx=20,
                pady=9,
                cursor="hand2",
            )
            self.clear_button.grid(row=0, column=2)

            ttk.Label(card, textvariable=self.status_var, style="Status.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 8))
            ttk.Label(card, text="Terminal", style="Label.TLabel").grid(row=4, column=0, sticky="w")

            self.terminal = scrolledtext.ScrolledText(
                card,
                height=16,
                bg="#0f172a",
                fg="#e5e7eb",
                insertbackground="#e5e7eb",
                font=("Consolas", 11),
                wrap="word",
                relief="flat",
                padx=10,
                pady=10,
            )
            self.terminal.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
            self.terminal.configure(state="disabled")

            self.root.bind("<Return>", lambda _event: self._start_run())
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            self.search_entry.focus_set()

        def _append_log(self, line: str) -> None:
            self.terminal.configure(state="normal")
            self.terminal.insert("end", f"{line}\n")
            self.terminal.see("end")
            self.terminal.configure(state="disabled")

        def _clear_logs(self) -> None:
            self.terminal.configure(state="normal")
            self.terminal.delete("1.0", "end")
            self.terminal.configure(state="disabled")

        def _create_settings(self) -> Settings:
            search_word = self.search_var.get().strip()
            if not search_word:
                raise SettingsError("SEARCH IN FACEBOOK is required.")

            try:
                groups = int(self.groups_var.get().strip())
            except ValueError as exc:
                raise SettingsError("GROUP LINKS NUMBER must be an integer.") from exc
            if groups <= 0:
                raise SettingsError("GROUP LINKS NUMBER must be greater than 0.")

            try:
                posts = int(self.posts_var.get().strip())
            except ValueError as exc:
                raise SettingsError("POSTS FROM EACH GROUP must be an integer.") from exc
            if posts <= 0:
                raise SettingsError("POSTS FROM EACH GROUP must be greater than 0.")

            return Settings(
                search_word=search_word,
                group_links_number=groups,
                posts_from_each_group=posts,
                headless=not self.show_process_var.get(),
            )

        def _set_running_ui(self, running: bool) -> None:
            self.is_running = running
            inputs_state = "disabled" if running else "normal"
            run_state = "disabled" if running else "normal"
            stop_state = "normal" if running else "disabled"
            self.run_button.configure(state=run_state)
            self.stop_button.configure(state=stop_state)
            self.search_entry.configure(state=inputs_state)
            self.groups_entry.configure(state=inputs_state)
            self.posts_entry.configure(state=inputs_state)
            self.show_process_checkbox.configure(state=inputs_state)

        def _start_run(self) -> None:
            if self.is_running:
                return
            try:
                settings = self._create_settings()
            except SettingsError as exc:
                self.status_var.set(str(exc))
                self._append_log(f"ERROR | {exc}")
                return

            self._set_running_ui(True)
            self.status_var.set("Running...")
            self.run_control = DriverControl()
            worker = threading.Thread(target=self._worker_run, args=(settings, self.run_control), daemon=True)
            worker.start()

        def _stop_run(self) -> None:
            if not self.is_running or self.run_control is None:
                return
            self.status_var.set("Stopping...")
            self.stop_button.configure(state="disabled")
            self.run_control.request_stop()

        def _worker_run(self, settings: Settings, control: DriverControl) -> None:
            configure_logging(extra_handlers=[self.log_handler])
            logger = logging.getLogger("facebook_scraper")
            logger.info("Run started from GUI.")
            exit_code = run_scraper(settings, control=control)
            self.log_queue.put(f"__RUN_DONE__:{exit_code}")

        def _poll_logs(self) -> None:
            try:
                while True:
                    message = self.log_queue.get_nowait()
                    if message.startswith("__RUN_DONE__:"):
                        code = message.split(":", 1)[1]
                        if code == "0":
                            self.status_var.set("CSV file is ready.")
                        elif code == "2":
                            self.status_var.set("Stopped.")
                        else:
                            self.status_var.set(f"Finished with errors (code {code}).")
                        self.run_control = None
                        self._set_running_ui(False)
                    else:
                        self._append_log(message)
            except queue.Empty:
                pass
            self.root.after(100, self._poll_logs)

        def _on_close(self) -> None:
            if self.is_running:
                self._stop_run()
                self.status_var.set("Stopping run before exit...")
                return
            self.root.destroy()

    app_root = tk.Tk()
    ScraperApp(app_root)
    app_root.mainloop()
    return 0


def main() -> int:
    if "--cli" in sys.argv:
        return run_cli()
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())