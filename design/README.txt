SoundSplitter — brand asset drop
=================================

Concept: "one sound → six stems." A single off-white spine splits into six
horizontal track bars, one color per stem (vocals, drums, bass, guitar, piano,
other). Mark sits on a dark rounded tile so the off-white spine stays legible on
any OS background (taskbar, installer, light or dark).

Palette: #8A7BFF #5B8CFF #36B3F0 #2BD0BE #46D39A #8FE06A  (spine #E7E9EE, tile #14161B)


WHERE EACH FILE GOES
--------------------
src-tauri/icons/
  icon.png            1024x1024   master
  128x128@2x.png      256x256     (note: the "@2x" must stay in the filename)
  128x128.png         128x128
  64x64.png           64x64
  32x32.png           32x32
  icon.ico            16/32/48/256  -> Windows installer + EXE + taskbar
  favicon.ico         16/32/48
  icon-mark-transparent-1024.png   bonus: bare mark, transparent (dark surfaces only)

frontend/public/
  favicon.ico         (same as above, for the browser tab)
  logo-wordmark.svg   horizontal "mark + SoundSplitter" lockup, transparent, dark-bg
  logo-wordmark.png   ~1022x236 transparent fallback
  loading-eq.svg      animated processing/loading spinner (the 6 bouncing stem bars)


NOTES
-----
- icon.ico / favicon.ico are real multi-resolution .ico containers (PNG-encoded
  frames). Prioritized for 16/32px legibility.
- Wordmark type is Space Grotesk 600. The .svg embeds the needed glyphs as a font
  subset AND @imports the webfont, so it renders correctly in the Chromium webview
  with no extra setup. The .png fallback is rasterized from the same render.
- To swap the header: replace the <span class="brand">🎚️ sound-splitter</span> in
  frontend/src/app/app.html with:
      <img src="/logo-wordmark.svg" alt="SoundSplitter" height="28">

LOADER USAGE (in-app processing / "Splitting stems…")
-----------------------------------------------------
Drop-in file, animates on its own:
    <img src="/loading-eq.svg" width="40" height="40" alt="Processing">
Inline it if you want it to inherit/recolor or sit in a modal — see the bars +
keyframes in loading-eq.svg (respects prefers-reduced-motion).
