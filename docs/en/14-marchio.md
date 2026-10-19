# Brand

The Nesso mark is the one already in the app menu: four squares on the same grid, rounded corners, and the four colours of the Espo theme used by the interface. The name "Nesso" is Inter SemiBold, the app typeface. The font licence is in `motore/fonts/LICENSE.txt`.

![Nesso lockup on a light background](img/lockup-su-chiaro.svg){ width="360" }

The files are in `assets/logo`. The SVG is the master and does not depend on an installed font: the name is drawn as a path. PNG and JPG have a long side of 4096 pixels. The JPG has no transparency: the transparent versions sit on a light background, except the negative mark, which sits on a dark background.

| File | What it is |
|---|---|
| `marchio` | The four squares, transparent background |
| `marchio-mono` | The same squares, all `#262626` |
| `marchio-negativo` | The same squares, all `#FEFEFE` |
| `lockup` | Mark and name on the same row, as in the menu |
| `lockup-verticale` | Mark above, name below, centred |
| `wordmark` | The name only, colour `#8090A0` |
| `*-su-chiaro` | The same set on `#F4F5F7`, the menu background |
| `*-su-scuro` | The same set on `#262626`. The name becomes `#F4F5F7` |

Each row exists as `.svg`, `.png` and `.jpg`.

Mark colours, from the top left: `#8B939C`, `#E4A133`, `#5589CA`, `#58C97A`.

To rebuild the files after a change to the mark:

```text
py -3 scripts/build_logo.py
```

The app menu embeds a small mark. The geometry is the same: canvas 26, margin 1, square 11, gap 2, radius 2.
