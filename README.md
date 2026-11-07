# Crash Team Racing Nitro-Fueled: English text patch

This community patch replaces Russian text in the English locale of the **macOS NXNative/DMROMFS1 build** of *Crash Team Racing Nitro-Fueled*. It currently contains 2,185 reviewed source-to-English text mappings, including menu labels, track and cup names, loading tips, race text, achievements, and customization names. **It is a partial translation**; some Russian text remains.

The repository contains text and a Python installer only. It does not contain the game or a game archive. You need your own installed copy of the compatible macOS app. This patch is not for the console releases or a different game image format.

## Install

1. **Quit the game completely.** Check that the app is no longer running.
2. Download this repository with **Code → Download ZIP** and unzip it, or clone it:

   ```sh
   git clone https://github.com/namak1/Crash-Translate.git
   cd Crash-Translate
   ```

3. From the folder containing `install.py` and `translations.json`, preview the changes:

   ```sh
   python3 install.py
   ```

4. If the preview succeeds, install:

   ```sh
   python3 install.py --apply
   ```

5. Open the game. If it was open during installation, quit and reopen it to reload the text.

The default location is `/Applications/Crash™ Team Racing Nitro-Fueled.app/Contents/Resources/romfs.img`. If your app is elsewhere, pass its path:

```sh
python3 install.py --image "/path/to/Crash™ Team Racing Nitro-Fueled.app" --apply
```

Use Python 3 on macOS; no third-party packages are required. If macOS reports permission denied, put the game app in a location you can write to and use `--image` with that path. Avoid running the installer with `sudo`, because its rollback journal is saved under the current user's home folder.

## Restore the previous text

Quit the game, then run:

```sh
python3 install.py --restore
```

Use the same `--image` path you used during installation. The installer stores a **small rollback journal** in `~/Library/Application Support/Crash-Translate/`; it records only the edited text regions. Restore returns those regions to **their exact state immediately before this installer ran**. If you had already made other translations or changes, it does not undo those earlier changes. A clean reinstall of the game is another way to restore the original game data.

## How it works

The installer validates the DMROMFS1 image and its IGA/IGZ English locale tables, checks that each translated string table fits inside its existing space, and then writes only those text regions in place. It verifies every write. It does not extract, upload, or duplicate the multi-gigabyte game image. The preview performs all size checks without changing the game.

If a game update replaces `romfs.img`, run the preview again before applying the patch. Different builds may have different locale layouts or capacity. A successful install on the tested build does not guarantee compatibility with every build.

The English text is in [`translations.json`](translations.json). Corrections are welcome; preserve placeholders such as `{0}`, `TRACKNAME_A`, and `CHARACTERNAME_A` when editing translations.
