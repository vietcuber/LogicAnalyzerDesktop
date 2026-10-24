# Logic Analyzer Desktop

Capture files use the `.la` JSON format. Version 2 stores the capture frequency
and samples together with each channel's name, visibility, display order, and
the vertical channel spacing. Opening a version 2 file restores that layout.
Version 1 files remain supported; they open using the current channel layout.

The saved display layout does not change sample data or the physical mapping:
bit 0 is CH0 through bit 7 as CH7. Channel names and order affect presentation
only.