from __future__ import annotations

from dataclasses import dataclass
from typing import Final


WINDOW_BG: Final[str] = "#f5f3ef"
CARD_BG: Final[str] = "#ffffff"
PRIMARY_TEXT: Final[str] = "#1f2937"
SECONDARY_TEXT: Final[str] = "#6b7280"
BUTTON_BG: Final[str] = "#1f2937"
BUTTON_FG: Final[str] = "#ffffff"
ERROR_TEXT: Final[str] = "#b91c1c"


def _default_chrome_profile_dir() -> str:
    return ".chrome-profile"


@dataclass(slots=True)
class Settings:
    search_word: str
    group_links_number: int
    posts_from_each_group: int
    headless: bool = False
    output_file: str = "facebookposts.csv"
    chrome_profile_dir: str = _default_chrome_profile_dir()

    @property
    def expected_table_size(self) -> int:
        return self.group_links_number * self.posts_from_each_group


class SettingsError(ValueError):
    pass


def _try_load_settings_from_gui() -> Settings | None:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return None

    result: Settings | None = None
    cancelled = False

    root = tk.Tk()
    root.title("Facebook Scraper Setup")
    root.geometry("760x520")
    root.minsize(760, 520)
    root.maxsize(920, 660)
    root.configure(bg=WINDOW_BG)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Card.TFrame", background=CARD_BG)
    style.configure("Title.TLabel", background=CARD_BG, foreground=PRIMARY_TEXT, font=("Segoe UI Semibold", 24))
    style.configure("Hint.TLabel", background=CARD_BG, foreground=SECONDARY_TEXT, font=("Segoe UI", 12))
    style.configure("FieldLabel.TLabel", background=CARD_BG, foreground=PRIMARY_TEXT, font=("Segoe UI Semibold", 13))
    style.configure("Input.TEntry", padding=(10, 8), font=("Segoe UI", 13))

    card = ttk.Frame(root, style="Card.TFrame", padding=36)
    card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.86, relheight=0.88)

    search_var = tk.StringVar()
    groups_var = tk.StringVar()
    posts_var = tk.StringVar()
    error_var = tk.StringVar()

    ttk.Label(card, text="Facebook Groups Scraper", style="Title.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(
        card,
        text="Quick setup before run",
        style="Hint.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(6, 26))

    form = ttk.Frame(card, style="Card.TFrame")
    form.grid(row=2, column=0, sticky="n")
    form.columnconfigure(0, minsize=420)

    ttk.Label(form, text="SEARCH IN FACEBOOK", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")
    search_entry = ttk.Entry(form, textvariable=search_var, style="Input.TEntry", font=("Segoe UI", 13), width=38)
    search_entry.grid(row=1, column=0, sticky="w", pady=(8, 16))

    ttk.Label(form, text="GROUP LINKS NUMBER", style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w")
    groups_entry = ttk.Entry(form, textvariable=groups_var, style="Input.TEntry", font=("Segoe UI", 13), width=38)
    groups_entry.grid(row=3, column=0, sticky="w", pady=(8, 16))

    ttk.Label(form, text="POSTS FROM EACH GROUP", style="FieldLabel.TLabel").grid(row=4, column=0, sticky="w")
    posts_entry = ttk.Entry(form, textvariable=posts_var, style="Input.TEntry", font=("Segoe UI", 13), width=38)
    posts_entry.grid(row=5, column=0, sticky="w", pady=(8, 10))

    error_label = ttk.Label(card, textvariable=error_var, style="Hint.TLabel")
    error_label.grid(row=3, column=0, sticky="w", pady=(8, 14))
    error_label.configure(foreground=ERROR_TEXT)

    card.columnconfigure(0, weight=1)

    def _show_error(message: str) -> None:
        error_var.set(message)

    def _submit() -> None:
        nonlocal result
        search_word = search_var.get().strip()
        groups_raw = groups_var.get().strip()
        posts_raw = posts_var.get().strip()

        if not search_word:
            _show_error("Search word is required.")
            return

        try:
            groups_value = int(groups_raw)
            if groups_value <= 0:
                raise ValueError
        except ValueError:
            _show_error("Group links number must be a positive integer.")
            return

        try:
            posts_value = int(posts_raw)
            if posts_value <= 0:
                raise ValueError
        except ValueError:
            _show_error("Posts from each group must be a positive integer.")
            return

        result = Settings(
            search_word=search_word,
            group_links_number=groups_value,
            posts_from_each_group=posts_value,
        )
        root.destroy()

    def _cancel() -> None:
        nonlocal cancelled
        cancelled = True
        root.destroy()

    buttons = ttk.Frame(card, style="Card.TFrame")
    buttons.grid(row=4, column=0, sticky="w", pady=(6, 0))

    cancel_button = tk.Button(
        buttons,
        text="Cancel",
        command=_cancel,
        font=("Segoe UI", 12),
        bg="#e5e7eb",
        fg=PRIMARY_TEXT,
        activebackground="#d1d5db",
        activeforeground=PRIMARY_TEXT,
        relief="flat",
        padx=18,
        pady=8,
        cursor="hand2",
    )
    cancel_button.grid(row=0, column=0, padx=(0, 10))

    run_button = tk.Button(
        buttons,
        text="Run Scraper",
        command=_submit,
        font=("Segoe UI Semibold", 12),
        bg=BUTTON_BG,
        fg=BUTTON_FG,
        activebackground="#111827",
        activeforeground=BUTTON_FG,
        relief="flat",
        padx=20,
        pady=8,
        cursor="hand2",
    )
    run_button.grid(row=0, column=1)

    root.bind("<Return>", lambda _event: _submit())
    root.protocol("WM_DELETE_WINDOW", _cancel)
    search_entry.focus_set()
    root.mainloop()

    if cancelled:
        raise SettingsError("Configuration input was cancelled.")

    return result


def _prompt_non_empty(prompt_text: str) -> str:
    value = input(prompt_text).strip()
    if not value:
        raise SettingsError(f"{prompt_text.strip(': ')} is required.")
    return value


def _prompt_positive_int(prompt_text: str) -> int:
    raw_value = input(prompt_text).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SettingsError(f"{prompt_text.strip(': ')} must be an integer.") from exc
    if value <= 0:
        raise SettingsError(f"{prompt_text.strip(': ')} must be greater than 0.")
    return value


def load_settings() -> Settings:
    gui_settings = _try_load_settings_from_gui()
    if gui_settings is not None:
        return gui_settings

    search_word = _prompt_non_empty("Search word: ")
    group_links_number = _prompt_positive_int("Group links number: ")
    posts_from_each_group = _prompt_positive_int("Posts from each group: ")

    return Settings(
        search_word=search_word,
        group_links_number=group_links_number,
        posts_from_each_group=posts_from_each_group,
    )
