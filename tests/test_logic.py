import os, sys, shutil, subprocess, tempfile
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import Keprename5video as m
from PIL import Image

d = tempfile.mkdtemp()
sub = os.path.join(d, "alma"); os.makedirs(sub)

def jpg(path, dt=None, orient=None):
    img = Image.new("RGB", (400, 200), "red"); ex = Image.Exif()
    if dt: ex.get_ifd(0x8769)[0x9003] = dt
    if orient: ex[0x0112] = orient
    img.save(path, exif=ex.tobytes())
jpg(os.path.join(d, "a.jpg"), "2023:07:15 10:20:30")
jpg(os.path.join(d, "b.JPG"), "2023:07:15 10:20:30")       # azonos időpont -> ütközés
jpg(os.path.join(sub, "c.jpg"), "2023:07:14 08:00:00", orient=6)
Image.new("RGB",(50,50)).save(os.path.join(d, "noexif.jpg"))
ex = Image.Exif(); ex.get_ifd(0x8769)[0x9003] = "2022:01:02 03:04:05"
Image.new("RGB",(50,50)).save(os.path.join(d, "p.png"), exif=ex.tobytes())
ff = lambda out, dur, ct: subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",f"testsrc=duration={dur}:size=320x240:rate=10",
     "-metadata",f"creation_time={ct}","-pix_fmt","yuv420p",out],check=True)
ff(os.path.join(d,"short.mp4"), 2, "2023-07-16T12:00:00.000000Z")
ff(os.path.join(d,"long.mov"), 8, "2023-07-16T13:00:00Z")

ok = lambda c, msg: print(("OK  " if c else "FAIL"), msg) or c
files = m.scan_media(d, True); ok(len(files)==7, f"rekurzív scan: {len(files)}")
ok(len(m.scan_media(d, False))==6, "nem rekurzív scan")

dt, src = m.get_media_datetime(os.path.join(d,"a.jpg")); ok((dt,src)==(datetime(2023,7,15,10,20,30),"exif"), f"JPEG EXIF {dt} {src}")
dt, src = m.get_media_datetime(os.path.join(d,"p.png")); ok(src=="exif" and dt.year==2022, f"PNG EXIF (régi kód None-t adott) {dt} {src}")
dt, src = m.get_media_datetime(os.path.join(d,"noexif.jpg")); ok(src=="file", f"EXIF nélkül fájldátum {dt}")
dt, src = m.get_media_datetime(os.path.join(d,"short.mp4"))
exp = m.parse_iso_datetime("2023-07-16T12:00:00Z")
ok(src=="video" and dt==exp, f"videó dátum UTC->helyi {dt} ({src})")
ok(m.parse_iso_datetime("2023-07-16T14:00:00+0200")==m.parse_iso_datetime("2023-07-16T12:00:00Z"), "apple +0200 eltolás")
ok(m.parse_iso_datetime("1904-01-01T00:00:00Z") is None, "üres 1904 dátum elutasítva")

# bélyegképek
for f in ("short.mp4","long.mov","sub"):
    pass
im = m.ThumbnailGenerator.generate(os.path.join(d,"short.mp4"))
ok(im.getextrema()!=((128,128),(128,128),(128,128)), f"2 mp-es videó bélyegkép nem szürke {im.size}")
im = m.ThumbnailGenerator.generate(os.path.join(sub,"c.jpg")); ok(im.size==(75,150), f"EXIF forgatás álló képre {im.size}")

# sablon
dt0 = datetime(2024,5,1,14,30,0)
ok(m.render_name(m.DEFAULT_PATTERN, dt0, "Balaton", 0, 1, "x", ".jpg")=="2024-05-01_14-30-00_Balaton.jpg", "alap sablon = régi viselkedés")
ok(m.render_name(m.DEFAULT_PATTERN, dt0, "Balaton", 2, 1, "x", ".jpg")=="2024-05-01_14-30-00_Balaton_2.jpg", "ütközésszámláló")
ok(m.render_name("{suffix}_{seq}", dt0, "Bala/ton:", 0, 7, "x", ".jpg")=="Bala-ton-_007.jpg", "tiltott karakter a témában + seq")
ok(m.render_name("{day}_{suffix}", dt0, "B", 3, 1, "x", ".jpg")=="2024-05-01_B_3.jpg", "{counter} nélküli sablon ütközéskor")
ok(m.validate_pattern("{datum}_{suffix}") is not None, "ismeretlen mező elutasítva")
ok(m.validate_pattern("{date}/{suffix}") is not None, "perjel elutasítva")
ok(m.validate_pattern("{date}_{suffix") is not None, "hibás kapcsos zárójel")
ok(m.validate_pattern("{day}_{time}_{suffix}_{counter}") is None, "érvényes sablon")

# átnevezés helyben
items = [(f, m.get_media_datetime(f)[0]) for f in files]
plan = m.plan_renames(items, "Nyaralás", m.DEFAULT_PATTERN)
names = [os.path.basename(n) for _, n in plan]
ok(len(set(m._key(n) for _, n in plan))==len(plan), "nincs ütközés a tervben")
ok("2023-07-15_10-20-30_Nyaralás_1.JPG" in names or "2023-07-15_10-20-30_Nyaralás_1.jpg" in names, f"azonos idő -> _1: {sorted(names)}")
ok(os.path.dirname(dict(plan)[os.path.join(sub,'c.jpg')])==sub, "helyben átnevezésnél almappa megmarad")
done, unchanged, errors = m.execute_plan(plan)
ok(len(done)==7 and not errors, f"végrehajtás {len(done)} {errors}")
# újrafuttatás: ne legyen _1 a már jó neveken
files2 = m.scan_media(d, True)
plan2 = m.plan_renames([(f, m.get_media_datetime(f)[0]) for f in files2], "Nyaralás", m.DEFAULT_PATTERN)
_, unchanged2, _ = m.execute_plan(plan2)
ok(unchanged2==7, f"második futás változatlan: {unchanged2}")

# mozgatás + visszavonás
target = os.path.join(d, "2023-07-14_Nyaralás"); os.makedirs(target)
plan3 = m.plan_renames([(f, m.get_media_datetime(f)[0]) for f in files2], "Nyaralás", m.DEFAULT_PATTERN, target)
done3, _, err3 = m.execute_plan(plan3)
ok(len(os.listdir(target))==7 and not err3, "mozgatás célmappába, ütközés nélkül")
back, _, errb = m.execute_plan([(n,o) for o,n in reversed(done3)])
ok(len(back)==7 and not os.listdir(target) and not errb, "visszavonás")

# meglévő fájl védelme
src_ = [f for f in m.scan_media(d, False) if "10-20-30" in f][0]
open(os.path.join(target, "2023-07-15_10-20-30_X"+os.path.splitext(src_)[1]),"w").write("ne írd felül")
src_ = [f for f in m.scan_media(d, False) if "10-20-30" in f][0]
p4 = m.plan_renames([(src_, datetime(2023,7,15,10,20,30))], "X", m.DEFAULT_PATTERN, target)
ok(p4[0][1].endswith("_X_1"+os.path.splitext(src_)[1]), f"létező fájl nem íródik felül: {os.path.basename(p4[0][1])}")

# beállítások
ini = os.path.join(d, "cfg", "settings.ini")
s = m.SettingsManager(ini); s.recent_suffixes=["Balaton","Esküvő"]; s.save_settings()
ok(m.SettingsManager(ini).recent_suffixes==["Balaton","Esküvő"], "témák mentése/visszaolvasása (ékezettel)")
shutil.rmtree(d)

# rendezés napok szerint
d = tempfile.mkdtemp()
sub = os.path.join(d, "regi_mappa"); os.makedirs(sub)
jpg(os.path.join(d, "a.jpg"), "2023:07:15 10:20:30")
jpg(os.path.join(sub, "a.jpg"), "2023:07:15 11:00:00")          # azonos név másik mappából
jpg(os.path.join(sub, "c.jpg"), "2023:07:14 08:00:00")
ex = Image.Exif(); ex.get_ifd(0x8769)[0x9003] = "2022:01:02 03:04:05"
Image.new("RGB",(50,50)).save(os.path.join(d, "p.png"), exif=ex.tobytes())
Image.new("RGB",(50,50)).save(os.path.join(d, "noexif.jpg"))
ff(os.path.join(d,"late.mp4"), 1, "2023-07-15T23:30:00Z")          # UTC: helyi időben más nap lehet
jpg(os.path.join(d, "2023-07-14_kesz.jpg"), "2023:07:14 09:00:00")
os.makedirs(os.path.join(d, "2023-07-14"))
shutil.move(os.path.join(d, "2023-07-14_kesz.jpg"), os.path.join(d, "2023-07-14", "kesz.jpg"))

files = m.scan_media(d, True)
items = [(f, m.get_media_datetime(f)[0]) for f in files]
blocker = os.path.join(d, "2023-07-15", "a.jpg")                      # a beolvasás után kerül oda
os.makedirs(os.path.dirname(blocker)); open(blocker, "w").write("ne írd felül")
plan, in_place = m.plan_day_sort(items, d)
new = dict(plan)
ok(in_place == 1, f"a már helyén lévő fájl kimarad ({in_place})")
ok(len(plan) == len(files) - 1, f"terv mérete {len(plan)}")
ok(os.path.dirname(new[os.path.join(sub, "c.jpg")]) == os.path.join(d, "2023-07-14"), "almappából is rendez")
ok(new[os.path.join(d, "p.png")].endswith(os.path.join("2022-01-02", "p.png")), "PNG EXIF dátum")
vday = m.parse_iso_datetime("2023-07-15T23:30:00Z").strftime("%Y-%m-%d")
ok(os.path.dirname(new[os.path.join(d, "late.mp4")]) == os.path.join(d, vday), f"videó helyi idő szerinti nap: {vday}")
ok(os.path.join(d, "noexif.jpg") in new, "metaadat nélküli fájl is (fájldátum)")
names15 = sorted(os.path.basename(new[p]) for p in (os.path.join(d, "a.jpg"), os.path.join(sub, "a.jpg")))
ok(names15 == ["a_1.jpg", "a_2.jpg"], f"ütközés: létezőt nem ír felül, egymást sem: {names15}")
done, errors, created = m.execute_day_sort(plan)
ok(len(done) == len(plan) and not errors, f"áthelyezés {len(done)} {errors}")
ok(open(blocker).read() == "ne írd felül", "meglévő fájl érintetlen")
ok(os.path.join(d, "2023-07-15") not in created and os.path.join(d, "2022-01-02") in created, "létrehozott mappák listája")
plan_again, _ = m.plan_day_sort([(f, m.get_media_datetime(f)[0]) for f in m.scan_media(d, True)
                                 if f != blocker], d)
ok(plan_again == [], f"második futás nem mozgat semmit ({len(plan_again)})")
back, _, errb = m.execute_plan([(n, o) for o, n in reversed(done)])
m.remove_empty_folders(created)
ok(len(back) == len(done) and not errb, "visszavonás")
ok(all(not os.path.exists(c) for c in created) and os.path.isdir(os.path.join(d, "2023-07-15")),
   "visszavonás után az általunk létrehozott üres mappák törölve, a régiek maradnak")
ok(sorted(f for f in m.scan_media(d, True) if f != blocker) == sorted(files), "minden fájl az eredeti helyén")
shutil.rmtree(d)
