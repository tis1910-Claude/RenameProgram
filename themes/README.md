# Beépített ttk témák

Mindkét téma rdbende munkája, MIT licenccel (a licenc szövege a mappájukban).

| Mappa | Forrás | Változtatás |
|---|---|---|
| `azure/` | https://github.com/rdbende/Azure-ttk-theme (997dbbe, 2.0) `theme/` mappája | nincs; az `azure.tcl` kimaradt, mert az átírná a betűtípust |
| `forest/` | https://github.com/rdbende/Forest-ttk-theme (4fdde95) | a globális betűtípus-beállítás kivéve |

A program a `light.tcl` / `dark.tcl` (`forest-*.tcl`) fájlt tölti be, és a
`ttk::style theme use` paranccsal kapcsol át; a klasszikus Tk widgetek színeit
a program saját palettája adja (`PALETTES` a `Keprename5video.py`-ban).
