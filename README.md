# Media Renamer Pro

Képek és videók csoportos átnevezése a **felvétel dátuma** és egy **téma** alapján, Tkinter felülettel.
Kérésre a fájlokat egy közös `ÉÉÉÉ-HH-NN_téma` mappába is átmozgatja.

Példa: `IMG_1234.jpg` → `2024-05-01_14-30-00_Balaton.jpg`

## Funkciók

- Bélyegképes áttekintés (fotók helyes elforgatással, videóknál képkocka az ffmpeg-gel)
- Dátum forrása: fotóknál EXIF (`DateTimeOriginal`), videóknál ffprobe (`creation_time`, iPhone-on az Apple saját mezője).
  Ha egyik sincs, a fájl dátuma lesz használva, és a program ezt jelzi.
  Ha a videó a felvétel helyének időeltolását is tartalmazza (iPhone), a felvétel helyi ideje lesz a név, ahogy a
  fotóknál is, így egy külföldi út fotói és videói ugyanarra az órára és napra esnek. A csak UTC-t tartalmazó
  videóknál (`creation_time`) a gép helyi ideje lesz használva.
- A macOS által pendrive-ra/SD-kártyára írt `._` kezdetű kísérőfájlokat a program kihagyja.
- Testreszabható névsablon (*Beállítások → Átnevezési sablonok*):
  `{date}` `{day}` `{time}` `{suffix}` `{seq}` `{original}` `{counter}`
- Ütközésvédelem: létező fájlt soha nem ír felül
- **Rendezés napok szerint**: a kijelölt (vagy kijelölés nélkül az összes betöltött) fájlt a felvétel napja
  szerinti `ÉÉÉÉ-HH-NN` almappába helyezi át, a fájlnév megmarad. Előnézetet mutat (napokra bontva, az új
  mappák `(+)` jellel), az *Almappák is* beállítás szerint az almappákban lévő fájlokat is rendezi, a
  metaadat nélküli fájlokat a fájl dátuma szerint rendezi (ez kikapcsolható),
  és névütközéskor `_1`, `_2` végződést ad. Visszavonható (Ctrl+Z); az általa létrehozott üres mappákat ilyenkor törli.
- Utolsó átnevezés vagy rendezés visszavonása (*Szerkesztés → Visszavonás*, Ctrl+Z)
- Törlés lomtárba (`send2trash`), almappák be-/kikapcsolása, mappa behúzása az ablakba
- Beépített VLC-lejátszó (ha nincs VLC, a rendszer alapértelmezett lejátszója nyílik meg)
- Magyar és angol felület
- Választható megjelenés (*Beállítások → Megjelenés*), azonnal vált, és megmarad:
  - **Rendszer**: a gép saját kinézete, mint eddig (alapértelmezett)
  - **Világos** és **Sötét**: lapos, modern színek, külső csomag nélkül
  - **Sun Valley világos / sötét**: Windows 11 stílus, ehhez kell az `sv-ttk` csomag

  Windowson a sötét megjelenéseknél a címsor is sötét lesz.

## Telepítés

1. Python 3.8 vagy újabb (Tkinterrel; Windowson alapból benne van).
2. Függőségek:
   ```
   pip install -r requirements.txt
   ```
3. Videókhoz: [ffmpeg](https://ffmpeg.org/download.html) (`ffmpeg` és `ffprobe` legyen a PATH-on).
4. Beépített lejátszóhoz: [VLC](https://www.videolan.org/vlc/) (a `python-vlc` bitszáma egyezzen a VLC-ével).

Az ikonok (`folder.png`, `rename.png`, `refresh.png`, `unmark.png`, `MarkAll.png`, `delete.png`, `exit.png`, `media.png`)
a program mellé kerülnek; ha hiányoznak, szürke helyettesítő ikon jelenik meg.

## Futtatás

```
python Keprename5video.py
```

A beállítások helye: Windowson `%APPDATA%\MediaRenamerPro\settings.ini`,
Linuxon `~/.config/MediaRenamerPro/settings.ini`, macOS-en `~/Library/Application Support/MediaRenamerPro/settings.ini`.

## Tesztek

A nem grafikus részek (dátumolvasás, sablon, ütközések, mozgatás, napok szerinti rendezés, visszavonás) tesztje valódi
JPEG/PNG/MP4 fájlokat generál, ehhez ffmpeg kell:

```
python tests/test_logic.py
```

## EXE készítése (opcionális)

```
pip install pyinstaller
pyinstaller --noconsole --onefile --add-data "*.png;." --collect-data sv_ttk --collect-all tkinterdnd2 --hidden-import PIL._tkinter_finder Keprename5video.py
```
A `--collect-data sv_ttk` a Sun Valley megjelenés fájljait, a `--collect-all tkinterdnd2` a fogd és vidd
programkönyvtárát csomagolja be. Amelyik csomag nincs telepítve, annak a kapcsolóját hagyd el.
(Linuxon/macOS-en az `--add-data` elválasztója `:` a `;` helyett.)
