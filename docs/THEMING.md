# Appearance and pinned tools

DocuFreedom stores preferences under publisher `dna.apps`, application `DocuFreedom`. Missing settings fall back to the former `DragShift/DragShift` namespace without changing it. The former default ribbon icon becomes the new `docufreedom` icon. Existing explicitly chosen alternative icons remain available.

The `theme` setting is `system`, `light` or `dark`; its default is `system`. The system mode follows Qt's operating-system colour-scheme signal. An explicit choice remains active when the OS changes appearance. Changes apply immediately to existing windows, dialogs, the PDF editor and registered custom surfaces. Document pages, photographs and the signature drawing sheet retain their actual colours.

The implementation is in `dragshift/theme.py`:

```python
from dragshift import theme

theme.register_window(window)       # Conventional Qt window: current and future QSS.
controller.settings.set("theme", "dark")  # Persist and apply immediately.
colours = theme.tokens()            # A copy of the effective palette.
theme.manager().changed.connect(custom_widget.update)
```

Custom painted windows use `tokens()` and subscribe to `manager().changed`. The signal carries the effective mode (`light` or `dark`); the selected preference is `manager().mode`. It also fires when the preference changes between system and an explicit mode with the same effective colours. A custom popover should keep its own stylesheet instead of registering for the full conventional-window stylesheet.

`apply_theme(mode, app=None)` changes the in-memory appearance without writing preferences. `style_sheet(mode=None)` and `tokens(mode=None)` allow explicit preview colours. The `documentCanvas` and `pdfCanvas` object names select the surrounding document-preview background.

Pinned PDF tools use the `favorite_tools` setting, a list of stable tool keys. Each catalog card has a keyboard-accessible star that pins or unpins it without launching the tool. The featured editor remains first; other pinned tools follow in pin order. The **Избранное** category filters the catalog to pinned tools. Search uses normalized Unicode, is case-insensitive, handles punctuation and `ё`/`е`, and matches every entered word. Invalid stored tool keys are ignored.

`PdfWorkspace.favorite_tools()` returns the pinned `Tool` objects. Its `favorites_changed(list)` signal reports stable keys after a change. Other surfaces should use these APIs instead of deriving tool identity from a translated title.

Behavior checks are in `tests/test_theme_favorites.py`: persistence and legacy fallback; live window/dialog/editor changes; system-following and explicit choices; settings-selector synchronization; mouse activation of stars without launching a tool; featured/favorite ordering; multiword search, category filtering and empty states.
