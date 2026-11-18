#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAM Plus EXE — kalkulator i konfigurator kompresji pamięci (zram / plik wymiany).

Desktopowy odpowiednik aplikacji RAM Plus A17.

WAŻNE: program liczy pojemność LOGICZNĄ (kompresja w RAM), a nie fizyczny RAM.
Nie dodaje pamięci — pokazuje, ile danych zmieści się w tej samej kości po
skompresowaniu i ile z tego zostaje dla programów.

Uruchomienie:  python app.py
Budowanie:     pyinstaller --onefile --windowed --name "RAM-Plus" app.py
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

APP_NAME = "RAM Plus"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

# Współczynniki na typowych danych z pamięci (strony jądra, sterty aplikacji,
# cache). Na realnym systemie wychodzi zwykle 2,4-3,2:1.
ALGOS = {
    "lz4": {
        "ratio": 2.3,
        "cpu": 1.0,
        "latency_us": 45,
        "speed": "~400 MB/s",
        "note": "Najszybszy, najniższy współczynnik. Domyślny w wielu systemach.",
    },
    "lz4hc": {
        "ratio": 2.8,
        "cpu": 2.4,
        "latency_us": 60,
        "speed": "~120 MB/s",
        "note": "Ten sam tani dekoder co lz4, mocniejsza kompresja przy zapisie. "
                "Najlepszy stosunek zysku do kosztu.",
    },
    "zstd": {
        "ratio": 3.2,
        "cpu": 3.1,
        "latency_us": 95,
        "speed": "~90 MB/s",
        "note": "Najlepsza kompresja, najdroższy CPU. Odczuwalnie grzeje przy dużym swapie.",
    },
    "lzo-rle": {
        "ratio": 2.5,
        "cpu": 1.3,
        "latency_us": 50,
        "speed": "~300 MB/s",
        "note": "RLE dobrze łapie zera w stronach jądra. Kompromis.",
    },
}

DEFAULT_ALGO = "lz4hc"
SIZES_GIB = [2, 3, 4, 6]

VERDICTS = {
    "komfort": ("Komfort", "#1E9E62",
                "System ma zapas, programy w tle przeżywają. Bezpieczny wybór."),
    "zalecane": ("Zalecane", "#1E9E62",
                 "Działa, ale przy kilku ciężkich programach zacznie brakować pamięci."),
    "granica": ("Granica", "#C77700",
                "System ledwo oddycha. Przełączanie programów będzie przeładowywać."),
    "cegla": ("Cegła", "#D93F3F",
              "Brak miejsca dla systemu. Komputer wstanie, ale nie uruchomi programów."),
}


def compute_budget(ram_gib: float, overhead_gib: float, size_gib: float, algo: str) -> dict:
    """Bilans pamięci. Wszystko w GiB."""
    a = ALGOS[algo]
    content_gib = size_gib * a["ratio"]
    mem_used_gib = size_gib / a["ratio"]
    free_gib = ram_gib - overhead_gib - mem_used_gib

    if free_gib >= 0.7:
        key = "komfort"
    elif free_gib >= 0.4:
        key = "zalecane"
    elif free_gib >= 0.15:
        key = "granica"
    else:
        key = "cegla"

    label, color, detail = VERDICTS[key]
    return {
        "ram_gib": ram_gib,
        "overhead_gib": overhead_gib,
        "size_gib": size_gib,
        "algo": algo,
        "content_gib": content_gib,
        "mem_used_gib": mem_used_gib,
        "free_gib": free_gib,
        "verdict": key,
        "verdict_label": label,
        "verdict_color": color,
        "verdict_detail": detail,
        "saved_pct": (1 - 1 / a["ratio"]) * 100,
    }


def parse_stats(text: str):
    """
    Parsuje statystyki kompresji. Obsługuje:
      - linię mm_stat: orig compr mem_used ...
      - pary "klucz: wartość" (np. z /proc/meminfo lub własnego raportu)
    Zwraca dict albo None.
    """
    if not text or not text.strip():
        return None

    # 1) Spróbuj pary klucz: wartość
    pairs = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip().split()[0] if v.strip() else ""
            try:
                pairs[k] = float(v)
            except ValueError:
                continue
    if "orig_data_size" in pairs and "compr_data_size" in pairs:
        orig = pairs["orig_data_size"]
        compr = pairs["compr_data_size"]
        used = pairs.get("mem_used_total", compr)
        return _stats(orig, compr, used)

    # 2) Linia liczb (mm_stat)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                nums = [float(p) for p in parts[:3]]
            except ValueError:
                continue
            if nums[0] > 0:
                return _stats(nums[0], nums[1], nums[2])
    return None


def _stats(orig: float, compr: float, used: float):
    if orig <= 0 or compr <= 0:
        return None
    return {
        "orig": orig,
        "compr": compr,
        "used": used,
        "ratio": orig / compr,
        "overhead": used / orig,
        "saved_pct": (1 - compr / orig) * 100,
    }


def judge_ratio(ratio: float):
    if ratio >= 2.5:
        return "Dobrze", "#1E9E62", "Kompresja pracuje jak należy — mnoży pojemność."
    if ratio >= 2.0:
        return "Ciasno", "#C77700", "Dane słabo się ściskają (multimedia, archiwa)."
    return "Nie warto", "#D93F3F", "Poniżej 2,0:1 kompresja zjada więcej, niż daje."


def format_bytes(n: float) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GiB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n:.0f} B"


# ---------------------------------------------------------------------------
# Generatory komend
# ---------------------------------------------------------------------------

def setup_commands(size_gib: float, algo: str) -> str:
    b = int(size_gib * 1024 ** 3)
    return f"""# 1. Zaladuj modul zram (Linux; na Windows nie dotyczy)
modprobe zram num_devices=1

# 2. Algorytm PRZED rozmiarem - po ustawieniu disksize jest za pozno
echo {algo} > /sys/block/zram0/comp_algorithm

# 3. Rozmiar urzadzenia
echo {b} > /sys/block/zram0/disksize

# 4. Format i wlaczenie z priorytetem 100
mkswap /dev/block/zram0
swapon -p 100 /dev/block/zram0

# 5. Tuning jadra
echo 100 > /proc/sys/vm/swappiness
echo 0 > /proc/sys/vm/page-cluster

# 6. Sprawdz
zramctl
cat /proc/swaps"""


def teardown_commands() -> str:
    return """# Wylacz swap na zram
swapoff /dev/block/zram0

# Zresetuj urzadzenie (zwalnia caly RAM)
echo 1 > /sys/block/zram0/reset

# Sprawdz, ze zniknelo
zramctl
cat /proc/swaps"""


def persist_commands(size_gib: float, algo: str) -> str:
    b = int(size_gib * 1024 ** 3)
    return f"""# /etc/systemd/system/zram-setup.service  (Linux)
# lub /data/adb/service.d/99-zram.sh na Androidzie z Magiskiem

[Unit]
Description=zram swap
After=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/modprobe zram num_devices=1
ExecStart=/bin/sh -c 'echo {algo} > /sys/block/zram0/comp_algorithm'
ExecStart=/bin/sh -c 'echo {b} > /sys/block/zram0/disksize'
ExecStart=/sbin/mkswap /dev/zram0
ExecStart=/sbin/swapon -p 100 /dev/zram0
ExecStart=/bin/sh -c 'echo 100 > /proc/sys/vm/swappiness'
ExecStart=/bin/sh -c 'echo 0 > /proc/sys/vm/page-cluster'

[Install]
WantedBy=multi-user.target"""


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

BG = "#0E1016"
CARD = "#181B24"
TEXT = "#F2F4F8"
MUTED = "#9AA3B2"
BORDER = "#2A2F3B"
PRIMARY = "#7FA3FF"
SUCCESS = "#4ADE80"
WARNING = "#FBBF24"
DANGER = "#FF6B6B"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION} — pojemnosc LOGICZNA, nie fizyczny RAM")
        self.geometry("880x760")
        self.minsize(760, 640)
        self.configure(bg=BG)

        # Stan współdzielony między zakładkami
        self.ram_var = tk.StringVar(value="4")
        self.overhead_var = tk.StringVar(value="2.0")
        self.size_var = tk.IntVar(value=3)
        self.algo_var = tk.StringVar(value=DEFAULT_ALGO)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=MUTED,
                        padding=(16, 8), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", PRIMARY)],
                  foreground=[("selected", "#0E1016")])
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED)
        style.configure("H1.TLabel", background=BG, foreground=TEXT,
                        font=("Segoe UI", 18, "bold"))
        style.configure("H2.TLabel", background=CARD, foreground=TEXT,
                        font=("Segoe UI", 12, "bold"))
        style.configure("Big.TLabel", background=CARD, foreground=TEXT,
                        font=("Segoe UI", 22, "bold"))
        style.configure("TButton", padding=(12, 6))
        style.configure("TRadiobutton", background=CARD, foreground=TEXT)
        style.configure("TCheckbutton", background=CARD, foreground=TEXT)

        header = ttk.Frame(self, style="TFrame")
        header.pack(fill="x", padx=16, pady=(14, 6))
        ttk.Label(header, text=f"{APP_NAME} — kalkulator kompresji pamieci",
                  style="H1.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Pojemnosc LOGICZNA: kompresja w RAM. To nie jest dodatkowa kosc pamieci.",
            style="TLabel", foreground=WARNING,
        ).pack(anchor="w", pady=(2, 0))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(6, 16))

        self.tab_budget = ttk.Frame(self.nb, style="TFrame")
        self.tab_setup = ttk.Frame(self.nb, style="TFrame")
        self.tab_verify = ttk.Frame(self.nb, style="TFrame")
        self.tab_algos = ttk.Frame(self.nb, style="TFrame")

        self.nb.add(self.tab_budget, text="Budzet")
        self.nb.add(self.tab_setup, text="Konfiguracja")
        self.nb.add(self.tab_verify, text="Weryfikacja")
        self.nb.add(self.tab_algos, text="Algorytmy")

        self._build_budget()
        self._build_setup()
        self._build_verify()
        self._build_algos()

        self.refresh_budget()

    # -- pomocnicze ---------------------------------------------------------

    def card(self, parent, **pack):
        f = ttk.Frame(parent, style="Card.TFrame", padding=14)
        f.pack(fill="x", **pack)
        return f

    def kv(self, parent, label, value, color=TEXT, bold=False):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=1)
        ttk.Label(row, text=label, style="Muted.TLabel").pack(side="left")
        ttk.Label(row, text=value, style="Card.TLabel", foreground=color,
                  font=("Segoe UI", 10, "bold" if bold else "normal")).pack(side="right")
        return row

    # -- zakładka Budżet ----------------------------------------------------

    def _build_budget(self):
        p = self.tab_budget

        c = self.card(p, pady=(0, 10))
        ttk.Label(c, text="PARAMETRY", style="Muted.TLabel").pack(anchor="w")
        grid = ttk.Frame(c, style="Card.TFrame")
        grid.pack(fill="x", pady=(6, 0))
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)

        ttk.Label(grid, text="RAM fizyczny (GiB)", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", pady=3)
        e1 = ttk.Entry(grid, textvariable=self.ram_var, width=10)
        e1.grid(row=0, column=1, sticky="w", padx=(8, 20))
        e1.bind("<KeyRelease>", lambda _e: self.refresh_budget())

        ttk.Label(grid, text="System / overhead (GiB)", style="Muted.TLabel").grid(
            row=0, column=2, sticky="w", pady=3)
        e2 = ttk.Entry(grid, textvariable=self.overhead_var, width=10)
        e2.grid(row=0, column=3, sticky="w", padx=(8, 0))
        e2.bind("<KeyRelease>", lambda _e: self.refresh_budget())

        ttk.Label(grid, text="Rozmiar zram (GiB)", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=3)
        cb = ttk.Combobox(grid, textvariable=self.size_var, width=8, state="readonly",
                          values=SIZES_GIB)
        cb.grid(row=1, column=1, sticky="w", padx=(8, 20))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh_budget())

        ttk.Label(grid, text="Algorytm", style="Muted.TLabel").grid(
            row=1, column=2, sticky="w", pady=3)
        cb2 = ttk.Combobox(grid, textvariable=self.algo_var, width=10, state="readonly",
                           values=list(ALGOS.keys()))
        cb2.grid(row=1, column=3, sticky="w", padx=(8, 0))
        cb2.bind("<<ComboboxSelected>>", lambda _e: self.refresh_budget())

        ttk.Label(c, text="Domyslnie 4 GiB / 2,0 GiB — jak Samsung Galaxy A17 (4 GB RAM).",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        self.verdict_card = self.card(p, pady=(0, 10))
        self.verdict_label = ttk.Label(self.verdict_card, text="", style="Big.TLabel")
        self.verdict_label.pack(anchor="w")
        self.verdict_detail = ttk.Label(self.verdict_card, text="", style="Muted.TLabel",
                                        wraplength=780, justify="left")
        self.verdict_detail.pack(anchor="w", pady=(4, 0))

        self.balance_card = self.card(p, pady=(0, 10))
        ttk.Label(self.balance_card, text="BILANS PAMIECI", style="Muted.TLabel").pack(anchor="w")
        self.balance_body = ttk.Frame(self.balance_card, style="Card.TFrame")
        self.balance_body.pack(fill="x", pady=(6, 0))

        self.gain_card = self.card(p, pady=(0, 10))
        ttk.Label(self.gain_card, text="CO DAJE KOMPRESJA", style="Muted.TLabel").pack(anchor="w")
        self.gain_body = ttk.Frame(self.gain_card, style="Card.TFrame")
        self.gain_body.pack(fill="x", pady=(6, 0))

        warn = self.card(p)
        ttk.Label(warn, text="⚠  TO POJEMNOSC LOGICZNA", style="H2.TLabel",
                  foreground=WARNING).pack(anchor="w")
        ttk.Label(
            warn,
            text="Kompresja nie dodaje kosci pamieci. Te same 4 GiB przechowuja 2,8 GiB "
                 "danych na kazdy 1 GiB, ale tylko wtedy, gdy dane sa scisliwe i stac Cie "
                 "na CPU. Fizyczny RAM pozostaje bez zmian.",
            style="Muted.TLabel", wraplength=780, justify="left",
        ).pack(anchor="w", pady=(4, 0))

    def refresh_budget(self):
        try:
            ram = float(self.ram_var.get().replace(",", "."))
            overhead = float(self.overhead_var.get().replace(",", "."))
        except ValueError:
            return
        if ram <= 0:
            return
        size = float(self.size_var.get())
        algo = self.algo_var.get()
        if algo not in ALGOS:
            return

        b = compute_budget(ram, overhead, size, algo)

        self.verdict_label.configure(text=f"Werdykt: {b['verdict_label']}",
                                     foreground=b["verdict_color"])
        self.verdict_detail.configure(text=b["verdict_detail"])

        for w in self.balance_body.winfo_children():
            w.destroy()
        self.kv(self.balance_body, "RAM fizyczny", f"{b['ram_gib']:.2f} GiB")
        self.kv(self.balance_body, "− system / overhead", f"−{b['overhead_gib']:.2f} GiB", MUTED)
        self.kv(self.balance_body,
                f"− zram ({size:.0f} GiB ÷ {ALGOS[algo]['ratio']}:1)",
                f"−{b['mem_used_gib']:.2f} GiB", MUTED)
        self.kv(self.balance_body, "= wolne dla programow",
                f"{b['free_gib']:.2f} GiB", b["verdict_color"], bold=True)

        for w in self.gain_body.winfo_children():
            w.destroy()
        self.kv(self.gain_body, "Tresc w zram (po kompresji)",
                f"{b['content_gib']:.1f} GiB")
        self.kv(self.gain_body, "Wspolczynnik", f"{ALGOS[algo]['ratio']}:1")
        self.kv(self.gain_body, "Oszczednosc vs brak kompresji",
                f"{b['saved_pct']:.0f}%", SUCCESS)

    # -- zakładka Konfiguracja ---------------------------------------------

    def _build_setup(self):
        p = self.tab_setup

        c = self.card(p, pady=(0, 10))
        ttk.Label(c, text="ROZMIAR URZADZENIA", style="Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 0))
        for s in SIZES_GIB:
            ttk.Radiobutton(row, text=f"{s} GiB", value=s, variable=self.size_var,
                            command=self._on_size).pack(side="left", padx=(0, 16))

        c2 = self.card(p, pady=(0, 10))
        ttk.Label(c2, text="ALGORYTM KOMPRESJI", style="Muted.TLabel").pack(anchor="w")
        for name, a in ALGOS.items():
            ttk.Radiobutton(
                c2, text=f"{name}  —  {a['ratio']}:1, CPU x{a['cpu']}, {a['latency_us']} us",
                value=name, variable=self.algo_var, command=self._on_algo,
            ).pack(anchor="w", pady=1)

        c3 = self.card(p, pady=(0, 10))
        ttk.Label(c3, text="GENERATOR KOMEND", style="Muted.TLabel").pack(anchor="w")
        btns = ttk.Frame(c3, style="Card.TFrame")
        btns.pack(fill="x", pady=(6, 8))
        ttk.Button(btns, text="Wlacz", command=lambda: self._show_cmds("setup")).pack(
            side="left", padx=(0, 8))
        ttk.Button(btns, text="Wylacz", command=lambda: self._show_cmds("teardown")).pack(
            side="left", padx=(0, 8))
        ttk.Button(btns, text="Autostart", command=lambda: self._show_cmds("persist")).pack(
            side="left", padx=(0, 8))
        ttk.Button(btns, text="Kopiuj", command=self._copy_cmds).pack(side="left")

        self.cmd_text = tk.Text(c3, height=16, bg=BG, fg=TEXT, insertbackground=TEXT,
                                relief="flat", font=("Consolas", 9), wrap="none")
        self.cmd_text.pack(fill="both", expand=True)

        c4 = self.card(p)
        ttk.Label(c4, text="TUNING I PRIORYTETY", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            c4,
            text="swappiness 100 — jadro chetnie przenosi zimne strony do zram, bo to tansze "
                 "niz ubijanie programow.\n"
                 "page-cluster 0 — odczyt jednej strony naraz; przy zram czytanie wiekszych "
                 "klastrow marnuje CPU.\n"
                 "Priorytety: zram 100, plik wymiany / karta 10. Jadro siega najpierw do "
                 "wyzszego priorytetu, wiec zram wypelnia sie przed dyskiem.",
            style="Muted.TLabel", wraplength=780, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self._show_cmds("setup")

    def _on_size(self):
        self.refresh_budget()
        self._show_cmds("setup")

    def _on_algo(self):
        self.refresh_budget()
        self._show_cmds("setup")

    def _show_cmds(self, mode):
        size = float(self.size_var.get())
        algo = self.algo_var.get()
        if mode == "setup":
            text = setup_commands(size, algo)
        elif mode == "teardown":
            text = teardown_commands()
        else:
            text = persist_commands(size, algo)
        self.cmd_text.delete("1.0", "end")
        self.cmd_text.insert("1.0", text)

    def _copy_cmds(self):
        self.clipboard_clear()
        self.clipboard_append(self.cmd_text.get("1.0", "end").strip())
        self.update_idletasks()

    # -- zakładka Weryfikacja ----------------------------------------------

    def _build_verify(self):
        p = self.tab_verify

        c = self.card(p, pady=(0, 10))
        ttk.Label(c, text="WKLEJ STATYSTYKI KOMPRESJI", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(
            c,
            text="Format 1 (mm_stat):  orig_data_size compr_data_size mem_used_total ...\n"
                 "Format 2 (pary):      orig_data_size: 12845056 / compr_data_size: 4608000",
            style="Muted.TLabel", justify="left",
        ).pack(anchor="w", pady=(4, 6))

        self.stats_text = tk.Text(c, height=6, bg=BG, fg=TEXT, insertbackground=TEXT,
                                  relief="flat", font=("Consolas", 9))
        self.stats_text.pack(fill="x")
        self.stats_text.insert("1.0", "12845056 4608000 4718592 0 4718592 12 0 0 0")

        ttk.Button(c, text="Analizuj", command=self._analyse).pack(anchor="w", pady=(8, 0))

        self.verify_card = self.card(p, pady=(0, 10))
        self.verify_ratio = ttk.Label(self.verify_card, text="—", style="Big.TLabel")
        self.verify_ratio.pack(anchor="w")
        self.verify_judge = ttk.Label(self.verify_card, text="", style="Muted.TLabel",
                                      wraplength=780, justify="left")
        self.verify_judge.pack(anchor="w", pady=(2, 6))
        self.verify_body = ttk.Frame(self.verify_card, style="Card.TFrame")
        self.verify_body.pack(fill="x")

        c3 = self.card(p, pady=(0, 10))
        ttk.Label(c3, text="PROGI — KIEDY KOMPRESJA PRZESTAJE POMAGAC",
                  style="Muted.TLabel").pack(anchor="w")
        rows = [
            ("Wolne RAM", "> 800 MiB", "300–800 MiB", "< 300 MiB",
             "system zaczyna ubijac programy w tle"),
            ("Wspolczynnik", "> 2,5:1", "2,0–2,5:1", "< 2,0:1",
             "kompresja zjada wiecej, niz daje"),
            ("Swap-in", "< 5 MB/s", "5–50 MB/s", "> 50 MB/s",
             "CPU staje sie waskim gardlem"),
            ("CPU przez kswapd", "< 5%", "5–15%", "> 15%",
             "grzanie i spadek plynnosci"),
        ]
        for metric, ok, tight, crit, effect in rows:
            r = ttk.Frame(c3, style="Card.TFrame")
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=metric, style="Card.TLabel", width=18).pack(side="left")
            ttk.Label(r, text=f"OK {ok}", style="Card.TLabel",
                      foreground=SUCCESS).pack(side="left", padx=(0, 10))
            ttk.Label(r, text=f"ciasno {tight}", style="Card.TLabel",
                      foreground=WARNING).pack(side="left", padx=(0, 10))
            ttk.Label(r, text=f"krytyczne {crit}", style="Card.TLabel",
                      foreground=DANGER).pack(side="left", padx=(0, 10))
            ttk.Label(r, text=effect, style="Muted.TLabel").pack(side="left")

        c4 = self.card(p)
        ttk.Label(c4, text="KOMENDY KONTROLNE", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(
            c4,
            text="Linux:  zramctl  |  cat /proc/swaps  |  free -h  |  "
                 "grep -E 'MemFree|MemAvailable|SwapTotal|SwapFree' /proc/meminfo\n"
                 "Windows: Get-Counter '\\Memory\\Available MBytes'  |  "
                 "Get-Process | Select-Object WS,PM",
            style="Muted.TLabel", justify="left",
        ).pack(anchor="w", pady=(4, 0))

    def _analyse(self):
        raw = self.stats_text.get("1.0", "end")
        st = parse_stats(raw)
        if not st:
            self.verify_ratio.configure(text="Nie udalo sie odczytac", foreground=DANGER)
            self.verify_judge.configure(
                text="Potrzebne sa co najmniej 3 liczby w linii, pierwsza wieksza od zera.")
            for w in self.verify_body.winfo_children():
                w.destroy()
            return

        label, color, detail = judge_ratio(st["ratio"])
        self.verify_ratio.configure(text=f"{st['ratio']:.2f}:1  —  {label}", foreground=color)
        self.verify_judge.configure(text=detail)

        for w in self.verify_body.winfo_children():
            w.destroy()
        self.kv(self.verify_body, "orig_data_size (przed kompresja)", format_bytes(st["orig"]))
        self.kv(self.verify_body, "compr_data_size (po kompresji)", format_bytes(st["compr"]))
        self.kv(self.verify_body, "mem_used_total (realny RAM)", format_bytes(st["used"]))
        self.kv(self.verify_body, "Narzut RAM na 1 B tresci", f"{st['overhead']:.2f} B")
        self.kv(self.verify_body, "Zaoszczedzone", f"{st['saved_pct']:.1f}%", SUCCESS)

    # -- zakładka Algorytmy -------------------------------------------------

    def _build_algos(self):
        p = self.tab_algos

        c = self.card(p, pady=(0, 10))
        ttk.Label(c, text="POROWNANIE ALGORYTMOW", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(
            c,
            text="Wspolczynniki na typowych danych z pamieci. Na realnym systemie "
                 "wychodzi zwykle 2,4–3,2:1 — sprawdz w zakladce Weryfikacja.",
            style="Muted.TLabel", wraplength=780, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        for name, a in ALGOS.items():
            card = self.card(p, pady=(0, 8))
            head = ttk.Frame(card, style="Card.TFrame")
            head.pack(fill="x")
            ttk.Label(head, text=name, style="H2.TLabel").pack(side="left")
            if name == DEFAULT_ALGO:
                ttk.Label(head, text="  ZALECANY", style="Card.TLabel",
                          foreground=SUCCESS).pack(side="left")
            ttk.Label(head, text=a["speed"], style="Muted.TLabel").pack(side="right")

            self._bar(card, "Kompresja", a["ratio"] / 3.2, f"{a['ratio']}:1", PRIMARY)
            self._bar(card, "Koszt CPU", a["cpu"] / 3.1, f"x{a['cpu']}", WARNING)
            self._bar(card, "Opoznienie", a["latency_us"] / 95, f"{a['latency_us']} us", MUTED)

            ttk.Label(card, text=a["note"], style="Muted.TLabel",
                      wraplength=780, justify="left").pack(anchor="w", pady=(4, 0))

        c2 = self.card(p)
        ttk.Label(c2, text="WNIOSEK", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            c2,
            text="lz4hc. Ma ten sam, tani dekoder co lz4, ale kompresuje mocniej — a na "
                 "komputerze z malym RAM dekodowanie zdarza sie czesciej niz kodowanie, bo "
                 "strony wracaja z zram do RAM. zstd daje 0,4:1 wiecej, ale za 3x drozszym "
                 "CPU.",
            style="Muted.TLabel", wraplength=780, justify="left",
        ).pack(anchor="w", pady=(4, 0))

    def _bar(self, parent, label, frac, text, color):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, style="Muted.TLabel", width=12).pack(side="left")
        canvas = tk.Canvas(row, height=10, bg=BORDER, highlightthickness=0)
        canvas.pack(side="left", fill="x", expand=True, padx=(0, 8))
        canvas.update_idletasks()
        width = max(1, int(canvas.winfo_width() or 400))
        pct = max(0.02, min(1.0, frac))
        canvas.create_rectangle(0, 0, int(width * pct), 10, fill=color, outline="")
        ttk.Label(row, text=text, style="Muted.TLabel", width=10).pack(side="left")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
