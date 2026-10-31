# Media Renamer Pro

Képek és videók csoportos átnevezése a **felvétel dátuma** és egy **téma** alapján, Tkinter felülettel.
Kérésre a fájlokat egy közös `ÉÉÉÉ-HH-NN_téma` mappába is átmozgatja.

Példa: `IMG_1234.jpg` → `2024-05-01_14-30-00_Balaton.jpg`

## Funkciók

- Bélyegképes áttekintés (fotók helyes elforgatással, videóknál képkocka az ffmpeg-gel)
- Dátum forrása: fotóknál EXIF (`DateTimeOriginal`), videóknál ffprobe (`creation_time`, iPhone-on az Apple saját mezője).
  Ha egyik sincs, a fájl dátuma lesz használva, és a program ezt jelzi.
- Testreszabható névsablon (*Beállítások → Átnevezési sablonok*):
  `{date}` `{day}` `{time}` `{suffix}` `{seq}` `{original}` `{counter}`
- Ütközésvédelem: létező fájlt soha nem ír felül
- Utolsó átnevezés visszavonása (*Szerkesztés → Visszavonás*, Ctrl+Z)
- Törlés lomtárba (`send2trash`), almappák be-/kikapcsolása, mappa behúzása az ablakba
- Beépített VLC-lejátszó (ha nincs VLC, a rendszer alapértelmezett lejátszója nyílik meg)
- Magyar és angol felület

## Telepítés

1. Python 3.8 vagy újabb (Tkinterrel; Windowson alapból benne van).
2. Függőségek:
   ```
   pip install -r requirements.txt
   ```
3. Videókhoz: [ffmpeg](https://ffmpeg.org/download.html) (`ffmpeg` és `ffprobe` legyen a PATH-on).
4. Beépített lejátszóhoz: [VLC](https://www.videolan.org/vlc/) (a `python-vlc` bitszáma egyezzen a VLC-ével).

Az ikonok (`folder.png`, `rename.png`, `unmark.png`, `MarkAll.png`, `delete.png`, `exit.png`, `media.png`)
a program mellett vannak. A `refresh.png` nincs a repóban: helyette a program egy kék környilat rajzol,
de ha a mappába teszel egy `refresh.png`-t, azt használja. Bármelyik hiányzó ikon helyén üres hely marad,
a program attól még működik.

## Futtatás

```
python Keprename5video.py
```

A beállítások helye: Windowson `%APPDATA%\MediaRenamerPro\settings.ini`,
Linuxon `~/.config/MediaRenamerPro/settings.ini`, macOS-en `~/Library/Application Support/MediaRenamerPro/settings.ini`.

## Tesztek

A nem grafikus részek (dátumolvasás, sablon, ütközések, mozgatás, visszavonás) tesztje valódi
JPEG/PNG/MP4 fájlokat generál, ehhez ffmpeg kell:

```
python tests/test_logic.py
```

## EXE készítése (opcionális)

```
pip install pyinstaller
pyinstaller --noconsole --onefile --add-data "*.png;." Keprename5video.py
```
(Linuxon/macOS-en az `--add-data` elválasztója `:` a `;` helyett.)
