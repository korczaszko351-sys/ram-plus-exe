# RAM Plus EXE

Desktopowy odpowiednik aplikacji **RAM Plus A17** — kalkulator i konfigurator
kompresji pamięci (zram / plik wymiany) dla Windows.

Pojedynczy plik `.exe`, bez instalacji, bez Pythona na komputerze użytkownika.

## Co robi

| Zakładka | Zawartość |
|---|---|
| **Budżet** | podajesz fizyczny RAM (domyślnie 4 GB jak w Galaxy A17), overhead systemu, rozmiar zram/pliku wymiany i algorytm → ile zostaje dla programów + werdykt |
| **Konfiguracja** | rozmiar 2/3/4/6 GiB, algorytm lz4/lz4hc/zstd/lzo-rle, generator komend (włącz / wyłącz / autostart) |
| **Weryfikacja** | wklejasz statystyki kompresji → współczynnik, narzut RAM, % oszczędności |
| **Algorytmy** | porównanie: stopień kompresji, koszt CPU, opóźnienie |

## Werdykt

| Wolne dla programów | Werdykt |
|---|---|
| ≥ 0,7 GiB | **Komfort** |
| 0,4–0,7 GiB | **Zalecane** |
| 0,15–0,4 GiB | **Granica** |
| < 0,15 GiB | **Cegła** |

## To pojemność LOGICZNA

Kompresja w RAM, nie dodatkowa kość. Program pokazuje to wprost w każdym widoku.

## Zbudowanie EXE

Workflow `.github/workflows/build-exe.yml` buduje plik na runnerze `windows-latest`.

1. **Actions** → **Build EXE** → **Run workflow**
2. Po ~2–4 min: **Artifacts** → `ram-plus-exe` → ZIP z `RAM-Plus.exe`
3. Albo tag: `git tag v1.0.0 && git push origin v1.0.0` → plik trafi do **Releases**

**Nie są potrzebne żadne sekrety** — runner Windows ma wszystko, czego trzeba.

## Uruchomienie lokalne (bez budowania)

```
python app.py
```

Wymaga Pythona 3.9+ z tkinterem (w instalatorze Windows: zaznacz „tcl/tk and IDLE").
