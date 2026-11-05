# anki-ml-ds

Flip-card study page for machine learning and data science, built from the Anki decks in
[ppant/anki](https://github.com/ppant/anki) (copied into `data/`, upstream commit `ab8c5d4`).

| Deck | Cards | Source |
|---|---|---|
| Machine Learning | 11 | `Hands On ML book - Geron.apkg` + ML notes from `PP-All-notes.txt` |
| Deep Learning | 7 | `PP__DL Specialization - Coursera.apkg` (CNN diagrams) |
| Data Mining & Data Engineering | 9 | `Data_Mining_PP.apkg`, `Coursera-GCP-ML-Specialization-Course1.apkg` + notes |
| Data Structures & Algorithms | 30 | `PP__DS-Algos-Python.apkg`, `PP-DS-Algos-Python.apkg` |
| Python | 13 | `PP__Python.apkg`, `Python-PP.apkg` + notes |

Duplicate cards across the decks and the raw-notes export are merged. The other upstream decks
(Git, Kubernetes, GCP migration, web dev, research) are kept in `data/` but not shown; add them to
`DECKS` in `build.py` to include them.

Open `flashcards/index.html` (or the GitHub Pages site). Click or press Space to flip, ←/→ to move,
1 = Again, 2 = Know it, S = speak. Progress is saved in the browser.

## Offline cache

When served over http(s), `flashcards/sw.js` (a service worker) caches the page and all images, so
repeat visits load instantly and the cards work offline.

- The cache version is a hash of the page, the images and the service worker. It changes only when
  the cards change.
- On each visit the browser checks for a new `sw.js` in the background. If there is one, it downloads
  the new files and shows a **New cards are available · Refresh** banner. Clicking Refresh switches to
  the new version and deletes the old cache.
- Cache and storage names are prefixed (`ml-ds-flashcards-`, `mlds.`), so this site doesn't clash with
  other sites on the same `github.io` origin.

## Rebuild

```
python build.py
```

This regenerates `flashcards/index.html`, `flashcards/media/` and `flashcards/sw.js` from
`template.html` and `sw-template.js`. Commit all of them.

The decks are by Pradeep Pant (ppant). The upstream repo has no license file.
