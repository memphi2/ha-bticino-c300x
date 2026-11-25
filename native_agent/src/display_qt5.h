#ifndef C300X_DISPLAY_QT5_H
#define C300X_DISPLAY_QT5_H

/* Firmware 3.0.x keeps its display files as Qt resources inside the BtClass
 * program. "extract DIR REL..." writes the named files of a known BtClass into
 * DIR; "pack ROOT OUT REL..." writes the files ROOT/REL as a Qt resource file
 * under skins/default, which qrc_overlay.so registers ahead of the program's
 * own; "overlay PATH" writes that preload library, carried in the agent, to
 * PATH. Prints one JSON line; the Display patch script calls it. */
int c300x_display_qt5_cli(int argc, char **argv);

#endif
