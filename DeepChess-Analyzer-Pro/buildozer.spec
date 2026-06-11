[app]

# (str) Title of your application
title = DeepChess Analyzer Pro

# (str) Package name
package.name = deepchess

# (str) Package domain (needed for android/ios packaging)
package.domain = org.deepchess

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,jpeg,kv,atlas,ttf,otf,wav,ogg,json

# (list) Source files to exclude
source.exclude_exts = spec,md

# (list) List of directory to exclude (let empty to not exclude anything)
source.exclude_dirs = tests, bin, .git, __pycache__, .buildozer

# (str) Application versioning
version = 1.0

# (list) Application requirements
# python-chess is published on PyPI as "chess".
# arabic_reshaper / python-bidi are pure-Python and install via pip.
requirements = python3,kivy,chess,arabic_reshaper,python-bidi,pillow

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = sensorLandscape

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (str) Presplash / icon (drop your own files here if desired)
# presplash.filename = %(source.dir)s/assets/presplash.png
# icon.filename = %(source.dir)s/assets/icon.png

#
# Android specific
#

# (list) Permissions
# Needed for exporting PGN files / saving board screenshots to storage.
android.permissions = WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK / AAB will support.
android.minapi = 21

# (str) Android NDK version to use
# android.ndk = 25b

# (str) The Android arch to build for
android.archs = arm64-v8a, armeabi-v7a

# (bool) enables Android auto backup feature (Android API >= 23)
android.allow_backup = True

#
# iOS specific
#

# (str) Name of the certificate to use for signing the debug version
# ios.codesign.debug = "iPhone Developer: ..."


[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
