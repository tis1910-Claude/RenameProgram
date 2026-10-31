# Media Renamer Pro

Képek és videók csoportos átnevezése a **felvétel dátuma** és egy **téma** alapján, Tkinter felülettel.
Kérésre a fájlokat egy közös `ÉÉÉÉ-HH-NN_téma` mappába is átmozgatja.

Példa: `IMG_1234.jpg` → `2024-05-01_14-30-00_Balaton.jpg`

## Funkciók

- Bélyegképes áttekintés (fotók helyes elforgatással, videóknál képkocka az ffmpeg-gel). Több ezer fájlnál is gyors:
  csak a látható képek töltődnek be, és a kész bélyegképeket a program lemezen megőrzi (legfeljebb kb. 300 MB,
  Windowson `%LOCALAPPDATA%\MediaRenamerPro\thumbs`), így a mappa következő megnyitása azonnali.
- Kijelölés: kattintás a képre (be/ki), **Shift+kattintás** egy tartományra, Ctrl+A az összesre;
  dupla kattintás megnyitja, a 📁 jel a fájlkezelőben mutatja meg. Az állapotsor mutatja, hány fájl van kijelölve.
- Szűrő a lista fölött: típus (képek, videók, RAW), névrészlet, dátumtartomány (`ÉÉÉÉ-HH-NN`), és
  „csak metaadat nélkül” (amelyeknél a fájl dátuma lenne a név). Az átnevezés, rendezés és törlés csak a látható,
  kijelölt fájlokra vonatkozik.
- Dátum forrása: fotóknál EXIF (`DateTimeOriginal`), videóknál ffprobe (`creation_time`, iPhone-on az Apple saját mezője).
  Ha nincs beágyazott dátum, a program a fájlnévből olvassa ki (WhatsApp `IMG-20230812-WA0001`, Android
  `IMG_20230812_143015`, Pixel `PXL_…` (UTC), Messenger `FB_IMG_<időbélyeg>`, képernyőképek, Signal); az előnézet
  ezt „(névből)” jelzéssel mutatja. Ha ez sincs, a fájl dátuma lesz használva, és a program ezt jelzi.
  Ha a videó a felvétel helyének időeltolását is tartalmazza (iPhone), a felvétel helyi ideje lesz a név, ahogy a
  fotóknál is, így egy külföldi út fotói és videói ugyanarra az órára és napra esnek. A csak UTC-t tartalmazó
  videóknál (`creation_time`) a gép helyi ideje lesz használva.
- A macOS által pendrive-ra/SD-kártyára írt `._` kezdetű kísérőfájlokat a program kihagyja.
- Fájltípusok: JPEG, PNG, TIFF, WebP, **HEIC/HEIF** (iPhone, a `pillow-heif` csomaggal), **RAW** (DNG, CR2, CR3, NEF,
  ARW, ORF, RW2, RAF, PEF, SRW; dátum az `exifread`, bélyegkép a `rawpy` csomaggal), videók: MP4, MOV, M4V, 3GP, AVI, MKV, MTS.
- Az MP4/MOV/M4V/3GP videók dátumát a program ffmpeg nélkül, maga olvassa ki a fájl fejlécéből (gyorsabb is).
  Az ffprobe csak az AVI/MKV/MTS fájlokhoz és a videós bélyegképekhez kell.
- Testreszabható névsablon (*Beállítások → Átnevezési sablonok*):
  `{date}` `{day}` `{time}` `{suffix}` `{seq}` `{original}` `{counter}`
- **Előnézet átnevezés előtt**: minden fájl jelenlegi neve, felvételi ideje és új neve látszik, és csak az OK után
  történik meg az átnevezés.
- **Időeltolás** az előnézetben (átnevezésnél és napok szerinti rendezésnél is): ha a fényképező órája rosszul
  járt, pl. `+1`, `-0:30` vagy `+1d 2:00` beírásával a kijelölt fájlok ideje eltolódik. A fájlok tartalmát
  (EXIF) a program nem módosítja, csak a név és a napi mappa igazodik hozzá.
- **Live Photo párok** (iPhone: `IMG_1234.HEIC` + `IMG_1234.MOV`, azonos mappában, azonos névvel): a rácsban
  „LIVE” jelzést kapnak, és átnevezéskor, napi rendezéskor, törléskor és visszavonáskor együtt mozognak, akkor is,
  ha csak az egyik van kijelölve. A videó a fotóval azonos nevet és napot kap (csak a kiterjesztés más).
- Ütközésvédelem: létező fájlt soha nem ír felül
- **Rendezés napok szerint**: a kijelölt (vagy kijelölés nélkül az összes betöltött) fájlt a felvétel napja
  szerinti `ÉÉÉÉ-HH-NN` almappába helyezi át, a fájlnév megmarad. Előnézetet mutat (napokra bontva, az új
  mappák `(+)` jellel), az *Almappák is* beállítás szerint az almappákban lévő fájlokat is rendezi, a
  metaadat nélküli fájlokat a fájl dátuma szerint rendezi (ez kikapcsolható),
  és névütközéskor `_1`, `_2` végződést ad. Visszavonható (Ctrl+Z); az általa létrehozott üres mappákat ilyenkor törli.
- Visszavonás több lépésben (*Szerkesztés → Visszavonás*, Ctrl+Z): az utolsó 20 átnevezés/rendezés
  visszavonható, a program újraindítása után is (`history.json` a beállítások mellett). A menü mutatja, mi lenne visszavonva.
- **Duplikátumkeresés** (*Szerkesztés → Duplikátumok keresése*): azonos tartalmú fájlok a kijelöltek (vagy a látható
  fájlok) között. A másolatokat egy gombnyomással kijelöli, a törlés a Törlés gombbal, lomtárba történik.
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
3. Videós bélyegképekhez és AVI/MKV/MTS dátumhoz: [ffmpeg](https://ffmpeg.org/download.html) (`ffmpeg` és `ffprobe` legyen a PATH-on).
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

A nem grafikus részek (dátumolvasás, sablon, ütközések, mozgatás, napok szerinti rendezés, visszavonás) tesztjei
valódi JPEG/PNG/MP4 fájlokat generálnak. A videós tesztekhez ffmpeg kell, nélküle ezek kimaradnak.

```
pip install -r requirements-dev.txt
python -m pytest
```

A GitHub minden PR-nél és a main minden változásánál lefuttatja őket Linuxon és Windowson is (*Actions → Tesztek*).

## EXE készítése (opcionális)

A legegyszerűbb: GitHubon *Actions → Windows EXE → Run workflow*, és a lefutás után a kész `MediaRenamerPro.exe`
letölthető az *Artifacts* részből. Ha `v`-vel kezdődő címkét (pl. `v4.4`) töltesz fel, az EXE a Release-hez is
hozzá lesz csatolva.

Kézzel:

```
pip install pyinstaller
pyinstaller --noconsole --onefile --add-data "*.png;." --collect-data sv_ttk --collect-all tkinterdnd2 --collect-all pillow_heif --collect-all rawpy --hidden-import PIL._tkinter_finder Keprename5video.py
```
A `--collect-data sv_ttk` a Sun Valley megjelenés fájljait, a `--collect-all tkinterdnd2` a fogd és vidd
programkönyvtárát csomagolja be. Amelyik csomag nincs telepítve, annak a kapcsolóját hagyd el.
(Linuxon/macOS-en az `--add-data` elválasztója `:` a `;` helyett.)
