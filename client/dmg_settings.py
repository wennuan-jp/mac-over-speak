import os.path

# The path to the application bundle
filename = 'dist/MacOverSpeak.app'
application = filename
appname = os.path.basename(application)

files = [ application ]
symlinks = { 'Applications': '/Applications' }

# Window settings
window_rect = ((100, 100), (600, 400))
background = 'builtin-arrow'
icon_size = 128

# Set DMG title
title = 'Mac Over Speak Installer'
